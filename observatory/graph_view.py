# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""
VDL2 Observatory — the Graph page (/graph), drawn from /api/graph (graph.py):
the ground-station handoff network on a map, and one aircraft's history.

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
</style></head>
<body>
<header>
  <h1>VDL2 Observatory</h1>
  <nav class="nav"><a href="/">Overview</a><a href="/messages">Messages</a><a href="/search">Search</a><a href="/flights">Flights</a><a href="/coverage">Coverage</a><a href="/graph" class="on">Graph</a><a id="livelink" href="#" hidden>Live</a></nav>
  <span class="sub">how ground stations hand aircraft on, and one aircraft's history</span>
  <span class="spacer"></span>
  <div class="controls" id="win">
    <button data-h="24">24h</button>
    <button data-h="168" class="on">7d</button>
    <button data-h="720">30d</button>
  </div>
  <span class="status" id="status"><span class="dot"></span>loading…</span>
</header>
<main>
  <div class="cards" id="cards"></div>
  <div class="panel">
    <h2><span>Handoff network <span class="hint">a line for each pair of stations aircraft were handed between (an XID names the station it leaves and the one it joins), thicker for more handoffs; stations at their estimated positions (see the Overview). Scroll to zoom, drag to move, click a station for its handoffs each way</span></span>
      <span class="controls"><span class="controls" id="lines"><span class="lab">Lines</span><button data-n="50">50</button><button data-n="100" class="on">100</button><button data-n="300">300</button><button data-n="0">all</button></span>
      <span class="controls" id="mapctl"><span class="lab">Zoom</span><button data-a="in" title="zoom in">+</button><button data-a="out" title="zoom out">−</button><button data-a="core" title="the stations that carry most handoffs">Fit core</button><button data-a="all" title="every placed station">Fit all</button></span></span></h2>
    <div id="map"></div>
    <div id="sel" class="sel"></div>
  </div>
  <div class="grid">
    <div class="panel">
      <h2>Busiest handoffs <span class="hint">by handoffs in the window</span></h2>
      <div id="pairs"></div>
    </div>
    <div class="panel">
      <h2>Stations <span class="hint">handoffs in and out, distinct aircraft heard</span></h2>
      <div id="stations"></div>
    </div>
  </div>
  <div class="panel" id="acpanel">
    <h2><span>One aircraft <span class="hint">by registration, flight or address: when it was heard, the stations it used, its handoffs and the routes its messages gave</span></span>
      <form class="find" id="acform"><input id="acq" list="aclist" placeholder="registration, flight or address" autocomplete="off"><datalist id="aclist"></datalist><button type="submit">Show</button></form></h2>
    <div id="ac"><div class="empty">pick an aircraft</div></div>
  </div>
</main>
<script>
const LIVE_PORT=__LIVE_PORT__;
if(LIVE_PORT){const h=location.hostname,a=document.getElementById("livelink");
  a.href=location.protocol+"//"+(h.includes(":")?"["+h+"]":h)+":"+LIVE_PORT+"/";a.hidden=false;}
const NS="http://www.w3.org/2000/svg",$=id=>document.getElementById(id);
function el(tag,attrs,txt){const e=document.createElementNS(NS,tag);
  for(const k in attrs)e.setAttribute(k,attrs[k]);if(txt!=null)e.textContent=txt;return e;}
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
function fmt(n){return n==null?"—":n.toLocaleString("en-US");}
function ago(t,now){const s=Math.max(0,(now||Date.now()/1000)-t);
  return s<90?Math.round(s)+"s ago":s<5400?Math.round(s/60)+"m ago":s<172800?Math.round(s/3600)+"h ago":Math.round(s/86400)+"d ago";}
