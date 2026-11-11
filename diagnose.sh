#!/usr/bin/env bash
# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# diagnose.sh — gather what's needed to troubleshoot a vdl2-observatory
# install into one text file: OS and tool versions, which libraries the
# receiver really loads, RTL-SDR permissions and udev rules, service state,
# ports, the live page's and the Observatory's answers, data folders, and
# recent logs.
#
# Usage (from the repo checkout, as your normal user; changes nothing):
#     ./diagnose.sh                write diagnose-<host>-<UTC time>.txt here
#     ./diagnose.sh -o FILE        write FILE instead
#
# The report includes your settings file (feed addresses, station ID) and
# the ground stations your receiver hears, which say roughly where it is;
# its logs can hold the addresses of people who opened your pages.
# Look it over before posting it publicly.
#
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX=/opt/vdl2-observatory
CONF=/etc/vdl2-observatory.conf
DATA_DIR=/var/lib/vdl2-observatory
OUT=""

while [ $# -gt 0 ]; do
  case "$1" in
    -o) OUT="${2:?-o needs a file name}"; shift;;
    -h|--help) sed -n '5,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 1;;
  esac
  shift
done
[ -n "$OUT" ] || OUT="$PWD/diagnose-$(hostname -s)-$(date -u +%Y%m%d-%H%M%S).txt"
: > "$OUT" || { echo "cannot write $OUT" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }
section() { printf '\n\n======== %s ========\n' "$1" >> "$OUT"; printf '  %s\n' "$1"; }
# Run a command into the report under a "$ cmd" line; never stop on failure.
run() {
  printf '\n$ %s\n' "$*" >> "$OUT"
  timeout 30 bash -c "$*" >> "$OUT" 2>&1
  local rc=$?
  [ $rc -eq 0 ] || printf '[exit %d]\n' "$rc" >> "$OUT"
}
note() { printf '%s\n' "$*" >> "$OUT"; }

# The args of a systemd unit's ExecStart, one per line (first = the program).
unit_argv() {
  systemctl show -p ExecStart "$1" 2>/dev/null \
    | sed -n 's/.*argv\[\]=\([^;]*\);.*/\1/p' | tr ' ' '\n' | sed '/^$/d'
}
# A KEY="value" from the settings file, read rather than sourced.
conf_get() { sed -n "s/^[[:space:]]*$1=//p" "$CONF" 2>/dev/null | tail -1 | sed -E 's/^"(.*)"$/\1/'; }

# Where things really are: the running unit's program, else the installer's.
# A receiver set up by hand from systemd/ runs as a user unit instead.
SCOPE=""
systemctl cat vdl2-sniffer.service >/dev/null 2>&1 || {
  systemctl --user cat vdl2-sniffer.service >/dev/null 2>&1 && SCOPE="--user"; }
SNIFFER_BIN="$(systemctl $SCOPE show -p ExecStart vdl2-sniffer.service 2>/dev/null \
  | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -1)"
[ -n "$SNIFFER_BIN" ] || SNIFFER_BIN="$PREFIX/bin/vdl2-sniffer"
WEB_PORT="$(conf_get WEB_PORT)"; [[ "$WEB_PORT" =~ ^[0-9]+$ ]] || WEB_PORT=8889
OBS_PORT="$(conf_get OBS_PORT)"; [[ "$OBS_PORT" =~ ^[0-9]+$ ]] || OBS_PORT=8891
JOURNAL="journalctl"; [ -n "$SCOPE" ] && JOURNAL="journalctl --user"

echo "Writing $OUT"
{
  echo "vdl2-observatory diagnostics"
  echo "generated $(date -u '+%Y-%m-%d %H:%M:%S UTC') by $(id -un) on $(hostname)"
  echo "receiver binary: $SNIFFER_BIN   live page :$WEB_PORT   observatory :$OBS_PORT   ${SCOPE:+(user units)}"
} >> "$OUT"

section "System"
run "cat /etc/os-release"
run "uname -a"
run "id"
run "nproc; free -h; df -h / ${DATA_DIR} 2>/dev/null; true"
run "for t in gcc g++ cmake python3 git curl; do printf '%-8s ' \$t; \$t --version 2>&1 | head -1; done"
run "timedatectl 2>/dev/null | grep -Ei 'synchron|NTP|time zone' || true"

