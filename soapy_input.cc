// Copyright (c) 2026 Mike Brown
// SPDX-License-Identifier: GPL-3.0-or-later
#include "soapy_input.hh"

#include "rate_converter.hh"

#include <SoapySDR/Device.hpp>
#include <SoapySDR/Errors.hpp>
#include <SoapySDR/Formats.hpp>
#include <SoapySDR/Logger.hpp>
#include <SoapySDR/Types.hpp>

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <unistd.h>

namespace {

double mono() {
    timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

std::string lower(std::string s) {
    for (auto& c : s) c = (char)std::tolower((unsigned char)c);
    return s;
}

std::string mhz(double hz) {
    char b[32];
    snprintf(b, sizeof b, "%.4g MS/s", hz / 1e6);
    return b;
}

// The rate to run the radio at. 1.05 MS/s itself when the radio has it (no
// conversion beyond a shift); otherwise the lowest it offers that holds the
// channels, preferring a whole multiple of 1.05 MS/s where it can be set
// freely (the converter's last step is then exact). Never much below the
// output rate: interpolating up from a rate whose band edge is near the
// channels (the HF+'s 456 kS/s) is where the radio's filter and the cubic
// step are both worst. A HackRF is kept at 2 MS/s or more: below that its
// own filters alias.
double chooseRate(const SoapySDR::RangeList& ranges, double need, double outRate, double floor) {
    if (floor <= outRate)
        for (const auto& r : ranges)
            if (outRate >= r.minimum() - 0.5 && outRate <= r.maximum() + 0.5) return outRate;
    const double lowest = std::max({need, floor, 0.85 * outRate});
    double best = 0;
    for (const auto& r : ranges) {
        double c;
        if (r.maximum() - r.minimum() < 1) {
            c = r.minimum();
        } else {
            c = std::ceil(lowest / outRate) * outRate;           // a multiple of the output rate
            if (c < r.minimum() || c > r.maximum()) c = std::max(lowest, r.minimum());
        }
        if (c < lowest - 0.5 || c > r.maximum() + 0.5) continue;
        if (!best || c < best) best = c;
    }
    return best;
}

}  // namespace

// One radio per line: the arguments that pick it for --soapy (driver, serial,
// then any other key a value without spaces), two spaces, its label. The
// installer reads this.
void soapyList(FILE* out) {
    SoapySDR::setLogLevel(SOAPY_SDR_WARNING);
    for (const auto& k : SoapySDR::Device::enumerate()) {
        std::string s;
        auto add = [&](const std::string& key) {
            auto it = k.find(key);
            if (it == k.end() || it->second.empty() || it->second.find(' ') != std::string::npos) return;
            if (!s.empty()) s += ",";
            s += key + "=" + it->second;
        };
        add("driver");
        add("serial");
        if (k.find("serial") == k.end())
            for (const auto& kv : k)
                if (kv.first != "driver" && kv.first != "label") add(kv.first);
        auto l = k.find("label");
        fprintf(out, "%s%s%s\n", s.c_str(), l != k.end() ? "  " : "", l != k.end() ? l->second.c_str() : "");
    }
}

FILE* SoapyInput::open(const SoapyOptions& o, const std::vector<double>& channels, double planCentre,
                       double outRate, const volatile sig_atomic_t* stop) {
    o_ = o;
    outRate_ = outRate;
    stop_ = stop;
    SoapySDR::setLogLevel(SOAPY_SDR_WARNING);
    // With no arguments, the first radio: SoapySDR's own first device may be
    // the sound card (its audio module).
    SoapySDR::Kwargs want = SoapySDR::KwargsFromString(o.args);
    try {
        if (o.args.empty()) {
            bool found = false;
            for (const auto& k : SoapySDR::Device::enumerate()) {
                auto d = k.find("driver");
                if (d != k.end() && d->second == "audio") continue;
                want = k;
                found = true;
                break;
            }
            if (!found) {
                fprintf(stderr, "vdl2-sniffer: SoapySDR finds no radio (is its module installed? "
                        "SoapySDRUtil --find)\n");
                return nullptr;
            }
        }
        dev_ = SoapySDR::Device::make(want);
    } catch (const std::exception& e) {
        fprintf(stderr, "vdl2-sniffer: cannot open SoapySDR device \"%s\": %s\n", o.args.c_str(), e.what());
        return nullptr;
    }
    if (!dev_) {
        fprintf(stderr, "vdl2-sniffer: no SoapySDR device matches \"%s\"\n", o.args.c_str());
        return nullptr;
    }
    try {
        const std::string driver = lower(dev_->getDriverKey()), hw = dev_->getHardwareKey();
        const bool hackrf = driver.find("hackrf") != std::string::npos;

        // Tuning: the plan's centre, except on a radio with a strong DC spike
        // (the HackRF's LO leaks into its own input), tuned 250 kHz above so
        // the spike falls clear of every channel.
        centre = o.centre > 0 ? o.centre : planCentre + (hackrf ? 250e3 : 0);
        double half = 0;   // farthest channel edge from the radio's centre
        for (double c : channels) half = std::max(half, std::fabs(c - centre) + 12500.0);
        rate = o.rate > 0 ? o.rate : chooseRate(dev_->getSampleRateRange(SOAPY_SDR_RX, 0),
                                                2 * (half + 50e3), outRate, hackrf ? 2e6 : 0);
        if (!(rate > 0)) {
            fprintf(stderr, "vdl2-sniffer: %s offers no sample rate of %.0f kS/s or more\n", hw.c_str(),
                    2 * (half + 50e3) / 1e3);
            return nullptr;
        }
        if (half + 10e3 > rate / 2) {
            fprintf(stderr, "vdl2-sniffer: the channels reach %.0f kHz from %.4f MHz, more than %s holds\n",
                    half / 1e3, centre / 1e6, mhz(rate).c_str());
            return nullptr;
        }
        dev_->setSampleRate(SOAPY_SDR_RX, 0, rate);
        rate = dev_->getSampleRate(SOAPY_SDR_RX, 0);   // what it really set

        // ppm: the driver's own correction when it has one, otherwise by
        // tuning (a crystal fast by N ppm tunes N ppm high).
        double tune = centre;
        if (o.ppm) {
            if (dev_->hasFrequencyCorrection(SOAPY_SDR_RX, 0)) dev_->setFrequencyCorrection(SOAPY_SDR_RX, 0, o.ppm);
            else tune = centre / (1 + o.ppm * 1e-6);
        }
        dev_->setFrequency(SOAPY_SDR_RX, 0, tune);
        if (!o.antenna.empty()) dev_->setAntenna(SOAPY_SDR_RX, 0, o.antenna);

        // Gain: auto (the radio's AGC), one figure, or named stages.
        if (o.gain == "auto") {
            if (dev_->hasGainMode(SOAPY_SDR_RX, 0)) {
                dev_->setGainMode(SOAPY_SDR_RX, 0, true);
                gain = "auto";
            } else {
                gain = "driver default (no AGC)";
                fprintf(stderr, "vdl2-sniffer: %s has no automatic gain; using the driver's default, "
                        "set it with --gain\n", hw.c_str());
            }
        } else {
            if (dev_->hasGainMode(SOAPY_SDR_RX, 0)) dev_->setGainMode(SOAPY_SDR_RX, 0, false);
            if (o.gain.find('=') == std::string::npos) {
                dev_->setGain(SOAPY_SDR_RX, 0, atof(o.gain.c_str()));
            } else {
                const auto names = dev_->listGains(SOAPY_SDR_RX, 0);
                for (size_t p = 0; p < o.gain.size();) {
                    const size_t q = std::min(o.gain.find(',', p), o.gain.size());
                    const std::string kv = o.gain.substr(p, q - p);
                    const size_t eq = kv.find('=');
                    p = q + 1;
                    if (eq == std::string::npos) continue;
                    std::string name = kv.substr(0, eq);
                    auto it = std::find_if(names.begin(), names.end(),
                                           [&](const std::string& n) { return lower(n) == lower(name); });
                    if (it == names.end()) {
                        std::string all;
                        for (const auto& n : names) all += (all.empty() ? "" : ", ") + n;
                        fprintf(stderr, "vdl2-sniffer: %s has no gain stage %s (it has %s)\n", hw.c_str(),
                                name.c_str(), all.c_str());
                        return nullptr;
                    }
                    dev_->setGain(SOAPY_SDR_RX, 0, *it, atof(kv.substr(eq + 1).c_str()));
                }
            }
            char b[64];
            for (const auto& n : dev_->listGains(SOAPY_SDR_RX, 0)) {
                snprintf(b, sizeof b, "%s%s %.0f", gain.empty() ? "" : ", ", n.c_str(), dev_->getGain(SOAPY_SDR_RX, 0, n));
                gain += b;
            }
            if (gain.empty()) { snprintf(b, sizeof b, "%.1f dB", dev_->getGain(SOAPY_SDR_RX, 0)); gain = b; }
        }

        // CS16 from every radio: native for the Airspys and lossless for the
        // 8-bit ones.
        stream_ = dev_->setupStream(SOAPY_SDR_RX, SOAPY_SDR_CS16, std::vector<size_t>{0});
        if (!stream_) throw std::runtime_error("setupStream failed");

        // 1.05 MS/s on a 12.5 kHz step from the channels goes straight through.
        const bool asIs = std::fabs(rate - outRate) < 0.5 &&
                          std::fabs(std::remainder(centre - channels.front(), 12500.0)) < 0.5 &&
                          std::fabs(centre - planCentre) < 0.5;
        if (!asIs) {
            double pass = 0;
            for (double c : channels) pass = std::max(pass, std::fabs(c - planCentre) + 12500.0);
            rs_.reset(new RateConverter(rate, outRate, planCentre - centre, pass));
        }

        if (pipe2(fd_, O_CLOEXEC) < 0) { perror("pipe"); return nullptr; }
        fcntl(fd_[1], F_SETPIPE_SZ, 1 << 20);   // a quarter second of ci16 at 1.05 MS/s
        pipeSize_ = fcntl(fd_[1], F_GETPIPE_SZ);

        // The label from enumeration ("Nooelec NESDR SMArt v5, serial 43399429")
        // where the driver gives one; the hardware info has the serial otherwise.
        std::string name = hw, serial;
        auto info = dev_->getHardwareInfo();
        const auto found = SoapySDR::Device::enumerate(want);
        if (!found.empty()) for (const auto& kv : found.front()) info.insert(kv);
        auto get = [&](const char* k) { auto it = info.find(k); return it == info.end() ? std::string() : it->second; };
        for (const char* k : {"serial", "serial_number", "SerialNumber"}) if (!(serial = get(k)).empty()) break;
        if (!get("product").empty()) name = (get("manufacturer").empty() ? "" : get("manufacturer") + " ") + get("product");
        device = name + (serial.empty() ? "" : ", serial " + serial) + " (SoapySDR " + driver + ")";
        tuner = rs_ ? rs_->describe() : mhz(rate) + ", as is";
        fprintf(stderr, "vdl2-sniffer: %s at %.4f MHz, gain %s, %d ppm, antenna %s\n", device.c_str(), centre / 1e6,
                gain.c_str(), o.ppm, dev_->getAntenna(SOAPY_SDR_RX, 0).c_str());
        fprintf(stderr, "vdl2-sniffer: input %s\n", rs_ ? rs_->describe().c_str() : (mhz(rate) + ", as is").c_str());

        if (dev_->activateStream(stream_) != 0) throw std::runtime_error("activateStream failed");

        // After activation: some drivers (SDRplay) can't take settings before.
        // The bias tee's key differs by driver: biastee (Airspy, RTL-SDR),
        // biastee_rx (bladeRF), biasT_ctrl (SDRplay); the HackRF has only
        // bias_tx, which powers its one antenna port whichever way it runs.
        if (o.biasTee) {
            std::string key;
            const auto info = dev_->getSettingInfo();
            for (const auto& a : info)
                if (lower(a.key).find("bias") != std::string::npos && lower(a.key).find("rx") != std::string::npos) { key = a.key; break; }
            if (key.empty())
                for (const auto& a : info)
                    if (lower(a.key).find("bias") != std::string::npos && lower(a.key).find("tx") == std::string::npos) { key = a.key; break; }
            if (key.empty() && hackrf) key = "bias_tx";
            if (key.empty()) {
                fprintf(stderr, "vdl2-sniffer: %s has no bias tee setting\n", hw.c_str());
                return nullptr;
            }
            dev_->writeSetting(key, "true");
            fprintf(stderr, "vdl2-sniffer: bias tee on (%s)\n", key.c_str());
        }
        for (const auto& kv : o.settings) {
            dev_->writeSetting(kv.first, kv.second);
            fprintf(stderr, "vdl2-sniffer: %s = %s\n", kv.first.c_str(), dev_->readSetting(kv.first).c_str());
        }
    } catch (const std::exception& e) {
        fprintf(stderr, "vdl2-sniffer: SoapySDR: %s\n", e.what());
        return nullptr;
    }
    th_ = std::thread([this] { run(); });
    return fdopen(fd_[0], "rb");
}

void SoapyInput::put(const void* data, size_t bytes) {
    int queued = 0;
    ioctl(fd_[1], FIONREAD, &queued);
    if (pipeSize_ - queued < (int)bytes) {
        dropped += bytes;
        return;
    }
    const char* p = static_cast<const char*>(data);
    for (size_t off = 0; off < bytes;) {
        ssize_t w = write(fd_[1], p + off, bytes - off);
        if (w <= 0) { if (errno == EINTR) continue; return; }
        off += (size_t)w;
    }
}

void SoapyInput::run() {
    size_t mtu = dev_->getStreamMTU(stream_);
    if (!mtu) mtu = 65536;
    std::vector<int16_t> buf(2 * mtu), packed;
    std::vector<std::complex<float>> iq, out;
    double firstAt = 0;
    uint64_t got = 0;           // radio samples, counting those lost in overflows
    bool checkClock = false;
    while (!cancelled_ && !*stop_) {
        void* bufs[1] = {buf.data()};
        int flags = 0;
        long long timeNs = 0;
        const int n = dev_->readStream(stream_, bufs, mtu, flags, timeNs, 200000);
        if (n == SOAPY_SDR_TIMEOUT) continue;
        if (n == SOAPY_SDR_OVERFLOW) { overflows++; checkClock = true; continue; }
        if (n < 0) {
            if (n == SOAPY_SDR_CORRUPTION) continue;
            if (!cancelled_ && !*stop_) {
                failed = true;
                fprintf(stderr, "vdl2-sniffer: SoapySDR read failed: %s\n", SoapySDR::errToStr(n));
            }
            break;
        }
        if (!n) continue;
        const double now = mono();
        if (!got) firstAt = now;
        arrived += (uint64_t)n;
        got += (uint64_t)n;
        // After an overflow: what the clock says the radio sent and we never
        // saw. Under 20 ms isn't told apart from the driver's buffering.
        if (checkClock) {
            checkClock = false;
            const double behind = (now - firstAt) * rate - (double)got;
            if (behind > 0.02 * rate) {
                got += (uint64_t)behind;
                dropped += (uint64_t)(behind * outRate_ / rate) * 4;
            }
        }
        if (!rs_) { put(buf.data(), (size_t)n * 4); continue; }
        iq.resize((size_t)n);
        for (int i = 0; i < n; i++) iq[i] = {buf[2 * i] / 32768.f, buf[2 * i + 1] / 32768.f};
        out.clear();
        rs_->process(iq.data(), (size_t)n, out);
        packed.resize(2 * out.size());
        for (size_t i = 0; i < out.size(); i++) {
            packed[2 * i] = (int16_t)std::lround(std::clamp(out[i].real() * 32768.f, -32768.f, 32767.f));
            packed[2 * i + 1] = (int16_t)std::lround(std::clamp(out[i].imag() * 32768.f, -32768.f, 32767.f));
        }
        if (!packed.empty()) put(packed.data(), packed.size() * 2);
    }
    close(fd_[1]);
    fd_[1] = -1;
}

void SoapyInput::stop() {
    if (!dev_) return;
    cancelled_ = true;
    if (th_.joinable()) th_.join();
    try {
        if (stream_) {
            dev_->deactivateStream(stream_);
            dev_->closeStream(stream_);
        }
    } catch (...) {
    }
    stream_ = nullptr;
    if (fd_[1] >= 0) { close(fd_[1]); fd_[1] = -1; }
    SoapySDR::Device::unmake(dev_);
    dev_ = nullptr;
}

SoapyInput::~SoapyInput() { stop(); }
