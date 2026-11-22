#!/usr/bin/env python3
# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""Take the Global Aviation Waypoints fixes out of data/waypoints.csv.

The file was merged (April 2026, in iridium-sniffer) from X-Plane's
earth_fix.dat (GPL) and Global Aviation Waypoints, then rebuilt with the
FAA's fix positions (build_waypoints.py). Global Aviation Waypoints' MIT
licence covers its scraper; its data is scraped from OpenNav, whose terms
for redistributing it are unknown. So every fix that only it supplies goes.

A row is dropped when no FAA or X-Plane fix of the same name lies within
2 km of it, and either a Global Aviation Waypoints fix of that name does, or
the name is Global Aviation Waypoints' alone (not X-Plane's) with its fix
within 10 km (the same fix, rounded differently). Everything else stays: the
FAA's (public domain) and X-Plane's (GPL), including fixes from a newer
X-Plane cycle than the one compared against, which match neither by position.

    remove_scraped_fixes.py WAYPOINTS FAA_CSV XPLANE_FIX GAW_CSV [--out PATH]

  FAA_CSV     the FAA fix list (fix_identifier, state, description with the
              DMS position), as for build_waypoints.py
  XPLANE_FIX  X-Plane fix data in fix.dat layout, plain or .gz: FlightGear
              ships Robin Peel's as Navaids/fix.dat.gz
              (https://gitlab.com/flightgear/fgdata/-/raw/next/Navaids/fix.dat.gz)
  GAW_CSV     global_aviation_waypoints.csv from
              https://github.com/FayyazAK/Global-Aviation-Waypoints

Run on 2026-11-21 (FlightGear's 2013.10 cycle, Global Aviation Waypoints
d529d59): 147,503 rows in, 13,829 dropped, 133,674 kept.
"""
import argparse
import collections
import csv
import gzip
import math
import re
import sys


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 12742 * math.asin(min(1.0, math.sqrt(h)))


DMS = re.compile(r"(\d+)-(\d+)-([\d.]+)([NS])\D+?(\d+)-(\d+)-([\d.]+)([EW])")


def load_faa(path):
    ix = collections.defaultdict(list)
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            m = DMS.search(r.get("description", ""))
            if not m:
                continue
            la = int(m[1]) + int(m[2]) / 60 + float(m[3]) / 3600
            lo = int(m[5]) + int(m[6]) / 60 + float(m[7]) / 3600
            ix[r["fix_identifier"].strip()].append((-la if m[4] == "S" else la,
                                                    -lo if m[8] == "W" else lo))
    return ix


def load_xplane(path):
    ix = collections.defaultdict(list)
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt", errors="replace") as f:
        for line in f:
            p = line.split()
            if len(p) >= 3:
                try:
                    ix[p[2]].append((float(p[0]), float(p[1])))
                except ValueError:
                    pass
    return ix


def load_gaw(path):
    ix = collections.defaultdict(list)
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                ix[r["IDENT"].strip()].append((float(r["LATITUDE"]), float(r["LONGITUDE"])))
            except (KeyError, ValueError):
                pass
    return ix


def nearest(ix, name, p):
    return min((km(p, q) for q in ix.get(name, ())), default=math.inf)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("waypoints")
    ap.add_argument("faa")
    ap.add_argument("xplane")
    ap.add_argument("gaw")
    ap.add_argument("--out")
    a = ap.parse_args()
    faa, xp, gaw = load_faa(a.faa), load_xplane(a.xplane), load_gaw(a.gaw)
    with open(a.waypoints, newline="") as f:
        rows = list(csv.reader(f))
    keep, dropped = [], 0
    for r in rows:
        try:
            p = (float(r[1]), float(r[2]))
        except (IndexError, ValueError):
            keep.append(r)
            continue
        n = r[0]
        if nearest(faa, n, p) <= 2 or nearest(xp, n, p) <= 2:
            keep.append(r)
            continue
        g = nearest(gaw, n, p)
        if g <= 2 or (n in gaw and n not in xp and g <= 10):
            dropped += 1
            continue
        keep.append(r)
    with open(a.out or a.waypoints, "w", newline="") as f:
        csv.writer(f, lineterminator="\n").writerows(keep)
    print(f"{len(rows)} rows in, {dropped} dropped, {len(keep)} kept", file=sys.stderr)


if __name__ == "__main__":
    main()
