#!/bin/bash
# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Recorded A/B, XID check and null test: run vdl2-sniffer over every VDL2
# capture that has dumpvdl2 output beside it, compare, check every XID frame
# dumpvdl2 decoded against our parse, then run the busiest captures
# again with the IQ conjugated (energy and timing kept, every phase change
# reversed, so no real unique word survives) and require zero frames.
#
#   ab_run.sh CAPTURE_DIR ORACLE_DIR [OUT_DIR]
#
# Captures are vdl2-NAME.cu8; each one's dumpvdl2 text output is
# ORACLE_DIR/vdl2-NAME-oracle.txt (Chalmette's is vdl2-oracle.txt).
# VDL2_CAPTURES and VDL2_ORACLES stand in for the first two arguments.

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
BIN="${VDL2_SNIFFER:-$HERE/../build/vdl2-sniffer}"
CAPS="${1:-${VDL2_CAPTURES:-}}"
ORACLES="${2:-${VDL2_ORACLES:-}}"
if [ -z "$CAPS" ] || [ -z "$ORACLES" ]; then
    echo "usage: $0 CAPTURE_DIR ORACLE_DIR [OUT_DIR]" >&2
    exit 2
fi
OUT="${3:-$(mktemp -d)}"
mkdir -p "$OUT"
echo "output in $OUT"

fail=0
for cap in "$CAPS"/vdl2-*.cu8; do
    name="$(basename "$cap" .cu8)"
    oracle="$ORACLES/$name-oracle.txt"
    [ "$name" = vdl2-chalmette ] && oracle="$ORACLES/vdl2-oracle.txt"
    [ -f "$oracle" ] || { echo "$name: no dumpvdl2 output, skipped"; continue; }
    "$BIN" -r "$cap" --json "$OUT/$name.json" --raw -q 2> "$OUT/$name.err" > /dev/null
    python3 "$HERE/ab_compare.py" "$OUT/$name.json" "$oracle" --name "$name" || fail=1
done

echo "XID parse against dumpvdl2:"
python3 "$HERE/xid_check.py" "$(dirname "$BIN")/vdl2-xid-test" "$ORACLES"/*oracle.txt || fail=1

echo "null test (conjugated IQ):"
for name in vdl2-chalmette vdl2-mandan-ab-loop vdl2-mandan-loop; do
    cap="$CAPS/$name.cu8"
    [ -f "$cap" ] || continue
    python3 "$HERE/conj_cu8.py" "$cap" | "$BIN" -r - --format cu8 --json "$OUT/$name-conj.json" -q 2> "$OUT/$name-conj.err" > /dev/null
    n=$(grep -c . "$OUT/$name-conj.json")
    bursts=$(grep -o 'from [0-9]* bursts' "$OUT/$name-conj.err")
    echo "  $name: $n frames $bursts"
    [ "$n" -eq 0 ] || fail=1
done
exit $fail
