#!/usr/bin/env python3
# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""
VDL2 Observatory — archive rollup

Folds the append-only JSONL archive written by vdl2-sniffer's --archive
flag into hourly aggregates and per-message rows in a SQLite database, so
the dashboard can query weeks of history cheaply. Adapted from
iridium-sniffer's observatory/rollup.py.

Design:
  * Incremental. Per-file byte offsets are tracked in `ingest_state`, so
    each run only reads bytes appended since last time. Re-running is safe
    and cheap; the current (growing) day file is picked up a bit at a time.
  * Only complete lines (terminated by '\n') are consumed. A partial
    trailing line is left for the next run.
  * Aggregates are UPSERT-added, so a line counted once always lands in
    exactly one hour bucket regardless of how the reads were chunked.
  * Deleting the DB triggers a clean full re-ingest (ingest_state lives in
    the same DB).

Time units — the one invariant worth stating loudly:
  * The JSONL archive carries `t` in **milliseconds**.
  * Every timestamp column in the DB is **epoch seconds** — `hour` buckets
    and the message-level `t` alike. Convert once, at the boundary, via
    sec_of()/hour_of(); never store a raw ev["t"].
Usage:
    rollup.py [--archive DIR] [--db PATH] [--verbose]

Defaults:
    --archive ./archive     --db ./observatory/observatory.db
"""

import argparse
import glob
import json
import os
import sqlite3
import sys
import time

SCHEMA_VERSION = 1

# A handoff's previous station must have been heard within this many seconds.
HANDOFF_WINDOW = 1800

def sec_of(t_ms):
    """Epoch seconds for the archive's ms stamp. The only ms->s boundary."""
    return int(t_ms) // 1000


def hour_of(t_ms):
    """UTC hour bucket (epoch seconds at the hour boundary) for a ms stamp."""
    return sec_of(t_ms) // 3600 * 3600


