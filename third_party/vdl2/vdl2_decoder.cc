#include "vdl2_decoder.hh"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace Jetstream::Vdl2Receiver {

namespace {

// (vdl2-sniffer) Parity octets sent with a block of the given data length
// (every block but the last is full, 249). Measured as the count under which
// clean frames need no correction, over ~140 frames from ten captures:
// <= 30 octets carry two, 44-66 four, 73 and up six. Lengths 31-43 and 67-72
// were never observed; the limits at 30 and 67 are assumptions between them.
int ShortBlockParity(int len) {
    if (len <= 30) return 2;
    if (len <= 67) return 4;
    return 6;
}

constexpr double Pi = 3.14159265358979323846;
constexpr float Step = static_cast<float>(Pi / 4.0);

// Unique word as phase-change indices. Recovered from the air as the
// longest run every burst shares, and it agrees symbol for symbol with the
// published tribit sequence under a reflected Gray mapping.
const int UW[16] = {0, 3, 2, 4, 0, 1, 6, 4, 1, 7, 2, 5, 6, 5, 7, 3};

// 15-stage scrambler, x^15 + x + 1, loaded 1101 0010 1011 001, applied to
// everything after the synchronisation pattern.
const int SCRAM_INIT[15] = {1,1,0,1,0,0,1,0,1,0,1,1,0,0,1};

constexpr int HEADER_BITS = 25;
constexpr int RING = 1 << 16;
constexpr std::uint64_t SeedSamples = 2048;              // ~20 ms at 105 kS/s
constexpr std::uint64_t MaxBurstSamples = 105000 / 4;    // 250 ms, well past any frame      // ~0.62 s at 105 kS/s, longest burst is 70 ms

// Parity-check matrix of the (25,20) header code.
const int H[5][20] = {
 {0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1},
 {0,0,1,1,1,1,1,1,0,0,0,0,1,1,1,1,1,1,1,1},
 {1,1,0,0,0,1,1,1,0,0,1,1,0,0,0,0,1,1,1,1},
 {1,1,0,1,1,0,1,1,0,1,0,1,0,0,1,1,0,0,1,1},
 {0,1,1,0,1,0,0,1,1,1,1,0,0,1,0,1,0,1,0,1},
};

// (vdl2-sniffer) out[i] = the sum over taps t of x[at[t] + i] * h[t]. Each sum is
// built tap by tap from t = 0, as the per-sample ring loop built it, so the result
// is the same to the bit -- but NV vectors of outputs are summed side by side in
// registers, and no ring index is wrapped per tap.
template <class V, std::size_t NV>
inline __attribute__((always_inline)) void FirBlocks(const float* h, std::size_t taps,
                                                     const std::size_t* at, const float* xRe,
                                                     const float* xIm, std::size_t n,
                                                     float* outRe, float* outIm) {
    constexpr std::size_t L = sizeof(V) / sizeof(float), B = L * NV;
    std::size_t i0 = 0;
    for (; i0 + B <= n; i0 += B) {
        V re[NV] = {}, im[NV] = {};
        for (std::size_t t = 0; t < taps; ++t) {
            const float* xr = xRe + at[t] + i0;
            const float* xi = xIm + at[t] + i0;
            const float k = h[t];
            for (std::size_t j = 0; j < NV; ++j) {
                V r, q;
                std::memcpy(&r, xr + j * L, sizeof r);
                std::memcpy(&q, xi + j * L, sizeof q);
                re[j] += r * k;
                im[j] += q * k;
            }
        }
        for (std::size_t j = 0; j < NV; ++j) {
            std::memcpy(outRe + i0 + j * L, &re[j], sizeof(V));
            std::memcpy(outIm + i0 + j * L, &im[j], sizeof(V));
        }
    }
    for (; i0 < n; ++i0) {
        float re = 0.0f, im = 0.0f;
        for (std::size_t t = 0; t < taps; ++t) {
            re += xRe[at[t] + i0] * h[t];
            im += xIm[at[t] + i0] * h[t];
        }
        outRe[i0] = re;
        outIm[i0] = im;
    }
}

typedef float Float4 __attribute__((vector_size(16)));
typedef float Float8 __attribute__((vector_size(32)));

#if defined(__x86_64__) && !defined(__AVX2__)
// AVX2 without FMA, so the products are still rounded before they are added.
__attribute__((target("avx2"))) void FirAvx2(const float* h, std::size_t taps,
                                             const std::size_t* at, const float* xRe,
                                             const float* xIm, std::size_t n, float* outRe,
                                             float* outIm) {
    FirBlocks<Float8, 4>(h, taps, at, xRe, xIm, n, outRe, outIm);
}
const bool HaveAvx2 = __builtin_cpu_supports("avx2");
#endif

void Fir(const std::vector<float>& h, const std::size_t* at, const float* xRe, const float* xIm,
         std::size_t n, float* outRe, float* outIm) {
#if defined(__AVX2__)
    FirBlocks<Float8, 4>(h.data(), h.size(), at, xRe, xIm, n, outRe, outIm);
#else
#if defined(__x86_64__)
    if (HaveAvx2) return FirAvx2(h.data(), h.size(), at, xRe, xIm, n, outRe, outIm);
#endif
    FirBlocks<Float4, 6>(h.data(), h.size(), at, xRe, xIm, n, outRe, outIm);
#endif
}

std::vector<float> lowpass(double cutoff, double rate, int taps) {
    std::vector<float> h(taps);
    const double fc = cutoff / rate;
    double sum = 0.0;
    for (int i = 0; i < taps; ++i) {
        const double n = i - (taps - 1) / 2.0;
        const double s = (std::abs(n) < 1e-9) ? 2.0 * fc
                                              : std::sin(2.0 * Pi * fc * n) / (Pi * n);
        const double w = 0.42 - 0.5 * std::cos(2.0 * Pi * i / (taps - 1))
                              + 0.08 * std::cos(4.0 * Pi * i / (taps - 1));
        h[i] = static_cast<float>(s * w);
        sum += h[i];
    }
    for (auto& v : h) v = static_cast<float>(v / sum);
    return h;
}

std::vector<int> scrambler(int n) {
    int s[15];
    std::copy(SCRAM_INIT, SCRAM_INIT + 15, s);
    std::vector<int> out;
    out.reserve(n + 1);
    for (int i = 0; i < n + 1; ++i) {
        out.push_back(s[0]);
        const int fb = s[14] ^ s[0];
        for (int k = 14; k > 0; --k) s[k] = s[k - 1];
        s[0] = fb;
    }
    out.erase(out.begin());        // the sequence starts one step in
    return out;
}

// Three bits per symbol, the Gray value most significant bit first.
void symbolBits(int phase, int* out) {
    const int v = phase ^ (phase >> 1);
    out[0] = (v >> 2) & 1; out[1] = (v >> 1) & 1; out[2] = v & 1;
}

std::vector<int> destuff(const std::vector<int>& bits) {
    std::vector<int> out;
    out.reserve(bits.size());
    int ones = 0;
    for (std::size_t i = 0; i < bits.size(); ++i) {
        if (ones == 5) {
            ones = 0;
            if (bits[i] == 0) continue;     // the stuffed zero
            out.push_back(bits[i]); ones = 1; continue;
        }
        out.push_back(bits[i]);
        ones = bits[i] ? ones + 1 : 0;
    }
    return out;
}

// A burst may carry several AVLC frames back to back, each closed by a flag
// (01111110). Stuffing guarantees six ones in a row never occur inside a
// frame, so they can only be a flag: split there, before destuffing, and
// hand each piece on as its own frame.
std::vector<std::vector<int>> splitOnFlags(const std::vector<int>& bits) {
    std::vector<std::vector<int>> out;
    std::size_t start = 0;
    int ones = 0;
    for (std::size_t i = 0; i < bits.size(); ++i) {
        if (bits[i]) { ones++; continue; }
        if (ones == 6 && i >= 7) {
            const std::size_t end = i - 7;              // the flag's leading zero
            if (end > start) out.emplace_back(bits.begin() + start, bits.begin() + end);
            start = i + 1;
        }
        ones = 0;
    }
    if (start < bits.size()) out.emplace_back(bits.begin() + start, bits.end());
    return out;
}

std::vector<std::uint8_t> octetsLsb(const std::vector<int>& bits) {
    std::vector<std::uint8_t> out;
    for (std::size_t i = 0; i + 8 <= bits.size(); i += 8) {
        int v = 0;
        for (int k = 0; k < 8; ++k) v |= bits[i + k] << k;
        out.push_back(static_cast<std::uint8_t>(v));
    }
    return out;
}

}  // namespace

