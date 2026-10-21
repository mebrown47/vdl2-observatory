/*
 * VDL2 XID frames: link management between aircraft and ground stations
 *
 * Copyright (c) 2026 Mike Brown
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The information field of an AVLC XID frame is an ISO 8885 general
 * format: a format identifier (0x82), then groups -- a group identifier
 * and a two-octet length -- each holding parameters as identifier,
 * length, value. Group 0x80 carries the public HDLC parameters, group
 * 0xF0 the VDL ones.
 *
 * Decoded here are only the parameters whose encoding was confirmed
 * against dumpvdl2's decode of real frames (used as a black box, its
 * source not read); every other parameter is kept as identifier and raw
 * octets. Likewise only the XID types those frames establish are named.
 */

#ifndef VDL2_XID_HH
#define VDL2_XID_HH

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace Vdl2Xid {

struct Param {
    int group = 0;                 // 0x80 public, 0xF0 VDL
    int id = 0;
    std::vector<std::uint8_t> value;
};

struct Location {
    double lat = 0, lon = 0;       // degrees, 0.1 resolution
    std::optional<int> altFt;      // absent when the octet is implausible
};

struct Xid {
    // "Handoff Initiation" or "Handoff Response", or empty when the frame
    // is of a kind not yet confirmed on the air.
    std::string type;

    // public parameters
    std::string parameterSet;      // e.g. "8885:1993"
    std::vector<std::uint8_t> procedureClasses, hdlcOptions;

    // VDL parameters
    std::optional<int> connectionManagement, avlcOptions;
    std::optional<int> sequence, retry;
    std::string destinationAirport;
    std::optional<Location> aircraftLocation;
    std::vector<std::uint32_t> alternateStations;   // 24-bit addresses

    std::vector<Param> unknown;    // everything not decoded above
};

// info: the AVLC information field (after the control octet, FCS removed).
// response: the frame's C/R bit; poll: its P/F bit; sourceKind: the address
// type of the sender (1 aircraft, 4/5 ground station). Nothing when the
// field is not a well-formed general-format XID.
std::optional<Xid> Parse(const std::uint8_t* info, std::size_t length,
                         bool response, bool poll, int sourceKind);

// The parsed frame as a JSON object, for the live output and the archive.
std::string ToJson(const Xid& x);

}  // namespace Vdl2Xid

#endif
