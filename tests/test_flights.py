#!/usr/bin/env python3
# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Flights page's data (observatory/flights.py) and the rollup's
messages.icao (observatory/rollup.py): route layouts, track plausibility, and
an archive through the rollup to /api/flights. One PASS or FAIL line per
check; exits non-zero on any failure.

    python3 tests/test_flights.py
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
import context  # noqa: E402
import flights  # noqa: E402
import vdl2_view  # noqa: E402

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("  " + str(detail) if detail and not ok else ""))
    fails += not ok


ref = context.Reference(waypoints=os.path.join(HERE, "..", "data", "waypoints.csv"), aircraft_csv="")

# One message in each layout, as heard on the feeder.
ROUTES = [
    ("TRP header", "TRP KMIA KMSP  7 4\r\n/A1 025254  30.6491  -83.9423 380", ("KMIA", "KMSP")),
    ("02E header", "76401\r\n02E21KMCOKOKC\r\nN30838W08646202393800M058203024G000021002X/9W\r\n", ("KMCO", "KOKC")),
    ("LDR01 fields", "LDR01,189,D,SWA-2600-019,0,----.---,----.---,2026, 11.1,KLAS,KMCO,KMCO,36L/,35R/", ("KLAS", "KMCO")),
    ("POSRPT O/D", "3P01 POSRPT  1544/20 KXNA/KTPA .N248BZ\r\n/UTC 031932/POS N3141.4 W08634.5/ALT 330", ("KXNA", "KTPA")),
    ("POS0n fields", "POS02,N31475W086235,289,KPNS,KFTY,1120,0310,0342,006.1", ("KPNS", "KFTY")),
    ("time O D", "190339 KATL KPNS7\r\n0402", ("KATL", "KPNS")),
    ("LDG DATA REQ", "/B6 LDG DATA REQ   / KDEN KMCO 19 033047 KMCO R36L/----", ("KDEN", "KMCO")),
]
for name, txt, want in ROUTES:
    r = flights.route_from_text(txt, ref)
    check("route: " + name, r is not None and r[:2] == want and r[2] == name, r)
check("route: none from a position report", flights.route_from_text("POSN45216W096178,VIVID,022727,350", ref) is None)
check("route: same airport twice is none", flights.route_from_text("TRP KMCO KMCO 7 4", ref) is None)
check("route: unknown airports are none", flights.route_from_text("TRP ZZZQ ZZZR 7 4", ref) is None)

# WN2235 (KMDW-KTPA), 6h before 03:06Z on 2026-11-21: XIDs at 02:57 and 03:04,
# an intent list's points ahead (02:56:13-18), and position histories whose
# blocks each gave an earlier entry (02:52:05, 03:06:06-08).
T = 1795230000
raw = [[T - 840, 33.5833, -86.1867, None, "text"], [T - 839, 32.6133, -85.6433, None, "text"],
       [T - 593, 33.3467, -86.1267, None, "text"], [T - 591, 29.12, -83.445, None, "text"],
       [T - 590, 28.28, -82.6133, None, "text"], [T - 588, 33.3467, -86.1267, None, "text"],
       [T - 510, 32.0, -85.2, 33000, "xid"], [T - 115, 31.3, -84.8, 33000, "xid"],
       [T + 6, 31.6917, -85.0517, None, "text"], [T + 8, 31.3867, -84.86, None, "text"],
       [T + 12, 31.265, -84.7833, None, "text"]]
got = flights.plausible(raw)
check("track: stray positions dropped, newest kept",
      [p[0] - T for p in got] == [-839, -510, -115, 12], [(p[0] - T, p[1], p[2]) for p in got])
check("track: one point unchanged", flights.plausible(raw[:1]) == raw[:1])

