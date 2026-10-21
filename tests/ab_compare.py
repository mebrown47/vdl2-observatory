#!/usr/bin/env python3
# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""
A/B: vdl2-sniffer's frames against dumpvdl2's on the same capture.

    ab_compare.py OURS.json ORACLE.txt [--name NAME] [--quiet]

OURS.json is `vdl2-sniffer --json --raw` output; ORACLE.txt is dumpvdl2's
text output (a header line in brackets, then a hex dump of the AVLC frame,
FCS included). Frames are matched as (channel, AVLC octets) multisets:
dumpvdl2 run on a file stamps wall-clock time, so times are not comparable.

Prints one summary line, then every frame only dumpvdl2 decoded (the
regressions worth chasing). Exit status 1 when dumpvdl2 has a frame we
lack.
"""

import argparse
import collections
import json
import re
import sys

HDR = re.compile(r"^\[[^\]]+\] \[(\d+\.\d+)\] \[[^\]]*\] \[(-?[\d.]+) dB\]")


def ours(path):
    out = collections.Counter()
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        v = json.loads(line)["vdl2"]
        out[(int(v["freq"]), v["raw"])] += 1
    return out


def oracle(path):
    out = collections.Counter()
    snr = {}
    cur, octets = None, []

    def done():
        if cur is not None and octets:
            key = (cur[0], "".join(octets))
            out[key] += 1
            snr[key] = cur[1]

    for line in open(path, errors="replace"):
        m = HDR.match(line)
        if m:
            done()
            cur, octets = (int(round(float(m.group(1)) * 1e6)), float(m.group(2))), []
        elif cur is not None and line.startswith(" ") and "|" in line:
            octets += [t for t in line.split("|")[0].split() if re.fullmatch(r"[0-9a-f]{2}", t)]
        elif cur is not None and line.strip() and not line.startswith(" "):
            # first decoded line after the dump ends the octets
            done()
            cur, octets = None, []
    done()
    return out, snr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ours")
    ap.add_argument("oracle")
    ap.add_argument("--name", default="")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    us = ours(a.ours)
    them, snr = oracle(a.oracle)
    shared = sum((us & them).values())
    only_us = sum((us - them).values())
    only_them = them - us
    print(f"{a.name or a.ours:24s} ours {sum(us.values()):4d}  dumpvdl2 {sum(them.values()):4d}  "
          f"shared {shared:4d}  ours-only {only_us:4d}  dumpvdl2-only {sum(only_them.values()):3d}")
    if not a.quiet:
        for (freq, raw), n in sorted(only_them.items()):
            print(f"    dumpvdl2 only: {freq / 1e6:.3f} {snr[(freq, raw)]:5.1f} dB "
                  f"{len(raw) // 2:3d} oct x{n} {raw[:48]}")
    return 1 if only_them else 0


if __name__ == "__main__":
    sys.exit(main())
