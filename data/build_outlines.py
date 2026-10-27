#!/usr/bin/env python3
# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Rebuild data/outlines.json, the background lines on the live page's map.

    build_outlines.py NE_DIR [--out data/outlines.json]

NE_DIR holds these Natural Earth GeoJSON files, from
github.com/nvkelso/natural-earth-vector (geojson/), public domain:

    ne_50m_land.geojson                       -> land (rings: filled, and the coast)
    ne_50m_admin_0_boundary_lines_land.geojson -> border (between countries)
    ne_50m_admin_1_states_provinces_lines.geojson -> state
    ne_50m_lakes.geojson                      -> lake (rings)
    ne_10m_populated_places_simple.geojson    -> places (towns to read the map by)

Every line is rounded to 0.01 degree (about 1 km, finer than the page
draws), points that round onto the one before are dropped, and each line
is written as integers: the first point in hundredths of a degree, then
the steps between points, lon before lat:

    {"q": 100, "layers": {"land": [[lon0, lat0, dlon, dlat, ...], ...], ...},
     "places": [[lon, lat, rank, "name"], ...]}

Places keep Natural Earth's scalerank (0 the biggest), so the page can show
only the bigger ones when it shows a big area. Ranks 9 and 10 are left out.

Running it again on the same files gives the same output.
"""

import argparse
import json
import os
import sys

LAYERS = [
    ("land", "ne_50m_land.geojson"),
    ("border", "ne_50m_admin_0_boundary_lines_land.geojson"),
    ("state", "ne_50m_admin_1_states_provinces_lines.geojson"),
    ("lake", "ne_50m_lakes.geojson"),
]
Q = 100
PLACES = "ne_10m_populated_places_simple.geojson"
MAX_PLACE_RANK = 8


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

    places = []
    with open(os.path.join(args.ne_dir, PLACES)) as f:
        for ft in json.load(f)["features"]:
            pr, (lon, lat) = ft["properties"], ft["geometry"]["coordinates"][:2]
            if pr.get("scalerank", 99) <= MAX_PLACE_RANK and pr.get("name"):
                places.append([round(lon * Q), round(lat * Q), pr["scalerank"], pr["name"]])
    places.sort(key=lambda p: (p[2], p[3], p[0], p[1]))
    print(f"places: {len(places)}", file=sys.stderr)

    doc = {"source": "Natural Earth, public domain (naturalearthdata.com)", "q": Q, "layers": layers,
           "places": places}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"), ensure_ascii=False)
        f.write("\n")
    print(f"{args.out}: {os.path.getsize(args.out)} bytes", file=sys.stderr)


if __name__ == "__main__":
    main()
