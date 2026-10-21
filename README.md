# vdl2-sniffer

A VDL Mode 2 receiver with its own dashboard. It decodes every VDL2 channel in one tuning: the
eight US channels between 136.650 and 136.975 MHz fit in 1.05 MHz. Output goes three ways:
- dumpvdl2-style JSON for feeds such as acarshub and airframes
- a line per frame in the terminal
- a JSONL archive, which the VDL2 Observatory dashboard reads

The receiver is Mike Brown's clean-room VDL2 decoder (`third_party/vdl2`, MIT), built to be
upstreamed to CyberEther. It was written from ETSI EN 301 841-1 and measurements on the air, with dumpvdl2 used only as a black-box oracle.
On ten recorded captures it decoded 357 frames to dumpvdl2's 250, and every frame dumpvdl2 decoded
was among them.

vdl2-sniffer began as part of [iridium-observatory](https://github.com/mebrown47/iridium-observatory)
and now stands alone; it needs no Iridium hardware or software.

## Build

```bash
sudo apt install build-essential cmake pkg-config
cmake -B build
cmake --build build -j
sudo cmake --install build      # optional: /usr/local/bin and the fix list
```

libacars-2 is optional. With it, multi-block ACARS messages are reassembled and FANS-1/A (CPDLC,
ADS-C) and MIAM are decoded. Without it, the engine still decodes and logs every ACARS block.

## Run

The receiver wants 1.05 MS/s, centred so that every channel is a multiple of 12.5 kHz from the
centre. With an RTL-SDR (built with librtlsdr) vdl2-sniffer tunes and reads the device itself;
other receivers come through a receiver program on stdin, tuned to `--print-centre`:

```bash
# RTL-SDR, US channel plan, tuner AGC
vdl2-sniffer --rtlsdr --archive ~/vdl2-archive --udp 127.0.0.1:5555 --station-id XX-VDL2

# The same through rtl_sdr
rtl_sdr -f $(vdl2-sniffer --print-centre) -s 1050000 -g 40 - \
  | vdl2-sniffer --archive ~/vdl2-archive --udp 127.0.0.1:5555 --station-id XX-VDL2

# A recording
vdl2-sniffer -r capture.cu8 --start "2026-09-25 18:04:06" --json frames.json
```

Other rates and centres are mixed and resampled, so 2.5 MS/s from an Airspy R2 also works:
`airspy_rx -f 136.8125 -a 2500000 -t 2 -r - | vdl2-sniffer -s 2500000 -c 136812500 --format ci16`.

| Option | |
| --- | --- |
| `--rtlsdr [DEV]` | read an RTL-SDR directly: index or serial (default 0); `--gain DB` (default auto), `--ppm N`, `--bias-tee`. If the decoder falls behind, whole buffers are dropped and reported once a minute, and frame times stay true. If the device goes away, vdl2-sniffer exits with status 1 for a service manager to restart it |
| `-r FILE` / `-` | IQ file or stdin; `--format cu8\|cs8\|ci16\|cf32` (from the extension by default, cu8 on stdin) |
| `-s HZ`, `-c HZ` | input rate (default 1050000) and centre (default: the plan's centre) |
| `--plan us\|eu`, `--channels LIST` | channel plan, or channels in MHz or Hz |
| `--start TIME` | capture start for a file: epoch, `YYYY-MM-DD HH:MM:SS` local, or `...Z` UTC. Default: the file's mtime minus its length |
| `--json [FILE]` | one dumpvdl2-style JSON object per frame (stdout by default); `--raw` adds the AVLC octets. XID frames use dumpvdl2's layout (`pub_params`, `vdl_params`), which feed parsers such as acars_router require; on the ten captures every frame passes acars_vdlm2_parser |
| `--udp HOST:PORT` | the same JSON over UDP (acarshub, airframes) |
| `--archive [DIR]` | `vdl2-YYYYMMDD.jsonl` for the Observatory (default `./archive`) |
| `--waypoints FILE` | fix list for positions from ACARS text (default: the installed `waypoints.csv`; `none` turns the fallback off) |
| `-q` | no line per frame |

Without `--json` on stdout, it prints a line per frame:

```
02:09:34 136.800 +26.8 dB A3578A -> 228E05(GS) ACARS N314VB AA1292 H1 TRP KMIA KDEN ...
```

That is the time, the channel, the signal level, the sender and receiver (`GS` marks a ground
station), and the frame: ACARS with tail, flight, label and text, an XID, or a control frame such as
`RR`. At exit it prints bursts, frames and ACARS blocks per channel to stderr.

## The Observatory

`observatory/` is a dashboard over the archive: Python 3 standard library only, no external
assets, so it runs on a headless receiver with no internet.

```bash
python3 observatory/rollup.py --archive ~/vdl2-archive --db observatory/observatory.db
python3 observatory/server.py --db observatory/observatory.db      # http://HOST:8891/
```

- **Overview** (`/`): the following panels.
  - frames per hour by channel
  - per-channel decoder health (frames per burst, SNR percentiles)
  - messages per hour
  - ground stations, with a map of their estimated positions
  - handoffs between stations, and aircraft positions
  - the busiest aircraft
- **Messages** (`/messages`): each aircraft's messages, the CPDLC log and ADS-C.

`rollup.py` reads only what was appended since its last run, so run it every few minutes from a
timer or cron. The server reads the database only and never talks to vdl2-sniffer. Port 8891 is
chosen so that it can sit beside iridium-observatory's dashboard on 8890.

## Running as a service

`systemd/` has user units for a receiver that runs on its own: `vdl2-sniffer.service` (the RTL-SDR,
restarted if it stops), `vdl2-rollup.timer` (the rollup every minute) and `vdl2-observatory.service`
(the dashboard on 8891). They expect the checkout at `~/vdl2-sniffer` and need no root:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/*.service systemd/*.timer ~/.config/systemd/user/
cp systemd/vdl2-sniffer.env.example ~/.config/vdl2-sniffer.env   # feeds, station id, gain
systemctl --user daemon-reload
systemctl --user enable --now vdl2-sniffer.service vdl2-rollup.timer vdl2-observatory.service
loginctl enable-linger      # keep them running after logout and start them at boot
```

`journalctl --user -u vdl2-sniffer -f` shows the frames as they arrive. After editing
`~/.config/vdl2-sniffer.env`, run `systemctl --user restart vdl2-sniffer`.

## Archive events

| Event | Fields |
| --- | --- |
| `start` | `t`, `sys`, `centre`, `rate`, `ch` |
| `vmix` | `t` (minute), `ch: {hz: [bursts, frames]}` |
| `vframe` | `t`, `freq`, `snr`, `src`, `sk`, `dst`, `dk`, `cr`, `ctl`, `len`, `rs`, `er` (kinds: 1 aircraft, 4/5 ground station) |
| `acars` | `t`, `freq`, `reg`, `flt`, `lbl`, `dir`, `txt`, `dec` (libacars's tree), `sys: "vdl2"`, `src`, `dst`, and `lat`/`lon`/`psrc` when the text gave a position. `dir` is `UL` for aircraft to ground, iridium-sniffer's convention; the dashboard shows it as A→G. `txt` is libacars's text (sub-label prefix such as `#M1B` removed) |
| `vpos` | `t`, `icao`, `gs`, `lat`, `lon`, `src` (`text` or `fix`): a position from ACARS text, logged per frame even when its multi-block message never completes |
| `xid` | `t`, `freq`, `src`, `sk`, `dst`, `dk`, `cr`, `x` (the XID object below) |

Times are epoch milliseconds. A multi-block ACARS message is logged once, whole, when libacars
completes it.

## Positions from ACARS text

Positions come only from messages the aircraft sent (`acars_position.c`). Only labels known to
report the aircraft's current position count (H1, 20, 44, 4J, 15, SA; not H1 flight plans).
Coordinates written in the text come first (`POSN46247W101478`, `N33521W084123`,
`LAT N 46:27.2 LONG W101:39.7` and similar). Trajectory and weather reports carry several timed
records, oldest first, and the newest one counts: `TRP` reports (`TRP 110814  32.8998  -97.0403`,
records `/A1` to `/A5`, or `#`-separated) and degrees-and-minutes records (`N3006.4,W08531.3,210145`). Labels 32 and 83 have position reports of their own:
`P,R,…,N45.773 W101.368,…` (32), `001PR26190048N4500.6W10043.3…` and `EHAM,KLAX,261903, 46.79,-101.63,…` (83). Failing that, a `POS` report that names a fix instead
of coordinates gives that fix, looked up in the fix list; the aircraft may be well past it. The fix
lookup is held to `POS` reports because anywhere else it matches ordinary words. Positions go into
the JSON (`ac_pos`), the `acars` and `vpos` archive events and the summary line.

The fix list (`data/waypoints.csv`, 147,503 fixes) is built by `data/build_waypoints.py`: the FAA's
fix positions where it lists the fix, X-Plane's and the Global Aviation Waypoints list elsewhere.

## XID

XID frames manage the link between aircraft and ground stations (`vdl2_xid.cc`). The JSON
`xid` object carries the public parameters (`param_set`, `proc_classes`, `hdlc_opts`) and the VDL
ones: `conn_mgmt`, `seq`/`retry`, `avlc_opts`, `dst_airport`, `ac_location`
(`lat`/`lon` to 0.1 degree, `alt_ft` in 1000 ft steps), and `alt_gs` (the ground stations the
aircraft can hear). `type` is set only for kinds confirmed on the air: `Handoff Initiation` and
`Handoff Response` from an aircraft. Any other parameter is kept under `unknown` as group, ID and
hex rather than guessed.

Every field was checked against dumpvdl2's decode of the same frames (`tests/xid_check.py`, 20 of
20). No capture so far holds a single ground-station transmission, so ground-station information
frames (station positions, frequencies) are unverified and arrive as `unknown` parameters. The
dashboard estimates each station's position instead, from the positions of aircraft talking to it.

## Tests

- `tests/run_tests.sh`: positions from ACARS text. Needs no captures.
- `tests/ab_run.sh CAPTURE_DIR ORACLE_DIR`: runs every capture that has dumpvdl2 text output
  beside it and compares frames byte for byte (`tests/ab_compare.py`). It then checks every XID
  frame dumpvdl2 decoded against our parse (`tests/xid_check.py`), and runs the three busiest
  captures with the IQ conjugated, requiring zero frames.

## Known gaps

- Direct input from RTL-SDR only (`--rtlsdr`); other receivers come through stdin (`airspy_rx`).
- No installer or live map yet.
- `sig_level` and `noise_level` are not in the JSON. The receiver measures SNR only, which is in
  `snr`.
- The air/ground status bit is read but untested: no capture has an aircraft on the ground.
- Packed trajectory records (`C1TRP` with `/C2324491,-0866412`) are not parsed.
- CPU: about 11% of a core per channel at 1.05 MS/s.

## Licence

GPL-3.0-or-later (`LICENSE`). The decoder in `third_party/vdl2` is Mike Brown's, under the MIT
licence of CyberEther, the project it is written for. `acars_position.c` and `waypoint_db.c` come from iridium-sniffer. The fix list combines
X-Plane's `earth_fix.dat` (GPL-3.0), Global Aviation Waypoints (MIT) and the FAA's fix data
(public domain).
