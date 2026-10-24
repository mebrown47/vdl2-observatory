#!/usr/bin/env python3
# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Rebuild data/outlines.json, the background lines on the live page's map.

    build_outlines.py NE_DIR [--out data/outlines.json]

NE_DIR holds four Natural Earth 1:50m GeoJSON files, from
github.com/nvkelso/natural-earth-vector (geojson/), public domain:

    ne_50m_coastline.geojson                  -> coast
    ne_50m_admin_0_boundary_lines_land.geojson -> border (between countries)
    ne_50m_admin_1_states_provinces_lines.geojson -> state
    ne_50m_lakes.geojson                      -> lake (outlines only)

Every line is rounded to 0.01 degree (about 1 km, finer than the page
draws), points that round onto the one before are dropped, and each line
is written as integers: the first point in hundredths of a degree, then
the steps between points, lon before lat:

    {"q": 100, "layers": {"coast": [[lon0, lat0, dlon, dlat, ...], ...], ...}}

Running it again on the same files gives the same output.
"""

import argparse
import json
import os
import sys

LAYERS = [
    ("coast", "ne_50m_coastline.geojson"),
    ("border", "ne_50m_admin_0_boundary_lines_land.geojson"),
    ("state", "ne_50m_admin_1_states_provinces_lines.geojson"),
    ("lake", "ne_50m_lakes.geojson"),
]
Q = 100


def lines(geom):
    """Every line of a geometry; polygon rings count as lines."""
    t, c = geom["type"], geom["coordinates"]
    if t == "LineString":
        return [c]
    if t in ("MultiLineString", "Polygon"):
        return c
    if t == "MultiPolygon":
        return [ring for poly in c for ring in poly]
    raise ValueError("unexpected geometry " + t)


def encode(line):
    pts = []
    for lon, lat, *_ in line:
        p = (round(lon * Q), round(lat * Q))
        if not pts or p != pts[-1]:
            pts.append(p)
    if len(pts) < 2:
        return None
    out = [pts[0][0], pts[0][1]]
    for a, b in zip(pts, pts[1:]):
        out += [b[0] - a[0], b[1] - a[1]]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ne_dir")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "outlines.json"))
    args = ap.parse_args()

    layers = {}
    for name, fn in LAYERS:
        with open(os.path.join(args.ne_dir, fn)) as f:
            features = json.load(f)["features"]
        enc = [e for ft in features if ft.get("geometry")
               for e in map(encode, lines(ft["geometry"])) if e]
        layers[name] = sorted(enc)
        print(f"{name}: {len(enc)} lines, {sum(len(e) for e in enc) // 2} points", file=sys.stderr)

    doc = {"source": "Natural Earth 1:50m, public domain (naturalearthdata.com)", "q": Q, "layers": layers}
    with open(args.out, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
        f.write("\n")
    print(f"{args.out}: {os.path.getsize(args.out)} bytes", file=sys.stderr)


if __name__ == "__main__":
    main()
