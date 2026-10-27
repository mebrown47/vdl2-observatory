# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""
The Overview page: GET / and GET /api/vdl2[?hours=N].

Reads the vdl2_* tables rollup.py builds from vdl2-sniffer's archive.
Read-only, stdlib only, like server.py.
"""

import math
import os
import sqlite3
import time

CHANNEL_COLORS = ["#4aa8ff", "#3fb950", "#f778ba", "#d29922", "#a371f7",
                  "#79c0ff", "#ff7b72", "#e3b341", "#56d364", "#bc8cff"]


def _percentiles(bins, ps=(10, 50, 90)):
    """SNR percentiles from {bin_floor: count} (2 dB bins): each percentile
    reports its bin's middle, so it is good to +-1 dB."""
    total = sum(bins.values())
    if not total:
        return [None] * len(ps)
    out, acc, keys = [], 0, sorted(bins)
    targets = [total * p / 100 for p in ps]
    i = 0
    for k in keys:
        acc += bins[k]
        while i < len(targets) and acc >= targets[i]:
            out.append(k + 1)
            i += 1
    while len(out) < len(ps):
        out.append(keys[-1] + 1)
    return out


# Ground stations are almost never heard directly: they sit low and far off,
# and no capture so far holds a single ground-station transmission. Their
# positions are estimated from aircraft positions (vdl2_pos: XID reports,
# coordinates and named fixes in ACARS text, ADS-C): the station an aircraft
# is talking to is one whose coverage it is in, and every station in an XID
# alternate list is one it can hear. Each station's estimate is the weighted
# centre of those positions; a named fix counts half, since the aircraft may
# be well past it.
#
# It is the centre of where aircraft were, not a fix: a receiver only hears
# aircraft within a few hundred km of itself, so a distant station is seen
# from the receiver's side only and its estimate is pulled towards the
# receiver. Stations near the receiver come out best. Repeated reports of
# one spot add nothing, so a station needs MIN_POSITIONS different
# positions before it gets an estimate.
MIN_POSITIONS = 3
SOURCE_WEIGHT = {"xid": 1.0, "text": 1.0, "adsc": 1.0, "fix": 0.5}
HEARD_WEIGHT = 0.5
EARTH_KM = 6371.0


def estimate_stations(con):
    """[{station, lat, lon, spread_km, n_target, n_heard, n_pos}] from every
    XID position on record (all time: stations do not move). lat, lon and
    spread_km are None below MIN_POSITIONS different positions."""
    samples = {}
    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "vdl2_pos" in have:
        for gs, lat, lon, src in con.execute("SELECT gs,lat,lon,src FROM vdl2_pos"):
            samples.setdefault(gs, []).append((lat, lon, SOURCE_WEIGHT.get(src, 0.5), 1))
    for gs, lat, lon, alt_gs in con.execute(
            "SELECT gs,lat,lon,alt_gs FROM vdl2_xid WHERE lat IS NOT NULL"):
        for other in (alt_gs or "").split():
            if other != gs:
                samples.setdefault(other, []).append((lat, lon, HEARD_WEIGHT, 0))
    out = []
    for st, pts in samples.items():
        # mean of unit vectors: right across the dateline and near the poles
        x = y = z = w = 0.0
        for lat, lon, wt, _ in pts:
            la, lo = math.radians(lat), math.radians(lon)
            x += wt * math.cos(la) * math.cos(lo)
            y += wt * math.cos(la) * math.sin(lo)
            z += wt * math.sin(la)
            w += wt
        lat0 = math.degrees(math.atan2(z, math.hypot(x, y)))
        lon0 = math.degrees(math.atan2(y, x))
        sq = 0.0
        for lat, lon, wt, _ in pts:
            sq += wt * _km(lat0, lon0, lat, lon) ** 2
        n_pos = len({(lat, lon) for lat, lon, *_ in pts})
        ok = n_pos >= MIN_POSITIONS
        out.append({"station": st,
                    "lat": round(lat0, 3) if ok else None,
                    "lon": round(lon0, 3) if ok else None,
                    "spread_km": round(math.sqrt(sq / w)) if ok else None,
                    "n_target": sum(t for *_, t in pts),
                    "n_heard": sum(1 - t for *_, t in pts),
                    "n_pos": n_pos})
    out.sort(key=lambda r: (r["lat"] is None, -r["n_pos"]))
    return out


