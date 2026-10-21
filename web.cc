/*
 * vdl2-sniffer's own live page (--web). See web.hh.
 *
 * Copyright (c) 2026 Mike Brown
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "web.hh"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <ctime>

namespace LiveWeb {

namespace {

constexpr double kKeepAircraft = 7200;     // s an aircraft stays listed after its last frame
constexpr double kHandoffWindow = 1800;    // s within which a station change is a handoff
constexpr size_t kMessages = 200, kHandoffs = 100, kTrack = 20, kSamples = 3000;
constexpr int kMinPositions = 3;           // different positions before a station is placed
constexpr double kEarthKm = 6371.0;

double wallNow() {
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

std::string quote(const std::string& s) {
    std::string o = "\"";
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') { o += '\\'; o += (char)c; }
        else if (c < 0x20 || c == 0x7f) { char b[8]; snprintf(b, sizeof b, "\\u%04x", c); o += b; }
        else o += (char)c;
    }
    return o + "\"";
}

std::string hex6(uint32_t a) {
    char b[12];
    snprintf(b, sizeof b, "\"%06X\"", a & 0xFFFFFF);
    return b;
}

std::string num(double v, int decimals) {
    char b[48];
    snprintf(b, sizeof b, "%.*f", decimals, v);
    return b;
}

double km(double lat1, double lon1, double lat2, double lon2) {
    const double r = M_PI / 180, p1 = lat1 * r, p2 = lat2 * r;
    const double dp = p2 - p1, dl = (lon2 - lon1) * r;
    const double a = std::sin(dp / 2) * std::sin(dp / 2) + std::cos(p1) * std::cos(p2) * std::sin(dl / 2) * std::sin(dl / 2);
    return 2 * kEarthKm * std::asin(std::min(1.0, std::sqrt(a)));
}

bool isStation(int kind) { return kind == 4 || kind == 5; }

extern const char kPage[];

}  // namespace

/* ---------- what the engine reports ---------- */

void Server::frame(double t, double freq, float snr, uint32_t src, int srcKind, uint32_t dst, int dstKind) {
    std::lock_guard<std::mutex> lock(mu_);
    nFrames_++;
    latest_ = std::max(latest_, t);
    for (auto [addr, kind] : {std::pair<uint32_t, int>{src, srcKind}, {dst, dstKind}})
        if (isStation(kind)) { auto& s = stations_[addr]; s.frames++; s.last = std::max(s.last, t); }
    const bool up = srcKind == 1, down = dstKind == 1;
    if (!up && !down) return;
    auto& a = aircraft_[up ? src : dst];
    if (!a.first) a.first = t;
    a.last = std::max(a.last, t);
    a.frames++;
    a.freq = freq;
    if (up) { a.snr = snr; a.bestSnr = std::max(a.bestSnr, snr); }
    if (t - lastPrune_ > 60) prune(t);
}

void Server::acars(double t, double freq, uint32_t aircraft, uint32_t station, bool fromAircraft,
                   const std::string& reg, const std::string& flight, const std::string& label,
                   const std::string& text) {
    std::lock_guard<std::mutex> lock(mu_);
    nAcars_++;
    auto& a = aircraft_[aircraft];
    if (!reg.empty()) a.reg = reg;
    if (!flight.empty()) a.flight = flight;
    a.acars++;
    // the station an aircraft exchanges traffic with, as the rollup keeps it
    a.station = station;
    a.stationT = t;
    messages_.push_back({t, freq, aircraft, station, fromAircraft, reg, flight, label, text});
    if (messages_.size() > kMessages) messages_.pop_front();
}

