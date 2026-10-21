/*
 * vdl2-sniffer: VDL Mode 2 receiver
 *
 * Copyright (c) 2026 Mike Brown
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * IQ in (file or stdin), AVLC frames out: dumpvdl2-style JSON for feeds,
 * and a JSONL archive that observatory/rollup.py reads. The receiver is
 * our clean-room VDL2 decoder, written for CyberEther (third_party/vdl2, MIT), one instance per channel, each on its own
 * thread per block: the receiver's cost is per channel.
 *
 * The receiver wants 1.05 MS/s around a centre 12.5 kHz-aligned with the
 * channels. Input at that rate and on such a centre goes in as it is;
 * anything else is mixed and resampled first.
 */

#include "third_party/vdl2/vdl2_acars.hh"
#include "third_party/vdl2/vdl2_decoder.hh"
#include "vdl2_xid.hh"

#include "acars_position.h"
#include "waypoint_db.h"

#include <arpa/inet.h>
#include <fcntl.h>
#include <netdb.h>
#include <signal.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>

#ifdef HAVE_RTLSDR
#include <rtl-sdr.h>
#endif

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <cmath>
#include <complex>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <future>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <thread>
#include <vector>

#ifndef VDL2_SNIFFER_VERSION
#define VDL2_SNIFFER_VERSION "0.1"
#endif

namespace V = Jetstream::Vdl2Receiver;
using cf = std::complex<float>;

// The fix list: beside the binary once installed (PREFIX/bin and
// PREFIX/share/vdl2-sniffer, which an AppImage keeps too), else the
// source tree's data/ for a build that was never installed.
static std::string defaultWaypoints() {
    char exe[4096];
    ssize_t n = readlink("/proc/self/exe", exe, sizeof exe - 1);
    if (n > 0) {
        exe[n] = '\0';
        std::string dir(exe);
        dir.erase(dir.rfind('/'));
        std::string p = dir + "/../share/vdl2-sniffer/waypoints.csv";
        if (access(p.c_str(), R_OK) == 0) return p;
    }
    return VDL2_DATA_DIR "/waypoints.csv";
}

static volatile sig_atomic_t stopRequested = 0;
static void onSignal(int) { stopRequested = 1; }

/* ---------- channel plans ---------- */

// US: the eight channels heard at Chalmette and in North Dakota.
// Europe: the common signalling channel and the usual regional ones.
static const std::map<std::string, std::vector<double>> kPlans = {
    {"us", {136650000, 136700000, 136725000, 136775000, 136800000, 136825000, 136875000, 136975000}},
    {"eu", {136725000, 136775000, 136825000, 136875000, 136975000}},
};

/* ---------- options ---------- */

struct Options {
    std::string input = "-";
    std::string rtlsdr;              // device index or serial; "" = not an RTL-SDR
    std::string gain = "auto";       // tuner gain in dB, or auto
    int ppm = 0;
    bool biasTee = false;
    std::string format;              // cu8 | cs8 | ci16 | cf32; empty = from the extension
    double rate = V::Decoder::RequiredSampleRate;
    double centre = 0;               // 0 = the plan's own centre
    std::vector<double> channels;
    std::string start;               // capture start for files
    std::string json;                // "" off, "-" stdout, else a file
    std::string udp;                 // host:port
    std::string stationId;
    std::string archive;             // "" off
    std::string waypoints;           // fix list; "" = the installed one, "none" = off
    double maxSeconds = 0;
    bool printCentre = false;
    bool raw = false;                // AVLC octets in the JSON, for A/B checks
    bool quiet = false;
};

static void usage(FILE* out) {
    fprintf(out,
        "usage: vdl2-sniffer [options]\n"
        "  -r, --input FILE      IQ file, or - for stdin (default -)\n"
        "      --rtlsdr [DEV]    read an RTL-SDR directly: device index or serial (default 0)\n"
        "      --gain DB         RTL-SDR tuner gain in dB, or auto (default auto)\n"
        "      --ppm N           RTL-SDR frequency correction in ppm (default 0)\n"
        "      --bias-tee        RTL-SDR: power the antenna port (off by default)\n"
        "      --format F        cu8 | cs8 | ci16 | cf32 (default: from extension, cu8 on stdin)\n"
        "  -s, --rate HZ         input sample rate (default 1050000)\n"
        "  -c, --centre HZ       input centre frequency (default: the channel plan's centre)\n"
        "      --plan us|eu      channel plan (default us)\n"
        "      --channels LIST   channels, comma-separated, MHz or Hz (overrides --plan)\n"
        "      --print-centre    print the centre to tune the receiver to, and exit\n"
        "      --start TIME      capture start: epoch seconds, or YYYY-MM-DD HH:MM:SS local,\n"
        "                        or YYYY-MM-DDTHH:MM:SSZ (default: now on stdin,\n"
        "                        file mtime minus its length for a file)\n"
        "      --json [FILE]     dumpvdl2-style JSON per frame to FILE (default stdout)\n"
        "      --udp HOST:PORT   the same JSON over UDP\n"
        "      --station-id ID   station id in the JSON\n"
        "      --raw             add the AVLC octets (hex) to the JSON\n"
        "      --archive [DIR]   JSONL archive for the Observatory (default ./archive)\n"
        "      --max-seconds S   stop after S seconds of input\n"
        "      --waypoints FILE  fix list for positions from ACARS text (IDENT,LAT,LON;\n"
        "                        default: the installed waypoints.csv; none = off)\n"
        "  -q, --quiet           no per-frame summary on stdout\n");
}

static std::vector<double> parseChannels(const std::string& s) {
    std::vector<double> v;
    size_t p = 0;
    while (p < s.size()) {
        size_t q = s.find(',', p);
        if (q == std::string::npos) q = s.size();
        if (q > p) {
            double x = atof(s.substr(p, q - p).c_str());
            if (x > 0 && x < 1e4) x *= 1e6;   // MHz
            v.push_back(std::round(x));
        }
        p = q + 1;
    }
    return v;
}

