# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""
VDL2 Observatory — Graph: the ground-station handoff network, and one
aircraft's history. The counterpart of iridium-observatory's Graph tab, built
from what VDL2 carries: every XID handoff names the station the aircraft
leaves and the one it joins (vdl2_xid.from_gs -> gs, as rollup.py records
them: the previous station heard within HANDOFF_WINDOW).

  network   stations at their estimated positions (vdl2_view.estimate_stations,
            all time), and per directed pair the handoffs and distinct
            aircraft in the window
  aircraft  one aircraft by registration, flight or address: when it was
            heard, messages per day, the stations it used, its recent
            handoffs, and the routes its own messages gave (flights.py's
            layouts)
"""
import re
import sqlite3
import time

import context
import flights

HEX = re.compile(r"^[0-9A-F]{6}$")


def _con(path):
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)


def build_network(db_path, stations, hours=168, now=None):
    """stations: vdl2_view.estimate_stations() output (all time)."""
    now = time.time() if now is None else now
    t0 = now - hours * 3600
    con = _con(db_path)
    try:
        pairs = con.execute(
            "SELECT from_gs, gs, COUNT(*), COUNT(DISTINCT icao), MAX(t) FROM vdl2_xid "
            "WHERE t >= ? AND t <= ? AND from_gs IS NOT NULL AND from_gs != '' AND from_gs != gs "
            "GROUP BY from_gs, gs", (t0, now)).fetchall()
        heard = dict(con.execute(
            "SELECT gs, COUNT(DISTINCT icao) FROM vdl2_xid WHERE t >= ? AND t <= ? GROUP BY gs",
            (t0, now)).fetchall())
        n_ac = con.execute("SELECT COUNT(DISTINCT icao) FROM vdl2_xid WHERE t >= ? AND t <= ? "
                           "AND from_gs IS NOT NULL AND from_gs != ''", (t0, now)).fetchone()[0]
    finally:
        con.close()
    est = {s["station"]: s for s in stations}
    deg = {}
    for f, g, n, ac, last in pairs:
        deg.setdefault(f, [0, 0])[0] += n
        deg.setdefault(g, [0, 0])[1] += n
    out_st = []
    for gs in sorted(set(deg) | set(heard)):
        # Stations have no names, only addresses; their positions are the
        # Overview's estimates (and lean towards this receiver for distant
        # ones), so no nearest-airport label is offered.
        e = est.get(gs, {})
        out_st.append({"station": gs, "lat": e.get("lat"), "lon": e.get("lon"),
                       "spread_km": e.get("spread_km"), "n_pos": e.get("n_pos", 0),
                       "out": deg.get(gs, [0, 0])[0], "in": deg.get(gs, [0, 0])[1],
                       "aircraft": heard.get(gs, 0)})
    out_st.sort(key=lambda s: -(s["in"] + s["out"]))
    out_pairs = [{"from": f, "to": g, "handoffs": n, "aircraft": ac, "last": int(last)}
                 for f, g, n, ac, last in sorted(pairs, key=lambda p: -p[2])]
    placed = {s["station"] for s in out_st if s["lat"] is not None}
    return {"now": int(now), "hours": hours, "stations": out_st, "pairs": out_pairs,
            "totals": {"handoffs": sum(p["handoffs"] for p in out_pairs),
                       "pairs": len(out_pairs), "stations": len(out_st), "placed": len(placed),
                       "aircraft": n_ac}}


def aircraft_list(db_path, days=7, now=None, limit=400):
    """The aircraft heard most in the last days, for the page's suggestions."""
    now = time.time() if now is None else now
    con = _con(db_path)
    try:
        return [{"icao": i, "reg": r, "flight": f, "msgs": n} for i, r, f, n in con.execute(
            "SELECT icao, MAX(reg), MAX(flt), COUNT(*) FROM messages WHERE t >= ? AND icao IS NOT NULL "
            "AND lbl != '_d' GROUP BY icao ORDER BY 4 DESC LIMIT ?", (now - days * 86400, limit))]
    finally:
        con.close()


def _every_day(rows):
    """[(YYYY-MM-DD, msgs, acks)] with the days between that heard nothing
    filled in as zeros, so the strip shows the gaps."""
    import datetime
    have = {d: (m or 0, a or 0) for d, m, a in rows}
    if not have:
        return []
    day, last = (datetime.date.fromisoformat(min(have)), datetime.date.fromisoformat(max(have)))
    out = []
    while day <= last:
        m, a = have.get(day.isoformat(), (0, 0))
        out.append({"day": day.isoformat(), "msgs": m, "acks": a})
        day += datetime.timedelta(days=1)
    return out


