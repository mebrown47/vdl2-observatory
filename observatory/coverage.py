# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""
VDL2 Observatory — Coverage: where this receiver hears aircraft, and how
strongly, from the positions aircraft report (vdl2_pos) and the SNR of the
frames that carried them (schema 3).

Every position the receiver decoded is a place it heard an aircraft from.
With the receiver's location, each one also has a bearing, a distance and,
from the aircraft's altitude (its XID's, or a position report's flight
level), an elevation as the antenna sees it:

  map       0.1-degree cells: how many positions, their median SNR; the
            farthest the receiver hears in each 5-degree sector (95th
            percentile, so one stray point doesn't set it)
  sky       azimuth x elevation, as iridium-observatory's sky map: median
            SNR in each cell. VDL2 aircraft sit within a few degrees of the
            horizon, where an antenna's pattern and what stands around it
            show.
  distance  SNR against distance: where signals fade

A frame that fails to decode has no sender and no position, so it can't be
placed: this shows where aircraft are heard, not where they are missed.

Elevation uses the 4/3 effective earth radius that VHF refraction gives.
The receiver's location comes from the settings (STATION in
/etc/vdl2-observatory.conf) or, failing that, from iridium-observatory on
the same machine (its ring-alert fix); the page shows it rounded to 0.1
degree.
"""
import math
import sqlite3
import time

import context
import flights

R_EFF_M = 4 / 3 * 6371000.0
SOURCES = ("xid", "text", "adsc")
GEO_CELL = 0.1
AZ_BIN = 10
EL_EDGES = [-1.0] + [x / 2 for x in range(0, 21)] + [90.0]   # -1, 0, 0.5 ... 10, 90
SECTOR = 5
DIST_BIN = 25
# Farther than a VHF receiver can hear: the radio horizon from 45,000 ft is
# under 500 km. A position beyond this is a bad one (an aircraft with a single
# stray position the track filter can't judge), set aside and counted.
MAX_KM = 600


def bearing_deg(a, b):
    return (math.degrees(context.bearing(a, b)) + 360) % 360


def elevation_deg(dist_km, alt_ft, rx_alt_m):
    """The angle above the horizon at which the receiver sees an aircraft
    dist_km away at alt_ft, over a 4/3-radius earth."""
    d = dist_km * 1000.0
    if d < 1:
        return 90.0
    h = alt_ft * 0.3048 - rx_alt_m - d * d / (2 * R_EFF_M)
    return math.degrees(math.atan2(h, d))


def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[i]


def _med(vals):
    s = sorted(vals)
    return round(_pct(s, 0.5), 1) if s else None


def build_coverage(db_path, station=None, hours=168, now=None):
    """station: {"lat", "lon", "alt_m", "source"} or None."""
    now = time.time() if now is None else now
    t0 = now - hours * 3600
    con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True, timeout=5)
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(vdl2_pos)")}
        if "snr" not in cols:
            return {"error": "the database predates the Coverage page: run rollup.py once "
                             "to add the SNR to stored positions"}
        rows = con.execute(
            "SELECT t, icao, lat, lon, alt, src, snr FROM vdl2_pos "
            "WHERE t >= ? AND t <= ? AND snr IS NOT NULL ORDER BY t", (t0, now)).fetchall()
    finally:
        con.close()

    # the same plausibility filter as the Flights tracks, per aircraft
    by_ac = {}
    for t, icao, lat, lon, alt, src, snr in rows:
        if src in SOURCES and lat is not None and lon is not None:
            by_ac.setdefault(icao, []).append([int(t), lat, lon, alt, src, snr])
    pts = []
    for icao, tr in by_ac.items():
        for p in flights.plausible(tr):
            pts.append(p)
    impossible = 0
    if station:
        rx = (station["lat"], station["lon"])
        keep = [p for p in pts if context.km(rx, (p[1], p[2])) <= MAX_KM]
        impossible = len(pts) - len(keep)
        pts = keep

    geo = {}
    for t, lat, lon, alt, src, snr in pts:
        k = (math.floor(lat / GEO_CELL), math.floor(lon / GEO_CELL))
        geo.setdefault(k, []).append(snr)
    cells = [[round(k[0] * GEO_CELL, 2), round(k[1] * GEO_CELL, 2), len(v), _med(v), round(max(v), 1)]
             for k, v in geo.items()]

    out = {"now": int(now), "hours": hours, "cell_deg": GEO_CELL,
           "totals": {"positions": len(pts), "aircraft": len(by_ac),
                      "with_altitude": sum(1 for p in pts if p[3]),
                      "median_snr": _med([p[5] for p in pts])},
           "cells": cells, "station": None}
    if not station:
        return out

    rx = (station["lat"], station["lon"])
    rx_alt = station.get("alt_m") or 0.0
    sky, sectors, dist = {}, {}, {}
    dists = []
    for t, lat, lon, alt, src, snr in pts:
        d = context.km(rx, (lat, lon))
        b = bearing_deg(rx, (lat, lon))
        dists.append(d)
        sectors.setdefault(int(b // SECTOR) * SECTOR, []).append((d, snr))
        dist.setdefault(int(d // DIST_BIN) * DIST_BIN, []).append(snr)
        if alt:
            e = elevation_deg(d, alt, rx_alt)
            if e >= EL_EDGES[0]:
                i = next(j for j in range(len(EL_EDGES) - 1) if e < EL_EDGES[j + 1] or j == len(EL_EDGES) - 2)
                sky.setdefault((int(b // AZ_BIN) * AZ_BIN, i), []).append(snr)
    dists.sort()
    out["station"] = {"lat": round(station["lat"], 1), "lon": round(station["lon"], 1),
                      "source": station.get("source", "from the settings")}
    out["totals"].update({"beyond_horizon": impossible,
                          "median_km": round(_pct(dists, 0.5)) if dists else None,
                          "p95_km": round(_pct(dists, 0.95)) if dists else None,
                          "max_km": round(dists[-1]) if dists else None})
    out["sky"] = [[az, EL_EDGES[i], EL_EDGES[i + 1], len(v), _med(v)]
                  for (az, i), v in sorted(sky.items())]
    out["el_edges"] = EL_EDGES
    out["sectors"] = []
    for s in range(0, 360, SECTOR):
        v = sectors.get(s, [])
        ds = sorted(x[0] for x in v)
        out["sectors"].append([s, len(v), round(_pct(ds, 0.95)) if ds else None,
                               round(ds[-1]) if ds else None, _med([x[1] for x in v])])
    out["distance"] = []
    for b in sorted(dist):
        v = sorted(dist[b])
        out["distance"].append([b, len(v), round(_pct(v, 0.1), 1), round(_pct(v, 0.5), 1),
                                round(_pct(v, 0.9), 1)])
    return out
