#!/usr/bin/env python3
# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Graph page's data (observatory/graph.py) on a small hand-made
database: handoff pairs counted per direction with distinct aircraft, the
window, stations without a position kept but not placed, and one aircraft
found by registration, flight or address with its stations, handoffs and
routes. One PASS or FAIL line per check.

    python3 tests/test_graph.py
"""
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "observatory"))
import context  # noqa: E402
import graph  # noqa: E402
import rollup  # noqa: E402

fails = 0


def check(ok, what, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + what + ("  (%s)" % (detail,) if detail and not ok else ""))
    fails += not ok


NOW = 1795400000
tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "observatory.db")
con = sqlite3.connect(db)
rollup.init_db(con)
xcols = {r[1] for r in con.execute("PRAGMA table_info(vdl2_xid)")}
def xid(t, icao, from_gs, gs, airport=""):
    row = {"t": t, "icao": icao, "from_gs": from_gs, "gs": gs, "kind": "Handoff Initiation", "airport": airport}
    row = {k: v for k, v in row.items() if k in xcols}
    con.execute("INSERT INTO vdl2_xid(%s) VALUES(%s)" % (",".join(row), ",".join("?" * len(row))), list(row.values()))
xid(NOW - 3600, "A00001", "AAAAAA", "BBBBBB", "KATL")
xid(NOW - 3000, "A00002", "AAAAAA", "BBBBBB")
xid(NOW - 2000, "A00001", "AAAAAA", "BBBBBB")
xid(NOW - 1000, "A00001", "BBBBBB", "AAAAAA")
xid(NOW - 500, "A00003", "", "CCCCCC")            # first contact: no from-station
xid(NOW - 10 * 86400, "A00004", "AAAAAA", "DDDDDD")  # outside a 7-day window
xid(NOW - 400, "A00005", "AAAAAA", "000000")         # a placeholder address, not a station
con.executemany("INSERT INTO messages(t,reg,flt,dir,lbl,freq,txt,has_cpdlc,has_adsc,icao) VALUES(?,?,?,?,?,?,?,?,?,?)", [
    (NOW - 3500, "N1AA", "AA0001", "UL", "H1", 136975000, "TRP KATL KMCO  7 4", 0, 0, "A00001"),
    (NOW - 3400, "N1AA", "AA0001", "UL", "_d", 136975000, "", 0, 0, "A00001"),
    (NOW - 3300, "N2BB", "BB0002", "UL", "H1", 136975000, "HELLO", 0, 0, "A00002"),
])
con.commit()
con.close()

stations = [{"station": "AAAAAA", "lat": 33.0, "lon": -85.0, "spread_km": 20, "n_pos": 9},
            {"station": "BBBBBB", "lat": 32.0, "lon": -84.0, "spread_km": 30, "n_pos": 7}]
n = graph.build_network(db, stations, hours=168, now=NOW)
p = {(x["from"], x["to"]): x for x in n["pairs"]}
check(p[("AAAAAA", "BBBBBB")]["handoffs"] == 3 and p[("AAAAAA", "BBBBBB")]["aircraft"] == 2, "pair: handoffs and distinct aircraft", p)
check(p[("BBBBBB", "AAAAAA")]["handoffs"] == 1, "each direction counted on its own")
check(("AAAAAA", "DDDDDD") not in p, "handoffs outside the window left out")
check(not any(x["from"] == "" for x in n["pairs"]), "first contacts are not handoffs")
check(not any("000000" in (x["from"], x["to"]) for x in n["pairs"]) and "000000" not in {x["station"] for x in n["stations"]},
      "the 000000 placeholder is not a station")
s = {x["station"]: x for x in n["stations"]}
check(s["AAAAAA"]["out"] == 3 and s["AAAAAA"]["in"] == 1, "station in/out")
check("CCCCCC" in s and s["CCCCCC"]["lat"] is None, "a station without a position is listed, unplaced")
check(n["totals"]["placed"] == 2 and n["totals"]["handoffs"] == 4 and n["totals"]["aircraft"] == 2, "totals", n["totals"])
check(len(graph.build_network(db, stations, hours=168 * 2, now=NOW)["pairs"]) == 3, "a longer window reaches further back")

ref = context.Reference(waypoints="", aircraft_csv="")
for q in ("N1AA", "aa0001", "a00001", ".n1aa"):
    a = graph.build_aircraft(db, ref, q, now=NOW)
    check(a.get("icao") == "A00001", "aircraft found by " + q, a.get("error"))
a = graph.build_aircraft(db, ref, "N1AA", now=NOW)
check(a["msgs"] == 2 and len(a["days"]) == 1 and a["days"][0]["msgs"] == 1 and a["days"][0]["acks"] == 1, "messages and heartbeats per day", a["days"])
check([h["to"] for h in a["handoffs"]] == ["AAAAAA", "BBBBBB", "BBBBBB"], "its handoffs, newest first", a["handoffs"])
check({x["station"] for x in a["stations"]} == {"AAAAAA", "BBBBBB"}, "stations it used")
check(a["routes"] and (a["routes"][0]["origin"], a["routes"][0]["dest"]) == ("KATL", "KMCO"), "route from its own message", a["routes"])
check("error" in graph.build_aircraft(db, ref, "N9ZZ", now=NOW), "an unknown aircraft is reported")
check("error" in graph.build_aircraft(db, ref, "", now=NOW), "an empty query is reported")
lst = graph.aircraft_list(db, now=NOW)
check(lst[0]["icao"] == "A00001" and lst[0]["msgs"] == 1, "suggestions leave out heartbeats", lst)

sys.exit(1 if fails else 0)
