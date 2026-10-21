#!/usr/bin/env python3
# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""
XID parse against dumpvdl2's decode of the same frames.

    xid_check.py XID_TEST_BINARY ORACLE.txt [ORACLE.txt ...]

Takes every XID frame from dumpvdl2's text output (--raw-frames), runs its
octets through vdl2-xid-test, and compares each field dumpvdl2 printed with
ours. Exit status 1 on any mismatch.
"""

import json
import re
import subprocess
import sys


def frames(paths):
    for p in paths:
        for block in open(p, errors="replace").read().split("\n\n"):
            if "AVLC type: U (XID)" not in block:
                continue
            octets, text = [], []
            for line in block.strip("\n").split("\n")[1:]:
                if re.match(r"^ ([0-9a-f]{2} )", line) and "|" in line:
                    octets += [t for t in line.split("|")[0].split() if re.fullmatch("[0-9a-f]{2}", t)]
                else:
                    text.append(line.strip())
            yield p.split("/")[-1], "".join(octets), text


def expected(text):
    """dumpvdl2's lines as the fields our JSON uses."""
    e = {}
    for t in text:
        k, _, v = t.partition(": ")
        if k == "XID":
            e["type"] = v
        elif k == "Parameter set ID" and v != "V":
            e["param_set"] = v
        elif k == "Procedure classes":
            e["proc_classes"] = v.replace(" ", "")
        elif k == "HDLC options":
            e["hdlc_opts"] = v.replace(" ", "")
        elif k == "Connection management":
            e["conn_mgmt"] = int(v, 16)
        elif k == "AVLC specific options":
            e["avlc_opts"] = int(v, 16)
        elif k == "XID sequencing":
            m = re.match(r"seq: (\d+) retry: (\d+)", v)
            e["seq"], e["retry"] = int(m.group(1)), int(m.group(2))
        elif k == "Destination airport":
            e["dst_airport"] = v
        elif k == "Aircraft location":
            m = re.match(r"([\d.]+)([NS]) ([\d.]+)([EW]) (\d+) ft", v)
            lat = float(m.group(1)) * (1 if m.group(2) == "N" else -1)
            lon = float(m.group(3)) * (1 if m.group(4) == "E" else -1)
            e["ac_location"] = {"lat": lat, "lon": lon, "alt_ft": int(m.group(5))}
        elif k == "Alternate ground stations":
            e["alt_gs"] = v.split()
    return e


def main():
    binary, paths = sys.argv[1], sys.argv[2:]
    got = list(frames(paths))
    out = subprocess.run([binary], input="\n".join(o for _, o, _ in got) + "\n",
                         capture_output=True, text=True, check=True).stdout.splitlines()
    bad = 0
    for (name, octets, text), line in zip(got, out):
        ours = json.loads(line) or {}
        exp = expected(text)
        diffs = []
        for k, v in exp.items():
            o = ours.get(k)
            if k == "ac_location" and o is not None and v["alt_ft"] > 60000:
                v = {"lat": v["lat"], "lon": v["lon"]}   # we drop implausible altitudes
            if o != v:
                diffs.append(f"{k}: dumpvdl2 {v!r} ours {o!r}")
        if ours.get("unknown"):
            diffs.append(f"undecoded parameters: {ours['unknown']}")
        if diffs:
            bad += 1
            print(f"MISMATCH {name} {octets[:24]}")
            for d in diffs:
                print("   ", d)
    print(f"{len(got)} XID frames, {len(got) - bad} match dumpvdl2, {bad} differ")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