std::vector<std::vector<std::uint8_t>> AvlcPieces(const std::vector<int>& bits) {
    std::vector<std::vector<std::uint8_t>> out;
    for (const auto& seg : splitOnFlags(bits)) out.push_back(octetsLsb(destuff(seg)));
    return out;
}

std::uint16_t Crc16X25(const std::uint8_t* data, std::size_t n) {
    std::uint16_t reg = 0xFFFF;
    for (std::size_t i = 0; i < n; ++i) {
        reg ^= data[i];
        for (int k = 0; k < 8; ++k) reg = (reg >> 1) ^ ((reg & 1) ? 0x8408 : 0);
    }
    return reg;
}

bool ParseAvlc(const std::vector<std::uint8_t>& f, Frame& out) {
    if (f.size() < 11) return false;
    auto addr = [](const std::uint8_t* p, std::uint32_t& a, std::uint8_t& kind) {
        std::uint32_t n = 0;
        for (int i = 0; i < 4; ++i) {
            const int v = p[i] >> 1;
            for (int k = 0; k < 7; ++k) n = (n << 1) | ((v >> k) & 1);
        }
        a = n & 0xFFFFFF;
        kind = static_cast<std::uint8_t>((n >> 24) & 0x7);
    };
    addr(f.data() + 0, out.dest, out.destKind);
    addr(f.data() + 4, out.source, out.sourceKind);
    out.control = f[8];
    return true;
}

