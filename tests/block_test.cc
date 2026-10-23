/*
 * The decoder's filters keep their state across buffers, so how the input is
 * cut up must not change a single frame. Decodes the first SECONDS of a cu8
 * capture (1.05 MS/s, centred on 136.8125 MHz) twice: in 262144-sample
 * buffers, and in buffers of random length from 1 sample up. Frames, their
 * bytes and their burst positions must agree exactly.
 *
 *   vdl2-block-test CAPTURE.cu8 [SECONDS]      (default 120)
 *
 * Copyright (c) 2026 Mike Brown
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "third_party/vdl2/vdl2_decoder.hh"

#include <complex>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <vector>

namespace V = Jetstream::Vdl2Receiver;

struct Got {
    double freq, first, last;
    std::vector<std::uint8_t> avlc;
    bool operator==(const Got& o) const {
        return freq == o.freq && first == o.first && last == o.last && avlc == o.avlc;
    }
};

static std::vector<Got> decode(const std::vector<std::complex<float>>& iq, bool random) {
    const std::vector<double> channels = {136650000, 136700000, 136725000, 136775000,
                                          136800000, 136825000, 136875000, 136975000};
    V::Decoder dec(136812500, channels);
    std::vector<Got> got;
    auto cb = [&](const V::Frame& f) { got.push_back({f.frequency, f.burstFirst, f.burstLast, f.avlc}); };
    std::mt19937 rng(7);
    std::size_t at = 0;
    while (at < iq.size()) {
        std::size_t n = 262144;
        // Mostly short and odd lengths, now and then a long one.
        if (random) n = rng() % 8 ? 1 + rng() % 997 : 1 + rng() % 300000;
        if (n > iq.size() - at) n = iq.size() - at;
        dec.process(iq.data() + at, n, cb);
        at += n;
    }
    return got;
}

int main(int argc, char** argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s CAPTURE.cu8 [SECONDS]\n", argv[0]);
        return 2;
    }
    const double seconds = argc > 2 ? atof(argv[2]) : 120;
    FILE* f = fopen(argv[1], "rb");
    if (!f) { perror(argv[1]); return 2; }
    std::vector<std::complex<float>> iq;
    const std::size_t want = static_cast<std::size_t>(seconds * V::Decoder::RequiredSampleRate);
    unsigned char p[2];
    while (iq.size() < want && fread(p, 1, 2, f) == 2)
        iq.push_back({(p[0] - 127.5f) / 127.5f, (p[1] - 127.5f) / 127.5f});
    fclose(f);

    const auto whole = decode(iq, false);
    const auto split = decode(iq, true);
    printf("%zu samples: %zu frames in fixed buffers, %zu in random ones\n", iq.size(),
           whole.size(), split.size());
    if (whole.empty() || !(whole == split)) {
        printf("FAIL: %s\n", whole.empty() ? "no frames to compare" : "frames differ");
        return 1;
    }
    printf("PASS: identical frames and burst positions\n");
    return 0;
}
