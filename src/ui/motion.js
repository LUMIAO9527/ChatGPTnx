/* Navigation moves live elements. No snapshots, copied text or avatar handoff. */
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
    // The same avatar stays in its original DOM parent and keeps its native font.
    // Remove its temporary fixed positioning and layout slot in the same frame.
    restoreNode(model.live); model.slot?.remove(); model.slot = null; model.applied = null;
  };
  const cancelAnimations = () => { for (const animation of [...running]) animation.cancel(); running.clear(); };
  const finish = () => {
    cancelAnimationFrame(frameId); frameId = 0; cancelAnimations();
    for (const model of models.values()) release(model);
    restore(); models.clear(); page = null; scene = null;
  };
  const stop = finish;
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
    // Allow enough braking distance for incoming momentum. Forcing a reversal
    // into a tiny excursion produces an abrupt, high-acceleration turn.
    // Planning happens once, outside the frame loop.
    for (let length = moveDuration; length >= 180; length -= 20) {
      const safe = ['x','y'].every(key => {
        const from = model.pose[key], to = model.goal[key], speed = model.velocity[key], acceleration = model.acceleration[key];
        const margin = Math.max(6, Math.min(64, Math.abs(to-from)*.08 + speed*speed/32000 + Math.abs(acceleration)/1000));
        const half = Math.max(model.pose[key==='x'?'w':'h'],model.goal[key==='x'?'w':'h'])/2;
        const limit = scene[key==='x'?'width':'height'];
        for (let i=1; i<16; i++) {
          const value = trajectory(from,speed,acceleration,to,length/1000*i/16,length/1000)[0];
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
  const visible = (node, surface) => {
    if (!node) return false;
    const box = node.getBoundingClientRect(), viewport = (surface.querySelector('.sheet-body') || surface).getBoundingClientRect();
    return box.width>0 && box.height>0 && box.bottom>viewport.top && box.top<viewport.bottom && box.right>viewport.left && box.left<viewport.right;
  };
  const findAnchor = (surface, identity) => {
    if (!surface || !identity) return null;
    const card = [...surface.querySelectorAll('.current-card')].find(node => node.dataset.motionIdentity === identity);
    const root = card || [...surface.querySelectorAll('.row, .quota-overview-row, .account-usage-row, .confirm-account')].find(node => node.dataset.email === identity);
    if (!root || !visible(root, surface)) return null;
    return {identity, root, avatar:root.querySelector('.avatar, .usage-brand')};
  };
  const prepareAvatar = model => {
    const node = model.live, slot = document.createElement('span');
    slot.__nxMotionPlaceholder = true; slot.setAttribute('aria-hidden','true'); slot.inert = true;
    Object.assign(slot.style, {display:'inline-block', flex:`0 0 ${model.goal.w}px`, width:`${model.goal.w}px`, height:`${model.goal.h}px`, visibility:'hidden', pointerEvents:'none'});
    node.parentNode.insertBefore(slot, node); model.slot = slot;
    // Fixed positioning escapes the list's scroll clip without reparenting the
    // real avatar. A slot preserves every sibling's layout and the scroll extent.
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
    model.base = rect(node); model.cssWidth = model.goal.w; model.cssHeight = model.goal.h;
    if (!model.base) throw new Error('Avatar bounds unavailable');
  };
  const upsert = (key, kind, initial, goal, live) => {
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
      if (kind === 'avatar') { model.goal = goal; prepareAvatar(model); }
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
    if (source?.avatar && target?.avatar) {
      const key = source.identity+':avatar', existing = models.get(key);
      const box = rect(existing?.live === target.avatar && existing.slot ? existing.slot : target.avatar);
      if (existing?.live === target.avatar && existing.applied) {
        // Auto insets follow the static position when a restored scroll offset
        // or passive layout update moves the parent. Read once per patch, never
        // in the frame loop, and remove the already applied transform.
        const liveBox=rect(existing.live), p=existing.applied;
        if (liveBox) {
          const w=liveBox.w/p.sx, h=liveBox.h/p.sy;
          existing.base={x:liveBox.x-p.x-(liveBox.w-w)/2,y:liveBox.y-p.y-(liveBox.h-h)/2,w,h};
        }
      }
      if (box) upsert(key,'avatar',source.avatar.box,box,target.avatar);
    }
    const filter = surface.querySelector('.usage-filter'), existing = models.get('usage-filter');
    let box = filter && rect(filter);
    if (box && existing?.live === filter && existing.applied) {
      const p = existing.applied, w = box.w/p.sx, h = box.h/p.sy;
      box = {x:box.x-p.x-(box.w-w)/2,y:box.y-p.y-(box.h-h)/2,w,h};
    }
    if (page.filter && box && visible(filter,surface)) {
      upsert('usage-filter','live',page.filter,box,filter);
      page.sharedPath.add(filter);
    }
    for (const [key,model] of models) if (!page.active.has(key)) { release(model); models.delete(key); }
    for (const model of models.values()) for (let node=model.live; node && node!==surface; node=node.parentNode) page.sharedPath.add(node);
  };
  const renderModels = () => {
    // No layout/style reads, element allocation or DOM replacement in this loop.
    for (const model of models.values()) {
      const p = model.pose, base = model.kind === 'avatar' ? model.base : model.goal;
      const x = p.x-base.x+(base.w-p.w)/2, y = p.y-base.y+(base.h-p.h)/2, sx = p.w/base.w, sy = p.h/base.h;
      const rx = model.kind === 'avatar' ? model.cssWidth/base.w : 1, ry = model.kind === 'avatar' ? model.cssHeight/base.h : 1;
      const number = value => Number(value.toFixed(5));
      style(model.live,'transform',`translate(${number(x*rx)}px,${number(y*ry)}px) scale(${number(sx)},${number(sy)})`);
      model.applied = {x:x*rx,y:y*ry,sx,sy};
    }
  };
  const settle = now => {
    for (const [key,model] of models) if (now>=model.start+model.length) {
      release(model); models.delete(key); page.completed.add(key);
    }
  };
  const frame = now => {
    frameId = 0;
    if (!page || !allowed()) { stop(); return; }
    advance(now); renderModels(); settle(now);
    const elapsed = now-page.start;
    if (elapsed>1100 || (elapsed>=page.endElapsed && !models.size)) { finish(); return; }
    frameId = requestAnimationFrame(frame);
  };
  const begin = (surface,direction=1,preferredIdentity=null) => {
    if (!allowed() || !surface || !ensureScene()) { stop(); return; }
    try {
      const now = performance.now(); advance(now); renderModels();
      const identity = surface.querySelector('.current-card')?.dataset.motionIdentity || null;
      const anchor = findAnchor(surface,preferredIdentity) || findAnchor(surface,identity);
      const source = anchor && {identity:anchor.identity,avatar:anchor.avatar && {box:rect(anchor.avatar)}};
      const filterNode = surface.querySelector('.usage-filter'), filter = visible(filterNode,surface) ? rect(filterNode) : null;
      cancelAnimations();
      for (const model of models.values()) release(model);
      restore();
      page = {start:now,direction,identity,source,filter,contentDelay:0,endElapsed:duration,active:new Set(),completed:new Set(),animated:new WeakSet(),sharedPath:new Set(),sharedCard:null};
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
    const entrance = node => {
      if (node.hidden || node.__nxMotionPlaceholder || node.matches('.header, .status-region, .status-stack')) return;
      if (node===page.sharedCard && node.matches('.current-card')) {
        if (!page.identity || node.dataset.motionIdentity!==page.identity) {
          run(node.querySelector('.identity-copy'),fade,duration,elapsed);
          run(node.querySelector('.quota-bars'),fade,duration,elapsed);
        }
        return;
      }
      // Never translate or fade the parent of a moving real control. Animate
      // its siblings individually; otherwise two coordinate systems compete.
      if (page.sharedPath.has(node)) {
        if ([...models.values()].some(model=>model.live===node) || node.matches('.usage-filter')) return;
        for (const child of node.children) entrance(child);
        return;
      }
      if (node.__nxMotionOwned) return;
      const bounds = node.getBoundingClientRect();
      if (bounds.bottom<=viewport.top || bounds.top>=viewport.bottom || bounds.right<=viewport.left || bounds.left>=viewport.right) return;
      const delay = Math.min(section++*stagger,maxStagger);
      page.endElapsed = Math.max(page.endElapsed,duration+delay);
      const fits = distance>0 ? bounds.bottom+distance<=viewport.bottom : bounds.top+distance>=viewport.top;
      run(node,node.matches('.current-card, .usage-filter') || !fits ? fade : frames,duration,elapsed,delay);
    };
    for (const node of body.children) entrance(node);
    run(surface.querySelector('.sheet-head h2, .header .brand'),fade,140,elapsed);
    run(surface.querySelector('.sheet-foot'),fade,duration,elapsed,page.endElapsed-duration);
    if (!frameId) frameId = requestAnimationFrame(frame);
  };
  const reveal = node => {
    if (page && performance.now()-page.start<page.endElapsed) return;
    if (node?.matches('.usage-summary')) run(node.querySelector('.trend'),[{opacity:.65},{opacity:1}],150);
    else run(node,[{opacity:.55,transform:'translateY(-2px)'},{opacity:1,transform:'translateY(0)'}],160);
  };
  window.NXMotion = {
    begin,paint,reveal,stop,enabled:()=>enabled && !preference.matches,
    setEnabled(value) { enabled=!!value; stop(); paintPreference(); }
  };
  preference.addEventListener('change',()=>{ stop(); paintPreference(); });
  document.addEventListener('visibilitychange',()=>{ if (document.hidden) stop(); });
  window.addEventListener('pagehide',stop); window.addEventListener('beforeunload',stop,{once:true});
  window.addEventListener('resize',stop);
  paintPreference();
})();
