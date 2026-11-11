# Licences

vdl2-observatory as a whole is distributed under the **GNU General Public License,
version 3 or later** (`../LICENSE`). Some parts carry their own licence or notice, which
still applies to those parts:

| Part | Licence | Holder | Text |
|---|---|---|---|
| The engine, live page, Observatory, installer, scripts and tests (`vdl2_sniffer.cc`, `vdl2_xid.*`, `web.*`, `observatory/`, `install.sh`, `diagnose.sh`, `data/*.py`, `tests/`) | GPL-3.0-or-later | Mike Brown | `../LICENSE` |
| `basestation.*`, `waypoint_db.*`, `acars_position.*` (from iridium-sniffer) | GPL-3.0-or-later | CEMAXECUTER LLC | `../LICENSE` |
| The VDL2 decoder, `third_party/vdl2/` | MIT | Luigi F. Cruz (CyberEther's licence; the decoder is Mike Brown's, written for CyberEther) | `../third_party/vdl2/LICENSE` |
| `data/waypoints.csv`: fixes from X-Plane's `earth_fix.dat` | GPL-3.0 | as distributed with X-Plane | `../LICENSE` |
| `data/waypoints.csv`: fixes from Global Aviation Waypoints | MIT | Fayyaz Ali Khan | `MIT-Global-Aviation-Waypoints.txt` |
| `data/waypoints.csv`: FAA fix positions | public domain (US government work) | | |
| `data/outlines.json`: map outlines and towns | public domain | Natural Earth | `Natural-Earth.txt` |

The X-Plane fixes are why the whole program is GPL-3.0, along with the three files from
iridium-sniffer. The decoder's MIT licence lets it be used under the GPL here, and stays with
it when it's copied out on its own.

## Libraries it links to

These come from your system (the installer gets them from your distribution, or builds
libacars from source); they aren't part of this repository.

| Library | Licence | Used for |
|---|---|---|
| librtlsdr (osmocom rtl-sdr) | GPL-2.0-or-later | reading the RTL-SDR |
| libacars | MIT | decoding ACARS, CPDLC and ADS-C |
| libusb (through librtlsdr) | LGPL-2.1-or-later | USB |

A binary built against librtlsdr is distributed under the GPL in any case.