Decoder::Decoder(double centreHz, const std::vector<double>& chans) : centre_(centreHz) {
    // 121 taps, not 401. Decimating by ten only needs whatever would
    // alias into the 7 kHz the channel filter keeps -- bands around
    // 105 kHz, 210 kHz and so on -- not a sharp edge at 52 kHz. That
    // turns the dominant cost of the whole receiver into a third of
    // itself for no measurable loss.
    aaTaps_ = lowpass(45000.0, RequiredSampleRate, 121);
    chTaps_ = lowpass(7000.0, RequiredSampleRate / Decimation, 121);

    mixer_.resize(MixerPeriod);
    for (int i = 0; i < MixerPeriod; ++i) {
        const double a = 2.0 * Pi * i / MixerPeriod;
        mixer_[i] = {static_cast<float>(std::cos(a)), static_cast<float>(std::sin(a))};
    }

    for (double f : chans) {
        Channel c;
        c.frequency = f;
        // Offsets are multiples of 12.5 kHz and 12.5 kHz divides the sample
        // rate 84 times, so the rotation is exact.
        const double off = f - centreHz;
        int step = static_cast<int>(std::llround(-off / (RequiredSampleRate / MixerPeriod)));
        step %= MixerPeriod;
        if (step < 0) step += MixerPeriod;
        c.mixerStep = step;
        channels_.push_back(std::move(c));
    }
    reset();
}

void Decoder::reset() {
    for (auto& c : channels_) {
        // Zeros before the first sample, as many as the first output's window
        // (ten samples in) and the channel filter's history hold.
        c.aaRe.assign(aaTaps_.empty() ? 0 : aaTaps_.size() - Decimation, 0.0f);
        c.aaIm.assign(c.aaRe.size(), 0.0f);
        c.chRe.assign(chTaps_.size() - 1, 0.0f);
        c.chIm.assign(c.chRe.size(), 0.0f);
        c.mixerPhase = 0;
        c.ring.assign(RING, {0.0f, 0.0f});
        c.ringPos = 0; c.ringCount = 0;
        c.envelope = 0.0f; c.floorEst = 1e-4f; c.peak = 0.0f;
        c.seed.clear();
        c.inBurst = false; c.burstStart = 0; c.quietFor = 0;
    }
    bursts_ = frames_ = 0;
}

Decoder::Decoder(double channelHz) : centre_(channelHz), narrow_(true) {
    // No mixer and no decimation, so only the channel filter is built --
    // and it was always designed at this rate.
    chTaps_ = lowpass(7000.0, NarrowSampleRate, 121);
    Channel c;
    c.frequency = channelHz;
    c.mixerStep = 0;
    channels_.push_back(std::move(c));
    reset();
}

void Decoder::process(const std::complex<float>* iq, std::size_t n, const Callback& cb) {
    if (narrow_) {
        // Already at the channel and already at rate: straight to the channel filter.
        Channel& c = channels_.front();
        for (std::size_t i = 0; i < n; ++i) {
            c.chRe.push_back(iq[i].real());
            c.chIm.push_back(iq[i].imag());
        }
        channelFilter(c, cb);
        return;
    }

    const std::size_t taps = aaTaps_.size();
    for (auto& c : channels_) {
        const std::size_t have = c.aaRe.size();
        c.aaRe.resize(have + n);
        c.aaIm.resize(have + n);
        float* re = c.aaRe.data() + have;
        float* im = c.aaIm.data() + have;
        for (std::size_t i = 0; i < n; ++i) {
            const std::complex<float> m = mixer_[c.mixerPhase];
            re[i] = iq[i].real() * m.real() - iq[i].imag() * m.imag();
            im[i] = iq[i].real() * m.imag() + iq[i].imag() * m.real();
            c.mixerPhase += c.mixerStep;
            if (c.mixerPhase >= MixerPeriod) c.mixerPhase -= MixerPeriod;
        }

        // Every tenth sample closes a window of 121, oldest first.
        const std::size_t len = c.aaRe.size();
        if (len < taps) continue;
        const std::size_t outs = (len - taps) / Decimation + 1;
        // Tap t of output i is sample 10 (i + t / 10) + t % 10. Each of the ten
        // phases on a row of its own makes every tap's samples consecutive.
        const std::size_t row = outs + (taps - 1) / Decimation;
        polyRe_.resize(Decimation * row);
        polyIm_.resize(Decimation * row);
        for (int r = 0; r < Decimation; ++r) {
            for (std::size_t m = 0; m < row; ++m) {
                const std::size_t k = m * Decimation + r;
                polyRe_[r * row + m] = k < len ? c.aaRe[k] : 0.0f;
                polyIm_[r * row + m] = k < len ? c.aaIm[k] : 0.0f;
            }
        }
        const std::size_t chHave = c.chRe.size();
        c.chRe.resize(chHave + outs);
        c.chIm.resize(chHave + outs);
        tapAt_.resize(taps);
        for (std::size_t t = 0; t < taps; ++t) tapAt_[t] = (t % Decimation) * row + t / Decimation;
        Fir(aaTaps_, tapAt_.data(), polyRe_.data(), polyIm_.data(), outs,
                 c.chRe.data() + chHave, c.chIm.data() + chHave);
        c.aaRe.erase(c.aaRe.begin(), c.aaRe.begin() + outs * Decimation);
        c.aaIm.erase(c.aaIm.begin(), c.aaIm.begin() + outs * Decimation);

        channelFilter(c, cb);
    }
}