function utc(t){return new Date(t*1000).toISOString().replace("T"," ").slice(0,16)+"Z";}
let hours=168,D=null,SEL=(location.hash.match(/st=([0-9A-Fa-f]{6})/)||[])[1]||null,AC=null;
if(SEL)SEL=SEL.toUpperCase();

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
function select(st){SEL=SEL===st?null:st;
  history.replaceState(null,"",SEL?"#st="+SEL:location.pathname+location.search);
  drawMap();drawTables();info();}

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
  if(!SEL)info();
}
function info(){
  const box=$("sel");
  if(!SEL){const t=D.totals,v=V||{};box.textContent="Busiest "+fmt(v.drawn||0)+" of "+fmt(MERGED.length)+" station pairs drawn. "+
    t.placed+" of "+t.stations+" stations placed ("+(t.stations-t.placed)+" too few positions yet)"+
    (v.hidden?"; "+v.hidden+" outside this view: zoom out, drag, or press Fit all":"")+".";return;}
  const s=D.stations.find(x=>x.station===SEL);if(!s){box.textContent="";return;}
  const out=D.pairs.filter(p=>p.from===SEL).slice(0,6).map(p=>p.to+" "+fmt(p.handoffs)).join(", ");
  const inn=D.pairs.filter(p=>p.to===SEL).slice(0,6).map(p=>p.from+" "+fmt(p.handoffs)).join(", ");
  box.innerHTML="<b>"+esc(SEL)+"</b>: "+fmt(s.in)+" handoffs in, "+fmt(s.out)+" out, "+fmt(s.aircraft)+" aircraft. "+
    "Hands on to (white): "+esc(out||"—")+". Takes from (yellow): "+esc(inn||"—")+". Click again to clear.";
}
function drawTables(){
  const rows=(SEL?D.pairs.filter(p=>p.from===SEL||p.to===SEL):D.pairs).slice(0,25);
  $("pairs").innerHTML=rows.length?'<table><thead><tr><th>From</th><th></th><th>To</th><th class="n">Handoffs</th><th class="n">Aircraft</th><th class="n">Last</th></tr></thead><tbody>'+
    rows.map(p=>'<tr><td class="mono">'+esc(p.from)+'</td><td class="dim">→</td><td class="mono">'+esc(p.to)+'</td><td class="n">'+fmt(p.handoffs)+
      '</td><td class="n">'+fmt(p.aircraft)+'</td><td class="n dim">'+ago(p.last,D.now)+'</td></tr>').join("")+'</tbody></table>':'<div class="empty">no handoffs</div>';
  const st=D.stations.filter(s=>s.in+s.out>0).slice(0,25);
  $("stations").innerHTML='<table><thead><tr><th>Station</th><th class="n">In</th><th class="n">Out</th><th class="n">Aircraft</th><th class="n">Placed</th></tr></thead><tbody>'+
    st.map(s=>'<tr class="row'+(s.station===SEL?" on":"")+'" data-st="'+s.station+'"><td class="mono">'+esc(s.station)+'</td><td class="n">'+fmt(s.in)+
      '</td><td class="n">'+fmt(s.out)+'</td><td class="n">'+fmt(s.aircraft)+'</td><td class="n dim">'+(s.lat!=null?"±"+(s.spread_km||"?")+" km":"not yet")+'</td></tr>').join("")+'</tbody></table>';
  $("stations").querySelectorAll("tr.row").forEach(tr=>tr.addEventListener("click",()=>select(tr.dataset.st)));
}
function card(k,v,sub){return '<div class="card"><div class="k">'+k+'</div><div class="v">'+v+(sub?' <small>'+sub+'</small>':'')+'</div></div>';}
function label(){return hours>=720?"30 days":hours>=168?"7 days":hours+" h";}
function render(){
  const t=D.totals;
  $("cards").innerHTML=card("Handoffs",fmt(t.handoffs),"last "+label())+card("Station pairs",fmt(t.pairs))+
    card("Stations",fmt(t.stations),t.placed+" placed")+card("Aircraft handed on",fmt(t.aircraft));
  mergePairs();drawMap();drawTables();info();
}
async function load(){
  const st=$("status");
  try{const d=await (await fetch("/api/graph?hours="+hours)).json();
    if(d.error){$("map").innerHTML='<div class="empty">'+esc(d.error)+'</div>';st.innerHTML='<span class="dot" style="background:var(--warn)"></span>'+esc(d.error);return;}
    D=d;render();st.innerHTML='<span class="dot"></span>updated '+new Date().toLocaleTimeString();
  }catch(e){st.innerHTML='<span class="dot" style="background:var(--warn)"></span>fetch failed';}
}

