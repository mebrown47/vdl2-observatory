#ifndef JETSTREAM_DOMAINS_DSP_VDL2_ACARS_HH
#define JETSTREAM_DOMAINS_DSP_VDL2_ACARS_HH

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>

namespace Jetstream::Vdl2Receiver {

// One ACARS block as carried in an AVLC information field. Most of what an
// airline sends over VDL2 is still ACARS, wrapped whole: three octets that
// say so, then the same character-oriented block ARINC 618 defines for the
// older 2400 bit/s channel.
struct AcarsMessage {
    char mode = 0;
    std::string registration;     // seven characters, dot-padded on the left
    char acknowledge = 0;
    std::string label;            // two characters, says what the text is
    char blockId = 0;
    std::string messageNumber;    // downlinks only
    std::string flight;           // downlinks only
    std::string text;
    bool more = false;            // ended ETB: another block follows
    int parityErrors = 0;         // characters whose odd parity failed
};

// The prefix that marks an information field as ACARS.
bool IsAcars(const std::uint8_t* info, std::size_t length);

// Parses an information field, which is the AVLC frame with its eight
// address octets, the control octet and the FCS taken off. Returns nothing
// if the field is not ACARS or is too short to hold the fixed header.
std::optional<AcarsMessage> ParseAcars(const std::uint8_t* info, std::size_t length);

// Multi-block messages, put back together. An aircraft splits anything
// longer than one block's 220 characters across several, and MIAM and
// FANS-1/A only decode once they are whole. One of these lives as long as
// the receiver does, and every block goes through it in order of arrival.
class AcarsReassembler {
 public:
    AcarsReassembler();
    ~AcarsReassembler();
    AcarsReassembler(const AcarsReassembler&) = delete;
    AcarsReassembler& operator=(const AcarsReassembler&) = delete;

    void* context() const { return ctx; }

 private:
    void* ctx = nullptr;   // la_reasm_ctx when libacars is built in
};

// What libacars made of one block.
struct AcarsContent {
    enum class Reassembly {
        None,       // a single-block message, or no reassembler was given
        Partial,    // one block of several; the rest are still to come
        Complete,   // the last block arrived, and the message is whole
        Repeat,     // a block already heard, sent again
    };
    Reassembly reassembly = Reassembly::None;
    std::string wholeText;             // Complete only: every block's text
    std::optional<std::string> tree;   // what the text carries, if anything
    // (vdl2-sniffer addition) The whole tree, ACARS layer included, as libacars's JSON
    // ({"acars":{...}}): the archive's "dec" field and dumpvdl2's avlc.acars object.
    std::optional<std::string> treeJson;
    // (vdl2-sniffer addition) The message text as libacars reads it, with the
    // sub-label prefix (e.g. "#M1B") taken off; for a completed multi-block
    // message, all of it.
    std::string messageText;
};

// What the ACARS text carries, decoded by libacars when the build has it:
// FANS-1/A CPDLC and ADS-C, MIAM, media advisories and the rest, as the
// indented tree libacars prints. With a reassembler, a block that ends a
// multi-block message decodes the whole message. Returns nothing when
// libacars is absent or the field is not ACARS.
std::optional<AcarsContent> DecodeAcarsContent(const std::uint8_t* info, std::size_t length,
                                               bool fromAircraft,
                                               AcarsReassembler* reassembler = nullptr,
                                               std::uint64_t wallSeconds = 0);

// Whether DecodeAcarsContent can say anything at all in this build.
bool AcarsContentDecoderAvailable();

}  // namespace Jetstream::Vdl2Receiver

#endif  // JETSTREAM_DOMAINS_DSP_VDL2_ACARS_HH
