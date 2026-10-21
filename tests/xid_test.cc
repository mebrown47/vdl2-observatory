/*
 * AVLC frames as hex, one per line on stdin; the XID parse of each as JSON
 * on stdout ("null" when the frame is not a parseable XID). For
 * tests/xid_check.py.
 *
 * Copyright (c) 2026 Mike Brown
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "vdl2_xid.hh"

#include <cstdint>
#include <cstdio>
#include <iostream>
#include <string>
#include <vector>

static std::uint32_t bits28(const std::uint8_t* p) {
    std::uint32_t n = 0;
    for (int i = 0; i < 4; ++i) {
        const int v = p[i] >> 1;
        for (int k = 0; k < 7; ++k) n = (n << 1) | ((v >> k) & 1);
    }
    return n;
}

int main() {
    std::string line;
    while (std::getline(std::cin, line)) {
        std::vector<std::uint8_t> f;
        for (std::size_t i = 0; i + 1 < line.size(); i += 2) f.push_back((std::uint8_t)std::stoul(line.substr(i, 2), nullptr, 16));
        if (f.size() < 11 || (f[8] & ~0x10) != 0xAF) { puts("null"); continue; }
        const std::uint32_t src = bits28(f.data() + 4);
        auto x = Vdl2Xid::Parse(f.data() + 9, f.size() - 11, (src >> 27) & 1, (f[8] >> 4) & 1, (src >> 24) & 7);
        puts(x ? Vdl2Xid::ToJson(*x).c_str() : "null");
    }
    return 0;
}