section "Install"
run "cat $PREFIX/VERSION 2>/dev/null || echo 'no $PREFIX/VERSION (not installed by install.sh?)'"
run "git -C '$REPO_ROOT' describe --always --dirty --tags; git -C '$REPO_ROOT' log --oneline -3; git -C '$REPO_ROOT' status --short | head -20"
run "cat $CONF 2>/dev/null || echo 'no $CONF'"
run "ls -la $PREFIX $PREFIX/bin $PREFIX/observatory 2>/dev/null | head -40"
if [ -f "$REPO_ROOT/build-install.log" ]; then
  run "grep -Ei 'rtlsdr|libacars|not found|NOTFOUND|Found ' '$REPO_ROOT/build-install.log' | head -20"
fi
[ -f "$REPO_ROOT/build-install/tests.log" ] && run "tail -5 '$REPO_ROOT/build-install/tests.log'"

section "Libraries"
note "Which copy of each library the receiver loads; a second copy elsewhere"
note "(e.g. /usr/local from source vs /usr/lib from apt) is a common conflict."
run "ldd '$SNIFFER_BIN' 2>&1 | grep -Ei 'rtlsdr|acars|usb|not found'"
run "for l in librtlsdr libacars-2 libusb-1.0; do ls -la /usr/lib/x86_64-linux-gnu/\$l.so* /usr/lib/aarch64-linux-gnu/\$l.so* /usr/lib/arm-linux-gnueabihf/\$l.so* /usr/lib/\$l.so* /usr/local/lib/\$l.so* /usr/local/lib64/\$l.so* 2>/dev/null; done; true"
run "for m in librtlsdr libacars-2 libusb-1.0; do printf '%-12s ' \$m; pkg-config --modversion \$m 2>&1; done"
run "dpkg -l 2>/dev/null | grep -Ei 'rtl-?sdr|acars' | awk '{print \$1, \$2, \$3}'"

