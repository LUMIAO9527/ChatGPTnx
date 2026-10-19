/* One layout transaction for every inline disclosure. Intent changes immediately;
   the real content stays attached only until its closing animation ends. */
'use strict';
window.NXDisclosure=(()=>{
  const selector='.settings-disclosure,.detail-reset,.resume-session,.update-release';
  const models=new Map(),popups=new Map();let frameId=0,changing=false;
  const enabled=()=>window.NXMotion?.enabled()&&typeof Element.prototype.animate==='function';
  const bodyOf=node=>node.querySelector('.disclosure-body,.reset-credit-details,.resume-tasks,#update-notes-body');
  const headOf=node=>node.querySelector('summary,[aria-expanded]');
  const desired=node=>models.get(node)?.open??(node.tagName==='DETAILS'?node.open:headOf(node)?.getAttribute('aria-expanded')==='true');
  const remember=(model,node,property,value)=>{
    if(!model.styles.has(node))model.styles.set(node,new Map());
    const saved=model.styles.get(node);if(!saved.has(property))saved.set(property,[node.style.getPropertyValue(property),node.style.getPropertyPriority(property)]);
    node.style.setProperty(property,value);node.__nxDisclosureOwned=true;
  };
  function restore(model){
    for(const [node,properties] of model.styles){for(const [key,[value,priority]] of properties)value?node.style.setProperty(key,value,priority):node.style.removeProperty(key);delete node.__nxDisclosureOwned;}
    const {node,body,open}=model;
    if(node.tagName==='DETAILS')node.open=open;
    if(body){body.inert=model.inert;if(model.aria===null)body.removeAttribute('aria-hidden');else body.setAttribute('aria-hidden',model.aria);if(body.__nxMotionRetained)body.remove();else if(model.reveal)body.hidden=!open;delete body.__nxMotionRetained;}
    delete node.__nxDisclosureIntent;models.delete(node);
  }
  const stop=()=>{cancelAnimationFrame(frameId);frameId=0;for(const model of [...models.values()])restore(model);for(const entry of [...popups.values()]){entry.animation?.cancel();entry.finish();}};
  function advance(now){
    for(const model of models.values())for(const key of ['height','alpha','clip']){
      [model.pose[key],model.velocity[key],model.acceleration[key]]=window.NXMotion.curve(model.origin[key],model.initialVelocity[key],model.initialAcceleration[key],model.goal[key],Math.max(0,now-model.start)/1000,.22);
    }
  }
  function paint(){
    for(const model of models.values()){
      if(!model.reveal)remember(model,model.node,'height',Math.max(model.minimum,model.pose.height)+'px');
      // Ordinary disclosures reveal and retract the same real content by
      // height clipping. Fading it out makes closing appear to finish early.
      if(model.body&&model.reveal){remember(model,model.body,'opacity',String(Math.max(0,Math.min(1,model.pose.alpha))));remember(model,model.body,'clip-path',`inset(0 0 ${Math.max(0,Math.min(100,model.pose.clip))}% 0)`);}
    }
  }
  function frame(now){
    frameId=0;if(!enabled()){stop();return;}
    advance(now);paint();
    for(const model of [...models.values()])if(!model.node.isConnected||now>=model.start+220)restore(model);
    if(models.size)frameId=requestAnimationFrame(frame);
  }
  const schedule=()=>{if(models.size&&!frameId)frameId=requestAnimationFrame(frame);};
  function capture(root){
    const snapshots=new Map();
    for(const node of root.querySelectorAll(selector)){
      const previous=models.get(node),body=bodyOf(node);
      snapshots.set(node,{node,body,open:desired(node),height:node.getBoundingClientRect().height,pose:previous?{...previous.pose}:null,velocity:previous?{...previous.velocity}:null,acceleration:previous?{...previous.acceleration}:null});
    }
    return snapshots;
  }
  function transact(root,change){
    if(!enabled()){stop();change();return;}
    const now=performance.now();advance(now);paint();const before=capture(root);
    stop();changing=true;
    try{change();}finally{changing=false;}
    for(const node of root.querySelectorAll(selector)){
      const old=before.get(node);if(!old)continue;
      const open=desired(node),reveal=node.classList.contains('update-release'),natural=node.getBoundingClientRect().height;
      if(open===old.open&&Math.abs(natural-old.height)<.5)continue;
      let body=bodyOf(node);
      if(!open&&old.body&&!body){body=old.body;body.__nxMotionRetained=true;node.append(body);}
      if(!body)continue;
      const pose=old.pose||{height:old.height,alpha:old.open?1:0,clip:old.open?0:100};
      const zero={height:0,alpha:0,clip:0};
      const model={node,body,open,reveal,minimum:headOf(node)?.getBoundingClientRect().height||0,styles:new Map(),pose:{...pose},velocity:old.velocity||{...zero},acceleration:old.acceleration||{...zero},goal:{height:natural,alpha:open?1:0,clip:open?0:100},start:now,inert:body.inert,aria:body.getAttribute('aria-hidden')};
      model.origin={...model.pose};model.initialVelocity={...model.velocity};model.initialAcceleration={...model.acceleration};
      models.set(node,model);node.__nxDisclosureIntent=open;
      if(node.tagName==='DETAILS')node.open=true;
      if(reveal)body.hidden=false;
      if(!open){body.inert=true;body.setAttribute('aria-hidden','true');}
      remember(model,node,'transition','none');
      if(!reveal){
        remember(model,node,'overflow','hidden');
        // aria-expanded records intent immediately. The header stays joined
        // to its body until the rounded outer shell has fully retracted.
        const head=headOf(node);
        if(head?.classList.contains('control-header')){
          remember(model,head,'border-bottom-left-radius','0px');
          remember(model,head,'border-bottom-right-radius','0px');
        }
      }
    }
    paint();schedule();
  }
  function afterPatch(root){
    if(changing||!models.size)return;
    const now=performance.now();advance(now);
    for(const model of models.values()){
      if(!root.contains(model.node)||!model.open||model.reveal)continue;
      const saved=model.styles.get(model.node)?.get('height')||['',''];
      saved[0]?model.node.style.setProperty('height',saved[0],saved[1]):model.node.style.removeProperty('height');
      const natural=model.node.getBoundingClientRect().height;
      if(Math.abs(natural-model.goal.height)>.5){model.origin={...model.pose};model.initialVelocity={...model.velocity};model.initialAcceleration={...model.acceleration};model.goal.height=natural;model.start=now;}
    }
    paint();schedule();
  }
  function popup(node,html,{reappear=false}={}){
    const visible=!!html,old=popups.get(node),wasVisible=old?old.visible:!node.hidden;
    if(old&&visible===old.visible&&!reappear){if(visible&&node.innerHTML!==html)node.innerHTML=html;return;}
    if(!old&&visible===wasVisible&&!reappear){if(node.innerHTML!==html)node.innerHTML=html;node.hidden=!visible;return;}
    const css=getComputedStyle(node),from=old?Number(css.opacity):wasVisible&&!reappear?1:0,transform=old?css.transform:wasVisible&&!reappear?'translateY(0)':'translateY(4px)';
    old?.animation?.cancel();
    const entry={node,visible,inert:old?.inert??node.inert,aria:old?old.aria:node.getAttribute('aria-hidden')};
    entry.finish=()=>{
      if(popups.get(node)!==entry)return;
      node.hidden=!visible;if(!visible)node.innerHTML='';node.inert=entry.inert;
      if(entry.aria===null)node.removeAttribute('aria-hidden');else node.setAttribute('aria-hidden',entry.aria);
      delete node.__nxPopupActive;popups.delete(node);entry.animation?.cancel();
    };
    popups.set(node,entry);node.__nxPopupActive=true;
    if(visible&&node.innerHTML!==html)node.innerHTML=html;
    node.hidden=false;node.inert=visible?entry.inert:true;if(!visible)node.setAttribute('aria-hidden','true');
    if(!enabled()){entry.finish();return;}
    try{entry.animation=node.animate([{opacity:from,transform},{opacity:visible?1:0,transform:visible?'translateY(0)':'translateY(4px)'}],{duration:visible?180:140,easing:'cubic-bezier(.2,.7,.25,1)',fill:'both'});entry.animation.onfinish=entry.finish;}
    catch{entry.finish();}
  }
  return {transact,afterPatch,popup,stop,isOpen:desired};
})();
