#!/usr/bin/env python3
# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Search page's queries (observatory/search.py) on a small hand-made
database: each filter, heartbeats hidden by default, LIKE wildcards taken
literally, paging, the date range including its last day, CPDLC summaries
joined in, the address and channel filters, and the CSV export. Ported from
iridium-observatory's test_search.py. One PASS or FAIL line per check.

    python3 tests/test_search.py
"""
import calendar
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "observatory"))
import rollup  # noqa: E402
import search  # noqa: E402

fails = 0


def check(ok, what, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + what + ("  (%s)" % (detail,) if detail and not ok else ""))
    fails += not ok


def day(s, hh=12):
    return calendar.timegm((int(s[:4]), int(s[5:7]), int(s[8:10]), hh, 0, 0))


tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "observatory.db")
con = sqlite3.connect(db)
rollup.init_db(con)
msgs = [  # t, reg, flt, dir, lbl, freq, txt, has_cpdlc, has_adsc, icao
    (day("2026-11-10"), "N100AA", "AA0100", "UL", "_d", 136975000, "", 0, 0, "A00100"),
    (day("2026-11-10", 13), "N100AA", "AA0100", "UL", "H1", 136975000, "LOADSHEET FINAL", 0, 0, "A00100"),
    (day("2026-11-11"), "N200BB", "", "DL", "Q0", 136650000, "", 0, 0, "A00200"),
    (day("2026-11-11", 23), "N200BB", "", "UL", "AA", 136650000, "/AT1.N200BB", 1, 0, "A00200"),
    (day("2026-11-12"), "N300CC", "", "UL", "H1", 136800000, "FUEL 100% OK", 0, 0, "B00300"),
    (day("2026-11-12", 1), "N300CC", "", "UL", "H1", 136800000, "FUEL 1000 OK", 0, 0, "B00300"),
]
con.executemany("INSERT INTO messages(t,reg,flt,dir,lbl,freq,txt,has_cpdlc,has_adsc,icao) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)", msgs)
con.execute("INSERT INTO cpdlc_log(t,reg,flt,dir,txt,summary,dec) VALUES(?,?,?,?,?,?,?)",
            (day("2026-11-11", 23), "N200BB", "", "UL", "", "CLIMB TO FL350", "{}"))
con.commit()
con.close()


def S(**kw):
    return search.build_search(db, {k: [str(v)] for k, v in kw.items()})


r = S()
check(r["total"] == 5, "heartbeats hidden by default", r["total"])
check(S(hb=1)["total"] == 6, "hb=1 includes them")
check([x["t"] for x in r["rows"]] == sorted((x["t"] for x in r["rows"]), reverse=True), "newest first")
check(S(sort="oldest")["rows"][0]["reg"] == "N100AA", "sort=oldest")
check(S(ac="n200")["total"] == 2, "aircraft: partial, case-insensitive")
check(S(ac="aa0100")["total"] == 1, "aircraft also matches the flight number")
check(S(ac=".N300CC")["total"] == 2, "a leading dot is ignored")
check(S(ac="b003")["total"] == 2 and S(ac="A00")["total"] == 3, "aircraft also matches the address, partly")
check(S(q="loadsheet")["total"] == 1, "text contains, case-insensitive")
check(S(q="100%")["total"] == 1, "% is literal, not a wildcard")
check(S(q="1_00")["total"] == 0, "_ is literal, not a wildcard")
check(S(dir="DL")["total"] == 1 and S(dir="dl")["total"] == 1, "direction")
check(S(dir="XX")["total"] == 5 and S(dir="XX")["filters"]["dir"] == "", "a bad direction is ignored")
check(S(lbl="H1")["total"] == 3, "label")
c = S(kind="cpdlc")
check(c["total"] == 1 and c["rows"][0]["summary"] == "CLIMB TO FL350", "CPDLC filter + summary joined")
check(S(ch="136.800")["total"] == 2 and S(ch="136800000")["total"] == 2
      and S(ch="136.8")["filters"]["ch"] == "136.800", "channel, in MHz or Hz")
check(S(ch="banana")["total"] == 5 and S(ch="banana")["filters"]["ch"] == "", "a bad channel is ignored")
check(S(**{"from": "2026-11-11", "to": "2026-11-11"})["total"] == 2, "date range includes the To day (23:00)")
check(S(**{"from": "garbage"})["total"] == 5, "a bad date is ignored")
p1, p2 = S(limit=2), S(limit=2, offset=2)
check(len(p1["rows"]) == 2 and len(p2["rows"]) == 2 and p1["rows"][0] != p2["rows"][0], "paging")
check(S(limit=99999)["limit"] == search.SEARCH_LIMIT_MAX, "limit capped")
check(dict(r["labels"])["H1"] == 3 and dict(r["aircraft"])["N300CC"] == 2, "label and aircraft breakdowns")
check(dict(r["channels"]) == {136800000: 2, 136975000: 1, 136650000: 2}, "channel breakdown", r["channels"])
check([d for d, _ in r["days"]] == ["2026-11-10", "2026-11-11", "2026-11-12"], "matches per day")
check(r["rows"][0]["icao"] == "B00300" and r["rows"][0]["freq"] == 136800000, "rows carry address and channel")
csv = search.search_csv(db, {"dir": ["DL"]}).splitlines()
check(csv[0].startswith("time_utc,reg,flight,icao") and len(csv) == 2 and "A00200" in csv[1], "CSV export")
check("error" in search.build_search(os.path.join(tmp, "missing.db"), {}), "missing database reported")
# a database from before schema 2 (no address on messages)
old = os.path.join(tmp, "old.db")
con = sqlite3.connect(old)
con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, t INTEGER, reg TEXT, flt TEXT, dir TEXT, "
            "lbl TEXT, freq INTEGER, txt TEXT, has_cpdlc INTEGER, has_adsc INTEGER)")
con.commit()
con.close()
check("rollup.py" in search.build_search(old, {}).get("error", ""), "an older database says to run the rollup")

sys.exit(1 if fails else 0)
