# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""
VDL2 Observatory — Search: every stored ACARS message, filtered by aircraft
(registration, flight or address, partial), text, label, direction,
CPDLC/ADS-C, channel and a UTC date range, with the matches per day and the
top labels, aircraft and channels. Ported from iridium-observatory's Search
tab (observatory/trends_server.py); the address and channel are VDL2's.

Every value is a bound parameter, with % and _ taken literally in the
partial matches, and a query still running after SEARCH_TIME_LIMIT_S is
stopped, so a broad search can't starve the receiver. Heartbeats (label _d)
are left out unless asked for.
"""
import calendar
import csv
import io
import os
import sqlite3
import time

SEARCH_LIMIT_MAX = 1000       # rows per page
SEARCH_CSV_MAX = 100000       # rows in one CSV export
SEARCH_TIME_LIMIT_S = 5.0     # abandon a query that runs longer (protects the receiver's CPU)


def _like(text):
    """A LIKE pattern matching `text` anywhere, with % and _ taken literally."""
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _day_start(s):
    """Epoch seconds at 00:00 UTC of a YYYY-MM-DD date, or None."""
    try:
        return calendar.timegm(time.strptime(s.strip(), "%Y-%m-%d"))
    except (ValueError, AttributeError):
        return None


def _freq(s):
    """A channel in MHz (136.975) or Hz (136975000), as Hz; None if not one."""
    try:
        x = float(s)
    except (TypeError, ValueError):
        return None
    if 100 <= x < 200:
        x *= 1e6
    return int(round(x)) if 100e6 <= x < 200e6 else None


def search_filters(q):
    """(WHERE clause, args, cleaned filters) from the query-string dict."""
    def one(k):
        return (q.get(k, [""])[0] or "").strip()
    f = {"ac": one("ac").upper().lstrip("."), "q": one("q"), "lbl": one("lbl"),
         "dir": one("dir").upper(), "kind": one("kind").lower(), "ch": one("ch"),
         "from": one("from"), "to": one("to"), "hb": one("hb") in ("1", "true", "on")}
    where, args = [], []
    if not f["hb"]:
        where.append("lbl != '_d'")
    if f["ac"]:
        where.append("(reg LIKE ? ESCAPE '\\' OR flt LIKE ? ESCAPE '\\' OR icao LIKE ? ESCAPE '\\')")
        args += [_like(f["ac"])] * 3
    if f["q"]:
        where.append("txt LIKE ? ESCAPE '\\'")
        args.append(_like(f["q"]))
    if f["lbl"]:
        where.append("lbl = ?")
        args.append(f["lbl"])
    if f["dir"] in ("DL", "UL"):
        where.append("dir = ?")
        args.append(f["dir"])
    else:
        f["dir"] = ""
    if f["kind"] == "cpdlc":
        where.append("has_cpdlc = 1")
    elif f["kind"] == "adsc":
        where.append("has_adsc = 1")
    else:
        f["kind"] = ""
    ch = _freq(f["ch"])
    if ch is not None:
        where.append("freq = ?")
        args.append(ch)
        f["ch"] = "%.3f" % (ch / 1e6)
    else:
        f["ch"] = ""
    a, b = _day_start(f["from"]), _day_start(f["to"])
    if a is not None:
        where.append("t >= ?")
        args.append(a)
    else:
        f["from"] = ""
    if b is not None:
        where.append("t < ?")
        args.append(b + 86400)      # the To day is included
    else:
        f["to"] = ""
    return ("WHERE " + " AND ".join(where)) if where else "", args, f


def _search_con(path):
    if not os.path.exists(path):
        return None
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    deadline = time.monotonic() + SEARCH_TIME_LIMIT_S
    # Returning non-zero aborts the running statement (sqlite3.OperationalError).
    con.set_progress_handler(lambda: time.monotonic() > deadline, 20000)
    return con


def build_search(path, q):
    """One page of matching messages, the total, and the per-day, per-label,
    per-aircraft and per-channel breakdown of all matches."""
    con = _search_con(path)
    if con is None:
        return {"error": "no database yet: run rollup.py first"}
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='messages'").fetchone():
            return {"error": "no messages table yet: run rollup.py first"}
        cols = {r[1] for r in con.execute("PRAGMA table_info(messages)")}
        if "icao" not in cols:
            return {"error": "the database predates Search: run rollup.py once to add "
                             "the aircraft address to messages"}
        where, args, f = search_filters(q)

        def num(k, default, lo, hi):
            try:
                return max(lo, min(hi, int(q.get(k, [default])[0])))
            except ValueError:
                return int(default)
        limit = num("limit", "200", 1, SEARCH_LIMIT_MAX)
        offset = num("offset", "0", 0, 10 ** 9)
        order = "ASC" if (q.get("sort", [""])[0] == "oldest") else "DESC"

        rows = [{"t": t, "reg": reg, "flt": flt, "icao": icao or "", "dir": d, "lbl": lbl, "freq": fr,
                 "txt": txt, "cpdlc": bool(hc), "adsc": bool(ha), "summary": summ}
                for t, reg, flt, icao, d, lbl, fr, txt, hc, ha, summ in con.execute(
                    "SELECT t, reg, flt, icao, dir, lbl, freq, txt, has_cpdlc, has_adsc, "
                    "CASE WHEN has_cpdlc=1 THEN (SELECT summary FROM cpdlc_log c "
                    "  WHERE c.t=m.t AND c.reg=m.reg LIMIT 1) "
                    "WHEN has_adsc=1 THEN (SELECT summary FROM adsc_log a "
                    "  WHERE a.t=m.t AND a.reg=m.reg LIMIT 1) END "
                    "FROM messages m " + where +
                    " ORDER BY t %s, id %s LIMIT ? OFFSET ?" % (order, order),
                    args + [limit, offset])]
        days = con.execute("SELECT date(t,'unixepoch'), COUNT(*) FROM messages " + where +
                           " GROUP BY 1 ORDER BY 1", args).fetchall()
        total = sum(n for _, n in days)     # one scan fewer than a separate COUNT(*)
        labels = con.execute("SELECT lbl, COUNT(*) FROM messages " + where +
                             " GROUP BY lbl ORDER BY 2 DESC LIMIT 15", args).fetchall()
        aircraft = con.execute("SELECT reg, COUNT(*) FROM messages " + where +
                               (" AND " if where else "WHERE ") + "reg != ''"
                               " GROUP BY reg ORDER BY 2 DESC LIMIT 15", args).fetchall()
        channels = con.execute("SELECT freq, COUNT(*) FROM messages " + where +
                               " GROUP BY freq ORDER BY 2 DESC LIMIT 15", args).fetchall()
        span = con.execute("SELECT MIN(t), MAX(t) FROM messages").fetchone()
        return {"filters": f, "total": total, "offset": offset, "limit": limit,
                "sort": "oldest" if order == "ASC" else "newest", "rows": rows,
                "days": days, "labels": labels, "aircraft": aircraft, "channels": channels,
                "span": {"first": span[0], "last": span[1]}, "now": int(time.time())}
    except sqlite3.OperationalError as e:
        if "interrupt" in str(e):
            return {"error": "the search took longer than %d s and was stopped: "
                             "narrow it with a date range or an aircraft" % SEARCH_TIME_LIMIT_S}
        raise
    finally:
        con.close()


def search_csv(path, q):
    """All matching messages (up to SEARCH_CSV_MAX) as CSV text."""
    con = _search_con(path)
    if con is None:
        return "error\nno database yet\n"
    try:
        where, args, _ = search_filters(q)
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["time_utc", "reg", "flight", "icao", "dir", "label", "freq_hz", "cpdlc", "adsc", "text"])
        for t, reg, flt, icao, d, lbl, fr, txt, hc, ha in con.execute(
                "SELECT t, reg, flt, icao, dir, lbl, freq, txt, has_cpdlc, has_adsc FROM messages " + where +
                " ORDER BY t, id LIMIT ?", args + [SEARCH_CSV_MAX]):
            w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t)), reg, flt, icao or "", d, lbl,
                        fr, int(bool(hc)), int(bool(ha)), txt])
        return out.getvalue()
    except sqlite3.OperationalError as e:
        if "interrupt" in str(e):
            return "error\nthe export took longer than %d s and was stopped: narrow the search\n" % SEARCH_TIME_LIMIT_S
        raise
    finally:
        con.close()
