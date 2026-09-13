/* Local software 3D scene. Recorded XY only; road width/car size/elevation are schematic. */
window.createOrbScene3D = function(canvas, ctx, track, pit, colors, invalidate) {
  const xs=track.x, ys=track.y, n=xs.length;
  const minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys);
  const cx=(minX+maxX)/2,cy=(minY+maxY)/2,unit=Math.max(maxX-minX,maxY-minY)/2.7||1;
  let yaw=-1.0,elevation=.55,zoom=1,view='3d',drag=null,W=800,H=360,focal=120,offsetX=400,offsetY=180;
  const road=.018, level=.036;
  function world(x,y,h=level){return [(x-cx)/unit,(y-cy)/unit,h];}
  function project(p){
    const a=p[0]*Math.cos(yaw)-p[1]*Math.sin(yaw),b=p[0]*Math.sin(yaw)+p[1]*Math.cos(yaw);
    const d=4+b*Math.cos(elevation)+p[2]*Math.sin(elevation);
    const k=focal*zoom/d;
    return [offsetX+a*k,offsetY+(b*Math.sin(elevation)-p[2]*Math.cos(elevation))*k,d];
  }
  const points=xs.map((x,i)=>world(x,ys[i]));
  const edges=points.map((p,i)=>{let a=points[(i+n-1)%n],b=points[(i+1)%n];let dx=b[0]-a[0],dy=b[1]-a[1],len=Math.hypot(dx,dy)||1;return [[p[0]-dy/len*road,p[1]+dx/len*road,level],[p[0]+dy/len*road,p[1]-dx/len*road,level]];});
  function poly(points,fill,stroke){const q=points.map(project);ctx.beginPath();q.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));ctx.closePath();ctx.fillStyle=fill;ctx.fill();if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=.7;ctx.stroke();}}
  function line(points,color,width=1){ctx.beginPath();points.map(project).forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke();}
  function label(p,text,color){const q=project(p);ctx.font='500 10px system-ui';ctx.textAlign='center';ctx.fillStyle=color;ctx.fillText(text,q[0],q[1]);}
  function box(center,sx,sy,sz,angle,fill){
    let verts=[];for(let h of [0,sz])for(let y of [-sy,sy])for(let x of [-sx,sx])verts.push([center[0]+x*Math.cos(angle)-y*Math.sin(angle),center[1]+x*Math.sin(angle)+y*Math.cos(angle),center[2]+h]);
    const faces=[[0,1,3,2],[0,4,5,1],[1,5,7,3],[3,7,6,2],[2,6,4,0],[4,6,7,5]];
    faces.sort((a,b)=>b.reduce((s,i)=>s+project(verts[i])[2],0)-a.reduce((s,i)=>s+project(verts[i])[2],0));
    for(const f of faces) poly(f.map(i=>verts[i]),f[0]===4?fill:'#617686',fill);
  }
  function car(pos,ahead,color,ghost){
    const p=world(pos[0],pos[1],level+.012),next=world(ahead[0],ahead[1]);const angle=Math.atan2(next[1]-p[1],next[0]-p[0]);
    const at=(x,y,h)=>[p[0]+x*Math.cos(angle)-y*Math.sin(angle),p[1]+x*Math.sin(angle)+y*Math.cos(angle),p[2]+h];
    ctx.save();ctx.globalAlpha=ghost ? .86 : 1;
    const g=project(p);ctx.beginPath();ctx.ellipse(g[0],g[1]+5,14,6,0,0,Math.PI*2);ctx.fillStyle=ghost?'#5cdcc43a':'#b9d8ff24';ctx.fill();
    for(const x of [-.035,.037])for(const y of [-.024,.024])box(at(x,y,0),.013,.008,.013,angle,'#18222e');
    box(at(0,0,.002),.05,.012,.019,angle,color);box(at(-.039,0,.018),.008,.037,.009,angle,color);
    box(at(.04,0,.002),.009,.033,.008,angle,color);box(at(-.004,0,.02),.015,.011,.012,angle,'#23384a');
    ctx.restore();return project(at(0,0,.08));
  }
  function draw(state,locations){
    W=canvas.clientWidth;H=canvas.clientHeight;const dpr=window.devicePixelRatio||1;ctx.setTransform(dpr,0,0,dpr,0,0);
    // Fit the projected recorded circuit with padding before user zoom, at every camera angle.
    focal=1;offsetX=0;offsetY=0;const oldZoom=zoom;zoom=1;const bounds=points.map(project);zoom=oldZoom;const loX=Math.min(...bounds.map(q=>q[0])),hiX=Math.max(...bounds.map(q=>q[0])),loY=Math.min(...bounds.map(q=>q[1])),hiY=Math.max(...bounds.map(q=>q[1]));
    focal=Math.min((W-100)/(hiX-loX||1),(H-76)/(hiY-loY||1));offsetX=W/2-(loX+hiX)*focal/2;offsetY=H/2-(loY+hiY)*focal/2;
    ctx.clearRect(0,0,W,H);
    const bg=ctx.createRadialGradient(W*.6,H*.3,10,W*.5,H*.5,W*.65);bg.addColorStop(0,'#1e3443');bg.addColorStop(.65,'#0e1b29');bg.addColorStop(1,'#0b141f');ctx.fillStyle=bg;ctx.fillRect(0,0,W,H);
    for(let v=-2;v<=2.001;v+=.2){line([[v,-2,-.015],[v,2,-.015]],'#33526925');line([[-2,v,-.015],[2,v,-.015]],'#33526925');}
    line([...points.map(p=>[p[0],p[1],0]),[points[0][0],points[0][1],0]],'#00000045',18);
    const segments=edges.map((e,i)=>({e,next:edges[(i+1)%n],p:points[i]})).sort((a,b)=>project(b.p)[2]-project(a.p)[2]);
    for(const {e,next} of segments){
      poly([e[0],next[0],[next[0][0],next[0][1],0],[e[0][0],e[0][1],0]],'#314657');
      poly([e[1],next[1],[next[1][0],next[1][1],0],[e[1][0],e[1][1],0]],'#243748');
      poly([e[0],next[0],next[1],e[1]],'#71838e');
    }
    line([...edges.map(e=>e[0]),edges[0][0]],'#d5e5ec88',1.15);
    line([...edges.map(e=>e[1]),edges[0][1]],'#9fc6d078',1);
    if(pit&&pit.x)line(pit.x.map((x,i)=>world(x,pit.y[i],level+.002)),'#c9b792a0',2);
    // The dotted centre line is ornamental; recorded geometry is unchanged.
    ctx.setLineDash([2,8]);line([...points,points[0]],'#ecf8ff28',.8);ctx.setLineDash([]);
    for(const [distance,name] of [[0,'S / F'],[track.sector1_end_s,'SECTOR 2'],[track.sector2_end_s,'SECTOR 3']]){if(distance==null||!Number.isFinite(distance))continue;const i=Math.min(n-1,Math.floor(distance/track.L*n));label([points[i][0],points[i][1],.14],name,'#a6becb');}
    const cars=locations ? [{p:locations.actual,next:locations.actualNext,c:'#e5efff',g:false},{p:locations.ghost,next:locations.ghostNext,c:'#6fe1ca',g:true}].sort((a,b)=>project(world(...b.p))[2]-project(world(...a.p))[2]) : [];
    const anchors=cars.map(c=>({c,q:car(c.p,c.next,c.c,c.g)}));
    const close=anchors.length===2 && Math.hypot(anchors[0].q[0]-anchors[1].q[0],anchors[0].q[1]-anchors[1].q[1])<90;
    for(const {c,q} of anchors){const dx=close?(c.g?38:-38):0,dy=close?20:-16;ctx.font='600 10px system-ui';ctx.textAlign='center';ctx.fillStyle='#0b1826';ctx.fillRect(q[0]+dx-26,q[1]+dy-10,52,16);ctx.fillStyle=c.c;ctx.fillText(c.g?'GHOST':'ACTUAL',q[0]+dx,q[1]+dy+1);ctx.strokeStyle=c.c+'88';ctx.beginPath();ctx.moveTo(q[0],q[1]);ctx.lineTo(q[0]+dx,q[1]+dy-8);ctx.stroke();}
    ctx.fillStyle='#9ab1c2';ctx.font='11px system-ui';ctx.textAlign='left';ctx.fillText(view==='3d'?'3D CIRCUIT · DRAG TO ORBIT':'TOP VIEW · DRAG TO ROTATE',18,24);
  }
  canvas.addEventListener('pointerdown',e=>{drag=[e.clientX,e.clientY,yaw,elevation];canvas.setPointerCapture(e.pointerId);});
  canvas.addEventListener('pointermove',e=>{if(!drag)return;yaw=drag[2]+(e.clientX-drag[0])*.008;if(view==='3d')elevation=Math.max(.3,Math.min(1.4,drag[3]+(e.clientY-drag[1])*.005));invalidate();});
  canvas.addEventListener('pointerup',()=>{drag=null;});canvas.addEventListener('pointercancel',()=>{drag=null;});
  canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.6,Math.min(1.7,zoom-e.deltaY*.0007));invalidate();},{passive:false});
  return {draw,setView(v){view=v;elevation=v==='top'?Math.PI/2:.55;invalidate();},rotate(v){yaw+=v;invalidate();},zoom(v){zoom=Math.max(.6,Math.min(1.7,zoom+v));invalidate();},reset(){yaw=-1.0;elevation=.55;zoom=1;view='3d';invalidate();}};
};
