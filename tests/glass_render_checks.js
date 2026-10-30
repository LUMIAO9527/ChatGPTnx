/* Real WebView2 checks: translucent surfaces, stable body origins and every
   intermediate frame of account entry, return and interrupted navigation. */
window.nxCheckGlassRendering = async () => {
  const checks=[], failures=[], layouts=[], transitions=[];
  const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const assert=(condition,message)=>{checks.push(message);if(!condition)failures.push(message);};
  const app=document.getElementById('app');
  const alpha=value=>{const parts=(value.match(/[\d.]+/g)||[]).map(Number);return parts.length===4?parts[3]:parts.length===3?1:0;};
  const active=()=>document.getElementById('sheet')?.hidden?document.getElementById('home'):document.getElementById('sheet');
  const bounds=node=>{const r=node.getBoundingClientRect(),a=app.getBoundingClientRect();return {x:r.x-a.x,y:r.y-a.y,w:r.width,h:r.height};};
  async function rest(){await wait(380);}
  async function record(label,action,interrupt){
    const frames=[];let recording=true;
    const frame=()=>{
      const plate=app.querySelector('.motion-identity-plate');
      const card=active()?.querySelector('.current-card');
      frames.push({t:performance.now(),plate:plate?alpha(getComputedStyle(plate).backgroundColor):0,
        card:card?alpha(getComputedStyle(card).backgroundColor):0,
        homeHidden:!document.getElementById('home').inert||getComputedStyle(document.getElementById('home')).visibility==='hidden',
        temporary:app.querySelectorAll('.motion-identity-plate').length});
      if(recording)requestAnimationFrame(frame);
    };
    action();requestAnimationFrame(frame);
    if(interrupt){await wait(75);interrupt();}
    await rest();recording=false;
    assert(frames.length>=3,label+': captured intermediate frames');
    assert(frames.every(f=>f.plate<.7),label+': identity protection stays translucent');
    assert(frames.every(f=>f.homeHidden),label+': home never paints through the page');
    assert(frames.every(f=>f.temporary<=1),label+': bounded identity layer');
    assert(!app.querySelector('.motion-identity-plate'),label+': no resting protection layer');
    transitions.push({label,frames});
  }
  const original=window.NXDemo.state().settings.appearance;
  for(const appearance of ['light','dark']){
    await window.NXPreview.appearance(appearance);
    window.NXPreview.home();await rest();
    assert(document.documentElement.dataset.material==='glass',appearance+': glass is active');
    assert(alpha(getComputedStyle(app.querySelector('.mark')).color)===1,appearance+': logo ink is opaque');
    assert(alpha(getComputedStyle(app.querySelector('.footer')).backgroundColor)===0,appearance+': footer is transparent');
    assert(Math.abs(bounds(app).w-312)<=1,appearance+': compact panel width');
    assert(parseFloat(getComputedStyle(app).getPropertyValue('--radius-window'))===16,appearance+': product radius is 16px');
    assert(parseFloat(getComputedStyle(app,'::after').borderTopLeftRadius)===16,appearance+': glass highlight follows the rounded outline');
    for(const page of ['detail','usage','settings','quota-overview']){
      await window.NXPreview.open(new URLSearchParams('open='+page));await rest();
      const surface=active(),head=surface.querySelector('.sheet-head'),body=surface.querySelector('.sheet-body');
      const firstNode=body.querySelector('.current-card,.settings-content,.quota-overview-toolbar')
        ||[...body.children].find(node=>node.getBoundingClientRect().height>0);
      const header=bounds(head),first=bounds(firstNode);
      layouts.push({appearance,page,header,first});
      assert(Math.abs(header.h-42)<.6,appearance+'/'+page+': compact shared title row');
      assert(Math.abs(first.y-(page==='settings'?45:53))<1,appearance+'/'+page+': expected body origin');
      assert(body.scrollWidth<=body.clientWidth+1,appearance+'/'+page+': no horizontal overflow');
      if(page==='usage'){
        assert(alpha(getComputedStyle(surface.querySelector('.usage-summary')).backgroundColor)===0,appearance+': overview report stays transparent');
      }
      window.NXPreview.home();await rest();
    }
    const row=()=>app.querySelector('#home .row[data-email="work-02@example.com"]');
    const back=()=>app.querySelector('.sheet-head [data-action="back"]');
    await record(appearance+'/account-entry',()=>row().click());
    await record(appearance+'/account-return',()=>back().click());
    await record(appearance+'/rapid-return',()=>row().click(),()=>back().click());
  }
  await window.NXPreview.appearance(original);window.NXPreview.home();await rest();
  return {passed:checks.length-failures.length,total:checks.length,failures,layouts,transitions};
};

window.nxCheckNativeMaterialSwitching = async () => {
  const cases=[],failures=[];
  const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  for(const appearance of ['light','dark']){
    await window.NXPreview.appearance(appearance);
    await window.NXPreview.open(new URLSearchParams('open=settings'));
    await wait(380);
    const disclosure=document.querySelector('[data-disclosure="appearance"]');
    if(!disclosure.open){disclosure.querySelector('summary').click();await wait(380);}
    for(const material of ['solid','glass','solid','glass']){
      document.querySelector(`[data-segment="pref:window_material"] [data-value="${material}"]`).click();
      await wait(180);await window.NX_NATIVE_SYNC;await wait(60);
      const native=await window.pywebview.api.material_state();
      const shown=document.documentElement.dataset.material;
      const expected=material==='glass'?'blur':'solid';
      const ok=native.mode===expected&&shown===material&&!native.native_error
        &&(material!=='glass'||native.backdrop_clip?.radius>0);
      cases.push({appearance,material,shown,...native,ok});
      if(!ok)failures.push(appearance+'/'+material+': '+JSON.stringify(native));
    }
  }
  await window.NXPreview.appearance('light');window.NXPreview.home();
  return {passed:cases.filter(c=>c.ok).length,total:cases.length,failures,cases};
};
