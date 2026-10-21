#!/usr/bin/env python3
# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""Conjugate a cu8 IQ file to stdout: Q -> 255 - Q, I unchanged."""

import sys

CHUNK = 1 << 22   # even, so I/Q pairs never split

with open(sys.argv[1], "rb") as f:
    out = sys.stdout.buffer
    table = bytes(255 - i for i in range(256))
    while True:
        b = bytearray(f.read(CHUNK))
        if not b:
            break
        b[1::2] = b[1::2].translate(table)
        out.write(b)
