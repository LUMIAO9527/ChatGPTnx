/* A primary action keeps one continuous surface across routes. Account identity
   and entry controls accompany it; supporting content never moves the page. */
(() => {
  const preference = matchMedia('(prefers-reduced-motion: reduce)');
  const running = new Set(), animationTargets = new WeakMap();
  const models = new Map(), bindings = new Map();
  const duration = 240, moveDuration = 300, stagger = 16, maxStagger = 32;
  const easing = 'cubic-bezier(.2,.7,.25,1)';
  let enabled = true, page = null, scene = null, frameId = 0;
  const allowed = () => enabled && !preference.matches && typeof Element.prototype.animate === 'function';
  const paintPreference = () => { document.documentElement.dataset.motion = enabled && !preference.matches ? 'on' : 'off'; };
  const style = (node, property, value) => {
    if (!node) return;
    if (!bindings.has(node)) bindings.set(node, new Map());
    const saved = bindings.get(node);
    if (!saved.has(property)) saved.set(property, [node.style.getPropertyValue(property), node.style.getPropertyPriority(property)]);
    node.style.setProperty(property, value);
    node.__nxMotionOwned = true;
  };
  const restoreNode = node => {
    const properties = bindings.get(node);
    if (!properties) return;
    // Restore CSS transitions last, so removing motion cannot start a second animation.
    const ordered = [...properties].sort(([a], [b]) => (a === 'transition') - (b === 'transition'));
    for (const [property, [value, priority]] of ordered) {
      if (value) node.style.setProperty(property, value, priority);
      else node.style.removeProperty(property);
    }
    delete node.__nxMotionOwned; bindings.delete(node);
  };
  const restore = () => { for (const node of [...bindings.keys()]) restoreNode(node); };
  const release = model => {
    // Keep the original DOM parent, native font and static-position raster origin.
    // Retire positioning and its layout slot together at the exact endpoint.
    restoreNode(model.live);
    if(model.live)delete model.live.__nxMotionRole;
    if(model.kind==='surface'){restoreNode(model.target);model.live?.remove();}
    model.slot?.remove(); model.slot = null; model.applied = null;
  };
  const cancelAnimations = () => { for (const animation of [...running]) animation.cancel(); running.clear(); };
  const clearIdentityPlate = () => {
    if(!page?.plate)return;
    restoreNode(page.plate.node);page.plate.node.remove();page.plate=null;
  };
  const finish = () => {
    cancelAnimationFrame(frameId); frameId = 0; cancelAnimations();
    clearIdentityPlate();
    for (const model of models.values()) release(model);
    restore(); models.clear(); page = null; scene = null;
  };
  const stop = () => {finish();window.NXUsageMotion?.stop();window.NXLocalMotion?.stop();window.NXDisclosure?.stop();};
  const run = (node, frames, length = duration, elapsed = 0, delay = 0) => {
    if (!node || !allowed() || elapsed >= length + delay) return;
    // Background state refreshes patch the same DOM. They must not cancel and
    // recreate an already running compositor animation, even at the same time.
    if (page?.animated.has(node)) return;
    try {
      for (const previous of [...running]) if (animationTargets.get(previous) === node) previous.cancel();
      const opacity = parseFloat(getComputedStyle(node).opacity);
      const restOpacity = Number.isFinite(opacity) ? opacity : 1;
      const values = frames.map(frame => 'opacity' in frame ? {...frame, opacity:frame.opacity * restOpacity} : frame);
      const navigation = page;
      if (navigation) { navigation.animated.add(node); style(node, 'transition', 'none'); }
      const animation = node.animate(values, {duration:length, delay, easing, fill:'both'});
      animationTargets.set(animation, node); running.add(animation);
      animation.currentTime = Math.max(0, elapsed);
      animation.oncancel = () => { running.delete(animation); if (navigation) restoreNode(node); };
      // Each effect retires at its own exact endpoint, not at a later page-wide cleanup.
      animation.onfinish = () => animation.cancel();
    } catch { /* Animation availability must never prevent navigation. */ }
  };
  const fade = [{opacity:0}, {opacity:1}];
  // Quintic Hermite trajectory: continuous position, velocity and acceleration
  // on interruption; all three reach their exact resting values at the end.
  const trajectory = (value, velocity, acceleration, target, elapsed, length) => {
    if (elapsed >= length) return [target, 0, 0];
    const u = Math.max(0, elapsed / length), delta = target - value;
    const v = velocity * length, a = acceleration * length * length;
    const c3 = 10*delta - 6*v - 1.5*a, c4 = -15*delta + 8*v + 1.5*a, c5 = 6*delta - 3*v - .5*a;
    return [value + v*u + .5*a*u*u + c3*u**3 + c4*u**4 + c5*u**5,
      (v + a*u + 3*c3*u*u + 4*c4*u**3 + 5*c5*u**4) / length,
      (a + 6*c3*u + 12*c4*u*u + 20*c5*u**3) / (length*length)];
  };
  const travelTime = model => {
    if(model.kind==='reveal')return moveDuration;
    // Allow enough braking distance for incoming momentum. Forcing a reversal
    // into a tiny excursion produces an abrupt, high-acceleration turn.
    // Planning happens once, outside the frame loop.
    for (let length = moveDuration; length >= 180; length -= 20) {
      const safe = ['x','y'].every(key => {
        const from = model.pose[key], to = model.goal[key], speed = model.velocity[key], acceleration = model.acceleration[key];
        const margin = Math.max(6, Math.min(64, Math.abs(to-from)*.08 + speed*speed/32000 + Math.abs(acceleration)/1000));
        const dimension=key==='x'?'w':'h';
        const limit = scene[key==='x'?'width':'height'];
        for (let i=1; i<16; i++) {
          const at=length/1000*i/16;
          const value = trajectory(from,speed,acceleration,to,at,length/1000)[0];
          const half=trajectory(model.pose[dimension],model.velocity[dimension],model.acceleration[dimension],model.goal[dimension],at,length/1000)[0]/2;
          if (value < Math.min(from,to)-margin || value > Math.max(from,to)+margin) return false;
          if (value < half || value > limit-half) return false;
        }
        return true;
      });
      if (safe || length === 180) return length;
    }
  };
  const advance = now => {
    for (const model of models.values()) {
      const elapsed = Math.max(0, (now-model.start)/1000);
      for (const key of Object.keys(model.goal)) {
        [model.pose[key], model.velocity[key], model.acceleration[key]] = trajectory(model.origin[key], model.initialVelocity[key], model.initialAcceleration[key], model.goal[key], elapsed, model.length/1000);
      }
    }
  };
  const ensureScene = () => {
    if (scene) return scene;
    const app = document.getElementById('app'); if (!app) return null;
    const css = getComputedStyle(app);
    scene = {app,width:parseFloat(css.width)||app.clientWidth,height:parseFloat(css.height)||app.clientHeight};
    if (!app.__nxMotionGestures) {
      app.__nxMotionGestures = true;
      app.addEventListener('wheel', stop, {passive:true});
      app.addEventListener('touchstart', stop, {passive:true});
      app.addEventListener('keydown', event => { if (['PageUp','PageDown','Home','End'].includes(event.key)) stop(); });
    }
    return scene;
  };
  const rect = node => {
    if (!node || !scene) return null;
    const box = node.getBoundingClientRect(), app = scene.app.getBoundingClientRect(), css = getComputedStyle(scene.app);
    const sx = app.width / (parseFloat(css.width) || scene.app.clientWidth);
    const sy = app.height / (parseFloat(css.height) || scene.app.clientHeight);
    if (!(sx > 0 && sy > 0 && box.width > 0 && box.height > 0)) return null;
    return {x:(box.left+box.width/2-app.left)/sx, y:(box.top+box.height/2-app.top)/sy, w:box.width/sx, h:box.height/sy};
  };
  const visible = (node, surface, scrollClip=true) => {
    if (!node) return false;
    const body=scrollClip?surface.querySelector('.sheet-body'):null;
    const box = node.getBoundingClientRect(), viewport = (body?.contains(node)?body:surface).getBoundingClientRect();
    return box.width>0 && box.height>0 && box.bottom>viewport.top && box.top<viewport.bottom && box.right>viewport.left && box.left<viewport.right;
  };
  const findAnchor = (surface, identity) => {
    if (!surface || !identity) return null;
    const card = [...surface.querySelectorAll('.current-card')].find(node => node.dataset.motionIdentity === identity);
    const root = card || [...surface.querySelectorAll('.row, .quota-overview-row, .account-usage-row, .confirm-account')].find(node => node.dataset.email === identity);
    if (!root || !visible(root, surface)) return null;
    return {identity, root, avatar:root.querySelector('.avatar, .usage-brand'),label:root.querySelector('.identity-copy, .meta, .confirm-account-copy, .quota-overview-main .identity-title')};
  };
  const entryControl = (surface,route={}) => {
    const homeRoute=route.from==='home'?route.to:route.from;
    const action={settings:'settings',usage:'usage-all','quota-overview':'quota-overview',add:'add'}[homeRoute];
    const node=surface?.querySelector(surface.id==='home'&&action?`[data-action="${action}"]`:'.sheet-head [data-action="back"]');
    const part=node&&capturePart(node,surface);
    return part?{node,...part,r:parseFloat(getComputedStyle(node).borderRadius)||0}:null;
  };
  const sharedMedia = surface => {
    const node=surface?.querySelector('.support-code img, .support-full-code'),part=node&&capturePart(node,surface);
    return part?{node,...part}:null;
  };
  const surfaceTone = node => {
    let color=node&&getComputedStyle(node).backgroundColor;
    if(!color||color==='transparent'||/rgba\([^)]*,\s*0\)$/.test(color))color=getComputedStyle(scene.app).backgroundColor;
    const rgb=(color?.match(/[\d.]+/g)||[]).slice(0,3).map(Number);
    return rgb.length===3?rgb:[255,255,255];
  };
  const primaryControl = surface => {
    if (!surface) return null;
    for (const node of surface.querySelectorAll('.primary, .relay')) {
      const value=capturePart(node,surface);
      if (value) return {node,...value,r:parseFloat(getComputedStyle(node).borderRadius)||0};
    }
    return null;
  };
  const contextSurface = surface => {
    const node=surface?.querySelector('[data-motion-surface="account-context"]'),value=node&&capturePart(node,surface);
    if(!value)return null;
    const existing=models.get('context-surface'),css=getComputedStyle(node);
    return {node,...value,r:existing?.target===node?existing.goal.r:parseFloat(css.borderRadius)||0,color:existing?.target===node?existing.color:css.backgroundColor};
  };
  const reportParts = surface => {
    const parts=new Map();
    if(surface?.dataset.page!=='usage')return parts;
    for(const selector of ['.usage-filter','.usage-summary']){
      const node=surface.querySelector(selector);
      if(visible(node,surface))parts.set(selector,{node,box:rect(node)});
    }
    return parts;
  };
  const capturePart = (node,surface) => {
    const floating=node?.__nxMotionOwned&&node.style.position==='fixed';
    if (!visible(node,floating?scene.app:surface,!floating)) return null;
    const box = node.getBoundingClientRect();
    // A partially clipped control or avatar uses the ordinary page entrance.
    // A live fixed anchor already escapes that clip; measuring its travelling
    // pose must not discard it when a poll arrives between footer and body.
    for (let parent=floating?surface:node.parentNode; parent && parent!==surface; parent=parent.parentNode) {
      const css=getComputedStyle(parent), clip=parent.getBoundingClientRect();
      if (['hidden','auto','scroll','clip'].includes(css.overflowY) && (box.top<clip.top-.5 || box.bottom>clip.bottom+.5)) return null;
      if (['hidden','auto','scroll','clip'].includes(css.overflowX) && (box.left<clip.left-.5 || box.right>clip.right+.5)) return null;
    }
    if (!floating&&node.scrollWidth>node.clientWidth+1) return null;
    return {box:rect(node),text:node.textContent,font:parseFloat(getComputedStyle(node).fontSize)||0};
  };
  const prepareFixed = model => {
    const node = model.live, css=getComputedStyle(node), slot = document.createElement('span');
    slot.__nxMotionPlaceholder = true; slot.setAttribute('aria-hidden','true'); slot.inert = true;
    Object.assign(slot.style, {display:css.display==='block'?'block':'inline-block', flex:css.flex||'0 0 auto', alignSelf:css.alignSelf, width:`${model.goal.w}px`, height:`${model.goal.h}px`, visibility:'hidden', pointerEvents:'none',
      boxSizing:css.boxSizing,minWidth:css.minWidth,minHeight:css.minHeight,maxWidth:css.maxWidth,maxHeight:css.maxHeight,
      paddingTop:css.paddingTop,paddingRight:css.paddingRight,paddingBottom:css.paddingBottom,paddingLeft:css.paddingLeft,
      borderStyle:'solid',borderColor:'transparent',borderTopWidth:css.borderTopWidth,borderRightWidth:css.borderRightWidth,borderBottomWidth:css.borderBottomWidth,borderLeftWidth:css.borderLeftWidth,
      marginTop:css.marginTop,marginRight:css.marginRight,marginBottom:css.marginBottom,marginLeft:css.marginLeft,verticalAlign:css.verticalAlign});
    node.parentNode.insertBefore(slot, node); model.slot = slot;
    // Fixed positioning escapes the list's scroll clip without reparenting the
    // real part. The slot preserves siblings and the scroll extent.
    for (let ancestor=node.parentNode; ancestor && ancestor!==scene.app; ancestor=ancestor.parentNode) {
      page.sharedPath.add(ancestor);
      const css = getComputedStyle(ancestor), transform = css.transform;
      // Persistent opacity surfaces create stacking contexts. Lift the shared
      // path so a later action button cannot paint over the travelling avatar.
      if (css.willChange?.split(',').some(value=>value.trim()==='opacity')) {
        if (!css.position || css.position === 'static') style(ancestor,'position','relative');
        style(ancestor,'z-index','7');
      }
      if (ancestor.tagName === 'BUTTON' || (transform && transform !== 'none')) {
        style(ancestor,'transition','none'); style(ancestor,'transform','none');
      }
    }
    // Keep the native static-position origin. Moving from the panel's origin
    // changes the glyph raster phase at fractional Windows display scales,
    // even when the final bounding rectangles agree to a fraction of a pixel.
    for (const [property,value] of Object.entries({transition:'none', position:'fixed', left:'auto', top:'auto', right:'auto', bottom:'auto', margin:'0', width:`${model.goal.w}px`, height:`${model.goal.h}px`, 'z-index':'6', 'pointer-events':'none', 'transform-origin':'0 0', transform:'none', 'will-change':'transform'})) style(node, property, value);
    if(model.kind==='control'||model.kind==='label') {
      // A button changes its physical surface, rather than scaling its text.
      // Fixed positioning isolates these size writes from the document layout.
      for(const [property,value] of Object.entries({'min-width':'0','min-height':'0','max-width':'none','max-height':'none'}))style(node,property,value);
      if(model.kind==='control'){style(node,'left',`${model.goal.x-model.goal.w/2}px`);style(node,'top',`${model.goal.y-model.goal.h/2}px`);}
    }
    model.base = rect(node); model.cssWidth = model.goal.w; model.cssHeight = model.goal.h;
    if (!model.base) throw new Error('Shared element bounds unavailable');
  };
  const upsert = (key, kind, initial, goal, live, extra={}) => {
    if (page.completed.has(key)) return null;
    let model = models.get(key);
    const different = Object.keys(goal).some(property => Math.abs(initial[property]-goal[property]) > .25);
    if (!model && !different) { page.completed.add(key); return null; }
    if (!model) {
      const zero = Object.fromEntries(Object.keys(initial).map(property => [property,0]));
      model = {key,kind,pose:{...initial},velocity:{...zero},acceleration:{...zero},goal}; models.set(key, model);
    }
    const changed = model.navigation !== page || Object.keys(goal).some(property => Math.abs(model.goal[property]-goal[property]) > .01);
    if (model.live !== live || model.navigation !== page) {
      release(model); model.live = live; model.base = goal;
      live.__nxMotionRole=kind==='reveal'?'reveal':key==='navigation-entry'?'entry':key==='primary-action'?'primary':key==='support-media'?'media':kind==='surface'?'surface':['region','label'].includes(kind)?'identity':'avatar';
      if(kind==='surface'){
        model.target=extra.target;model.color=extra.color;
        live.__nxMotionPlaceholder=true;live.setAttribute('aria-hidden','true');live.inert=true;live.className='motion-surface';
        model.target.insertBefore(live,model.target.firstChild);style(model.target,'background-color','transparent');
        for(const [property,value] of Object.entries({position:'fixed',left:`${goal.x-goal.w/2}px`,top:`${goal.y-goal.h/2}px`,width:`${goal.w}px`,height:`${goal.h}px`,'z-index':'-1','background-color':extra.color,'pointer-events':'none',transition:'none','transform-origin':'0 0'}))style(live,property,value);
      }
      else if (kind === 'fixed' || kind === 'control'||kind==='label') { model.goal = goal; prepareFixed(model); }
      else { style(live,'transition','none'); style(live,'transform-origin','0 0'); style(live,'will-change','transform'); }
    }
    model.goal = goal;
    if (changed) {
      model.origin = {...model.pose}; model.initialVelocity = {...model.velocity}; model.initialAcceleration = {...model.acceleration};
      model.start = performance.now(); model.length = travelTime(model); model.navigation = page;
    }
    page.active.add(key); return model;
  };
  const bindShared = surface => {
    const source = page.source, target = source && findAnchor(surface,source.identity);
    page.sharedCard = target?.root || null;
    const targetBox=target && rect(target.root);
    page.stationaryCard=source?.card && target?.root.matches('.current-card') && targetBox && Object.keys(targetBox).every(key=>Math.abs(targetBox[key]-source.box[key])<.25);
    const control=primaryControl(surface),filter=surface.querySelector('.usage-filter'),context=contextSurface(surface);
    const sharedSurface=source?.surface&&context&&['x','y','w','h'].some(key=>Math.abs(source.surface.box[key]-context.box[key])>.25);
    const report=surface.dataset.page==='usage'&&page.report.size>0;
    // Home and account detail keep the same neutral top card, even when the
    // travelling account came from another row. Its backdrop never re-enters.
    const homeDetail=page.route.from==='home'&&page.route.to==='detail'||page.route.from==='detail'&&page.route.to==='home';
    page.backdrop=homeDetail&&page.backdropSource&&context&&['x','y','w','h'].every(key=>Math.abs(page.backdropSource.box[key]-context.box[key])<.5)?context:null;
    if(page.backdrop)for(let node=context.node;node&&node!==surface;node=node.parentNode)page.sharedPath.add(node);
    // A neutral account card must never take the black action's moving role.
    const chosen=source?.control&&control?'control':sharedSurface?'surface':!report&&page.filter&&visible(filter,surface)?'filter':source?.avatar&&target?.avatar?'avatar':null;
    const key=chosen==='surface'?'context-surface':chosen==='control'?'primary-action':chosen==='avatar'?source.identity+':avatar':'usage-filter';
    const live=chosen==='surface'?context.node:chosen==='control'?control.node:chosen==='avatar'?target.avatar:filter;
    const existing=models.get(key);
    // An async page can expose its shared part after an entrance already began.
    // Retire effects on that path before measuring its final, static geometry.
    if(chosen)for(let node=live;node&&node!==surface;node=node.parentNode){
      for(const animation of [...running])if(animationTargets.get(animation)===node)animation.cancel();
    }
    let box=live&&rect(existing?.live===live&&existing.slot?existing.slot:live);
    if(chosen==='surface'&&box){
      const decoration=existing?.navigation===page&&existing.target===live?existing.live:document.createElement('span');
      upsert(key,'surface',{...source.surface.box,r:source.surface.r},{...box,r:context.r},decoration,{target:live,color:context.color});
      page.sharedCard=live;for(let node=live;node&&node!==surface;node=node.parentNode)page.sharedPath.add(node);
    }else if(chosen==='control'&&box) {
      // The live radius is an intermediate pose, not a new destination.
      box={...box,r:existing?.live===live&&existing.slot?existing.goal.r:control.r};
      upsert(key,'control',{...source.control.box,r:source.control.r},box,live);
      for(let node=live;node&&node!==surface;node=node.parentNode)page.sharedPath.add(node);
      const crossing=page.accountLink&&source?.avatar&&target?.avatar&&!page.stationaryCard;
      if(source.control.text!==control.text)run(live.querySelector('.control-content'),fade,crossing?80:180,performance.now()-page.start,crossing?220:40);
    } else if(chosen==='avatar'&&box&&(existing||capturePart(live,surface))) {
      if(existing?.live===live&&existing.applied) {
        const liveBox=rect(live),p=existing.applied;
        if(liveBox){const w=liveBox.w/p.sx,h=liveBox.h/p.sy;existing.base={x:liveBox.x-p.x-(liveBox.w-w)/2,y:liveBox.y-p.y-(liveBox.h-h)/2,w,h};}
      }
      upsert(key,'fixed',source.avatar.box,box,live);
      for(let node=live;node&&node!==surface;node=node.parentNode)page.sharedPath.add(node);
    } else if(chosen==='filter'&&box) {
      if(existing?.live===live&&existing.applied){const p=existing.applied,w=box.w/p.sx,h=box.h/p.sy;box={x:box.x-p.x-(box.w-w)/2,y:box.y-p.y-(box.h-h)/2,w,h};}
      upsert(key,'live',page.filter,box,live);page.sharedPath.add(live);
    }
    // The selected account travels alongside the action, never in its place.
    // Name, membership and subtitle form one unscaled block, so a travelling
    // name never collides with a subtitle already at its destination.
    page.linkedIdentity=!!(page.accountLink&&['control','avatar'].includes(chosen)&&source?.avatar&&target?.avatar&&!page.stationaryCard);
    if(page.linkedIdentity){
      const live=target.avatar,key=source.identity+':avatar',prior=models.get(key);
      let goal=rect(prior?.live===live&&prior.slot?prior.slot:live);
      if(goal&&(prior||capturePart(live,surface)))upsert(key,'fixed',source.avatar.box,goal,live);
      if(source.label&&target.label){
        const key=source.identity+':label',prior=models.get(key),goal=rect(prior?.live===target.label&&prior.slot?prior.slot:target.label);
        if(goal)upsert(key,'label',source.label.box,goal,target.label);
      }
      if(chosen==='control'&&models.has(source.identity+':label')){
        if(page.plate?.root!==target.root){
          clearIdentityPlate();const node=document.createElement('span');node.className='motion-identity-plate';node.__nxMotionRetained=true;node.__nxMotionDecoration=true;node.setAttribute('aria-hidden','true');node.inert=true;
          target.root.insertBefore(node,target.root.firstChild);page.plate={node,root:target.root,from:source.tone,to:surfaceTone(target.root),color:source.tone,avatar:rect(target.avatar),label:rect(target.label)};
          for(const [property,value]of Object.entries({position:'fixed','z-index':'-1','pointer-events':'none',transition:'none','border-radius':'16px'}))style(node,property,value);
        }
        page.plate.avatar=models.get(source.identity+':avatar')?.goal||rect(target.avatar);page.plate.label=models.get(source.identity+':label')?.goal||rect(target.label);
        // Account information is one foreground surface while crossing an
        // action. Its native text never disappears behind the black button.
        for(let node=target.root;node&&node!==surface;node=node.parentNode){
          if(node===target.root||getComputedStyle(node).willChange?.includes('opacity')){
            if(getComputedStyle(node).position==='static')style(node,'position','relative');
            style(node,'z-index','8');
          }
        }
      }
    }
    if(!page.linkedIdentity||chosen!=='control')clearIdentityPlate();
    const media=page.media&&sharedMedia(surface);
    page.linkedMedia=!!media;
    if(media){
      const prior=models.get('support-media'),goal=rect(prior?.live===media.node&&prior.slot?prior.slot:media.node);
      if(goal)upsert('support-media','fixed',page.media.box,goal,media.node);
    }
    const anchored=['primary-action','context-surface',source?.identity+':avatar'].some(key=>page.active.has(key));
    // Navigation controls keep their own continuity even when a card or
    // account identity is also shared. Neither motion should suppress the other.
    const homeNavigation=page.route.from==='home'||page.route.to==='home';
    const homePage=page.route.from==='home'?page.route.to:page.route.from;
    const commonEntry=homeNavigation&&['settings','usage'].includes(homePage);
    page.entryActive=!!(page.entry&&(homeNavigation||!anchored&&!report&&!media));
    if(page.entryActive){
      const target=entryControl(surface,page.route),prior=models.get('navigation-entry');
      const goal=target&&rect(prior?.live===target.node&&prior.slot?prior.slot:target.node);
      page.entryMoving=!!(goal&&(prior||['x','y','w','h'].some(key=>Math.abs(page.entry.box[key]-goal[key])>.25)));
      if(goal){
        upsert('navigation-entry','control',{...page.entry.box,r:page.entry.r},{...goal,r:prior?.live===target.node&&prior.slot?prior.goal.r:target.r},target.node);
        style(target.node,'pointer-events','auto');
      }
    }
    if(page.entryActive&&!media&&(commonEntry||!anchored&&!report)){
      // Reveal real sections in place. One clock survives interrupted return
      // and passive rendering; there is no outgoing page copy or lateral slide.
      // Settings and usage keep this same content motion even while the usage
      // context card follows its own shared path.
      const body=surface.id==='home'?surface:surface.querySelector('.sheet-body');
      const sections=[...(body?.querySelectorAll('.settings-section')||[])];
      const groups=surface.id==='home'?[...surface.children].filter(node=>!node.matches('.header, .status-region, .status-stack')):sections.length?sections:[...(body?.children||[])];
      let index=0;
      const revealGroup=node=>{
        if(!visible(node,surface)||node.__nxMotionPlaceholder||node===page.sharedCard&&page.stationaryCard)return;
        if([...models.values()].some(model=>model.kind!=='reveal'&&(model.live===node||model.target===node)))return;
        // The usage report wraps the shared card and the remaining sections.
        // Keep shared parts in their own coordinate system, then reveal their
        // siblings. Previously registered groups retain their clock on refresh.
        if(page.sharedPath.has(node)&&!page.reportNodes.has(node)){
          if(node===page.sharedCard)return;
          for(const child of node.children)revealGroup(child);
          return;
        }
        const model=upsert('entry-content:'+index++,'reveal',{open:0},{open:1},node);
        page.reportNodes.add(node);
        if(model)for(let parent=node;parent&&parent!==surface;parent=parent.parentNode)page.sharedPath.add(parent);
      };
      for(const node of groups)revealGroup(node);
    }
    if(report)for(const [selector,from] of page.report){
      const node=surface.querySelector(selector);if(!visible(node,surface))continue;
      const key='report:'+selector,prior=models.get(key),goal=rect(node);
      if(prior?.live===node&&prior.applied){goal.x-=prior.applied.x;goal.y-=prior.applied.y;}
      upsert(key,'region',from.box,goal,node);
      page.reportNodes.add(node);
      for(let parent=node;parent&&parent!==surface;parent=parent.parentNode)page.sharedPath.add(parent);
    }
    for (const [key,model] of models) if (!page.active.has(key)) { release(model); models.delete(key); }
    for (const model of models.values()) for (let node=model.live; node && node!==surface; node=node.parentNode) page.sharedPath.add(node);
  };
  const renderModels = () => {
    // No layout/style reads, element allocation or DOM replacement in this loop.
    for (const model of models.values()) {
      const p = model.pose, base = model.kind === 'fixed'||model.kind==='label' ? model.base : model.goal;
      if(model.kind==='reveal'){
        const open=Math.max(0,Math.min(1,p.open));
        style(model.live,'transform',`translate(0px,${((1-open)*10).toFixed(5)}px)`);
        style(model.live,'clip-path',`inset(0 0 ${((1-open)*100).toFixed(5)}% 0 round 16px)`);
        continue;
      }
      if(model.kind==='region'||model.kind==='label'){
        const x=p.x-p.w/2-(base.x-base.w/2),y=p.y-p.h/2-(base.y-base.h/2);
        style(model.live,'transform',`translate(${x.toFixed(5)}px,${y.toFixed(5)}px)`);
        model.applied={x:Number(x.toFixed(5)),y:Number(y.toFixed(5))};continue;
      }
      if(model.kind==='control'||model.kind==='surface') {
        style(model.live,'left',`${model.goal.x-model.goal.w/2}px`);style(model.live,'top',`${model.goal.y-model.goal.h/2}px`);
        style(model.live,'width',`${p.w}px`);style(model.live,'height',`${p.h}px`);style(model.live,'border-radius',`${Math.max(0,p.r)}px`);
        style(model.live,'transform',`translate(${p.x-p.w/2-(base.x-base.w/2)}px,${p.y-p.h/2-(base.y-base.h/2)}px)`);
        continue;
      }
      const x = p.x-base.x+(base.w-p.w)/2, y = p.y-base.y+(base.h-p.h)/2, sx = p.w/base.w, sy = p.h/base.h;
      const rx = model.kind === 'fixed' ? model.cssWidth/base.w : 1, ry = model.kind === 'fixed' ? model.cssHeight/base.h : 1;
      const number = value => Number(value.toFixed(5));
      style(model.live,'transform',`translate(${number(x*rx)}px,${number(y*ry)}px) scale(${number(sx)},${number(sy)})`);
      model.applied = {x:x*rx,y:y*ry,sx,sy};
    }
    if(page?.plate){
      const plate=page.plate,a=models.get(page.source.identity+':avatar')?.pose||plate.avatar,l=models.get(page.source.identity+':label')?.pose||plate.label;
      const label=models.get(page.source.identity+':label')?.goal||plate.label;
      const left=Math.min(a.x-a.w/2,l.x-l.w/2)-6,top=Math.min(a.y-a.h/2,l.y-l.h/2)-6;
      const right=Math.max(a.x+a.w/2,l.x-l.w/2+label.w)+6,bottom=Math.max(a.y+a.h/2,l.y-l.h/2+label.h)+6;
      const progress=trajectory(0,0,0,1,Math.max(0,performance.now()-page.start)/1000,moveDuration/1000)[0];
      plate.color=plate.from.map((value,index)=>value+(plate.to[index]-value)*progress);
      for(const [key,value]of Object.entries({left:left+'px',top:top+'px',width:(right-left)+'px',height:(bottom-top)+'px','background-color':`rgb(${plate.color.map(n=>n.toFixed(3)).join(',')})`}))style(plate.node,key,value);
      if(page.backdrop){
        // The moving identity still needs protection while crossing the black
        // action. Cut the persistent card out of that protection, so its shade
        // cannot be painted over and then exposed again at animation cleanup.
        const b=page.backdrop.box,w=right-left,h=bottom-top;
        const cutLeft=b.x-b.w/2-left,cutTop=b.y-b.h/2-top,cutRight=cutLeft+b.w,cutBottom=cutTop+b.h;
        style(plate.node,'clip-path',`polygon(evenodd,0px 0px,${w}px 0px,${w}px ${h}px,0px ${h}px,0px 0px,${cutLeft}px ${cutTop}px,${cutLeft}px ${cutBottom}px,${cutRight}px ${cutBottom}px,${cutRight}px ${cutTop}px,${cutLeft}px ${cutTop}px,0px 0px)`);
      }else style(plate.node,'clip-path','none');
    }
  };
  const settle = now => {
    for (const [key,model] of models) if (now>=model.start+model.length) {
      release(model); models.delete(key); page.completed.add(key);
    }
    if(page.plate&&!models.has(page.source.identity+':avatar')&&!models.has(page.source.identity+':label'))clearIdentityPlate();
  };
  const frame = now => {
    frameId = 0;
    if (!page || !allowed()) { stop(); return; }
    advance(now); renderModels(); settle(now);
    const elapsed = now-page.start;
    if (elapsed>1100 || (elapsed>=page.endElapsed && !models.size)) { finish(); return; }
    frameId = requestAnimationFrame(frame);
  };
  const begin = (surface,direction=1,preferredIdentity=null,route={}) => {
    window.NXDisclosure?.stop();
    if (!allowed() || !surface || !ensureScene()) { stop(); return; }
    try {
      const now = performance.now(); advance(now); renderModels();
      const usage=window.NXUsageMotion?.beforeNavigation(surface),report=reportParts(surface);
      const identity = surface.querySelector('.current-card')?.dataset.motionIdentity || null;
      const anchor = findAnchor(surface,preferredIdentity) || findAnchor(surface,identity);
      const source = {identity:anchor?.identity||null,avatar:anchor?.avatar?capturePart(anchor.avatar,surface):null,label:anchor?.label?capturePart(anchor.label,surface):null,tone:page?.plate?.color||surfaceTone(anchor?.root),control:primaryControl(surface),surface:anchor?.root.matches('.current-card')?contextSurface(surface):null,card:!!anchor?.root.matches('.current-card'),box:anchor?rect(anchor.root):null};
      const backdrop=contextSurface(surface);
      const entry=route.from&&route.to&&route.from!==route.to?entryControl(surface,route):null;
      const media=['purchase','support-qr'].includes(route.from)&&['purchase','support-qr'].includes(route.to)&&route.from!==route.to?sharedMedia(surface):null;
      const filterNode = surface.querySelector('.usage-filter'), filter = visible(filterNode,surface) ? rect(filterNode) : null;
      window.NXLocalMotion?.stop();
      cancelAnimations();
      clearIdentityPlate();
      for (const model of models.values()) release(model);
      restore();
      page = {start:now,direction,identity,source,filter,usage,report,entry,media,route,backdropSource:backdrop,accountLink:route.from==='detail'||route.to==='detail'||route.from==='quota-overview'||route.to==='quota-overview',reportNodes:new Set(),contentDelay:0,endElapsed:duration,active:new Set(),completed:new Set(),animated:new WeakSet(),sharedPath:new Set(),sharedCard:null};
    } catch { stop(); }
  };
  const paint = surface => {
    if (!page || !allowed() || !surface) return;
    const now = performance.now(), elapsed = now-page.start;
    if (elapsed>=1100) { stop(); return; }
    try {
      advance(now); page.active.clear();
      for (const node of page.sharedPath) if (!surface.contains(node)) page.sharedPath.delete(node);
      bindShared(surface); renderModels(); settle(now);
      if(page.usage){window.NXUsageMotion?.afterPatch(surface,page.usage);page.usage=null;}
      // Release detached nodes after a real DOM rebuild, without touching effects
      // or positioning on nodes that a background patch kept alive.
      for (const node of [...bindings.keys()]) if (!surface.contains(node)) restoreNode(node);
      for (const animation of [...running]) if (!surface.contains(animationTargets.get(animation))) animation.cancel();
    } catch { stop(); return; }
    const body = surface.id === 'home' ? surface : surface.querySelector('.sheet-body');
    if (!body) { stop(); return; }
    const viewport = body.getBoundingClientRect(), distance = page.direction>0 ? 4 : -3;
    const frames = [{opacity:0,transform:`translateY(${distance}px)`},{opacity:1,transform:'translateY(0)'}];
    let section = 0;
    const entrance = (node,clip=viewport) => {
      if (node.hidden || node.__nxMotionPlaceholder || node.matches('.header, .status-region, .status-stack')) return;
      if(page.reportNodes.has(node))return;
      if (node===page.sharedCard && page.stationaryCard) return;
      // Never translate or fade the parent of a moving real control. Animate
      // its siblings individually; otherwise two coordinate systems compete.
      if (page.sharedPath.has(node)) {
        if ([...models.values()].some(model=>model.live===node) || node.matches('.avatar, .usage-brand, .usage-filter, .primary, .relay')) return;
        for (const child of node.children) entrance(child,clip);
        return;
      }
      if (node.__nxMotionOwned) return;
      const bounds = node.getBoundingClientRect();
      if (bounds.bottom<=clip.top || bounds.top>=clip.bottom || bounds.right<=clip.left || bounds.left>=clip.right) return;
      // Leave the travel corridor clear. Secondary actions and quota text
      // appear as the identity and black surface reach their resting places.
      const waitForHero=page.linkedIdentity||page.linkedMedia||models.has('primary-action')&&node.matches('.secondary');
      const delay = waitForHero?220:Math.min(section++*stagger,maxStagger),length=waitForHero?80:duration;
      page.endElapsed = Math.max(page.endElapsed,length+delay);
      const fits = distance>0 ? bounds.bottom+distance<=clip.bottom : bounds.top+distance>=clip.top;
      run(node,models.size||page.stationaryCard||node.matches('.current-card, .usage-filter') || !fits ? fade : frames,length,elapsed,delay);
    };
    if(models.size||page.stationaryCard||page.reportNodes.size){for (const node of body.children) entrance(node);}
    else run(body,frames,duration,elapsed);
    // The travelling entry crosses the title's resting position. Show the
    // title once that corridor is clear, rather than passing through its text.
    run(surface.querySelector('.sheet-head h2, .header .brand'),fade,page.entryMoving?90:140,elapsed,page.entryMoving?210:0);
    const footer=surface.querySelector('.sheet-foot');
    if(footer){if(page.sharedPath.has(footer))entrance(footer,surface.getBoundingClientRect());else run(footer,fade,page.linkedIdentity?80:duration,elapsed,page.linkedIdentity?220:page.endElapsed-duration);}
    if(models.has('primary-action')){
      const notification=surface.querySelector('.status-dock .status-notification');
      if(notification){run(notification,fade,80,elapsed,220);style(notification,'pointer-events','none');}
    }
    if (!frameId) frameId = requestAnimationFrame(frame);
  };
  window.NXMotion = {
    begin,paint,stop,settlePage:finish,curve:trajectory,enabled:()=>enabled && !preference.matches,
    setEnabled(value) { enabled=!!value; stop(); paintPreference(); }
  };
  preference.addEventListener('change',()=>{ stop(); paintPreference(); });
  document.addEventListener('visibilitychange',()=>{ if (document.hidden) stop(); });
  window.addEventListener('pagehide',stop); window.addEventListener('beforeunload',stop,{once:true});
  window.addEventListener('resize',stop);
  paintPreference();
})();
