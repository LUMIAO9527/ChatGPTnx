/* Local range motion: split the old and new chart at shared normalized
   boundaries. Pieces reshape without fading, and remain continuous when a
   later selection interrupts them. The actual chart retains its semantics. */
'use strict';
window.NXUsageMotion = (() => {
  const duration=300, easing='cubic-bezier(.2,0,.2,1)';
  let current=null, frame=0;
  const enabled=()=>window.NXMotion?.enabled()&&typeof Element.prototype.animate==='function';
  const box=(node,plot)=>{
    const r=node.getBoundingClientRect(),p=plot.getBoundingClientRect();
    const sx=p.width/plot.offsetWidth||1,sy=p.height/plot.offsetHeight||1;
    return {x:(r.left-p.left)/sx,bottom:(r.bottom-p.top)/sy,w:r.width/sx,h:r.height/sy};
  };
  const paintNumber=(node,value)=>{
    const number=node.querySelector(':scope > .count-number'),unit=node.querySelector(':scope > .count-unit');
    if(!number||!unit)return;
    const formatted=node.dataset.countFormat==='days'?{main:String(value),unit:'天'}:window.NXMath.compact(value);
    number.textContent=formatted.main;unit.textContent=formatted.unit;node.__nxCountValue=value;
  };
  function stop(){
    cancelAnimationFrame(frame);frame=0;
    if(!current)return;
    const prior=current;current=null;
    for(const animation of prior.animations)animation.cancel();
    for(const [node,value,priority] of prior.hidden){
      value?node.style.setProperty('visibility',value,priority):node.style.removeProperty('visibility');
    }
    for(const counter of prior.counters){paintNumber(counter.node,counter.goal);delete counter.node.__nxCountValue;}
    prior.layer?.remove();
  }
  function select(surface,value){
    window.NXLocalMotion?.select(surface.querySelector('.usage-filter'),value);
  }
  function beforePatch(surface,requested=false){
    if(!requested&&current?.surface!==surface)return null;
    if(!enabled()){stop();return null;}
    const plot=surface.querySelector('.trend');
    const pieces=current?.surface===surface&&current.layer?[...current.layer.children]:null;
    const bars=plot?[...plot.querySelectorAll(':scope > .trend-bar')]:[];
    const segments=plot?(pieces||bars).map((node,index)=>({
      start:pieces?Number(node.dataset.rangeStart):index/bars.length,
      end:pieces?Number(node.dataset.rangeEnd):(index+1)/bars.length,...box(node,plot)
    })):[];
    const counts=new Map([...surface.querySelectorAll('[data-count-value]')].map(node=>[
      node.dataset.countKey,{value:node.__nxCountValue??window.NXMath.count(node.dataset.countValue),format:node.dataset.countFormat}
    ]));
    stop();return {segments,counts};
  }
  function afterPatch(surface,previous){
    if(!previous||!enabled()||surface.hidden||surface.dataset.page!=='usage')return;
    const state={surface,layer:null,hidden:[],animations:[],counters:[],start:performance.now()};
    const plot=surface.querySelector('.trend'),bars=plot?[...plot.querySelectorAll(':scope > .trend-bar')]:[];
    if(plot&&bars.length&&previous.segments.length){
      const targets=bars.map(node=>box(node,plot));
      const boundaries=[0,1,...previous.segments.flatMap(part=>[part.start,part.end]),...bars.map((_,i)=>i/bars.length)]
        .sort((a,b)=>a-b).filter((value,i,array)=>!i||value-array[i-1]>1e-7);
      const layer=document.createElement('span');layer.className='range-morph-layer';layer.setAttribute('aria-hidden','true');
      for(let i=0;i<boundaries.length-1;i++){
        const start=boundaries[i],end=boundaries[i+1],mid=(start+end)/2;
        const from=previous.segments.find(part=>mid>=part.start-1e-8&&mid<=part.end+1e-8);if(!from)continue;
        const index=Math.min(bars.length-1,Math.floor(mid*bars.length)),to=targets[index];
        const fromX=from.x+(start-from.start)/(from.end-from.start)*from.w;
        const fromW=(end-start)/(from.end-from.start)*from.w;
        const toX=to.x+(start*bars.length-index)*to.w,toW=Math.max(.001,(end-start)*bars.length*to.w),toH=Math.max(.001,to.h);
        const piece=document.createElement('i');piece.className=bars[index].className;
        piece.dataset.rangeStart=start;piece.dataset.rangeEnd=end;
        Object.assign(piece.style,{left:toX+'px',top:(to.bottom-toH)+'px',width:toW+'px'});
        piece.style.setProperty('height',toH+'px','important');layer.append(piece);
        const fromTransform=`translate(${fromX-toX}px,${from.bottom-to.bottom}px) scale(${fromW/toW},${from.h/toH})`;
        state.animations.push(piece.animate([{transform:fromTransform},{transform:'none'}],{duration,easing,fill:'both'}));
      }
      for(const bar of bars){state.hidden.push([bar,bar.style.getPropertyValue('visibility'),bar.style.getPropertyPriority('visibility')]);bar.style.visibility='hidden';}
      plot.append(layer);state.layer=layer;
    }
    for(const node of surface.querySelectorAll('[data-count-value]')){
      const from=previous.counts.get(node.dataset.countKey),goal=window.NXMath.count(node.dataset.countValue);
      if(from?.value===null||from?.value===undefined||goal===null||from.format!==node.dataset.countFormat||from.value===goal)continue;
      state.counters.push({node,from:from.value,goal});paintNumber(node,from.value);
    }
    if(!state.layer&&!state.counters.length)return;
    current=state;
    const tick=now=>{
      if(current!==state)return;
      if(!enabled()||!surface.isConnected||surface.hidden||surface.dataset.page!=='usage'){stop();return;}
      const progress=Math.max(0,Math.min(1,(now-state.start)/duration));
      const eased=1-Math.pow(1-progress,3),fraction=BigInt(Math.round(eased*10000));
      for(const counter of state.counters)paintNumber(counter.node,counter.from+(counter.goal-counter.from)*fraction/10000n);
      if(progress===1){stop();return;}
      frame=requestAnimationFrame(tick);
    };
    frame=requestAnimationFrame(tick);
  }
  return {select,beforePatch,afterPatch,stop,active:()=>!!current};
})();
