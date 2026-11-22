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

## Install

New to Linux or SDR? [QUICKSTART.md](QUICKSTART.md) walks through it step by step.

On Debian, Ubuntu or Raspberry Pi OS, with the radio plugged in (an RTL-SDR, or a HackRF, Airspy R2
or Airspy HF+ through SoapySDR):

```bash
git clone https://github.com/mebrown47/vdl2-observatory.git
cd vdl2-observatory
./install.sh
```

Run it as your normal user; it uses sudo when it needs to. It installs the packages (and builds
libacars from source where the distro has none, and the Airspy HF+'s SoapySDR module, which no
distro packages), builds and tests vdl2-sniffer, lets the plugdev group open the radio, asks a few
questions (which radio, channel plan, gain, a feed and station id), and installs three services
that start at boot:

| Service | What it is |
| --- | --- |
| `vdl2-sniffer` | the receiver, with the live page on 8889 |
| `vdl2-rollup.timer` | folds the archive into the Observatory database every minute |
| `vdl2-observatory` | the VDL2 Observatory dashboard on 8891 |

**The pages have no login.** The live page (8889) and the Observatory (8891) answer anyone who can
reach those ports: they only read, and can't change the receiver or its settings, but they show
the aircraft and ground stations your receiver hears, which says roughly where it is. On a home
network that's usually fine. Before opening the ports to the internet, put them behind a reverse
proxy with a login (nginx or Caddy with basic auth, say) or allow only the addresses you trust in
the firewall (`ufw allow from 203.0.113.7 to any port 8891`). The servers are simple, made for a
handful of viewers; heavy traffic from the internet can slow them down.

Settings live in `/etc/vdl2-observatory.conf`. After an edit, restart the service that reads the
setting: `sudo systemctl restart vdl2-sniffer` for the receiver's `VDL2_ARGS`, or
`sudo systemctl restart vdl2-observatory` for the dashboard's `STATION`. Their logs are
`journalctl -u vdl2-sniffer -f` and `journalctl -u vdl2-observatory -f`. Program files live in
`/opt/vdl2-observatory`, the archive and database in `/var/lib/vdl2-observatory`. Later:

```bash
./install.sh --update        # git pull, rebuild, test, reinstall, restart
./install.sh --reconfigure   # ask the questions again; Enter keeps each current setting
./install.sh --uninstall     # remove services and program files; settings and data stay
./install.sh --dry-run       # show what it would do as root, change nothing
```

The version you're running is at the foot of the live page and the Observatory, in
`vdl2-sniffer --version`, and in the first line of its log: `v1.0` on a release, `v1.0-3-g4f31b44`
three commits after it.

A receiver set up by hand with the user units in `systemd/` is taken over: the installer offers its
settings, copies its archive, and stops and removes its user units (keeping copies).

When something isn't working, `./diagnose.sh` writes one text file with what's needed to
troubleshoot it: versions, the radio and its permissions, SoapySDR's modules, service state, what the live page and the
Observatory answer, and recent logs. It changes nothing. The file holds your settings and the stations
you hear, so look it over before posting it publicly.

## Build

```bash
sudo apt install build-essential cmake pkg-config librtlsdr-dev rtl-sdr
cmake -B build
cmake --build build -j
sudo cmake --install build      # optional: /usr/local/bin and the fix list
```