void Server::xid(double t, uint32_t aircraft, uint32_t station, const std::string& type,
                 const std::string& airport, const std::vector<uint32_t>& alternates,
                 bool hasLocation, double lat, double lon, int altFt) {
    std::lock_guard<std::mutex> lock(mu_);
    nXid_++;
    auto& a = aircraft_[aircraft];
    const uint32_t from = a.station && a.station != station && t - a.stationT < kHandoffWindow ? a.station : 0;
    a.station = station;
    a.stationT = t;
    if (!airport.empty()) a.airport = airport;
    if (hasLocation) {
        nPos_++;
        a.track.push_back({t, lat, lon, altFt, "xid"});
        if (a.track.size() > kTrack) a.track.pop_front();
        addSample(station, lat, lon, 1.0, true);
        for (uint32_t o : alternates)
            if (o != station) addSample(o, lat, lon, 0.5, false);
    }
    handoffs_.push_back({t, aircraft, from, station, type, airport, hasLocation, lat, lon, altFt});
    if (handoffs_.size() > kHandoffs) handoffs_.pop_front();
}

void Server::position(double t, uint32_t aircraft, uint32_t station, double lat, double lon, const char* src) {
    std::lock_guard<std::mutex> lock(mu_);
    nPos_++;
    auto& a = aircraft_[aircraft];
    a.track.push_back({t, lat, lon, -1, src});
    if (a.track.size() > kTrack) a.track.pop_front();
    if (station) addSample(station, lat, lon, strcmp(src, "fix") == 0 ? 0.5 : 1.0, true);
}

void Server::channels(const std::vector<uint64_t>& bursts, const std::vector<uint64_t>& frames) {
    std::lock_guard<std::mutex> lock(mu_);
    bursts_ = bursts;
    frames_ = frames;
}

void Server::addSample(uint32_t station, double lat, double lon, double w, bool target) {
    auto& s = stations_[station];
    s.samples.push_back({lat, lon, w, target});
    if (s.samples.size() > kSamples) s.samples.pop_front();
}

void Server::prune(double now) {
    lastPrune_ = now;
    for (auto it = aircraft_.begin(); it != aircraft_.end();)
        it = now - it->second.last > kKeepAircraft ? aircraft_.erase(it) : std::next(it);
}

/* ---------- the state as JSON ---------- */

