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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context  # noqa: E402
import flights  # noqa: E402
import flights_view  # noqa: E402
import messages_view  # noqa: E402
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


def flights_api(db_path, hours):
    """/api/flights: the reference data (airports, fixes) is read on first
    use; the station estimates (all time, every position) every 5 minutes."""
    global _flights_ref
    try:
        hours = max(1, min(48, int(hours)))
    except (TypeError, ValueError):
        hours = 6
    if not os.path.exists(db_path):
        return {"error": "no database yet — run rollup.py first"}
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
                _stations["v"] = [x for x in vdl2_view.estimate_stations(con) if x.get("lat") is not None]
            finally:
                con.close()
            _stations["t"] = time.time()
        ref, st = _flights_ref, _stations["v"]
    return flights.build_flights(db_path, ref, hours=hours, stations=st)


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
                       q.get("hours", [None])[0])
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
    ap = argparse.ArgumentParser(description="VDL2 Observatory server")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--live-port", type=int, default=LIVE_PORT,
                    help="vdl2-sniffer's live page on this host, for the link to it (0 = no link)")
    args = ap.parse_args()

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
