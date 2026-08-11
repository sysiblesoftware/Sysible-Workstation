/* Sysible Linux wallpaper generators — procedural, resolution-independent.
   Injected into a headless Chromium page by render.mjs to export PNGs.
   Exposes window.SYS.render(key, ctx, W, H) and window.SYS.keys. */
(function () {
  function h2(h){if(Array.isArray(h))return h;h=h.replace('#','');return[parseInt(h.slice(0,2),16),parseInt(h.slice(2,4),16),parseInt(h.slice(4,6),16)];}
  function mixc(a,b,t){const A=h2(a),B=h2(b);return[A[0]+(B[0]-A[0])*t,A[1]+(B[1]-A[1])*t,A[2]+(B[2]-A[2])*t];}
  function rgba(c,al){c=h2(c);return "rgba("+(c[0]|0)+","+(c[1]|0)+","+(c[2]|0)+","+al+")";}
  function clamp(x,a,b){return x<a?a:x>b?b:x;}
  function mulberry32(a){return function(){a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};}
  function hexPath(x,cx,cy,r){x.beginPath();for(let i=0;i<6;i++){const a=Math.PI/180*(60*i-90),px=cx+r*Math.cos(a),py=cy+r*Math.sin(a);i?x.lineTo(px,py):x.moveTo(px,py);}x.closePath();}
  const SANS='-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif';
  const MONO='ui-monospace,"SF Mono","JetBrains Mono","Cascadia Code",Menlo,Consolas,monospace';
  const G='#43a047',GH='#63c869',B='#3560d4',BH='#5580ee',TL='#3fa9a0',DG='#2f8f3c',DB='#2f60d4',DT='#2f8f8a';
  const HEX=[[0,-20],[17,-10],[17,10],[0,20],[-17,10],[-17,-10]];
  function hexPoly(x,cx,cy,k){x.beginPath();HEX.forEach(function(p,i){const px=cx+p[0]*k,py=cy+p[1]*k;i?x.lineTo(px,py):x.moveTo(px,py);});x.closePath();}
  function bgLin(x,W,H,a,b){const g=x.createLinearGradient(0,0,W,H);g.addColorStop(0,a);g.addColorStop(1,b);x.fillStyle=g;x.fillRect(0,0,W,H);}
  function vign(x,W,H,a,light){const v=x.createRadialGradient(W/2,H*0.44,Math.min(W,H)*0.16,W/2,H/2,Math.max(W,H)*0.72);v.addColorStop(0,'rgba(0,0,0,0)');v.addColorStop(1,light?('rgba(44,60,96,'+a+')'):('rgba(0,0,0,'+a+')'));x.fillStyle=v;x.fillRect(0,0,W,H);}

  // ---- centered lockup (Mesh) ----
  function drawLogo(x,cx,cy,R,light,markImg,word){const k=R/20;markImg=markImg||window.SYS_MARK;word=word||'SYSIBLE·LINUX';
    const rg=x.createRadialGradient(cx,cy,0,cx,cy,R*2.8);rg.addColorStop(0,light?'rgba(90,140,235,0.14)':'rgba(90,140,240,0.22)');rg.addColorStop(1,'rgba(0,0,0,0)');x.fillStyle=rg;x.fillRect(cx-R*3,cy-R*3,R*6,R*6);
    /* the ACTUAL canonical product mark (SVG) — no hand-drawn copy to drift */
    var S=R*2.327;if(markImg)x.drawImage(markImg,cx-S/2,cy-S/2,S,S);
    x.save();x.textAlign='center';x.textBaseline='top';try{x.letterSpacing=(R*0.05)+'px';}catch(e){}x.font='600 '+(R*0.30)+'px '+SANS;x.fillStyle=light?'rgba(28,42,66,0.9)':'rgba(214,223,238,0.92)';x.fillText(word,cx,cy+R*1.5);
    /* tagline under the wordmark */ try{x.letterSpacing=(R*0.145)+'px';}catch(e){}x.font='600 '+(R*0.125)+'px '+SANS;x.fillStyle=light?'rgba(60,80,120,0.82)':'rgba(150,170,205,0.80)';x.fillText('ENGINEERING · AUTOMATION',cx,cy+R*1.5+R*0.52);x.restore();}
  function drawMesh(x,W,H,light,markImg,word){const s=H/1080;light?bgLin(x,W,H,'#eef1f7','#dfe4ee'):bgLin(x,W,H,'#090b10','#12151e');
    const r=30*s,hw=Math.sqrt(3)*r,vh=1.5*r,gx=W*0.5,gy=H*0.44,gR=Math.min(W,H)*0.52,faint=light?'rgba(58,84,132,0.11)':'rgba(150,170,200,0.055)';
    let row=0;for(let cy=-r;cy<H+r;cy+=vh,row++){const off=(row%2)?hw/2:0;for(let cx=-r+off;cx<W+r;cx+=hw){const d=Math.hypot(cx-gx,cy-gy);hexPath(x,cx,cy,r*0.93);
      if(d<gR){const t=1-d/gR,fx=clamp((cx-(gx-gR))/(2*gR),0,1);x.fillStyle=rgba(mixc('#43a047','#3560d4',fx),(light?0.05:0.06)+(light?0.15:0.30)*t*t);x.fill();
        const sc=light?mixc('#2f8f3c','#2f60d4',fx):mixc('#63c869','#5580ee',fx);x.lineWidth=1.1*s;x.strokeStyle=rgba(sc,(light?0.13:0.16)+(light?0.42:0.55)*t);x.stroke();
      }else{x.lineWidth=1*s;x.strokeStyle=faint;x.stroke();}}}
    const v=x.createRadialGradient(gx,gy,Math.min(W,H)*0.18,W/2,H/2,Math.max(W,H)*0.72);v.addColorStop(0,'rgba(0,0,0,0)');v.addColorStop(1,light?'rgba(42,58,92,0.12)':'rgba(0,0,0,0.55)');x.fillStyle=v;x.fillRect(0,0,W,H);
    drawLogo(x,gx,gy,Math.min(W,H)*0.082,light,markImg,word);}

  // ---- bases (light-aware) ----
  function base_fleet(x,W,H,light){const s=H/1080;light?bgLin(x,W,H,'#eef1f7','#e0e5ef'):bgLin(x,W,H,'#0a0d13','#0e1119');
    const rnd=mulberry32(11),N=66,p=[];for(let i=0;i<N;i++)p.push({x:rnd()*W,y:rnd()*H,hub:i%6===0});
    const TH=W*0.17,eG=light?DG:G,eB=light?DB:B;
    for(let i=0;i<N;i++)for(let j=i+1;j<N;j++){const d=Math.hypot(p[i].x-p[j].x,p[i].y-p[j].y);if(d<TH){x.lineWidth=1.05*s;x.strokeStyle=rgba(mixc(eG,eB,p[i].x/W),(light?0.22:0.16)*(1-d/TH));x.beginPath();x.moveTo(p[i].x,p[i].y);x.lineTo(p[j].x,p[j].y);x.stroke();}}
    for(const n of p){const col=mixc(mixc(light?DG:G,light?DT:TL,clamp(n.y/H,0,1)),light?DB:B,clamp(n.x/W,0,1));x.save();if(n.hub&&!light){x.shadowBlur=24*s;x.shadowColor=rgba(col,0.95);}x.fillStyle=rgba(col,n.hub?1:(light?0.82:0.9));x.beginPath();x.arc(n.x,n.y,(n.hub?6:3)*s,0,7);x.fill();x.restore();}vign(x,W,H,light?0.14:0.48,light);}
  function base_topo(x,W,H,light){const s=H/1080;light?bgLin(x,W,H,'#eef1f7','#dfe4ee'):bgLin(x,W,H,'#0a0d12','#0d1017');
    const cx=W*0.52,cy=H*0.5,K=17,base=Math.min(W,H)*0.045,cG=light?DG:G,cB=light?DB:B;
    for(let k=0;k<K;k++){const rr=base*(k+1);x.beginPath();for(let a=0;a<=Math.PI*2+0.01;a+=0.03){const pp=rr+Math.sin(a*3+k*0.7)*rr*0.11+Math.cos(a*5-k*0.5)*rr*0.05;const px=cx+pp*Math.cos(a),py=cy+pp*0.6*Math.sin(a);a?x.lineTo(px,py):x.moveTo(px,py);}const fade=Math.sin(Math.PI*(k+1)/(K+1));x.lineWidth=1.25*s;x.strokeStyle=rgba(mixc(cG,cB,k/(K-1)),(light?0.12:0.09)+(light?0.34:0.28)*fade);x.stroke();}vign(x,W,H,light?0.13:0.45,light);}
  function base_aurora(x,W,H,light){light?bgLin(x,W,H,'#eef1f7','#e2e7f0'):bgLin(x,W,H,'#0c0f16','#090b10');
    x.save();if(!light)x.globalCompositeOperation='lighter';
    function bloom(bx,by,rr,col,al){const rg=x.createRadialGradient(bx,by,0,bx,by,rr);rg.addColorStop(0,rgba(col,al));rg.addColorStop(0.5,rgba(col,al*0.4));rg.addColorStop(1,rgba(col,0));x.fillStyle=rg;x.fillRect(0,0,W,H);}
    if(light){bloom(W*0.76,H*0.30,W*0.6,DB,0.22);bloom(W*0.64,H*0.5,W*0.52,DG,0.17);bloom(W*0.82,H*0.24,W*0.34,'#4a7be0',0.16);}else{bloom(W*0.78,H*0.30,W*0.6,B,0.30);bloom(W*0.66,H*0.44,W*0.5,G,0.24);bloom(W*0.82,H*0.24,W*0.32,BH,0.22);}
    x.restore();vign(x,W,H,light?0.12:0.4,light);}

  // ---- bottom-left lockup ----
  function drawMark(x,cx,cy,R,light){var S=R*2.327;if(window.SYS_MARK)x.drawImage(window.SYS_MARK,cx-S/2,cy-S/2,S,S);}
  function lockup(x,W,H,light){const R=H*0.048*0.72,mB=H*0.13,mLx=W*0.06,k=R/20,cx=mLx+17*k,cy=H-mB-R;
    const rg=x.createRadialGradient(0,H,0,0,H,W*0.55);rg.addColorStop(0,light?'rgba(236,238,244,0.42)':'rgba(0,0,0,0.38)');rg.addColorStop(1,'rgba(0,0,0,0)');x.fillStyle=rg;x.fillRect(0,0,W,H);
    drawMark(x,cx,cy,R,light);
    const tx=cx+17*k+R*0.6,wSize=R*0.62,tSize=R*0.235,white=light?'#14203a':'#eaeef6',accent=light?'#2f60d4':'#6f9bff',mut=light?'rgba(40,55,85,0.72)':'rgba(160,175,200,0.85)';
    x.textAlign='left';x.textBaseline='alphabetic';x.font='700 '+wSize+'px '+SANS;try{x.letterSpacing=(wSize*0.015)+'px';}catch(e){}
    const wy=cy+wSize*0.06;let px=tx;x.fillStyle=white;x.fillText('SYSIBLE',px,wy);px+=x.measureText('SYSIBLE').width;x.fillStyle=accent;x.fillText('·',px,wy);px+=x.measureText('·').width;x.fillStyle=white;x.fillText('LINUX',px,wy);
    /* tagline removed */ }

  // ---- SysTerm badge + center variations ----
  function sysTermBadge(x,cx,cy,R){const k=R/20;
    const glow=x.createRadialGradient(cx,cy,0,cx,cy,R*2.5);glow.addColorStop(0,'rgba(80,130,235,0.30)');glow.addColorStop(0.6,'rgba(60,150,110,0.10)');glow.addColorStop(1,'rgba(0,0,0,0)');x.fillStyle=glow;x.fillRect(cx-R*2.7,cy-R*2.7,R*5.4,R*5.4);
    /* the ACTUAL SysTerm icon (canonical SVG) */
    var S=R*2.327;if(window.SYS_TERM)x.drawImage(window.SYS_TERM,cx-S/2,cy-S/2,S,S);}
  function base_beacon(x,W,H){const s=H/1080;bgLin(x,W,H,'#0a0c12','#10131c');const cx=W*0.5,cy=H*0.47,M=Math.min(W,H),r0=M*0.20,step=M*0.072,rings=9;
    for(let k=0;k<rings;k++){hexPath(x,cx,cy,r0+k*step);const a=0.42*(1-k/rings)+0.04;x.lineWidth=(1.5-0.06*k)*s;x.strokeStyle=rgba(mixc(GH,BH,k/(rings-1)),a);x.stroke();}
    vign(x,W,H,0.5,false);sysTermBadge(x,cx,cy,M*0.145);}
  function base_hub(x,W,H){const s=H/1080;bgLin(x,W,H,'#0a0c12','#0e1119');const cx=W*0.5,cy=H*0.47,M=Math.min(W,H);
    const bl=x.createRadialGradient(cx,cy,0,cx,cy,M*0.5);bl.addColorStop(0,'rgba(60,120,220,0.16)');bl.addColorStop(0.5,'rgba(50,140,90,0.07)');bl.addColorStop(1,'rgba(0,0,0,0)');x.fillStyle=bl;x.fillRect(0,0,W,H);
    const rnd=mulberry32(9),N=20;for(let i=0;i<N;i++){const ang=rnd()*Math.PI*2,rad=M*(0.28+rnd()*0.26),nx=cx+Math.cos(ang)*rad,ny=cy+Math.sin(ang)*rad*0.82,col=mixc(G,B,(nx/W));x.strokeStyle=rgba(col,0.16);x.lineWidth=1.1*s;x.beginPath();x.moveTo(cx,cy);x.lineTo(nx,ny);x.stroke();x.save();x.shadowBlur=14*s;x.shadowColor=rgba(col,0.8);x.fillStyle=rgba(col,0.9);x.beginPath();x.arc(nx,ny,3.4*s,0,7);x.fill();x.restore();}
    vign(x,W,H,0.5,false);sysTermBadge(x,cx,cy,M*0.145);}

  const R = {
    'mesh-dark':      function(x,W,H){drawMesh(x,W,H,false);},
    'mesh-light':     function(x,W,H){drawMesh(x,W,H,true);},
    'systerm-dark':    function(x,W,H){drawMesh(x,W,H,false,window.SYS_TERM,'SYSTERM');},
    'systerm-light':   function(x,W,H){drawMesh(x,W,H,true,window.SYS_TERM,'SYSTERM');},
    'controller-dark': function(x,W,H){drawMesh(x,W,H,false,window.SYS_CTRL,'SYSIBLE·CONTROLLER');},
    'controller-light':function(x,W,H){drawMesh(x,W,H,true,window.SYS_CTRL,'SYSIBLE·CONTROLLER');},
    'fleet-dark':     function(x,W,H){base_fleet(x,W,H,false);lockup(x,W,H,false);},
    'fleet-light':    function(x,W,H){base_fleet(x,W,H,true);lockup(x,W,H,true);},
    'contour-dark':   function(x,W,H){base_topo(x,W,H,false);lockup(x,W,H,false);},
    'contour-light':  function(x,W,H){base_topo(x,W,H,true);lockup(x,W,H,true);},
    'aurora-dark':    function(x,W,H){base_aurora(x,W,H,false);lockup(x,W,H,false);},
    'aurora-light':   function(x,W,H){base_aurora(x,W,H,true);lockup(x,W,H,true);},
    'beacon':         function(x,W,H){base_beacon(x,W,H);},
    'hub':            function(x,W,H){base_hub(x,W,H);},
  };
  window.SYS = { keys: Object.keys(R), render: function(key,x,W,H){ R[key](x,W,H); } };
})();