def _km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def build_vdl2(path, hours=None):
    if not os.path.exists(path):
        return {"error": "no database yet — run rollup.py first"}
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        have = {r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "vdl2_channel_hourly" not in have:
            return {"error": "database predates VDL2 (schema 4) — run "
                             "rollup.py once to add the tables"}

        def rows(sql, *a):
            return con.execute(sql, a).fetchall()

        span = rows("SELECT MIN(hour) a, MAX(hour) b FROM vdl2_channel_hourly")[0]
        hmin, hmax = span["a"], span["b"]
        if hmin is None:
            return {"error": "no VDL2 data yet — run vdl2-sniffer with "
                             "--archive into the archive directory"}
        hours = int(hours) if hours else 0
        floor = max(hmin, hmax - (hours - 1) * 3600) if hours > 0 else hmin

        channels = {}
        for r in rows("SELECT freq,SUM(bursts) b,SUM(frames) f FROM "
                      "vdl2_channel_hourly WHERE hour>=? GROUP BY freq", floor):
            channels[r["freq"]] = {"freq": r["freq"], "bursts": r["b"],
                                   "frames": r["f"]}
        bins = {}
        for r in rows("SELECT freq,bin,SUM(count) c FROM vdl2_snr_hourly "
                      "WHERE hour>=? GROUP BY freq,bin", floor):
            bins.setdefault(r["freq"], {})[r["bin"]] = r["c"]
        for f, c in channels.items():
            c["snr_p10"], c["snr_p50"], c["snr_p90"] = _percentiles(bins.get(f, {}))
        chan_list = [channels[f] for f in sorted(channels)]

        hourly = {}
        for r in rows("SELECT hour,freq,frames FROM vdl2_channel_hourly "
                      "WHERE hour>=? ORDER BY hour", floor):
            h = hourly.setdefault(r["hour"], {"hour": r["hour"], "ch": {},
                                              "aircraft": 0, "acars": 0,
                                              "cpdlc": 0, "adsc": 0})
            h["ch"][str(r["freq"])] = r["frames"]
        for r in rows("SELECT hour,COUNT(*) n FROM vdl2_aircraft_hourly "
                      "WHERE hour>=? GROUP BY hour", floor):
            if r["hour"] in hourly:
                hourly[r["hour"]]["aircraft"] = r["n"]
        for r in rows("SELECT hour,service,SUM(count) c FROM vdl2_msg_hourly "
                      "WHERE hour>=? GROUP BY hour,service", floor):
            if r["hour"] in hourly:
                hourly[r["hour"]][r["service"]] = r["c"]
        hour_list = [hourly[k] for k in sorted(hourly)]

        stations = [dict(r) for r in rows(
            "SELECT station,SUM(count) count,MAX(hour) last FROM "
            "vdl2_station_hourly WHERE hour>=? GROUP BY station "
            "ORDER BY count DESC LIMIT 20", floor)]
        aircraft = [dict(r) for r in rows(
            "SELECT icao,SUM(count) count,MAX(best_snr) best_snr,MAX(hour) last "
            "FROM vdl2_aircraft_hourly WHERE hour>=? GROUP BY icao "
            "ORDER BY count DESC LIMIT 40", floor)]

        xids, station_est, positions, pos_src = [], [], [], {}
        if "vdl2_xid" in have:
            station_est = estimate_stations(con)
            xids = [dict(r) for r in rows(
                "SELECT t,icao,gs,from_gs,kind,airport,lat,lon,alt FROM vdl2_xid "
                "WHERE t>=? ORDER BY t DESC LIMIT 60", floor)]
        if "vdl2_pos" in have:
            positions = [dict(r) for r in rows(
                "SELECT icao,gs,lat,lon,src FROM vdl2_pos ORDER BY t DESC LIMIT 500")]
            pos_src = {r["src"]: r["n"] for r in rows(
                "SELECT src,COUNT(*) n FROM vdl2_pos WHERE t>=? GROUP BY src", floor)}

        n_ac = rows("SELECT COUNT(DISTINCT icao) n FROM vdl2_aircraft_hourly "
                    "WHERE hour>=?", floor)[0]["n"]
        n_gs = rows("SELECT COUNT(DISTINCT station) n FROM vdl2_station_hourly "
                    "WHERE hour>=?", floor)[0]["n"]
        msg = {r["service"]: r["c"] for r in rows(
            "SELECT service,SUM(count) c FROM vdl2_msg_hourly WHERE hour>=? "
            "GROUP BY service", floor)}
        meta = {r[0]: r[1] for r in con.execute("SELECT key,value FROM meta")}

        return {
            "meta": {"generated": int(time.time()),
                     "last_run": int(meta.get("last_run", 0))},
            "span": {"start": floor, "end": hmax,
                     "hours": (hmax - floor) // 3600 + 1},
            "totals": {
                "bursts": sum(c["bursts"] for c in chan_list),
                "frames": sum(c["frames"] for c in chan_list),
                "aircraft": n_ac, "stations": n_gs,
                "messages": {s: msg.get(s, 0) for s in ("acars", "cpdlc", "adsc")},
            },
            "channels": chan_list,
            "hours": hour_list,
            "stations": stations,
            "aircraft": aircraft,
            "xid": xids,
            "station_est": station_est,
            "positions": positions,
            "pos_sources": pos_src,
        }
    finally:
        con.close()


VDL2_PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VDL2 Observatory</title>
<style>
  :root{
    --bg:#0e1116; --panel:#161b22; --panel2:#1c232c; --line:#2b333d;
    --fg:#e6edf3; --dim:#8b98a5; --accent:#4aa8ff; --good:#3fb950;
    --warn:#d29922; --hot:#f778ba; --grid:#242c36;
    --coast:#46566a; --border:#5a6878; --state:#36414e; --land:#1d242d; --water:#141920;
    --place:#8593a1;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
    font:14px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
  header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;
    padding:16px 22px;border-bottom:1px solid var(--line);background:var(--panel)}
  header h1{font-size:18px;margin:0;font-weight:650;letter-spacing:.2px}
  header .sub{color:var(--dim);font-size:12.5px}
  header .spacer{flex:1}
  .nav{display:flex;gap:4px}
  .nav a{color:var(--dim);text-decoration:none;font-size:13px;padding:4px 11px;
    border-radius:6px;border:1px solid transparent}
  .nav a:hover{color:var(--fg)}
  .nav a.on{color:var(--fg);background:var(--panel2);border-color:var(--line)}
  .nav a[hidden]{display:none}
  header .status{color:var(--dim);font-size:12px}
  header .dot{display:inline-block;width:8px;height:8px;border-radius:50%;
    background:var(--good);margin-right:5px;vertical-align:middle}
  .controls{display:flex;gap:6px}
  .controls button{background:var(--panel2);color:var(--dim);border:1px solid
    var(--line);padding:4px 10px;border-radius:6px;cursor:pointer;font-size:12px}
  .controls button.on{color:var(--fg);border-color:var(--accent);
    background:#182634}
  main{padding:18px 22px;max-width:1400px;margin:0 auto}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
    gap:12px;margin-bottom:18px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
    padding:14px 16px}
  .card .k{color:var(--dim);font-size:11.5px;text-transform:uppercase;
    letter-spacing:.6px}
  .card .v{font-size:26px;font-weight:600;margin-top:4px}
  .card .v small{font-size:13px;color:var(--dim);font-weight:400}
  .card.hot .v{color:var(--hot)}
  .grid{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:14px}
  @media(max-width:900px){.grid{grid-template-columns:minmax(0,1fr)}}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;
    padding:14px 16px 6px;margin-bottom:14px;overflow-x:auto}
  .panel h2{font-size:13px;margin:0 0 10px;font-weight:600;color:var(--fg);
    display:flex;justify-content:space-between;align-items:center;gap:10px}
  .panel h2 .hint{color:var(--dim);font-weight:400;font-size:11.5px}
  .legend{display:flex;flex-wrap:wrap;gap:10px;margin:6px 0 2px;font-size:11.5px;
    color:var(--dim)}
  .legend span{display:inline-flex;align-items:center;gap:5px}
  .legend i{width:10px;height:10px;border-radius:2px;display:inline-block}
  svg{display:block;width:100%;overflow:visible}
  .ax{fill:var(--dim);font-size:10.5px}
  .gl{stroke:var(--grid);stroke-width:1}
  .empty{color:var(--dim);padding:30px;text-align:center;font-size:13px}
  .bar:hover{opacity:.82}
  .mapax{fill:var(--dim);font-size:11px}
  .plc{fill:var(--place);font-size:10.5px}
  .maplbl{fill:var(--fg);font-size:12px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;cursor:pointer}
  .stsel{color:var(--dim);font-size:12px;min-height:16px;margin-top:6px}
  .strow{cursor:pointer}
  .strow.on td{background:#182634}
  table{width:100%;border-collapse:collapse;font-size:12.5px;margin-bottom:8px}
  th{color:var(--dim);font-weight:500;text-align:right;padding:4px 8px;
    border-bottom:1px solid var(--line);white-space:nowrap}
  td{text-align:right;padding:4px 8px;border-bottom:1px solid var(--grid);
    font-variant-numeric:tabular-nums;white-space:nowrap}
  th:first-child,td:first-child{text-align:left}
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  a{color:var(--accent)}
</style></head>
<body>
<header>
  <h1>VDL2 Observatory</h1>
  <nav class="nav"><a href="/" class="on">Overview</a><a href="/messages">Messages</a><a id="livelink" href="#" hidden>Live</a></nav>
  <span class="sub">VHF data link, 136.650–136.975 MHz</span>
  <span class="spacer"></span>
  <div class="controls" id="win">
    <button data-h="6">6h</button>
    <button data-h="24" class="on">24h</button>
    <button data-h="72">3d</button>
    <button data-h="168">7d</button>
    <button data-h="0">all</button>
  </div>
  <span class="status" id="status"><span class="dot"></span>loading…</span>
</header>
<main>
  <div class="cards" id="cards"></div>
  <div class="panel">
    <h2>Frames per hour <span class="hint">by channel</span></h2>
    <div class="legend" id="ch-legend"></div>
    <div id="frames"></div>
  </div>
  <div class="panel">
    <h2>Station map <span class="hint">each station at the centre of the positions of aircraft talking to or hearing it, all time; biased towards this receiver for distant stations. Click a station (here or in Ground stations) for its spread and positions</span></h2>
    <div id="stmap"></div>
    <div id="stsel" class="stsel"></div>
    <div class="stsel" style="text-align:right">map: Natural Earth</div>
  </div>
  <div class="grid">
    <div>
      <div class="panel">
        <h2>Channels <span class="hint">decoder health in window: frames per detected burst, SNR percentiles</span></h2>
        <div id="chans"></div>
      </div>
      <div class="panel">
        <h2>Messages per hour <span class="hint">ACARS and what libacars found inside</span></h2>
        <div class="legend" id="svc-legend"></div>
        <div id="svc"></div>
      </div>
      <div class="panel">
        <h2>Handoffs and positions <span class="hint">XID frames: the station an aircraft moves to, and where it said it was</span></h2>
        <div id="xid"></div>
      </div>
      <div class="panel">
        <h2>Aircraft per hour <span class="hint">distinct ICAO addresses heard or addressed</span></h2>
        <div id="achours"></div>
      </div>
    </div>
    <div>
      <div class="panel">
        <h2>Ground stations <span class="hint">frames to or from, in window</span></h2>
        <div id="stations"></div>
      </div>
      <div class="panel">
        <h2>Aircraft <span class="hint">most frames in window</span></h2>
        <div id="aircraft"></div>
      </div>
    </div>
  </div>
  <p style="color:var(--dim);font-size:11.5px;margin:6px 2px 30px">
    Times UTC. Aggregated hourly by rollup.py from vdl2-sniffer's archive.
    A burst is anything the energy detector opened on; most of a quiet
    channel's bursts are noise, so frames per burst is a trend, not a score.
    <span id="freshness"></span>
  </p>
</main>
<script>
// The live page runs on the same host, on vdl2-sniffer's --web port (server.py
// --live-port fills it in; 0 = no link).
const LIVE_PORT=__LIVE_PORT__;
if(LIVE_PORT){const h=location.hostname,a=document.getElementById("livelink");
  a.href=location.protocol+"//"+(h.includes(":")?"["+h+"]":h)+":"+LIVE_PORT+"/";a.hidden=false;}
const NS="http://www.w3.org/2000/svg";
const CH_COLORS=""" + repr(CHANNEL_COLORS) + r""";
const SVC_COLORS={acars:"#4aa8ff",cpdlc:"#f778ba",adsc:"#d29922"};
let win=24;

function el(tag,attrs,txt){const e=document.createElementNS(NS,tag);
  for(const k in attrs)e.setAttribute(k,attrs[k]);
  if(txt!=null)e.textContent=txt;return e;}
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,
  c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
function fmt(n){if(n>=1e6)return (n/1e6).toFixed(n<1e7?1:0)+"M";
  if(n>=1e3)return (n/1e3).toFixed(n<1e4?1:0)+"k";return ""+n;}
function mhz(f){return (f/1e6).toFixed(3);}
function hourLabel(h){const d=new Date(h*1000);
  return String(d.getUTCHours()).padStart(2,"0")+":00";}
function dayLabel(h){const d=new Date(h*1000);
  return (d.getUTCMonth()+1)+"/"+d.getUTCDate();}
function ago(sec){const s=Math.max(0,Math.floor(Date.now()/1000)-sec);
  if(s<90)return s+"s ago";if(s<5400)return Math.round(s/60)+"m ago";
  if(s<172800)return Math.round(s/3600)+"h ago";return Math.round(s/86400)+"d ago";}
function svg(host,h){host.innerHTML="";const s=el("svg",
  {viewBox:"0 0 1000 "+h,preserveAspectRatio:"none",height:h});
  host.appendChild(s);return s;}
function emptyMsg(host,t){host.innerHTML='<div class="empty">'+esc(t)+'</div>';}

function stackedBars(host,rows,keys,colors){
  if(!rows.length){emptyMsg(host,"no data in window");return;}
  const W=1000,H=200,padL=44,padB=22,padT=8;
  const s=svg(host,H);const iw=W-padL-6,ih=H-padB-padT;
  let max=0;rows.forEach(r=>{let t=0;keys.forEach(k=>t+=(r.vals[k]||0));
    if(t>max)max=t;});
  max=max||1;
  [0,.25,.5,.75,1].forEach(f=>{const y=padT+ih-ih*f;
    s.appendChild(el("line",{x1:padL,y1:y,x2:W,y2:y,class:"gl"}));
    s.appendChild(el("text",{x:padL-6,y:y+3,"text-anchor":"end",class:"ax"},
      fmt(Math.round(max*f))));});
  const bw=iw/rows.length, bar=Math.max(1,bw*0.82);
  rows.forEach((r,i)=>{const x=padL+i*bw+(bw-bar)/2;let acc=0;
    keys.forEach(k=>{const v=r.vals[k]||0;if(!v)return;
      const hh=ih*v/max,y=padT+ih-acc-hh;acc+=hh;
      const rc=el("rect",{x:x,y:y,width:bar,height:hh,fill:colors[k]||"#888",
        class:"bar"});rc.appendChild(el("title",null,
        r.label+" · "+k+": "+v));s.appendChild(rc);});
    if(rows.length<=26||i%Math.ceil(rows.length/16)===0)
      s.appendChild(el("text",{x:x+bar/2,y:H-6,"text-anchor":"middle",
        class:"ax"},r.tick));});
}
function lineChart(host,rows,color){
  if(!rows.length){emptyMsg(host,"no data in window");return;}
  const W=1000,H=150,padL=44,padB=22,padT=8;
  const s=svg(host,H);const iw=W-padL-6,ih=H-padB-padT;
  let max=0;rows.forEach(r=>{if(r.v>max)max=r.v;});max=max||1;
  [0,.5,1].forEach(f=>{const y=padT+ih-ih*f;
    s.appendChild(el("line",{x1:padL,y1:y,x2:W,y2:y,class:"gl"}));
    s.appendChild(el("text",{x:padL-6,y:y+3,"text-anchor":"end",class:"ax"},
      fmt(Math.round(max*f))));});
  const n=rows.length,step=n>1?iw/(n-1):0;
  const X=i=>padL+(n>1?i*step:iw/2), Y=v=>padT+ih-ih*v/max;
  let d="";rows.forEach((r,i)=>{d+=(i?"L":"M")+X(i).toFixed(1)+" "+Y(r.v).toFixed(1)+" ";});
  s.appendChild(el("path",{d:d,fill:"none",stroke:color,"stroke-width":2}));
  rows.forEach((r,i)=>{const c=el("circle",{cx:X(i),cy:Y(r.v),r:2.4,fill:color});
    c.appendChild(el("title",null,r.label+": "+r.v));s.appendChild(c);
    if(n<=26||i%Math.ceil(n/16)===0)
      s.appendChild(el("text",{x:X(i),y:H-6,"text-anchor":"middle",class:"ax"},r.tick));});
}
function ll(lat,lon){return Math.abs(lat).toFixed(1)+(lat<0?'S ':'N ')+
  Math.abs(lon).toFixed(1)+(lon<0?'W':'E');}
// Stations (squares) and the aircraft positions behind them (dots), drawn at
// the panel's own pixel size. Equirectangular around the data, scaled by the
// middle latitude; no tiles, so it works offline. A selected station (SEL)
// shows its spread as a ring and lines to the positions that placed it;
// everything else dims. Labels that would overlap are left off (the
// station's details stay in its tooltip), busiest stations first.
// #st=ID in the address selects a station, so a view can be shared.
let SEL=(location.hash.match(/st=([0-9A-Fa-f]{6})/)||[])[1]||null, MAPDATA=null;
// Background map from /map.json (Natural Earth, data/outlines.json), fetched
// once: land over water, lakes, state and country lines, and towns to read it by.
// Each line keeps its box, so only those in view are drawn, and the paths are
// rebuilt only when the view moves.
let OUT=null,OUTP=[],outKey="",outD={};
// fill, stroke, stroke width, in drawing order
const OUTSTYLE={land:["var(--land)","var(--coast)",1],lake:["var(--water)","var(--coast)",.8],
  state:["none","var(--state)",.8],border:["none","var(--border)",1.1]};
fetch("/map.json?v=__MAP_V__").then(r=>r.json()).then(d=>{const q=d.q;OUT={};
  for(const [k,ls] of Object.entries(d.layers))OUT[k]=ls.map(e=>{const p=new Float32Array(e.length);
    let x=e[0],y=e[1],b=[x,y,x,y];p[0]=x/q;p[1]=y/q;
    for(let i=2;i<e.length;i+=2){x+=e[i];y+=e[i+1];p[i]=x/q;p[i+1]=y/q;
      if(x<b[0])b[0]=x;if(x>b[2])b[2]=x;if(y<b[1])b[1]=y;if(y>b[3])b[3]=y;}
    return {p,b:b.map(v=>v/q)};});
  OUTP=(d.places||[]).map(p=>({lon:p[0]/q,lat:p[1]/q,r:p[2],n:p[3]}));
  if(MAPDATA)stationMap(...MAPDATA);}).catch(()=>{});
// The background, clipped to the frame, in a group the town names go into later.
function outlines(s,X,Y,lo0,la0,lo1,la1){
  const W=X(lo1),H=Y(la0),cp=el("clipPath",{id:"outclip"});
  cp.appendChild(el("rect",{x:0,y:0,width:W,height:H}));s.appendChild(cp);
  const g=el("g",{"clip-path":"url(#outclip)","pointer-events":"none"});s.appendChild(g);
  if(!OUT)return g;
  const key=[lo0,la0,lo1,la1,W,H].map(v=>v.toFixed(4)).join();
  if(key!==outKey){outKey=key;outD={};
    for(const k in OUTSTYLE){let d="";const ring=OUTSTYLE[k][0]!=="none";
      for(const l of OUT[k]||[]){const b=l.b,p=l.p;if(b[2]<lo0||b[0]>lo1||b[3]<la0||b[1]>la1)continue;
        d+="M"+X(p[0]).toFixed(1)+" "+Y(p[1]).toFixed(1);
        for(let i=2;i<p.length;i+=2)d+="L"+X(p[i]).toFixed(1)+" "+Y(p[i+1]).toFixed(1);
        if(ring)d+="Z";}
      outD[k]=d;}}
  for(const k in OUTSTYLE)if(outD[k])g.appendChild(el("path",{d:outD[k],fill:OUTSTYLE[k][0],
    "fill-rule":"evenodd",stroke:OUTSTYLE[k][1],"stroke-width":OUTSTYLE[k][2],"stroke-linejoin":"round"}));
  return g;
}
// Town names, under the data and clear of its labels (boxes): only the bigger
// towns as the view widens, and no more than 30.
function placeNames(g,X,Y,lo0,la0,lo1,la1,boxes){
  const W=X(lo1),H=Y(la0),span=Math.max(lo1-lo0,la1-la0);
  const maxr=span>40?2:span>20?4:span>10?6:span>5?7:8;
  const hit=(a,b)=>a[0]<b[0]+b[2]&&b[0]<a[0]+a[2]&&a[1]<b[1]+b[3]&&b[1]<a[1]+a[3];
  let n=0;
  for(const p of OUTP){
    if(p.r>maxr||p.lon<lo0||p.lon>lo1||p.lat<la0||p.lat>la1)continue;
    const x=X(p.lon),y=Y(p.lat),w=p.n.length*6.1+6,b=[x-3,y-7,w,13];
    if(b[0]<0||b[1]<0||b[0]+w>W||b[1]+13>H||boxes.some(q=>hit(b,q)))continue;
    boxes.push(b);
    g.appendChild(el("circle",{cx:x,cy:y,r:1.7,fill:"var(--place)"}));
    g.appendChild(el("text",{x:x+4,y:y+3.5,class:"plc"},p.n));
    if(++n>=30)break;
  }
}
if(SEL)SEL=SEL.toUpperCase();
function selectStation(id){SEL=SEL===id?null:id;
  history.replaceState(null,"",SEL?"#st="+SEL:location.pathname+location.search);
  if(MAPDATA)stationMap(...MAPDATA);markStationRows();}
function markStationRows(){document.querySelectorAll("#stations tr[data-st]").forEach(tr=>
  tr.classList.toggle("on",tr.dataset.st===SEL));}
function stationMap(host,all,pos){
  MAPDATA=[host,all,pos];
  const info=document.getElementById("stsel");
  const st=all.filter(x=>x.lat!=null);
  if(!st.length){emptyMsg(host,all.length?"no station has "+3+" different aircraft positions yet":
    "no aircraft position reports yet");info.textContent="";return;}
  if(SEL&&!st.some(x=>x.station===SEL))SEL=null;
  // only the reports near an estimated station: one receiver's aircraft
  // should not shrink another receiver's stations to a dot
  const near=(p,x)=>Math.hypot(p.lat-x.lat,(p.lon-x.lon)*Math.cos(x.lat*Math.PI/180))*111<600;
  pos=pos.filter(p=>st.some(x=>near(p,x)));
  const pts=st.map(s=>[s.lat,s.lon]).concat(pos.map(p=>[p.lat,p.lon]));
  let la0=Math.min(...pts.map(p=>p[0])),la1=Math.max(...pts.map(p=>p[0]));
  let lo0=Math.min(...pts.map(p=>p[1])),lo1=Math.max(...pts.map(p=>p[1]));
  const k=Math.cos((la0+la1)/2*Math.PI/180);
  const pad=Math.max(0.3,(la1-la0)*0.08,(lo1-lo0)*k*0.08);
  la0-=pad;la1+=pad;lo0-=pad/k;lo1+=pad/k;
  const W=Math.max(240,host.clientWidth||900);
  const H=Math.round(Math.max(280,Math.min(560,W*(la1-la0)/((lo1-lo0)*k))));
  const sc=Math.min(W/((lo1-lo0)*k),H/(la1-la0));
  const X=lo=>(lo-lo0)*k*sc+(W-(lo1-lo0)*k*sc)/2, Y=la=>(la1-la)*sc+(H-(la1-la0)*sc)/2;
  host.innerHTML="";const s=el("svg",{viewBox:"0 0 "+W+" "+H,width:W,height:H});host.appendChild(s);
  const bg=el("rect",{x:0,y:0,width:W,height:H,fill:"var(--water)",stroke:"var(--line)"});
  bg.addEventListener("click",()=>{if(SEL)selectStation(SEL);});s.appendChild(bg);
  // what the box shows, which is wider than the data one way or the other
  const lonAt=x=>lo0+(x-X(lo0))/(k*sc),latAt=y=>la1-(y-Y(la1))/sc;
  const view=[lonAt(0),latAt(H),lonAt(W),latAt(0)],bgG=outlines(s,X,Y,...view);
  const step=(lo1-lo0)>8?2:1;
  for(let g=Math.ceil(lo0);g<=lo1;g++){if(g%step)continue;
    s.appendChild(el("line",{x1:X(g),y1:0,x2:X(g),y2:H,class:"gl"}));
    s.appendChild(el("text",{x:X(g)+4,y:H-6,class:"mapax"},Math.abs(g)+(g<0?"W":"E")));}
  for(let g=Math.ceil(la0);g<=la1;g++){if(g%step)continue;
    s.appendChild(el("line",{x1:0,y1:Y(g),x2:W,y2:Y(g),class:"gl"}));
    s.appendChild(el("text",{x:4,y:Y(g)-4,class:"mapax"},Math.abs(g)+(g<0?"S":"N")));}
  const at={};st.forEach(x=>at[x.station]=x);
  const sel=SEL?at[SEL]:null;
  if(sel){
    if(sel.spread_km)s.appendChild(el("circle",{cx:X(sel.lon),cy:Y(sel.lat),r:sel.spread_km/111*sc,
      fill:"#4aa8ff","fill-opacity":.06,stroke:"#4aa8ff","stroke-opacity":.6,"stroke-width":1.5,"stroke-dasharray":"6 5"}));
    pos.forEach(p=>{if(p.gs!==SEL)return;
      s.appendChild(el("line",{x1:X(p.lon),y1:Y(p.lat),x2:X(sel.lon),y2:Y(sel.lat),
        stroke:"#4aa8ff","stroke-opacity":.5,"stroke-width":1}));});
  }
  pos.forEach(p=>{const mine=sel&&p.gs===SEL;
    const c=el("circle",{cx:X(p.lon),cy:Y(p.lat),r:mine?4:2.5,fill:mine?"#e6edf3":"#8b98a5",
      "fill-opacity":sel&&!mine?.2:.6});
    c.appendChild(el("title",null,p.icao+" → "+p.gs+" at "+ll(p.lat,p.lon)+" ("+p.src+")"));s.appendChild(c);});
  // labels: the selected station first, then the busiest; a label goes in the
  // first spot around its square that hits no other label or square
  const boxes=st.map(x=>[X(x.lon)-6,Y(x.lat)-6,12,12,x.station]);
  const hit=(a,b)=>a[0]<b[0]+b[2]&&b[0]<a[0]+a[2]&&a[1]<b[1]+b[3]&&b[1]<a[1]+a[3];
  const order=st.slice().sort((a,b)=>(b.station===SEL)-(a.station===SEL)||b.n_pos-a.n_pos);
  const labels=[];
  order.forEach(x=>{const cx=X(x.lon),cy=Y(x.lat),t=x.station+" ("+x.n_pos+")",w=t.length*7.3,h=13;
    const spots=[[10,-h/2],[-10-w,-h/2],[-w/2,-8-h],[-w/2,8],[10,-h-6],[10,6],[-10-w,-h-6],[-10-w,6]];
    for(const [dx,dy] of spots){const b=[cx+dx,cy+dy,w,h];
      if(b[0]<0||b[1]<0||b[0]+w>W||b[1]+h>H)continue;
      if(labels.some(l=>hit(b,l))||boxes.some(q=>q[4]!==x.station&&hit(b,q)))continue;
      labels.push(b);
      const tx=el("text",{x:b[0],y:b[1]+h-2,class:"maplbl","fill-opacity":sel&&x!==sel?.35:1},t);
      tx.addEventListener("click",e=>{e.stopPropagation();selectStation(x.station);});
      s.appendChild(tx);break;}});
  st.forEach(x=>{const cx=X(x.lon),cy=Y(x.lat),on=x.station===SEL;
    const r=el("rect",{x:cx-(on?7:5),y:cy-(on?7:5),width:on?14:10,height:on?14:10,rx:2,fill:on?"#e6edf3":"#4aa8ff",
      "fill-opacity":sel&&!on?.35:1,style:"cursor:pointer"});
    r.appendChild(el("title",null,x.station+": "+ll(x.lat,x.lon)+", ±"+x.spread_km+" km from "+
      x.n_pos+" positions ("+x.n_target+" from aircraft talking to it, "+x.n_heard+" from XID alternate lists)"));
    r.addEventListener("click",e=>{e.stopPropagation();selectStation(x.station);});
    s.appendChild(r);});
  placeNames(bgG,X,Y,...view,boxes.concat(labels));
  info.textContent=sel?sel.station+": "+ll(sel.lat,sel.lon)+", ±"+sel.spread_km+" km from "+sel.n_pos+
    " positions ("+sel.n_target+" from aircraft talking to it, "+sel.n_heard+" from XID alternate lists). Click again to clear."
    :st.length+" stations placed, "+pos.length+" positions";
}
let resizeTimer=null;
window.addEventListener("resize",()=>{clearTimeout(resizeTimer);
  resizeTimer=setTimeout(()=>{if(MAPDATA)stationMap(...MAPDATA);},200);});
function card(k,v,sub,hot){return '<div class="card'+(hot?' hot':'')+
  '"><div class="k">'+k+'</div><div class="v">'+v+
  (sub?' <small>'+sub+'</small>':'')+'</div></div>';}
function ticks(rows){
  const span=rows.length?rows[rows.length-1].hour-rows[0].hour:0;
  const byDay=span>36*3600;
  rows.forEach(r=>r._tick=byDay?dayLabel(r.hour):hourLabel(r.hour));
}

async function load(){
  const st=document.getElementById("status");
  try{
    const r=await fetch("/api/vdl2"+(win?("?hours="+win):""));
    const d=await r.json();
    if(d.error){document.getElementById("cards").innerHTML="";
      emptyMsg(document.getElementById("frames"),d.error);
      st.innerHTML='<span class="dot" style="background:var(--warn)"></span>'+esc(d.error);
      return;}
    render(d);
    st.innerHTML='<span class="dot"></span>updated '+new Date().toLocaleTimeString();
  }catch(e){st.innerHTML='<span class="dot" style="background:var(--warn)"></span>fetch failed';}
}

function render(d){
  const t=d.totals,m=t.messages;
  document.getElementById("cards").innerHTML=
    card("Frames",fmt(t.frames),"from "+fmt(t.bursts)+" bursts")+
    card("Aircraft",fmt(t.aircraft),"distinct ICAO")+
    card("Ground stations",fmt(t.stations),null)+
    card("ACARS msgs",fmt(m.acars),null)+
    card("CPDLC",fmt(m.cpdlc),"clearances",true)+
    card("ADS-C",fmt(m.adsc),"reports")+
    card("Positions",fmt(Object.values(d.pos_sources||{}).reduce((a,b)=>a+b,0)),
      ["text","fix","xid","adsc"].filter(k=>(d.pos_sources||{})[k]).map(k=>k+" "+d.pos_sources[k]).join(" · "))+
    card("Span",d.span.hours+"h",dayLabel(d.span.start)+"–"+dayLabel(d.span.end));

  const freqs=d.channels.map(c=>String(c.freq));
  const colors={};freqs.forEach((f,i)=>colors[mhz(+f)]=CH_COLORS[i%CH_COLORS.length]);
  const leg=document.getElementById("ch-legend");leg.innerHTML="";
  freqs.forEach(f=>{const sp=document.createElement("span");
    sp.innerHTML='<i style="background:'+colors[mhz(+f)]+'"></i>'+mhz(+f);leg.appendChild(sp);});
  ticks(d.hours);
  stackedBars(document.getElementById("frames"),d.hours.map(h=>{const vals={};
    freqs.forEach(f=>vals[mhz(+f)]=h.ch[f]||0);
    return {label:dayLabel(h.hour)+" "+hourLabel(h.hour),tick:h._tick,vals:vals};}),
    freqs.map(f=>mhz(+f)),colors);

  const ct=document.getElementById("chans");
  if(!d.channels.length)emptyMsg(ct,"no channels");
  else ct.innerHTML='<table><tr><th>Channel, MHz</th><th>Bursts</th><th>Frames</th>'+
    '<th>Frames per burst</th><th>SNR p10</th><th>p50</th><th>p90, dB</th></tr>'+
    d.channels.map(c=>'<tr><td class="mono">'+mhz(c.freq)+'</td><td>'+fmt(c.bursts)+
      '</td><td>'+fmt(c.frames)+'</td><td>'+(c.bursts?(100*c.frames/c.bursts).toFixed(0)+'%':'–')+
      '</td><td>'+(c.snr_p10??'–')+'</td><td>'+(c.snr_p50??'–')+'</td><td>'+(c.snr_p90??'–')+
      '</td></tr>').join("")+'</table>';

  const svcKeys=["acars","cpdlc","adsc"];
  const sl=document.getElementById("svc-legend");sl.innerHTML="";
  svcKeys.forEach(k=>{const sp=document.createElement("span");
    sp.innerHTML='<i style="background:'+SVC_COLORS[k]+'"></i>'+k.toUpperCase();sl.appendChild(sp);});
  stackedBars(document.getElementById("svc"),d.hours.map(h=>({label:hourLabel(h.hour),
    tick:h._tick,vals:{acars:h.acars,cpdlc:h.cpdlc,adsc:h.adsc}})),svcKeys,SVC_COLORS);

  lineChart(document.getElementById("achours"),d.hours.map(h=>({tick:h._tick,
    label:hourLabel(h.hour),v:h.aircraft})),"#3fb950");

  const est={};(d.station_est||[]).forEach(s=>est[s.station]=s);
  const sh=document.getElementById("stations");
  if(!d.stations.length)emptyMsg(sh,"no ground stations");
  else{const top=d.stations[0].count||1;
    sh.innerHTML='<table><tr><th>Station</th><th></th><th>Frames</th><th>Est. position</th><th>Last heard</th></tr>'+
    d.stations.map(g=>{const e=est[g.station];
      const pos=!e?'–':e.lat==null?'<span style="color:var(--dim)">too few reports ('+e.n_pos+')</span>':
        ll(e.lat,e.lon)+' <span style="color:var(--dim)">±'+e.spread_km+' km, '+e.n_pos+' positions</span>';
      return '<tr class="strow" data-st="'+esc(g.station)+'"><td class="mono">'+esc(g.station)+'</td><td style="width:30%">'+
      '<div style="height:9px;border-radius:2px;background:#2f6feb;width:'+
      Math.max(1,100*g.count/top).toFixed(0)+'%"></div></td><td>'+fmt(g.count)+'</td><td>'+pos+'</td><td>'+
      dayLabel(g.last)+' '+hourLabel(g.last)+'</td></tr>';}).join("")+'</table>';}
  sh.querySelectorAll("tr[data-st]").forEach(tr=>tr.addEventListener("click",()=>selectStation(tr.dataset.st)));
  stationMap(document.getElementById("stmap"),d.station_est||[],d.positions||[]);
  markStationRows();
  const at=document.getElementById("aircraft");
  if(!d.aircraft.length)emptyMsg(at,"no aircraft");
  else at.innerHTML='<table><tr><th>ICAO</th><th>Frames</th><th>Best SNR, dB</th><th>Last heard</th></tr>'+
    d.aircraft.map(a=>'<tr><td class="mono">'+esc(a.icao)+'</td><td>'+fmt(a.count)+'</td><td>'+
      a.best_snr.toFixed(1)+'</td><td>'+dayLabel(a.last)+' '+hourLabel(a.last)+'</td></tr>').join("")+
    '</table>';

  const xh=document.getElementById("xid");
  if(!d.xid.length)emptyMsg(xh,"no XID frames in window");
  else xh.innerHTML='<table><tr><th>Time (UTC)</th><th>ICAO</th><th>XID</th><th>Station</th>'+
    '<th>Destination</th><th>Position</th></tr>'+d.xid.map(x=>{
      const tm=new Date(x.t*1000).toISOString().slice(5,19).replace("T"," ");
      const stn=(x.from_gs?esc(x.from_gs)+' → ':'')+esc(x.gs);
      const pos=x.lat==null?'–':Math.abs(x.lat).toFixed(1)+(x.lat<0?'S ':'N ')+
        Math.abs(x.lon).toFixed(1)+(x.lon<0?'W':'E')+(x.alt!=null?' · '+fmt(x.alt)+' ft':'');
      return '<tr><td class="mono">'+tm+'</td><td class="mono">'+esc(x.icao)+'</td><td>'+
        esc(x.kind||'XID')+'</td><td class="mono">'+stn+'</td><td class="mono">'+esc(x.airport||'–')+
        '</td><td>'+pos+'</td></tr>';}).join("")+'</table>';

  const f=document.getElementById("freshness");
  if(d.meta.last_run)f.textContent=" Last rollup "+ago(d.meta.last_run)+".";
}

document.querySelectorAll("#win button").forEach(b=>{
  b.onclick=()=>{document.querySelectorAll("#win button").forEach(x=>
    x.classList.remove("on"));b.classList.add("on");
    win=+b.dataset.h;load();};});
load();
setInterval(load,30000);
</script>
</body></html>
"""
