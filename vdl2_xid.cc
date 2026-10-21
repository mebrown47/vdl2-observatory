/*
 * VDL2 XID frames: link management between aircraft and ground stations
 *
 * Copyright (c) 2026 Mike Brown
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "vdl2_xid.hh"

#include <cstdio>

namespace Vdl2Xid {

namespace {

// An address as it sits in an AVLC address field: four octets, seven bits
// each above an extension bit, least significant bit first.
std::uint32_t Address(const std::uint8_t* p) {
    std::uint32_t n = 0;
    for (int i = 0; i < 4; ++i) {
        const int v = p[i] >> 1;
        for (int k = 0; k < 7; ++k) n = (n << 1) | ((v >> k) & 1);
    }
    return n & 0xFFFFFF;
}

int Signed12(int v) { return v >= 0x800 ? v - 0x1000 : v; }

std::string Hex(const std::vector<std::uint8_t>& v) {
    std::string s;
    char b[4];
    for (auto x : v) { snprintf(b, sizeof b, "%02x", x); s += b; }
    return s;
}

std::string Quote(const std::string& s) {
    std::string o = "\"";
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') { o += '\\'; o += (char)c; }
        else if (c < 0x20 || c >= 0x7f) { char b[8]; snprintf(b, sizeof b, "\\u%04x", c); o += b; }
        else o += (char)c;
    }
    return o + "\"";
}

bool Printable(const std::vector<std::uint8_t>& v) {
    for (auto c : v) if (c < 0x20 || c >= 0x7f) return false;
    return !v.empty();
}

void Vdl(Xid& x, const Param& p) {
    const auto& v = p.value;
    switch (p.id) {
        case 0x00:   // parameter set identifier, "V"
            if (v.size() == 1 && v[0] == 'V') return;
            break;
        case 0x01:   // connection management
            if (v.size() == 1) { x.connectionManagement = v[0]; return; }
            break;
        case 0x03:   // XID sequencing: sequence in the low nibble, retry count above
            if (v.size() == 1) { x.sequence = v[0] & 0x0F; x.retry = v[0] >> 4; return; }
            break;
        case 0x04:   // AVLC specific options
            if (v.size() == 1) { x.avlcOptions = v[0]; return; }
            break;
        case 0x82:   // alternate ground stations, four address octets each
            if (!v.empty() && v.size() % 4 == 0) {
                for (std::size_t i = 0; i < v.size(); i += 4) x.alternateStations.push_back(Address(&v[i]));
                return;
            }
            break;
        case 0x83:   // destination airport, ICAO code
            if (Printable(v)) { x.destinationAirport.assign(v.begin(), v.end()); return; }
            break;
        case 0x84:   // aircraft location: 12-bit latitude, 12-bit longitude
            if (v.size() == 4) {   // (signed, 0.1 degree), 8-bit altitude (1000 ft)
                Location l;
                l.lat = Signed12((v[0] << 4) | (v[1] >> 4)) / 10.0;
                l.lon = Signed12(((v[1] & 0x0F) << 8) | v[2]) / 10.0;
                // A handoff response was seen with 0xc0 here: 192,000 ft.
                if (v[3] <= 60) l.altFt = v[3] * 1000;
                if (l.lat >= -90 && l.lat <= 90 && l.lon >= -180 && l.lon <= 180) {
                    x.aircraftLocation = l;
                    return;
                }
            }
            break;
    }
    x.unknown.push_back(p);
}

void Public(Xid& x, const Param& p) {
    switch (p.id) {
        case 0x01:
            if (Printable(p.value)) { x.parameterSet.assign(p.value.begin(), p.value.end()); return; }
            break;
        case 0x02: x.procedureClasses = p.value; return;
        case 0x03: x.hdlcOptions = p.value; return;
    }
    x.unknown.push_back(p);
}

}  // namespace

std::optional<Xid> Parse(const std::uint8_t* info, std::size_t length,
                         bool response, bool poll, int sourceKind) {
    if (length < 4 || info[0] != 0x82) return std::nullopt;
    Xid x;
    std::size_t i = 1;
    while (i < length) {
        if (i + 3 > length) return std::nullopt;
        const int group = info[i];
        const std::size_t glen = (std::size_t(info[i + 1]) << 8) | info[i + 2];
        i += 3;
        if (i + glen > length) return std::nullopt;
        std::size_t j = i;
        while (j < i + glen) {
            if (j + 2 > i + glen) return std::nullopt;
            Param p;
            p.group = group;
            p.id = info[j];
            const std::size_t plen = info[j + 1];
            if (j + 2 + plen > i + glen) return std::nullopt;
            p.value.assign(info + j + 2, info + j + 2 + plen);
            j += 2 + plen;
            if (group == 0x80) Public(x, p);
            else if (group == 0xF0) Vdl(x, p);
            else x.unknown.push_back(p);
        }
        i += glen;
    }

    // Every handoff seen so far came from an aircraft with P set and bit 0
    // of connection management set: commands are initiations, responses
    // answer a ground station's request. Anything else is left unnamed.
    if (sourceKind == 1 && poll && x.connectionManagement && (*x.connectionManagement & 1))
        x.type = response ? "Handoff Response" : "Handoff Initiation";
    return x;
}

std::string ToJson(const Xid& x) {
    std::string j = "{";
    bool first = true;
    auto key = [&](const char* k) { j += first ? "\"" : ",\""; j += k; j += "\":"; first = false; };
    char b[64];
    if (!x.type.empty()) { key("type"); j += Quote(x.type); }
    if (!x.parameterSet.empty()) { key("param_set"); j += Quote(x.parameterSet); }
    if (!x.procedureClasses.empty()) { key("proc_classes"); j += Quote(Hex(x.procedureClasses)); }
    if (!x.hdlcOptions.empty()) { key("hdlc_opts"); j += Quote(Hex(x.hdlcOptions)); }
    if (x.connectionManagement) { key("conn_mgmt"); j += std::to_string(*x.connectionManagement); }
    if (x.sequence) { key("seq"); j += std::to_string(*x.sequence); key("retry"); j += std::to_string(*x.retry); }
    if (x.avlcOptions) { key("avlc_opts"); j += std::to_string(*x.avlcOptions); }
    if (!x.destinationAirport.empty()) { key("dst_airport"); j += Quote(x.destinationAirport); }
    if (x.aircraftLocation) {
        key("ac_location");
        snprintf(b, sizeof b, "{\"lat\":%.1f,\"lon\":%.1f", x.aircraftLocation->lat, x.aircraftLocation->lon);
        j += b;
        if (x.aircraftLocation->altFt) j += ",\"alt_ft\":" + std::to_string(*x.aircraftLocation->altFt);
        j += "}";
    }
    if (!x.alternateStations.empty()) {
        key("alt_gs");
        j += "[";
        for (std::size_t i = 0; i < x.alternateStations.size(); ++i) {
            snprintf(b, sizeof b, "%s\"%06X\"", i ? "," : "", x.alternateStations[i]);
            j += b;
        }
        j += "]";
    }
    if (!x.unknown.empty()) {
        key("unknown");
        j += "[";
        for (std::size_t i = 0; i < x.unknown.size(); ++i) {
            snprintf(b, sizeof b, "%s{\"group\":%d,\"id\":%d,\"hex\":", i ? "," : "", x.unknown[i].group, x.unknown[i].id);
            j += b + Quote(Hex(x.unknown[i].value)) + "}";
        }
        j += "]";
    }
    return j + "}";
}

}  // namespace Vdl2Xid
