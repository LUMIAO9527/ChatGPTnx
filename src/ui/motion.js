/* Lightweight navigation motion. Real controls, focus, history and scroll update immediately. */
(() => {
  const preference = matchMedia('(prefers-reduced-motion: reduce)');
  const running = new Set();
  const models = new Map(), bindings = new Map();
  const duration = 240, stagger = 16, maxStagger = 32;
  const easing = 'cubic-bezier(.2,.7,.25,1)';
  let enabled = true, page = null, layers = null, frameId = 0, lastTime = 0;
  const allowed = () => enabled && !preference.matches && typeof Element.prototype.animate === 'function';
  const paintPreference = () => {
    document.documentElement.dataset.motion = enabled && !preference.matches ? 'on' : 'off';
  };
  const style = (node, property, value) => {
    if (!node) return;
    if (!bindings.has(node)) bindings.set(node, new Map());
    const saved = bindings.get(node);
    if (!saved.has(property)) saved.set(property, [node.style.getPropertyValue(property), node.style.getPropertyPriority(property)]);
    node.style.setProperty(property, value);
  };
  const restore = () => {
    for (const [node, properties] of bindings) {
      for (const [property, [value, priority]] of properties) {
        if (value) node.style.setProperty(property, value, priority);
        else node.style.removeProperty(property);
      }
      delete node.__nxMotionOwned;
    }
    bindings.clear();
  };
  const cancelAnimations = () => {
    const animations = [...running];
    running.clear();
    for (const animation of animations) animation.cancel();
  };
  const finish = () => {
    cancelAnimationFrame(frameId); frameId = 0;
    cancelAnimations();
    restore(); models.clear(); page = null;
    layers?.front.remove(); layers = null;
  };
  const stop = () => { cancelAnimations(); finish(); };
  const run = (node, frames, length = duration, elapsed = 0, delay = 0) => {
    if (!node || !allowed() || elapsed >= length + delay) return;
    try {
      const animation = node.animate(frames, {duration: length, delay, easing, fill: 'backwards'});
      animation.currentTime = Math.max(0, elapsed);
      running.add(animation);
      animation.onfinish = animation.oncancel = () => running.delete(animation);
    } catch { /* An unavailable animation must never prevent the action. */ }
  };
  const fade = [{opacity: 0}, {opacity: 1}];
  // Exact critically damped spring: a new destination keeps the current velocity.
  const spring = (value, velocity, target, elapsed, frequency = 32) => {
    const delta = value - target, c = velocity + frequency * delta;
    const decay = Math.exp(-frequency * elapsed);
    return [target + (delta + c * elapsed) * decay, (velocity - frequency * c * elapsed) * decay];
  };
  const settled = model => Object.keys(model.goal).every(key =>
    Math.abs(model.pose[key] - model.goal[key]) < (key === 'o' || key === 's' ? .001 : .08) &&
    Math.abs(model.velocity[key]) < (key === 'o' || key === 's' ? .025 : 1));
  const advance = now => {
    const elapsed = Math.max(0, (now - lastTime) / 1000); lastTime = now;
    for (const model of models.values()) {
      for (const key of Object.keys(model.goal)) {
        [model.pose[key], model.velocity[key]] = spring(model.pose[key], model.velocity[key], model.goal[key], elapsed, model.frequency || 32);
      }
    }
  };
  const ensureLayers = () => {
    if (layers) return layers;
    const app = document.getElementById('app');
    if (!app) return null;
    const make = z => {
      const node = document.createElement('div');
      node.className = 'nx-motion-layer'; node.setAttribute('aria-hidden', 'true'); node.inert = true;
      Object.assign(node.style, {position:'absolute', inset:'0', pointerEvents:'none', overflow:'hidden', zIndex:String(z)});
      app.append(node); return node;
    };
    layers = {app, front:make(6)};
    if (!app.__nxMotionGestures) {
      app.__nxMotionGestures = true;
      app.addEventListener('wheel', stop, {passive:true});
      app.addEventListener('touchstart', stop, {passive:true});
      app.addEventListener('keydown', event => { if (['PageUp','PageDown','Home','End'].includes(event.key)) stop(); });
    }
    return layers;
  };
  const rect = node => {
    if (!node || !layers) return null;
    const box = node.getBoundingClientRect(), app = layers.app.getBoundingClientRect();
    const sx = app.width / layers.app.clientWidth, sy = app.height / layers.app.clientHeight;
    if (!(sx > 0 && sy > 0 && box.width > 0 && box.height > 0)) return null;
    return {x:(box.left + box.width / 2 - app.left) / sx, y:(box.top + box.height / 2 - app.top) / sy, w:box.width / sx, h:box.height / sy};
  };
  const visible = (node, surface) => {
    if (!node) return false;
    const box = node.getBoundingClientRect();
    const viewport = (surface.querySelector('.sheet-body') || surface).getBoundingClientRect();
    return box.width > 0 && box.height > 0 && box.bottom > viewport.top && box.top < viewport.bottom && box.right > viewport.left && box.left < viewport.right;
  };
  const findAnchor = (surface, identity) => {
    if (!surface || !identity) return null;
    const card = [...surface.querySelectorAll('.current-card')].find(node => node.dataset.motionIdentity === identity);
    const root = card || [...surface.querySelectorAll('.row, .quota-overview-row, .account-usage-row, .confirm-account')].find(node => node.dataset.email === identity);
    if (!root || !visible(root, surface)) return null;
    return {identity, root, avatar:root.querySelector('.avatar, .usage-brand'), name:root.querySelector('.identity-title strong, .account-name, .identity-copy > strong')};
  };
  const sanitize = node => {
    const appearance = new Set(['data-window-minutes','data-feedback-tone','aria-pressed','aria-expanded','aria-checked','aria-invalid','aria-selected','aria-disabled']);
    for (const element of [node, ...node.querySelectorAll('*')]) {
      for (const attribute of [...element.attributes]) {
        if (!appearance.has(attribute.name) && (attribute.name === 'id' || attribute.name === 'name' || attribute.name === 'autofocus' || attribute.name.startsWith('data-') || attribute.name.startsWith('on') || attribute.name.startsWith('aria-'))) element.removeAttribute(attribute.name);
      }
      element.setAttribute('tabindex', '-1');
    }
    node.setAttribute('aria-hidden', 'true'); node.inert = true;
  };
  const visual = (node, kind) => {
    const css = getComputedStyle(node), box = rect(node);
    if (!box) return null;
    const clone = kind === 'name' ? document.createElement('span') : node.cloneNode(true);
    if (kind === 'name') clone.textContent = node.textContent;
    sanitize(clone);
    for (const property of ['color','background-color','background-image','border','border-radius','font-family','font-size','font-weight','font-style','line-height','letter-spacing','text-align','text-overflow','align-items','justify-content']) clone.style.setProperty(property, css.getPropertyValue(property));
    Object.assign(clone.style, {position:'absolute', left:'0', top:'0', margin:'0', padding:'0', width:`${box.w}px`, height:`${box.h}px`, display:kind === 'name' ? 'block' : 'flex', whiteSpace:'nowrap', overflow:'hidden', pointerEvents:'none', transformOrigin:'0 0', transition:'none', animation:'none', opacity:'1'});
    return {node:clone, box, font:parseFloat(css.fontSize) || 14};
  };
  const upsert = (key, kind, initial, goal, factory, live) => {
    let model = models.get(key);
    const different = Object.keys(goal).some(property => Math.abs(initial[property] - goal[property]) > (property === 's' || property === 'o' ? .005 : .25));
    if (!model && !different) return null;
    if (!model) {
      const appearance = factory();
      if (!appearance) return null;
      model = {key, kind, pose:{...initial}, velocity:Object.fromEntries(Object.keys(initial).map(property => [property, 0])), goal, ...appearance};
      models.set(key, model);
      if (model.node) layers.front.append(model.node);
    }
    model.goal = goal; model.live = live;
    page.active.add(key);
    return model;
  };
  const bindShared = surface => {
    const source = page.source, target = source && findAnchor(surface, source.identity);
    if (source && target) {
      for (const kind of ['avatar', 'name']) {
        const from = source[kind], to = target[kind];
        if (!from || !to || (kind === 'name' && from.text !== to.textContent)) continue;
        const box = rect(to); if (!box) continue;
        const font = parseFloat(getComputedStyle(to).fontSize) || from.font;
        const start = {...from.box, o:1, ...(kind === 'name' ? {s:1} : {})};
        const goal = {...box, o:1, ...(kind === 'name' ? {s:font / from.font} : {})};
        const key = source.identity + ':' + kind;
        // An existing clone keeps its original font size while its target changes.
        if (kind === 'name' && models.has(key)) goal.s = font / models.get(key).font;
        const model = upsert(key, kind, start, goal, () => from, to);
        if (model) style(to, 'opacity', '0');
      }
    }
    const filter = surface.querySelector('.usage-filter'), box = filter && rect(filter);
    if (page.filter && box && visible(filter, surface)) {
      const model = upsert('usage-filter', 'live', {...page.filter, o:1}, {...box, o:1}, () => ({node:null, box:page.filter}), filter);
      filter.__nxMotionOwned = true; style(filter, 'transition', 'none');
      if (model) style(filter, 'transform-origin', '0 0');
    }
    for (const [key, model] of models) {
      if (!page.active.has(key)) { model.node?.remove(); models.delete(key); }
    }
  };
  const contentDelay = () => {
    const moving = [...models.values()].filter(model => model.kind === 'avatar' || model.kind === 'name');
    // New labels appear after the shared identity has cleared their path.
    for (let delay = 0; delay <= 200; delay += 10) {
      if (moving.every(model => {
        const x = spring(model.pose.x, model.velocity.x, model.goal.x, delay / 1000)[0];
        const y = spring(model.pose.y, model.velocity.y, model.goal.y, delay / 1000)[0];
        return Math.hypot(x - model.goal.x, y - model.goal.y) <= (model.kind === 'name' ? 8 : 16);
      })) return delay;
    }
    return 200;
  };
  const renderModels = () => {
    for (const model of models.values()) {
      const p = model.pose, node = model.kind === 'live' ? model.live : model.node;
      if (!node) continue;
      const number = value => Number(value.toFixed(4));
      if (model.kind === 'live') {
        style(node, 'transform', `translate(${number(p.x - model.goal.x + (model.goal.w - p.w) / 2)}px,${number(p.y - model.goal.y + (model.goal.h - p.h) / 2)}px) scale(${number(p.w / model.goal.w)},${number(p.h / model.goal.h)})`);
      } else if (model.kind === 'name') {
        node.style.width = `${p.w / p.s}px`;
        node.style.height = `${p.h / p.s}px`; node.style.lineHeight = `${p.h / p.s}px`;
        node.style.transform = `translate(${number(p.x - p.w / 2)}px,${number(p.y - p.h / 2)}px) scale(${number(p.s)})`;
        node.style.opacity = String(Math.max(0, Math.min(1, p.o)));
      } else {
        node.style.transform = `translate(${number(p.x - p.w / 2)}px,${number(p.y - p.h / 2)}px) scale(${number(p.w / model.box.w)},${number(p.h / model.box.h)})`;
        node.style.opacity = String(Math.max(0, Math.min(1, p.o)));
      }
    }
  };
  const frame = now => {
    frameId = 0;
    if (!page || !allowed()) { stop(); return; }
    advance(now); renderModels();
    const elapsed = now - page.start;
    if (elapsed > 1100 || (elapsed >= page.endElapsed && [...models.values()].every(settled))) { finish(); return; }
    frameId = requestAnimationFrame(frame);
  };
  const begin = (surface, direction = 1, preferredIdentity = null) => {
    if (!allowed() || !surface || !ensureLayers()) { stop(); return; }
    try {
      const now = performance.now(); advance(now); renderModels();
      const identity = surface.querySelector('.current-card')?.dataset.motionIdentity || null;
      const anchor = findAnchor(surface, preferredIdentity) || findAnchor(surface, identity);
      const source = anchor && {identity:anchor.identity, avatar:anchor.avatar && visual(anchor.avatar, 'avatar'), name:anchor.name && visual(anchor.name, 'name')};
      if (source?.name) source.name.text = anchor.name.textContent;
      const filterNode = surface.querySelector('.usage-filter');
      const filter = visible(filterNode, surface) ? rect(filterNode) : null;
      // Retain only the moving identity; never clone an outgoing page.
      restore(); cancelAnimations();
      page = {start:now, direction, identity, source, filter, contentDelay:null, endElapsed:duration, active:new Set()};
      lastTime = now;
    } catch { stop(); }
  };
  const paint = surface => {
    if (!page || !allowed() || !surface) return;
    const elapsed = performance.now() - page.start;
    if (elapsed >= 1100) { stop(); return; }
    // Async data may rebuild the page during its entrance. Resume the same clock.
    try {
      advance(performance.now()); restore(); page.active.clear();
      bindShared(surface); renderModels();
      page.contentDelay ??= contentDelay();
    } catch { stop(); return; }
    cancelAnimations();
    const body = surface.id === 'home' ? surface : surface.querySelector('.sheet-body');
    if (!body) { stop(); return; }
    const viewport = body.getBoundingClientRect();
    const distance = page.direction > 0 ? 4 : -3;
    const frames = [
      {opacity: 0, transform: `translateY(${distance}px)`},
      {opacity: 1, transform: 'translateY(0)'}
    ];
    let section = 0;
    page.endElapsed = duration + page.contentDelay;
    for (const node of body.children) {
      if (node.hidden || node.__nxMotionOwned || node.matches('.header, .status-region, .status-stack')) continue;
      if (node.matches('.current-card')) {
        // Matching account cards stay still; changed identities fade in place.
        if (!page.identity || node.dataset.motionIdentity !== page.identity) run(node, fade, duration, elapsed, page.contentDelay);
      } else if (node.matches('.usage-filter')) {
        run(node, fade, duration, elapsed, page.contentDelay);
      } else {
        const bounds = node.getBoundingClientRect();
        if (bounds.bottom <= viewport.top || bounds.top >= viewport.bottom || bounds.right <= viewport.left || bounds.left >= viewport.right) continue;
        const delay = page.contentDelay + Math.min(section++ * stagger, maxStagger);
        page.endElapsed = Math.max(page.endElapsed, duration + delay);
        const fits = distance > 0 ? bounds.bottom + distance <= viewport.bottom : bounds.top + distance >= viewport.top;
        // Content at a viewport edge only fades; motion never adds scroll overflow.
        run(node, fits ? frames : fade, duration, elapsed, delay);
      }
    }
    run(surface.querySelector('.sheet-head h2, .header .brand'), fade, 140, elapsed);
    // Action buttons share the final beat; input and focus remain immediate.
    run(surface.querySelector('.sheet-foot'), fade, duration, elapsed, page.endElapsed - duration);
    if (!frameId) frameId = requestAnimationFrame(frame);
  };
  const reveal = node => {
    if (page && performance.now() - page.start < page.endElapsed) return;
    if (node?.matches('.usage-summary')) {
      // Changing a time range keeps the numbers and labels fixed; only the chart softens.
      run(node.querySelector('.trend'), [{opacity:.65}, {opacity:1}], 150);
    } else {
      run(node, [{opacity:.55, transform:'translateY(-2px)'}, {opacity:1, transform:'translateY(0)'}], 160);
    }
  };
  window.NXMotion = {
    begin, paint, reveal, stop,
    enabled: () => enabled && !preference.matches,
    setEnabled(value) { enabled = !!value; stop(); paintPreference(); }
  };
  preference.addEventListener('change', () => { stop(); paintPreference(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
  window.addEventListener('pagehide', stop);
  window.addEventListener('beforeunload', stop, {once:true});
  paintPreference();
})();
