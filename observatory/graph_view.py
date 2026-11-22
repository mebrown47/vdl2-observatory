# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""
VDL2 Observatory — the Graph page (/graph), drawn from /api/graph (graph.py):
the station handoff diagram and pairs (laid out like iridium-observatory's
Graph tab), one aircraft's history, and the same handoffs on a map.

The map helpers (outlines, town names) are the Overview page's
(vdl2_view.py), repeated here so each page stands alone.
"""

GRAPH_PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VDL2 Graph</title>
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
  .nav{display:flex;gap:4px;flex-wrap:wrap}
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
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:14px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
  .card .k{color:var(--dim);font-size:11.5px;text-transform:uppercase;letter-spacing:.6px}
  .card .v{font-size:26px;font-weight:600;margin-top:4px}
  .card .v small{font-size:13px;color:var(--dim);font-weight:400}
  .grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px}
  @media(max-width:1000px){.grid{grid-template-columns:minmax(0,1fr)}}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;
    padding:14px 16px 8px;margin-bottom:14px;overflow:hidden}
  .panel h2{font-size:13px;margin:0 0 10px;font-weight:600;color:var(--fg);
    display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
  .panel h2 .hint{color:var(--dim);font-weight:400;font-size:11.5px}
  svg{display:block;overflow:hidden}
  #map{touch-action:none;cursor:grab;user-select:none}
  .controls span.controls{gap:4px;align-items:center}
  .controls .lab{color:var(--dim);font-size:11.5px;font-weight:400;margin-right:2px}
  .panel h2 .controls{display:flex;gap:10px;flex-wrap:wrap}
  .gl{stroke:var(--grid);stroke-width:1}
  .mapax{fill:var(--dim);font-size:11px}
  .plc{fill:var(--place);font-size:10.5px}
  .stl{fill:var(--fg);font-size:11.5px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;cursor:pointer}
  .empty{color:var(--dim);padding:26px;text-align:center;font-size:13px}
  .sel{color:var(--dim);font-size:12.5px;min-height:18px;margin:6px 0 4px}
  .sel b{color:var(--fg)}
  table{width:100%;border-collapse:collapse;font-size:12.5px;margin-bottom:8px}
  th{color:var(--dim);font-weight:500;text-align:left;padding:4px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
  td{text-align:left;padding:4px 8px;border-bottom:1px solid var(--grid);font-variant-numeric:tabular-nums;white-space:nowrap}
  td.n,th.n{text-align:right}
  tr.row{cursor:pointer}
  tr.row:hover td{background:#141b23}
  tr.row.on td{background:#182634}
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  .dim{color:var(--dim)}
  .find{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  .find input{background:var(--panel2);color:var(--fg);border:1px solid var(--line);border-radius:7px;
    padding:6px 9px;font-size:13px;width:260px}
  .find button{background:#16324f;color:var(--fg);border:1px solid var(--accent);border-radius:7px;
    padding:6px 14px;cursor:pointer;font-size:13px}
  .chips{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0 10px}
  .chip{background:var(--panel2);border:1px solid var(--line);border-radius:14px;padding:2px 9px;font-size:12px;
    font-family:ui-monospace,SFMono-Regular,Menlo,monospace;cursor:pointer}
  .chip:hover{border-color:var(--accent)}
  .chip .dim{font-family:inherit}
  .bars{display:flex;align-items:flex-end;gap:2px;height:70px;margin:6px 0 2px}
  .bars i{flex:1;background:var(--accent);opacity:.8;min-width:2px;border-radius:2px 2px 0 0}
  .axis{display:flex;justify-content:space-between;color:var(--dim);font-size:10.5px}
  a{color:var(--accent)}
  .seg{display:flex;gap:4px}
  .seg button{background:var(--panel);color:var(--dim);border:1px solid var(--line);
    border-radius:6px;padding:4px 11px;font-size:12.5px;cursor:pointer}
  .seg button.on{color:var(--fg);background:var(--panel2);border-color:var(--accent)}
  .bar{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:14px;align-items:center}
  main{max-width:1200px}
  .card{padding:12px 14px}
  .card .v{font-size:22px;margin-top:3px;font-variant-numeric:tabular-nums}
  .panel{padding:14px}
  .panel h2{font-size:14px;margin:0 0 4px;display:block}
  .meta{color:var(--dim);font-size:12px;margin-bottom:10px}
  #diagram svg,#actl svg{width:100%;height:auto}
  .lbl{fill:var(--fg);font-size:13px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;cursor:pointer}
  .sublbl{fill:var(--dim);font-size:11px}
  .note{color:var(--dim);font-size:12.5px;line-height:1.55}
  .note b{color:var(--fg)}
  .chip b{font-weight:600}
  .chip.link{cursor:pointer}
  .acgrid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px}
  @media (max-width:900px){.acgrid{grid-template-columns:minmax(0,1fr)}}
  h3{font-size:12.5px;color:var(--dim);font-weight:600;text-transform:uppercase;letter-spacing:.5px;margin:14px 0 4px}
  details.panel summary{cursor:pointer;font-size:14px;font-weight:600}
  details.panel summary .meta{font-weight:400;margin:0 0 0 6px}
  .maptools{display:flex;gap:16px;flex-wrap:wrap;margin:10px 0}
  .maptools .lab{color:var(--dim);font-size:11.5px;margin-right:2px;align-self:center}
</style></head>
<body>
<header>
  <h1>VDL2 Observatory</h1>
  <nav class="nav"><a href="/">Overview</a><a href="/messages">Messages</a><a href="/search">Search</a><a href="/flights">Flights</a><a href="/coverage">Coverage</a><a href="/graph" class="on">Graph</a><a id="livelink" href="#" hidden>Live</a></nav>
  <span class="sub">who hands aircraft to whom, from XID handoffs</span>
  <span class="spacer"></span>
  <span class="status" id="status">loading…</span>
</header>
<main>
  <div class="bar">
    <div class="seg" id="win"><button data-h="24">24h</button><button data-h="168" class="on">7d</button>
      <button data-h="720">30d</button><button data-h="0">all</button></div>
  </div>
  <div class="cards" id="cards"></div>
  <div class="panel">
    <h2>Station handoffs</h2>
    <div class="meta">Left: the ground station the aircraft left. Right: the station it joined (an XID names both).
      Line width: aircraft. The busiest pairs are shown; hover a line or name for counts, click a station to show only its handoffs.</div>
    <div id="diagram"></div>
  </div>
  <div class="panel">
    <h2>Handoffs, by pair</h2>
    <div class="meta" id="tablenote"></div>
    <div id="table"></div>
  </div>
  <div class="panel" id="aircraft">
    <h2>One aircraft</h2>
    <div class="meta">Type a registration, flight or address, or pick one of the most active. Shows when it was
      heard, the stations it used, its handoffs and the routes its messages gave, and aircraft served by the
      same stations at the same times.</div>
    <div class="bar"><input id="tail" list="tails" placeholder="registration, flight or address, e.g. N828NV"
      style="background:var(--panel2);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px 10px;font-size:13px;width:280px">
      <datalist id="tails"></datalist>
      <div class="seg"><button id="go">Show</button></div><span class="meta" id="acnote" style="margin:0"></span></div>
    <div id="acview"></div>
  </div>
  <details class="panel" id="mappanel">
    <summary>Station map <span class="meta">the same handoffs at the stations' estimated positions</span></summary>
    <div class="maptools">
      <span class="seg" id="lines"><span class="lab">Lines</span><button data-n="50">50</button><button data-n="100" class="on">100</button><button data-n="300">300</button><button data-n="0">all</button></span>
      <span class="seg" id="mapctl"><span class="lab">Zoom</span><button data-a="in" title="zoom in">+</button><button data-a="out" title="zoom out">−</button><button data-a="core" title="the stations that carry most handoffs">Fit core</button><button data-a="all" title="every placed station">Fit all</button></span>
    </div>
    <div id="map"></div>
    <div class="meta" id="mapnote" style="margin:6px 0 0"></div>
  </details>
  <div class="panel note">
    <b>Where this comes from:</b> every XID an aircraft sends when it joins a ground station names the station it
    is leaving, so each one is a handoff between two stations. This shows which stations pass traffic to which,
    summed over many aircraft. Stations have no names on the air, only six-character addresses such as 11495A;
    on the map they sit where the aircraft talking to them reported themselves (the Overview's estimates), which
    pulls distant stations towards this receiver.
  </div>
</main>
<script>
const LIVE_PORT=__LIVE_PORT__;
if(LIVE_PORT){const h=location.hostname,a=document.getElementById("livelink");
  a.href=location.protocol+"//"+(h.includes(":")?"["+h+"]":h)+":"+LIVE_PORT+"/";a.hidden=false;}
const NS="http://www.w3.org/2000/svg",$=id=>document.getElementById(id);
function el(tag,attrs,txt){const e=document.createElementNS(NS,tag);
  for(const k in attrs)if(attrs[k]!=null)e.setAttribute(k,attrs[k]);if(txt!=null)e.textContent=txt;return e;}
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
function fmt(n){return n==null?"—":n.toLocaleString("en-US");}
function card(k,v,sub){return '<div class="card"><div class="k">'+k+'</div><div class="v">'+v+(sub?' <small>'+sub+'</small>':'')+'</div></div>';}
function ago(t,now){const s=Math.max(0,(now||Date.now()/1000)-t);
  return s<90?Math.round(s)+"s ago":s<5400?Math.round(s/60)+"m ago":s<172800?Math.round(s/3600)+"h ago":Math.round(s/86400)+"d ago";}
function dt(t){return t?new Date(t*1000).toLocaleDateString():"";}
let hours=168,D=null,SEL=null,MAPOPEN=false;

// ---- the handoff diagram: the busiest pairs, at most MAXN stations a side ----
const MAXN=15;
function diagramPairs(){
  const src=SEL?D.pairs.filter(p=>p.from===SEL||p.to===SEL):D.pairs;
  const byAc=src.slice().sort((a,b)=>b.aircraft-a.aircraft||b.handoffs-a.handoffs),L=new Set(),R=new Set(),out=[];
  for(const p of byAc){const nl=L.has(p.from)?0:1,nr=R.has(p.to)?0:1;
    if(L.size+nl>MAXN||R.size+nr>MAXN)continue;L.add(p.from);R.add(p.to);out.push(p);if(out.length>=40)break;}
  return out;
}
function diagram(){
  const host=$("diagram");host.innerHTML="";
  const pairs=diagramPairs();
  if(!pairs.length){host.innerHTML='<div class="empty">No handoffs in this window yet.</div>';return;}
  const st={};D.stations.forEach(s=>st[s.station]=s);
  const uniq=(k)=>[...new Set(pairs.map(p=>p[k]))];
  const left=uniq("from").sort((a,b)=>(st[b]||{}).handed_on-(st[a]||{}).handed_on);
  const right=uniq("to").sort((a,b)=>(st[b]||{}).received-(st[a]||{}).received);
  const li={},ri={};left.forEach((k,i)=>li[k]=i);right.forEach((k,i)=>ri[k]=i);
  const row=40,top=24,W=900,xl=200,xr=650,H=top+Math.max(left.length,right.length)*row+10;
  const svg=el("svg",{viewBox:"0 0 "+W+" "+H,role:"img","aria-label":"Station handoff diagram"});host.appendChild(svg);
  const yl=k=>top+li[k]*row+row/2,yr=k=>top+ri[k]*row+row/2,max=Math.max(...pairs.map(p=>p.aircraft));
  pairs.slice().reverse().forEach(p=>{const y1=yl(p.from),y2=yr(p.to),mx=(xl+xr)/2,w=1.5+7*Math.sqrt(p.aircraft/max);
    const back=D.pairs.find(q=>q.from===p.to&&q.to===p.from);
    const path=el("path",{d:"M"+(xl+8)+" "+y1+"C"+mx+" "+y1+" "+mx+" "+y2+" "+(xr-8)+" "+y2,fill:"none",
      stroke:"var(--accent)","stroke-opacity":0.55,"stroke-width":w});
    path.appendChild(el("title",null,p.from+" → "+p.to+"\n"+fmt(p.aircraft)+" aircraft, "+fmt(p.handoffs)+" handoffs\nlast "+ago(p.last,D.now)+
      (back?"\nthe other way: "+fmt(back.aircraft)+" aircraft":"")));
    svg.appendChild(path);});
  const node=(k,x,y,side)=>{const s=st[k]||{},on=k===SEL,n=side==="l"?s.handed_on:s.received;
    svg.appendChild(el("circle",{cx:x,cy:y,r:6,fill:side==="l"?"var(--fg)":"var(--accent)",stroke:on?"var(--warn)":null,"stroke-width":on?3:null}));
    const tx=side==="l"?x-14:x+14,anchor=side==="l"?"end":"start";
    const t=el("text",{x:tx,y:y+4,"text-anchor":anchor,class:"lbl","data-st":k,fill:on?"var(--warn)":null},k);
    t.appendChild(el("title",null,k+": handed on "+fmt(s.handed_on)+" aircraft, received "+fmt(s.received)+
      (s.lat!=null?"; placed ±"+(s.spread_km||"?")+" km":"; not placed yet")+"\nclick to show only its handoffs"));
    t.addEventListener("click",()=>select(k));svg.appendChild(t);
    svg.appendChild(el("text",{x:tx,y:y+17,"text-anchor":anchor,class:"sublbl"},(side==="l"?"handed on ":"received ")+fmt(n)+" aircraft"));};
  left.forEach(k=>node(k,xl,yl(k),"l"));right.forEach(k=>node(k,xr,yr(k),"r"));
}
function table(){
  const rows=(SEL?D.pairs.filter(p=>p.from===SEL||p.to===SEL):D.pairs).slice().sort((a,b)=>b.aircraft-a.aircraft||b.handoffs-a.handoffs);
  $("tablenote").innerHTML=(SEL?'Only <b>'+esc(SEL)+'</b>’s handoffs. <a href="#" id="clr" style="color:var(--accent)">Show all</a>. ':"")+
    fmt(rows.length)+" pairs"+(rows.length>40?", the busiest 40 shown":"")+".";
  const c=$("clr");if(c)c.onclick=e=>{e.preventDefault();select(SEL);};
  let h='<table><tr><th>from</th><th>to</th><th class="n">aircraft</th><th class="n">handoffs</th><th class="n">last seen</th></tr>';
  rows.slice(0,40).forEach(p=>{h+='<tr><td class="mono">'+esc(p.from)+'</td><td class="mono">'+esc(p.to)+'</td><td class="n">'+fmt(p.aircraft)+
    '</td><td class="n">'+fmt(p.handoffs)+'</td><td class="n">'+ago(p.last,D.now)+'</td></tr>';});
  $("table").innerHTML=rows.length?h+'</table>':'<div class="empty">none</div>';
}
function select(k){SEL=SEL===k?null:k;history.replaceState(null,"",SEL?"#st="+SEL:location.pathname+location.search);
  diagram();table();if(MAPOPEN)drawMap();}
function render(){
  const t=D.totals,win=hours?(hours>=720?"30 days":hours>=168?"7 days":hours+" h"):"all time";
  $("cards").innerHTML=card("Aircraft",fmt(t.aircraft),"handed on")+card("Handoffs",fmt(t.handoffs),win)+
    card("Station pairs",fmt(t.pairs),"")+card("Stations",fmt(t.stations),t.placed+" on the map");
  mergePairs();diagram();table();if(MAPOPEN)drawMap();
}
async function load(){
  try{const d=await (await fetch("/api/graph?hours="+hours)).json();
    if(d.error){$("diagram").innerHTML='<div class="empty">'+esc(d.error)+'</div>';$("status").textContent=d.error;return;}
    D=d;render();$("status").textContent="updated "+new Date().toLocaleTimeString();
  }catch(e){$("status").textContent="fetch failed";}
}

// ---- the station map (closed until asked for) ----
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
    g.appendChild(el("text",{x:x+4,y:y+3.5,class:"plc"},p.n));
    if(++n>=30)break;
  }
}
// The map view: centre (lon, lat) and scale (px per degree of latitude), on
// an equirectangular projection squeezed by cos(latitude). It opens on the
// busy core and keeps whatever view the viewer zooms or drags to.
let V=null,NP=100,MERGED=[],DRAG=null;
function placed(){return D.stations.filter(s=>s.lat!=null&&s.in+s.out>0);}
function geom(){const host=$("map"),W=Math.max(260,host.clientWidth||900);
  return {W,H:Math.round(Math.max(360,Math.min(620,W*.6)))};}
function wpct(items,key,p){const a=items.slice().sort((x,y)=>key(x)-key(y)),tot=a.reduce((t,x)=>t+x.w,0);
  let c=0;for(const x of a){c+=x.w;if(c>=p*tot)return key(x);}return key(a[a.length-1]);}
function fitBox(la0,la1,lo0,lo1,k){const {W,H}=geom();
  if(la1-la0<1.2){const c=(la0+la1)/2;la0=c-.6;la1=c+.6;}
  if((lo1-lo0)*k<1.2){const c=(lo0+lo1)/2;lo0=c-.6/k;lo1=c+.6/k;}
  return {k,cx:(lo0+lo1)/2,cy:(la0+la1)/2,sc:Math.min(W/((lo1-lo0)*k),H/(la1-la0))};}
function fitCore(){const st=placed().map(s=>({lat:s.lat,lon:s.lon,w:s.in+s.out}));if(!st.length)return null;
  const k=Math.cos(wpct(st,s=>s.lat,.5)*Math.PI/180);
  let la0=wpct(st,s=>s.lat,.1),la1=wpct(st,s=>s.lat,.9),lo0=wpct(st,s=>s.lon,.1),lo1=wpct(st,s=>s.lon,.9);
  const pl=(la1-la0)*.3+.15,po=(lo1-lo0)*.3+.15/k;
  return fitBox(la0-pl,la1+pl,lo0-po,lo1+po,k);}
function fitAll(){const st=placed();if(!st.length)return null;const k=V?V.k:fitCore().k;
  let la0=Math.min(...st.map(s=>s.lat)),la1=Math.max(...st.map(s=>s.lat)),lo0=Math.min(...st.map(s=>s.lon)),lo1=Math.max(...st.map(s=>s.lon));
  const pl=(la1-la0)*.05+.1,po=(lo1-lo0)*.05+.1/k;
  return fitBox(la0-pl,la1+pl,lo0-po,lo1+po,k);}
function zoom(f,mx,my){const {W,H}=geom();if(mx==null){mx=W/2;my=H/2;}
  const lim=fitAll(),lo=lim?lim.sc*.6:1,sc=Math.max(lo,Math.min(3000,V.sc*f));
  const lon=V.cx+(mx-W/2)/(V.k*V.sc),lat=V.cy-(my-H/2)/V.sc;
  V.cx=lon-(mx-W/2)/(V.k*sc);V.cy=lat+(my-H/2)/sc;V.sc=sc;redraw();}
let rq=0;function redraw(){if(!rq)rq=requestAnimationFrame(()=>{rq=0;drawMap();});}
function mergePairs(){const m={};
  for(const p of D.pairs){const key=p.from<p.to?p.from+"|"+p.to:p.to+"|"+p.from;
    const e=m[key]||(m[key]={a:p.from<p.to?p.from:p.to,b:p.from<p.to?p.to:p.from,n:0,ab:0,ba:0,last:0});
    e.n+=p.handoffs;if(p.from===e.a)e.ab+=p.handoffs;else e.ba+=p.handoffs;e.last=Math.max(e.last,p.last);}
  MERGED=Object.values(m).sort((x,y)=>y.n-x.n);}
(function(){const host=$("map");
  host.addEventListener("wheel",e=>{if(!V)return;e.preventDefault();const r=host.getBoundingClientRect();
    zoom(e.deltaY<0?1.25:.8,e.clientX-r.left,e.clientY-r.top);},{passive:false});
  host.addEventListener("pointerdown",e=>{if(!V||e.button)return;DRAG={x:e.clientX,y:e.clientY,moved:false};});
  host.addEventListener("pointermove",e=>{if(!DRAG)return;const dx=e.clientX-DRAG.x,dy=e.clientY-DRAG.y;
    if(!DRAG.moved&&Math.hypot(dx,dy)<4)return;
    if(!DRAG.moved){DRAG.moved=true;host.setPointerCapture(e.pointerId);host.style.cursor="grabbing";}
    V.cx-=dx/(V.k*V.sc);V.cy+=dy/V.sc;DRAG.x=e.clientX;DRAG.y=e.clientY;redraw();});
  const up=()=>{if(DRAG&&DRAG.moved)setTimeout(()=>{DRAG=null;},0);else DRAG=null;host.style.cursor="";};
  host.addEventListener("pointerup",up);host.addEventListener("pointercancel",up);
  host.addEventListener("click",e=>{if(DRAG&&DRAG.moved)return;const st=e.target.dataset&&e.target.dataset.st;
    if(st)select(st);else if(SEL)select(SEL);});
  document.querySelectorAll("#mapctl button").forEach(b=>b.addEventListener("click",()=>{if(!V)return;
    const a=b.dataset.a;if(a==="in")zoom(1.5);else if(a==="out")zoom(1/1.5);
    else{V=(a==="all"?fitAll():fitCore())||V;drawMap();}}));
  document.querySelectorAll("#lines button").forEach(b=>b.addEventListener("click",()=>{
    document.querySelectorAll("#lines button").forEach(x=>x.classList.toggle("on",x===b));NP=+b.dataset.n||1e9;drawMap();}));
})();

function drawMap(){
  const host=$("map"),st=placed(),at={};st.forEach(s=>at[s.station]=s);
  if(!st.length||!MERGED.length){host.innerHTML='<div class="empty">no handoffs between placed stations in the window</div>';return;}
  if(!V)V=fitCore();
  const {W,H}=geom(),k=V.k,sc=V.sc;
  const X=lo=>W/2+(lo-V.cx)*k*sc,Y=la=>H/2-(la-V.cy)*sc;
  const lo0=V.cx-W/2/(k*sc),lo1=V.cx+W/2/(k*sc),la0=V.cy-H/2/sc,la1=V.cy+H/2/sc;
  const inView=s=>s.lon>=lo0&&s.lon<=lo1&&s.lat>=la0&&s.lat<=la1;
  host.innerHTML="";const s=el("svg",{viewBox:"0 0 "+W+" "+H,width:W,height:H});host.appendChild(s);
  const defs=el("defs");const m=el("marker",{id:"ar",viewBox:"0 0 10 10",refX:9,refY:5,markerWidth:4.5,markerHeight:4.5,orient:"auto"});
  m.appendChild(el("path",{d:"M0 0L10 5L0 10z",fill:"#e6edf3"}));defs.appendChild(m);s.appendChild(defs);
  s.appendChild(el("rect",{x:0,y:0,width:W,height:H,fill:"var(--water)",stroke:"var(--line)"}));
  const bgG=outlines(s,X,Y,lo0,la0,lo1,la1);
  const draw=MERGED.filter(p=>at[p.a]&&at[p.b]).slice(0,NP),maxn=Math.max(...draw.map(p=>p.n),1),boxes=[];
  // line ends both off one side of the view can't cross it
  const off=(a,b)=>(a.lon<lo0&&b.lon<lo0)||(a.lon>lo1&&b.lon>lo1)||(a.lat<la0&&b.lat<la0)||(a.lat>la1&&b.lat>la1);
  draw.slice().reverse().forEach(p=>{const a=at[p.a],b=at[p.b];if(off(a,b))return;
    const on=SEL&&(p.a===SEL||p.b===SEL);if(on)return;
    const ln=el("line",{x1:X(a.lon),y1:Y(a.lat),x2:X(b.lon),y2:Y(b.lat),stroke:"#4aa8ff",
      "stroke-width":.7+4.5*Math.sqrt(p.n/maxn),"stroke-opacity":SEL?.07:.15+.55*p.n/maxn,"stroke-linecap":"round"});
    ln.appendChild(el("title",null,p.a+" ⇄ "+p.b+": "+fmt(p.n)+" handoffs ("+p.a+"→"+p.b+" "+fmt(p.ab)+", "+p.b+"→"+p.a+" "+fmt(p.ba)+"), last "+ago(p.last,D.now)));
    s.appendChild(ln);});
  if(SEL&&at[SEL]){  // the selected station's pairs, every one, one arrow per direction
    const mine=D.pairs.filter(p=>(p.from===SEL||p.to===SEL)&&at[p.from]&&at[p.to]),mx=Math.max(...mine.map(p=>p.handoffs),1);
    mine.slice().reverse().forEach(p=>{const a=at[p.from],b=at[p.to],x1=X(a.lon),y1=Y(a.lat),x2=X(b.lon),y2=Y(b.lat);
      const len=Math.hypot(x2-x1,y2-y1);if(len<14)return;
      const ux=(x2-x1)/len,uy=(y2-y1)/len,ox=-uy*2.5,oy=ux*2.5;
      const ln=el("line",{x1:x1+ox+ux*7,y1:y1+oy+uy*7,x2:x2+ox-ux*8,y2:y2+oy-uy*8,stroke:p.from===SEL?"#e6edf3":"#f2cc60",
        "stroke-width":.8+4*Math.sqrt(p.handoffs/mx),"stroke-opacity":.85,"marker-end":"url(#ar)"});
      ln.appendChild(el("title",null,p.from+" → "+p.to+": "+fmt(p.handoffs)+" handoffs, "+fmt(p.aircraft)+" aircraft"));
      s.appendChild(ln);});}
  const vis=st.filter(inView),maxd=Math.max(...st.map(x=>x.in+x.out));
  vis.forEach(x=>{const cx=X(x.lon),cy=Y(x.lat),on=x.station===SEL,r=2.5+5*Math.sqrt((x.in+x.out)/maxd);
    const q=el("rect",{x:cx-r,y:cy-r,width:2*r,height:2*r,rx:2,fill:on?"#e6edf3":"#4aa8ff",stroke:"#0e1116",
      "fill-opacity":SEL&&!on?.55:1,style:"cursor:pointer","data-st":x.station});
    q.appendChild(el("title",null,x.station+": "+fmt(x.in)+" handoffs in, "+fmt(x.out)+" out, "+fmt(x.aircraft)+" aircraft; position ±"+(x.spread_km||"?")+" km"));
    s.appendChild(q);boxes.push([cx-r,cy-r,2*r,2*r]);});
  const hit=(a,b)=>a[0]<b[0]+b[2]&&b[0]<a[0]+a[2]&&a[1]<b[1]+b[3]&&b[1]<a[1]+a[3];
  vis.slice().sort((a,b)=>(b.station===SEL)-(a.station===SEL)||(b.in+b.out)-(a.in+a.out)).forEach(x=>{
    const cx=X(x.lon),cy=Y(x.lat),w=x.station.length*7.2,h=12;
    for(const [dx,dy] of [[9,-h/2],[-9-w,-h/2],[-w/2,-9-h],[-w/2,9]]){const b=[cx+dx,cy+dy,w,h];
      if(b[0]<0||b[1]<0||b[0]+w>W||b[1]+h>H||boxes.some(q=>hit(b,q)))continue;
      boxes.push(b);s.appendChild(el("text",{x:b[0],y:b[1]+h-2,class:"stl","fill-opacity":SEL&&x.station!==SEL?.45:1,"data-st":x.station},x.station));break;}});
  placeNames(bgG,X,Y,lo0,la0,lo1,la1,boxes);
  // scale bar
  const kmpx=111.2/sc,nice=[5,10,20,25,50,100,200,250,500,1000].find(v=>v/kmpx>=70)||1000,bw=nice/kmpx;
  s.appendChild(el("rect",{x:10,y:H-30,width:bw+16,height:22,rx:4,fill:"var(--panel)","fill-opacity":.8}));
  s.appendChild(el("line",{x1:18,y1:H-14,x2:18+bw,y2:H-14,stroke:"var(--fg)","stroke-width":2}));
  s.appendChild(el("text",{x:18,y:H-18,class:"mapax"},nice+" km"));
  V.hidden=st.length-vis.length;V.drawn=draw.length;
  const note=document.getElementById("mapnote");if(note)note.textContent="Busiest "+fmt(draw.length)+" of "+fmt(MERGED.length)+" station pairs drawn"+
    (V.hidden?"; "+V.hidden+" stations outside this view: zoom out, drag, or press Fit all":"")+".";
}
$("mappanel").addEventListener("toggle",()=>{MAPOPEN=$("mappanel").open;if(MAPOPEN&&D)drawMap();});

// ---- one aircraft ----
function activity(host,a){
  host.innerHTML="";const days=a.days;
  if(!days.length){host.innerHTML='<div class="meta">no messages</div>';return;}
  const nd=days.length,W=900,H=110,pl=34,pr=8,pb=20,pt=6,iw=W-pl-pr,ih=H-pt-pb,bw=Math.max(1,Math.min(18,iw/nd-1));
  const max=Math.max(...days.map(x=>x.msgs+x.acks),1);
  const svg=el("svg",{viewBox:"0 0 "+W+" "+H,role:"img","aria-label":"Messages per day"});host.appendChild(svg);
  const X=i=>pl+iw*i/nd,Y=v=>pt+ih*(1-v/max);
  [0,max].forEach(v=>{svg.appendChild(el("line",{x1:pl,x2:W-pr,y1:Y(v),y2:Y(v),stroke:"var(--grid)"}));
    svg.appendChild(el("text",{x:pl-6,y:Y(v)+4,"text-anchor":"end",class:"sublbl"},v));});
  days.forEach((x,i)=>{const tip=x.day+": "+x.msgs+" messages, "+x.acks+" heartbeats";
    const g=el("rect",{x:X(i),y:Y(x.msgs+x.acks),width:bw,height:ih*x.acks/max,fill:"var(--dim)","fill-opacity":0.45});
    g.appendChild(el("title",null,tip));svg.appendChild(g);
    const c=el("rect",{x:X(i),y:Y(x.msgs),width:bw,height:ih*x.msgs/max,fill:"var(--accent)"});
    c.appendChild(el("title",null,tip));svg.appendChild(c);});
  svg.appendChild(el("text",{x:pl,y:H-4,class:"sublbl"},days[0].day));
  svg.appendChild(el("text",{x:W-pr,y:H-4,"text-anchor":"end",class:"sublbl"},days[nd-1].day));
}
function chips(list,f){return '<div class="chips">'+(list.length?list.map(f).join(""):'<span class="meta">none</span>')+'</div>';}
function showAircraft(q){
  q=(q||"").trim();if(!q)return;$("tail").value=q;
  history.replaceState(null,"","?ac="+encodeURIComponent(q)+location.hash);
  fetch("/api/graph?aircraft="+encodeURIComponent(q)).then(r=>r.json()).then(a=>{
    const v=$("acview");
    if(a.error){v.innerHTML='<div class="empty">'+esc(a.error)+'</div>';return;}
    const acks=a.days.reduce((t,d)=>t+d.acks,0),heard=a.days.filter(d=>d.msgs+d.acks).length;
    let h='<div class="cards">'+card("Messages",fmt(a.msgs-acks),"content")+card("Heartbeats",fmt(acks),"")+
      card("Days heard",fmt(heard),"")+card("Seen",dt(a.first),"to "+dt(a.last))+'</div>';
    h+='<div class="meta" style="margin:0">'+esc(a.regs[0]||"")+' · address <span class="mono">'+esc(a.icao)+'</span> · flights <span class="mono">'+
      esc(a.flights.slice(0,6).map(f=>f.flight).join(", ")||"—")+'</span>'+(a.others.length?' · other aircraft matched: <span class="mono">'+esc(a.others.join(", "))+'</span>':'')+'</div>';
    h+='<h3>Messages per day</h3><div id="actl"></div><div class="meta">blue: messages; grey: heartbeats</div>';
    h+='<div class="acgrid"><div><h3>Ground stations</h3>'+chips(a.stations.slice(0,16),g=>'<span class="chip link" data-st="'+esc(g.station)+'"><b class="mono">'+esc(g.station)+'</b> '+g.n+'</span>');
    const dests={};a.xid_destinations.forEach(x=>dests[x.airport]=(dests[x.airport]||0)+1);
    h+='<h3>Destinations in its XIDs</h3>'+chips(Object.entries(dests).sort((x,y)=>y[1]-x[1]).slice(0,12),d=>'<span class="chip"><b>'+esc(d[0])+'</b> '+d[1]+(d[1]>1?' days':' day')+'</span>');
    h+='<h3>Message labels</h3>'+chips(a.labels,l=>'<span class="chip">'+esc(l[0])+' '+l[1]+'</span>')+'</div>';
    h+='<div><h3>Related aircraft</h3><div class="meta">served by the same station within '+Math.round(a.co_present_s/60)+' minutes</div>'+
      chips(a.related,r=>'<span class="chip link" data-ac="'+esc(r.icao)+'"><b>'+esc(r.reg||r.icao)+'</b> ×'+r.times+' · '+esc(r.stations.join(", "))+'</span>')+'</div></div>';
    const ev=a.handoffs.map(x=>({t:x.t,what:"handoff"+(x.airport?", going to "+x.airport:""),from:x.from||"(first contact)",to:x.to}))
      .concat(a.routes.map(r=>({t:r.t,what:"route "+r.origin+" → "+r.dest+" ("+r.src+")"+(r.flight?", "+r.flight:""),from:"",to:""})))
      .sort((x,y)=>y.t-x.t).slice(0,40);
    h+='<h3>Handoffs and routes</h3>';
    if(ev.length){h+='<table class="ev"><tr><th>time (UTC)</th><th>event</th><th>from</th><th>to</th></tr>';
      ev.forEach(e=>{h+='<tr><td>'+new Date(e.t*1000).toISOString().slice(0,16).replace("T"," ")+'</td><td>'+esc(e.what)+
        '</td><td class="mono">'+esc(e.from)+'</td><td class="mono">'+esc(e.to)+'</td></tr>';});h+='</table>';}
    else h+='<div class="meta">none</div>';
    h+='<p class="meta">Its messages: <a href="/search?ac='+encodeURIComponent(a.icao)+'" style="color:var(--accent)">Search, '+esc(a.regs[0]||a.icao)+'</a>'+
      (a.last&&a.now-a.last<86400?' · its track: <a href="/flights#ac='+encodeURIComponent(a.icao)+'" style="color:var(--accent)">Flights</a>':'')+'</p>';
    v.innerHTML=h;activity($("actl"),a);
    v.querySelectorAll(".chip.link[data-ac]").forEach(c=>c.onclick=()=>showAircraft(c.dataset.ac));
    v.querySelectorAll(".chip.link[data-st]").forEach(c=>c.onclick=()=>{SEL=null;select(c.dataset.st);$("diagram").scrollIntoView({behavior:"smooth"});});
  });
}
fetch("/api/graph?list=1").then(r=>r.json()).then(d=>{const l=d.aircraft||[];
  $("tails").innerHTML=l.map(a=>'<option value="'+esc(a.reg||a.icao)+'">'+esc((a.flight||"")+" "+a.icao+", "+a.msgs+" messages")+'</option>').join("");
  $("acnote").textContent=l.length?"most active: "+l.slice(0,5).map(a=>a.reg||a.icao).join(", "):"";
  const q0=new URLSearchParams(location.search).get("ac");showAircraft(q0||(l[0]&&(l[0].reg||l[0].icao)));}).catch(()=>{});
$("go").onclick=()=>showAircraft($("tail").value);
$("tail").onkeydown=e=>{if(e.key==="Enter")showAircraft(e.target.value);};
$("win").onclick=e=>{const b=e.target.closest("button");if(!b)return;
  hours=+b.dataset.h;[...b.parentNode.children].forEach(x=>x.classList.toggle("on",x===b));load();};
{const m=location.hash.match(/st=([0-9A-Fa-f]{6})/);if(m)SEL=m[1].toUpperCase();}
let rt=null;window.addEventListener("resize",()=>{clearTimeout(rt);rt=setTimeout(()=>{if(D&&MAPOPEN)drawMap();},200);});
load();setInterval(load,300000);
</script>
</body></html>
"""
