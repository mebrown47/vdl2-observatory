# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""
VDL2 Observatory — the Search page (/search), drawn from /api/search
(search.py). Ported from iridium-observatory's Search tab: the address,
channel and links to the Flights page are VDL2's.
"""

SEARCH_PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VDL2 Search</title>
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
  .nav{display:flex;gap:4px;flex-wrap:wrap}
  .nav a{color:var(--dim);text-decoration:none;font-size:13px;padding:4px 11px;
    border-radius:6px;border:1px solid transparent}
  .nav a:hover{color:var(--fg)}
  .nav a.on{color:var(--fg);background:var(--panel2);border-color:var(--line)}
  .nav a[hidden]{display:none}
  main{padding:18px 22px;max-width:1400px;margin:0 auto}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;
    padding:14px 16px;margin-bottom:14px}
  .panel h2{font-size:13px;margin:0 0 10px;font-weight:600;
    display:flex;justify-content:space-between;align-items:center;gap:8px}
  .panel h2 .hint{color:var(--dim);font-weight:400;font-size:11.5px}
  form.filters{display:grid;gap:10px 12px;align-items:end;
    grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
  form.filters label{display:flex;flex-direction:column;gap:4px;color:var(--dim);
    font-size:11px;text-transform:uppercase;letter-spacing:.5px}
  form.filters label.wide{grid-column:span 2}
  @media(max-width:520px){form.filters label.wide{grid-column:auto}}
  input,select{background:var(--panel2);border:1px solid var(--line);color:var(--fg);
    border-radius:7px;padding:7px 9px;font-size:13px;font-family:inherit;
    text-transform:none;letter-spacing:0;width:100%;min-width:0}
  input:focus,select:focus{outline:none;border-color:var(--accent)}
  label.check{flex-direction:row!important;align-items:center;gap:7px!important;
    padding-bottom:8px;text-transform:none!important;letter-spacing:0!important;
    font-size:12.5px!important}
  label.check input{width:auto}
  .btns{display:flex;gap:8px}
  button{background:var(--panel2);color:var(--fg);border:1px solid var(--line);
    padding:7px 14px;border-radius:7px;cursor:pointer;font-size:13px;font-family:inherit}
  button:hover{border-color:var(--accent)}
  button.primary{background:#16324f;border-color:var(--accent)}
  button:disabled{opacity:.4;cursor:default}
  .quick{display:flex;gap:6px;flex-wrap:wrap;margin-top:12px;align-items:center}
  .quick span{color:var(--dim);font-size:12px;margin-right:2px}
  .quick button{padding:4px 10px;font-size:12px;color:var(--dim)}
  .quick button:hover{color:var(--fg)}
  .summary{display:flex;gap:18px;flex-wrap:wrap;align-items:baseline;margin-bottom:10px}
  .summary .big{font-size:22px;font-weight:600}
  .summary .dim{color:var(--dim);font-size:12.5px}
  .summary .spacer{flex:1}
  .summary a{color:var(--accent);font-size:12.5px;text-decoration:none}
  .grid{display:grid;grid-template-columns:1fr 230px 230px 190px;gap:14px;align-items:start}
  @media(max-width:1100px){.grid{grid-template-columns:1fr 1fr 1fr}.grid .days{grid-column:1/-1}}
  @media(max-width:620px){.grid{grid-template-columns:1fr}}
  svg{display:block;width:100%;height:110px}
  .bar{fill:var(--accent);opacity:.8}
  .bar:hover{opacity:1}
  .axis{display:flex;justify-content:space-between;color:var(--dim);font-size:10.5px;margin-top:4px}
  .facet{display:flex;justify-content:space-between;gap:8px;padding:4px 7px;
    border-radius:6px;cursor:pointer;font-size:12.5px}
  .facet:hover{background:var(--panel2)}
  .facet .k{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  .facet .n{color:var(--dim);font-variant-numeric:tabular-nums}
  .tbl-wrap{overflow-x:auto}
  table{width:100%;border-collapse:collapse;font-size:12.5px}
  th{text-align:left;color:var(--dim);font-weight:500;font-size:11px;
    text-transform:uppercase;letter-spacing:.5px;padding:6px 8px;
    border-bottom:1px solid var(--line)}
  td{padding:6px 8px;border-bottom:1px solid #1b2129;vertical-align:top}
  tr:hover td{background:var(--panel2)}
  td.ts{white-space:nowrap;color:var(--dim);font-variant-numeric:tabular-nums}
  td.reg{white-space:nowrap}
  td.reg a{color:var(--fg);font-weight:600;text-decoration:none}
  td.reg a:hover{color:var(--accent)}
  td.reg .flt{color:var(--accent);font-size:11.5px}
  td.reg .hex{color:var(--dim);font-size:11px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  td.reg .hex a{color:var(--dim);font-weight:400}
  td.reg .hex a:hover{color:var(--accent)}
  td.ch{white-space:nowrap;color:var(--dim);font-variant-numeric:tabular-nums}
  td.lbl{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;white-space:nowrap}
  td.txt{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;
    white-space:pre-wrap;word-break:break-word;min-width:260px}
  td.txt .more{color:var(--accent);cursor:pointer;font-family:inherit}
  td.txt .sum{color:#e6d7ef;margin-top:4px}
  .dir{font-size:10px;padding:1px 5px;border-radius:4px}
  .dir.DL{background:#12261a;color:var(--good)}
  .dir.UL{background:#241a2e;color:#a371f7}
  .badge{font-size:10px;padding:1px 6px;border-radius:20px;margin-left:4px;white-space:nowrap}
  .badge.cp{background:#3d1f33;color:var(--hot)}
  .badge.ad{background:#3a3020;color:var(--warn)}
  .empty{color:var(--dim);padding:26px;text-align:center;font-size:13px}
  .err{color:#ff7b72}
  .pager{display:flex;gap:10px;align-items:center;justify-content:flex-end;margin-top:10px;
    color:var(--dim);font-size:12.5px}
  mark{background:#4a3b0b;color:inherit;border-radius:2px}
</style></head>
<body>
<header>
  <h1>VDL2 Observatory</h1>
  <nav class="nav"><a href="/">Overview</a><a href="/messages">Messages</a><a href="/search" class="on">Search</a><a href="/flights">Flights</a><a href="/coverage">Coverage</a><a id="livelink" href="#" hidden>Live</a></nav>
  <span class="sub">every stored ACARS message, by aircraft, text, label, channel and date</span>
  <span class="spacer"></span>
  <span class="status" id="status">loading…</span>
</header>
<main>
  <div class="panel">
    <form class="filters" id="f" autocomplete="off">
      <label>Aircraft<input name="ac" placeholder="registration, flight or address"></label>
      <label class="wide">Text contains<input name="q" placeholder="e.g. LOADSHEET"></label>
      <label>Label<input name="lbl" list="lbls" placeholder="any"></label>
      <label>Direction<select name="dir"><option value="">any</option>
        <option value="DL">DL: to aircraft</option><option value="UL">UL: from aircraft</option></select></label>
      <label>Type<select name="kind"><option value="">any</option>
        <option value="cpdlc">CPDLC</option><option value="adsc">ADS-C</option></select></label>
      <label>Channel (MHz)<input name="ch" list="chs" placeholder="any"></label>
      <label>From (UTC)<input name="from" type="date"></label>
      <label>To (UTC)<input name="to" type="date"></label>
      <label>Order<select name="sort"><option value="newest">newest first</option>
        <option value="oldest">oldest first</option></select></label>
      <label class="check"><input type="checkbox" name="hb" value="1"> include heartbeats (_d)</label>
      <div class="btns"><button class="primary" type="submit">Search</button>
        <button type="button" id="reset">Reset</button></div>
    </form>
    <datalist id="lbls"></datalist><datalist id="chs"></datalist>
    <div class="quick"><span>Quick:</span>
      <button type="button" data-q="from=@today&amp;to=@today">Everything today</button>
      <button type="button" data-q="q=POSN&amp;from=@today&amp;to=@today">Position reports today</button>
      <button type="button" data-q="kind=cpdlc&amp;from=@week">CPDLC this week</button>
      <button type="button" data-q="kind=adsc">ADS-C</button>
      <button type="button" data-q="q=LOADSHEET">Loadsheets</button>
      <button type="button" data-q="dir=DL">Ground-sent</button>
    </div>
  </div>

  <div class="grid">
    <div class="panel days"><h2>Matches per day <span class="hint" id="dayhint"></span></h2>
      <div id="days"><div class="empty">…</div></div></div>
    <div class="panel"><h2>Labels <span class="hint">click to filter</span></h2>
      <div id="labels"></div></div>
    <div class="panel"><h2>Aircraft <span class="hint">click to filter</span></h2>
      <div id="aircraft"></div></div>
    <div class="panel"><h2>Channels <span class="hint">click to filter</span></h2>
      <div id="channels"></div></div>
  </div>

  <div class="panel">
    <div class="summary"><span class="big" id="total">–</span><span class="dim" id="range"></span>
      <span class="spacer"></span><a id="csv" href="#">Download CSV</a></div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Time (UTC)</th><th>Aircraft</th><th>Dir</th><th>Label</th><th>Channel</th><th>Text</th></tr></thead>
      <tbody id="rows"></tbody></table></div>
    <div class="pager"><span id="pageinfo"></span>
      <button type="button" id="prev">‹ Newer</button><button type="button" id="next">Older ›</button></div>
  </div>
</main>
<script>
const LIVE_PORT=__LIVE_PORT__;
if(LIVE_PORT){const h=location.hostname,a=document.getElementById("livelink");
  a.href=location.protocol+"//"+(h.includes(":")?"["+h+"]":h)+":"+LIVE_PORT+"/";a.hidden=false;}
const F=document.getElementById("f"), PAGE=200;
const mhz=f=>f?(f/1e6).toFixed(3):"";
let OFFSET=0, LAST=null, SEQ=0;
const esc=s=>String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt=n=>n.toLocaleString("en-US");
const utc=t=>new Date(t*1000).toISOString().replace("T"," ").slice(0,19);
const day=d=>d.toISOString().slice(0,10);

function params(){
  const p=new URLSearchParams();
  for(const el of F.elements){
    if(!el.name) continue;
    if(el.type==="checkbox"){ if(el.checked) p.set(el.name,"1"); }
    else if(el.value.trim()) p.set(el.name,el.value.trim());
  }
  if(p.get("sort")==="newest") p.delete("sort");
  return p;
}
function fill(p){
  for(const el of F.elements){
    if(!el.name) continue;
    if(el.type==="checkbox") el.checked=p.get(el.name)==="1";
    else el.value=p.get(el.name)||(el.name==="sort"?"newest":"");
  }
}
function setField(name,val){ F.elements[name].value=val; OFFSET=0; run(); }

function highlight(txt,q){
  const e=esc(txt);
  if(!q) return e;
  const qe=esc(q).replace(/[.*+?^${}()|[\]\\]/g,"\\$&");
  return e.replace(new RegExp(qe,"gi"),m=>"<mark>"+m+"</mark>");
}
function textCell(r,q){
  const t=r.txt||"", lim=400;
  let h;
  if(!t) h='<span style="color:var(--dim)">(no text)</span>';
  else if(t.length>lim) h='<span class="short">'+highlight(t.slice(0,lim),q)+
    '… <span class="more">more</span></span><span class="full" hidden>'+highlight(t,q)+'</span>';
  else h=highlight(t,q);
  if(r.summary) h+='<div class="sum">'+esc(r.summary)+'</div>';
  return h;
}

function drawDays(days){
  const box=document.getElementById("days");
  if(!days.length){ box.innerHTML='<div class="empty">no matches</div>'; document.getElementById("dayhint").textContent=""; return; }
  // fill missing days with zero so the axis is true time
  const m=new Map(days), start=new Date(days[0][0]+"T00:00:00Z"), end=new Date(days[days.length-1][0]+"T00:00:00Z");
  const all=[];
  for(let d=new Date(start); d<=end; d.setUTCDate(d.getUTCDate()+1)){ const k=day(d); all.push([k,m.get(k)||0]); }
  const W=900,H=110,pad=0, max=Math.max(...all.map(x=>x[1])), bw=W/all.length;
  let s='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none">';
  all.forEach(([k,n],i)=>{
    const h=max?(n/max)*(H-pad-4):0;
    s+='<rect class="bar" data-day="'+k+'" x="'+(i*bw+0.5)+'" y="'+(H-pad-h)+'" width="'+Math.max(1,bw-1)+'" height="'+h+'"><title>'+k+": "+fmt(n)+'</title></rect>';
  });
  s+='</svg><div class="axis"><span>'+all[0][0]+'</span><span>'+all[all.length-1][0]+'</span></div>';
  box.innerHTML=s;
  document.getElementById("dayhint").textContent="peak "+fmt(max)+" · click a day to pick it";
  box.querySelectorAll(".bar").forEach(b=>b.onclick=()=>{ F.elements.from.value=F.elements.to.value=b.dataset.day; OFFSET=0; run(); });
}
function drawFacet(id,items,field){
  const box=document.getElementById(id);
  box.innerHTML=items.length?items.map(([k,n])=>'<div class="facet" data-v="'+esc(k)+'"><span class="k">'+
    esc(k||"(none)")+'</span><span class="n">'+fmt(n)+'</span></div>').join(""):'<div class="empty">–</div>';
  box.querySelectorAll(".facet").forEach(el=>el.onclick=()=>setField(field,el.dataset.v));
}

function render(d){
  const st=document.getElementById("status");
  if(d.error){ st.innerHTML='<span class="err">'+esc(d.error)+'</span>';
    document.getElementById("rows").innerHTML='<tr><td colspan="6" class="empty err">'+esc(d.error)+'</td></tr>'; return; }
  LAST=d;
  st.textContent=d.span.first?"archive "+utc(d.span.first).slice(0,10)+" → "+utc(d.span.last).slice(0,10):"empty database";
  document.getElementById("total").textContent=fmt(d.total)+(d.total===1?" message":" messages");
  document.getElementById("range").textContent=d.filters.hb?"heartbeats included":"heartbeats hidden";
  drawDays(d.days); drawFacet("labels",d.labels,"lbl"); drawFacet("aircraft",d.aircraft,"ac");
  drawFacet("channels",d.channels.map(([f,n])=>[mhz(f),n]),"ch");
  const dl=document.getElementById("lbls");
  if(!dl.children.length) dl.innerHTML=d.labels.map(([k])=>'<option value="'+esc(k)+'">').join("");
  const dc=document.getElementById("chs");
  if(!dc.children.length) dc.innerHTML=d.channels.map(([f])=>'<option value="'+mhz(f)+'">').join("");
  const q=d.filters.q;
  document.getElementById("rows").innerHTML=d.rows.length?d.rows.map(r=>{
    const reg=(r.reg||"").replace(/^\./,"");
    const badges=(r.cpdlc?'<span class="badge cp">CPDLC</span>':"")+(r.adsc?'<span class="badge ad">ADS-C</span>':"");
    const recent=r.icao&&d.now-r.t<86400;
    return '<tr><td class="ts">'+utc(r.t)+'</td><td class="reg">'+
      (reg?'<a href="?ac='+encodeURIComponent(reg)+'" title="every message from this aircraft">'+esc(reg)+'</a>':'–')+
      (r.flt?'<div class="flt">'+esc(r.flt)+'</div>':'')+
      (r.icao?'<div class="hex">'+esc(r.icao)+(recent?' · <a href="/flights#ac='+encodeURIComponent(r.icao)+'" title="its track and route on the Flights page">track</a>':'')+'</div>':'')+
      '</td><td><span class="dir '+esc(r.dir)+'">'+esc(r.dir)+
      '</span></td><td class="lbl">'+esc(r.lbl)+badges+'</td><td class="ch">'+mhz(r.freq)+'</td><td class="txt">'+textCell(r,q)+'</td></tr>';
  }).join(""):'<tr><td colspan="6" class="empty">No messages match. Try fewer filters, or include heartbeats.</td></tr>';
  document.querySelectorAll("td.txt .more").forEach(m=>m.onclick=()=>{
    const td=m.closest("td"); td.querySelector(".short").hidden=true; td.querySelector(".full").hidden=false; });
  const a=d.total?d.offset+1:0, b=Math.min(d.offset+d.rows.length,d.total);
  document.getElementById("pageinfo").textContent=d.total?fmt(a)+"–"+fmt(b)+" of "+fmt(d.total):"";
  const newest=d.sort!=="oldest";
  document.getElementById("prev").textContent=newest?"‹ Newer":"‹ Older";
  document.getElementById("next").textContent=newest?"Older ›":"Newer ›";
  document.getElementById("prev").disabled=d.offset<=0;
  document.getElementById("next").disabled=b>=d.total;
}

async function run(){
  const p=params();
  history.replaceState(null,"",p.toString()?"?"+p:location.pathname);
  document.getElementById("csv").href="/api/search.csv?"+p;
  p.set("offset",OFFSET); p.set("limit",PAGE);
  const seq=++SEQ;
  document.getElementById("status").textContent="searching…";
  try{
    const r=await fetch("/api/search?"+p), d=await r.json();
    if(seq===SEQ) render(d);
  }catch(e){ if(seq===SEQ) render({error:"request failed: "+e}); }
}

F.addEventListener("submit",e=>{ e.preventDefault(); OFFSET=0; run(); });
for(const n of ["dir","kind","sort","from","to","hb","ch"]) F.elements[n].addEventListener("change",()=>{ OFFSET=0; run(); });
document.getElementById("reset").onclick=()=>{ fill(new URLSearchParams()); OFFSET=0; run(); };
document.getElementById("prev").onclick=()=>{ OFFSET=Math.max(0,OFFSET-PAGE); run(); window.scrollTo(0,0); };
document.getElementById("next").onclick=()=>{ OFFSET+=PAGE; run(); window.scrollTo(0,0); };
document.querySelectorAll(".quick button").forEach(b=>b.onclick=()=>{
  const now=new Date(), wk=new Date(now.getTime()-6*86400000);
  const q=b.dataset.q.replace(/@today/g,day(now)).replace(/@week/g,day(wk));
  fill(new URLSearchParams(q)); OFFSET=0; run();
});
fill(new URLSearchParams(location.search));
run();
</script>
</body></html>
"""
