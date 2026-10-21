#ifndef JETSTREAM_DOMAINS_DSP_VDL2_VDL2_RS_HH
#define JETSTREAM_DOMAINS_DSP_VDL2_VDL2_RS_HH

#include <cstdint>
#include <vector>

// RS(255,249) over GF(256) as VDL Mode 2 uses it.
//
// Primitive polynomial x^8 + x^7 + x^2 + x + 1. The generator is the
// product of (x - alpha^i) for i = 120..125: the standard renders those
// limits as 20..125, which would be 106 parity symbols where six are
// needed, and 120 is the only offset that makes the syndromes of a
// known-good block vanish.
//
// Six parity symbols correct three errors at unknown positions or six at
// known ones. That distinction earns its keep here: a block of 3..30 data
// octets transmits only the first two of its six parity octets, and the
// other four must be entered as erasures or nothing short decodes.

namespace Jetstream::Vdl2Receiver {

class ReedSolomon {
 public:
    static constexpr int Parity = 6;
    static constexpr int BlockData = 249;
    static constexpr int BlockTotal = 255;

    ReedSolomon();

    // Corrects in place. `erasures` are codeword indices already known bad.
    // Returns the number of errors it had to find itself, or -1 if the
    // pattern is beyond the code. Erasure positions are not counted: they
    // were handed to it, and counting them makes a clean short frame look
    // heavily corrected.
    int correct(std::vector<std::uint8_t>& codeword,
                const std::vector<int>& erasures = {}) const;

    bool clean(const std::vector<std::uint8_t>& codeword) const;

    // Writes the six parity octets over positions 249..254. A receiver
    // never needs this; the tests do, and a decoder that cannot be handed
    // a known-good codeword cannot be checked at all.
    void encode(std::vector<std::uint8_t>& codeword) const;

 private:
    std::uint8_t exp_[512];
    std::uint8_t log_[256];

    std::uint8_t mul(std::uint8_t a, std::uint8_t b) const;
    std::uint8_t div(std::uint8_t a, std::uint8_t b) const;
    std::uint8_t inv(std::uint8_t a) const;
    std::uint8_t pow(std::uint8_t a, int n) const;
    std::vector<std::uint8_t> polyMul(const std::vector<std::uint8_t>& p,
                                      const std::vector<std::uint8_t>& q) const;
    std::uint8_t polyEval(const std::vector<std::uint8_t>& p, std::uint8_t x) const;
    std::vector<std::uint8_t> syndromes(const std::vector<std::uint8_t>& cw) const;
};

}  // namespace Jetstream::Vdl2Receiver

#endif