std::string Server::stateJson() {
    std::lock_guard<std::mutex> lock(mu_);
    std::string j = "{\"now\":" + num(wallNow(), 1) + ",\"latest\":" + num(latest_, 1) +
                    ",\"started\":" + num(started_, 1) + ",\"station_id\":" + quote(stationId_);
    j += ",\"totals\":{\"frames\":" + std::to_string(nFrames_) + ",\"acars\":" + std::to_string(nAcars_) +
         ",\"xid\":" + std::to_string(nXid_) + ",\"positions\":" + std::to_string(nPos_) + "}";

    j += ",\"channels\":[";
    for (size_t i = 0; i < channels_.size(); i++) {
        if (i) j += ",";
        j += "{\"freq\":" + num(channels_[i], 0) + ",\"bursts\":" + std::to_string(i < bursts_.size() ? bursts_[i] : 0) +
             ",\"frames\":" + std::to_string(i < frames_.size() ? frames_[i] : 0) + "}";
    }
    j += "]";

    std::vector<std::pair<uint32_t, const Aircraft*>> acs;
    for (auto& [id, a] : aircraft_) acs.push_back({id, &a});
    std::sort(acs.begin(), acs.end(), [](auto& x, auto& y) { return x.second->last > y.second->last; });
    j += ",\"aircraft\":[";
    for (size_t i = 0; i < acs.size(); i++) {
        const Aircraft& a = *acs[i].second;
        if (i) j += ",";
        j += "{\"icao\":" + hex6(acs[i].first) + ",\"reg\":" + quote(a.reg) + ",\"flight\":" + quote(a.flight) +
             ",\"airport\":" + quote(a.airport) + ",\"station\":" + (a.station ? hex6(a.station) : "null") +
             ",\"first\":" + num(a.first, 1) + ",\"last\":" + num(a.last, 1) + ",\"freq\":" + num(a.freq, 0) +
             ",\"snr\":" + num(a.snr, 1) + ",\"best_snr\":" + (a.bestSnr > -1e8f ? num(a.bestSnr, 1) : "null") +
             ",\"frames\":" + std::to_string(a.frames) + ",\"acars\":" + std::to_string(a.acars) + ",\"track\":[";
        for (size_t k = 0; k < a.track.size(); k++) {
            const Fix& f = a.track[k];
            if (k) j += ",";
            j += "[" + num(f.t, 1) + "," + num(f.lat, 4) + "," + num(f.lon, 4) + "," +
                 (f.altFt >= 0 ? std::to_string(f.altFt) : "null") + "," + quote(f.src) + "]";
        }
        j += "]}";
    }
    j += "]";

    // each station at the weighted centre of the aircraft positions reported
    // to it or near it (mean of unit vectors), as the Observatory does it
    j += ",\"stations\":[";
    bool first = true;
    for (auto& [id, s] : stations_) {
        if (!first) j += ",";
        first = false;
        double x = 0, y = 0, z = 0, w = 0;
        int target = 0, heard = 0;
        std::vector<std::pair<double, double>> distinct;
        for (auto& p : s.samples) {
            const double la = p.lat * M_PI / 180, lo = p.lon * M_PI / 180;
            x += p.w * std::cos(la) * std::cos(lo);
            y += p.w * std::cos(la) * std::sin(lo);
            z += p.w * std::sin(la);
            w += p.w;
            (p.target ? target : heard)++;
            if (std::find(distinct.begin(), distinct.end(), std::make_pair(p.lat, p.lon)) == distinct.end())
                distinct.push_back({p.lat, p.lon});
        }
        j += "{\"id\":" + hex6(id) + ",\"frames\":" + std::to_string(s.frames) + ",\"last\":" + num(s.last, 1) +
             ",\"n_pos\":" + std::to_string(distinct.size()) + ",\"n_target\":" + std::to_string(target) +
             ",\"n_heard\":" + std::to_string(heard);
        if ((int)distinct.size() >= kMinPositions && w > 0) {
            const double lat0 = std::atan2(z, std::hypot(x, y)) * 180 / M_PI, lon0 = std::atan2(y, x) * 180 / M_PI;
            double sq = 0;
            for (auto& p : s.samples) { const double d = km(lat0, lon0, p.lat, p.lon); sq += p.w * d * d; }
            j += ",\"lat\":" + num(lat0, 3) + ",\"lon\":" + num(lon0, 3) + ",\"spread_km\":" + num(std::sqrt(sq / w), 0);
        }
        j += "}";
    }
    j += "]";

    j += ",\"messages\":[";
    for (size_t i = 0; i < messages_.size(); i++) {
        const Message& m = messages_[messages_.size() - 1 - i];   // newest first
        if (i) j += ",";
        j += "{\"t\":" + num(m.t, 1) + ",\"freq\":" + num(m.freq, 0) + ",\"aircraft\":" + hex6(m.aircraft) +
             ",\"station\":" + hex6(m.station) + ",\"up\":" + (m.fromAircraft ? "true" : "false") +
             ",\"reg\":" + quote(m.reg) + ",\"flight\":" + quote(m.flight) + ",\"label\":" + quote(m.label) +
             ",\"text\":" + quote(m.text) + "}";
    }
    j += "]";

    j += ",\"handoffs\":[";
    for (size_t i = 0; i < handoffs_.size(); i++) {
        const Handoff& h = handoffs_[handoffs_.size() - 1 - i];
        if (i) j += ",";
        j += "{\"t\":" + num(h.t, 1) + ",\"aircraft\":" + hex6(h.aircraft) + ",\"from\":" +
             (h.from ? hex6(h.from) : "null") + ",\"to\":" + hex6(h.to) + ",\"type\":" + quote(h.type) +
             ",\"airport\":" + quote(h.airport);
        if (h.hasLocation)
            j += ",\"lat\":" + num(h.lat, 1) + ",\"lon\":" + num(h.lon, 1) +
                 ",\"alt\":" + (h.altFt >= 0 ? std::to_string(h.altFt) : "null");
        j += "}";
    }
    return j + "]}";
}

/* ---------- HTTP ---------- */

