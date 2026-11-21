# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""
VDL2 Observatory — the Flights page (/flights), drawn from /api/flights
(flights.py): each aircraft's reported positions as a track, and its origin
and destination as its own messages give them.

The map helpers (outlines, town names) are the Overview page's
(vdl2_view.py), repeated here so each page stands alone.
"""

FLIGHTS_PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VDL2 Flights</title>
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
  .controls button.on{color:var(--fg);border-color:var(--accent);background:#182634}
  main{padding:18px 22px;max-width:1400px;margin:0 auto}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
    gap:12px;margin-bottom:18px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
  .card .k{color:var(--dim);font-size:11.5px;text-transform:uppercase;letter-spacing:.6px}
  .card .v{font-size:26px;font-weight:600;margin-top:4px}
  .card .v small{font-size:13px;color:var(--dim);font-weight:400}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;
    padding:14px 16px 6px;margin-bottom:14px;overflow-x:auto}
  .panel h2{font-size:13px;margin:0 0 10px;font-weight:600;color:var(--fg);
    display:flex;justify-content:space-between;align-items:center;gap:10px}
  .panel h2 .hint{color:var(--dim);font-weight:400;font-size:11.5px}
  svg{display:block;overflow:hidden}
  .gl{stroke:var(--grid);stroke-width:1}
  .mapax{fill:var(--dim);font-size:11px}
  .plc{fill:var(--place);font-size:10.5px}
  .aclbl{fill:#c9d1d9;font-size:11px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;cursor:pointer}
  .aplbl{fill:var(--warn);font-size:11px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  .empty{color:var(--dim);padding:30px;text-align:center;font-size:13px}
  .sel{color:var(--dim);font-size:12.5px;min-height:18px;margin:6px 0 4px;white-space:pre-wrap}
  .sel b{color:var(--fg);font-weight:600}
  .sel .msg{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:#c9d1d9}
  .legend{display:flex;flex-wrap:wrap;gap:14px;margin:4px 0 8px;font-size:11.5px;color:var(--dim)}
  .legend span{display:inline-flex;align-items:center;gap:5px}
  .legend i{display:inline-block;width:14px;height:0;border-top:2px solid}
  .find{background:var(--panel2);color:var(--fg);border:1px solid var(--line);border-radius:6px;
    padding:4px 9px;font-size:12.5px;width:220px}
  table{width:100%;border-collapse:collapse;font-size:12.5px;margin-bottom:8px}
  th{color:var(--dim);font-weight:500;text-align:left;padding:4px 8px;
    border-bottom:1px solid var(--line);white-space:nowrap}
  td{text-align:left;padding:4px 8px;border-bottom:1px solid var(--grid);
    font-variant-numeric:tabular-nums;white-space:nowrap}
  td.n{text-align:right}
  tr.row{cursor:pointer}
  tr.row:hover td{background:#141b23}
  tr.row.on td{background:#182634}
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  .src{color:var(--dim);font-size:11px}
  .dim{color:var(--dim)}
  a{color:var(--accent)}
</style></head>
<body>
<header>
  <h1>VDL2 Observatory</h1>
  <nav class="nav"><a href="/">Overview</a><a href="/messages">Messages</a><a href="/flights" class="on">Flights</a><a id="livelink" href="#" hidden>Live</a></nav>
  <span class="sub">where aircraft have been and are going, from their own messages</span>
  <span class="spacer"></span>
  <div class="controls" id="win">
    <button data-h="2">2h</button>
    <button data-h="6" class="on">6h</button>
    <button data-h="24">24h</button>
  </div>
  <span class="status" id="status"><span class="dot"></span>loading…</span>
</header>
<main>
  <div class="cards" id="cards"></div>
  <div class="panel">
    <h2>Map <span class="hint">tracks are positions the aircraft reported (XIDs to 0.1°, position reports, ADS-C); the dashed line runs from the latest one to the destination its messages give. Click an aircraft, here or in the list</span></h2>
    <div class="legend">
      <span><i style="border-color:#e6edf3"></i>track, position in the last 30 min</span>
      <span><i style="border-color:#8b98a5"></i>30 to 60 min</span>
      <span><i style="border:0;width:6px;height:6px;border-radius:50%;background:#8b98a5;opacity:.5"></i>last position earlier (track when selected)</span>
      <span><i style="border-color:var(--warn);border-top-style:dashed"></i>to destination (selected aircraft)</span>
      <span><i style="border-color:#4aa8ff;width:9px;height:9px;border:0;background:#4aa8ff"></i>ground station (estimated)</span>
    </div>
    <div id="map"></div>
    <div id="sel" class="sel"></div>
    <div class="sel" style="text-align:right;min-height:0">map: Natural Earth</div>
  </div>
  <div class="panel">
    <h2><span>Aircraft <span class="hint">newest first; route = origin and destination from the aircraft's own messages (the layout in grey), else the destination in its XIDs</span></span>
      <input id="find" class="find" placeholder="find flight, registration, airport"></h2>
    <div id="list"></div>
  </div>
</main>
<script>
const LIVE_PORT=__LIVE_PORT__;
if(LIVE_PORT){const h=location.hostname,a=document.getElementById("livelink");
  a.href=location.protocol+"//"+(h.includes(":")?"["+h+"]":h)+":"+LIVE_PORT+"/";a.hidden=false;}
const NS="http://www.w3.org/2000/svg";
const $=id=>document.getElementById(id);
function el(tag,attrs,txt){const e=document.createElementNS(NS,tag);
  for(const k in attrs)e.setAttribute(k,attrs[k]);
  if(txt!=null)e.textContent=txt;return e;}
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,
  c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
function ago(sec,now){const s=Math.max(0,Math.floor((now||Date.now()/1000))-sec);
  if(s<90)return s+"s ago";if(s<5400)return Math.round(s/60)+"m ago";
  if(s<172800)return Math.round(s/3600)+"h ago";return Math.round(s/86400)+"d ago";}
function ll(lat,lon){return Math.abs(lat).toFixed(2)+(lat<0?"S ":"N ")+Math.abs(lon).toFixed(2)+(lon<0?"W":"E");}
function hhmm(t){const d=new Date(t*1000);return String(d.getUTCHours()).padStart(2,"0")+":"+String(d.getUTCMinutes()).padStart(2,"0")+"Z";}
function name(a){return a.flight||a.reg||a.icao;}
let hours=6,D=null,SEL=(location.hash.match(/ac=([0-9A-Fa-f]{6})/)||[])[1]||null,FIND="";
if(SEL)SEL=SEL.toUpperCase();

// Background map from /map.json (Natural Earth), as on the Overview page.
let OUT=null,OUTP=[],outKey="",outD={};
const OUTSTYLE={land:["var(--land)","var(--coast)",1],lake:["var(--water)","var(--coast)",.8],
  state:["none","var(--state)",.8],border:["none","var(--border)",1.1]};
fetch("/map.json?v=__MAP_V__").then(r=>r.json()).then(d=>{const q=d.q;OUT={};
  for(const [k,ls] of Object.entries(d.layers))OUT[k]=ls.map(e=>{const p=new Float32Array(e.length);
    let x=e[0],y=e[1],b=[x,y,x,y];p[0]=x/q;p[1]=y/q;
    for(let i=2;i<e.length;i+=2){x+=e[i];y+=e[i+1];p[i]=x/q;p[i+1]=y/q;
      if(x<b[0])b[0]=x;if(x>b[2])b[2]=x;if(y<b[1])b[1]=y;if(y>b[3])b[3]=y;}
    return {p,b:b.map(v=>v/q)};});
  OUTP=(d.places||[]).map(p=>({lon:p[0]/q,lat:p[1]/q,r:p[2],n:p[3]}));
  if(D)drawMap();}).catch(()=>{});
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

function shown(){
  if(!D)return [];
  const f=FIND.trim().toUpperCase();
  return D.aircraft.filter(a=>!f||[a.flight,a.reg,a.icao,a.route&&a.route.origin.code,a.route&&a.route.dest.code,
    a.xid_dest&&a.xid_dest.code].some(v=>v&&String(v).toUpperCase().includes(f)));
}
function dest(a){return a.route?a.route.dest:a.xid_dest;}
function select(icao){SEL=SEL===icao?null:icao;
  history.replaceState(null,"",SEL?"#ac="+SEL:location.pathname+location.search);
  drawMap();markRows();detail();}

function drawMap(){
  const host=$("map");if(!D)return;
  const list=shown(),withPos=list.filter(a=>a.track.length);
  if(!withPos.length){host.innerHTML='<div class="empty">no aircraft positions in the last '+hours+' h</div>';return;}
  const sel=SEL?D.aircraft.find(a=>a.icao===SEL):null;
  // the view: every latest position, and the selected aircraft's track and destination
  const pts=withPos.map(a=>a.track[a.track.length-1].slice(1,3));
  if(sel&&sel.track.length){sel.track.forEach(p=>pts.push([p[1],p[2]]));
    const dd=dest(sel);if(dd&&dd.pos)pts.push(dd.pos);}
  let la0=Math.min(...pts.map(p=>p[0])),la1=Math.max(...pts.map(p=>p[0]));
  let lo0=Math.min(...pts.map(p=>p[1])),lo1=Math.max(...pts.map(p=>p[1]));
  const k=Math.cos((la0+la1)/2*Math.PI/180);
  const pad=Math.max(0.3,(la1-la0)*0.06,(lo1-lo0)*k*0.06);
  la0-=pad;la1+=pad;lo0-=pad/k;lo1+=pad/k;
  const MIN=2;
  if(la1-la0<MIN){const c=(la0+la1)/2;la0=c-MIN/2;la1=c+MIN/2;}
  if((lo1-lo0)*k<MIN){const c=(lo0+lo1)/2;lo0=c-MIN/2/k;lo1=c+MIN/2/k;}
  const W=Math.max(260,host.clientWidth||900);
  const H=Math.round(Math.max(300,Math.min(620,W*(la1-la0)/((lo1-lo0)*k))));
  const sc=Math.min(W/((lo1-lo0)*k),H/(la1-la0));
  const X=lo=>(lo-lo0)*k*sc+(W-(lo1-lo0)*k*sc)/2, Y=la=>(la1-la)*sc+(H-(la1-la0)*sc)/2;
  host.innerHTML="";const s=el("svg",{viewBox:"0 0 "+W+" "+H,width:W,height:H});host.appendChild(s);
  const bg=el("rect",{x:0,y:0,width:W,height:H,fill:"var(--water)",stroke:"var(--line)"});
  bg.addEventListener("click",()=>{if(SEL)select(SEL);});s.appendChild(bg);
  const lonAt=x=>lo0+(x-X(lo0))/(k*sc),latAt=y=>la1-(y-Y(la1))/sc;
  const view=[lonAt(0),latAt(H),lonAt(W),latAt(0)],bgG=outlines(s,X,Y,...view);
  const span=view[2]-view[0],step=span>16?4:span>8?2:1;
  for(let g=Math.ceil(view[0]);g<=view[2];g++){if(g%step)continue;
    s.appendChild(el("line",{x1:X(g),y1:0,x2:X(g),y2:H,class:"gl"}));
    s.appendChild(el("text",{x:X(g)+4,y:H-6,class:"mapax"},Math.abs(g)+(g<0?"W":"E")));}
  for(let g=Math.ceil(view[1]);g<=view[3];g++){if(g%step)continue;
    s.appendChild(el("line",{x1:0,y1:Y(g),x2:W,y2:Y(g),class:"gl"}));
    s.appendChild(el("text",{x:4,y:Y(g)-4,class:"mapax"},Math.abs(g)+(g<0?"S":"N")));}
  const boxes=[];
  // ground stations (estimated), quiet
  (D.stations||[]).forEach(g=>{if(g.lat==null||g.lon<view[0]||g.lon>view[2]||g.lat<view[1]||g.lat>view[3])return;
    const r=el("rect",{x:X(g.lon)-3.5,y:Y(g.lat)-3.5,width:7,height:7,rx:1.5,fill:"#4aa8ff","fill-opacity":sel?.2:.4});
    r.appendChild(el("title",null,"ground station "+g.station+" (estimated, ±"+g.spread_km+" km)"));
    s.appendChild(r);boxes.push([X(g.lon)-4,Y(g.lat)-4,8,8]);});
  const now=D.now;
  // selected aircraft: origin and destination airports, dashed line to the destination
  if(sel){const dd=dest(sel),r=sel.route;
    const last=sel.track.length?sel.track[sel.track.length-1]:null;
    const apMark=(a,role)=>{if(!a||!a.pos)return;const x=X(a.pos[1]),y=Y(a.pos[0]);
      s.appendChild(el("path",{d:"M"+x+" "+(y-6)+"L"+(x+6)+" "+y+"L"+x+" "+(y+6)+"L"+(x-6)+" "+y+"Z",fill:"none",stroke:"var(--warn)","stroke-width":1.6}));
      const t=a.code+" "+role;s.appendChild(el("text",{x:x+9,y:y+4,class:"aplbl"},t));boxes.push([x-6,y-6,t.length*6.7+15,12]);};
    if(r)apMark(r.origin,"origin");
    if(dd){apMark(dd,"dest");
      if(last&&dd.pos)s.appendChild(el("line",{x1:X(last[2]),y1:Y(last[1]),x2:X(dd.pos[1]),y2:Y(dd.pos[0]),
        stroke:"var(--warn)","stroke-width":1.6,"stroke-dasharray":"6 5","stroke-opacity":.9}));}
    if(sel.plan&&sel.plan.route.length>1){let d="";sel.plan.route.forEach((p,i)=>{d+=(i?"L":"M")+X(p[1]).toFixed(1)+" "+Y(p[0]).toFixed(1);});
      s.appendChild(el("path",{d:d,fill:"none",stroke:"var(--warn)","stroke-width":1,"stroke-dasharray":"2 4"}));}
  }
  // tracks, oldest aircraft first so the newest draw on top
  const order=withPos.slice().sort((a,b)=>a.last-b.last);
  // A track for each aircraft heard in the last hour (and the selected one,
  // whenever); the rest are a faint dot where they were last.
  order.forEach(a=>{const on=a.icao===SEL,t=a.track,last=t[t.length-1],age=now-last[0],fresh=age<1800;
    if(!on&&age>=3600){const c=el("circle",{cx:X(last[2]),cy:Y(last[1]),r:2.5,fill:"#8b98a5",
        "fill-opacity":sel?.12:.35,style:"cursor:pointer"});
      c.appendChild(el("title",null,name(a)+" "+ll(last[1],last[2])+", "+ago(last[0],now)+(dest(a)?" → "+dest(a).code:"")));
      c.addEventListener("click",e=>{e.stopPropagation();select(a.icao);});s.appendChild(c);return;}
    const col=on?"#ffffff":fresh?"#e6edf3":"#8b98a5",op=sel&&!on?.18:on?1:fresh?.8:.5;
    // a gap of more than 30 minutes breaks the line: another flight, or out of range
    if(t.length>1){let d="";t.forEach((p,i)=>{d+=(i&&p[0]-t[i-1][0]<=1800?"L":"M")+X(p[2]).toFixed(1)+" "+Y(p[1]).toFixed(1);});
      s.appendChild(el("path",{d:d,fill:"none",stroke:col,"stroke-width":on?2.4:1.3,"stroke-opacity":op,"stroke-linejoin":"round"}));}
    if(on)t.forEach(p=>{const c=el("circle",{cx:X(p[2]),cy:Y(p[1]),r:2.6,fill:"#ffffff"});
      c.appendChild(el("title",null,hhmm(p[0])+" "+ll(p[1],p[2])+(p[3]?" "+p[3]+" ft":"")+" ("+p[4]+")"));s.appendChild(c);});
    const c=el("circle",{cx:X(last[2]),cy:Y(last[1]),r:on?6:4,fill:col,"fill-opacity":sel&&!on?.25:1,
      stroke:on?"var(--accent)":"none","stroke-width":2,style:"cursor:pointer"});
    c.appendChild(el("title",null,name(a)+(a.reg&&a.flight?" ("+a.reg+")":"")+" "+ll(last[1],last[2])+
      (last[3]?" "+last[3]+" ft":"")+", "+ago(last[0],now)+(dest(a)?" → "+dest(a).code:"")));
    c.addEventListener("click",e=>{e.stopPropagation();select(a.icao);});
    s.appendChild(c);boxes.push([X(last[2])-5,Y(last[1])-5,10,10]);});
  // labels: the selected aircraft, then the freshest, where they fit
  const hit=(a,b)=>a[0]<b[0]+b[2]&&b[0]<a[0]+a[2]&&a[1]<b[1]+b[3]&&b[1]<a[1]+a[3];
  const lab=withPos.slice().sort((a,b)=>(b.icao===SEL)-(a.icao===SEL)||b.last-a.last);
  let nl=0;
  for(const a of lab){if(sel&&a.icao!==SEL&&nl>=1)break;
    const last=a.track[a.track.length-1];if(now-last[0]>3600&&a.icao!==SEL)continue;
    const cx=X(last[2]),cy=Y(last[1]),t=name(a)+(dest(a)?"→"+dest(a).code:""),w=t.length*6.7,h=12;
    for(const [dx,dy] of [[8,-h/2],[-8-w,-h/2],[-w/2,-7-h],[-w/2,7]]){const b=[cx+dx,cy+dy,w,h];
      if(b[0]<0||b[1]<0||b[0]+w>W||b[1]+h>H||boxes.some(q=>hit(b,q)))continue;
      boxes.push(b);const tx=el("text",{x:b[0],y:b[1]+h-2,class:"aclbl","fill-opacity":sel&&a.icao!==SEL?.3:1},t);
      tx.addEventListener("click",e=>{e.stopPropagation();select(a.icao);});s.appendChild(tx);nl++;break;}
    if(nl>=40)break;}
  placeNames(bgG,X,Y,...view,boxes);
}

function routeCell(a){
  if(a.route){const r=a.route;
    return '<span class="mono" title="'+esc(r.origin.name+" → "+r.dest.name)+'">'+esc(r.origin.code)+" → "+esc(r.dest.code)+
      '</span> <span class="src">'+esc(r.src)+'</span>';}
  if(a.xid_dest)return '<span class="mono" title="'+esc(a.xid_dest.name)+'">→ '+esc(a.xid_dest.code)+'</span> <span class="src">XID</span>';
  return '<span class="dim">—</span>';
}
function drawList(){
  const list=shown(),now=D.now;
  if(!list.length){$("list").innerHTML='<div class="empty">'+(D.aircraft.length?"nothing matches":"no aircraft in the last "+hours+" h")+'</div>';return;}
  let h='<table><thead><tr><th>Flight</th><th>Registration</th><th>Address</th><th>Route</th><th>Last position</th>'+
    '<th>Altitude</th><th>Station</th><th class="n">Messages</th><th class="n">Last heard</th></tr></thead><tbody>';
  list.slice(0,400).forEach(a=>{const last=a.track.length?a.track[a.track.length-1]:null;
    h+='<tr class="row" data-ac="'+a.icao+'"><td class="mono">'+esc(a.flight||"")+'</td><td class="mono">'+esc(a.reg||"")+
      '</td><td class="mono dim">'+a.icao+'</td><td>'+routeCell(a)+'</td><td class="mono">'+
      (last?ll(last[1],last[2])+' <span class="src">'+esc(last[4])+", "+ago(last[0],now)+'</span>':'<span class="dim">—</span>')+
      '</td><td class="mono">'+(last&&last[3]?last[3].toLocaleString()+" ft":"")+'</td><td class="mono dim">'+esc(a.gs||"")+
      '</td><td class="n">'+a.msgs+'</td><td class="n">'+ago(a.last,now)+'</td></tr>';});
  h+='</tbody></table>';
  if(list.length>400)h+='<div class="sel">'+(list.length-400)+' more; narrow it with the search box</div>';
  $("list").innerHTML=h;
  $("list").querySelectorAll("tr.row").forEach(tr=>tr.addEventListener("click",()=>select(tr.dataset.ac)));
  markRows();
}
function markRows(){document.querySelectorAll("#list tr.row").forEach(tr=>tr.classList.toggle("on",tr.dataset.ac===SEL));}
function detail(){
  const box=$("sel"),a=SEL&&D?D.aircraft.find(x=>x.icao===SEL):null;
  if(!a){box.textContent=D?D.totals.with_track+" aircraft with positions on the map, of "+D.totals.aircraft+" heard":"";return;}
  const now=D.now,last=a.track.length?a.track[a.track.length-1]:null;
  let t="<b>"+esc(name(a))+"</b>"+(a.reg&&a.flight?" "+esc(a.reg):"")+" ("+a.icao+")";
  if(a.route)t+="  ·  "+esc(a.route.origin.code)+" "+esc(a.route.origin.name)+" → "+esc(a.route.dest.code)+" "+esc(a.route.dest.name)+
    ' <span class="src">('+esc(a.route.src)+", "+hhmm(a.route.t)+")</span>";
  else if(a.xid_dest)t+="  ·  → "+esc(a.xid_dest.code)+" "+esc(a.xid_dest.name)+' <span class="src">(XID, '+hhmm(a.xid_dest.t)+")</span>";
  if(a.route&&a.xid_dest&&a.xid_dest.code!==a.route.dest.code)t+='  ·  <span class="src">XID says '+esc(a.xid_dest.code)+" ("+hhmm(a.xid_dest.t)+")</span>";
  if(last)t+="  ·  "+a.track.length+" positions, latest "+ll(last[1],last[2])+(last[3]?" "+last[3].toLocaleString()+" ft":"")+", "+ago(last[0],now);
  if(a.plan)t+="  ·  flight plan via "+esc(a.plan.via.join(" "))+(a.plan.cruise_fl?" FL"+a.plan.cruise_fl:"");
  for(const k of ["atis","takeoff"])if(a[k])t+="  ·  "+k+" "+esc(a[k].code);
  if(a.last_msg)t+='\n<span class="src">last message '+hhmm(a.last_msg.t)+" label "+esc(a.last_msg.lbl)+':</span> <span class="msg">'+
    esc(a.last_msg.txt.replace(/\s+/g," ").slice(0,220))+"</span>";
  box.innerHTML=t+'  <span class="src">— click again to clear</span>';
}
function card(k,v,sub){return '<div class="card"><div class="k">'+k+'</div><div class="v">'+v+(sub?' <small>'+sub+'</small>':'')+'</div></div>';}
function render(){
  const T=D.totals,pc=n=>T.aircraft?' ('+Math.round(100*n/T.aircraft)+'%)':'';
  $("cards").innerHTML=card("Aircraft",T.aircraft,"last "+hours+" h")+card("With a track",T.with_track,pc(T.with_track))+
    card("With a destination",T.with_destination,pc(T.with_destination))+card("Origin and destination",T.with_route,pc(T.with_route));
  if(SEL&&!D.aircraft.some(a=>a.icao===SEL))SEL=null;
  drawMap();drawList();detail();
}
async function load(){
  const st=$("status");
  try{const r=await fetch("/api/flights?hours="+hours),d=await r.json();
    if(d.error){$("cards").innerHTML="";$("map").innerHTML='<div class="empty">'+esc(d.error)+'</div>';
      st.innerHTML='<span class="dot" style="background:var(--warn)"></span>'+esc(d.error);return;}
    D=d;render();st.innerHTML='<span class="dot"></span>updated '+new Date().toLocaleTimeString();
  }catch(e){st.innerHTML='<span class="dot" style="background:var(--warn)"></span>fetch failed';}
}
document.querySelectorAll("#win button").forEach(b=>b.addEventListener("click",()=>{
  document.querySelectorAll("#win button").forEach(x=>x.classList.toggle("on",x===b));hours=+b.dataset.h;load();}));
$("find").addEventListener("input",e=>{FIND=e.target.value;if(D){drawMap();drawList();}});
let rt=null;window.addEventListener("resize",()=>{clearTimeout(rt);rt=setTimeout(()=>{if(D)drawMap();},200);});
load();setInterval(load,60000);
</script>
</body></html>
"""
