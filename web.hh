/*
 * vdl2-sniffer's own live page (--web): what the receiver is hearing now,
 * served from memory with no Python and no database.
 *
 * Copyright (c) 2026 Mike Brown
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The engine reports frames, ACARS, XID and positions as it decodes them;
 * a small HTTP server on its own thread serves one self-contained page
 * (GET /) and the live state as JSON (GET /api/state), which the page
 * polls every few seconds. Everything is kept since the engine started:
 * aircraft heard in the last two hours, the latest messages and handoffs,
 * per-channel counts, and each ground station's position estimated the way
 * the Observatory does it.
 */

#ifndef VDL2_WEB_HH
#define VDL2_WEB_HH

#include <cstdint>
#include <deque>
#include <map>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace LiveWeb {

class Server {
public:
    // Listen on port (all interfaces). False when the port cannot be bound.
    bool start(int port, const std::vector<double>& channels, const std::string& stationId);
    void stop();
    ~Server() { stop(); }

    // Every decoded frame. Times are epoch seconds of the frame.
    void frame(double t, double freq, float snr, uint32_t src, int srcKind, uint32_t dst, int dstKind);
    // An ACARS message (one per frame; a multi-block message as each block arrives).
    void acars(double t, double freq, uint32_t aircraft, uint32_t station, bool fromAircraft,
               const std::string& reg, const std::string& flight, const std::string& label,
               const std::string& text);
    // An XID from an aircraft: type ("Handoff Initiation" ...), destination
    // airport, the stations it can also hear.
    void xid(double t, uint32_t aircraft, uint32_t station, const std::string& type,
             const std::string& airport, const std::vector<uint32_t>& alternates,
             bool hasLocation, double lat, double lon, int altFt);
    // A position from ACARS text: src "text" or "fix".
    void position(double t, uint32_t aircraft, uint32_t station, double lat, double lon,
                  const char* src);
    // Per-channel bursts and frames since the start, in channel order.
    void channels(const std::vector<uint64_t>& bursts, const std::vector<uint64_t>& frames);

private:
    struct Fix { double t, lat, lon; int altFt; std::string src; };
    struct Aircraft {
        std::string reg, flight, airport;
        uint32_t station = 0;
        double stationT = 0;         // when it last exchanged traffic with that station
        double first = 0, last = 0, freq = 0;
        float snr = 0, bestSnr = -1e9f;
        uint64_t frames = 0, acars = 0;
        std::deque<Fix> track;       // newest last, a few entries
    };
    struct Sample { double lat, lon, w; bool target; };
    struct Station {
        double last = 0;
        uint64_t frames = 0;
        std::deque<Sample> samples;  // positions of aircraft talking to or hearing it
    };
    struct Message {
        double t, freq;
        uint32_t aircraft, station;
        bool fromAircraft;
        std::string reg, flight, label, text;
    };
    struct Handoff {
        double t;
        uint32_t aircraft, from, to;
        std::string type, airport;
        bool hasLocation;
        double lat, lon;
        int altFt;
    };

    void addSample(uint32_t station, double lat, double lon, double w, bool target);
    void prune(double now);
    std::string stateJson();
    void serve();
    void handle(int fd);

    std::mutex mu_;
    std::map<uint32_t, Aircraft> aircraft_;
    std::map<uint32_t, Station> stations_;
    std::deque<Message> messages_;
    std::deque<Handoff> handoffs_;
    std::vector<double> channels_;
    std::vector<uint64_t> bursts_, frames_;
    std::string stationId_;
    double started_ = 0, latest_ = 0, lastPrune_ = 0;
    uint64_t nFrames_ = 0, nAcars_ = 0, nXid_ = 0, nPos_ = 0;

    int listenFd_ = -1;
    volatile bool running_ = false;
    std::thread thread_;
};

}  // namespace LiveWeb

#endif
