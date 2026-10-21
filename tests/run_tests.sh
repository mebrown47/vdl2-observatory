#!/usr/bin/env bash
# Unit tests that need no captures: positions from ACARS text.
# The recorded A/B against dumpvdl2 is tests/ab_run.sh.
#
#   tests/run_tests.sh [BUILD_DIR]     (default: build)
#
# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later

HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD="${1:-$HERE/../build}"
pass=0 fail=0

# HASTE and GOODY are good fixes, BADFX a packed-DDMMSS row of the kind
# older lists carried.
fixes="$(mktemp)"
trap 'rm -f "$fixes"' EXIT
printf 'HASTE,46.000000,-101.000000\nGOODY,10.000000,10.000000\nBADFX,242917,541148\n' > "$fixes"

echo "== ACARS text positions =="
while read -r line; do
    echo "  $line"
    case "$line" in
        PASS*) pass=$((pass + 1)) ;;
        FAIL*) fail=$((fail + 1)) ;;
    esac
done < <("$BUILD/test-acars-position" "$fixes" 2>/dev/null)

echo "RESULT: $pass passed, $fail failed"
[ "$fail" -eq 0 ] && [ "$pass" -gt 0 ]