static bool parseOptions(int argc, char** argv, Options& o) {
    std::string plan = "us";
    for (int i = 1; i < argc; i++) {
        std::string k = argv[i], val;
        bool hasVal = false;
        if (k.rfind("--", 0) == 0) {
            const size_t eq = k.find('=');
            if (eq != std::string::npos) { val = k.substr(eq + 1); k = k.substr(0, eq); hasVal = true; }
        }
        auto need = [&]() -> bool {
            if (hasVal) return true;
            if (i + 1 >= argc) { fprintf(stderr, "vdl2-sniffer: %s needs a value\n", k.c_str()); return false; }
            val = argv[++i];
            return true;
        };
        // an optional value: taken only when the next argument is not an option
        auto maybe = [&](const char* dflt) {
            if (hasVal) return;
            if (i + 1 < argc && argv[i + 1][0] != '-') val = argv[++i];
            else val = dflt;
        };
        if (k == "-h" || k == "--help") { usage(stdout); exit(0); }
        else if (k == "-r" || k == "--input") { if (!need()) return false; o.input = val; }
        else if (k == "--rtlsdr") { maybe("0"); o.rtlsdr = val; }
        else if (k == "--gain") { if (!need()) return false; o.gain = val; }
        else if (k == "--ppm") { if (!need()) return false; o.ppm = atoi(val.c_str()); }
        else if (k == "--bias-tee") o.biasTee = true;
        else if (k == "--format") { if (!need()) return false; o.format = val; }
        else if (k == "-s" || k == "--rate") { if (!need()) return false; o.rate = atof(val.c_str()); }
        else if (k == "-c" || k == "--centre" || k == "--center") { if (!need()) return false; o.centre = atof(val.c_str()); }
        else if (k == "--plan") { if (!need()) return false; plan = val; }
        else if (k == "--channels") { if (!need()) return false; o.channels = parseChannels(val); }
        else if (k == "--print-centre" || k == "--print-center") o.printCentre = true;
        else if (k == "--start") { if (!need()) return false; o.start = val; }
        else if (k == "--json") { maybe("-"); o.json = val; }
        else if (k == "--udp") { if (!need()) return false; o.udp = val; }
        else if (k == "--raw") o.raw = true;
        else if (k == "--station-id") { if (!need()) return false; o.stationId = val; }
        else if (k == "--archive") { maybe("archive"); o.archive = val; }
        else if (k == "--max-seconds") { if (!need()) return false; o.maxSeconds = atof(val.c_str()); }
        else if (k == "--waypoints") { if (!need()) return false; o.waypoints = val; }
        else if (k == "-q" || k == "--quiet") o.quiet = true;
        else { fprintf(stderr, "vdl2-sniffer: unknown option %s\n", k.c_str()); usage(stderr); return false; }
    }
    if (o.channels.empty()) {
        auto it = kPlans.find(plan);
        if (it == kPlans.end()) { fprintf(stderr, "vdl2-sniffer: unknown plan %s (us, eu)\n", plan.c_str()); return false; }
        o.channels = it->second;
    }
    std::sort(o.channels.begin(), o.channels.end());
    o.channels.erase(std::unique(o.channels.begin(), o.channels.end()), o.channels.end());
    if (!o.rtlsdr.empty()) {
#ifndef HAVE_RTLSDR
        fprintf(stderr, "vdl2-sniffer: built without librtlsdr, so --rtlsdr is not available\n");
        return false;
#endif
        if (!o.format.empty() && o.format != "cu8") {
            fprintf(stderr, "vdl2-sniffer: an RTL-SDR delivers cu8\n");
            return false;
        }
        o.format = "cu8";
    }
    if (o.format.empty()) {
        auto ends = [&](const char* e) {
            const size_t n = strlen(e);
            return o.input.size() >= n && o.input.compare(o.input.size() - n, n, e) == 0;
        };
        o.format = ends(".cf32") || ends(".fc32") ? "cf32"
                 : ends(".ci16") || ends(".cs16") ? "ci16"
                 : ends(".cs8") || ends(".ci8") ? "cs8" : "cu8";
    }
    if (o.format != "cu8" && o.format != "cs8" && o.format != "ci16" && o.format != "cf32") {
        fprintf(stderr, "vdl2-sniffer: unknown format %s\n", o.format.c_str());
        return false;
    }
    if (!(o.rate > 0)) { fprintf(stderr, "vdl2-sniffer: bad sample rate\n"); return false; }
    return true;
}

/* ---------- time ---------- */

static double parseStart(const std::string& s) {
    if (s.find_first_not_of("0123456789.") == std::string::npos) return atof(s.c_str());
    struct tm tm{};
    const char* end = strptime(s.c_str(), "%Y-%m-%dT%H:%M:%S", &tm);
    if (end && (*end == 'Z' || *end == 'z')) return (double)timegm(&tm);
    tm = {};
    end = strptime(s.c_str(), "%Y-%m-%d %H:%M:%S", &tm);
    if (end) { tm.tm_isdst = -1; return (double)mktime(&tm); }
    return -1;
}

static double nowSeconds() {
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

/* ---------- JSON ---------- */

static std::string jsonQuote(const std::string& s) {
    std::string o = "\"";
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') { o += '\\'; o += (char)c; }
        else if (c < 0x20 || c == 0x7f) { char b[8]; snprintf(b, sizeof b, "\\u%04x", c); o += b; }
        else o += (char)c;
    }
    return o + "\"";
}

static std::string hex6(uint32_t a) {
    char b[8];
    snprintf(b, sizeof b, "%06X", a & 0xFFFFFF);
    return b;
}

/* ---------- AVLC ---------- */

// The 28 address bits as the decoder reads them; bit 27 is the flag above
// the type. On the source address it is command/response; on the
// destination it is the aircraft's air/ground status. Both read off the
// recorded fixtures against the oracle's text.
static uint32_t addressBits(const uint8_t* p) {
    uint32_t n = 0;
    for (int i = 0; i < 4; ++i) {
        const int v = p[i] >> 1;
        for (int k = 0; k < 7; ++k) n = (n << 1) | ((v >> k) & 1);
    }
    return n;
}

static const char* kindName(int kind) {
    switch (kind) {
        case 1: return "Aircraft";
        case 4: case 5: return "Ground station";
        case 7: return "All stations";
        default: return "Reserved";
    }
}

struct Control {
    std::string type;    // I, RR, RNR, REJ, SREJ, UI, XID, ...
    char frameType;      // I, S, U
    int sseq = -1, rseq = -1;
    bool pf = false;
};