def init_db(con):
    con.executescript(
        """
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY, value TEXT
        );
        CREATE TABLE IF NOT EXISTS ingest_state (
            file    TEXT PRIMARY KEY,
            offset  INTEGER NOT NULL,   -- bytes consumed
            size    INTEGER NOT NULL,   -- file size at last read
            updated INTEGER NOT NULL    -- epoch of last run
        );
        -- Message-level tables: one row per decoded message, so the
        -- aviation dashboard can browse per-tail history and the CPDLC log.
        -- Populated by the same incremental pass; rows are append-only and
        -- each archive event is ingested exactly once (byte-offset tracked).
        CREATE TABLE IF NOT EXISTS messages (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            t        INTEGER,          -- epoch SECONDS (see module docstring)
            reg      TEXT, flt TEXT, dir TEXT, lbl TEXT,
            freq     INTEGER, txt TEXT,
            has_cpdlc INTEGER, has_adsc INTEGER
        );
        CREATE INDEX IF NOT EXISTS ix_messages_reg ON messages(reg);
        CREATE INDEX IF NOT EXISTS ix_messages_t   ON messages(t);

        CREATE TABLE IF NOT EXISTS cpdlc_log (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            t       INTEGER, reg TEXT, flt TEXT, dir TEXT,
            txt     TEXT,               -- ACARS free text, if any
            summary TEXT,               -- readable gist from the decoded tree
            dec     TEXT                -- full cpdlc subtree JSON, for detail
        );
        CREATE INDEX IF NOT EXISTS ix_cpdlc_t ON cpdlc_log(t);

        -- ADS-C log. `kinds` lists the tag names present (contract requests
        -- vs. actual reports); `has_pos`/lat/lon/alt are populated only when
        -- the message carries real coordinates.
        CREATE TABLE IF NOT EXISTS adsc_log (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            t       INTEGER, reg TEXT, flt TEXT, dir TEXT,
            txt     TEXT,
            kinds   TEXT,               -- comma-joined ADS-C tag names
            summary TEXT,               -- readable gist
            has_pos INTEGER,            -- 1 iff lat+lon decoded
            lat     REAL, lon REAL, alt INTEGER,
            dec     TEXT                -- full adsc subtree JSON
        );
        CREATE INDEX IF NOT EXISTS ix_adsc_t   ON adsc_log(t);
        CREATE INDEX IF NOT EXISTS ix_adsc_pos ON adsc_log(has_pos);

        -- Per channel,
        -- bursts and frames come from the per-minute "vmix" health event;
        -- everything else from the per-frame "vframe" event.
        CREATE TABLE IF NOT EXISTS vdl2_channel_hourly (
            hour INTEGER, freq INTEGER, bursts INTEGER, frames INTEGER,
            PRIMARY KEY (hour, freq)
        );
        CREATE TABLE IF NOT EXISTS vdl2_snr_hourly (
            hour INTEGER, freq INTEGER, bin INTEGER, count INTEGER,
            PRIMARY KEY (hour, freq, bin)   -- bin = 2 dB floor of the SNR
        );
        CREATE TABLE IF NOT EXISTS vdl2_station_hourly (
            hour INTEGER, station TEXT, count INTEGER,
            PRIMARY KEY (hour, station)
        );
        CREATE TABLE IF NOT EXISTS vdl2_aircraft_hourly (
            hour INTEGER, icao TEXT, count INTEGER, best_snr REAL,
            PRIMARY KEY (hour, icao)
        );
        CREATE TABLE IF NOT EXISTS vdl2_msg_hourly (
            hour INTEGER, service TEXT, dir TEXT, count INTEGER,
            PRIMARY KEY (hour, service, dir)
        );

        -- XID frames, one row each. `gs` is the ground station
        -- the frame went to or came from; `from_gs` is the station the
        -- aircraft last exchanged frames with (within HANDOFF_WINDOW), so a
        -- handoff row is an edge from_gs -> gs. Positions are the aircraft's
        -- own report (0.1 degree, altitude in 1000 ft steps).
        CREATE TABLE IF NOT EXISTS vdl2_xid (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            t       INTEGER, icao TEXT, gs TEXT, from_gs TEXT,
            kind    TEXT,               -- e.g. Handoff Initiation, or ''
            airport TEXT,
            lat REAL, lon REAL, alt INTEGER,
            alt_gs  TEXT                -- space-joined alternate stations
        );
        CREATE INDEX IF NOT EXISTS ix_vdl2_xid_t ON vdl2_xid(t);
        -- Aircraft positions, one row each, from every source:
        -- 'xid' (the aircraft's own XID report), 'text' (coordinates in
        -- ACARS text), 'fix' (a fix named in ACARS text: the aircraft may be
        -- well past it), 'adsc' (ADS-C). `gs` is the station the aircraft
        -- was talking to at the time.
        CREATE TABLE IF NOT EXISTS vdl2_pos (
            t INTEGER, icao TEXT, gs TEXT,
            lat REAL, lon REAL, alt INTEGER, src TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_vdl2_pos_t ON vdl2_pos(t);
        -- Each aircraft's latest ground station, carried between runs.
        CREATE TABLE IF NOT EXISTS vdl2_last_gs (
            icao TEXT PRIMARY KEY, gs TEXT, t INTEGER
        );
        """
    )
    con.execute(
        "INSERT INTO meta(key,value) VALUES('schema',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )
    con.commit()


def has_key(obj, name):
    """Recursively test whether a decoded-message tree contains a node
    whose key contains `name` (e.g. 'cpdlc', 'adsc'). libacars names its
    nodes after the message type, so this reliably tags CPDLC/ADS-C."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if name in k:
                return True
            if has_key(v, name):
                return True
    elif isinstance(obj, list):
        for v in obj:
            if has_key(v, name):
                return True
    return False


def find_node(obj, name):
    """Return the first sub-object whose key contains `name`, else None."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if name in k:
                return v
            r = find_node(v, name)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_node(v, name)
            if r is not None:
                return r
    return None


# Structural/bookkeeping keys that carry no readable clearance content.
_CPDLC_NOISE = {"err", "crc_ok", "mode", "label", "blk_id", "ack", "more",
                "reg", "imi", "msg_type", "timestamp", "dir", "msg_id"}


def cpdlc_summary(cpdlc_node, limit=12):
    """Best-effort readable gist of a decoded CPDLC message: collect the
    meaningful string/number leaves (route, level, beacon, free text, ...)
    from the decoded tree. Not a full renderer — the dashboard keeps the
    complete subtree for detail — but enough for a scannable log line."""
    leaves = []

    def walk(o):
        if len(leaves) >= limit:
            return
        if isinstance(o, dict):
            for k, v in o.items():
                # Skip whole timestamp/header subtrees — their hour/min/sec
                # leaves are bookkeeping, not clearance content.
                if isinstance(v, (dict, list)):
                    if "time" in k or "header" in k:
                        continue
                    walk(v)
                elif k in _CPDLC_NOISE:
                    continue
                elif isinstance(v, bool):
                    continue
                elif isinstance(v, str) and len(v) > 1:
                    leaves.append(f"{k}={v}")
                elif isinstance(v, (int, float)):
                    leaves.append(f"{k}={v}")
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(cpdlc_node)
    return " · ".join(leaves[:limit])


# Readable names for the ADS-C tags libacars emits. Anything unmapped falls
# through as its raw tag name, so a new/unknown tag still shows up rather
# than silently rendering blank.
_ADSC_LABELS = {
    # Ground -> air: the contract negotiation.
    "periodic_contract_req": "periodic contract",
    "event_contract_req": "event contract",
    "demand_contract_req": "demand contract",
    "cancel_contract_req": "cancel contract",
    "cancel_all_contracts_req": "cancel all contracts",
    "cancel_emergency_mode_req": "cancel emergency",
    # Event-contract trigger groups.
    "report_wpt_changes": "wpt changes",
    "report_when_alt_out_of_range": "alt band",
    "report_when_lateral_dev_exceeds": "lateral dev",
    "report_when_vspd_out_of_range": "vspd band",
    "report_when_airspeed_change_exceeds": "airspeed change",
    # Periodic-contract groups: how often, and which extras to include.
    "report_interval": "interval",
    "earth_ref_data": "earth ref",
    "air_ref_data": "air ref",
    "meteo_data": "meteo",
    # Air -> ground: the reports. `basic_report` is the one carrying position.
    "basic_report": "position",
    "flight_id": "flight id",
    "predicted_route": "predicted route",
    "earth_ref": "earth ref",
    "air_ref": "air ref",
    "meteo": "meteo",
    "airframe_id": "airframe id",
    "intermediate_proj": "intermediate projection",
    "fixed_proj": "fixed projection",
    "ack": "ack",
    "nack": "nack",
    "noncompliance_notify": "noncompliance",
}


def adsc_tags(adsc_node):
    """The ADS-C `tags` list is a list of single-key dicts; return the list of
    (name, body) pairs in order."""
    out = []
    tags = adsc_node.get("tags") if isinstance(adsc_node, dict) else None
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, dict):
                out.extend(tag.items())
    return out


