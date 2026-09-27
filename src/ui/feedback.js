/* One feedback vocabulary. Control feedback never participates in layout.
   Tickets prevent an old completion/timer from clearing a newer action. */
'use strict';
window.NXFeedback = (() => {
  const {esc, icon} = window.NXComponents;
  const tones = new Set(['neutral', 'progress', 'success', 'warning', 'error']);
  function status({text, tone='neutral', action='', attrs='', className='', symbol=''}={}) {
    tone=tones.has(tone)?tone:'neutral';
    const tag=action?'button':'div';
    const glyph=symbol||({progress:'refresh',success:'check',warning:'info',error:'info'}[tone]||'info');
    return `<${tag} class="notice status-bar ${tone} ${className}" ${action?`data-action="${esc(action)}"`:''} ${attrs} title="${esc(text)}">${icon(glyph,tone==='progress'?'spinner':'')}<span class="status-text">${esc(text)}</span>${action?icon('chevron'):''}</${tag}>`;
  }
  function controlKey(node) {
    if(!node?.dataset?.action)return null;
    return JSON.stringify(['action','email','key','value','session'].map(k=>node.dataset[k]||''));
  }
  function create({root, changed=()=>{}, announce=()=>{}, clock=globalThis}={}) {
    const entries=new Map(), originals=new WeakMap();
    let revision=0;
    function restore(node) {
      const old=originals.get(node);if(!old)return;
      node.querySelector(':scope > .control-feedback')?.remove();
      node.classList.remove('has-feedback','feedback-icon-only');
      delete node.dataset.feedbackTone;
      for(const attr of ['aria-busy','aria-label','disabled']) {
        const value=old[attr];value===null?node.removeAttribute(attr):node.setAttribute(attr,value);
      }
      originals.delete(node);
    }
    function paint() {
      for(const node of root.querySelectorAll('button[data-action]')) {
        restore(node);
        const entry=entries.get(controlKey(node));if(!entry)continue;
        originals.set(node,Object.fromEntries(['aria-busy','aria-label','disabled'].map(k=>[k,node.getAttribute(k)])));
        const iconOnly=node.classList.contains('tool')||node.classList.contains('switch');
        node.classList.add('has-feedback');node.classList.toggle('feedback-icon-only',iconOnly);
        node.dataset.feedbackTone=entry.tone;
        node.setAttribute('aria-busy',String(entry.tone==='progress'));
        const label=node.getAttribute('aria-label')||node.textContent.trim();
        node.setAttribute('aria-label',`${label}，${entry.text}`);
        if(entry.tone==='progress')node.disabled=true;
        const overlay=document.createElement('span');overlay.className='control-feedback';overlay.setAttribute('aria-hidden','true');
        overlay.innerHTML=icon(entry.tone==='progress'?'refresh':entry.tone==='error'?'info':'check',entry.tone==='progress'?'spinner':'')+(iconOnly?'':`<span>${esc(entry.text)}</span>`);
        node.append(overlay);
      }
    }
    function begin(node,text='处理中…') {
      const key=controlKey(node);const token={key,id:++revision};
      if(key){const old=entries.get(key);if(old?.timer)clock.clearTimeout(old.timer);entries.set(key,{id:token.id,tone:'progress',text});paint();}
      announce(text);return token;
    }
    function finish(token,{text='',tone='success',duration=1200}={}) {
      if(!token?.key)return;
      const current=entries.get(token.key);if(!current||current.id!==token.id)return;
      if(!text){entries.delete(token.key);paint();return;}
      const entry={id:token.id,text,tone};entries.set(token.key,entry);paint();announce(text);
      entry.timer=clock.setTimeout(()=>{
        if(entries.get(token.key)?.id!==token.id)return;
        entries.delete(token.key);paint();changed();
      },duration);
    }
    function clear() {for(const entry of entries.values())clock.clearTimeout(entry.timer);entries.clear();paint();}
    return {begin,finish,paint,clear};
  }
  /* A single out-of-flow dock. On home it covers the third roster avatar;
     sheets use a fixed bottom inset, independent of footer/expanded content.
     Only scroll reachability is extended. No content node is inserted in flow. */
  function createDock({root,changed=()=>{}}) {
    const host=document.createElement('div');
    host.className='status-region status-dock';host.hidden=true;
    host.setAttribute('role','region');host.setAttribute('aria-label','状态提示');
    let surface=null,viewport=null,runway=null,baseRange=0,scheduled=0,holdRunway=false;
    const number=(key,fallback)=>parseFloat(getComputedStyle(root).getPropertyValue(key))||fallback;
    const request=()=>{if(!scheduled)scheduled=requestAnimationFrame(()=>{scheduled=0;layout();});};
    const resize=new ResizeObserver(request);resize.observe(root);
    const intersects=(a,b)=>a.bottom>b.top-6&&a.top<b.bottom+6&&a.left<b.right&&a.right>b.left;
    function clearRunway(force=false) {
      if(!runway)return;
      if(!force&&viewport?.scrollTop>baseRange+1){holdRunway=true;return;}
      runway.remove();runway=null;holdRunway=false;changed();
    }
    function revealFocus() {
      const node=document.activeElement;
      const overlaps=!host.hidden&&node&&surface?.contains(node)&&!host.contains(node)
        &&node!==viewport&&intersects(node.getBoundingClientRect(),host.getBoundingClientRect());
      // A fixed footer cannot scroll. Yield while its control owns focus rather
      // than moving the footer or raising the notification to a different slot.
      const yieldFocus=overlaps&&!viewport?.contains(node);
      host.classList.toggle('yields-to-focus',!!yieldFocus);
      if(yieldFocus)host.setAttribute('aria-hidden','true');else host.removeAttribute('aria-hidden');
    }
    function layout() {
      if(!surface?.isConnected||!host.isConnected)return;
      const bounds=surface.getBoundingClientRect();
      let bottom=number('--status-bottom',12);
      const footer=surface.querySelector(':scope > footer');
      const workflow=surface.classList.contains('is-onboarding')||['confirm','add','reauth','remove','resume-clear'].includes(surface.dataset.page);
      if(workflow&&footer){
        // Confirmation/login flows must never have their primary actions covered.
        bottom=bounds.bottom-footer.getBoundingClientRect().top+8;
      }else if(surface.id==='home') {
        bottom=number('--status-home-bottom',52);
        const avatar=surface.querySelector('.account-list > .row:nth-child(3) .avatar');
        if(avatar&&viewport) {
          const r=avatar.getBoundingClientRect();
          // Use the unscrolled reference slot, not the moving row under it.
          bottom=bounds.bottom-(r.top+viewport.scrollTop+r.height/2)-number('--status-height',40)/2;
        }
        bottom=Math.max(48,Math.min(80,bottom));
      }
      host.style.bottom=bottom+'px';
      revealFocus();
    }
    function reserveScroll() {
      if(!viewport||viewport.querySelector(':scope > .roster-empty'))return;
      const clearance=Math.max(0,viewport.getBoundingClientRect().bottom-host.getBoundingClientRect().top+8);
      if(clearance<1){clearRunway();return;}
      const scroll=viewport.scrollTop;
      if(runway)runway.remove();
      const extent=viewport.scrollHeight;
      baseRange=Math.max(0,extent-viewport.clientHeight);
      runway=document.createElement('span');runway.className='status-runway';
      runway.setAttribute('aria-hidden','true');runway.style.top=extent+'px';runway.style.height=clearance+'px';
      viewport.classList.add('dock-scroll-target');viewport.style.scrollPaddingBottom=clearance+'px';
      viewport.append(runway);viewport.scrollTop=scroll;changed();
    }
    function paint(next,html='') {
      if(!next)return;
      const nextViewport=next.querySelector('.sheet-body,.onboarding-main,.account-list');
      const moved=next!==surface||viewport!==nextViewport;
      const held=holdRunway&&next===surface;
      if(moved){clearRunway(true);surface=next;viewport=nextViewport;}
      if(host.parentElement!==next)next.append(host);
      const wasHidden=host.hidden;
      if(host.innerHTML!==html)host.innerHTML=html;
      host.hidden=!html;layout();
      if((html||held)&&(moved||wasHidden||!runway))reserveScroll();
      if(!html&&!held)clearRunway();
      holdRunway=held;
    }
    root.addEventListener('scroll',event=>{if(event.target===viewport&&host.hidden)clearRunway();},true);
    root.addEventListener('focusin',event=>{
      if(!host.hidden&&viewport?.contains(event.target)&&event.target!==viewport) {
        const node=event.target.getBoundingClientRect(),dock=host.getBoundingClientRect();
        if(intersects(node,dock))viewport.scrollTop+=node.bottom-dock.top+8;
      }
      revealFocus();
    });
    root.addEventListener('focusout',request);
    function refresh(){layout();if(!host.hidden)reserveScroll();}
    return {paint,layout,refresh,host};
  }
  return {status,controlKey,create,createDock};
})();
