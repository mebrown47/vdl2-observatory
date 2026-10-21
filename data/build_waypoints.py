#!/usr/bin/env python3
# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Rebuild data/waypoints.csv with the FAA's current fix positions.

    build_waypoints.py FAA_CSV [--base data/waypoints.csv] [--out data/waypoints.csv]

FAA_CSV is the FAA fix list (columns fix_identifier, state, description;
the position is the DDD-MM-SS.ssssN DDD-MM-SS.ssssW pair in the
description). It is public domain. The base is the existing global file
(X-Plane earth_fix.dat, GPL v3; Global Aviation Waypoints, MIT).

For every fix the FAA lists, the FAA position wins: base entries with the
same name inside the FAA's area (any 1-degree cell holding an FAA fix, or
next to one) are dropped as stale, since fix names get reassigned and the
base had thousands placed on the wrong side of the country. Base entries
with that name outside the FAA's area are different fixes that happen to
share it, and are kept. Fixes the FAA does not list are kept as they are.
Lines the loader cannot use (identifiers outside 2-5 characters, broken
rows) are dropped. The output is sorted, one IDENT,LAT,LON per line.

Running it again on its own output with the same FAA file changes nothing.
"""

import argparse
import csv
import math
import re
import sys

DMS = re.compile(r"(\d{2})-(\d{2})-([\d.]+)([NS]) (\d{3})-(\d{2})-([\d.]+)([EW])")
IDENT = re.compile(r"^[A-Z0-9]{2,5}$")


def faa_fixes(path):
    fixes = {}
    bad = 0
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            ident = r["fix_identifier"].strip()
            m = DMS.search(r["description"])
            if not IDENT.match(ident) or not m:
                bad += 1
                continue
            lat = int(m[1]) + int(m[2]) / 60 + float(m[3]) / 3600
            lon = int(m[5]) + int(m[6]) / 60 + float(m[7]) / 3600
            fixes[ident] = (-lat if m[4] == "S" else lat,
                            -lon if m[8] == "W" else lon)
    return fixes, bad


def base_fixes(path):
    rows, bad = [], 0
    with open(path) as f:
        for line in f:
            p = line.rstrip("\r\n").split(",")
            try:
                if len(p) != 3 or not IDENT.match(p[0]):
                    raise ValueError
                lat, lon = float(p[1]), float(p[2])
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ValueError
            except ValueError:
                bad += 1
                continue
            rows.append((p[0], lat, lon))
    return rows, bad


def cell(lat, lon):
    return math.floor(lat), math.floor(lon) % 360


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    ap.add_argument("faa")
    ap.add_argument("--base", default="data/waypoints.csv")
    ap.add_argument("--out", default="data/waypoints.csv")
    a = ap.parse_args()

    faa, faa_bad = faa_fixes(a.faa)
    base, base_bad = base_fixes(a.base)

    # The FAA's area: every 1-degree cell holding an FAA fix, and its neighbours.
    area = set()
    for lat, lon in faa.values():
        la, lo = cell(lat, lon)
        for dl in (-1, 0, 1):
            for dn in (-1, 0, 1):
                area.add((la + dl, (lo + dn) % 360))

    out, replaced, kept_abroad, moved = [], 0, 0, 0
    for ident, lat, lon in base:
        if ident in faa:
            if cell(lat, lon) in area:
                replaced += 1
                flat, flon = faa[ident]
                if math.hypot(lat - flat, (lon - flon) * math.cos(math.radians(lat))) * 111.2 > 5:
                    moved += 1
                continue
            kept_abroad += 1
        out.append((ident, lat, lon))
    base_idents = {r[0] for r in base}
    for ident, (lat, lon) in faa.items():
        out.append((ident, lat, lon))
    out = sorted(set((i, round(la, 6), round(lo, 6)) for i, la, lo in out))

    with open(a.out, "w") as f:
        for ident, lat, lon in out:
            f.write(f"{ident},{lat:.6f},{lon:.6f}\n")

    new = sum(1 for i in faa if i not in base_idents)
    print(f"base: {len(base)} fixes ({base_bad} unusable lines dropped)", file=sys.stderr)
    print(f"FAA: {len(faa)} fixes ({faa_bad} unusable rows skipped)", file=sys.stderr)
    print(f"replaced {replaced} base entries with the FAA's position "
          f"({moved} of them more than 5 km off); kept {kept_abroad} same-name fixes "
          f"outside the FAA's area; added {new} fixes the base lacked", file=sys.stderr)
    print(f"wrote {len(out)} fixes to {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
