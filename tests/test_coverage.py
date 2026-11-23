#!/usr/bin/env python3
# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Coverage page's data (observatory/coverage.py) and the rollup's
schema 3 (the SNR and flight level on positions): geometry, the location
setting, and an archive through the rollup to /api/coverage. One PASS or FAIL
line per check; exits non-zero on any failure. Example coordinates only.

    python3 tests/test_coverage.py
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OBS = os.path.join(HERE, "..", "observatory")
sys.path.insert(0, OBS)
import coverage  # noqa: E402
import server  # noqa: E402

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("  " + str(detail) if detail and not ok else ""))
    fails += not ok


# geometry: FL350 at 100 km is 5.8 degrees up over a 4/3 earth, at 300 km 1.0
e100, e300 = coverage.elevation_deg(100, 35000, 0), coverage.elevation_deg(300, 35000, 0)
check("elevation at 100 and 300 km", abs(e100 - 5.76) < 0.05 and abs(e300 - 1.03) < 0.05, (e100, e300))
check("elevation falls with the antenna's height", coverage.elevation_deg(100, 35000, 500) < e100)
check("bearing north and east", abs(coverage.bearing_deg((40, -100), (41, -100))) < 0.01
      and abs(coverage.bearing_deg((40, -100), (40, -99)) - 90) < 1)

# the location setting
check("setting LAT,LON", server.parse_station("40.0,-100.0") ==
      {"lat": 40.0, "lon": -100.0, "alt_m": 0.0, "source": "from the settings"})
check("setting with antenna height and spaces", (server.parse_station(" 40.0, -100.0, 300") or {}).get("alt_m") == 300)
check("bad settings are none", all(server.parse_station(x) is None for x in ("", "here", "95,10", "40,-200", "1,2,3,4")))
# why a setting is ignored, without repeating it (the page may be public)
why = server.station_problem("40.123,-100.456_Discone")
check("a name after the longitude: says why", why and "other than numbers" in why and "40.123" not in why, why)
check("too few numbers: says why", "two numbers" in (server.station_problem("40.1") or ""))
check("out of range: says why", "between -90 and 90" in (server.station_problem("95,10") or ""))
check("a good setting has no problem", server.station_problem("40.0,-100.0,300") is None)
# an empty port setting (unset in the config file) falls back to the default
conv = server.port_or(8889)
check("an empty port falls back to the default", conv("") == 8889 and conv(" ") == 8889 and conv("8899") == 8899)

# An archive through the rollup: two aircraft north and east of the receiver,
# and one stray position far beyond the radio horizon.
RX = {"lat": 40.0, "lon": -100.0, "alt_m": 0.0, "source": "from the settings"}
T = 1795230000
with tempfile.TemporaryDirectory() as tmp:
    arch = os.path.join(tmp, "archive")
    os.makedirs(arch)
    ms = T * 1000
    fr = lambda t, a, snr: {"e": "vframe", "t": t, "freq": 136975000, "snr": snr, "src": a, "sk": 1,
                            "dst": "10423A", "dk": 5, "cr": 0, "ctl": "ACARS", "len": 40}
    ev = [
        fr(ms, "A00001", 31.5),
        {"e": "xid", "t": ms, "freq": 136975000, "src": "A00001", "sk": 1, "dst": "10423A", "dk": 5,
         # sent as the corner of its 0.1-degree cell; the rollup reads the centre, 40.9, -100.0
         "x": {"type": "Handoff Initiation", "ac_location": {"lat": 40.85, "lon": -99.95, "alt_ft": 35000}}},
        fr(ms + 5000, "A00002", 22.0),
        {"e": "vpos", "t": ms + 5000, "icao": "A00002", "gs": "10423A", "lat": 40.0, "lon": -97.65, "src": "text"},
        {"e": "acars", "t": ms + 5000, "sys": "vdl2", "dir": "UL", "freq": 136975000, "src": "A00002",
         "dst": "10423A", "reg": "N2", "flt": "XX2", "lbl": "H1",
         "txt": "POSN40000W097390,ABCDE,120000,330,FGHIJ,121500,KLMNO,M55,23210"},
        fr(ms + 9000, "A00003", 19.0),
        {"e": "vpos", "t": ms + 9000, "icao": "A00003", "gs": "10423A", "lat": 1.0, "lon": 1.0, "src": "text"},
    ]
    with open(os.path.join(arch, "vdl2-20261121.jsonl"), "w") as f:
        f.write("".join(json.dumps(e) + "\n" for e in ev))
    db = os.path.join(tmp, "observatory.db")
    rollup = [sys.executable, os.path.join(OBS, "rollup.py"), "--archive", arch, "--db", db]
    r = subprocess.run(rollup, capture_output=True, text=True)
    check("rollup runs", r.returncode == 0, r.stderr)
    con = sqlite3.connect(db)
    got = dict((row[0], row[1:]) for row in con.execute("SELECT icao, snr, alt, src FROM vdl2_pos"))
    check("each position carries its frame's SNR", got.get("A00001", ())[:1] == (31.5,)
          and got.get("A00002", ())[:1] == (22.0,), got)
    check("a position report's flight level is its altitude", got.get("A00002", (None, None))[1] == 33000, got)
    # A database from before schema 3: both filled in once.
    con.execute("UPDATE vdl2_pos SET snr=NULL")
    con.execute("UPDATE vdl2_pos SET alt=NULL WHERE src='text'")
    con.execute("DELETE FROM meta WHERE key='pos_snr'")
    con.commit()
    con.close()
    r = subprocess.run(rollup, capture_output=True, text=True)
    con = sqlite3.connect(db)
    check("older positions get SNR and flight level once (backfill)",
          con.execute("SELECT COUNT(*) FROM vdl2_pos WHERE snr IS NULL").fetchone()[0] == 0
          and con.execute("SELECT alt FROM vdl2_pos WHERE icao='A00002'").fetchone()[0] == 33000, r.stdout)
    con.close()

    d = coverage.build_coverage(db, RX, hours=6, now=T + 60)
    t = d["totals"]
    check("the stray position is set aside", t["beyond_horizon"] == 1 and t["positions"] == 2, t)
    check("ranges: 100 and 200 km", t["median_km"] in (100, 200) and t["max_km"] == 200, t)
    check("station shown to 0.1 degree", d["station"] == {"lat": 40.0, "lon": -100.0, "source": "from the settings"},
          d["station"])
    sky = {(c[0], c[1]): c for c in d["sky"]}
    north = [c for (az, e0), c in sky.items() if az == 0]
    # due east along the parallel is a great-circle bearing of about 88.8 degrees
    east = [c for (az, e0), c in sky.items() if az == 80]
    check("sky: the XID north at about 5.8 degrees", len(north) == 1 and north[0][1] == 5.5 and north[0][4] == 31.5, d["sky"])
    check("sky: the report east at about 2.2 degrees, from its flight level",
          len(east) == 1 and east[0][1] == 2.0 and east[0][4] == 22.0, d["sky"])
    sectors = {s[0]: s for s in d["sectors"]}
    check("range by direction", sectors[0][1] == 1 and sectors[0][2] == 100 and sectors[85][2] == 200, sectors[0])
    check("SNR by distance", [r[0] for r in d["distance"]] == [100, 200], d["distance"])

    d = coverage.build_coverage(db, None, hours=6, now=T + 60)
    check("without a location: cells only", d["station"] is None and "sky" not in d and len(d["cells"]) == 3, d)

sys.exit(1 if fails else 0)