bool Server::start(int port, const std::vector<double>& channels, const std::string& stationId) {
    channels_ = channels;
    stationId_ = stationId;
    started_ = wallNow();
    listenFd_ = socket(AF_INET, SOCK_STREAM, 0);
    if (listenFd_ < 0) { perror("web: socket"); return false; }
    int one = 1;
    setsockopt(listenFd_, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port = htons((uint16_t)port);
    if (bind(listenFd_, (sockaddr*)&addr, sizeof addr) < 0 || listen(listenFd_, 16) < 0) {
        fprintf(stderr, "vdl2-sniffer: --web cannot listen on port %d: %s\n", port, strerror(errno));
        close(listenFd_);
        listenFd_ = -1;
        return false;
    }
    running_ = true;
    thread_ = std::thread([this] { serve(); });
    fprintf(stderr, "vdl2-sniffer: live page on http://0.0.0.0:%d/\n", port);
    return true;
}

void Server::stop() {
    if (!running_) return;
    running_ = false;
    if (thread_.joinable()) thread_.join();
    close(listenFd_);
    listenFd_ = -1;
}

// One request at a time: the page and its poll are small, and a client gets
// two seconds to send its request line before it is dropped.
void Server::serve() {
    while (running_) {
        fd_set rf;
        FD_ZERO(&rf);
        FD_SET(listenFd_, &rf);
        timeval tv{1, 0};
        if (select(listenFd_ + 1, &rf, nullptr, nullptr, &tv) <= 0) continue;
        const int fd = accept(listenFd_, nullptr, nullptr);
        if (fd < 0) continue;
        timeval to{2, 0};
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &to, sizeof to);
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &to, sizeof to);
        handle(fd);
        close(fd);
    }
}

void Server::handle(int fd) {
    char req[2048];
    size_t n = 0;
    while (n < sizeof req - 1) {
        const ssize_t r = recv(fd, req + n, sizeof req - 1 - n, 0);
        if (r <= 0) break;
        n += (size_t)r;
        req[n] = '\0';
        if (strstr(req, "\r\n\r\n") || strstr(req, "\n\n")) break;
    }
    req[n] = '\0';
    char method[8] = "", path[256] = "";
    if (sscanf(req, "%7s %255s", method, path) != 2) return;
    if (char* q = strchr(path, '?')) *q = '\0';
    const bool head = strcmp(method, "HEAD") == 0;
    std::string body, type = "text/plain", status = "200 OK";
    if (strcmp(method, "GET") != 0 && !head) { status = "405 Method Not Allowed"; body = "GET only"; }
    else if (strcmp(path, "/") == 0) { body = kPage; type = "text/html; charset=utf-8"; }
    else if (strcmp(path, "/api/state") == 0) { body = stateJson(); type = "application/json"; }
    else if (strcmp(path, "/healthz") == 0) body = "ok";
    else { status = "404 Not Found"; body = "not found"; }
    std::string out = "HTTP/1.1 " + status + "\r\nContent-Type: " + type + "\r\nContent-Length: " +
                      std::to_string(body.size()) + "\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n";
    if (!head) out += body;
    for (size_t off = 0; off < out.size();) {
        const ssize_t w = send(fd, out.data() + off, out.size() - off, MSG_NOSIGNAL);
        if (w <= 0) return;
        off += (size_t)w;
    }
}

/* ---------- the page ---------- */