static Control decodeControl(uint8_t c) {
    Control k;
    k.pf = (c >> 4) & 1;
    if ((c & 0x01) == 0) {
        k.type = "I"; k.frameType = 'I';
        k.sseq = (c >> 1) & 7; k.rseq = (c >> 5) & 7;
        return k;
    }
    if ((c & 0x03) == 0x01) {
        static const char* s[] = {"RR", "RNR", "REJ", "SREJ"};
        k.type = s[(c >> 2) & 3]; k.frameType = 'S';
        k.rseq = (c >> 5) & 7;
        return k;
    }
    k.frameType = 'U';
    switch (c & ~0x10) {
        case 0x03: k.type = "UI"; break;
        case 0x0F: k.type = "DM"; break;
        case 0x43: k.type = "DISC"; break;
        case 0x63: k.type = "UA"; break;
        case 0x87: k.type = "FRMR"; break;
        case 0xAF: k.type = "XID"; break;
        case 0xE3: k.type = "TEST"; break;
        default: { char b[8]; snprintf(b, sizeof b, "U%02X", c); k.type = b; }
    }
    return k;
}

static const char* sName(const std::string& t) {
    if (t == "RR") return "Receive Ready";
    if (t == "RNR") return "Receive not Ready";
    if (t == "REJ") return "Reject";
    if (t == "SREJ") return "Selective Reject";
    return t.c_str();
}

static std::string trimPad(const std::string& s, char pad) {
    const size_t a = s.find_first_not_of(pad), b = s.find_last_not_of(pad);
    return a == std::string::npos ? "" : s.substr(a, b - a + 1);
}

/* ---------- resampler ---------- */

// Mix by -shift Hz and resample from inRate to outRate with a windowed-sinc
// interpolator (Blackman, 1024 phases), centred on each output instant: no
// delay, so output sample j is the input at j / outRate. From
// iridium-analyzer's vdl2dec.
class Resampler {
public:
    Resampler(double inRate, double outRate, double shiftHz) {
        step_ = inRate / outRate;
        const double fc = 0.45 * std::min(1.0, outRate / inRate);
        half_ = (int)std::ceil(16.0 / (2.0 * fc));
        table_.resize((size_t)(2 * half_ + 1) * kPhases + 1);
        for (size_t i = 0; i < table_.size(); i++) {
            const double x = (double)i / kPhases - half_;
            const double s = x == 0 ? 2 * fc : std::sin(2 * M_PI * fc * x) / (M_PI * x);
            const double w = 0.42 + 0.5 * std::cos(M_PI * x / (half_ + 1)) + 0.08 * std::cos(2 * M_PI * x / (half_ + 1));
            table_[i] = (float)(s * w);
        }
        rot_ = std::polar(1.0, -2 * M_PI * shiftHz / inRate);
    }
    void process(const cf* x, size_t n, std::vector<cf>& out) {
        for (size_t i = 0; i < n; i++) {
            buf_.push_back(cf((float)(x[i].real() * ph_.real() - x[i].imag() * ph_.imag()),
                              (float)(x[i].real() * ph_.imag() + x[i].imag() * ph_.real())));
            ph_ *= rot_;
            if ((++count_ & 1023) == 0) ph_ /= std::abs(ph_);
        }
        while (next_ + half_ + 1 < (double)(base_ + buf_.size())) {
            const double rel = next_ - base_;
            const long c = (long)std::floor(rel);
            const double frac = rel - c;
            cf acc{0, 0};
            for (int k = -half_; k <= half_; k++) {
                const long idx = c + k;
                if (idx < 0) continue;
                const double x = (frac - k + half_) * kPhases;
                const size_t ti = (size_t)x;
                const float w = table_[ti] + (table_[ti + 1] - table_[ti]) * (float)(x - ti);
                acc += buf_[(size_t)idx] * w;
            }
            out.push_back(acc);
            next_ += step_;
        }
        const long keepFrom = (long)std::floor(next_ - base_) - half_ - 1;
        if (keepFrom > 4096) { buf_.erase(buf_.begin(), buf_.begin() + keepFrom); base_ += keepFrom; }
    }
private:
    static constexpr int kPhases = 1024;
    double step_;
    int half_;
    std::vector<float> table_;
    std::complex<double> ph_{1, 0}, rot_;
    uint64_t count_ = 0;
    std::vector<cf> buf_;
    long base_ = 0;
    double next_ = 0;
};

/* ---------- archive ---------- */

// vdl2-YYYYMMDD.jsonl beside iridium-YYYYMMDD.jsonl, one file per UTC day
// of the event's own time, so a replayed capture lands on its own day.
class Archive {
public:
    bool open(const std::string& dir) {
        if (mkdir(dir.c_str(), 0755) != 0 && errno != EEXIST) {
            fprintf(stderr, "archive: cannot create directory %s: %s\n", dir.c_str(), strerror(errno));
            return false;
        }
        dir_ = dir;
        return true;
    }
    bool enabled() const { return !dir_.empty(); }
    void write(uint64_t tMs, const std::string& line) {
        if (dir_.empty()) return;
        const time_t t = (time_t)(tMs / 1000);
        struct tm g;
        gmtime_r(&t, &g);
        const int day = (g.tm_year + 1900) * 10000 + (g.tm_mon + 1) * 100 + g.tm_mday;
        if (day != day_ || !f_) {
            if (f_) fclose(f_);
            char path[1024];
            snprintf(path, sizeof path, "%s/vdl2-%08d.jsonl", dir_.c_str(), day);
            f_ = fopen(path, "a");
            if (!f_) { fprintf(stderr, "archive: cannot open %s: %s\n", path, strerror(errno)); return; }
            day_ = day;
        }
        fputs(line.c_str(), f_);
        fputc('\n', f_);
        fflush(f_);
    }
    ~Archive() { if (f_) fclose(f_); }
private:
    std::string dir_;
    FILE* f_ = nullptr;
    int day_ = 0;
};

/* ---------- UDP ---------- */

