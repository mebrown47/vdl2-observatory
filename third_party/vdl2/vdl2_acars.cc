#include "vdl2_acars.hh"

#include <bitset>

// (iridium-analyzer) CyberEther's jetstream/config.hh is not vendored: the build defines
// JETSTREAM_LOADER_LIBACARS_AVAILABLE when libacars-2 is there (Makefile).

#ifdef JETSTREAM_LOADER_LIBACARS_AVAILABLE
#include <libacars/acars.h>
#include <libacars/libacars.h>
#include <libacars/reassembly.h>
#include <libacars/vstring.h>
#endif

namespace Jetstream::Vdl2Receiver {

namespace {

constexpr std::uint8_t STX = 0x02;
constexpr std::uint8_t ETX = 0x03;
constexpr std::uint8_t ETB = 0x17;

// ACARS characters are seven-bit ASCII with an odd parity bit on top. The
// parity is checked but not acted on: the AVLC FCS has already vouched for
// every octet, so a failure here says the sender set it wrong, not that
// the character is.
struct Reader {
    const std::uint8_t* data;
    std::size_t length;
    std::size_t pos = 0;
    int parityErrors = 0;

    bool empty() const { return pos >= length; }

    char next() {
        const std::uint8_t octet = data[pos++];
        if (std::bitset<8>(octet).count() % 2 == 0) {
            parityErrors++;
        }
        return static_cast<char>(octet & 0x7F);
    }

    std::string take(std::size_t count) {
        std::string out;
        for (std::size_t i = 0; i < count && !empty(); ++i) {
            out.push_back(next());
        }
        return out;
    }
};

}  // namespace

bool IsAcars(const std::uint8_t* info, std::size_t length) {
    return length >= 3 && info[0] == 0xFF && info[1] == 0xFF && info[2] == 0x01;
}

std::optional<AcarsMessage> ParseAcars(const std::uint8_t* info, std::size_t length) {
    if (!IsAcars(info, length)) {
        return std::nullopt;
    }

    // Mode, seven of registration, acknowledge, two of label, block id.
    constexpr std::size_t HeaderLength = 12;
    Reader reader{info + 3, length - 3};
    if (reader.length < HeaderLength) {
        return std::nullopt;
    }

    AcarsMessage message;
    message.mode = reader.next();
    message.registration = reader.take(7);
    message.acknowledge = reader.next();
    message.label = reader.take(2);
    message.blockId = reader.next();

    if (reader.empty()) {
        message.parityErrors = reader.parityErrors;
        return message;
    }

    // A block with no text goes straight to its terminator.
    const char start = reader.next();
    if (start != STX) {
        message.more = (start == ETB);
        message.parityErrors = reader.parityErrors;
        return message;
    }

    // Aircraft number their blocks with a digit and ground stations with a
    // letter, and only the aircraft's carry a message number and flight.
    const bool downlink = message.blockId >= '0' && message.blockId <= '9';
    if (downlink) {
        message.messageNumber = reader.take(4);
        message.flight = reader.take(6);
    }

    while (!reader.empty()) {
        const char c = reader.next();
        if (c == ETX || c == ETB) {
            message.more = (c == ETB);
            break;
        }
        message.text.push_back(c);
    }

    message.parityErrors = reader.parityErrors;
    return message;
}

bool AcarsContentDecoderAvailable() {
#ifdef JETSTREAM_LOADER_LIBACARS_AVAILABLE
    return true;
#else
    return false;
#endif
}

AcarsReassembler::AcarsReassembler() {
#ifdef JETSTREAM_LOADER_LIBACARS_AVAILABLE
    ctx = la_reasm_ctx_new();
#endif
}

AcarsReassembler::~AcarsReassembler() {
#ifdef JETSTREAM_LOADER_LIBACARS_AVAILABLE
    la_reasm_ctx_destroy(ctx);
#endif
}

std::optional<AcarsContent> DecodeAcarsContent(const std::uint8_t* info, std::size_t length,
                                               bool fromAircraft,
                                               AcarsReassembler* reassembler,
                                               std::uint64_t wallSeconds) {
#ifdef JETSTREAM_LOADER_LIBACARS_AVAILABLE
    if (!IsAcars(info, length)) {
        return std::nullopt;
    }

    // libacars times out a half-built message by this clock, so blocks that
    // never complete are forgotten rather than kept for ever.
    struct timeval rxTime{};
    rxTime.tv_sec = static_cast<time_t>(wallSeconds);
    la_reasm_ctx* ctx = reassembler != nullptr
                            ? static_cast<la_reasm_ctx*>(reassembler->context())
                            : nullptr;
    la_proto_node* root = la_acars_parse_and_reassemble(
        info + 3, static_cast<int>(length - 3),
        fromAircraft ? LA_MSG_DIR_AIR2GND : LA_MSG_DIR_GND2AIR, ctx, rxTime);
    if (root == nullptr) {
        return std::nullopt;
    }

    AcarsContent out;
    const auto* msg = static_cast<const la_acars_msg*>(root->data);
    if (msg != nullptr && !msg->err && msg->txt != nullptr) out.messageText = msg->txt;   // (vdl2-sniffer)
    if (ctx != nullptr && msg != nullptr && !msg->err) {
        switch (msg->reasm_status) {
            case LA_REASM_IN_PROGRESS:
                out.reassembly = AcarsContent::Reassembly::Partial;
                break;
            case LA_REASM_DUPLICATE:
                out.reassembly = AcarsContent::Reassembly::Repeat;
                break;
            case LA_REASM_COMPLETE:
                // A message of one block is reported as skipped, so this
                // is always the end of several.
                out.reassembly = AcarsContent::Reassembly::Complete;
                out.wholeText = msg->txt != nullptr ? msg->txt : "";
                break;
            default:
                break;
        }
    }

    // (vdl2-sniffer addition) The whole tree as JSON, root included.
    if (la_vstring* json = la_proto_tree_format_json(nullptr, root); json != nullptr) {
        out.treeJson = std::string(json->str);
        la_vstring_destroy(json, true);
    }

    // The root is the ACARS layer itself, which the table already shows as
    // columns and text. Only what libacars found beneath it is new.
    if (root->next != nullptr) {
        la_vstring* text = la_proto_tree_format_text(nullptr, root->next);
        if (text != nullptr) {
            out.tree = std::string(text->str);
            la_vstring_destroy(text, true);
        }
    }
    la_proto_tree_destroy(root);
    return out;
#else
    (void)info;
    (void)length;
    (void)fromAircraft;
    (void)reassembler;
    (void)wallSeconds;
    return std::nullopt;
#endif
}

}  // namespace Jetstream::Vdl2Receiver