def adsc_position(node):
    """(lat, lon, alt) of the first node carrying real coordinates, else None.

    Requires `lat` AND `lon` as exact keys in the *same* dict. This matters:
    the event-contract group `report_when_lateral_dev_exceeds` has a key
    `lat_dev_treshold_nm` (libacars' spelling), so a substring match on 'lat'
    would happily report a 5-nautical-mile deviation threshold as a latitude.
    """
    found = []

    def walk(o):
        if found:
            return
        if isinstance(o, dict):
            lat, lon = o.get("lat"), o.get("lon")
            if isinstance(lat, (int, float)) and not isinstance(lat, bool) \
               and isinstance(lon, (int, float)) and not isinstance(lon, bool):
                alt = o.get("alt")
                found.append((
                    float(lat), float(lon),
                    int(alt) if isinstance(alt, (int, float))
                    and not isinstance(alt, bool) else None))
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(node)
    return found[0] if found else None


def adsc_summary(adsc_node, limit=12):
    """Readable gist of a decoded ADS-C message, e.g.
       'event contract #8 · alt band 34796–35204 ft · wpt changes'
    Event-contract groups are flattened to the top level so the trigger
    conditions read as a flat list rather than a nested blob."""
    parts = []

    def emit(name, body):
        if len(parts) >= limit:
            return
        bits = []
        if isinstance(body, dict):
            if isinstance(body.get("contract_num"), int):
                bits.append(f"#{body['contract_num']}")
            lat, lon = body.get("lat"), body.get("lon")
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                bits.append(f"{lat:.4f},{lon:.4f}")
                if isinstance(body.get("alt"), (int, float)):
                    bits.append(f"{body['alt']} ft")
            f, c = body.get("floor_alt"), body.get("ceiling_alt")
            if f is not None and c is not None:
                bits.append(f"{f}–{c} ft")
            if body.get("lat_dev_treshold_nm") is not None:
                bits.append(f">{body['lat_dev_treshold_nm']} nm")
            if isinstance(body.get("interval_secs"), int):
                bits.append(f"{body['interval_secs']}s")
            # Periodic groups use a modulus: include this datum every Nth
            # report. Modulus 1 = every report, which is the common case.
            if isinstance(body.get("modulus"), int):
                bits.append("every report" if body["modulus"] == 1
                            else f"every {body['modulus']}th")
        label = _ADSC_LABELS.get(name, name)
        parts.append((label + " " + " ".join(bits)).strip())
        if isinstance(body, dict):
            for g in body.get("groups") or []:
                if isinstance(g, dict):
                    for gn, gb in g.items():
                        emit(gn, gb)

    for name, body in adsc_tags(adsc_node):
        emit(name, body)
    return " · ".join(parts[:limit])


