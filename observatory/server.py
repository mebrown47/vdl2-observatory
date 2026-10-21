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
  GET /healthz       -> ok

Usage:
    server.py [--db PATH] [--port 8891] [--host 0.0.0.0]

It never talks to vdl2-sniffer; run rollup.py on a timer to keep it current.
"""

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import messages_view  # noqa: E402
import vdl2_view  # noqa: E402

DB_PATH = "observatory/observatory.db"
# iridium-sniffer's Observatory uses 8890, so both can run on one machine.
PORT = 8891


class Handler(BaseHTTPRequestHandler):
    db_path = DB_PATH
    server_version = "vdl2-observatory"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, build, *a):
        try:
            self._send(200, json.dumps(build(*a)), "application/json")
        except Exception as e:  # noqa: keep the server alive
            self._send(500, json.dumps({"error": str(e)}), "application/json")

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            self._send(200, vdl2_view.VDL2_PAGE, "text/html; charset=utf-8")
        elif u.path == "/api/vdl2":
            self._json(vdl2_view.build_vdl2, self.db_path,
                       q.get("hours", [None])[0])
        elif u.path == "/messages":
            self._send(200, messages_view.MESSAGES_PAGE,
                       "text/html; charset=utf-8")
        elif u.path == "/api/messages":
            tail = q.get("tail", [None])[0] or None
            try:
                limit = max(1, min(1000, int(q.get("limit", ["200"])[0])))
            except ValueError:
                limit = 200
            self._json(messages_view.build_messages, self.db_path, tail, limit)
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
    args = ap.parse_args()

    Handler.db_path = args.db
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"vdl2 observatory: http://{args.host}:{args.port}/  db={args.db}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