section "RTL-SDR and permissions"
note "The service runs as its user with group plugdev: each dongle's node must"
note "be group plugdev and group-writable (or world-writable). The DVB-T kernel"
note "driver is detached by librtlsdr when the receiver opens the dongle."
{
  printf '\n$ (RTL-SDR device nodes)\n'
  found=0
  for d in /sys/bus/usb/devices/*; do
    [ -r "$d/idVendor" ] || continue
    id="$(<"$d/idVendor"):$(<"$d/idProduct")"
    case "$id" in 0bda:2832|0bda:2838) ;; *) continue;; esac
    found=1
    node="$(printf '/dev/bus/usb/%03d/%03d' "$(<"$d/busnum")" "$(<"$d/devnum")")"
    g="$(stat -c %G "$node" 2>/dev/null)"; m="$(stat -c %a "$node" 2>/dev/null)"
    if { [ "$g" = plugdev ] && (( 8#${m:-0} & 8#020 )); } || (( 8#${m:-0} & 8#002 )); then v=OK; else v="PROBLEM: the service can't open it"; fi
    printf '%s  %s  group %s mode %s  %s  [%s, serial %s]\n' "$id" "$node" "$g" "$m" "$v" \
      "$(cat "$d/product" 2>/dev/null)" "$(cat "$d/serial" 2>/dev/null || echo -)"
  done
  [ $found = 1 ] || echo "no RTL-SDR on USB"
} >> "$OUT" 2>&1
RULE_DIRS="$(for r in /etc/udev/rules.d /usr/lib/udev/rules.d /lib/udev/rules.d; do [ -d "$r" ] && readlink -f "$r"; done | awk '!seen[$0]++' | tr '\n' ' ')"
run "for r in $RULE_DIRS; do grep -sHn -Ei '0bda.*283[28]|283[28].*0bda|rtl' \$r/*.rules; done | head -20"
run "lsmod | grep -E '^(dvb_usb_rtl28xxu|rtl2832|rtl2830)' || echo 'no DVB-T driver loaded'"
run "getent group plugdev; svc_user=\$(systemctl show -p User --value vdl2-sniffer 2>/dev/null); [ -n \"\$svc_user\" ] && echo \"service user: \$svc_user (\$(id -nG \$svc_user 2>/dev/null))\"; true"
run "pgrep -a -f 'rtl_tcp|rtl_sdr|rtl_fm|dumpvdl2|acarsdec|dump1090|readsb' || echo 'no other dongle programs running'"

section "Services"
for u in vdl2-sniffer.service vdl2-observatory.service vdl2-rollup.service vdl2-rollup.timer; do
  run "systemctl $SCOPE status $u --no-pager -n 0 2>&1 | head -12"
done
run "systemctl $SCOPE show vdl2-sniffer -p NRestarts -p ActiveEnterTimestamp -p ExecMainStatus -p User -p SupplementaryGroups -p WorkingDirectory"
run "systemctl $SCOPE cat vdl2-sniffer.service 2>&1 | grep -vE '^\s*#|^\s*$'"
run "systemctl $SCOPE cat vdl2-observatory.service 2>&1 | grep -E 'ExecStart|User'"
run "systemctl $SCOPE list-timers --all --no-pager 2>/dev/null | grep -Ei 'vdl2|NEXT'"
if [ -z "$SCOPE" ] && systemctl --user cat vdl2-sniffer.service >/dev/null 2>&1; then
  note ""
  note "NOTE: a user unit vdl2-sniffer.service exists too (a receiver set up by hand);"
  note "both can't hold the dongle. Re-running ./install.sh takes it over."
fi

section "Ports"
run "ss -ltnp 2>/dev/null | grep -E ':(${WEB_PORT}|${OBS_PORT})\b' || echo 'nothing listening on :${WEB_PORT} or :${OBS_PORT}'"

section "Live endpoints"
# Fetch a JSON endpoint and summarise it with a little Python; say so plainly
# when it can't be reached instead of dumping a traceback.
endpoint() {
  local url="$1" py="$2" body
  printf '\n$ curl %s\n' "$url" >> "$OUT"
  if ! body="$(curl -fsS -m 20 "$url" 2>&1)"; then
    printf 'not reachable: %s\n' "$body" >> "$OUT"; return
  fi
  printf '%s' "$body" | python3 -c "$py" >> "$OUT" 2>&1 || printf '[could not parse the reply]\n' >> "$OUT"
}
if have curl && have python3; then
  run "curl -fsS -m 10 http://127.0.0.1:${WEB_PORT}/healthz"
  run "curl -fsS -m 10 http://127.0.0.1:${OBS_PORT}/healthz"
  endpoint "http://127.0.0.1:${WEB_PORT}/api/state" '
import sys, json, time
d = json.load(sys.stdin)
print("up for %.0f s; newest frame %s" % (d["now"] - d["started"],
      "%.0f s ago" % (d["now"] - d["latest"]) if d.get("latest") else "none yet"))
print("totals:", d.get("totals"))
for c in d.get("channels", []): print("  %.3f MHz  bursts %-8s frames %s" % (c["freq"] / 1e6, c["bursts"], c["frames"]))
r = d.get("receiver", {})
print("receiver:", {k: r.get(k) for k in ("device", "tuner", "gain", "ppm", "bias_tee", "centre", "rate", "samples", "dropped")})
print("frequency error:", r.get("skew"), " suggested --ppm:", r.get("suggested_ppm", "not yet (needs 10 aircraft)"))
print("aircraft:", len(d.get("aircraft", [])), " stations:", len(d.get("stations", [])),
      " messages:", len(d.get("messages", [])), " handoffs:", len(d.get("handoffs", [])))'
  endpoint "http://127.0.0.1:${OBS_PORT}/api/vdl2" '
import sys, json
d = json.load(sys.stdin)
print("span:", d.get("span"))
print("totals:", d.get("totals"))
print("hours:", len(d.get("hours", [])), " stations:", len(d.get("stations", [])), " aircraft:", len(d.get("aircraft", [])))'
else
  note "curl or python3 missing: endpoints not checked"
fi

section "Data"
ARCHIVE="$(unit_argv vdl2-sniffer.service | grep -A1 -x -- --archive | tail -1)"
for dir in "$DATA_DIR" "$DATA_DIR/archive" "$ARCHIVE"; do
  [ -n "$dir" ] && [ -d "$dir" ] && run "ls -la '$dir' | tail -12"
done
run "tail -n 3 \$(ls -1 '${ARCHIVE:-$DATA_DIR/archive}'/vdl2-*.jsonl 2>/dev/null | tail -1) 2>/dev/null | cut -c1-300 || echo 'no archive file'"

section "Logs"
note "If these are empty, add your user to the adm or systemd-journal group,"
note "or run: sudo journalctl -u vdl2-sniffer -n 120"
run "$JOURNAL -u vdl2-sniffer -n 120 --no-pager 2>&1"
run "$JOURNAL -u vdl2-observatory -n 40 --no-pager 2>&1"
run "$JOURNAL -u vdl2-rollup -n 20 --no-pager 2>&1"
run "dmesg 2>/dev/null | grep -Ei 'usb.*(0bda|rtl|2838|2832)|usb.*(error|disconnect|reset)' | tail -20 || echo 'dmesg not readable as this user'"

echo
echo "Done: $OUT ($(wc -l < "$OUT") lines)"
echo "It contains your settings and the stations you hear; look it over before posting publicly."
