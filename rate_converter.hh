// Copyright (c) 2026 Mike Brown
// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef VDL2_SNIFFER_RATE_CONVERTER_HH
#define VDL2_SNIFFER_RATE_CONVERTER_HH

#include <complex>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

// Any input rate to the decoder's 1.05 MS/s, for radios that can't produce it
// (Airspy R2 2.5/10 MS/s, HackRF 2-20 MS/s, Airspy HF+ 912 kS/s) and for
// recordings at other rates. The design is the RTL-SDR Workbench's channel
// tap (usb/tap.js), which feeds dumpvdl2 there:
//
//   mix   the plan's centre to DC
//   1     when the input is 8x the output or more, a cheap decimating FIR that
//         only keeps the channels clear of what folds onto them
//   2     a decimating FIR to between 2 and 4 times the output rate, cutting
//         everything well outside the channels
//   3     cubic (Catmull-Rom) interpolation to the exact output rate
//
// The filters are sized from the channels in use (passband = the farthest
// channel's edge from the centre), not from the whole output band, so the
// US plan's +-175 kHz needs about a third of the taps tap.js uses for its
// +-400 kHz. The FIRs run on GCC vector types, AVX2 where the CPU has it.
//
// The output lags the input by the two FIRs' group delay, a few
// microseconds (delaySeconds()); frame times are kept to the millisecond.
class RateConverter {
public:
    using cf = std::complex<float>;

    // passbandHz: the farthest any channel's edge lies from centre + shiftHz.
    RateConverter(double inRate, double outRate, double shiftHz, double passbandHz);

    void process(const cf* x, std::size_t n, std::vector<cf>& out);

    double delaySeconds() const { return delay_; }
    // For the start-up line: "10 MS/s /2 (13 taps) /2 (79 taps) -> 2.5 MS/s, cubic to 1.05 MS/s"
    std::string describe() const;

private:
    struct Stage {
        int factor = 1;
        std::vector<float> taps;
        std::vector<float> re, im;           // input not yet used up
        std::vector<float> rowRe, rowIm;     // polyphase scratch
        std::vector<std::size_t> at;
        std::vector<float> outRe, outIm;
        void run(const float* xr, const float* xi, std::size_t n);   // appends to re/im, fills out*
    };

    double inRate_, outRate_, midRate_, ratio_, delay_ = 0;
    bool mix_ = false;
    double step_ = 0, phase_ = 0;            // radians per input sample, and now
    std::vector<cf> rot_;                    // e^{-j step k} for one block
    std::vector<float> mixRe_, mixIm_;
    Stage s1_, s2_;
    bool useS1_ = false, useS2_ = false;
    std::vector<float> histRe_, histIm_;     // stage-3 input: the last samples, then the new ones
    double t_ = 0;                           // next output's position in histRe_ (in samples)
};

#endif
