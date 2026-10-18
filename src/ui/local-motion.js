/* Shared local motion for segmented choices and keyed sorted rows. A patch
   captures the current pose, velocity and acceleration, then changes the goal.
   Background refreshes with the same goal keep the existing trajectory. */
'use strict';
window.NXLocalMotion=(()=>{
  const models=new Map();let frame=0;
  const enabled=()=>window.NXMotion?.enabled();
  const find=(root,selector)=>[...(root.matches?.(selector)?[root]:[]),...root.querySelectorAll(selector)];
  const segmentKey=node=>'segment:'+node.dataset.segment;
  const rowKey=node=>'row:'+node.parentElement.dataset.motionList+':'+node.dataset.email;
  const pageKey=node=>'page:'+node.dataset.motionPages;
  const width=node=>parseFloat(getComputedStyle(node).width)||node.offsetWidth;
  const segmentGoal=node=>{
    const selected=node.querySelector('[aria-pressed="true"]');if(!selected)return null;
    const css=getComputedStyle(node),a=node.getBoundingClientRect(),b=selected.getBoundingClientRect(),scale=a.width/width(node)||1;
    const left=parseFloat(css.paddingLeft)||0,right=parseFloat(css.paddingRight)||0;
    const controlWidth=width(selected);
    return {goal:{x:(b.left+b.width/2-a.left)/scale-controlWidth/2-left,w:controlWidth},extent:width(node)-left-right};
  };
  const segmentPose=node=>{
    const css=getComputedStyle(node,'::before');let x=0;
    try{x=new DOMMatrixReadOnly(css.transform).m41;}catch{}
    return {x,w:parseFloat(css.width)||0};
  };
  const rowPose=node=>{
    const list=node.parentElement,a=list.getBoundingClientRect(),b=node.getBoundingClientRect(),scale=a.width/width(list)||1;
    return {y:(b.top-a.top)/scale};
  };
  function release(model){
    const node=model.node;
    if(model.kind==='segment'){
      node.style.removeProperty('--segment-x');node.style.removeProperty('--segment-width');
    }else if(model.kind==='page'){
      node.removeAttribute('data-page-moving');
      node.querySelectorAll('.resume-page-ghost').forEach(ghost=>ghost.remove());
      const content=node.querySelector('.resume-page-content');
      content?.style.removeProperty('transform');content?.style.removeProperty('will-change');
    }else{
      node.removeAttribute('data-local-moving');node.style.removeProperty('--motion-row-dy');node.style.removeProperty('--motion-row-z');
    }
    delete node.__nxLocalMotionOwned;
  }
  function stop(){
    cancelAnimationFrame(frame);frame=0;
    for(const model of models.values())release(model);models.clear();
  }
  function bounded(model,pose){
    if(model.kind==='segment'){
      pose.w=Math.max(0,Math.min(model.extent,pose.w));pose.x=Math.max(0,Math.min(model.extent-pose.w,pose.x));
    }else if(model.kind==='page')pose.p=Math.max(1,Math.min(model.extent,pose.p));
    else pose.y=Math.max(0,Math.min(model.extent,pose.y));
    return pose;
  }
  function advance(now){
    for(const model of models.values()){
      const t=Math.max(0,(now-model.start)/1000);
      for(const key of Object.keys(model.goal)){
        [model.pose[key],model.velocity[key],model.acceleration[key]]=window.NXMotion.curve(model.origin[key],model.initialVelocity[key],model.initialAcceleration[key],model.goal[key],t,model.length/1000);
      }
      const raw={...model.pose};bounded(model,model.pose);
      for(const key of Object.keys(raw))if(raw[key]!==model.pose[key])model.velocity[key]=model.acceleration[key]=0;
    }
  }
  function paint(model){
    const node=model.node,p=model.pose;node.__nxLocalMotionOwned=true;
    if(model.kind==='segment'){
      node.style.setProperty('--segment-x',p.x.toFixed(4)+'px');node.style.setProperty('--segment-width',p.w.toFixed(4)+'px');
    }else if(model.kind==='page'){
      node.setAttribute('data-page-moving','');
      const page=Number(node.dataset.page),stride=width(node)+16;
      const content=node.querySelector('.resume-page-content');
      if(content){content.style.transform=`translateX(${((page-p.p)*stride).toFixed(4)}px)`;content.style.willChange='transform';}
      for(const [index,ghost] of model.pages){
        if(index===page||Math.abs(index-p.p)>1.6){ghost.remove();continue;}
        ghost.style.transform=`translateX(${((index-p.p)*stride).toFixed(4)}px)`;
        if(ghost.parentElement!==node)node.appendChild(ghost);
      }
    }else{
      node.setAttribute('data-local-moving','');node.style.setProperty('--motion-row-dy',(p.y-model.goal.y).toFixed(4)+'px');
      node.style.setProperty('--motion-row-z',model.goal.y<model.origin.y?'1':'0');
    }
  }
  const safeLength=model=>{
    for(let length=300;length>=60;length-=20){
      let safe=true;
      for(let i=1;i<20&&safe;i++){
        const pose={};
        for(const key of Object.keys(model.goal))pose[key]=window.NXMotion.curve(model.pose[key],model.velocity[key],model.acceleration[key],model.goal[key],length/1000*i/20,length/1000)[0];
        safe=model.kind==='segment'?pose.x>=-.01&&pose.w>=0&&pose.x+pose.w<=model.extent+.01:
          model.kind==='page'?pose.p>=.99&&pose.p<=model.extent+.01:pose.y>=-.01&&pose.y<=model.extent+.01;
      }
      if(safe)return length;
    }
    return 60;
  };
  function retarget(key,kind,node,from,goal,extent,now,pages){
    let model=models.get(key);
    if(model&&pages)model.pages=pages;
    if(model&&model.kind===kind&&Object.keys(goal).every(k=>Math.abs(goal[k]-model.goal[k])<.02)){
      if(model.node!==node){release(model);model.node=node;}
      model.extent=extent;paint(model);return;
    }
    if(!model){
      if(!from||Object.keys(goal).every(k=>Math.abs(goal[k]-from[k])<.05))return;
      const zero=Object.fromEntries(Object.keys(goal).map(k=>[k,0]));
      model={key,kind,node,pages,pose:{...from},velocity:{...zero},acceleration:{...zero}};models.set(key,model);
    }else if(model.node!==node){release(model);model.node=node;}
    model.extent=extent;bounded(model,model.pose);model.goal=goal;
    model.origin={...model.pose};model.initialVelocity={...model.velocity};model.initialAcceleration={...model.acceleration};
    model.start=now;model.length=safeLength(model);paint(model);
  }
  function tick(now){
    frame=0;if(!enabled()){stop();return;}
    advance(now);
    for(const [key,model] of models){
      if(!model.node.isConnected||now>=model.start+model.length){release(model);models.delete(key);continue;}
      paint(model);
    }
    if(models.size)frame=requestAnimationFrame(tick);
  }
  function beforePatch(root){
    if(!enabled()){stop();return null;}
    advance(performance.now());for(const model of models.values())paint(model);
    const snapshot=new Map();
    for(const node of find(root,'.segmented[data-segment]')){
      if(node.getBoundingClientRect().width) snapshot.set(segmentKey(node),{kind:'segment',node,pose:{...(models.get(segmentKey(node))?.pose||segmentPose(node))}});
    }
    for(const node of find(root,'[data-motion-list] > [data-email]')){
      if(node.getBoundingClientRect().width)snapshot.set(rowKey(node),{kind:'row',node,pose:{...(models.get(rowKey(node))?.pose||rowPose(node))}});
    }
    for(const node of find(root,'[data-motion-pages]')){
      const content=node.querySelector('.resume-page-content');if(!content||!node.getBoundingClientRect().width)continue;
      const key=pageKey(node),model=models.get(key),pages=new Map(model?.pages||[]);
      const ghost=content.cloneNode(true);ghost.classList.add('resume-page-ghost');ghost.removeAttribute('style');
      ghost.setAttribute('aria-hidden','true');ghost.setAttribute('inert','');
      pages.set(Number(node.dataset.page),ghost);
      snapshot.set(key,{kind:'page',node,pose:{...(model?.pose||{p:Number(node.dataset.page)})},pages});
    }
    return snapshot;
  }
  function afterPatch(root,snapshot){
    if(!snapshot||!enabled())return;
    const now=performance.now(),jobs=[],found=new Set();advance(now);
    for(const node of find(root,'.segmented[data-segment]')){
      const key=segmentKey(node),next=node.getBoundingClientRect().width&&segmentGoal(node);if(!next)continue;
      found.add(key);jobs.push({key,kind:'segment',node,...next});
    }
    const rows=find(root,'[data-motion-list] > [data-email]');
    // Measure final layout without the previous translation; all reads precede writes.
    for(const node of rows)node.removeAttribute('data-local-moving');
    for(const node of rows){
      if(!node.getBoundingClientRect().width)continue;
      const key=rowKey(node),goal=rowPose(node),list=node.parentElement;
      found.add(key);jobs.push({key,kind:'row',node,goal,extent:Math.max(0,list.offsetHeight-node.offsetHeight)});
    }
    for(const node of find(root,'[data-motion-pages]')){
      if(!node.getBoundingClientRect().width)continue;
      const key=pageKey(node);found.add(key);
      jobs.push({key,kind:'page',node,goal:{p:Number(node.dataset.page)},extent:Number(node.dataset.pageCount),pages:snapshot.get(key)?.pages});
    }
    for(const key of snapshot.keys())if(!found.has(key)&&models.has(key)){release(models.get(key));models.delete(key);}
    for(const job of jobs)retarget(job.key,job.kind,job.node,snapshot.get(job.key)?.pose,job.goal,job.extent,now,job.pages);
    if(models.size&&!frame)frame=requestAnimationFrame(tick);
  }
  function select(group,value){
    if(!group)return;
    window.NXMotion?.settlePage();const prior=beforePatch(group);
    const buttons=[...group.querySelectorAll('[data-action]')],index=buttons.findIndex(node=>node.dataset.value===String(value));
    if(index<0)return;
    buttons.forEach((node,i)=>{node.classList.toggle('active',i===index);node.setAttribute('aria-pressed',String(i===index));});
    group.style.setProperty('--segment-index',index);afterPatch(group,prior);
  }
  return {beforePatch,afterPatch,select,stop,active:()=>models.size>0};
})();