namespace {

const char kPage[] = R"PAGE(<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VDL2 live</title>
<style>
  :root{--bg:#0e1116;--panel:#161b22;--panel2:#1c232c;--line:#2b333d;--grid:#222a33;
    --fg:#e6edf3;--dim:#8b98a5;--accent:#4aa8ff;--good:#3fb950;--warn:#d29922;--hot:#f778ba}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
    font:14px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
  header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;padding:14px 22px;
    border-bottom:1px solid var(--line);background:var(--panel)}
  header h1{font-size:18px;margin:0;font-weight:650}
  header .sub{color:var(--dim);font-size:12.5px}
  header .spacer{flex:1}
  .status{color:var(--dim);font-size:12px}
  .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--good);
    margin-right:5px;vertical-align:middle}
  main{padding:16px 22px;max-width:1500px;margin:0 auto}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:14px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
  .card .k{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.6px}
  .card .v{font-size:24px;font-weight:600;margin-top:3px}
  .card .v small{font-size:12.5px;color:var(--dim);font-weight:400}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;
    margin-bottom:14px;min-width:0}
  .panel h2{font-size:13px;margin:0 0 8px;font-weight:600;display:flex;justify-content:space-between;
    gap:8px;flex-wrap:wrap}
  .panel h2 .hint{color:var(--dim);font-weight:400;font-size:11.5px}
  .grid{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:14px}
  @media(max-width:1000px){.grid{grid-template-columns:minmax(0,1fr)}}
  .scroll{max-height:460px;overflow:auto}
  table{width:100%;border-collapse:collapse;font-size:12.5px}
  th{text-align:left;color:var(--dim);font-weight:500;font-size:11px;text-transform:uppercase;
    letter-spacing:.5px;padding:5px 7px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--panel)}
  td{padding:5px 7px;border-bottom:1px solid #1b2129;vertical-align:top;white-space:nowrap}
  td.body{white-space:normal;overflow-wrap:anywhere;min-width:240px}
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  .n{color:var(--dim);font-variant-numeric:tabular-nums}
  .dir{font-size:10px;padding:1px 5px;border-radius:4px}
  .dir.up{background:#241a2e;color:#a371f7}
  .dir.dn{background:#12261a;color:var(--good)}
  .fresh td{animation:fresh 2.5s ease-out}
  @keyframes fresh{from{background:#1d3a5c}to{background:transparent}}
  .empty{color:var(--dim);padding:20px;text-align:center;font-size:13px}
  .gl{stroke:var(--grid);stroke-width:1}
  .ax{fill:var(--dim);font-size:11px}
  .lbl{fill:var(--fg);font-size:12px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  .albl{fill:#c9d1d9;font-size:11px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  .key{color:var(--dim);font-size:11.5px;margin-top:6px}
  .key i{display:inline-block;width:9px;height:9px;margin:0 4px 0 10px;vertical-align:middle}
</style></head>
<body>
<header>
  <h1>VDL2 live</h1>
  <span class="sub" id="sub">vdl2-sniffer</span>
  <span class="spacer"></span>
  <span class="status" id="status"><span class="dot"></span>loading…</span>
</header>
<main>
  <div class="cards" id="cards"></div>
  <div class="panel">
    <h2>Map <span class="hint">aircraft positions from handoffs and ACARS text, last hour; stations at the centre of the positions reported to them since the receiver started</span></h2>
    <div id="map"></div>
    <div class="key"><i style="background:#4aa8ff"></i>ground station<i style="background:#e6edf3;border-radius:50%"></i>aircraft, latest position (fades with age)<i style="background:#8b98a5;height:2px"></i>its track</div>
  </div>
  <div class="grid">
    <div class="panel">
      <h2>Messages <span class="hint">newest first; A→G aircraft to ground</span></h2>
      <div class="scroll" id="msgs"></div>
    </div>
    <div class="panel">
      <h2>Aircraft <span class="hint">heard in the last 30 minutes</span></h2>
      <div class="scroll" id="acft"></div>
    </div>
  </div>
  <div class="grid">
    <div class="panel">
      <h2>Handoffs <span class="hint">XID frames: the station an aircraft moves to</span></h2>
      <div class="scroll" id="hand"></div>
    </div>
    <div class="panel">
      <h2>Channels <span class="hint">since the receiver started</span></h2>
      <div id="chans"></div>
    </div>
  </div>
</main>
<script>
const $=id=>document.getElementById(id);
let D=null, seen=new Set(), firstLoad=true;
function esc(s){return (s==null?"":""+s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
function hms(t){const d=new Date(t*1000),p=x=>String(x).padStart(2,"0");
  return p(d.getUTCHours())+":"+p(d.getUTCMinutes())+":"+p(d.getUTCSeconds());}
function ago(s){s=Math.max(0,Math.round(s));if(s<60)return s+" s";if(s<3600)return Math.round(s/60)+" min";
  return (s/3600).toFixed(1)+" h";}
function fmt(n){return n>=1e4?(n/1e3).toFixed(1)+"k":""+n;}
function ll(la,lo){return Math.abs(la).toFixed(2)+(la<0?"S ":"N ")+Math.abs(lo).toFixed(2)+(lo<0?"W":"E");}
function el(tag,attrs,text){const e=document.createElementNS("http://www.w3.org/2000/svg",tag);
  for(const k in attrs||{})e.setAttribute(k,attrs[k]);if(text!=null)e.textContent=text;return e;}
function card(k,v,sub){return '<div class="card"><div class="k">'+k+'</div><div class="v">'+v+
  (sub?' <small>'+sub+'</small>':'')+'</div></div>';}
function name(a){return a?(a.flight||a.reg||a.icao):"";}

async function load(){
  try{const r=await fetch("/api/state",{cache:"no-store"});D=await r.json();render();}
  catch(e){$("status").innerHTML='<span class="dot" style="background:var(--warn)"></span>receiver not answering';}
}
function render(){
  const now=D.latest||D.now, A={};D.aircraft.forEach(a=>A[a.icao]=a);
  const age=D.latest?D.now-D.latest:null;
  $("status").innerHTML='<span class="dot" style="background:'+(age!=null&&age<300?'var(--good)':'var(--warn)')+
    '"></span>'+(age==null?'no frames yet':'last frame '+ago(age)+' ago')+' · up '+ago(D.now-D.started);
  $("sub").textContent=(D.station_id?D.station_id+" · ":"")+D.channels.length+" channels "+
    (D.channels.length?(D.channels[0].freq/1e6).toFixed(3)+"–"+(D.channels[D.channels.length-1].freq/1e6).toFixed(3)+" MHz":"");
  const recent=D.aircraft.filter(a=>now-a.last<600).length;
  const placed=D.stations.filter(s=>s.lat!=null).length;
  $("cards").innerHTML=card("Aircraft",recent,"last 10 min · "+D.aircraft.length+" in 2 h")+
    card("Frames",fmt(D.totals.frames))+card("ACARS",fmt(D.totals.acars))+card("Handoffs",fmt(D.totals.xid))+
    card("Positions",fmt(D.totals.positions))+card("Stations",D.stations.length,placed+" placed");
  map(now,A);
  // messages
  if(!D.messages.length)$("msgs").innerHTML='<div class="empty">no ACARS yet</div>';
  else $("msgs").innerHTML='<table><tr><th>UTC</th><th>MHz</th><th>Dir</th><th>Tail</th><th>Flight</th><th>Lbl</th><th>Text</th></tr>'+
    D.messages.slice(0,80).map(m=>{const k="m"+m.t+m.aircraft+m.label,f=!firstLoad&&!seen.has(k);seen.add(k);
      return '<tr'+(f?' class="fresh"':'')+'><td class="mono n">'+hms(m.t)+'</td><td class="mono n">'+(m.freq/1e6).toFixed(3)+
      '</td><td><span class="dir '+(m.up?'up">A→G':'dn">G→A')+'</span></td><td class="mono">'+esc(m.reg||m.aircraft)+
      '</td><td>'+esc(m.flight)+'</td><td class="mono">'+esc(m.label)+'</td><td class="body">'+
      (m.text?esc(m.text):'<span class="n">—</span>')+'</td></tr>';}).join("")+'</table>';
  // aircraft
  const ac=D.aircraft.filter(a=>now-a.last<1800);
  if(!ac.length)$("acft").innerHTML='<div class="empty">no aircraft in the last 30 minutes</div>';
  else $("acft").innerHTML='<table><tr><th>ICAO</th><th>Tail</th><th>Flight</th><th>To</th><th>Station</th><th>SNR</th><th>Frames</th><th>Heard</th></tr>'+
    ac.map(a=>{const p=a.track.length?a.track[a.track.length-1]:null;
      return '<tr><td class="mono">'+a.icao+'</td><td class="mono">'+esc(a.reg)+'</td><td>'+esc(a.flight)+'</td><td>'+esc(a.airport)+
      '</td><td class="mono n">'+(a.station||'')+'</td><td class="n">'+(a.best_snr!=null?a.snr.toFixed(0)+' dB':'')+
      '</td><td class="n">'+a.frames+'</td><td class="n" title="'+(p?'position '+ll(p[1],p[2])+' ('+p[4]+', '+ago(now-p[0])+' ago)':'no position')+'">'+
      ago(now-a.last)+(p?' ◆':'')+'</td></tr>';}).join("")+'</table>';
  // handoffs
  if(!D.handoffs.length)$("hand").innerHTML='<div class="empty">no handoffs yet</div>';
  else $("hand").innerHTML='<table><tr><th>UTC</th><th>Aircraft</th><th>Station</th><th>To</th><th>Position</th></tr>'+
    D.handoffs.slice(0,50).map(h=>'<tr><td class="mono n">'+hms(h.t)+'</td><td class="mono">'+esc(name(A[h.aircraft])||h.aircraft)+
      '</td><td class="mono n">'+(h.from?h.from+' → ':'')+h.to+'</td><td>'+esc(h.airport)+'</td><td class="n">'+
      (h.lat!=null?ll(h.lat,h.lon)+(h.alt!=null?' '+fmt(h.alt)+' ft':''):'')+'</td></tr>').join("")+'</table>';
  // channels
  $("chans").innerHTML='<table><tr><th>MHz</th><th>Bursts</th><th>Frames</th><th>Frames per burst</th></tr>'+
    D.channels.map(c=>'<tr><td class="mono">'+(c.freq/1e6).toFixed(3)+'</td><td class="n">'+fmt(c.bursts)+
      '</td><td class="n">'+fmt(c.frames)+'</td><td class="n">'+(c.bursts?Math.round(100*c.frames/c.bursts)+'%':'–')+
      '</td></tr>').join("")+'</table>';
  firstLoad=false;
}
// Aircraft (dot at the latest position, faint track) and the ground
// stations they talk to, equirectangular around the data, no tiles.
function map(now,A){
  const host=$("map");
  const st=D.stations.filter(s=>s.lat!=null);
  const ac=D.aircraft.filter(a=>a.track.length&&now-a.track[a.track.length-1][0]<3600);
  const pts=st.map(s=>[s.lat,s.lon]);ac.forEach(a=>a.track.forEach(p=>pts.push([p[1],p[2]])));
  if(!pts.length){host.innerHTML='<div class="empty">no positions yet: they arrive with handoffs and ACARS position reports</div>';return;}
  let la0=Math.min(...pts.map(p=>p[0])),la1=Math.max(...pts.map(p=>p[0]));
  let lo0=Math.min(...pts.map(p=>p[1])),lo1=Math.max(...pts.map(p=>p[1]));
  const k=Math.cos((la0+la1)/2*Math.PI/180),pad=Math.max(0.3,(la1-la0)*0.08,(lo1-lo0)*k*0.08);
  la0-=pad;la1+=pad;lo0-=pad/k;lo1+=pad/k;
  const W=Math.max(240,host.clientWidth||900),H=Math.round(Math.max(260,Math.min(520,W*(la1-la0)/((lo1-lo0)*k))));
  const sc=Math.min(W/((lo1-lo0)*k),H/(la1-la0));
  const X=lo=>(lo-lo0)*k*sc+(W-(lo1-lo0)*k*sc)/2,Y=la=>(la1-la)*sc+(H-(la1-la0)*sc)/2;
  host.innerHTML="";const s=el("svg",{viewBox:"0 0 "+W+" "+H,width:W,height:H});host.appendChild(s);
  s.appendChild(el("rect",{x:0,y:0,width:W,height:H,fill:"none",stroke:"var(--line)"}));
  const step=(lo1-lo0)>8?2:1;
  for(let g=Math.ceil(lo0);g<=lo1;g++){if(g%step)continue;
    s.appendChild(el("line",{x1:X(g),y1:0,x2:X(g),y2:H,class:"gl"}));
    s.appendChild(el("text",{x:X(g)+4,y:H-6,class:"ax"},Math.abs(g)+(g<0?"W":"E")));}
  for(let g=Math.ceil(la0);g<=la1;g++){if(g%step)continue;
    s.appendChild(el("line",{x1:0,y1:Y(g),x2:W,y2:Y(g),class:"gl"}));
    s.appendChild(el("text",{x:4,y:Y(g)-4,class:"ax"},Math.abs(g)+(g<0?"S":"N")));}
  const S={};st.forEach(x=>S[x.id]=x);
  // a faint line from each aircraft to the station it is talking to
  ac.forEach(a=>{const p=a.track[a.track.length-1],g=S[a.station];if(!g||now-p[0]>1800)return;
    s.appendChild(el("line",{x1:X(p[2]),y1:Y(p[1]),x2:X(g.lon),y2:Y(g.lat),stroke:"#4aa8ff","stroke-opacity":.25,
      "stroke-width":1,"stroke-dasharray":"4 4"}));});
  ac.forEach(a=>{if(a.track.length<2)return;
    s.appendChild(el("polyline",{points:a.track.map(p=>X(p[2])+","+Y(p[1])).join(" "),fill:"none",
      stroke:"#8b98a5","stroke-opacity":.5,"stroke-width":1.5}));});
  const boxes=[],hit=(a,b)=>a[0]<b[0]+b[2]&&b[0]<a[0]+a[2]&&a[1]<b[1]+b[3]&&b[1]<a[1]+a[3];
  st.forEach(x=>boxes.push([X(x.lon)-6,Y(x.lat)-6,12,12]));
  const place=(cx,cy,t,cls,cw)=>{const w=t.length*cw,h=13;
    for(const [dx,dy] of [[9,-h/2],[-9-w,-h/2],[-w/2,-7-h],[-w/2,7],[9,-h-5],[9,5],[-9-w,-h-5],[-9-w,5]]){
      const b=[cx+dx,cy+dy,w,h];if(b[0]<0||b[1]<0||b[0]+w>W||b[1]+h>H)continue;
      if(boxes.some(q=>hit(b,q)))continue;boxes.push(b);
      s.appendChild(el("text",{x:b[0],y:b[1]+h-2,class:cls},t));return;}};
  ac.forEach(a=>{const p=a.track[a.track.length-1],o=now-p[0]<600?1:now-p[0]<1800?.6:.35;
    const c=el("circle",{cx:X(p[2]),cy:Y(p[1]),r:4.5,fill:"#e6edf3","fill-opacity":o});
    c.appendChild(el("title",null,name(a)+" ("+a.icao+") "+ll(p[1],p[2])+(p[3]!=null?" "+p[3]+" ft":"")+", "+p[4]+", "+ago(now-p[0])+" ago"));
    s.appendChild(c);boxes.push([X(p[2])-5,Y(p[1])-5,10,10]);});
  st.slice().sort((a,b)=>b.n_pos-a.n_pos).forEach(x=>place(X(x.lon),Y(x.lat),x.id,"lbl",7.3));
  ac.forEach(a=>{const p=a.track[a.track.length-1];if(now-p[0]<1800)place(X(p[2]),Y(p[1]),name(a),"albl",6.7);});
  st.forEach(x=>{const r=el("rect",{x:X(x.lon)-5,y:Y(x.lat)-5,width:10,height:10,rx:2,fill:"#4aa8ff"});
    r.appendChild(el("title",null,x.id+": "+ll(x.lat,x.lon)+", ±"+x.spread_km+" km from "+x.n_pos+" positions, "+x.frames+" frames"));
    s.appendChild(r);});
}
let rt=null;window.addEventListener("resize",()=>{clearTimeout(rt);rt=setTimeout(()=>{if(D)render();},200);});
load();setInterval(load,3000);
</script>
</body></html>
)PAGE";

}  // namespace

}  // namespace LiveWeb