class Udp {
public:
    bool open(const std::string& hostPort) {
        const size_t c = hostPort.rfind(':');
        if (c == std::string::npos) { fprintf(stderr, "vdl2-sniffer: --udp wants HOST:PORT\n"); return false; }
        const std::string host = hostPort.substr(0, c), port = hostPort.substr(c + 1);
        struct addrinfo hints{}, *res = nullptr;
        hints.ai_family = AF_UNSPEC;
        hints.ai_socktype = SOCK_DGRAM;
        if (getaddrinfo(host.c_str(), port.c_str(), &hints, &res) != 0 || !res) {
            fprintf(stderr, "vdl2-sniffer: cannot resolve %s\n", hostPort.c_str());
            return false;
        }
        fd_ = socket(res->ai_family, res->ai_socktype, res->ai_protocol);
        if (fd_ < 0 || connect(fd_, res->ai_addr, res->ai_addrlen) != 0) {
            fprintf(stderr, "vdl2-sniffer: UDP %s: %s\n", hostPort.c_str(), strerror(errno));
            freeaddrinfo(res);
            return false;
        }
        freeaddrinfo(res);
        return true;
    }
    void send(const std::string& s) {
        if (fd_ >= 0) (void)::send(fd_, s.data(), s.size(), 0);
    }
    ~Udp() { if (fd_ >= 0) close(fd_); }
private:
    int fd_ = -1;
};

/* ---------- RTL-SDR ---------- */

#ifdef HAVE_RTLSDR
// A live RTL-SDR. librtlsdr's reader thread hands the samples to the main
// loop through a pipe, so they arrive exactly as stdin would. A buffer the
// pipe has no room for is dropped whole and counted rather than written
// late: blocking in the callback would stall the USB transfers and lose
// samples without a trace. The main loop moves its clock on by what was
// dropped, so frame times stay true.
class RtlInput {
public:
    std::atomic<uint64_t> dropped{0};   // bytes
    std::atomic<bool> failed{false};    // the device stopped without being asked

    FILE* open(const Options& o) {
        if (rtlsdr_get_device_count() == 0) {
            fprintf(stderr, "vdl2-sniffer: no RTL-SDR found\n");
            return nullptr;
        }
        // A short number is an index; anything else is a serial ("00000001").
        int idx = o.rtlsdr.size() <= 2 && o.rtlsdr.find_first_not_of("0123456789") == std::string::npos
                ? atoi(o.rtlsdr.c_str()) : rtlsdr_get_index_by_serial(o.rtlsdr.c_str());
        if (idx < 0 || rtlsdr_open(&dev_, (uint32_t)idx) < 0) {
            fprintf(stderr, "vdl2-sniffer: cannot open RTL-SDR %s\n", o.rtlsdr.c_str());
            dev_ = nullptr;
            return nullptr;
        }
        char vendor[256] = "", product[256] = "", serial[256] = "";
        rtlsdr_get_usb_strings(dev_, vendor, product, serial);
        if (rtlsdr_set_sample_rate(dev_, (uint32_t)std::lround(o.rate)) < 0 ||
            rtlsdr_set_center_freq(dev_, (uint32_t)std::lround(o.centre)) < 0) {
            fprintf(stderr, "vdl2-sniffer: RTL-SDR refused %.0f S/s at %.4f MHz\n", o.rate, o.centre / 1e6);
            return nullptr;
        }
        if (o.ppm) rtlsdr_set_freq_correction(dev_, o.ppm);
        std::string gainText = "auto";
        if (o.gain == "auto") {
            rtlsdr_set_tuner_gain_mode(dev_, 0);
        } else {
            // the nearest gain the tuner has, in tenths of a dB
            int n = rtlsdr_get_tuner_gains(dev_, nullptr);
            std::vector<int> gains(n > 0 ? n : 0);
            if (n > 0) rtlsdr_get_tuner_gains(dev_, gains.data());
            const int want = (int)std::lround(atof(o.gain.c_str()) * 10);
            int best = want;
            for (int g : gains) if (std::abs(g - want) < std::abs(best - want) || best == want) best = g;
            rtlsdr_set_tuner_gain_mode(dev_, 1);
            rtlsdr_set_tuner_gain(dev_, best);
            char b[32];
            snprintf(b, sizeof b, "%.1f dB", best / 10.0);
            gainText = b;
        }
        rtlsdr_set_bias_tee(dev_, o.biasTee ? 1 : 0);
        rtlsdr_reset_buffer(dev_);

        if (pipe2(fd_, O_CLOEXEC) < 0) { perror("pipe"); return nullptr; }
        fcntl(fd_[1], F_SETPIPE_SZ, 1 << 20);   // about half a second at 1.05 MS/s
        pipeSize_ = fcntl(fd_[1], F_GETPIPE_SZ);
        fprintf(stderr, "vdl2-sniffer: RTL-SDR %d (%s %s, serial %s), gain %s, %d ppm, bias tee %s\n",
                idx, vendor, product, serial, gainText.c_str(), o.ppm, o.biasTee ? "on" : "off");
        th_ = std::thread([this] {
            // 32 transfers of 64 KiB (31 ms each)
            int r = rtlsdr_read_async(dev_, &RtlInput::onSamples, this, 32, 65536);
            if (!cancelled_) {
                failed = true;
                fprintf(stderr, "vdl2-sniffer: RTL-SDR stopped (%d)\n", r);
            }
            close(fd_[1]);
            fd_[1] = -1;
        });
        return fdopen(fd_[0], "rb");
    }

    // Stop the device and wait for its thread; the pipe then reads as ended.
    void stop() {
        if (!dev_) return;
        cancelled_ = true;
        rtlsdr_cancel_async(dev_);
        if (th_.joinable()) th_.join();
        rtlsdr_close(dev_);
        dev_ = nullptr;
    }
    ~RtlInput() { stop(); }

private:
    static void onSamples(unsigned char* buf, uint32_t len, void* ctx) {
        auto* self = static_cast<RtlInput*>(ctx);
        if (stopRequested) {
            self->cancelled_ = true;
            rtlsdr_cancel_async(self->dev_);
            return;
        }
        int queued = 0;
        ioctl(self->fd_[1], FIONREAD, &queued);
        if (self->pipeSize_ - queued < (int)len) {
            self->dropped += len;
            return;
        }
        for (uint32_t off = 0; off < len; ) {
            ssize_t w = write(self->fd_[1], buf + off, len - off);
            if (w <= 0) { if (errno == EINTR) continue; return; }
            off += (uint32_t)w;
        }
    }

    rtlsdr_dev_t* dev_ = nullptr;
    int fd_[2] = {-1, -1};
    int pipeSize_ = 0;
    std::thread th_;
    std::atomic<bool> cancelled_{false};
};
#endif

