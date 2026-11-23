# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""
VDL2 Observatory — Flights: each aircraft heard in the last hours, where it
has been and where it is going, from what its own messages say.

  track        positions the aircraft reported: its XIDs (to 0.1 degree) and
               ACARS position reports and ADS-C, as the receiver placed them
               (vdl2_pos). Never a fix it merely named (src 'fix'): it may
               be well past it.
  route        origin and destination, from the aircraft's own messages in
               the layouts below, each checked against the destination the
               same aircraft gave in its XIDs (two days on the feeder):
                 TRP header         TRP KMIA KMSP          77/78 agree
                 02E header         02E21KMCOKOKC (WN)     204/213
                 LDR01 fields       LDR01,..,KLAS,KMCO,..  61/62
                 POSRPT O/D         POSRPT 1544/20 KXNA/KTPA  60/66
                 POS0n fields       POS02,N..W..,289,KPNS,KFTY,  9/10
                 time O D           190339 KATL KPNS (DL)  167/171
                 LDG DATA REQ       LDG DATA REQ / KDEN KMCO  24/24
               Most disagreements are an XID naming the origin while the
               aircraft is still there.
  destination  the airport in the aircraft's XIDs (dst_airport), when no
               route says more.
  plan, atis, takeoff
               ground-sent flight plans, ATIS and takeoff data (context.py's
               rules, shared with iridium-observatory). Only a receiver that
               hears ground stations gets these; the feeder hears none.

