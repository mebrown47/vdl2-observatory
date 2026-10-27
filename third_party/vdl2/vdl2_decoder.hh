#ifndef JETSTREAM_DOMAINS_DSP_VDL2_VDL2_DECODER_HH
#define JETSTREAM_DOMAINS_DSP_VDL2_VDL2_DECODER_HH

#include <complex>
#include <cstdint>
#include <functional>
#include <string>
#include <vector>

#include "vdl2_rs.hh"

// A self-contained VDL Mode 2 receiver: complex baseband in, AVLC frames
// out. Depends on nothing but the standard library, so it can be tested
// against a recorded capture on its own.
//
// D8PSK, 10 500 symbols/s, 31.5 kbit/s, in 25 kHz channels. A burst opens
// with five ramp symbols, a sixteen-symbol unique word, then a 25-bit
// header carrying the transmission length. Everything after the unique
// word is scrambled by a 15-stage generator; the data is cut into
// 249-octet blocks, Reed-Solomon protected, and interleaved across them.

namespace Jetstream::Vdl2Receiver {

struct Frame {
    double frequency = 0.0;       // channel it arrived on, Hz
    float snr = 0.0f;             // dB above the channel's noise floor
    std::uint32_t source = 0;     // ICAO address
    std::uint32_t dest = 0;
    std::uint8_t sourceKind = 0;  // 1 aircraft, 5 ground station
    std::uint8_t destKind = 0;
    std::uint8_t control = 0;
    int errorsCorrected = 0;
    int erasuresUsed = 0;
    std::vector<std::uint8_t> avlc;   // the frame, flags and stuffing removed
    // (iridium-analyzer addition) Where the burst carrying this frame was, in the channel's
    // 105 kS/s samples (Decoder::ringSampleToInput turns them into input samples): its first
    // ramp symbol and the end of its last data symbol, from the unique word's position and the
    // header's transmission length. Every frame of one burst carries the same two.
    double burstFirst = 0.0, burstLast = 0.0;
    // (vdl2-sniffer addition) The burst's carrier offset from the channel, in ppm of the
    // channel frequency, from the phase drift across the unique word: dumpvdl2's
    // freq_skew. Averaged over many aircraft it is the receiver's own tuning error.
    float ppm = 0.0f;
};

class Decoder {
 public:
    // 1.05 MS/s is 105000 x 10, which is the rate the standard's symbol
    // rate implies and the lowest an RTL-SDR can legally produce -- there
    // is no permitted rate between 300 kS/s and 900 kS/s. Channel offsets
    // are all multiples of 12.5 kHz, and 12.5 kHz divides 1.05 MHz exactly
    // 84 times, so every mixer closes on itself with no accumulated phase.
    static constexpr double RequiredSampleRate = 1050000.0;
    static constexpr int SymbolRate = 10500;
    static constexpr int Decimation = 10;
    static constexpr int SamplesPerSymbol = 10;
    static constexpr int MixerPeriod = 84;

    using Callback = std::function<void(const Frame&)>;

    Decoder(double centreHz, const std::vector<double>& channels);

    // Single channel, already tuned and already at NarrowSampleRate --
    // which is what a SpyServer node hands back when asked for one VDL2
    // channel. The mixer, the anti-alias filter and the decimator all
    // become no-ops; everything downstream of them is unchanged, because
    // it always ran at this rate anyway.
    static constexpr double NarrowSampleRate = RequiredSampleRate / Decimation;
    explicit Decoder(double channelHz);

    // Streaming: filter, envelope and burst state persist across calls, so
    // a burst straddling two buffers is still decoded. Never blocks.
    void process(const std::complex<float>* iq, std::size_t count, const Callback& cb);
    void reset();

    // (iridium-analyzer addition) The input sample a channel sample (Frame::burstFirst /
    // burstLast) shows, through the decimation and both FIR delays (121 taps each, linear
    // phase): wide, input 10m + 9 less 60 (anti-alias) less 600 (channel filter, 60 at
    // 105 kS/s); narrow, m less 60.
    double ringSampleToInput(double m) const {
        return narrow_ ? m - 60.0 : 10.0 * m + 9.0 - 60.0 - 600.0;
    }
        std::uint64_t bursts() const { return bursts_; }
    std::uint64_t frames() const { return frames_; }

 private:
    struct Channel {
        double frequency = 0.0;
        int mixerStep = 0;
        int mixerPhase = 0;

        // (vdl2-sniffer) Filter input not yet used up, real and imaginary apart: the
        // mixed samples from the oldest the next anti-alias output needs, and the
        // channel filter's last 120 inputs before the new ones.
        std::vector<float> aaRe, aaIm;
        std::vector<float> chRe, chIm;

        std::vector<std::complex<float>> ring;     // filtered, at 105 kS/s
        std::size_t ringPos = 0;
        std::uint64_t ringCount = 0;

        std::vector<float> seed;                   // first magnitudes, for the floor
        float envelope = 0.0f;
        float floorEst = 0.0f;
        float peak = 0.0f;
        bool inBurst = false;
        std::uint64_t burstStart = 0;
        std::uint64_t quietFor = 0;
    };

    void channelFilter(Channel& c, const Callback& cb);
    void pushFiltered(Channel& c, std::complex<float> f, const Callback& cb);
    void tryBurst(Channel& c, std::uint64_t from, std::uint64_t to, const Callback& cb);

    double centre_;
    std::vector<Channel> channels_;
    std::vector<float> aaTaps_, chTaps_;
    std::vector<std::complex<float>> mixer_;
    std::vector<float> polyRe_, polyIm_, outRe_, outIm_;   // filter scratch
    std::vector<std::size_t> tapAt_;
    bool narrow_ = false;
    ReedSolomon rs_;
    std::uint64_t bursts_ = 0, frames_ = 0;
};

// Exposed for tests.
// A burst's bit stream after the opening flag, still stuffed, split at every
// flag and destuffed: one octet vector per AVLC frame it carried.
std::vector<std::vector<std::uint8_t>> AvlcPieces(const std::vector<int>& bits);
std::uint16_t Crc16X25(const std::uint8_t* data, std::size_t n);
bool ParseAvlc(const std::vector<std::uint8_t>& frame, Frame& out);

}  // namespace Jetstream::Vdl2Receiver

#endif