`rtl-sdr` brings the udev rules that let the plugdev group open the dongle. SoapySDR is optional,
for `--soapy`: `libsoapysdr-dev` and the radio's module (`soapysdr-module-hackrf`,
`soapysdr-module-airspy`; for the Airspy HF+, `libairspyhf-dev` and
[SoapyAirspyHF](https://github.com/pothosware/SoapyAirspyHF) built from source). libacars-2 is optional. With it, multi-block ACARS messages are reassembled and FANS-1/A (CPDLC,
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
| `--rtlsdr [DEV]` | read an RTL-SDR directly: index or serial (default 0); `--gain DB` (default auto), `--ppm N`, `--bias-tee`. If the decoder falls behind, whole buffers are dropped and reported once a minute, and frame times stay true. If the device goes away, vdl2-sniffer exits with status 1 for a service manager to restart it; if it hangs without going away, the watchdog below does the same |
| `--soapy [ARGS]` | read a radio through SoapySDR: HackRF, Airspy R2 or Airspy HF+ (supported, like the RTL-SDR: all four tested by the author), or anything else with a SoapySDR module (best effort; reports welcome). ARGS picks the device (`driver=airspy`, `driver=hackrf,serial=...`; default the first radio found; `--soapy list` shows them). The rate is chosen to cover the channels (1.05 MS/s where the radio has it, otherwise its lowest that fits: R2 2.5 MS/s, HF+ 912 kS/s, HackRF 2 MS/s) unless `-s` sets it, and converted to 1.05 MS/s on its own thread. A HackRF is tuned 250 kHz above the plan's centre, keeping its DC spike off the channels. `--gain` takes auto (the radio's AGC), a figure, or stages by name (`LNA=32,VGA=20`); `--antenna NAME`, `--soapy-setting KEY=VALUE` (repeatable), `--ppm`, `--bias-tee` as for the RTL-SDR. Drops and restarts as for `--rtlsdr`; samples the radio itself loses are counted from the clock |
| `-r FILE` / `-` | IQ file or stdin; `--format cu8\|cs8\|ci16\|cf32` (from the extension by default, cu8 on stdin) |
| `-s HZ`, `-c HZ` | input rate (default 1050000) and centre (default: the plan's centre). Any rate is converted to 1.05 MS/s |
| `--stall-exit S` | watchdog for live input (a radio or stdin): when no samples have been decoded for S seconds, log whether the radio went silent or the decoder stuck, and exit with status 3 so the service restarts it (default 60; 0 = never). A working RTL-SDR delivers samples every 31 ms however quiet the channels are, so a minute with none is a hang. Also ends a shutdown that hangs in the driver for more than 10 s |
| `--wait-for-radio` | a radio that isn't there or won't open is tried again after 10 s, 20 s, 40 s ... up to every 5 minutes, instead of exiting. The service units use it, so an unplugged radio costs a log line every few minutes rather than a restart every 10 s, and is picked up when it's plugged back in |
| `--plan us\|eu`, `--channels LIST` | channel plan, or channels in MHz or Hz |
| `--start TIME` | capture start for a file: epoch, `YYYY-MM-DD HH:MM:SS` local, or `...Z` UTC. Default: the file's mtime minus its length |
| `--json [FILE]` | one dumpvdl2-style JSON object per frame (stdout by default); `--raw` adds the AVLC octets. XID frames use dumpvdl2's layout (`pub_params`, `vdl_params`), which feed parsers such as acars_router require; on the ten captures every frame passes acars_vdlm2_parser |
| `--udp HOST:PORT [HOST:PORT ...]` | the same JSON over UDP to each destination, such as a local acarshub and an aggregator: `--udp 127.0.0.1:5555 feed.example.net:5552`. Up to 8; commas or a repeated `--udp` work too. A destination that can't be reached yet (at boot, say) is tried again every 10 s |
| `--station-id ID` | station id in the JSON (also `--station`) |
| `--archive [DIR]` | `vdl2-YYYYMMDD.jsonl` for the Observatory (default `./archive`) |
| `--web[=PORT]` | the live page, served by vdl2-sniffer itself on PORT (default 8889): no Python, no database |
| `--observatory-port PORT` | the Observatory port the live page links to, on the same host (default 8891; 0 = no link) |
| `--basestation[=PORT]` | BaseStation (SBS) `MSG,3` positions for tar1090, VRS and the like: a server on PORT (default 30003) that tools connect to, or `--basestation=HOST:PORT` to push to one (reconnects by itself) |
| `--basestation-fix` | also send positions taken from a named fix (off by default: the aircraft may be well past it) |
| `--waypoints FILE` | fix list for positions from ACARS text (default: the installed `waypoints.csv`; `none` turns the fallback off) |
| `-q` | no line per frame |

Without `--json` on stdout, it prints a line per frame:

```
02:09:34 136.800 +26.8 dB A3578A -> 228E05(GS) ACARS N314VB AA1292 H1 TRP KMIA KDEN ...
```

That is the time, the channel, the signal level, the sender and receiver (`GS` marks a ground
station), and the frame: ACARS with tail, flight, label and text, an XID, or a control frame such as
`RR`. At exit it prints bursts, frames and ACARS blocks per channel to stderr.

## The live page

`--web` serves a page from vdl2-sniffer itself, with nothing else to install: the frames it is
hearing now, seconds behind the air. It shows:

- aircraft and stations on a map, each aircraft with its track and a line to the station it is
  talking to, over land and water, country and state borders, lakes and town names;
- the newest messages, the aircraft heard in the last 30 minutes, handoffs, and per-channel counts;
- the receiver: the dongle, its gain and `--ppm`, dropped samples, and how far off frequency it
  is, with a suggested `--ppm`.

Station positions are estimated as the Observatory does it, from the positions reported since the
receiver started. The state lives in memory, so it starts empty after a restart; for history, use the
Observatory. `GET /api/state` returns the same state as JSON.

The map is Natural Earth's 1:50m land, lakes, and country and state lines, with its 1:10m towns,
built into the binary from `data/outlines.json` (made by `data/build_outlines.py`) and served at
`/map.json`, so the page needs no internet and loads no tiles. The map frames itself on what the
receiver hears, and shows fewer, bigger towns as the area it covers grows.

**Frequency error and `--ppm`.** Every frame's carrier offset from its channel is measured on the
unique word, in ppm: dumpvdl2's `freq_skew`, which the JSON output carries under the same name
(within a few tenths of a ppm of dumpvdl2's on the same recordings). One aircraft says little, since
transmitters are allowed a few ppm each way, but the median across many is the dongle's own error.
The Receiver panel takes each aircraft's median over its recent frames, then the median across the
aircraft heard in the last two hours, and once there are ten it suggests a `--ppm`: the current
setting minus that error, rounded. Change it in `/etc/vdl2-observatory.conf` and restart the
receiver. A TCXO dongle such as the RTL-SDR Blog V3 usually needs none.

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
  - ground stations, with a map of their estimated positions over the same Natural Earth
    outlines as the live page (`/map.json`, read from `data/outlines.json`)
  - handoffs between stations, and aircraft positions
  - the busiest aircraft
- **Messages** (`/messages`): each aircraft's messages, the CPDLC log and ADS-C.
- **Search** (`/search`): every stored ACARS message, filtered by aircraft (registration, flight
  or address, partial), text, label, direction, CPDLC/ADS-C, channel and a UTC date range. It
  shows the matches per day and the top labels, aircraft and channels (click one to filter),
  and the messages 200 to a page with the search text marked, CPDLC/ADS-C summaries joined in,
  and a link to the aircraft's track on the Flights page for the last 24 hours. Heartbeats
  (`_d`) are hidden unless asked for; filters live in the address, so a search can be
  bookmarked; `/api/search.csv` downloads up to 100,000 matches. A query still running after
  5 s is stopped, so a broad search can't slow the receiver. On a month of a feeder's messages
  (238,000) a search takes 0.2-0.3 s. Ported from iridium-observatory's Search tab.
- **Flights** (`/flights`): each aircraft heard in the last 2, 6 or 24 hours, with a map.
  - Its **track** is the positions it reported: XIDs (to 0.1°), ACARS position reports and
    ADS-C. Points it couldn't have flown between are left out (an intent list's points ahead, an
    older entry of a position history), and a fix it only named is never a position.
  - Its **origin and destination** come from its own messages, in seven layouts that airlines
    use: `TRP KMIA KMSP`, Southwest's `02E21KMCOKOKC`, `LDR01,...,KLAS,KMCO`,
    `POSRPT 1544/20 KXNA/KTPA`, `POS02,...,KPNS,KFTY`, `190339 KATL KPNS` and
    `LDG DATA REQ / KDEN KMCO`. Over two days on a feeder, each layout's destination matched
    the one the same aircraft gave in its XIDs 90-100% of the time. Otherwise the destination
    is the XID's.
  - A receiver that hears ground stations also gets their flight plans, ATIS and takeoff data,
    read by the same rules as iridium-observatory's Flights page (`observatory/context.py`).
  - Airports and navaids come from `observatory/data/`: OurAirports and FAA data, both public
    domain, built by `observatory/tools/build_reference_data.py`.
- **Coverage** (`/coverage`): where the receiver hears aircraft and how strongly, over the last
  day, week or month, from the positions aircraft report and the SNR of the frames that carried
  them.
  - A map of 0.1° cells coloured by median SNR, with range rings and the farthest the receiver
    hears in each 5° direction (95th percentile).
  - A sky plot, azimuth against elevation, like iridium-observatory's: VDL2 aircraft sit a few
    degrees above the horizon, where an antenna's pattern and what stands around it show. The
    elevation comes from the aircraft's altitude (its XIDs, or a position report's flight level)
    over a 4/3 earth.
  - SNR against distance.
  - It needs the receiver's location: `STATION="LAT,LON"` or `"LAT,LON,ANTENNA_M"` (antenna height
    above sea level, metres) in `/etc/vdl2-observatory.conf`, which the installer asks for. Without
    it, iridium-observatory's location (its ring-alert fix) is used if that runs on the same
    machine, and otherwise the page shows the map of cells alone. The page shows the location
    rounded to 0.1°.
  - Only decoded frames carry a position, so it shows where aircraft are heard, not where they're
    missed. Positions farther than a VHF receiver can hear (600 km) are set aside and counted.