Positions and XIDs carry the aircraft's address, messages its registration
and flight too (messages.icao, schema 2), so aircraft are keyed by address.
"""
import re
import sqlite3
import time

import context
import vdl2_view

A = r"([A-Z]{4})"
ROUTE_RULES = [
    ("TRP header", re.compile(r"\bTRP " + A + r" " + A + r"\b")),
    ("02E header", re.compile(r"(?m)^\s*\d{2}E\d{2}" + A + A + r"\s*$")),
    ("LDR01 fields", re.compile(r"\bLDR01,(?:[^,\r\n]*,)*?" + A + r"," + A + r",")),
    ("POSRPT O/D", re.compile(r"POSRPT\s+\S+\s+" + A + r"/" + A + r"\b")),
    ("POS0n fields", re.compile(r"^POS0\d,[NS]\d{5}[EW]\d{6},[^,]*," + A + r"," + A + r",")),
    ("time O D", re.compile(r"(?m)^\d{6} " + A + r" " + A)),
    ("LDG DATA REQ", re.compile(r"LDG DATA REQ\s*/\s*" + A + r" " + A + r"\b")),
]
TRACK_SOURCES = ("xid", "text", "adsc")
TRACK_MAX = 200
# A track keeps only points it could have flown between: 700 kt, plus 20 km
# for the XIDs' 0.1-degree rounding.
MAX_KM_S = 700 * 1.852 / 3600
SLACK_KM = 20.0


def plausible(track):
    """The track's points that hang together, in time order. Text positions
    include some that are not where the aircraft was at that time: intent
    lists of points ahead (H1 IDL0...), and an earlier entry of a position
    history taken from one block of a multi-block message. Starting from the
    newest XID (a fixed layout the aircraft sends itself), else the newest
    point, a point is kept when the one kept before it, either way in time,
    is within reach."""
    if len(track) < 2:
        return track
    # Text positions seconds apart are the blocks of one message, each giving
    # the last entry it holds: the final block's is the newest.
    track = sorted(track)
    track = [p for i, p in enumerate(track)
             if not (p[4] == "text" and i + 1 < len(track) and track[i + 1][4] == "text"
                     and track[i + 1][0] - p[0] <= 20)]
    xi = [i for i, p in enumerate(track) if p[4] == "xid"]
    a = xi[-1] if xi else len(track) - 1

    def ok(p, q):
        return context.km((p[1], p[2]), (q[1], q[2])) <= SLACK_KM + MAX_KM_S * abs(p[0] - q[0])

    keep = [track[a]]
    for p in track[a + 1:]:
        if ok(p, keep[-1]):
            keep.append(p)
    before = []
    for p in reversed(track[:a]):
        if ok(p, before[-1] if before else track[a]):
            before.append(p)
    return before[::-1] + keep


def route_from_text(txt, ref):
    """(origin, destination, rule) from an aircraft-sent message, or None."""
    t = txt or ""
    for name, rx in ROUTE_RULES:
        m = rx.search(t)
        if not m:
            continue
        o, d = m.group(1), m.group(2)
        if o != d and ref.airport(o) and ref.airport(d):
            return o, d, name
    return None


def _airport(ref, code):
    p = ref.airport(code)
    return {"code": code, "name": ref.airport_name(code),
            "pos": [round(p[0], 4), round(p[1], 4)] if p else None}


def build_flights(db_path, ref, hours=6, now=None, stations=None, centre=None):
    """centre: (lat, lon) the radio horizon is measured from (see
    vdl2_view.receiver_centre); positions beyond it are left out."""
    now = time.time() if now is None else now
    t0 = now - hours * 3600
    con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True, timeout=5)
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(messages)")}
        if "icao" not in cols:
            return {"error": "the database predates the Flights page: run "
                             "rollup.py once to add the aircraft address to messages"}
        msgs = con.execute(
            "SELECT id, t, icao, reg, flt, dir, lbl, txt FROM messages "
            "WHERE t >= ? AND t <= ? AND icao IS NOT NULL ORDER BY t", (t0, now)).fetchall()
        if centre is None:
            centre = vdl2_view.receiver_centre(con)
        pos = [r for r in con.execute(
            "SELECT t, icao, gs, lat, lon, alt, src FROM vdl2_pos "
            "WHERE t >= ? AND t <= ? ORDER BY t", (t0, now)) if vdl2_view.in_range(centre, r[3], r[4])]
        xids = con.execute(
            "SELECT t, icao, gs, airport FROM vdl2_xid "
            "WHERE t >= ? AND t <= ? ORDER BY t", (t0, now)).fetchall()
    finally:
        con.close()

    ac = {}

    def entry(icao):
        e = ac.get(icao)
        if e is None:
            e = ac[icao] = {"icao": icao, "reg": "", "flight": "", "last": 0, "msgs": 0,
                            "track": [], "gs": "", "gs_t": 0, "route": None,
                            "xid_dest": None, "plan": None, "atis": None, "takeoff": None,
                            "last_msg": None}
        return e

    def seen(e, t, gs=None):
        e["last"] = max(e["last"], t)
        if gs and t >= e["gs_t"]:
            e["gs"], e["gs_t"] = gs, t

    for mid, t, icao, reg, flt, d, lbl, txt in msgs:
        e = entry(icao)
        e["msgs"] += 1
        seen(e, t)
        if reg:
            e["reg"] = reg
        if flt:
            e["flight"] = flt
        e["last_msg"] = {"t": t, "lbl": lbl, "dir": d, "txt": (txt or "")[:300]}
        if d == "UL":          # aircraft-sent (iridium-sniffer's convention)
            r = route_from_text(txt, ref)
            if r:
                e["route"] = {"origin": r[0], "dest": r[1], "src": r[2], "t": t, "id": mid}
        else:                  # ground-sent: flight plans, ATIS, takeoff data
            for it in context.infer(lbl, txt, d, ref):
                it.update(t=t, id=mid)
                k = it["kind"]
                if k in ("plan", "plan_notice"):
                    e["plan"] = it
                    e["route"] = {"origin": it["origin"], "dest": it["dest"],
                                  "src": "flight plan" if k == "plan" else "plan notice",
                                  "t": t, "id": mid}
                elif k in ("atis", "takeoff"):
                    e[k] = it
    for t, icao, gs, lat, lon, alt, src in pos:
        if src not in TRACK_SOURCES or lat is None or lon is None:
            continue
        e = entry(icao)
        seen(e, t, gs)
        e["track"].append([int(t), round(lat, 4), round(lon, 4), alt, src])
    for t, icao, gs, airport in xids:
        e = entry(icao)
        seen(e, t, gs)
        if airport and ref.airport(airport):
            e["xid_dest"] = {"code": airport, "t": t}

    out = []
    n_track = n_route = n_dest = 0
    for e in ac.values():
        if not e["msgs"] and not e["track"] and not e["xid_dest"]:
            continue
        e["track"] = plausible(e["track"])[-TRACK_MAX:]
        r = e["route"]
        route = None
        if r:
            route = {"origin": _airport(ref, r["origin"]), "dest": _airport(ref, r["dest"]),
                     "src": r["src"], "t": r["t"]}
        dest = None
        if e["xid_dest"]:
            dest = dict(_airport(ref, e["xid_dest"]["code"]), t=e["xid_dest"]["t"], src="XID")
        plan = None
        if e["plan"] and e["plan"]["kind"] == "plan":
            p = e["plan"]
            plan = {"route": [[round(q[0], 4), round(q[1], 4)] for q in p["route"]],
                    "via": p.get("via", []), "cruise_fl": p.get("cruise_fl"),
                    "dep_hhmm": p.get("dep_hhmm"), "t": p["t"]}
        extra = {}
        for k in ("atis", "takeoff"):
            if e[k]:
                extra[k] = dict(_airport(ref, e[k]["airport"]), t=e[k]["t"],
                                role=e[k].get("role"))
        n_track += bool(e["track"])
        n_route += bool(route)
        n_dest += bool(route or dest)
        out.append({"icao": e["icao"], "reg": e["reg"], "flight": e["flight"],
                    "last": int(e["last"]), "msgs": e["msgs"], "gs": e["gs"],
                    "track": e["track"], "route": route, "xid_dest": dest, "plan": plan,
                    "last_msg": e["last_msg"], **extra})
    out.sort(key=lambda x: -x["last"])
    return {"now": int(now), "hours": hours, "stations": stations or [],
            "totals": {"aircraft": len(out), "with_track": n_track,
                       "with_route": n_route, "with_destination": n_dest},
            "aircraft": out}
