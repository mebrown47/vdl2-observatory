# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""
The Messages page: per-tail history, the CPDLC log and ADS-C, from the
messages, cpdlc_log and adsc_log tables rollup.py writes. Adapted from
iridium-sniffer's Aviation tab (observatory/trends_server.py).
"""

import os
import sqlite3


def connect_ro(path):
    if not os.path.exists(path):
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)


def build_messages(path, tail=None, limit=200):
    con = connect_ro(path)
    if con is None:
        return {"error": "no database yet — run rollup.py first"}
    con.row_factory = sqlite3.Row
    try:
        have = {r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"messages", "cpdlc_log", "adsc_log"} <= have:
            return {"error": "no messages yet — run rollup.py first"}

        def rows(sql, *a):
            return con.execute(sql, a).fetchall()

        span = rows("SELECT MIN(t) a, MAX(t) b FROM messages")[0]
        stats = {
            "messages": rows("SELECT COUNT(*) c FROM messages")[0]["c"],
            "tails": rows("SELECT COUNT(DISTINCT reg) c FROM messages "
                          "WHERE reg!=''")[0]["c"],
            "cpdlc": rows("SELECT COUNT(*) c FROM cpdlc_log")[0]["c"],
            "adsc": rows("SELECT COUNT(*) c FROM messages "
                         "WHERE has_adsc=1")[0]["c"],
            "adsc_pos": rows("SELECT COUNT(*) c FROM adsc_log "
                             "WHERE has_pos=1")[0]["c"],
            "span_start": span["a"], "span_end": span["b"],
        }

        tails = [dict(r) for r in rows(
            "SELECT reg, COUNT(*) n, MAX(t) last_t, MAX(flt) flt, "
            "SUM(has_cpdlc) cpdlc, SUM(has_adsc) adsc FROM messages "
            "WHERE reg!='' GROUP BY reg ORDER BY n DESC LIMIT 120")]

        where = "WHERE reg=?" if tail else ""
        args = (tail,) if tail else ()
        msgs = [dict(r) for r in rows(
            f"SELECT t,reg,flt,dir,lbl,freq,txt,has_cpdlc,has_adsc FROM messages "
            f"{where} ORDER BY t DESC LIMIT ?", *args, int(limit))]
        cpdlc = [dict(r) for r in rows(
            f"SELECT t,reg,flt,dir,txt,summary,dec FROM cpdlc_log "
            f"{where} ORDER BY t DESC LIMIT ?", *args, 100)]
        # Position reports first (they're the rare prize), then newest.
        adsc = [dict(r) for r in rows(
            f"SELECT t,reg,flt,dir,txt,kinds,summary,has_pos,lat,lon,alt,dec "
            f"FROM adsc_log {where} ORDER BY has_pos DESC, t DESC LIMIT ?",
            *args, 100)]

        return {"stats": stats, "tails": tails, "messages": msgs,
                "cpdlc": cpdlc, "adsc": adsc, "tail": tail or ""}
    finally:
        con.close()


MESSAGES_PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VDL2 Observatory — Messages</title>
<style>
  :root{
    --bg:#0e1116; --panel:#161b22; --panel2:#1c232c; --line:#2b333d;
    --fg:#e6edf3; --dim:#8b98a5; --accent:#4aa8ff; --good:#3fb950;
    --warn:#d29922; --hot:#f778ba;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
    font:14px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
  header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;
    padding:16px 22px;border-bottom:1px solid var(--line);background:var(--panel)}
  header h1{font-size:18px;margin:0;font-weight:650;letter-spacing:.2px}
  header .sub{color:var(--dim);font-size:12.5px}
  header .spacer{flex:1}
  header .status{color:var(--dim);font-size:12px}
  header .dot{display:inline-block;width:8px;height:8px;border-radius:50%;
    background:var(--good);margin-right:5px;vertical-align:middle}
  .nav{display:flex;gap:4px}
  .nav a{color:var(--dim);text-decoration:none;font-size:13px;padding:4px 11px;
    border-radius:6px;border:1px solid transparent}
  .nav a:hover{color:var(--fg)}
  .nav a.on{color:var(--fg);background:var(--panel2);border-color:var(--line)}
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
  .grid{display:grid;grid-template-columns:300px 1fr;gap:14px;align-items:start}
  @media(max-width:820px){.grid{grid-template-columns:minmax(0,1fr)}}
  .grid>*{min-width:0}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;
    padding:14px 16px;margin-bottom:14px}
  .panel h2{font-size:13px;margin:0 0 10px;font-weight:600;
    display:flex;justify-content:space-between;align-items:center;gap:8px}
  .panel h2 .hint{color:var(--dim);font-weight:400;font-size:11.5px}
  .tails{max-height:70vh;overflow:auto}
  .tail{display:flex;justify-content:space-between;align-items:center;gap:8px;
    padding:7px 9px;border-radius:7px;cursor:pointer;font-size:13px}
  .tail:hover{background:var(--panel2)}
  .tail.on{background:#182634;border:1px solid var(--accent)}
  .tail .reg{font-weight:600;font-variant-numeric:tabular-nums}
  .tail .meta{color:var(--dim);font-size:11.5px}
  .tail .badge{font-size:10px;padding:1px 6px;border-radius:20px;margin-left:4px}
  .badge.cp{background:#3d1f33;color:var(--hot)}
  .badge.ad{background:#3a3020;color:var(--warn)}
  .n{color:var(--dim);font-variant-numeric:tabular-nums}
  input.search{width:100%;background:var(--panel2);border:1px solid var(--line);
    color:var(--fg);border-radius:7px;padding:7px 10px;font-size:13px;
    margin-bottom:8px}
  table{width:100%;border-collapse:collapse;font-size:12.5px}
  th{text-align:left;color:var(--dim);font-weight:500;font-size:11px;
    text-transform:uppercase;letter-spacing:.5px;padding:6px 8px;
    border-bottom:1px solid var(--line);position:sticky;top:0;
    background:var(--panel)}
  td{padding:6px 8px;border-bottom:1px solid #1b2129;vertical-align:top;
    white-space:nowrap}
  td.body{white-space:normal;overflow-wrap:anywhere}
  tr:hover td{background:var(--panel2)}
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  .dir{font-size:10px;padding:1px 5px;border-radius:4px}
  .dir.DL{background:#12261a;color:var(--good)}
  .dir.UL{background:#241a2e;color:#a371f7}
  .tbl-wrap{max-height:60vh;overflow:auto}
  .cpd{border-left:3px solid var(--hot);padding:9px 12px;margin:8px 0;
    background:#161019;border-radius:0 8px 8px 0}
  .cpd .top{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
  .cpd .reg{font-weight:600}
  .cpd .flt{color:var(--accent)}
  .cpd .ts{color:var(--dim);font-size:11.5px;margin-left:auto}
  .cpd .sum{margin-top:5px;font-family:ui-monospace,SFMono-Regular,Menlo,
    monospace;font-size:12px;color:#e6d7ef}
  .cpd .txt{margin-top:4px;color:var(--dim);font-size:12px}
  .cpd details{margin-top:6px}
  .cpd summary{color:var(--dim);font-size:11.5px;cursor:pointer}
  .cpd pre{white-space:pre-wrap;word-break:break-word;font-size:11px;
    color:var(--dim);background:#0d0a10;padding:8px;border-radius:6px;
    margin:6px 0 0;max-height:240px;overflow:auto}
  .empty{color:var(--dim);padding:26px;text-align:center;font-size:13px}
  /* ADS-C entries reuse the .cpd card shape in amber; a position report
     switches to green — that colour shift is the track-replay tripwire. */
  .ad{border-left:3px solid var(--warn);padding:9px 12px;margin:8px 0;
    background:#17130c;border-radius:0 8px 8px 0}
  .ad.pos{border-left-color:var(--good);background:#0d1a10}
  .ad .top{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
  .ad .reg{font-weight:600}
  .ad .flt{color:var(--accent)}
  .ad .ts{color:var(--dim);font-size:11.5px;margin-left:auto}
  .ad .sum{margin-top:5px;font-family:ui-monospace,SFMono-Regular,Menlo,
    monospace;font-size:12px;color:#efe2cd}
  .ad.pos .sum{color:#c6f6d5}
  .ad .txt{margin-top:4px;color:var(--dim);font-size:12px}
  .ad details{margin-top:6px}
  .ad summary{color:var(--dim);font-size:11.5px;cursor:pointer}
  .ad pre{white-space:pre-wrap;word-break:break-word;font-size:11px;
    color:var(--dim);background:#0b0d0a;padding:8px;border-radius:6px;
    margin:6px 0 0;max-height:240px;overflow:auto}
  .kind{font-size:10px;padding:1px 6px;border-radius:20px;
    background:#3a3020;color:var(--warn)}
  .kind.rep{background:#12261a;color:var(--good)}
  .banner{border:1px solid var(--line);border-radius:9px;padding:11px 14px;
    margin-bottom:12px;font-size:12.5px;color:var(--dim);background:var(--panel2)}
  .banner.hit{border-color:var(--good);background:#0d1a10;color:#c6f6d5}
  .banner b{color:var(--fg)}
  .banner.hit b{color:var(--good)}
  .tabs{display:flex;gap:4px;margin-bottom:10px}
  .tabs button{background:var(--panel2);color:var(--dim);border:1px solid
    var(--line);padding:5px 12px;border-radius:7px;cursor:pointer;font-size:12.5px}
  .tabs button.on{color:var(--fg);border-color:var(--accent);background:#182634}
  a{color:var(--accent)}
</style></head>
<body>
<header>
  <h1>VDL2 Observatory</h1>
  <nav class="nav"><a href="/">Overview</a><a href="/messages" class="on">Messages</a></nav>
  <span class="sub">decoded aircraft traffic — per-tail history &amp; CPDLC log</span>
  <span class="spacer"></span>
  <span class="status" id="status"><span class="dot"></span>loading…</span>
</header>
<main>
  <div class="cards" id="cards"></div>
  <div class="tabs" id="tabs">
    <button data-v="tails" class="on">Per-tail history</button>
    <button data-v="cpdlc">CPDLC catch log</button>
    <button data-v="adsc">ADS-C contracts</button>
  </div>

  <div id="view-tails">
    <div class="grid">
      <div class="panel">
        <h2>Aircraft <span class="hint" id="tailcount"></span></h2>
        <input class="search" id="tailsearch" placeholder="filter tails…">
        <div class="tails" id="tails"></div>
      </div>
      <div class="panel">
        <h2 id="msgtitle">Messages <span class="hint">select a tail, or newest across all</span></h2>
        <div class="tbl-wrap">
          <table><thead><tr><th>Time (UTC)</th><th>Tail</th><th>Flight</th>
            <th>MHz</th><th>Dir</th><th>Lbl</th><th>Text / type</th></tr></thead>
            <tbody id="msgrows"></tbody></table>
        </div>
      </div>
    </div>
  </div>

  <div id="view-cpdlc" style="display:none">
    <div class="panel">
      <h2>CPDLC catch log <span class="hint">every controller–pilot data-link
        message decoded</span></h2>
      <div id="cpdlclist"></div>
    </div>
  </div>

  <div id="view-adsc" style="display:none">
    <div class="panel">
      <h2>ADS-C log <span class="hint">contract negotiation &amp; position
        reports</span></h2>
      <div id="adscbanner"></div>
      <div id="adsclist"></div>
    </div>
  </div>

  <p style="color:var(--dim);font-size:11.5px;margin:6px 2px 30px">
    Times UTC. A→G is aircraft to ground, G→A ground to aircraft.
    From the vdl2-sniffer archive via rollup.py.
    <span id="freshness"></span>
  </p>
</main>
<script>
let TAIL=null, VIEW="tails", DATA=null;

function fmt(n){if(n>=1e6)return (n/1e6).toFixed(1)+"M";
  if(n>=1e3)return (n/1e3).toFixed(1)+"k";return ""+n;}
// Every DB timestamp is epoch SECONDS. Multiply here, at the render
// boundary, and nowhere else.
function ts(sec){const d=new Date(sec*1000);
  const p=x=>String(x).padStart(2,"0");
  return p(d.getUTCMonth()+1)+"/"+p(d.getUTCDate())+" "+
    p(d.getUTCHours())+":"+p(d.getUTCMinutes())+":"+p(d.getUTCSeconds());}
function esc(s){return (s==null?"":""+s).replace(/[&<>]/g,
  c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));}
// The archive's dir is UL for aircraft to ground (iridium-sniffer's
// convention), the reverse of ACARS's own "downlink"; show it plainly.
function dirb(d){return '<span class="dir '+esc(d)+'">'+
  (d==="UL"?"A→G":d==="DL"?"G→A":esc(d))+'</span>';}
function card(k,v,sub,hot){return '<div class="card'+(hot?' hot':'')+
  '"><div class="k">'+k+'</div><div class="v">'+v+
  (sub?' <small>'+sub+'</small>':'')+'</div></div>';}

async function load(){
  const st=document.getElementById("status");
  try{
    const q=TAIL?("?tail="+encodeURIComponent(TAIL)):"";
    const r=await fetch("/api/messages"+q);
    DATA=await r.json();
    if(DATA.error){document.getElementById("cards").innerHTML="";
      document.getElementById("tails").innerHTML=
        '<div class="empty">'+esc(DATA.error)+'</div>';
      st.innerHTML='<span class="dot" style="background:var(--warn)"></span>'
        +esc(DATA.error);return;}
    render();
    st.innerHTML='<span class="dot"></span>updated '+
      new Date().toLocaleTimeString();
  }catch(e){st.innerHTML='<span class="dot" style="background:var(--warn)">'
    +'</span>fetch failed';}
}

function render(){
  const s=DATA.stats;
  document.getElementById("cards").innerHTML=
    card("Messages",fmt(s.messages),null)+
    card("Aircraft",fmt(s.tails),"tails seen")+
    card("CPDLC",fmt(s.cpdlc),"clearances",true)+
    card("ADS-C",fmt(s.adsc),(s.adsc_pos?s.adsc_pos+" w/ position"
      :"contracts only"))+
    card("Span",s.span_start?ts(s.span_start).split(" ")[0]+"–"+
      ts(s.span_end).split(" ")[0]:"—","UTC");
  renderTails();
  renderMsgs();
  renderCpdlc();
  renderAdsc();
  document.getElementById("tailcount").textContent=
    DATA.tails.length+" shown";
}

function renderTails(){
  const host=document.getElementById("tails");
  const filt=(document.getElementById("tailsearch").value||"").toUpperCase();
  const list=DATA.tails.filter(t=>!filt||t.reg.toUpperCase().includes(filt));
  if(!list.length){host.innerHTML='<div class="empty">no tails</div>';return;}
  host.innerHTML="";
  const all=document.createElement("div");
  all.className="tail"+(TAIL?"":" on");
  all.innerHTML='<span class="reg">All aircraft</span>'+
    '<span class="meta">newest across fleet</span>';
  all.onclick=()=>{TAIL=null;load();};
  host.appendChild(all);
  list.forEach(t=>{const el=document.createElement("div");
    el.className="tail"+(TAIL===t.reg?" on":"");
    el.innerHTML='<span class="reg">'+esc(t.reg)+
      (t.cpdlc?'<span class="badge cp">CPDLC</span>':'')+
      (t.adsc?'<span class="badge ad">ADS-C</span>':'')+'</span>'+
      '<span class="meta"><span class="n">'+t.n+'</span> · '+
      ts(t.last_t).split(" ")[1]+'</span>';
    el.onclick=()=>{TAIL=t.reg;load();};
    host.appendChild(el);});
}

function renderMsgs(){
  const host=document.getElementById("msgrows");
  document.getElementById("msgtitle").innerHTML="Messages "+
    (TAIL?'<span class="hint">'+esc(TAIL)+'</span>':
      '<span class="hint">newest across all tails</span>');
  if(!DATA.messages.length){host.innerHTML=
    '<tr><td colspan="7" class="empty">no messages</td></tr>';return;}
  host.innerHTML=DATA.messages.map(m=>{
    let body=esc(m.txt);
    if(m.has_cpdlc)body='<span style="color:var(--hot)">◆ CPDLC</span> '+body;
    else if(m.has_adsc)body='<span style="color:var(--warn)">◆ ADS-C</span> '+body;
    else if(!m.txt)body='<span class="n">—</span>';
    return '<tr><td class="mono n">'+ts(m.t)+'</td><td class="mono">'+
      esc(m.reg)+'</td><td>'+esc(m.flt)+'</td><td class="mono n">'+
      (m.freq?(m.freq/1e6).toFixed(3):"")+'</td><td>'+dirb(m.dir)+
      '</td><td class="mono">'+esc(m.lbl)+
      '</td><td class="body">'+body+'</td></tr>';}).join("");
}

function renderCpdlc(){
  const host=document.getElementById("cpdlclist");
  if(!DATA.cpdlc.length){host.innerHTML='<div class="empty">'+
    'No CPDLC captured yet in this window — clearances are bursty. '+
    'The log fills as aircraft exchange controller messages.</div>';return;}
  host.innerHTML=DATA.cpdlc.map(c=>{
    let dj="";try{dj=JSON.stringify(JSON.parse(c.dec),null,2);}
    catch(e){dj=c.dec||"";}
    return '<div class="cpd"><div class="top">'+
      '<span class="reg">'+esc(c.reg||"—")+'</span>'+
      (c.flt?'<span class="flt">'+esc(c.flt)+'</span>':'')+
      dirb(c.dir)+
      '<span class="ts">'+ts(c.t)+' UTC</span></div>'+
      (c.summary?'<div class="sum">'+esc(c.summary)+'</div>':'')+
      (c.txt?'<div class="txt">'+esc(c.txt)+'</div>':'')+
      (dj?'<details><summary>full decode</summary><pre>'+esc(dj)+
        '</pre></details>':'')+'</div>';}).join("");
}

function renderAdsc(){
  const host=document.getElementById("adsclist");
  const ban=document.getElementById("adscbanner");
  const list=DATA.adsc||[];
  const nPos=DATA.stats.adsc_pos||0;

  ban.className="banner"+(nPos?" hit":"");
  ban.innerHTML=nPos
    ? '<b>Position reports arriving.</b> '+nPos+' ADS-C message'+
      (nPos===1?"":"s")+' carrying lat/lon decoded — enough to plot a track.'
    : '<b>Contracts only so far.</b> '+list.length+' ADS-C message'+
      (list.length===1?"":"s")+' captured, all contract negotiation — the '+
      'ground station arming reports. None carry coordinates yet. A position '+
      'report (a <code>basic_report</code> tag with lat/lon) turns this '+
      'banner green.';

  if(!list.length){host.innerHTML='<div class="empty">'+
    'No ADS-C captured yet.</div>';
    return;}
  host.innerHTML=list.map(a=>{
    let dj="";try{dj=JSON.stringify(JSON.parse(a.dec),null,2);}
    catch(e){dj=a.dec||"";}
    const kinds=(a.kinds||"").split(",").filter(Boolean).map(k=>
      '<span class="kind'+(a.has_pos?' rep':'')+'">'+esc(k)+'</span>').join(" ");
    const pos=a.has_pos
      ? '<div class="sum">◆ '+a.lat.toFixed(4)+', '+a.lon.toFixed(4)+
        (a.alt!=null?' @ '+fmt(a.alt)+' ft':'')+'</div>'
      : '';
    return '<div class="ad'+(a.has_pos?' pos':'')+'"><div class="top">'+
      '<span class="reg">'+esc(a.reg||"—")+'</span>'+
      (a.flt?'<span class="flt">'+esc(a.flt)+'</span>':'')+
      dirb(a.dir)+kinds+
      '<span class="ts">'+ts(a.t)+' UTC</span></div>'+pos+
      (a.summary?'<div class="sum">'+esc(a.summary)+'</div>':'')+
      (a.txt?'<div class="txt">'+esc(a.txt)+'</div>':'')+
      (dj?'<details><summary>full decode</summary><pre>'+esc(dj)+
        '</pre></details>':'')+'</div>';}).join("");
}

document.getElementById("tailsearch").oninput=renderTails;
const VIEWS=["tails","cpdlc","adsc"];
document.querySelectorAll("#tabs button").forEach(b=>{
  b.onclick=()=>{document.querySelectorAll("#tabs button").forEach(x=>
    x.classList.remove("on"));b.classList.add("on");VIEW=b.dataset.v;
    VIEWS.forEach(v=>{document.getElementById("view-"+v).style.display=
      VIEW===v?"":"none";});};});
load();
setInterval(load,30000);
</script>
</body></html>
"""