void Decoder::channelFilter(Channel& c, const Callback& cb) {
    const std::size_t taps = chTaps_.size();
    const std::size_t len = c.chRe.size();
    if (len < taps) return;
    const std::size_t outs = len - taps + 1;
    outRe_.resize(outs);
    outIm_.resize(outs);
    tapAt_.resize(taps);
    for (std::size_t t = 0; t < taps; ++t) tapAt_[t] = t;
    Fir(chTaps_, tapAt_.data(), c.chRe.data(), c.chIm.data(), outs, outRe_.data(),
             outIm_.data());
    c.chRe.erase(c.chRe.begin(), c.chRe.begin() + outs);
    c.chIm.erase(c.chIm.begin(), c.chIm.begin() + outs);
    for (std::size_t i = 0; i < outs; ++i) pushFiltered(c, {outRe_[i], outIm_[i]}, cb);
}

void Decoder::pushFiltered(Channel& c, std::complex<float> f, const Callback& cb) {
    c.ring[c.ringPos] = f;
    c.ringPos = (c.ringPos + 1) % RING;
    c.ringCount++;

    // Envelope against a slowly tracked floor. The floor only follows
    // downward quickly, so a long burst cannot drag it up and hide itself.
    const float mag = std::abs(f);
    c.envelope += (mag - c.envelope) * 0.05f;
    // Track the median of the envelope, not its minimum. A tracker that
    // falls fast and rises slowly converges on the quietest sample seen,
    // and a threshold 9 dB above the quietest sample is crossed by
    // ordinary noise all day -- which is why this opened 175000 spans in
    // ten minutes. Stepping by a fixed fraction in whichever direction the
    // envelope lies converges on the median instead, and the step is
    // proportional so it works at any signal level.
    // ...and only while no burst is in progress. The floor is an estimate
    // of the noise; updating it through a burst lets the signal drag it up
    // and the burst ends underneath its own threshold. That is the same
    // truncation the previous tracker suffered, arrived at from the other
    // direction.
    // A burst cannot last longer than the longest legal frame. If one
    // appears to, the floor estimate is wrong rather than the air being
    // busy -- abandon it so the floor can converge again. Without this the
    // detector can deadlock at startup: the floor begins below the noise,
    // a burst opens immediately, and freezing the floor inside a burst
    // means it can never catch up.
    // Seed the floor with the median of the first 20 ms, which is where the
    // tracker below would end up anyway. Walking it up from nothing took
    // half a second, and the detector was blind for all of it: a frame
    // 150 ms into a recording was lost that way.
    if (c.ringCount <= SeedSamples) {
        c.seed.push_back(mag);
        if (c.ringCount < SeedSamples) return;
        const auto mid = c.seed.begin() + c.seed.size() / 2;
        std::nth_element(c.seed.begin(), mid, c.seed.end());
        c.floorEst = std::max(*mid, 1e-7f);
        std::vector<float>().swap(c.seed);
        return;
    }

    if (c.inBurst && c.ringCount - c.burstStart > MaxBurstSamples) {
        c.inBurst = false;
        c.quietFor = 0;
    }
    if (!c.inBurst) {
        const float step = c.floorEst * 0.002f;
        c.floorEst += (mag > c.floorEst) ? step : -step;
        if (c.floorEst < 1e-7f) c.floorEst = 1e-7f;
    }

    // Hysteresis: it takes 9 dB to open a burst and only 6 to keep it,
    // so the trailing ramp does not chop a frame in half. Without the
    // gap the detector chatters and reports thousands of bursts a minute.
    const bool open_ = c.envelope > c.floorEst * 2.8f;    // ~9 dB
    const bool keep = c.envelope > c.floorEst * 2.0f;     // ~6 dB
    if (c.inBurst ? keep : open_) {
        if (!c.inBurst) { c.inBurst = true; c.burstStart = c.ringCount; c.peak = c.envelope; }
        c.peak = std::max(c.peak, c.envelope);
        c.quietFor = 0;
    } else if (c.inBurst) {
        if (++c.quietFor > 60) {
            const std::uint64_t end = c.ringCount - c.quietFor;
            c.inBurst = false;
            const std::uint64_t len = end - c.burstStart;
            if (len >= 4 * SamplesPerSymbol * 10 && len <= 260 * SamplesPerSymbol * 10) {
                bursts_++;
                tryBurst(c, c.burstStart, end, cb);
            }
        }
    }
}

