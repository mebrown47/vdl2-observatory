#!/usr/bin/env python3
# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""
VDL2 Observatory: the dashboard server

A small read-only HTTP server over the database rollup.py builds from
vdl2-sniffer's archive. Stdlib only, no external assets, so it runs on a
headless receiver with no internet. Adapted from iridium-sniffer's
observatory/trends_server.py.

  GET /              -> Overview: channels, stations, handoffs, positions
  GET /api/vdl2      -> its data (optional ?hours=N window)
  GET /messages      -> per-tail history, CPDLC and ADS-C
  GET /api/messages  -> its data (optional ?tail=REG&limit=N)
  GET /map.json      -> the map's background lines (data/outlines.json)
  GET /healthz       -> ok

Usage:
    server.py [--db PATH] [--port 8891] [--host 0.0.0.0]

It never talks to vdl2-sniffer; run rollup.py on a timer to keep it current.
"""

import argparse
import hashlib
import sqlite3
import threading
import time
import html as htmllib
import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context  # noqa: E402
import coverage  # noqa: E402
import coverage_view  # noqa: E402
import flights  # noqa: E402
import flights_view  # noqa: E402
import graph  # noqa: E402
import graph_view  # noqa: E402
import messages_view  # noqa: E402
import search  # noqa: E402
import search_view  # noqa: E402
import vdl2_view  # noqa: E402

DB_PATH = "observatory/observatory.db"
OUTLINES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "outlines.json")
# iridium-sniffer's Observatory uses 8890, so both can run on one machine.
PORT = 8891
# vdl2-sniffer's live page (--web), which the pages link to on the same host.
LIVE_PORT = 8889


def map_version():
    """The map file's fingerprint, for the page's request for it (/map.json?v=...):
    a browser holding an older copy fetches the new one. Read again when the file
    changes, so an update needs no restart."""
    try:
        st = os.stat(OUTLINES)
    except OSError:
        return "none"
    key = (st.st_mtime_ns, st.st_size)
    if _map_v.get("key") != key:
        with open(OUTLINES, "rb") as f:
            _map_v.update(key=key, v=hashlib.md5(f.read()).hexdigest()[:10])
    return _map_v["v"]


_map_v = {}


def running_version():
    """The version of the code this server runs: the VERSION file install.sh
    writes beside observatory/, else `git describe` of the checkout it runs
    from (as the receiver reports it), else "unknown"."""
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(here, "..", "VERSION")) as f:
            v = f.read().strip()
        if v:
            return v
    except OSError:
        pass
    try:
        v = subprocess.run(["git", "-C", here, "describe", "--tags", "--always", "--dirty"],
                           capture_output=True, text=True, timeout=5).stdout.strip()
        if v:
            return v
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


VERSION = running_version()   # read once: the version of the code now running
FOOTER = ('<footer style="color:var(--dim,#8b98a5);font-size:11.5px;text-align:center;'
          'margin:18px 0 22px"><a href="https://github.com/mebrown47/vdl2-observatory/releases" '
          'target="_blank" rel="noopener" style="color:inherit;text-decoration:none">'
          'vdl2-observatory ' + htmllib.escape(VERSION) + '</a></footer>\n')


_flights_lock = threading.Lock()
_flights_ref = None
_stations = {"t": 0, "v": []}


def _shared(db_path, placed_only=True):
    """The reference data (airports, fixes), read on first use, and the
    station estimates (all time, every position), every 5 minutes; for the
    Flights and Graph pages."""
    global _flights_ref
    with _flights_lock:
        if _flights_ref is None:
            here = os.path.dirname(os.path.abspath(__file__))
            wp = next((p for p in (os.path.join(here, "..", "data", "waypoints.csv"),
                                   os.path.join(here, "..", "share", "vdl2-sniffer", "waypoints.csv"))
                       if os.path.exists(p)), "")
            _flights_ref = context.Reference(waypoints=wp, aircraft_csv="")
        if time.time() - _stations["t"] > 300:
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            try:
                _stations["centre"] = vdl2_view.receiver_centre(con, station())
                _stations["v"] = vdl2_view.estimate_stations(con, _stations["centre"])
            finally:
                con.close()
            _stations["t"] = time.time()
        ref, st = _flights_ref, _stations["v"]
    return ref, ([x for x in st if x.get("lat") is not None] if placed_only else st)


def flights_api(db_path, hours):
    try:
        hours = max(1, min(48, int(hours)))
    except (TypeError, ValueError):
        hours = 6
    if not os.path.exists(db_path):
        return {"error": "no database yet — run rollup.py first"}
    ref, st = _shared(db_path)
    return flights.build_flights(db_path, ref, hours=hours, stations=st, centre=_stations.get("centre"))


def graph_api(db_path, q):
    """/api/graph (the network), ?aircraft=Q (one aircraft), ?list=1 (suggestions)."""
    if not os.path.exists(db_path):
        return {"error": "no database yet — run rollup.py first"}
    ref, st = _shared(db_path, placed_only=False)
    if q.get("aircraft"):
        return graph.build_aircraft(db_path, ref, q["aircraft"][0])
    if q.get("list"):
        return {"aircraft": graph.aircraft_list(db_path)}
    try:
        hours = int(q.get("hours", ["168"])[0])
        hours = 0 if hours <= 0 else min(hours, 24 * 3660)      # 0: all
    except ValueError:
        hours = 168
    return graph.build_network(db_path, st, hours=hours)


# The receiver's location, for the Coverage page: the settings' STATION
# (--station LAT,LON[,ANTENNA_M]) first, else iridium-observatory's fix on this
# machine (its /api/sky station, from ring alerts), asked every 10 minutes.
STATION = None
IRIDIUM_PORT = 8890
_iridium = {"t": 0, "v": None}


def parse_station(text):
    """{"lat", "lon", "alt_m", "source"} from "LAT,LON[,ANTENNA_M]", or None."""
    try:
        p = [float(x) for x in (text or "").replace(" ", "").split(",") if x != ""]
    except ValueError:
        return None
    if len(p) not in (2, 3) or not (-90 <= p[0] <= 90 and -180 <= p[1] <= 180):
        return None
    return {"lat": p[0], "lon": p[1], "alt_m": p[2] if len(p) == 3 else 0.0, "source": "from the settings"}


def station():
    if STATION:
        return STATION
    if not IRIDIUM_PORT:
        return None
    if time.time() - _iridium["t"] > 600:
        _iridium["t"] = time.time()
        try:
            with urlopen(f"http://127.0.0.1:{IRIDIUM_PORT}/api/sky", timeout=3) as r:
                st = json.load(r).get("station") or {}
            _iridium["v"] = ({"lat": float(st["lat"]), "lon": float(st["lon"]), "alt_m": 0.0,
                              "source": "from iridium-observatory on this machine ("
                                        + str(st.get("source") or "its fix") + ")"}
                             if st.get("lat") is not None else None)
        except (OSError, ValueError, KeyError, TypeError):
            _iridium["v"] = None
    return _iridium["v"]


def coverage_api(db_path, hours):
    try:
        hours = max(1, min(24 * 90, int(hours)))
    except (TypeError, ValueError):
        hours = 168
    if not os.path.exists(db_path):
        return {"error": "no database yet — run rollup.py first"}
    return coverage.build_coverage(db_path, station(), hours=hours)


class Handler(BaseHTTPRequestHandler):
    db_path = DB_PATH
    live_port = LIVE_PORT
    server_version = "vdl2-observatory"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype, cache="no-store"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _page(self, html):
        html = html.replace("__LIVE_PORT__", str(self.live_port)).replace("__MAP_V__", map_version())
        head, sep, tail = html.rpartition("</body>")
        return head + FOOTER + sep + tail if sep else html

    def _json(self, build, *a):
        try:
            self._send(200, json.dumps(build(*a)), "application/json")
        except Exception as e:  # noqa: keep the server alive
            self._send(500, json.dumps({"error": str(e)}), "application/json")

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            self._send(200, self._page(vdl2_view.VDL2_PAGE), "text/html; charset=utf-8")
        elif u.path == "/api/vdl2":
            self._json(vdl2_view.build_vdl2, self.db_path,
                       q.get("hours", [None])[0], station())
        elif u.path == "/messages":
            self._send(200, self._page(messages_view.MESSAGES_PAGE),
                       "text/html; charset=utf-8")
        elif u.path == "/api/messages":
            tail = q.get("tail", [None])[0] or None
            try:
                limit = max(1, min(1000, int(q.get("limit", ["200"])[0])))
            except ValueError:
                limit = 200
            self._json(messages_view.build_messages, self.db_path, tail, limit)
        elif u.path == "/flights":
            self._send(200, self._page(flights_view.FLIGHTS_PAGE), "text/html; charset=utf-8")
        elif u.path == "/api/flights":
            self._json(flights_api, self.db_path, q.get("hours", ["6"])[0])
        elif u.path == "/search":
            self._send(200, self._page(search_view.SEARCH_PAGE), "text/html; charset=utf-8")
        elif u.path == "/api/search":
            self._json(search.build_search, self.db_path, q)
        elif u.path == "/api/search.csv":
            try:
                body = search.search_csv(self.db_path, q)
            except Exception as e:  # noqa: keep the server alive
                self._send(500, "error\n%s\n" % e, "text/csv; charset=utf-8")
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="vdl2-messages-%s.csv"'
                                 % time.strftime("%Y%m%d-%H%M%S", time.gmtime()))
                b = body.encode("utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(b)
        elif u.path == "/graph":
            self._send(200, self._page(graph_view.GRAPH_PAGE), "text/html; charset=utf-8")
        elif u.path == "/api/graph":
            self._json(graph_api, self.db_path, q)
        elif u.path == "/coverage":
            self._send(200, self._page(coverage_view.COVERAGE_PAGE), "text/html; charset=utf-8")
        elif u.path == "/api/coverage":
            self._json(coverage_api, self.db_path, q.get("hours", ["168"])[0])
        elif u.path == "/map.json":
            try:
                with open(OUTLINES, "rb") as f:
                    body = f.read()
            except OSError:
                self._send(404, "no outlines: " + OUTLINES, "text/plain")
                return
            # Changes only with the repo: let the browser keep it for a day.
            self._send(200, body, "application/json", "public, max-age=86400")
        elif u.path == "/healthz":
            self._send(200, "ok", "text/plain")
        else:
            self._send(404, "not found", "text/plain")

    do_HEAD = do_GET


def main():
    global STATION, IRIDIUM_PORT
    ap = argparse.ArgumentParser(description="VDL2 Observatory server")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--live-port", type=int, default=LIVE_PORT,
                    help="vdl2-sniffer's live page on this host, for the link to it (0 = no link)")
    ap.add_argument("--station", default="",
                    help="the receiver's location for the Coverage page: LAT,LON[,ANTENNA_M] "
                         "(antenna height above sea level, metres); empty = ask iridium-observatory")
    ap.add_argument("--iridium-port", type=int, default=IRIDIUM_PORT,
                    help="iridium-observatory on this host, for its location when --station is "
                         "empty (0 = don't ask)")
    args = ap.parse_args()
    STATION = parse_station(args.station)
    if args.station and not STATION:
        print(f"vdl2 observatory: ignoring --station {args.station!r}: expected LAT,LON[,ANTENNA_M]",
              file=sys.stderr)
    IRIDIUM_PORT = args.iridium_port

    Handler.db_path = args.db
    Handler.live_port = args.live_port
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"vdl2 observatory: http://{args.host}:{args.port}/  db={args.db}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