/* ---------- per-channel health ---------- */

struct ChannelStats {
    uint64_t bursts = 0, frames = 0, acars = 0;     // whole run
    uint64_t minuteBursts = 0, minuteFrames = 0;    // current archive minute
    uint64_t lastBursts = 0;                        // decoder counter at the last block
};

/* ---------- the engine ---------- */

int main(int argc, char** argv) {
    Options o;
    if (!parseOptions(argc, argv, o)) return 2;

    const double lo = o.channels.front(), hi = o.channels.back();
    const double planCentre = std::round((lo + hi) / 2 / 12500.0) * 12500.0;
    if (o.printCentre) { printf("%.0f\n", planCentre); return 0; }
    const double decRate = V::Decoder::RequiredSampleRate;
    if (hi - planCentre > 0.4 * decRate || planCentre - lo > 0.4 * decRate) {
        fprintf(stderr, "vdl2-sniffer: channels span %.3f-%.3f MHz, more than 1.05 MS/s holds\n", lo / 1e6, hi / 1e6);
        return 2;
    }
    if (o.centre <= 0) o.centre = planCentre;
    for (double c : o.channels)
        if (c < o.centre - o.rate / 2 + 10e3 || c > o.centre + o.rate / 2 - 10e3) {
            fprintf(stderr, "vdl2-sniffer: %.3f MHz is outside the input band (%.4f MHz +- %.0f kHz)\n",
                    c / 1e6, o.centre / 1e6, o.rate / 2e3);
            return 2;
        }
    // As it is when the rate is right and the centre keeps every mixer exact.
    const bool asIs = std::fabs(o.rate - decRate) < 0.5 && std::fabs(std::remainder(o.centre - lo, 12500.0)) < 0.5;
    const double decCentre = asIs ? o.centre : planCentre;
    std::unique_ptr<Resampler> rs;
    if (!asIs) rs.reset(new Resampler(o.rate, decRate, decCentre - o.centre));

    std::vector<std::unique_ptr<V::Decoder>> decs;
    for (double c : o.channels) decs.emplace_back(new V::Decoder(decCentre, std::vector<double>{c}));
    const V::Decoder& dec0 = *decs.front();   // the same filter delays for all
    std::map<double, size_t> chanIndex;
    for (size_t i = 0; i < o.channels.size(); i++) chanIndex[o.channels[i]] = i;
    std::vector<ChannelStats> stats(o.channels.size());
    V::AcarsReassembler reasm;

    const bool live = !o.rtlsdr.empty();
#ifdef HAVE_RTLSDR
    RtlInput rtl;
#endif
    FILE* in = nullptr;
    if (live) {
#ifdef HAVE_RTLSDR
        if (!(in = rtl.open(o))) return 1;
#endif
    } else {
        in = o.input == "-" ? stdin : fopen(o.input.c_str(), "rb");
        if (!in) { perror(o.input.c_str()); return 1; }
    }
    const size_t bps = o.format == "cf32" ? 8 : o.format == "ci16" ? 4 : 2;

    double t0;
    if (!o.start.empty()) {
        t0 = parseStart(o.start);
        if (t0 < 0) { fprintf(stderr, "vdl2-sniffer: cannot read --start %s\n", o.start.c_str()); return 2; }
    } else if (in != stdin && !live) {
        struct stat st;
        t0 = fstat(fileno(in), &st) == 0 ? st.st_mtime - (double)st.st_size / bps / o.rate : nowSeconds();
    } else {
        t0 = nowSeconds();
    }

    FILE* jsonOut = nullptr;
    if (o.json == "-") jsonOut = stdout;
    else if (!o.json.empty() && !(jsonOut = fopen(o.json.c_str(), "a"))) { perror(o.json.c_str()); return 1; }
    Udp udp;
    if (!o.udp.empty() && !udp.open(o.udp)) return 1;
    Archive archive;
    if (!o.archive.empty() && !archive.open(o.archive)) return 1;
    // Fixes named in ACARS text are a last-resort position, as in
    // iridium-sniffer. Without the list that fallback is simply off.
    if (o.waypoints != "none") {
        const std::string wp = o.waypoints.empty() ? defaultWaypoints() : o.waypoints;
        if (waypoint_db_load(wp.c_str()) < 0 && !o.waypoints.empty()) return 1;
    }
    const bool summary = !o.quiet && jsonOut != stdout;

    struct sigaction sa{};
    sa.sa_handler = onSignal;
    sigaction(SIGINT, &sa, nullptr);
    sigaction(SIGTERM, &sa, nullptr);
    signal(SIGPIPE, SIG_IGN);

    {
        std::string ch;
        for (double c : o.channels) { if (!ch.empty()) ch += ","; ch += std::to_string((long long)c); }
        char b[256];
        snprintf(b, sizeof b, "{\"e\":\"start\",\"t\":%llu,\"sys\":\"vdl2\",\"centre\":%.0f,\"rate\":%.0f,\"ch\":[",
                 (unsigned long long)(t0 * 1000), o.centre, o.rate);
        archive.write((uint64_t)(t0 * 1000), b + ch + "]}");
    }
    fprintf(stderr, "vdl2-sniffer %s: %zu channels %.3f-%.3f MHz, %s at %.0f S/s around %.4f MHz%s, libacars %s\n",
            VDL2_SNIFFER_VERSION, o.channels.size(), lo / 1e6, hi / 1e6, o.format.c_str(), o.rate, o.centre / 1e6,
            asIs ? "" : " (resampled)", V::AcarsContentDecoderAvailable() ? "on" : "off");

    // One archive minute of health counters per channel, flushed when the
    // sample clock leaves the minute.
    int64_t minute = (int64_t)std::floor(t0 / 60);
    auto flushMinute = [&]() {
        std::string ch;
        bool any = false;
        for (size_t i = 0; i < stats.size(); i++) {
            auto& s = stats[i];
            if (!s.minuteBursts && !s.minuteFrames) continue;
            char b[96];
            snprintf(b, sizeof b, "%s\"%lld\":[%llu,%llu]", any ? "," : "", (long long)o.channels[i],
                     (unsigned long long)s.minuteBursts, (unsigned long long)s.minuteFrames);
            ch += b;
            any = true;
            s.minuteBursts = s.minuteFrames = 0;
        }
        char b[64];
        snprintf(b, sizeof b, "{\"e\":\"vmix\",\"t\":%lld,\"ch\":{", (long long)minute * 60000);
        archive.write((uint64_t)minute * 60000, b + ch + "}}");
    };

    uint64_t nFrames = 0, nAcars = 0, nPos = 0;
    // The last position logged per aircraft: a completed multi-block message
    // repeats the one its first block already gave.
    struct LastPos { double lat, lon, t; };
    std::map<uint32_t, LastPos> lastPos;
    auto onFrame = [&](const V::Frame& f) {
        nFrames++;
        const size_t ci = chanIndex.count(f.frequency) ? chanIndex[f.frequency] : 0;
        stats[ci].frames++;
        stats[ci].minuteFrames++;

        const double t = t0 + dec0.ringSampleToInput(f.burstFirst) / decRate;
        const uint64_t tMs = (uint64_t)std::llround(t * 1000);
        const uint64_t tUs = (uint64_t)std::llround(t * 1e6);

        const uint32_t dBits = addressBits(f.avlc.data()), sBits = addressBits(f.avlc.data() + 4);
        const bool response = (sBits >> 27) & 1, onGround = (dBits >> 27) & 1;
        const Control ctl = decodeControl(f.control);
        const bool fromAircraft = f.sourceKind == 1;

        const size_t H = 9, FCS = 2;
        const uint8_t* info = f.avlc.data() + H;
        const size_t ilen = f.avlc.size() > H + FCS ? f.avlc.size() - H - FCS : 0;
        std::optional<V::AcarsMessage> ac;
        std::optional<V::AcarsContent> content;
        if ((ctl.type == "I" || ctl.type == "UI") && ilen) ac = V::ParseAcars(info, ilen);
        if (ac) {
            nAcars++;
            stats[ci].acars++;
            content = V::DecodeAcarsContent(info, ilen, fromAircraft, &reasm, tUs / 1000000);
        }
        std::optional<Vdl2Xid::Xid> xid;
        if (ctl.type == "XID" && ilen) xid = Vdl2Xid::Parse(info, ilen, response, ctl.pf, f.sourceKind);
        std::string label = ac ? ac->label : "";
        for (char& c : label) if (c == 0x7f) c = 'd';

        // The text as libacars reads it (sub-label prefix such as "#M1B" off,
        // a completed multi-block message whole), as iridium-sniffer's archive
        // keeps it; the block's own text without libacars.
        std::string text;
        if (ac) {
            text = content && !content->messageText.empty() ? content->messageText : ac->text;
            if (!content && text.size() > 4 && text[0] == '#') text = text.substr(4);
        }
        // Where the aircraft is, by the rules of
        // acars_aircraft_position (shared with iridium-sniffer): only what the aircraft sent; coordinates
        // in the text, else the fix a POS report names.
        double plat = 0, plon = 0;
        const char* psrc = nullptr;
        if (ac) {
            const int src = acars_aircraft_position(label.c_str(), text.c_str(), fromAircraft, &plat, &plon);
            psrc = src == ACARS_POS_TEXT ? "text" : src == ACARS_POS_FIX ? "fix" : nullptr;
        }

        // dumpvdl2-style JSON
        if (jsonOut || !o.udp.empty()) {
            auto party = [&](uint32_t addr, int kind, bool withStatus) {
                std::string s = "{\"addr\":\"" + hex6(addr) + "\",\"type\":\"" + kindName(kind) + "\"";
                if (withStatus) s += std::string(",\"status\":\"") + (onGround ? "On ground" : "Airborne") + "\"";
                return s + "}";
            };
            char b[512];
            snprintf(b, sizeof b,
                     "{\"vdl2\":{\"app\":{\"name\":\"vdl2-sniffer\",\"ver\":\"%s\"},%s"
                     "\"t\":{\"sec\":%llu,\"usec\":%llu},\"freq\":%.0f,\"idx\":%zu,\"burst_len_octets\":%zu,"
                     "\"octets_corrected_by_fec\":%d,\"snr\":%.1f,\"avlc\":{",
                     VDL2_SNIFFER_VERSION,
                     o.stationId.empty() ? "" : ("\"station\":" + jsonQuote(o.stationId) + ",").c_str(),
                     (unsigned long long)(tUs / 1000000), (unsigned long long)(tUs % 1000000), f.frequency, ci,
                     f.avlc.size(), f.errorsCorrected, f.snr);
            std::string j = b;
            j += "\"src\":" + party(f.source, f.sourceKind, fromAircraft);
            j += ",\"dst\":" + party(f.dest, f.destKind, f.destKind == 1);
            j += std::string(",\"cr\":\"") + (response ? "Response" : "Command") + "\"";
            j += std::string(",\"frame_type\":\"") + ctl.frameType + "\"";
            if (ctl.frameType == 'I') {
                snprintf(b, sizeof b, ",\"rseq\":%d,\"sseq\":%d,\"poll\":%s", ctl.rseq, ctl.sseq, ctl.pf ? "true" : "false");
                j += b;
            } else if (ctl.frameType == 'S') {
                snprintf(b, sizeof b, ",\"cmd\":\"%s\",\"pf\":%s,\"rseq\":%d", sName(ctl.type), ctl.pf ? "true" : "false", ctl.rseq);
                j += b;
            } else {
                j += ",\"cmd\":\"" + ctl.type + "\",\"pf\":" + (ctl.pf ? "true" : "false");
            }
            if (ac) {
                // libacars's own ACARS object when there is one (what dumpvdl2
                // prints); otherwise the same fields from the block itself.
                const std::string pre = "{\"acars\":";
                if (content && content->treeJson && content->treeJson->rfind(pre, 0) == 0 && content->treeJson->back() == '}') {
                    j += ",\"acars\":" + content->treeJson->substr(pre.size(), content->treeJson->size() - pre.size() - 1);
                } else {
                    const std::string num = ac->messageNumber;
                    j += ",\"acars\":{\"err\":false,\"more\":" + std::string(ac->more ? "true" : "false") +
                         ",\"reg\":" + jsonQuote(ac->registration) +
                         ",\"mode\":" + jsonQuote(std::string(1, ac->mode)) +
                         ",\"label\":" + jsonQuote(label) +
                         ",\"blk_id\":" + jsonQuote(std::string(1, ac->blockId)) +
                         ",\"ack\":" + jsonQuote(std::string(1, ac->acknowledge == 0x15 ? '!' : ac->acknowledge));
                    if (fromAircraft) {
                        j += ",\"flight\":" + jsonQuote(trimPad(ac->flight, ' '));
                        j += ",\"msg_num\":" + jsonQuote(num.size() == 4 ? num.substr(0, 3) : num);
                        j += ",\"msg_num_seq\":" + jsonQuote(num.size() == 4 ? num.substr(3) : "");
                    }
                    j += ",\"msg_text\":" + jsonQuote(ac->text) + "}";
                }
            }
            if (xid) j += ",\"xid\":" + Vdl2Xid::ToJson(*xid);
            if (psrc) {
                snprintf(b, sizeof b, ",\"ac_pos\":{\"lat\":%.4f,\"lon\":%.4f,\"src\":\"%s\"}", plat, plon, psrc);
                j += b;
            }
            j += "}";
            if (o.raw) {
                j += ",\"raw\":\"";
                for (uint8_t x : f.avlc) { char h[3]; snprintf(h, sizeof h, "%02x", x); j += h; }
                j += "\"";
            }
            j += "}}";
            if (jsonOut) { fputs(j.c_str(), jsonOut); fputc('\n', jsonOut); fflush(jsonOut); }
            udp.send(j + "\n");
        }

        // archive
        if (archive.enabled()) {
            char b[384];
            snprintf(b, sizeof b,
                     "{\"e\":\"vframe\",\"t\":%llu,\"freq\":%.0f,\"snr\":%.1f,\"src\":\"%s\",\"sk\":%d,"
                     "\"dst\":\"%s\",\"dk\":%d,\"cr\":%d,\"ctl\":\"%s\",\"len\":%zu,\"rs\":%d,\"er\":%d}",
                     (unsigned long long)tMs, f.frequency, f.snr, hex6(f.source).c_str(), f.sourceKind,
                     hex6(f.dest).c_str(), f.destKind, response ? 1 : 0, ac ? "ACARS" : ctl.type.c_str(),
                     f.avlc.size(), f.errorsCorrected, f.erasuresUsed);
            archive.write(tMs, b);
            // A position from ACARS text, logged per frame: a multi-block
            // message whose later blocks never arrive is never logged whole,
            // but its first block's position is still good.
            if (psrc) {
                const uint32_t aircraft = fromAircraft ? f.source : f.dest;
                const uint32_t station = fromAircraft ? f.dest : f.source;
                auto it = lastPos.find(aircraft);
                const bool repeat = it != lastPos.end() && it->second.lat == plat &&
                                    it->second.lon == plon && t - it->second.t < 60;
                if (!repeat) {
                    snprintf(b, sizeof b, "{\"e\":\"vpos\",\"t\":%llu,\"icao\":\"%s\",\"gs\":\"%s\","
                             "\"lat\":%.4f,\"lon\":%.4f,\"src\":\"%s\"}",
                             (unsigned long long)tMs, hex6(aircraft).c_str(), hex6(station).c_str(),
                             plat, plon, psrc);
                    archive.write(tMs, b);
                    nPos++;
                }
                lastPos[aircraft] = {plat, plon, t};
            }
            if (xid) {
                snprintf(b, sizeof b, "{\"e\":\"xid\",\"t\":%llu,\"freq\":%.0f,\"src\":\"%s\",\"sk\":%d,"
                         "\"dst\":\"%s\",\"dk\":%d,\"cr\":%d,\"x\":",
                         (unsigned long long)tMs, f.frequency, hex6(f.source).c_str(), f.sourceKind,
                         hex6(f.dest).c_str(), f.destKind, response ? 1 : 0);
                archive.write(tMs, b + Vdl2Xid::ToJson(*xid) + "}");
            }
            // One message per ACARS message: the blocks of a multi-block
            // message are logged once, whole, when libacars completes it.
            const auto rsm = content ? content->reassembly : V::AcarsContent::Reassembly::None;
            if (ac && rsm != V::AcarsContent::Reassembly::Partial && rsm != V::AcarsContent::Reassembly::Repeat) {
                snprintf(b, sizeof b, "{\"e\":\"acars\",\"t\":%llu,\"sys\":\"vdl2\",\"dir\":\"%s\",\"freq\":%.0f,",
                         (unsigned long long)tMs, fromAircraft ? "UL" : "DL", f.frequency);
                std::string line = b;
                line += "\"src\":\"" + hex6(f.source) + "\",\"dst\":\"" + hex6(f.dest) + "\"";
                line += ",\"reg\":" + jsonQuote(trimPad(ac->registration, '.'));
                line += ",\"flt\":" + jsonQuote(trimPad(ac->flight, ' '));
                line += ",\"lbl\":" + jsonQuote(label);
                line += ",\"txt\":" + jsonQuote(text);
                if (psrc) {
                    snprintf(b, sizeof b, ",\"lat\":%.4f,\"lon\":%.4f,\"psrc\":\"%s\"", plat, plon, psrc);
                    line += b;
                }
                if (content && content->treeJson) line += ",\"dec\":" + *content->treeJson;
                archive.write(tMs, line + "}");
            }
        }

        if (summary) {
            const time_t tt = (time_t)(tUs / 1000000);
            struct tm g;
            gmtime_r(&tt, &g);
            char ts[32];
            strftime(ts, sizeof ts, "%H:%M:%S", &g);
            std::string what = ctl.type;
            if (ac) {
                what = "ACARS " + trimPad(ac->registration, '.') + " " + trimPad(ac->flight, ' ') + " " + label + " ";
                for (char c : text.substr(0, 80)) what += (c == '\r' || c == '\n') ? ' ' : c;
                if (psrc) {
                    char b[64];
                    snprintf(b, sizeof b, " [at %.2f %.2f, %s]", plat, plon, psrc);
                    what += b;
                }
            } else if (xid) {
                what = "XID " + (xid->type.empty() ? std::string(response ? "response" : "command") : xid->type);
                if (!xid->destinationAirport.empty()) what += " to " + xid->destinationAirport;
                if (xid->aircraftLocation) {
                    char b[64];
                    snprintf(b, sizeof b, " at %.1f %.1f", xid->aircraftLocation->lat, xid->aircraftLocation->lon);
                    what += b;
                    if (xid->aircraftLocation->altFt) what += " " + std::to_string(*xid->aircraftLocation->altFt) + " ft";
                }
            }
            printf("%s %.3f %+5.1f dB %s%s -> %s%s %s%s\n", ts, f.frequency / 1e6, f.snr,
                   hex6(f.source).c_str(), f.sourceKind == 1 ? "" : "(GS)",
                   hex6(f.dest).c_str(), f.destKind == 1 ? "" : "(GS)", what.c_str(),
                   f.errorsCorrected > 0 ? (" RS " + std::to_string(f.errorsCorrected)).c_str() : "");
            fflush(stdout);
        }
    };

    const size_t chunk = 65536;
    std::vector<uint8_t> raw(chunk * bps);
    std::vector<cf> iq(chunk), resampled;
    const uint64_t maxIn = o.maxSeconds > 0 ? (uint64_t)(o.maxSeconds * o.rate) : UINT64_MAX;
    uint64_t inCount = 0;
    size_t carry = 0;   // bytes of a partial sample left from the last read
    uint64_t droppedSamples = 0, minuteDropped = 0;
    double lastDropReport = 0;
    if (live) setvbuf(stdout, nullptr, _IOLBF, 0);

    while (!stopRequested) {
        size_t want = chunk;
        if (inCount + want > maxIn) want = (size_t)(maxIn - inCount);
        if (!want) break;
        const size_t nread = fread(raw.data() + carry, 1, want * bps - carry, in) + carry;
        const size_t k = nread / bps;
        carry = nread - k * bps;
        if (!k) { if (feof(in) || ferror(in)) break; continue; }
        for (size_t i = 0; i < k; i++) {
            const uint8_t* p = &raw[bps * i];
            if (bps == 8) { float r, q; memcpy(&r, p, 4); memcpy(&q, p + 4, 4); iq[i] = {r, q}; }
            else if (bps == 4) { int16_t r, q; memcpy(&r, p, 2); memcpy(&q, p + 2, 2); iq[i] = {r / 32768.f, q / 32768.f}; }
            else if (o.format == "cs8") iq[i] = {(int8_t)p[0] / 128.f, (int8_t)p[1] / 128.f};
            else iq[i] = {(p[0] - 127.5f) / 127.5f, (p[1] - 127.5f) / 127.5f};
        }
        if (carry) memmove(raw.data(), raw.data() + k * bps, carry);
        inCount += k;
#ifdef HAVE_RTLSDR
        // Samples the decoder had no room for: the clock moves on past them.
        if (live) {
            if (const uint64_t d = rtl.dropped.exchange(0)) {
                t0 += d / (double)bps / o.rate;
                droppedSamples += d / bps;
                minuteDropped += d / bps;
            }
            const double now = nowSeconds();
            if (minuteDropped && now - lastDropReport >= 60) {
                fprintf(stderr, "vdl2-sniffer: %.2f s of samples dropped in the last minute (decoder behind)\n",
                        minuteDropped / o.rate);
                minuteDropped = 0;
                lastDropReport = now;
            }
        }
#endif

        const cf* feed = iq.data();
        size_t nfeed = k;
        if (rs) { resampled.clear(); rs->process(iq.data(), k, resampled); feed = resampled.data(); nfeed = resampled.size(); }
        if (!nfeed) continue;

        // every channel's receiver on the block at once; their frames, then in burst order
        std::vector<std::vector<V::Frame>> got(decs.size());
        std::vector<std::future<void>> work;
        for (size_t i = 0; i < decs.size(); i++)
            work.push_back(std::async(std::launch::async, [&, i] {
                decs[i]->process(feed, nfeed, [&, i](const V::Frame& f) { got[i].push_back(f); });
            }));
        for (auto& w : work) w.get();
        std::vector<const V::Frame*> all;
        for (auto& g : got) for (auto& f : g) all.push_back(&f);
        std::stable_sort(all.begin(), all.end(), [](const V::Frame* x, const V::Frame* y) { return x->burstFirst < y->burstFirst; });

        // Frames belong to the minute their burst started in; bursts are
        // counted at the end of the block that finished them.
        for (const V::Frame* f : all) {
            const int64_t m = (int64_t)std::floor((t0 + dec0.ringSampleToInput(f->burstFirst) / decRate) / 60);
            if (m > minute) { flushMinute(); minute = m; }
            onFrame(*f);
        }
        const int64_t m = (int64_t)std::floor((t0 + inCount / o.rate) / 60);
        if (m > minute) { flushMinute(); minute = m; }
        for (size_t i = 0; i < decs.size(); i++) {
            const uint64_t b = decs[i]->bursts();
            stats[i].minuteBursts += b - stats[i].lastBursts;
            stats[i].bursts += b - stats[i].lastBursts;
            stats[i].lastBursts = b;
        }
    }
    flushMinute();

    bool deviceFailed = false;
#ifdef HAVE_RTLSDR
    if (live) {
        rtl.stop();
        deviceFailed = rtl.failed;
    }
#endif
    if (jsonOut && jsonOut != stdout) fclose(jsonOut);
    if (in != stdin) fclose(in);

    uint64_t nBursts = 0;
    for (auto& s : stats) nBursts += s.bursts;
    fprintf(stderr, "vdl2-sniffer: %.0f s of input, %llu frames (%llu ACARS) from %llu bursts, "
            "%llu ACARS positions\n",
            inCount / o.rate, (unsigned long long)nFrames, (unsigned long long)nAcars, (unsigned long long)nBursts,
            (unsigned long long)nPos);
    for (size_t i = 0; i < stats.size(); i++)
        if (stats[i].bursts || stats[i].frames)
            fprintf(stderr, "  %.3f MHz: %6llu bursts %5llu frames %5llu ACARS\n", o.channels[i] / 1e6,
                    (unsigned long long)stats[i].bursts, (unsigned long long)stats[i].frames,
                    (unsigned long long)stats[i].acars);
    if (droppedSamples)
        fprintf(stderr, "  %.1f s of samples dropped (decoder behind)\n", droppedSamples / o.rate);
    // A receiver that went away is a failure, so a service manager restarts us.
    return deviceFailed ? 1 : 0;
}