// one aircraft
async function showAircraft(q){
  if(!q)return;
  history.replaceState(null,"","?ac="+encodeURIComponent(q)+location.hash);
  const box=$("ac");box.innerHTML='<div class="empty">loading…</div>';
  const a=await (await fetch("/api/graph?aircraft="+encodeURIComponent(q))).json();
  if(a.error){box.innerHTML='<div class="empty">'+esc(a.error)+'</div>';return;}
  AC=a;const now=a.now,recent=a.last&&now-a.last<86400;
  let h='<div class="cards">'+card("Aircraft",'<span class="mono">'+esc(a.regs[0]||a.icao)+'</span>',esc(a.icao))+
    card("Heard",a.first?ago(a.last,now):"—",a.first?"first "+utc(a.first).slice(0,10):"")+
    card("Messages",fmt(a.msgs),"on "+fmt(a.days.filter(d=>d.msgs+d.acks).length)+" days")+card("Positions",fmt(a.positions))+'</div>';
  h+='<div class="sel">Flights: <span class="mono">'+esc(a.flights.slice(0,8).map(f=>f.flight).join(", ")||"—")+'</span>'+
    (a.regs.length>1?' · also registered as <span class="mono">'+esc(a.regs.slice(1).join(", "))+'</span>':'')+
    (a.others.length?' · other aircraft matched: <span class="mono">'+esc(a.others.join(", "))+'</span>':'')+
    ' · <a href="/search?ac='+encodeURIComponent(a.icao)+'">its messages in Search</a>'+
    (recent?' · <a href="/flights#ac='+encodeURIComponent(a.icao)+'">its track on Flights</a>':'')+'</div>';
  if(a.days.length){const mx=Math.max(...a.days.map(d=>d.msgs+d.acks));
    h+='<div class="sel">Messages per day (UTC)</div><div class="bars">'+a.days.map(d=>'<i title="'+d.day+": "+d.msgs+" messages, "+d.acks+
      ' heartbeats" style="height:'+Math.max(2,70*(d.msgs+d.acks)/mx)+'px"></i>').join("")+'</div><div class="axis"><span>'+a.days[0].day+
      '</span><span>'+a.days[a.days.length-1].day+'</span></div>';}
  h+='<div class="sel">Stations it used (click to show on the map)</div><div class="chips">'+(a.stations.slice(0,24).map(s=>
    '<span class="chip" data-st="'+s.station+'">'+esc(s.station)+' <span class="dim">'+s.n+'</span></span>').join("")||'<span class="dim">none</span>')+'</div>';
  h+='<div class="grid"><div><div class="sel">Recent handoffs</div>'+(a.handoffs.length?'<table><thead><tr><th>Time</th><th>From</th><th></th><th>To</th><th>Going to</th></tr></thead><tbody>'+
    a.handoffs.slice(0,20).map(x=>'<tr><td class="dim">'+utc(x.t)+'</td><td class="mono">'+esc(x.from||"—")+'</td><td class="dim">→</td><td class="mono">'+esc(x.to)+
      '</td><td class="mono">'+esc(x.airport)+'</td></tr>').join("")+'</tbody></table>':'<div class="empty">no handoffs heard</div>')+'</div>';
  h+='<div><div class="sel">Routes from its messages, by day</div>'+(a.routes.length?'<table><thead><tr><th>Day</th><th>Flight</th><th>Route</th><th>From</th></tr></thead><tbody>'+
    a.routes.slice(0,20).map(r=>'<tr><td class="dim">'+r.day+'</td><td class="mono">'+esc(r.flight)+'</td><td class="mono" title="'+esc(r.origin_name+" → "+r.dest_name)+'">'+
      esc(r.origin)+" → "+esc(r.dest)+'</td><td class="dim">'+esc(r.src)+'</td></tr>').join("")+'</tbody></table>':
    (a.xid_destinations.length?'<table><thead><tr><th>Day</th><th>Destination in its XIDs</th></tr></thead><tbody>'+a.xid_destinations.slice(0,20).map(x=>
      '<tr><td class="dim">'+x.day+'</td><td class="mono" title="'+esc(x.name)+'">'+esc(x.airport)+'</td></tr>').join("")+'</tbody></table>':'<div class="empty">no routes in its messages</div>'))+'</div></div>';
  box.innerHTML=h;
  box.querySelectorAll(".chip").forEach(c=>c.addEventListener("click",()=>{SEL=null;select(c.dataset.st);
    const x=D&&D.stations.find(v=>v.station===c.dataset.st);if(x&&x.lat!=null&&V){V.cx=x.lon;V.cy=x.lat;drawMap();}
    $("map").scrollIntoView({behavior:"smooth"});}));
}
$("acform").addEventListener("submit",e=>{e.preventDefault();showAircraft($("acq").value.trim());});
fetch("/api/graph?list=1").then(r=>r.json()).then(d=>{$("aclist").innerHTML=(d.aircraft||[]).map(a=>
  '<option value="'+esc(a.reg||a.icao)+'">'+esc((a.flight||"")+" "+a.icao+", "+a.msgs+" messages")+'</option>').join("");}).catch(()=>{});
document.querySelectorAll("#win button").forEach(b=>b.addEventListener("click",()=>{
  document.querySelectorAll("#win button").forEach(x=>x.classList.toggle("on",x===b));hours=+b.dataset.h;load();}));
let rt=null;window.addEventListener("resize",()=>{clearTimeout(rt);rt=setTimeout(()=>{if(D)drawMap();},200);});
load();setInterval(load,300000);
const q0=new URLSearchParams(location.search).get("ac");if(q0){$("acq").value=q0;showAircraft(q0);}
</script>
</body></html>
"""
