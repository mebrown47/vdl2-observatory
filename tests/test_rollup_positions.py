#!/usr/bin/env python3
# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""Position handling in observatory/rollup.py: XID positions read as the
centre of their 0.1-degree cell (old rows moved once, new rows as they are
ingested, never twice), and text positions from snapshot reports and
forecast points removed once. One PASS or FAIL line per check.

    python3 tests/test_rollup_positions.py
"""
import json
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "observatory"))
import rollup  # noqa: E402

fails = 0


def check(ok, what, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + what + ("  (%s)" % (detail,) if detail and not ok else ""))
    fails += not ok


C = rollup.xid_centre
check((C(33.2), C(-85.1), C(0), C(None)) == (33.25, -85.15, 0, None),
      "an XID value moves half a cell away from zero", (C(33.2), C(-85.1)))

d = tempfile.mkdtemp()
db, arch = os.path.join(d, "o.db"), os.path.join(d, "archive")
os.makedirs(arch)
con = sqlite3.connect(db)
rollup.init_db(con)
# rows from before the change: an XID position as sent, and text positions
# from a snapshot report, a forecast point and a real position report
con.execute("INSERT INTO vdl2_pos(t,icao,gs,lat,lon,src) VALUES(100,'A1','G1',33.2,-85.1,'xid')")
con.execute("INSERT INTO vdl2_xid(t,icao,gs,lat,lon) VALUES(100,'A1','G1',33.2,-85.1)")
texts = {"A2": "74102,8319,B737-800,261123,WN2235,KMDW,KTPA,0082,EN2605\r\n"
               "02.51.19,CR,0538,37012,258.3,.796,-50.3,-21.7,N3347.2,W08527.2,145040",
         "A3": "021546.1,,,N28249W081196,14,021733.1,,,N28258W081185:1100/PR1280",
         "A4": "POSN33208W086076,TEMPO,201500,370"}
for icao, txt in texts.items():
    con.execute("INSERT INTO messages(t,dir,lbl,txt,icao) VALUES(200,'UL','H1',?,?)", (txt, icao))
    con.execute("INSERT INTO vdl2_pos(t,icao,gs,lat,lon,src) VALUES(200,?,'G1',33.5,-85.5,'text')", (icao,))
con.commit()
con.close()
# a new XID after the change, in the archive
ev = {"e": "xid", "t": 300000, "src": "A5", "sk": 1, "dst": "G1", "dk": 4,
      "x": {"type": "Handoff Response", "ac_location": {"lat": 32.0, "lon": -86.3, "alt_ft": 37000}}}
with open(os.path.join(arch, "vdl2-20261123.jsonl"), "w") as f:
    f.write(json.dumps(ev) + "\n")
sys.argv = ["rollup.py", "--archive", arch, "--db", db]
for run in (1, 2):                      # the second run must change nothing
    rollup.main()
    con = sqlite3.connect(db)
    old = con.execute("SELECT lat, lon FROM vdl2_pos WHERE icao='A1'").fetchone()
    oldx = con.execute("SELECT lat, lon FROM vdl2_xid WHERE icao='A1'").fetchone()
    new = con.execute("SELECT lat, lon FROM vdl2_pos WHERE icao='A5'").fetchone()
    text = {r[0] for r in con.execute("SELECT icao FROM vdl2_pos WHERE src='text'")}
    con.close()
    check(old == (33.25, -85.15) and oldx == (33.25, -85.15), "run %d: an XID position stored before is centred once" % run, (old, oldx))
    check(new == (32.05, -86.35), "run %d: a new XID position is centred as it is ingested, once" % run, new)
    check(text == {"A4"}, "run %d: snapshot and forecast positions removed, the position report kept" % run, text)
sys.exit(1 if fails else 0)