def aircraft_station(ev):
    """(aircraft, ground station) for a VDL2 event between the two, else
    None. Address kinds: 1 aircraft, 4/5 ground station."""
    sk, dk = ev.get("sk"), ev.get("dk")
    if sk == 1 and dk in (4, 5):
        return ev["src"], ev["dst"]
    if sk in (4, 5) and dk == 1:
        return ev["dst"], ev["src"]
    return None


class Agg:
    """In-memory accumulator; flushed to the DB as UPSERT-adds."""

    def __init__(self):
        self.v_chan = {}  # (hour,freq) -> [bursts, frames]
        self.v_snr = {}   # (hour,freq,bin) -> count
        self.v_stn = {}   # (hour,station) -> count
        self.v_ac = {}    # (hour,icao) -> [count, best snr]
        self.v_msg = {}   # (hour,service,dir) -> count
        self.v_xid = []   # per-XID rows
        self.v_pos = []   # per-position rows, every source
        self.last_gs = {}  # icao -> (gs, t seconds); loaded from the DB
        self.messages = []  # per-message rows
        self.cpdlcs = []    # per-CPDLC rows
        self.adscs = []     # per-ADS-C rows
        self.lines = 0
        self.bad = 0

    def load_state(self, con):
        self.last_gs = {r[0]: (r[1], r[2]) for r in
                        con.execute("SELECT icao,gs,t FROM vdl2_last_gs")}

    def add(self, d, key, n=1):
        d[key] = d.get(key, 0) + n

    def event(self, ev):
        e = ev.get("e")
        if e == "vmix":
            h = hour_of(ev["t"])
            for freq, (bursts, frames) in ev.get("ch", {}).items():
                c = self.v_chan.setdefault((h, int(freq)), [0, 0])
                c[0] += bursts
                c[1] += frames
        elif e == "vframe":
            h = hour_of(ev["t"])
            snr = float(ev.get("snr", 0))
            self.add(self.v_snr, (h, int(ev["freq"]), int(snr // 2) * 2))
            # Address kinds: 1 aircraft, 4/5 ground station.
            for addr, kind in ((ev.get("src"), ev.get("sk")),
                               (ev.get("dst"), ev.get("dk"))):
                if kind in (4, 5):
                    self.add(self.v_stn, (h, addr))
                elif kind == 1:
                    a = self.v_ac.setdefault((h, addr), [0, snr])
                    a[0] += 1
                    a[1] = max(a[1], snr)
            # Who each aircraft is talking to. An XID's own frame is left to
            # the "xid" event that follows it, so the station it hands off
            # from is still the latest one.
            pair = aircraft_station(ev)
            if pair and ev.get("ctl") != "XID":
                self.last_gs[pair[0]] = (pair[1], sec_of(ev["t"]))
        elif e == "vpos":
            # a VDL2 position from ACARS text ('text' or 'fix')
            self.v_pos.append((sec_of(ev["t"]), ev["icao"], ev["gs"], ev["lat"],
                               ev["lon"], None, ev.get("src", "text")))
        elif e == "xid":
            pair = aircraft_station(ev)
            if pair:
                icao, gs = pair
                ts = sec_of(ev["t"])
                x = ev.get("x", {})
                prev = self.last_gs.get(icao)
                from_gs = (prev[0] if prev and prev[0] != gs
                           and 0 <= ts - prev[1] <= HANDOFF_WINDOW else None)
                loc = x.get("ac_location") or {}
                if loc.get("lat") is not None:
                    self.v_pos.append((ts, icao, gs, loc["lat"], loc["lon"],
                                       loc.get("alt_ft"), "xid"))
                self.v_xid.append((ts, icao, gs, from_gs, x.get("type", ""),
                                   x.get("dst_airport", ""), loc.get("lat"),
                                   loc.get("lon"), loc.get("alt_ft"),
                                   " ".join(x.get("alt_gs", []))))
                self.last_gs[icao] = (gs, ts)
        elif e == "acars":
            h = hour_of(ev["t"])
            ts = sec_of(ev["t"])
            dirname = ev.get("dir", "DL")
            hourly = self.v_msg
            self.add(hourly, (h, "acars", dirname))
            dec = ev.get("dec")
            is_cpdlc = is_adsc = False
            if dec is not None:
                if has_key(dec, "cpdlc"):
                    is_cpdlc = True
                    self.add(hourly, (h, "cpdlc", dirname))
                if has_key(dec, "adsc"):
                    is_adsc = True
                    self.add(hourly, (h, "adsc", dirname))
            reg = (ev.get("reg") or "").lstrip(".")
            flt = ev.get("flt") or ""
            txt = ev.get("txt") or ""
            self.messages.append((ts, reg, flt, dirname,
                                  ev.get("lbl") or "", ev.get("freq") or 0,
                                  txt, int(is_cpdlc), int(is_adsc)))
            if is_cpdlc:
                node = find_node(dec, "cpdlc")
                self.cpdlcs.append(
                    (ts, reg, flt, dirname, txt,
                     cpdlc_summary(node) if node is not None else "",
                     json.dumps(node, separators=(",", ":"))
                     if node is not None else ""))
            # Positions: the station is the other end of the frame, and UL
            # is aircraft to ground (iridium-sniffer's convention).
            vpair = None
            if ev.get("src") and ev.get("dst"):
                vpair = ((ev["src"], ev["dst"]) if dirname == "UL"
                         else (ev["dst"], ev["src"]))
            if is_adsc:
                node = find_node(dec, "adsc")
                pos = adsc_position(node) if node is not None else None
                if vpair and pos:
                    self.v_pos.append((ts, vpair[0], vpair[1], pos[0], pos[1],
                                       pos[2], "adsc"))
                kinds = ",".join(n for n, _ in adsc_tags(node)) \
                    if node is not None else ""
                self.adscs.append(
                    (ts, reg, flt, dirname, txt, kinds,
                     adsc_summary(node) if node is not None else "",
                     1 if pos else 0,
                     pos[0] if pos else None,
                     pos[1] if pos else None,
                     pos[2] if pos else None,
                     json.dumps(node, separators=(",", ":"))
                     if node is not None else ""))
        # 'start' and unknown events: ignored.

    def flush(self, con):
        def upsert(table, cols, d):
            q = (f"INSERT INTO {table}({','.join(cols)},count) "
                 f"VALUES({','.join('?' * len(cols))},?) "
                 f"ON CONFLICT({','.join(cols)}) "
                 f"DO UPDATE SET count=count+excluded.count")
            con.executemany(q, [(*k, v) for k, v in d.items()])

        upsert("vdl2_snr_hourly", ("hour", "freq", "bin"), self.v_snr)
        upsert("vdl2_station_hourly", ("hour", "station"), self.v_stn)
        upsert("vdl2_msg_hourly", ("hour", "service", "dir"), self.v_msg)
        con.executemany(
            "INSERT INTO vdl2_channel_hourly(hour,freq,bursts,frames) "
            "VALUES(?,?,?,?) ON CONFLICT(hour,freq) DO UPDATE SET "
            "bursts=bursts+excluded.bursts, frames=frames+excluded.frames",
            [(*k, v[0], v[1]) for k, v in self.v_chan.items()])
        con.executemany(
            "INSERT INTO vdl2_aircraft_hourly(hour,icao,count,best_snr) "
            "VALUES(?,?,?,?) ON CONFLICT(hour,icao) DO UPDATE SET "
            "count=count+excluded.count, "
            "best_snr=MAX(best_snr,excluded.best_snr)",
            [(*k, v[0], v[1]) for k, v in self.v_ac.items()])

        con.executemany(
            "INSERT INTO vdl2_xid(t,icao,gs,from_gs,kind,airport,lat,lon,alt,"
            "alt_gs) VALUES(?,?,?,?,?,?,?,?,?,?)", self.v_xid)
        con.executemany(
            "INSERT INTO vdl2_pos(t,icao,gs,lat,lon,alt,src) "
            "VALUES(?,?,?,?,?,?,?)", self.v_pos)
        con.executemany(
            "INSERT INTO vdl2_last_gs(icao,gs,t) VALUES(?,?,?) "
            "ON CONFLICT(icao) DO UPDATE SET gs=excluded.gs, t=excluded.t "
            "WHERE excluded.t >= vdl2_last_gs.t",
            [(k, v[0], v[1]) for k, v in self.last_gs.items()])
        con.executemany(
            "INSERT INTO messages(t,reg,flt,dir,lbl,freq,txt,has_cpdlc,"
            "has_adsc) VALUES(?,?,?,?,?,?,?,?,?)", self.messages)
        con.executemany(
            "INSERT INTO cpdlc_log(t,reg,flt,dir,txt,summary,dec) "
            "VALUES(?,?,?,?,?,?,?)", self.cpdlcs)
        con.executemany(
            "INSERT INTO adsc_log(t,reg,flt,dir,txt,kinds,summary,has_pos,"
            "lat,lon,alt,dec) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            self.adscs)


def ingest_file(con, path, agg, verbose):
    size = os.path.getsize(path)
    row = con.execute(
        "SELECT offset,size FROM ingest_state WHERE file=?", (path,)
    ).fetchone()
    offset = row[0] if row else 0
    if row and size < row[1]:
        # File shrank/was replaced (shouldn't happen with append-only, but
        # be safe): re-read from the top.
        offset = 0
    if offset >= size:
        return 0

    with open(path, "rb") as f:
        f.seek(offset)
        buf = f.read()

    *complete, tail = buf.split(b"\n")
    consumed = len(buf) - len(tail)
    n = 0
    for raw in complete:
        if not raw.strip():
            continue
        try:
            agg.event(json.loads(raw))
            n += 1
        except (ValueError, KeyError):
            agg.bad += 1
    agg.lines += n

    new_offset = offset + consumed
    con.execute(
        "INSERT INTO ingest_state(file,offset,size,updated) VALUES(?,?,?,?) "
        "ON CONFLICT(file) DO UPDATE SET offset=excluded.offset, "
        "size=excluded.size, updated=excluded.updated",
        (path, new_offset, size, int(time.time())),
    )
    if verbose:
        print(f"  {os.path.basename(path)}: +{n} events "
              f"({offset}->{new_offset} of {size} bytes)")
    return n


def main():
    ap = argparse.ArgumentParser(description="VDL2 Observatory rollup")
    ap.add_argument("--archive", default="archive",
                    help="directory of vdl2-YYYYMMDD.jsonl files")
    ap.add_argument("--db", default="observatory/observatory.db",
                    help="SQLite database to write")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.archive, "vdl2-*.jsonl")))
    if not files:
        print(f"rollup: no archive files in {args.archive}", file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
    con = sqlite3.connect(args.db)
    init_db(con)

    agg = Agg()
    agg.load_state(con)
    total = 0
    for path in files:
        total += ingest_file(con, path, agg, args.verbose)
    agg.flush(con)
    con.execute(
        "INSERT INTO meta(key,value) VALUES('last_run',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(int(time.time())),),
    )
    con.commit()
    con.close()

    print(f"rollup: {total} new events from {len(files)} file(s)"
          + (f", {agg.bad} malformed" if agg.bad else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