# An archive through the rollup to the Flights data.
with tempfile.TemporaryDirectory() as tmp:
    arch = os.path.join(tmp, "archive")
    os.makedirs(arch)
    ms = T * 1000
    ev = [
        {"e": "acars", "t": ms, "sys": "vdl2", "dir": "UL", "freq": 136650000, "src": "AC2BE9",
         "dst": "112DCA", "reg": ".N8834L", "flt": "WN2235", "lbl": "H1",
         "txt": "76401\r\n02E21KMDWKTPA\r\n"},
        {"e": "acars", "t": ms + 1000, "sys": "vdl2", "dir": "UL", "freq": 136650000, "src": "A0F1BB",
         "dst": "2121A5", "reg": "N160AN", "flt": "AA1840", "lbl": "H1", "txt": "FREE TEXT"},
        {"e": "xid", "t": ms + 2000, "freq": 136975000, "src": "AC2BE9", "sk": 1, "dst": "112DCA", "dk": 5,
         "x": {"type": "Handoff Initiation", "dst_airport": "KTPA",
               "ac_location": {"lat": 31.3, "lon": -84.8, "alt_ft": 33000}}},
        {"e": "vpos", "t": ms + 3000, "icao": "AC2BE9", "gs": "112DCA", "lat": 31.265, "lon": -84.7833, "src": "text"},
        # a misread text position (FANS hex read as N64116E140066) and a handoff giving 0, 0
        {"e": "vpos", "t": ms + 3500, "icao": "AC2BE9", "gs": "112DCA", "lat": 64.1933, "lon": 140.11, "src": "text"},
        {"e": "xid", "t": ms + 3600, "freq": 136975000, "src": "A0F1BB", "sk": 1, "dst": "2121A5", "dk": 5,
         "x": {"type": "Handoff Initiation", "ac_location": {"lat": 0, "lon": 0, "alt_ft": 0}}},
        {"e": "xid", "t": ms + 4000, "freq": 136975000, "src": "A0F1BB", "sk": 1, "dst": "2121A5", "dk": 5,
         "x": {"type": "Handoff Initiation", "dst_airport": "KIAH"}},
    ]
    with open(os.path.join(arch, "vdl2-20261121.jsonl"), "w") as f:
        f.write("".join(json.dumps(e) + "\n" for e in ev))
    db = os.path.join(tmp, "observatory.db")
    rollup = [sys.executable, os.path.join(OBS, "rollup.py"), "--archive", arch, "--db", db]
    r = subprocess.run(rollup, capture_output=True, text=True)
    check("rollup runs", r.returncode == 0, r.stderr)
    con = sqlite3.connect(db)
    check("messages carry the aircraft address",
          sorted(con.execute("SELECT icao FROM messages").fetchall()) == [("A0F1BB",), ("AC2BE9",)])
    # A database from before schema 2: the address is filled in from the archive.
    con.execute("UPDATE messages SET icao=NULL")
    con.execute("DELETE FROM meta WHERE key='messages_icao'")
    con.commit()
    con.close()
    r = subprocess.run(rollup, capture_output=True, text=True)
    con = sqlite3.connect(db)
    check("older rows get the address once (backfill)",
          con.execute("SELECT COUNT(*) FROM messages WHERE icao IS NULL").fetchone()[0] == 0
          and "added to 2 earlier messages" in r.stdout, r.stdout)
    con.close()

    d = flights.build_flights(db, ref, hours=6, now=T + 60)
    by = {a["icao"]: a for a in d["aircraft"]}
    a = by.get("AC2BE9", {})
    check("aircraft keyed by address, named by its messages",
          a.get("reg") == "N8834L" and a.get("flight") == "WN2235", a)
    check("route from the 02E header",
          a.get("route") and a["route"]["origin"]["code"] == "KMDW" and a["route"]["dest"]["code"] == "KTPA"
          and a["route"]["src"] == "02E header" and a["route"]["dest"]["pos"] is not None, a.get("route"))
    check("track from its XID and position report", [p[4] for p in a.get("track", [])] == ["xid", "text"],
          a.get("track"))
    check("station is the last one it talked to", a.get("gs") == "112DCA", a.get("gs"))
    b = by.get("A0F1BB", {})
    check("destination from the XID alone", b.get("route") is None and (b.get("xid_dest") or {}).get("code") == "KIAH", b)
    check("totals", d["totals"] == {"aircraft": 2, "with_track": 1, "with_route": 1, "with_destination": 2},
          d["totals"])
    con = sqlite3.connect(db)
    check("a handoff giving 0, 0 stores no position",
          con.execute("SELECT COUNT(*) FROM vdl2_pos WHERE lat=0 AND lon=0").fetchone()[0] == 0
          and con.execute("SELECT COUNT(*) FROM vdl2_xid WHERE lat=0 AND lon=0").fetchone()[0] == 0)
    centre = vdl2_view.receiver_centre(con)
    check("horizon centre from the XID positions when no location is set",
          centre and abs(centre[0] - 31.35) < 0.01 and abs(centre[1] + 84.85) < 0.01, centre)   # cell centres
    check("the receiver's location wins when known",
          vdl2_view.receiver_centre(con, {"lat": 32.0, "lon": -86.0}) == (32.0, -86.0))
    check("a position beyond the horizon is set aside, one inside kept",
          not vdl2_view.in_range(centre, 64.1933, 140.11) and vdl2_view.in_range(centre, 33.0, -86.5))
    est = {x["station"]: x for x in vdl2_view.estimate_stations(con, centre)}
    con.close()
    check("station estimates leave out positions beyond the horizon", est["112DCA"]["n_pos"] == 2, est.get("112DCA"))
    check("Flights leaves out positions beyond the horizon",
          all(p[1] < 40 for p in a.get("track", [])), a.get("track"))
    check("an older window is empty", flights.build_flights(db, ref, hours=1, now=T + 7200)["aircraft"] == [])

sys.exit(1 if fails else 0)