- **Graph** (`/graph`): who hands aircraft to whom, laid out like iridium-observatory's Graph tab.
  Each XID names the ground station the aircraft leaves and the one it joins.
  - A diagram of the busiest station pairs in the last day, week, month or all time: left, the
    station the aircraft left; right, the one it joined; line width by aircraft. Click a station
    to show only its handoffs. A table lists the pairs.
  - One aircraft, by registration, flight or address: messages and heartbeats per day, the
    stations it used, the destinations in its XIDs, its message labels, aircraft served by the
    same station within 15 minutes, and its handoffs and the routes its messages gave. It links
    to the aircraft's messages in Search and, if heard in the last day, its track on Flights.
  - A station map, closed until opened: the same handoffs at the stations' estimated positions
    (the Overview's), opening on the busy core (the middle 80% of stations, weighted by
    handoffs); scroll to zoom, drag to move, or fit every station. Distant stations lean
    towards the receiver, as on the Overview.

`rollup.py` reads only what was appended since its last run, so run it every few minutes from a
timer or cron. The server reads the database only and never talks to vdl2-sniffer. Port 8891 is
chosen so that it can sit beside iridium-observatory's dashboard on 8890.

## Running as a service by hand

`install.sh` is the easy way. Without it, `systemd/` has user units for a receiver that runs on its own: `vdl2-sniffer.service` (the RTL-SDR,
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

## BaseStation output

`--basestation` sends each aircraft position as an SBS `MSG,3` line under the aircraft's ICAO address,
with the flight from its latest ACARS message as the callsign:

- coordinates in ACARS text (precise), and
- XID handoff positions (0.1 degree, about 10 km, with the reported altitude).

Speed and heading are derived only between two precise positions, at least 10 s apart; a coarse
XID position would turn them into noise. The code is iridium-sniffer's `basestation.c`, adapted:
VDL2 frames carry the ICAO address, so no aircraft database is needed.

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

The fix list (`data/waypoints.csv`, 133,674 fixes) holds the FAA's fix positions where it lists the
fix (`data/build_waypoints.py`) and X-Plane's elsewhere. Fixes that came only from the Global
Aviation Waypoints list were taken out (`data/remove_scraped_fixes.py`): that list is scraped from
OpenNav, whose terms for redistributing it are unknown. They were 9% of the file, and in a month
on a feeder no position came from a named fix at all.

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

- `sig_level` and `noise_level` are not in the JSON. The receiver measures SNR only, which is in
  `snr`.
- The air/ground status bit is read but untested: no capture has an aircraft on the ground.
- Packed trajectory records (`C1TRP` with `/C2324491,-0866412`) are not parsed.
- CPU: about 1% of a core per channel at 1.05 MS/s (eight channels: 7.5% of one laptop core with
  AVX2, 9% without). Nearly all of it is the mixer and the two channel filters.

## Licence

GPL-3.0-or-later (`LICENSE`). The decoder in `third_party/vdl2` is Mike Brown's, under the MIT
licence of CyberEther, the project it is written for. `basestation.c`, `waypoint_db.c` and
`acars_position.c` come from iridium-sniffer. The fix list combines X-Plane's `earth_fix.dat`
(GPL-3.0) and the FAA's fix data (public domain). The map outlines
are Natural Earth (public domain). [LICENSES/](LICENSES/README.md) lists every part with its licence,
holder and notice, and the libraries it links to.
