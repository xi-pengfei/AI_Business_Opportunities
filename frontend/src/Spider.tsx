import { useEffect, useRef, useState } from "react";
import { cargoKey, cargoText, fragmentColor, type Cargo } from "./fragments";

type Point = {x:number;y:number};
type Foot = Point & {from:Point;to:Point;step:number};
const clamp = (n:number,a=0,b=1) => Math.max(a,Math.min(b,n));
const ease = (n:number) => { const t=clamp(n); return t*t*(3-2*t); };
const mix = (a:Point,b:Point,t:number):Point => ({x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t});
const distance = (a:Point,b:Point) => Math.hypot(a.x-b.x,a.y-b.y);

// Canvas is decorative. All evidence remains selectable DOM text in the document/table.
// Only a committed incoming item starts a journey; a quiet source never invents one.
export function Spider({item,onDelivered}: {item:Cargo|null;searching?:boolean;onDelivered:()=>void}) {
  const ref=useRef<HTMLCanvasElement>(null);
  const callback=useRef(onDelivered); callback.current=onDelivered;
  const pose=useRef({x:140,y:180,angle:-Math.PI/2,feet:[] as Foot[]});
  const completed=useRef<string|null>(null);
  const [size,setSize]=useState('');
  const [reduced,setReduced]=useState(()=>matchMedia('(prefers-reduced-motion: reduce)').matches);
  useEffect(()=>{
    const media=matchMedia('(prefers-reduced-motion: reduce)');
    const change=()=>setReduced(media.matches); media.addEventListener('change',change);
    const parent=ref.current?.parentElement;
    const observer=new ResizeObserver(([entry])=>setSize(`${entry.contentRect.width}:${entry.contentRect.height}`));
    if(parent) observer.observe(parent);
    return ()=>{observer.disconnect();media.removeEventListener('change',change);};
  },[]);
  useEffect(()=>{
    const canvas=ref.current, cargo=item;
    if(!canvas) return;
    const parent=canvas.parentElement!,ctx=canvas.getContext('2d');
    if(!ctx) return;
    const bounds=parent.getBoundingClientRect(),ratio=Math.min(devicePixelRatio,2);
    canvas.width=bounds.width*ratio;canvas.height=bounds.height*ratio;ctx.scale(ratio,ratio);
    const key=cargo?cargoKey(cargo):null;
    const source=key?parent.querySelector<HTMLElement>(`[data-source-fragment="${key}"]`):null;
    const feed=parent.querySelector<HTMLElement>('.terminal-feed');
    const scrollStart=feed?.scrollTop || 0;
    // Measure the final reading band once, then scroll the document during approach.
    if(source&&feed){
      const sr=source.getBoundingClientRect(),fr=feed.getBoundingClientRect();
      if(sr.top<fr.top+36||sr.bottom>fr.bottom-40) feed.scrollTop+=sr.top-fr.top-76;
    }
    const scrollEnd=feed?.scrollTop || 0;
    const sr=source?.getClientRects()[0];
    if(feed&&!reduced)feed.scrollTop=scrollStart;
    const sourcePoint={x:sr?sr.left-bounds.left+Math.min(sr.width/2,120):145,y:sr?sr.top-bounds.top+sr.height/2:170};
    const from={x:clamp(sourcePoint.x+24,85,bounds.width-85),y:clamp(sourcePoint.y+68,110,bounds.height-65)};
    const initial={x:clamp(pose.current.x,70,bounds.width-70),y:clamp(pose.current.y,85,bounds.height-65)};
    const destination=cargo?parent.querySelector<HTMLElement>(`[data-library-item="${cargo.id}"] [data-field="${cargo.field}"]`)||parent.querySelector<HTMLElement>(`[data-inbox-field="${cargo.field}"]`):null;
    const tr=destination?.getBoundingClientRect();
    const target={x:tr?tr.left-bounds.left+Math.min(tr.width/2,120):bounds.width*.7,y:tr?tr.top-bounds.top+(destination?.tagName==='TH'?65:tr.height/2):130};
    const to={x:clamp(target.x-20,75,bounds.width-85),y:clamp(target.y+65,110,bounds.height-65)};
    const approach=clamp(distance(initial,from)/280,.65,3.8);
    const scanEnd=approach+.55,pluckEnd=scanEnd+.6,carryEnd=pluckEnd+clamp(distance(from,to)/230,1.4,5),end=carryEnd+.55;
    let raf=0,last=0,elapsed=0,phase='';
    const text=cargo?cargoText(cargo):'';
    const font=source?getComputedStyle(source).font:'14px sans-serif';
    const ink=source?getComputedStyle(source).color:'#d0d0d0';
    function finish(){if(key&&completed.current!==key){completed.current=key;callback.current();}}
    if(reduced){
      canvas.dataset.phase='waiting';
      if(cargo){const timer=setTimeout(finish,0);return()=>clearTimeout(timer);}
      return;
    }
    function draw(now:number){
      if(!ctx||!canvas)return;
      const dt=last?Math.min((now-last)/1000,.04):0;last=now;
      // A background tab cannot finish an unseen sequence on a single resumed frame.
      if(!document.hidden) elapsed+=dt;
      const active=!!cargo&&completed.current!==key;
      if(feed&&active&&elapsed<.6)feed.scrollTop=scrollStart+(scrollEnd-scrollStart)*ease(elapsed/.45);
      const nextPhase=!active?'waiting':elapsed<approach?'approach':elapsed<scanEnd?'highlight':elapsed<pluckEnd?'pluck':elapsed<carryEnd?'carrying':'landing';
      if(phase!==nextPhase){phase=nextPhase;canvas.dataset.phase=phase;if(source)source.dataset.crawlPhase=phase;}
      const place=!active?initial:elapsed<approach?mix(initial,from,ease(elapsed/approach)):elapsed<pluckEnd?from:mix(from,to,ease((elapsed-pluckEnd)/(carryEnd-pluckEnd)));
      const p=pose.current,dx=place.x-p.x,dy=place.y-p.y;
      let heading=distance(p,place)>.05?Math.atan2(dy,dx):elapsed<pluckEnd?Math.atan2(sourcePoint.y-p.y,sourcePoint.x-p.x):p.angle;
      const turn=Math.atan2(Math.sin(heading-p.angle),Math.cos(heading-p.angle));
      p.angle+=turn*Math.min(1,dt*7);p.x=place.x;p.y=place.y;
      const local=(x:number,y:number):Point=>({x:p.x+Math.cos(p.angle)*x-Math.sin(p.angle)*y,y:p.y+Math.sin(p.angle)*x+Math.cos(p.angle)*y});
      ctx.clearRect(0,0,bounds.width,bounds.height);
      const carrying=active&&elapsed>=scanEnd&&elapsed<end;
      ctx.font=font;
      // Same literal text, single torn strip; only the visual strip is ellipsized.
      let strip=text; const maxWidth=Math.min(330,bounds.width*.36);
      while(strip.length>1&&ctx.measureText(strip).width>maxWidth)strip=strip.slice(0,-2)+'…';
      const width=ctx.measureText(strip).width+12,height=25;
      const carried={x:clamp(p.x-width/2,8,bounds.width-width-8),y:p.y-48};
      let stripPoint={x:sourcePoint.x-width/2,y:sourcePoint.y-height/2};
      if(carrying){
        stripPoint=elapsed<pluckEnd?mix(stripPoint,carried,ease((elapsed-scanEnd)/.6)):carried;
        if(elapsed>=carryEnd)stripPoint=mix(carried,{x:target.x-width/2,y:target.y-height/2},ease((elapsed-carryEnd)/.55));
      }
      const gripping=active&&elapsed>=approach&&elapsed<end;
      const grip=carrying?{x:stripPoint.x+12,y:stripPoint.y+height}:sourcePoint;
      const joints:{hip:Point;knee:Point;foot:Point}[]=[];
      for(let i=0;i<8;i++){
        const side=i<4?-1:1,j=i%4,hip=local(12-j*7,side*6);
        const desired=local([60,32,-27,-58][j],side*[43,68,68,45][j]);
        if(!p.feet[i])p.feet[i]={...desired,from:desired,to:desired,step:1};
        const f=p.feet[i];
        if(f.step>=1&&distance(f,desired)>21&&Math.floor(elapsed*6)%2===i%2){f.from={x:f.x,y:f.y};f.to=desired;f.step=0;}
        if(distance(f,desired)>125){f.x=desired.x;f.y=desired.y;f.step=1;}
        if(f.step<1){f.step=Math.min(1,f.step+dt*6);const pos=mix(f.from,f.to,ease(f.step));f.x=pos.x;f.y=pos.y-Math.sin(f.step*Math.PI)*7;}
        // One foreleg reaches toward the strip; its silk tether remains attached.
        let foot:Point=f;
        if(i===0&&gripping){const reach=distance(hip,grip);foot=mix(hip,grip,Math.min(1,78/Math.max(1,reach)));}
        const d=clamp(distance(hip,foot),1,91),axis=Math.atan2(foot.y-hip.y,foot.x-hip.x);
        const bend=Math.acos(clamp((43*43+d*d-51*51)/(86*d),-1,1));
        const a=axis+side*(j<2?-1:1)*bend,knee={x:hip.x+Math.cos(a)*43,y:hip.y+Math.sin(a)*43};
        joints.push({hip,knee,foot});
      }
      // Black under-stroke keeps the fine coral skeleton legible over dense copy.
      for(const {hip,knee,foot} of joints){
        ctx.beginPath();ctx.moveTo(hip.x,hip.y);ctx.lineTo(knee.x,knee.y);ctx.lineTo(foot.x,foot.y);
        ctx.strokeStyle='#030304';ctx.lineWidth=3;ctx.stroke();
        ctx.strokeStyle='#ee8d99';ctx.lineWidth=1;ctx.stroke();
        for(const pt of [knee,foot]){ctx.beginPath();ctx.arc(pt.x,pt.y,2.2,0,Math.PI*2);ctx.fillStyle='#95f5ba';ctx.fill();ctx.strokeStyle='#07100c';ctx.lineWidth=.7;ctx.stroke();}
      }
      if(gripping){ctx.beginPath();ctx.moveTo(joints[0].foot.x,joints[0].foot.y);ctx.lineTo(grip.x,grip.y);ctx.strokeStyle='#d75edb';ctx.lineWidth=1;ctx.stroke();}
      ctx.save();ctx.translate(p.x,p.y);ctx.rotate(p.angle);
      ctx.fillStyle='#020305';ctx.fillRect(-20,-7,39,14);
      ctx.strokeStyle='#8f92f4';ctx.lineWidth=1.3;ctx.strokeRect(-20,-7,39,14);
      ctx.beginPath();ctx.moveTo(-15,5);ctx.lineTo(15,-5);ctx.strokeStyle='#69b9e8';ctx.lineWidth=.7;ctx.stroke();
      ctx.beginPath();ctx.arc(11,0,2.7,0,Math.PI*2);ctx.fillStyle='#e15bda';ctx.fill();ctx.restore();
      if(carrying){
        ctx.save();ctx.translate(stripPoint.x+width/2,stripPoint.y+height/2);
        ctx.rotate(Math.sin(elapsed*3)*.035*(elapsed<carryEnd?1:1-ease((elapsed-carryEnd)/.55)));
        ctx.fillStyle=cargo?fragmentColor(cargo.fragmentIndex):'#db70c7';ctx.fillRect(-width/2,-height/2,width,height);
        ctx.font=font;ctx.fillStyle='#121015';ctx.textBaseline='middle';ctx.fillText(strip,-width/2+6,0);ctx.restore();
      }else if(active&&phase==='highlight'&&sr){
        ctx.strokeStyle='#cb60dc';ctx.lineWidth=1;ctx.strokeRect(sr.left-bounds.left-2,sr.top-bounds.top-2,sr.width+4,sr.height+4);
        ctx.fillStyle=ink;
      }
      if(active&&elapsed>=end){finish();return;}
      if(active)raf=requestAnimationFrame(draw);
    }
    raf=requestAnimationFrame(draw);
    return()=>{cancelAnimationFrame(raf);if(source)delete source.dataset.crawlPhase;ctx.clearRect(0,0,bounds.width,bounds.height);};
  },[item?cargoKey(item):null,size,reduced]);
  return <canvas className="spider" ref={ref} aria-hidden="true"/>;
}