def build_aircraft(db_path, ref, q, now=None):
    """One aircraft by registration, flight or address (exact, case-blind)."""
    now = time.time() if now is None else now
    q = (q or "").strip().upper().lstrip(".")
    if not q:
        return {"error": "give a registration, flight or address"}
    con = _con(db_path)
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(messages)")}
        if "icao" not in cols:
            return {"error": "the database predates the Graph page: run rollup.py once"}
        icaos = [q] if HEX.match(q) else []
        if not icaos or not con.execute("SELECT 1 FROM messages WHERE icao=? LIMIT 1", (q,)).fetchone():
            hits = [r[0] for r in con.execute(
                "SELECT icao, MAX(t) FROM messages WHERE (UPPER(reg)=? OR UPPER(flt)=?) AND icao IS NOT NULL "
                "GROUP BY icao ORDER BY 2 DESC", (q, q))]
            if hits:
                icaos = hits
            elif not icaos:
                return {"error": "no messages from an aircraft with that registration, flight or address"}
        icao = icaos[0]
        regs = con.execute("SELECT reg, COUNT(*) FROM messages WHERE icao=? AND reg != '' GROUP BY reg "
                           "ORDER BY 2 DESC", (icao,)).fetchall()
        flts = con.execute("SELECT flt, COUNT(*), MAX(t) FROM messages WHERE icao=? AND flt != '' GROUP BY flt "
                           "ORDER BY 3 DESC LIMIT 20", (icao,)).fetchall()
        days = con.execute(
            "SELECT date(t,'unixepoch'), SUM(lbl != '_d'), SUM(lbl = '_d') FROM messages WHERE icao=? "
            "GROUP BY 1 ORDER BY 1", (icao,)).fetchall()
        span = con.execute("SELECT MIN(t), MAX(t), COUNT(*) FROM messages WHERE icao=?", (icao,)).fetchone()
        xids = con.execute("SELECT t, from_gs, gs, kind, airport FROM vdl2_xid WHERE icao=? ORDER BY t",
                           (icao,)).fetchall()
        st = con.execute("SELECT gs, COUNT(*), MAX(t) FROM (SELECT gs, t FROM vdl2_xid WHERE icao=? "
                         "UNION ALL SELECT gs, t FROM vdl2_pos WHERE icao=?) GROUP BY gs ORDER BY 2 DESC",
                         (icao, icao)).fetchall()
        msgs = con.execute("SELECT t, flt, dir, txt FROM messages WHERE icao=? AND dir='UL' ORDER BY t DESC "
                           "LIMIT 3000", (icao,)).fetchall()
        npos = con.execute("SELECT COUNT(*) FROM vdl2_pos WHERE icao=? AND src IN ('xid','text','adsc')",
                           (icao,)).fetchone()[0]
    finally:
        con.close()
    routes, seen = [], set()
    for t, flt, d, txt in msgs:
        r = flights.route_from_text(txt, ref)
        if not r:
            continue
        key = (time.strftime("%Y-%m-%d", time.gmtime(t)), r[0], r[1])
        if key in seen:
            continue
        seen.add(key)
        routes.append({"day": key[0], "t": int(t), "flight": flt or "", "origin": r[0], "dest": r[1],
                       "origin_name": ref.airport_name(r[0]), "dest_name": ref.airport_name(r[1]), "src": r[2]})
    dests = {}
    for t, f, g, kind, ap in xids:
        if ap:
            key = (time.strftime("%Y-%m-%d", time.gmtime(t)), ap)
            dests.setdefault(key, int(t))
    return {"icao": icao, "others": icaos[1:6], "regs": [r for r, _ in regs], "flights": [
        {"flight": f, "msgs": n, "last": int(last)} for f, n, last in flts],
        "first": int(span[0]) if span[0] else None, "last": int(span[1]) if span[1] else None,
        "msgs": span[2], "positions": npos, "days": _every_day(days),
        "stations": [{"station": g, "n": n, "last": int(last)} for g, n, last in st],
        "handoffs": [{"t": int(t), "from": f or "", "to": g, "kind": k or "", "airport": ap or ""}
                     for t, f, g, k, ap in xids[-60:]][::-1],
        "routes": routes[:40],
        "xid_destinations": [{"day": d, "airport": ap, "name": ref.airport_name(ap), "t": t}
                             for (d, ap), t in sorted(dests.items(), key=lambda kv: -kv[1])][:40],
        "now": int(now)}