void Decoder::tryBurst(Channel& c, std::uint64_t from, std::uint64_t to,
                       const Callback& cb) {
    const std::uint64_t oldest = c.ringCount > RING ? c.ringCount - RING : 0;
    if (from < oldest + 32) return;
    auto at = [&](double idx) -> std::complex<float> {
        const std::int64_t i0 = static_cast<std::int64_t>(std::floor(idx));
        if (i0 < static_cast<std::int64_t>(oldest) ||
            i0 + 1 >= static_cast<std::int64_t>(c.ringCount)) return {0.0f, 0.0f};
        const float w = static_cast<float>(idx - i0);
        const auto a = c.ring[i0 % RING];
        const auto b = c.ring[(i0 + 1) % RING];
        return a * (1.0f - w) + b * w;
    };

    // Reach back over the ramp and well past the trailing edge: the
    // envelope trips late at the start and early at the end, and a frame
    // clipped at either end is lost outright.
    const double lo = static_cast<double>(from) - 16.0 * SamplesPerSymbol;
    const double hi = static_cast<double>(to) + 40.0 * SamplesPerSymbol;
    const int nsym = static_cast<int>((hi - lo) / SamplesPerSymbol);
    if (nsym < 40) return;

    // Symbol clock: whichever fractional phase makes the phase changes
    // cluster most tightly on eight points. Searched coarsely over whole
    // samples on a subset of symbols first, then refined around the winner
    // -- the detector offers far more spans than there are bursts, and
    // this search over all of them is where the time goes.
    // Always the change between *adjacent* symbols -- a stride taken
    // across the difference measures the phase change over three symbols,
    // which is a different quantity and loses short bursts. Sampling fewer
    // adjacent pairs keeps the statistic and still skips most of the work.
    // Score the clock over the *detected* span only. The window above
    // deliberately overhangs the burst at both ends so no frame is
    // clipped, but those overhangs are noise, and on a short burst they
    // are nearly half the symbols -- enough to pull the estimate off and
    // lose the unique word. Extract wide, measure narrow.
    const int kLo = static_cast<int>((static_cast<double>(from) - lo) / SamplesPerSymbol);
    const int kHi = static_cast<int>((static_cast<double>(to) - lo) / SamplesPerSymbol);
    const int sLo = std::max(4, kLo);
    const int sHi = std::min(nsym - 3, kHi);
    auto score = [&](double frac, int stride) {
        std::complex<double> acc{0.0, 0.0};
        int cnt = 0;
        for (int k = sLo; k < sHi; k += stride) {
            const double t = lo + k * static_cast<double>(SamplesPerSymbol) + frac;
            const auto d = at(t + SamplesPerSymbol) * std::conj(at(t));
            const double ang = std::atan2(d.imag(), d.real()) * 8.0;
            acc += std::complex<double>(std::cos(ang), std::sin(ang));
            cnt++;
        }
        return cnt ? std::abs(acc) / cnt : 0.0;
    };

    // One decode attempt at a given sampling phase.
    auto attempt = [&](double frac) -> bool {
        std::vector<std::complex<float>> sym(nsym);
        for (int k = 0; k < nsym; ++k) {
            sym[k] = at(lo + k * static_cast<double>(SamplesPerSymbol) + frac);
        }

        // Differential pass, only to locate the unique word.
        std::vector<int> diff(nsym - 1);
        std::complex<double> bias{0.0, 0.0};
        std::vector<double> dphi(nsym - 1);
        for (int k = 0; k + 1 < nsym; ++k) {
            const auto d = sym[k + 1] * std::conj(sym[k]);
            dphi[k] = std::atan2(d.imag(), d.real());
            bias += std::complex<double>(std::cos(8 * dphi[k]), std::sin(8 * dphi[k]));
        }
        const double b0 = std::atan2(bias.imag(), bias.real()) / 8.0;
        for (int k = 0; k + 1 < nsym; ++k) {
            double a = std::fmod(dphi[k] - b0, 2 * Pi);
            if (a < 0) a += 2 * Pi;
            diff[k] = static_cast<int>(std::llround(a / (Pi / 4))) % 8;
        }

        int best = -1, off = -1;
        for (int i = 0; i + 16 <= static_cast<int>(diff.size()); ++i) {
            int m = 0;
            for (int j = 0; j < 16; ++j) m += (diff[i + j] == UW[j]);
            if (m > best) { best = m; off = i; }
        }
        // Thirteen of sixteen. The differential decisions used here are the
        // noisiest in the chain, and a short frame near 14 dB can lose three
        // of them at every sampling phase. Header parity, Reed-Solomon and
        // the FCS all stand behind this, so a looser match costs time, not
        // false frames.
        if (best < 13) return false;

        // Coherent detection. Phase and frequency come from the unique word,
        // which is sixteen known symbols; blind recovery by raising an 8-PSK
        // sample to the eighth power multiplies noise where it hurts most.
        if (off + 17 > nsym) return false;
        double psi = 0.0, sumK = 0, sumR = 0, sumKK = 0, sumKR = 0;
        double prevResid = 0.0;
        for (int k = 0; k < 17; ++k) {
            const auto v = sym[off + k] * std::complex<float>(
                static_cast<float>(std::cos(-psi)), static_cast<float>(std::sin(-psi)));
            double r = std::atan2(v.imag(), v.real());
            if (k) { while (r - prevResid > Pi) r -= 2 * Pi;
                     while (r - prevResid < -Pi) r += 2 * Pi; }
            prevResid = r;
            sumK += k; sumR += r; sumKK += double(k) * k; sumKR += double(k) * r;
            if (k < 16) psi += UW[k] * (Pi / 4);
        }
        const double den = 17 * sumKK - sumK * sumK;
        double slope = den != 0 ? (17 * sumKR - sumK * sumR) / den : 0.0;
        double theta = (sumR - slope * sumK) / 17 + slope * off;
        double freq = slope;

        std::vector<int> abs_(nsym), conf(nsym);
        for (int k = 0; k < nsym; ++k) {
            const auto v = sym[k] * std::complex<float>(
                static_cast<float>(std::cos(-theta)), static_cast<float>(std::sin(-theta)));
            const double a = std::atan2(v.imag(), v.real());
            int d = static_cast<int>(std::llround(a / (Pi / 4)));
            d = ((d % 8) + 8) % 8;
            abs_[k] = d;
            double err = a - d * (Pi / 4);
            while (err > Pi) err -= 2 * Pi;
            while (err < -Pi) err += 2 * Pi;
            conf[k] = static_cast<int>(1000.0 * std::abs(err) / (Pi / 8));
            theta += freq + 0.30 * err;
        }
        std::vector<int> idx(nsym - 1);
        for (int k = 0; k + 1 < nsym; ++k) idx[k] = ((abs_[k + 1] - abs_[k]) % 8 + 8) % 8;

        int m2 = 0;
        for (int j = 0; j < 16 && off + j < static_cast<int>(idx.size()); ++j) {
            m2 += (idx[off + j] == UW[j]);
        }
        if (m2 < 12) return false;

        // Everything after the unique word is scrambled.
        const int first = off + 16;
        const int avail = static_cast<int>(idx.size()) - first;
        if (avail < 20) return false;
        std::vector<int> bits;
        bits.reserve(avail * 3);
        for (int k = 0; k < avail; ++k) {
            int t[3]; symbolBits(idx[first + k], t);
            bits.push_back(t[0]); bits.push_back(t[1]); bits.push_back(t[2]);
        }
        const auto pn = scrambler(static_cast<int>(bits.size()));
        for (std::size_t k = 0; k < bits.size(); ++k) bits[k] ^= pn[k];

        if (bits.size() < HEADER_BITS + 64) return false;
        if (bits[0] || bits[1] || bits[2]) return false;
        int tl = 0;
        for (int k = 0; k < 17; ++k) tl |= bits[3 + k] << k;  // least significant bit first
        if (tl < 40 || tl > 16000) return false;
        for (int r = 0; r < 5; ++r) {
            int p = 0;
            for (int k = 0; k < 20; ++k) p ^= bits[k] & H[r][k];
            if (p != bits[20 + r]) return false;
        }

        const int D = (tl + 7) / 8;
        std::vector<int> body(bits.begin() + HEADER_BITS, bits.end());
        const auto oct = octetsLsb(body);
        // (vdl2-sniffer) De-interleave any number of blocks. The data is cut
        // into 249-octet blocks, the last one short; each block is a row, and
        // the stream is the data read column-wise, then the parity read
        // column-wise. A short block carries fewer parity octets. With one or
        // two blocks this is exactly the layout measured on the fixtures (the
        // long block first in each column pair, the short block's two parity
        // octets after the long block's first and second). Each codeword
        // position keeps the stream octet it came from, which is what makes
        // confidence-driven erasures possible.
        const int BD = ReedSolomon::BlockData;
        const int nb = (D + BD - 1) / BD;
        std::vector<int> blen(nb, BD), npar(nb, ReedSolomon::Parity);
        blen[nb - 1] = D - BD * (nb - 1);
        npar[nb - 1] = ShortBlockParity(blen[nb - 1]);
        std::vector<std::vector<int>> octOfCw(nb, std::vector<int>(ReedSolomon::BlockTotal, -1));
        int total = 0;
        for (int j = 0; j < BD; ++j)
            for (int b = 0; b < nb; ++b)
                if (j < blen[b]) octOfCw[b][j] = total++;
        for (int i = 0; i < ReedSolomon::Parity; ++i)
            for (int b = 0; b < nb; ++b)
                if (i < npar[b]) octOfCw[b][BD + i] = total++;
        if (static_cast<int>(oct.size()) < total) return false;

        // Worst symbol confidence contributing to each stream octet. A symbol
        // decided close to a decision boundary is the one likely to be wrong,
        // and the demodulator already measured how close.
        const int nOct = total;
        std::vector<int> octConf(nOct, 0);
        for (int k = 0; k < nOct; ++k) {
            const int s0 = (HEADER_BITS + 8 * k) / 3;
            const int s1 = (HEADER_BITS + 8 * k + 7) / 3;
            int worst = 0;
            for (int sIdx = first + s0; sIdx <= first + s1; ++sIdx) {
                if (sIdx >= 0 && sIdx < static_cast<int>(conf.size())) {
                    worst = std::max(worst, conf[sIdx]);
                }
            }
            octConf[k] = worst;
        }

        std::vector<std::vector<std::uint8_t>> cws(nb, std::vector<std::uint8_t>(ReedSolomon::BlockTotal, 0));
        std::vector<std::vector<int>> ranked(nb), fixedEr(nb);
        for (int b = 0; b < nb; ++b) {
            for (int i = 0; i < ReedSolomon::BlockTotal; ++i) {
                const int oi = octOfCw[b][i];
                if (oi < 0) continue;
                cws[b][i] = oct[oi];
                ranked[b].push_back(i);
            }
            // Codeword positions ranked most doubtful first.
            std::sort(ranked[b].begin(), ranked[b].end(), [&](int x, int y) {
                return octConf[octOfCw[b][x]] > octConf[octOfCw[b][y]];
            });
            // Parity octets that were never transmitted are erasures by definition.
            for (int i = npar[b]; i < ReedSolomon::Parity; ++i) fixedEr[b].push_back(BD + i);
        }

        // RS(255,249) fixes three errors when it has to find them itself, or
        // six when it is told where they are. Ask for more help each round and
        // let the frame's own FCS say whether the guess was worth anything.
        // Every block must correct for a round to count. With several frames
        // in the burst, one round can pass some and fail others; keep going
        // for the rest, and settle for the best round.
        int maxBudget = 0;
        for (int b = 0; b < nb; ++b)
            maxBudget = std::max(maxBudget, ReedSolomon::Parity - static_cast<int>(fixedEr[b].size()));
        std::vector<Frame> kept;
        static const int Tries[] = {0, 1, 2, 3, 4, 5, 6};
        for (int nEr : Tries) {
            if (nEr > maxBudget) break;
            std::vector<std::uint8_t> data;
            data.reserve(D);
            int corrected = 0, erased = 0;
            bool ok = true;
            for (int b = 0; b < nb && ok; ++b) {
                std::vector<int> erase = fixedEr[b];
                const int budget = ReedSolomon::Parity - static_cast<int>(erase.size());
                for (int i = 0; i < std::min(nEr, budget) && i < static_cast<int>(ranked[b].size()); ++i) {
                    erase.push_back(ranked[b][i]);
                }
                std::sort(erase.begin(), erase.end());
                erase.erase(std::unique(erase.begin(), erase.end()), erase.end());
                auto cwTry = cws[b];
                const int c = rs_.correct(cwTry, erase);
                if (c < 0) { ok = false; break; }
                corrected += c;
                erased += static_cast<int>(erase.size());
                data.insert(data.end(), cwTry.begin(), cwTry.begin() + blen[b]);
            }
            if (!ok || data.empty()) continue;

            std::vector<int> fb;
            fb.reserve(data.size() * 8);
            for (std::size_t j = 1; j < data.size(); ++j) {      // past the opening flag
                for (int k = 0; k < 8; ++k) fb.push_back((data[j] >> k) & 1);
            }
            std::vector<Frame> got;
            int pieces = 0;
            for (const auto& out : AvlcPieces(fb)) {
                // 11 octets is a legal AVLC frame: four each of address, one
                // control, two of FCS. Requiring more discards most of the
                // traffic; anything shorter is padding after the closing flag.
                if (out.size() < 11) continue;
                pieces++;
                for (int trim = 3; trim >= 0; --trim) {
                    if (static_cast<int>(out.size()) - trim < 11) continue;
                    std::vector<std::uint8_t> cand(out.begin(), out.end() - trim);
                    if (Crc16X25(cand.data(), cand.size()) != 0xF0B8) continue;
                    Frame f;
                    f.frequency = c.frequency;
                    f.snr = 20.0f * std::log10((c.peak + 1e-12f) / (c.floorEst + 1e-12f));
                    f.errorsCorrected = corrected;
                    f.erasuresUsed = erased;
                    f.avlc = cand;
                    if (ParseAvlc(cand, f)) got.push_back(std::move(f));
                    break;
                }
            }
            if (got.size() > kept.size()) kept = std::move(got);
            if (!kept.empty() && static_cast<int>(kept.size()) == pieces) break;
        }
        if (kept.empty()) return false;
        // (iridium-analyzer addition) The burst's extent: the ramp's five symbols before the
        // unique word, to the end of the header and the D data octets plus their RS parity.
        const int lastSym = first + (HEADER_BITS + 8 * total + 2) / 3 + 1;
        const double burstFirst = lo + std::max(0, off - 5) * static_cast<double>(SamplesPerSymbol) + frac;
        const double burstLast = lo + lastSym * static_cast<double>(SamplesPerSymbol) + frac;
        for (auto& f : kept) {
            f.burstFirst = burstFirst;
            f.burstLast = burstLast;
            frames_++;
            if (cb) cb(f);
        }
        return true;
    };

    // Sampling phase. The concentration score is flat near its peak, so
    // the highest-scoring phase is not always the one that decides symbols
    // best -- two phases nearly a sample apart can score the same and
    // differ by an octet, which at the Reed-Solomon limit is the whole
    // frame. Search the period exhaustively, then keep the few distinct
    // peaks and let the frame check decide between them.
    double bestFrac = 0.0, bestScore = -1.0;
    for (int q = 0; q < SamplesPerSymbol; ++q) {
        const double sc = score(q, 3);
        if (sc > bestScore) { bestScore = sc; bestFrac = q; }
    }
    // A coarse pass on a third of the symbols is enough to reject noise;
    // only a span that looks like a signal earns the fine search.
    if (bestScore < 0.08) return;

    constexpr int FracSteps = SamplesPerSymbol * 8;
    std::vector<std::pair<double, double>> cand;   // (score, frac)
    cand.reserve(FracSteps);
    bestScore = -1.0;
    for (int q = 0; q < FracSteps; ++q) {
        const double frac = q / 8.0;
        const double sc = score(frac, 1);
        cand.emplace_back(sc, frac);
        if (sc > bestScore) { bestScore = sc; bestFrac = frac; }
    }
    if (bestScore < 0.05) return;

    // Keep peaks worth trying: strong enough to be plausible, and far
    // enough apart to be genuinely different sampling instants.
    std::sort(cand.begin(), cand.end(),
              [](const auto& a, const auto& b) { return a.first > b.first; });
    std::vector<double> fracs;
    for (const auto& [sc, fr] : cand) {
        if (static_cast<int>(fracs.size()) >= 4) break;
        if (sc < bestScore * 0.85) break;
        bool near = false;
        for (double have : fracs) {
            double d = std::fabs(have - fr);
            d = std::min(d, SamplesPerSymbol - d);      // the phase wraps
            if (d < 0.5) { near = true; break; }
        }
        if (!near) fracs.push_back(fr);
    }
    if (fracs.empty()) fracs.push_back(bestFrac);

    for (double tryFrac : fracs) {
        if (attempt(tryFrac)) return;
    }

    // On a short burst the clock score is flat and noisy, and the phase
    // that decodes can sit well away from every peak it offers: two 11-octet
    // frames at Chalmette decoded only at 6.9 and 7.4 samples, against
    // peaks near 0 and 9. Before giving up, sweep the whole symbol period.
    for (int q = 0; q < SamplesPerSymbol * 4; ++q) {
        const double frac = q / 4.0;
        bool tried = false;
        for (double have : fracs) {
            if (std::fabs(have - frac) < 0.125) { tried = true; break; }
        }
        if (!tried && attempt(frac)) return;
    }
}

}  // namespace Jetstream::Vdl2Receiver
