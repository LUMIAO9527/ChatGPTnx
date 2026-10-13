/* Demo-only driver. Uses real navigation/actions; never linked to panel.html. */
'use strict';
(() => {
  const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const params=new URLSearchParams(window.NX_PREVIEW_QUERY??location.search);
  const id=window.NX_PREVIEW_CASE||params.get('case');
  const selected=(window.NX_CATALOG||[]).find(c=>c.id===id);
  const report=(type,extra={})=>{if(parent!==window)parent.postMessage({source:'chatgptnx-preview',type,...extra},'*');};
  const bounds=node=>{
    if(!node)return null;
    const box=node.getBoundingClientRect(),app=document.getElementById('app').getBoundingClientRect();
    return {x:box.x-app.x,y:box.y-app.y,w:box.width,h:box.height,font:parseFloat(getComputedStyle(node).fontSize)};
  };
  function inspectLayout(){
    const app=document.getElementById('app'),info=window.NXPreview.info();
    const surface=info.page==='home'||info.page==='onboarding'?document.getElementById('home'):document.getElementById('sheet');
    const problems=[];
    if(Math.abs(app.getBoundingClientRect().width-327)>.5||Math.abs(app.getBoundingClientRect().height-458)>.5)problems.push('面板尺寸变化');
    if(app.scrollWidth>app.clientWidth+1)problems.push('面板横向溢出');
    if(!surface)problems.push('缺少活动页面');
    const body=surface?.querySelector('.sheet-body');
    if(body&&body.scrollWidth>body.clientWidth+1)problems.push('正文横向溢出');
    if([...app.querySelectorAll('*')].some(n=>n.__nxMotionOwned||n.__nxMotionPlaceholder||n.__nxDisclosureOwned||n.__nxMotionRetained||n.__nxPopupActive))problems.push('动画结束后样式未释放');
    const notes=surface?.querySelector('#update-notes-body'),toggle=surface?.querySelector('#update-notes-toggle');
    if(notes&&!notes.hidden&&toggle){
      const gap=notes.getBoundingClientRect().top-toggle.getBoundingClientRect().bottom;
      if(gap<0||gap>8.5||notes.parentElement!==toggle.closest('.update-release'))problems.push('更新说明与版本入口脱节');
    }
    if(surface?.querySelector('.resume-session-stats')||[...surface?.querySelectorAll('.resume-summary > strong')||[]].some(n=>n.textContent.includes('已接续')))problems.push('接续记录保留了多余汇总文字');
    const regions={};
    for(const selector of ['.header','.current-card','.relay','.section-link','.account-list','.row','.row .avatar','.footer','.sheet-head [data-action="back"]','.update-identity','.update-mark','.update-brand','.update-version','.update-github','.update-primary','.update-state','.update-description','.update-footer']){
      const node=surface?.querySelector(selector);
      if(node&&node.getBoundingClientRect().height)regions[selector]=bounds(node);
    }
    return {id,theme:document.documentElement.dataset.appearance,page:info.page,problems,regions};
  }
  const waitForRest=()=>new Promise(resolve=>{
    const start=performance.now();
    function frame(){
      const active=[...document.getElementById('app').querySelectorAll('*')].some(n=>n.__nxMotionOwned||n.__nxMotionPlaceholder||n.__nxDisclosureOwned||n.__nxMotionRetained||n.__nxPopupActive);
      if(!active||performance.now()-start>1800)resolve();else requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  });
  async function inspectMotion(steps){
    const app=document.getElementById('app'),results=[];
    for(const step of steps){
      const before=inspectLayout(),frames=[],start=performance.now();
      let recording=true;
      const capture=()=>{
        const moving=[...app.querySelectorAll('*')].filter(n=>n.__nxMotionOwned&&n.style.position==='fixed');
        const body=app.querySelector('#sheet').hidden?app.querySelector('#home'):app.querySelector('#sheet .sheet-body');
        frames.push({time:performance.now()-start,moving:moving.map(n=>({role:n.matches('.primary,.relay')?'primary':n.matches('.motion-surface')?'surface':'avatar',...bounds(n),transform:getComputedStyle(n).transform})),slots:[...app.querySelectorAll('*')].filter(n=>n.__nxMotionPlaceholder).length,bodyMotion:!!body?.getAnimations().length,popups:[...app.querySelectorAll('*')].filter(n=>n.__nxPopupActive).length,disclosures:[...app.querySelectorAll('[data-disclosure]')].filter(n=>n.__nxDisclosureIntent!==undefined).map(n=>({key:n.dataset.disclosure,...bounds(n)}))});
        if(recording)requestAnimationFrame(capture);
      };
      capture();
      await applyStep({...step,wait:step.wait??420});
      if(!step.interrupt)await waitForRest();
      recording=false;
      const after=inspectLayout(),problems=after.problems.filter(p=>!(step.interrupt&&p==='动画结束后样式未释放'));
      if(frames.some(f=>f.moving.length>1||f.slots>1))problems.push('一个转场出现多个移动元素');
      if(frames.some(f=>f.moving.some(n=>n.x<-.75||n.y<-.75||n.x+n.w>327.75||n.y+n.h>458.75)))problems.push('移动元素超出面板');
      if(frames.some(f=>f.moving.some(n=>n.role==='primary'&&n.transform!=='none'&&!/^matrix\(1, 0, 0, 1,/.test(n.transform))))problems.push('主按钮文字发生缩放');
      if(step.stable){
        if(frames.some(f=>f.moving.length))problems.push('数据刷新重播切页动画');
        for(const [key,old] of Object.entries(before.regions)){
          const current=after.regions[key];
          if(current&&['x','y','w','h','font'].some(k=>Math.abs(current[k]-old[k])>.5))problems.push('原位操作改变布局：'+key);
        }
      }
      if(step.hero&&!frames.some(f=>f.moving.some(n=>n.role===step.hero)))problems.push('主要元素没有衔接动画');
      if(step.disclosure&&!frames.some(f=>f.disclosures.length))problems.push('展开项没有平滑过渡');
      if(step.group&&!frames.some(f=>f.bodyMotion))problems.push('普通切页没有整体过渡');
      if(step.popup&&!frames.some(f=>f.popups))problems.push('浮动提示没有显示或收起动画');
      if(step.scroll&&step.top==='bottom'){
        const region=document.querySelector(step.scroll);
        if(region.scrollTop+region.clientHeight<region.scrollHeight-1)problems.push('长内容末尾不可到达');
      }
      results.push({step:step.click||step.simulate||step.scroll,frames,after,problems});
    }
    return results;
  }
  addEventListener('error',event=>report('error',{message:event.message||'页面脚本异常'}));
  addEventListener('unhandledrejection',event=>report('error',{message:String(event.reason?.message||event.reason||'异步操作异常')}));
  async function applyStep(step) {
    if(step.simulate){window.NXDemo.simulate(step.simulate);await window.NXPreview.refresh();await wait(step.wait??80);return;}
    const target=step.click||step.fill||step.hover||step.scroll;
    let node;
    for(let attempt=0;attempt<40;attempt++){
      node=document.querySelector(target);
      if(node && !node.disabled)break;
      await wait(50);
    }
    if(!node||node.disabled)throw new Error('演示步骤找不到可用控件：'+target);
    if(step.click)node.click();
    if(step.fill){node.value=step.value;node.dispatchEvent(new Event('input',{bubbles:true}));}
    if(step.scroll)node.scrollTop=step.top==='bottom'?node.scrollHeight:(step.top||0);
    if(step.hover){node.dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));}
    await wait(step.wait??120);
  }
  window.NX_CASE_READY=false;
  window.NX_CASE_PROMISE=(async()=>{
    await window.NXPreviewReady;
    for(const step of selected?.steps||[])await applyStep(step);
    await wait(40);
    window.NX_CASE_READY=true;report('ready',{id,info:window.NXPreview.info()});
  })().catch(error=>{window.NX_CASE_ERROR=String(error.message||error);report('error',{message:window.NX_CASE_ERROR});});
  window.addEventListener('message',async event=>{
    if(event.source!==parent||event.data?.source!=='chatgptnx-explorer')return;
    const {command,value}=event.data;
    try{
      if(command==='appearance')await window.NXPreview.appearance(value);
      else if(command==='simulate'){window.NXDemo.simulate(value);await window.NXPreview.refresh();}
      else if(command==='audit-layout'){await window.NX_CASE_PROMISE;await wait(360);await waitForRest();report('audit-layout',{result:inspectLayout()});return;}
      else if(command==='audit-motion'){await window.NX_CASE_PROMISE;await wait(360);await waitForRest();report('audit-motion',{result:await inspectMotion(value)});return;}
      report('state',{info:window.NXPreview.info()});
    }catch(error){report('error',{message:String(error.message||error)});}
  });
  let lastInfo='';
  setInterval(()=>{if(!window.NX_CASE_READY)return;const info=window.NXPreview.info(),key=JSON.stringify(info);if(key!==lastInfo){lastInfo=key;report('state',{info});}},400);
})();
