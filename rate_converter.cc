// Copyright (c) 2026 Mike Brown
// SPDX-License-Identifier: GPL-3.0-or-later
#include "rate_converter.hh"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

namespace {

// Blackman-windowed sinc, unity gain at DC: flat to cutoff - transition/2,
// about 74 dB down from cutoff + transition/2.
std::vector<float> lowpass(double cutoff, double rate, double transition, int maxTaps) {
    int n = (int)std::ceil(5.5 * rate / transition) | 1;
    n = std::min(n, maxTaps | 1);
    std::vector<float> h(n);
    const double m = (n - 1) / 2.0, fc = cutoff / rate;
    double sum = 0;
    std::vector<double> hd(n);
    for (int i = 0; i < n; i++) {
        const double x = i - m;
        const double s = x == 0 ? 2 * fc : std::sin(2 * M_PI * fc * x) / (M_PI * x);
        const double w = 0.42 - 0.5 * std::cos(2 * M_PI * i / (n - 1)) + 0.08 * std::cos(4 * M_PI * i / (n - 1));
        sum += hd[i] = s * w;
    }
    for (int i = 0; i < n; i++) h[i] = (float)(hd[i] / sum);
    return h;
}

// out[i] = sum over t of x[at[t] + i] * h[t], NV vectors of outputs at once
// (the decoder's FirBlocks, without its bit-exactness constraint).
template <class V, std::size_t NV>
inline __attribute__((always_inline)) void FirBlocks(const float* h, std::size_t taps, const std::size_t* at,
                                                     const float* xRe, const float* xIm, std::size_t n,
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
        float re = 0, im = 0;
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
__attribute__((target("avx2"))) void FirAvx2(const float* h, std::size_t taps, const std::size_t* at,
                                             const float* xRe, const float* xIm, std::size_t n, float* outRe,
                                             float* outIm) {
    FirBlocks<Float8, 4>(h, taps, at, xRe, xIm, n, outRe, outIm);
}
const bool HaveAvx2 = __builtin_cpu_supports("avx2");
#endif

void Fir(const std::vector<float>& h, const std::size_t* at, const float* xRe, const float* xIm, std::size_t n,
         float* outRe, float* outIm) {
#if defined(__AVX2__)
    FirBlocks<Float8, 4>(h.data(), h.size(), at, xRe, xIm, n, outRe, outIm);
#else
#if defined(__x86_64__)
    if (HaveAvx2) return FirAvx2(h.data(), h.size(), at, xRe, xIm, n, outRe, outIm);
#endif
    FirBlocks<Float4, 6>(h.data(), h.size(), at, xRe, xIm, n, outRe, outIm);
#endif
}

constexpr std::size_t MixBlock = 4096;

}  // namespace

// Decimating FIR: output m is the sum over t of taps[t] * x[m * factor + t].
// The input is laid out as factor polyphase rows (row r holds x[r + k factor]),
// so every tap reads a contiguous run and the outputs vectorise.
void RateConverter::Stage::run(const float* xr, const float* xi, std::size_t n) {
    re.insert(re.end(), xr, xr + n);
    im.insert(im.end(), xi, xi + n);
    const std::size_t T = taps.size(), D = (std::size_t)factor, len = re.size();
    const std::size_t count = len >= T ? (len - T) / D + 1 : 0;
    outRe.resize(count);
    outIm.resize(count);
    if (!count) return;
    at.resize(T);
    if (D == 1) {
        for (std::size_t t = 0; t < T; t++) at[t] = t;
        Fir(taps, at.data(), re.data(), im.data(), count, outRe.data(), outIm.data());
    } else {
        const std::size_t row = count + (T - 1) / D + 1;
        rowRe.assign(D * row, 0.0f);
        rowIm.assign(D * row, 0.0f);
        for (std::size_t r = 0; r < D; r++)
            for (std::size_t k = 0, i = r; k < row && i < len; k++, i += D) {
                rowRe[r * row + k] = re[i];
                rowIm[r * row + k] = im[i];
            }
        for (std::size_t t = 0; t < T; t++) at[t] = (t % D) * row + t / D;
        Fir(taps, at.data(), rowRe.data(), rowIm.data(), count, outRe.data(), outIm.data());
    }
    re.erase(re.begin(), re.begin() + (long)(count * D));
    im.erase(im.begin(), im.begin() + (long)(count * D));
}

RateConverter::RateConverter(double inRate, double outRate, double shiftHz, double passbandHz)
    : inRate_(inRate), outRate_(outRate) {
    const double P = passbandHz;
    if (std::fabs(shiftHz) > 0.5) {
        mix_ = true;
        step_ = -2 * M_PI * shiftHz / inRate;
        rot_.resize(MixBlock);
        for (std::size_t k = 0; k < MixBlock; k++) rot_[k] = std::polar(1.0f, (float)std::fmod(step_ * (double)k, 2 * M_PI));
    }
    double rate = inRate;
    // 1: only what folds onto the channels after decimating by d1 must go.
    const int d1 = (int)std::floor(inRate / (4 * outRate));
    if (d1 >= 2) {
        const double r1 = inRate / d1, stop = r1 - P;
        s1_.factor = d1;
        s1_.taps = lowpass((P + stop) / 2, inRate, stop - P, 1023);
        useS1_ = true;
        delay_ += (s1_.taps.size() - 1) / 2.0 / inRate;
        rate = r1;
    }
    // 2: to 2-4x the output, everything from half the output rate up gone (or
    // from 100 kHz past the channels, for a channel set wider than that).
    const int d2 = std::max(1, (int)std::floor(rate / (2 * outRate)));
    const double stop2 = std::min(std::max(0.5 * outRate, P + 0.1 * outRate), outRate - P);
    if (d2 > 1 || stop2 < rate / 2) {
        s2_.factor = d2;
        s2_.taps = lowpass((P + stop2) / 2, rate, stop2 - P, 1023);
        useS2_ = true;
        delay_ += (s2_.taps.size() - 1) / 2.0 / rate;
    }
    // (A radio slower than that, the HF+ at 912 kS/s, is band-limited already.)
    midRate_ = rate / d2;
    ratio_ = midRate_ / outRate;
    histRe_.assign(1, 0.0f);   // sample -1, so the first output can interpolate
    histIm_.assign(1, 0.0f);
    t_ = 1;
}

std::string RateConverter::describe() const {
    char b[200];
    std::string s;
    snprintf(b, sizeof b, "%.4g MS/s", inRate_ / 1e6);
    s = b;
    if (useS1_) { snprintf(b, sizeof b, " /%d (%zu taps)", s1_.factor, s1_.taps.size()); s += b; }
    if (useS2_) {
        if (s2_.factor > 1) snprintf(b, sizeof b, " /%d (%zu taps)", s2_.factor, s2_.taps.size());
        else snprintf(b, sizeof b, " filtered (%zu taps)", s2_.taps.size());
        s += b;
    }
    if (std::fabs(midRate_ - inRate_) > 0.5) { snprintf(b, sizeof b, " -> %.4g MS/s", midRate_ / 1e6); s += b; }
    snprintf(b, sizeof b, ", cubic to %.4g MS/s", outRate_ / 1e6);
    return s + b;
}

void RateConverter::process(const cf* x, std::size_t n, std::vector<cf>& out) {
    mixRe_.resize(n);
    mixIm_.resize(n);
    if (mix_) {
        for (std::size_t i0 = 0; i0 < n; i0 += MixBlock) {
            const std::size_t m = std::min(MixBlock, n - i0);
            const float br = (float)std::cos(phase_), bi = (float)std::sin(phase_);
            for (std::size_t k = 0; k < m; k++) {
                const float wr = br * rot_[k].real() - bi * rot_[k].imag();
                const float wi = br * rot_[k].imag() + bi * rot_[k].real();
                const float xr = x[i0 + k].real(), xi = x[i0 + k].imag();
                mixRe_[i0 + k] = xr * wr - xi * wi;
                mixIm_[i0 + k] = xr * wi + xi * wr;
            }
            phase_ = std::fmod(phase_ + step_ * (double)m, 2 * M_PI);
        }
    } else {
        for (std::size_t i = 0; i < n; i++) { mixRe_[i] = x[i].real(); mixIm_[i] = x[i].imag(); }
    }
    const float *r = mixRe_.data(), *q = mixIm_.data();
    std::size_t m = n;
    if (useS1_) { s1_.run(r, q, m); r = s1_.outRe.data(); q = s1_.outIm.data(); m = s1_.outRe.size(); }
    if (useS2_) { s2_.run(r, q, m); r = s2_.outRe.data(); q = s2_.outIm.data(); m = s2_.outRe.size(); }

    // 3: Catmull-Rom through samples i-1 .. i+2 for each output at t in [i, i+1).
    histRe_.insert(histRe_.end(), r, r + m);
    histIm_.insert(histIm_.end(), q, q + m);
    const float* hr = histRe_.data();
    const float* hi = histIm_.data();
    const double last = (double)histRe_.size() - 3;
    double t = t_;
    while (t < last) {
        const std::size_t i = (std::size_t)t;
        const float f = (float)(t - (double)i), f2 = f * f, f3 = f2 * f;
        const float w0 = -0.5f * f3 + f2 - 0.5f * f, w1 = 1.5f * f3 - 2.5f * f2 + 1;
        const float w2 = -1.5f * f3 + 2 * f2 + 0.5f * f, w3 = 0.5f * f3 - 0.5f * f2;
        out.emplace_back(w0 * hr[i - 1] + w1 * hr[i] + w2 * hr[i + 1] + w3 * hr[i + 2],
                         w0 * hi[i - 1] + w1 * hi[i] + w2 * hi[i + 1] + w3 * hi[i + 2]);
        t += ratio_;
    }
    const std::size_t drop = (std::size_t)t - 1;   // keep sample i-1 for the next output
    histRe_.erase(histRe_.begin(), histRe_.begin() + (long)drop);
    histIm_.erase(histIm_.begin(), histIm_.begin() + (long)drop);
    t_ = t - (double)drop;
}
