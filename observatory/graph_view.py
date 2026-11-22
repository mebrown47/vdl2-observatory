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
    <h2>Handoff network <span class="hint">a line for each pair of stations an aircraft was handed between (its XID names the station it leaves and the one it joins), thicker for more handoffs, the arrow pointing where it went; stations at their estimated positions (see the Overview). Click a station, or a row below</span></h2>
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

function drawMap(){
  const host=$("map"),st=D.stations.filter(s=>s.lat!=null),at={};st.forEach(s=>at[s.station]=s);
  const pairs=D.pairs.filter(p=>at[p.from]&&at[p.to]);
  if(!st.length||!pairs.length){host.innerHTML='<div class="empty">no handoffs between placed stations in the window</div>';return;}
  const used=new Set();pairs.forEach(p=>{used.add(p.from);used.add(p.to);});
  const shown=st.filter(s=>used.has(s.station));
  let la0=Math.min(...shown.map(s=>s.lat)),la1=Math.max(...shown.map(s=>s.lat));
  let lo0=Math.min(...shown.map(s=>s.lon)),lo1=Math.max(...shown.map(s=>s.lon));
  const k=Math.cos((la0+la1)/2*Math.PI/180),pad=Math.max(.3,(la1-la0)*.06);
  la0-=pad;la1+=pad;lo0-=pad/k;lo1+=pad/k;
  if(la1-la0<2){const c=(la0+la1)/2;la0=c-1;la1=c+1;}
  if((lo1-lo0)*k<2){const c=(lo0+lo1)/2;lo0=c-1/k;lo1=c+1/k;}
  const W=Math.max(260,host.clientWidth||900),H=Math.round(Math.max(340,Math.min(660,W*(la1-la0)/((lo1-lo0)*k))));
  const sc=Math.min(W/((lo1-lo0)*k),H/(la1-la0));
  const X=lo=>(lo-lo0)*k*sc+(W-(lo1-lo0)*k*sc)/2,Y=la=>(la1-la)*sc+(H-(la1-la0)*sc)/2;
  host.innerHTML="";const s=el("svg",{viewBox:"0 0 "+W+" "+H,width:W,height:H});host.appendChild(s);
  const defs=el("defs");["a","b"].forEach(n=>{const m=el("marker",{id:"ar-"+n,viewBox:"0 0 10 10",refX:9,refY:5,markerWidth:5,markerHeight:5,orient:"auto"});
    m.appendChild(el("path",{d:"M0 0L10 5L0 10z",fill:n==="a"?"#4aa8ff":"#e6edf3"}));defs.appendChild(m);});s.appendChild(defs);
  const bg=el("rect",{x:0,y:0,width:W,height:H,fill:"var(--water)",stroke:"var(--line)"});
  bg.addEventListener("click",()=>{if(SEL)select(SEL);});s.appendChild(bg);
  const lonAt=x=>lo0+(x-X(lo0))/(k*sc),latAt=y=>la1-(y-Y(la1))/sc;
  const view=[lonAt(0),latAt(H),lonAt(W),latAt(0)],bgG=outlines(s,X,Y,...view);
  const maxh=Math.max(...pairs.map(p=>p.handoffs)),boxes=[];
  // the busiest 300 pairs, quietest first so the busiest draw on top; each
  // direction offset to its own side of the line between the two stations
  const draw=pairs.slice(0,300).reverse();
  draw.forEach(p=>{const a=at[p.from],b=at[p.to],x1=X(a.lon),y1=Y(a.lat),x2=X(b.lon),y2=Y(b.lat);
    const len=Math.hypot(x2-x1,y2-y1);if(len<12)return;
    const ux=(x2-x1)/len,uy=(y2-y1)/len,ox=-uy*2.5,oy=ux*2.5;
    const on=SEL&&(p.from===SEL||p.to===SEL),w=.8+5*Math.sqrt(p.handoffs/maxh);
    const ln=el("line",{x1:x1+ox+ux*7,y1:y1+oy+uy*7,x2:x2+ox-ux*8,y2:y2+oy-uy*8,stroke:on?"#e6edf3":"#4aa8ff",
      "stroke-width":w,"stroke-opacity":SEL?(on?.9:.06):.18+.6*p.handoffs/maxh,"marker-end":"url(#ar-"+(on?"b":"a")+")"});
    ln.appendChild(el("title",null,p.from+" → "+p.to+": "+fmt(p.handoffs)+" handoffs, "+fmt(p.aircraft)+" aircraft, last "+ago(p.last,D.now)));
    s.appendChild(ln);});
  const maxd=Math.max(...shown.map(x=>x.in+x.out));
  shown.forEach(x=>{const cx=X(x.lon),cy=Y(x.lat),on=x.station===SEL,r=3+5*Math.sqrt((x.in+x.out)/maxd);
    const q=el("rect",{x:cx-r,y:cy-r,width:2*r,height:2*r,rx:2,fill:on?"#e6edf3":"#4aa8ff",stroke:"#0e1116",
      "fill-opacity":SEL&&!on?.5:1,style:"cursor:pointer"});
    q.appendChild(el("title",null,x.station+": "+fmt(x.in)+" handoffs in, "+fmt(x.out)+" out, "+fmt(x.aircraft)+" aircraft; position ±"+(x.spread_km||"?")+" km"));
    q.addEventListener("click",e=>{e.stopPropagation();select(x.station);});
    s.appendChild(q);boxes.push([cx-r,cy-r,2*r,2*r]);});
  const hit=(a,b)=>a[0]<b[0]+b[2]&&b[0]<a[0]+a[2]&&a[1]<b[1]+b[3]&&b[1]<a[1]+a[3];
  shown.slice().sort((a,b)=>(b.station===SEL)-(a.station===SEL)||(b.in+b.out)-(a.in+a.out)).slice(0,30).forEach(x=>{
    const cx=X(x.lon),cy=Y(x.lat),w=x.station.length*7.2,h=12;
    for(const [dx,dy] of [[9,-h/2],[-9-w,-h/2],[-w/2,-9-h],[-w/2,9]]){const b=[cx+dx,cy+dy,w,h];
      if(b[0]<0||b[1]<0||b[0]+w>W||b[1]+h>H||boxes.some(q=>hit(b,q)))continue;
      boxes.push(b);const t=el("text",{x:b[0],y:b[1]+h-2,class:"stl","fill-opacity":SEL&&x.station!==SEL?.4:1},x.station);
      t.addEventListener("click",e=>{e.stopPropagation();select(x.station);});s.appendChild(t);break;}});
  placeNames(bgG,X,Y,...view,boxes);
}
function info(){
  const box=$("sel");
  if(!SEL){const t=D.totals;box.textContent=t.placed+" of "+t.stations+" stations placed; "+
    (t.stations-t.placed)+" too few positions to place yet. Busiest 300 pairs drawn.";return;}
  const s=D.stations.find(x=>x.station===SEL);if(!s){box.textContent="";return;}
  const out=D.pairs.filter(p=>p.from===SEL).slice(0,6).map(p=>p.to+" "+fmt(p.handoffs)).join(", ");
  const inn=D.pairs.filter(p=>p.to===SEL).slice(0,6).map(p=>p.from+" "+fmt(p.handoffs)).join(", ");
  box.innerHTML="<b>"+esc(SEL)+"</b>: "+fmt(s.in)+" handoffs in, "+fmt(s.out)+" out, "+fmt(s.aircraft)+" aircraft. "+
    "Hands on to: "+esc(out||"—")+". Takes from: "+esc(inn||"—")+". Click again to clear.";
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
  drawMap();drawTables();info();
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
  box.querySelectorAll(".chip").forEach(c=>c.addEventListener("click",()=>{SEL=null;select(c.dataset.st);$("map").scrollIntoView({behavior:"smooth"});}));
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
