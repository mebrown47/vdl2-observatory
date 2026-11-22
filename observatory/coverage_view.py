# Copyright (c) 2026 Mike Brown
# SPDX-License-Identifier: GPL-3.0-or-later
"""
VDL2 Observatory — the Coverage page (/coverage), drawn from /api/coverage
(coverage.py): where the receiver hears aircraft and how strongly, on a map,
on a sky plot of azimuth and elevation, and against distance.

The map helpers (outlines, town names) are the Overview page's
(vdl2_view.py), repeated here so each page stands alone.
"""

COVERAGE_PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VDL2 Coverage</title>
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
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:14px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
  .card .k{color:var(--dim);font-size:11.5px;text-transform:uppercase;letter-spacing:.6px}
  .card .v{font-size:26px;font-weight:600;margin-top:4px}
  .card .v small{font-size:13px;color:var(--dim);font-weight:400}
  .loc{color:var(--dim);font-size:12.5px;margin:0 0 14px}
  .loc code{color:var(--fg)}
  .grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px}
  @media(max-width:1000px){.grid{grid-template-columns:minmax(0,1fr)}}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;
    padding:14px 16px 8px;margin-bottom:14px;overflow:hidden}
  .panel h2{font-size:13px;margin:0 0 10px;font-weight:600;color:var(--fg)}
  .panel h2 .hint{color:var(--dim);font-weight:400;font-size:11.5px}
  svg{display:block;overflow:hidden}
  .gl{stroke:var(--grid);stroke-width:1}
  .mapax{fill:var(--dim);font-size:11px}
  .plc{fill:var(--place);font-size:10.5px}
  .rng{fill:none;stroke:#8b98a5;stroke-opacity:.45;stroke-dasharray:3 4}
  .rngl{fill:var(--dim);font-size:10.5px}
  .ax{fill:var(--dim);font-size:10.5px}
  .empty{color:var(--dim);padding:30px;text-align:center;font-size:13px}
  .note{color:var(--dim);font-size:12px;margin:6px 0 2px}
  .scale{display:flex;align-items:center;gap:8px;color:var(--dim);font-size:11.5px;margin:2px 0 8px}
  .scale i{display:inline-block;width:160px;height:9px;border-radius:2px;
    background:linear-gradient(90deg,#440154,#3b528b,#21918c,#5ec962,#fde725)}
</style></head>
<body>
<header>
  <h1>VDL2 Observatory</h1>
  <nav class="nav"><a href="/">Overview</a><a href="/messages">Messages</a><a href="/flights">Flights</a><a href="/coverage" class="on">Coverage</a><a id="livelink" href="#" hidden>Live</a></nav>
  <span class="sub">where this receiver hears aircraft, and how strongly</span>
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
  <div class="loc" id="loc"></div>
  <div class="panel">
    <h2>Map <span class="hint">0.1° cells where aircraft were heard, coloured by median SNR of the frames that carried their positions; dashed: the farthest this receiver hears in each 5° direction (95th percentile)</span></h2>
    <div class="scale"><span>SNR</span><span>10 dB</span><i></i><span>40 dB</span></div>
    <div id="map"></div>
    <div class="note">Only decoded frames carry a position, so this shows where aircraft are heard, not where they are missed. Map: Natural Earth.</div>
  </div>
  <div class="grid">
    <div class="panel">
      <h2>Sky <span class="hint">azimuth around, elevation inwards (horizon at the edge, 10° and up at the centre), median SNR; aircraft with a known altitude</span></h2>
      <div id="sky"></div>
    </div>
    <div class="panel">
      <h2>SNR by distance <span class="hint">median, and the 10th to 90th percentile; bars: positions in each 25 km</span></h2>
      <div id="dist"></div>
    </div>
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
function fmt(n){return n==null?"—":n>=1e4?(n/1e3).toFixed(0)+"k":n>=1e3?(n/1e3).toFixed(1)+"k":String(n);}
let hours=168,D=null;
// viridis, 10 to 40 dB
const VIR=[[68,1,84],[59,82,139],[33,145,140],[94,201,98],[253,231,37]];
function col(snr){const x=Math.max(0,Math.min(1,(snr-10)/30))*(VIR.length-1),i=Math.min(VIR.length-2,Math.floor(x)),f=x-i;
  const c=VIR[i].map((v,k)=>Math.round(v+(VIR[i+1][k]-v)*f));return "rgb("+c.join(",")+")";}

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
    g.appendChild(el("text",{x:x+4,y:y+3.5,class:"plc"},p.n));
    if(++n>=30)break;
  }
}
// the point dist_km from (lat, lon) along bearing brg (degrees)
function dest(lat,lon,brg,km){const R=6371,d=km/R,b=brg*Math.PI/180,f1=lat*Math.PI/180,l1=lon*Math.PI/180;
  const f2=Math.asin(Math.sin(f1)*Math.cos(d)+Math.cos(f1)*Math.sin(d)*Math.cos(b));
  const l2=l1+Math.atan2(Math.sin(b)*Math.sin(d)*Math.cos(f1),Math.cos(d)-Math.sin(f1)*Math.sin(f2));
  return [f2*180/Math.PI,((l2*180/Math.PI)+540)%360-180];}

function drawMap(){
  const host=$("map"),cells=D.cells,st=D.station,cs=D.cell_deg;
  if(!cells.length){host.innerHTML='<div class="empty">no positions in the last '+label()+'</div>';return;}
  // the view: the cells (2nd to 98th percentile, by positions) and the range outline
  const wq=(arr,q)=>{const s=arr.slice().sort((a,b)=>a[0]-b[0]),tot=s.reduce((t,x)=>t+x[1],0);let acc=0;
    for(const x of s){acc+=x[1];if(acc>=q*tot)return x[0];}return s[s.length-1][0];};
  let la0=wq(cells.map(c=>[c[0],c[2]]),.02),la1=wq(cells.map(c=>[c[0]+cs,c[2]]),.98);
  let lo0=wq(cells.map(c=>[c[1],c[2]]),.02),lo1=wq(cells.map(c=>[c[1]+cs,c[2]]),.98);
  let ring=null;
  if(st&&D.sectors){ring=D.sectors.filter(s=>s[2]!=null).map(s=>dest(st.lat,st.lon,s[0]+2.5,s[2]));
    ring.forEach(p=>{la0=Math.min(la0,p[0]);la1=Math.max(la1,p[0]);lo0=Math.min(lo0,p[1]);lo1=Math.max(lo1,p[1]);});}
  const k=Math.cos((la0+la1)/2*Math.PI/180),pad=Math.max(.2,(la1-la0)*.04);
  la0-=pad;la1+=pad;lo0-=pad/k;lo1+=pad/k;
  const W=Math.max(260,host.clientWidth||900),H=Math.round(Math.max(320,Math.min(640,W*(la1-la0)/((lo1-lo0)*k))));
  const sc=Math.min(W/((lo1-lo0)*k),H/(la1-la0));
  const X=lo=>(lo-lo0)*k*sc+(W-(lo1-lo0)*k*sc)/2,Y=la=>(la1-la)*sc+(H-(la1-la0)*sc)/2;
  host.innerHTML="";const s=el("svg",{viewBox:"0 0 "+W+" "+H,width:W,height:H});host.appendChild(s);
  s.appendChild(el("rect",{x:0,y:0,width:W,height:H,fill:"var(--water)",stroke:"var(--line)"}));
  const lonAt=x=>lo0+(x-X(lo0))/(k*sc),latAt=y=>la1-(y-Y(la1))/sc;
  const view=[lonAt(0),latAt(H),lonAt(W),latAt(0)],bgG=outlines(s,X,Y,...view);
  const cw=cs*k*sc,ch=cs*sc,maxn=Math.max(...cells.map(c=>c[2]));
  cells.forEach(c=>{const r=el("rect",{x:X(c[1]),y:Y(c[0]+cs),width:cw+.3,height:ch+.3,fill:col(c[3]),
      "fill-opacity":.35+.55*Math.min(1,Math.log(1+c[2])/Math.log(1+Math.min(maxn,30)))});
    r.appendChild(el("title",null,c[0].toFixed(1)+", "+c[1].toFixed(1)+": "+c[2]+" positions, median SNR "+c[3]+" dB, best "+c[4]+" dB"));
    s.appendChild(r);});
  const boxes=[];
  if(st){const cx=X(st.lon),cy=Y(st.lat);
    [100,200,300,400,500].forEach(r=>{const ry=r/111*sc,rx=ry;
      if(ry>Math.max(W,H))return;
      s.appendChild(el("ellipse",{cx:cx,cy:cy,rx:rx,ry:ry,class:"rng"}));
      s.appendChild(el("text",{x:cx+3,y:cy-ry-3,class:"rngl"},r+" km"));boxes.push([cx,cy-ry-14,40,12]);});
    if(ring&&ring.length>2){let d="";ring.forEach((p,i)=>{d+=(i?"L":"M")+X(p[1]).toFixed(1)+" "+Y(p[0]).toFixed(1);});
      s.appendChild(el("path",{d:d+"Z",fill:"none",stroke:"#e6edf3","stroke-width":1.6,"stroke-dasharray":"6 4","stroke-opacity":.85}));}
    s.appendChild(el("rect",{x:cx-5,y:cy-5,width:10,height:10,fill:"var(--accent)",stroke:"#0e1116"}));boxes.push([cx-5,cy-5,10,10]);}
  placeNames(bgG,X,Y,...view,boxes);
}

function drawSky(){
  const host=$("sky");
  if(!D.station){host.innerHTML='<div class="empty">needs the receiver\'s location (see above)</div>';return;}
  if(!D.sky.length){host.innerHTML='<div class="empty">no positions with an altitude yet</div>';return;}
  const W=Math.max(260,Math.min(560,host.clientWidth||520)),H=W,cx=W/2,cy=H/2,R=W/2-26;
  const EMAX=10,EMIN=-1,rad=e=>R*(EMAX-Math.max(EMIN,Math.min(EMAX,e)))/(EMAX-EMIN);
  host.innerHTML="";const s=el("svg",{viewBox:"0 0 "+W+" "+H,width:W,height:H});host.appendChild(s);
  s.appendChild(el("circle",{cx:cx,cy:cy,r:R,fill:"var(--water)",stroke:"var(--line)"}));
  const pt=(az,r)=>[cx+r*Math.sin(az*Math.PI/180),cy-r*Math.cos(az*Math.PI/180)];
  const maxn=Math.max(...D.sky.map(c=>c[3]));
  D.sky.forEach(([az,e0,e1,n,med])=>{const r0=rad(e0),r1=rad(e1),a0=az,a1=az+10;
    const [x0,y0]=pt(a0,r0),[x1,y1]=pt(a1,r0),[x2,y2]=pt(a1,r1),[x3,y3]=pt(a0,r1);
    const d="M"+x0+" "+y0+"A"+r0+" "+r0+" 0 0 1 "+x1+" "+y1+"L"+x2+" "+y2+(r1>0?"A"+r1+" "+r1+" 0 0 0 "+x3+" "+y3:"")+"Z";
    const p=el("path",{d:d,fill:col(med),"fill-opacity":.3+.65*Math.min(1,Math.log(1+n)/Math.log(1+Math.min(maxn,40))),stroke:"none"});
    p.appendChild(el("title",null,"azimuth "+az+"–"+(az+10)+"°, elevation "+e0+"–"+(e1>EMAX?"90":e1)+"°: "+n+" positions, median SNR "+med+" dB"));
    s.appendChild(p);});
  [0,2,5].forEach(e=>{s.appendChild(el("circle",{cx:cx,cy:cy,r:rad(e),fill:"none",stroke:"#8b98a5","stroke-opacity":.5,"stroke-dasharray":"3 4"}));
    s.appendChild(el("text",{x:cx+3,y:cy-rad(e)+12,class:"ax"},e+"°"));});
  s.appendChild(el("text",{x:cx+3,y:cy+4,class:"ax"},"10°+"));
  for(let a=0;a<360;a+=30){const [x,y]=pt(a,R);s.appendChild(el("line",{x1:cx,y1:cy,x2:x,y2:y,class:"gl"}));}
  [["N",0],["E",90],["S",180],["W",270]].forEach(([t,a])=>{const [x,y]=pt(a,R+13);
    s.appendChild(el("text",{x:x,y:y+4,"text-anchor":"middle",class:"ax"},t));});
}

function drawDist(){
  const host=$("dist");
  if(!D.station){host.innerHTML='<div class="empty">needs the receiver\'s location (see above)</div>';return;}
  const rows=D.distance.filter(r=>r[0]<=600);
  if(!rows.length){host.innerHTML='<div class="empty">no positions yet</div>';return;}
  const W=Math.max(260,host.clientWidth||520),H=Math.round(Math.min(420,Math.max(260,W*.62))),pl=40,pr=10,pt=10,pb=28;
  const xmax=Math.max(100,Math.ceil((rows[rows.length-1][0]+25)/100)*100),ymax=50;
  const X=d=>pl+(W-pl-pr)*d/xmax,Y=v=>pt+(H-pt-pb)*(1-v/ymax);
  host.innerHTML="";const s=el("svg",{viewBox:"0 0 "+W+" "+H,width:W,height:H});host.appendChild(s);
  for(let v=0;v<=ymax;v+=10){s.appendChild(el("line",{x1:pl,y1:Y(v),x2:W-pr,y2:Y(v),class:"gl"}));
    s.appendChild(el("text",{x:pl-6,y:Y(v)+3,"text-anchor":"end",class:"ax"},v+" dB"));}
  for(let d=0;d<=xmax;d+=100)s.appendChild(el("text",{x:X(d),y:H-8,"text-anchor":"middle",class:"ax"},d+" km"));
  const maxn=Math.max(...rows.map(r=>r[1]));
  rows.forEach(r=>{const h=(H-pt-pb)*.28*r[1]/maxn;
    const b=el("rect",{x:X(r[0])+1,y:Y(0)-h,width:Math.max(1,X(25)-X(0)-2),height:h,fill:"#4aa8ff","fill-opacity":.22});
    b.appendChild(el("title",null,r[0]+"–"+(r[0]+25)+" km: "+r[1]+" positions, SNR "+r[2]+" / "+r[3]+" / "+r[4]+" dB (10th / median / 90th)"));s.appendChild(b);});
  const mid=r=>X(r[0]+12.5);let band="";
  rows.forEach((r,i)=>{band+=(i?"L":"M")+mid(r)+" "+Y(r[4]);});
  rows.slice().reverse().forEach(r=>{band+="L"+mid(r)+" "+Y(r[2]);});
  s.appendChild(el("path",{d:band+"Z",fill:"#5ec962","fill-opacity":.18,stroke:"none"}));
  let line="";rows.forEach((r,i)=>{line+=(i?"L":"M")+mid(r)+" "+Y(r[3]);});
  s.appendChild(el("path",{d:line,fill:"none",stroke:"#5ec962","stroke-width":2}));
}

function label(){return hours>=720?"30 days":hours>=168?"7 days":hours+" h";}
function card(k,v,sub){return '<div class="card"><div class="k">'+k+'</div><div class="v">'+v+(sub?' <small>'+sub+'</small>':'')+'</div></div>';}
function render(){
  const T=D.totals,st=D.station;
  let c=card("Positions placed",fmt(T.positions),"last "+label())+card("Aircraft",fmt(T.aircraft))+card("Median SNR",T.median_snr!=null?T.median_snr+" dB":"—");
  if(st)c+=card("Median range",T.median_km!=null?T.median_km+" km":"—")+card("95% within",T.p95_km!=null?T.p95_km+" km":"—","farthest "+(T.max_km||"—")+" km");
  $("cards").innerHTML=c;
  $("loc").innerHTML=st?"Receiver location: "+esc(st.source)+", shown to 0.1°."+(T.beyond_horizon?" "+T.beyond_horizon+" positions farther than a VHF receiver can hear were set aside.":"")
    :'The receiver\'s location isn\'t set, so there are no bearings, ranges or elevations. Set <code>STATION="LAT,LON,ANTENNA_M"</code> in <code>/etc/vdl2-observatory.conf</code> (antenna height above sea level, in metres; or re-run <code>./install.sh --reconfigure</code>), then <code>sudo systemctl restart vdl2-observatory</code>. With iridium-observatory running on this machine, its location is used instead.';
  drawMap();drawSky();drawDist();
}
async function load(){
  const st=$("status");
  try{const r=await fetch("/api/coverage?hours="+hours),d=await r.json();
    if(d.error){$("cards").innerHTML="";$("map").innerHTML='<div class="empty">'+esc(d.error)+'</div>';
      st.innerHTML='<span class="dot" style="background:var(--warn)"></span>'+esc(d.error);return;}
    D=d;render();st.innerHTML='<span class="dot"></span>updated '+new Date().toLocaleTimeString();
  }catch(e){st.innerHTML='<span class="dot" style="background:var(--warn)"></span>fetch failed';}
}
document.querySelectorAll("#win button").forEach(b=>b.addEventListener("click",()=>{
  document.querySelectorAll("#win button").forEach(x=>x.classList.toggle("on",x===b));hours=+b.dataset.h;load();}));
let rt=null;window.addEventListener("resize",()=>{clearTimeout(rt);rt=setTimeout(()=>{if(D)render();},200);});
load();setInterval(load,300000);
</script>
</body></html>
"""
