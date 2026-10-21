/*
 * BaseStation (SBS) format output for aircraft position feeds
 *
 * Outputs MSG,3 position messages compatible with VRS, tar1090,
 * PlanePlotter, and other ADS-B tracking tools.
 *
 * Copied from iridium-sniffer's basestation.c. Changes for VDL2: the
 * aircraft's ICAO address comes from the frame, so there is no aircraft
 * database; speed and heading are derived only between precise fixes;
 * and the threads stop on basestation_destroy() rather than a global flag.
 *
 * Copyright (c) 2026 CEMAXECUTER LLC
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#ifndef __BASESTATION_H__
#define __BASESTATION_H__

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Initialize basestation output.
 * endpoint: "PORT" for TCP server, "HOST:PORT" for TCP client
 * Returns 0 on success, -1 on error.
 */
int basestation_init(const char *endpoint);

/*
 * Send an aircraft position in MSG,3 format to all connected clients
 * (server mode) or to the remote host (client mode).
 *
 * hex:       ICAO address, six hex digits
 * flight:    flight ID / callsign (may be empty)
 * lat, lon:  position in decimal degrees
 * alt_ft:    altitude in feet (-99999 if unknown)
 * precise:   1 for a position good enough to derive speed and heading
 *            from (coordinates in ACARS text); 0 for a coarse one (an XID
 *            report, 0.1 degree), which is sent but not used for that
 * timestamp: detection time in nanoseconds
 */
void basestation_send_position(const char *hex, const char *flight,
                                double lat, double lon,
                                int alt_ft, int precise, uint64_t timestamp_ns);

/*
 * Shut down basestation output (close sockets, stop thread).
 */
void basestation_destroy(void);

#ifdef __cplusplus
}
#endif

#endif
