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
    const [width,height]=window.NX_CONFIG.sizes.home;
    if(Math.abs(app.getBoundingClientRect().width-width)>.5||Math.abs(app.getBoundingClientRect().height-height)>.5)problems.push('面板尺寸变化');
    if(app.scrollWidth>app.clientWidth+1)problems.push('面板横向溢出');
    if(!surface)problems.push('缺少活动页面');
    const body=surface?.querySelector('.sheet-body');
    if(body&&body.scrollWidth>body.clientWidth+1)problems.push('正文横向溢出');
    if(info.page==='detail'&&body){
      const rows=[...body.querySelectorAll('.detail-item')].map(n=>n.matches('.control-container')?n.querySelector('.control-header'):n);
      const archive=body.querySelector('.danger-row'),note=body.querySelector('.detail-expiry-note'),editor=body.querySelector('.account-editor details[open]'),reset=body.classList.contains('reset-expanded'),vaultOpen=!!body.querySelector('.detail-vault.is-open');
      if(!archive||!note||note.previousElementSibling!==archive||getComputedStyle(note).position!=='static')problems.push('账号详情归档和日期未随正文排列');
      if(rows.length!==4)problems.push('账号详情缺少信息行');
      const controls=archive?[...rows,archive]:rows;
      if(new Set(controls.map(n=>n.getBoundingClientRect().height)).size>1||new Set(controls.map(n=>getComputedStyle(n).borderTopLeftRadius)).size>1)problems.push('账号详情信息行尺寸不一致');
      // An expanded disclosure is allowed to push the body past its height, the
      // same way the reset list and the nickname editor already are.
      if(!reset&&!editor&&!vaultOpen){
        const held=parseFloat(body.style.getPropertyValue('--detail-scroll-floor'))>0;
        if(!held&&(body.scrollTop||body.scrollHeight>body.clientHeight+1))problems.push('账号详情产生滚动');
        if(controls.slice(1).some((n,i)=>Math.abs(n.getBoundingClientRect().top-controls[i].getBoundingClientRect().bottom-6)>.5))problems.push('账号详情行间距不一致');
        if(archive&&archive.getBoundingClientRect().bottom>body.getBoundingClientRect().bottom+.5)problems.push('账号详情归档行溢出正文');
        if(note&&note.getBoundingClientRect().bottom>body.getBoundingClientRect().bottom+.5)problems.push('账号详情日期溢出正文');
      }
      if(editor&&[...editor.querySelectorAll('.inline-field')].some(n=>Math.abs(n.getBoundingClientRect().height-editor.querySelector('summary').getBoundingClientRect().height)>.5))problems.push('昵称与会员期限展开行高度不一致');
      if(reset){
        const summary=body.querySelector('.reset-summary'),list=body.querySelector('.reset-credit-details');
        if(list&&(getComputedStyle(list).position!=='static'||Math.abs(list.getBoundingClientRect().top-summary.getBoundingClientRect().bottom)>.5))problems.push('重置详情未随行展开');
        if(list&&[...list.querySelectorAll('.collection-row,.inline-empty')].some(n=>Math.abs(n.getBoundingClientRect().height-summary.getBoundingClientRect().height)>.5))problems.push('重置次数展开行高度不一致');
      }
      for(const selector of ['.detail-usage','.danger-row'])if(getComputedStyle(surface.querySelector(selector)).backgroundColor!=='rgba(0, 0, 0, 0)')problems.push('账号详情透明行出现底色');
    }
    for(const body of surface?.querySelectorAll('.settings-disclosure[open] > .disclosure-body')||[]){
      if(getComputedStyle(body).backgroundColor!=='rgba(0, 0, 0, 0)')problems.push('展开区域与入口底色不一致');
    }
    const message=surface?.querySelector('[data-disclosure="message"][open]');
    if(message){
      const height=message.querySelector('summary').getBoundingClientRect().height;
      if([...message.querySelectorAll('.toggle-line,.inline-field')].some(n=>Math.abs(n.getBoundingClientRect().height-height)>.5))problems.push('任务接续展开行高度不一致');
    }
    const current=info.page==='home'&&surface?.querySelector('.current-card > .current-identity');
    if(current){
      const card=current.parentElement.getBoundingClientRect(),row=current.getBoundingClientRect(),avatar=current.querySelector('.avatar')?.getBoundingClientRect();
      if(Math.abs(row.top-card.top-row.left+card.left)>.5)problems.push('首页账号悬停框上侧与左侧边距不一致');
      if(avatar&&Math.abs(row.top+row.height/2-avatar.top-avatar.height/2)>.5)problems.push('首页账号悬停框与头像未垂直居中');
    }
    const uninstallMark=surface?.querySelector('.uninstall-identity > .update-mark');
    if(uninstallMark){
      const mark=uninstallMark.getBoundingClientRect(),panel=surface.getBoundingClientRect(),css=getComputedStyle(uninstallMark),brand=document.querySelector('#home .header .mark');
      if(mark.width!==40||mark.height!==40||Math.abs(mark.left+mark.width/2-panel.left-panel.width/2)>.5||Math.abs(mark.top-body.getBoundingClientRect().top-20)>.5)problems.push('卸载页应用图标位置或尺寸不一致');
      if(brand&&css.color!==getComputedStyle(brand).color||css.opacity!=='1'||css.filter!=='none'||css.boxShadow!=='none')problems.push('卸载页应用图标颜色或遮罩异常');
    }
    for(const list of surface?.querySelectorAll('.disclosure-list')||[]){
      const count=Number(list.dataset.itemCount),size=window.NXComponents.listPageSize;
      if(!!list.querySelector('.resume-inline-pager')!==(count>size))problems.push('分页栏与条目数量不符');
      if(list.querySelectorAll('.resume-page-content > .collection-row').length>size)problems.push('列表单页条目超出上限');
    }
    for(const label of surface?.querySelectorAll('.settings-disclosure > summary > span:first-child,.toggle-line > span,.sheet-head h2,.transfer-select-head > span')||[]){
      if(!label.getBoundingClientRect().height||label.closest('[hidden],[inert],details:not([open]) .disclosure-body'))continue;
      const range=document.createRange();range.selectNodeContents(label);
      const tops=[];for(const r of range.getClientRects())if(r.width&&!tops.some(y=>Math.abs(y-r.y)<4))tops.push(r.y);
      if(tops.length>1)problems.push('单行标签换行：'+label.textContent.trim());
    }
    for(const line of surface?.querySelectorAll('.quota-bar-head,.quota-overview-window')||[]){
      if(!line.getBoundingClientRect().height)continue;
      const pieces=[...line.children].map(node=>node.getBoundingClientRect());
      if(line.scrollWidth>line.clientWidth+1||line.getBoundingClientRect().height>24||pieces.some((box,i)=>i&&box.left<pieces[i-1].right-1))problems.push('额度内容重叠或换行');
    }
    const roster=surface?.querySelector('.account-list'),heading=surface?.querySelector('.section-link');
    if(roster&&heading&&roster.getBoundingClientRect().top<heading.getBoundingClientRect().bottom-1)problems.push('账号列表侵入标题行');
    const selectHead=surface?.querySelector('.transfer-select-head'),selectAll=selectHead?.querySelector('button');
    if(selectAll&&selectHead.getBoundingClientRect().height){const a=selectHead.getBoundingClientRect(),b=selectAll.getBoundingClientRect();if(Math.abs(a.top+a.height/2-b.top-b.height/2)>.75)problems.push('全选按钮未垂直居中');}
    if(document.documentElement.dataset.material==='glass')for(const bar of surface?.querySelectorAll('.quota-overview-toolbar')||[])if(getComputedStyle(bar).backgroundColor!=='rgba(0, 0, 0, 0)')problems.push('玻璃材质栏位背景叠加');
    for(const head of surface?.querySelectorAll('.quota-bar-head')||[]){
      const time=head.querySelector('.reset'),percent=head.querySelector('b');
      if(time&&percent&&time.getBoundingClientRect().right>percent.getBoundingClientRect().left)problems.push('倒计时占用额度位置');
    }
    if([...app.querySelectorAll('*')].some(n=>n.__nxLocalMotionOwned||n.__nxMotionOwned||n.__nxMotionPlaceholder||n.__nxDisclosureOwned||n.__nxMotionRetained||n.__nxPopupActive))problems.push('动画结束后样式未释放');
    const notes=surface?.querySelector('#update-notes-body'),toggle=surface?.querySelector('#update-notes-toggle');
    if(notes&&!notes.hidden&&toggle){
      const gap=notes.getBoundingClientRect().top-toggle.getBoundingClientRect().bottom;
      if(gap<0||gap>8.5||notes.parentElement!==toggle.closest('.update-release'))problems.push('更新说明与版本入口脱节');
    }
    const controls=[];
    for(const button of surface?.querySelectorAll('button,summary')||[]) {
      if(button.__nxLocalMotionOwned||button.__nxMotionOwned||button.closest('[hidden],[inert],details:not([open]) .disclosure-body')||!button.getBoundingClientRect().height)continue;
      const css=getComputedStyle(button),height=parseFloat(css.height),border=parseFloat(css.borderTopWidth);
      const radius=parseFloat(css.borderTopLeftRadius),floor=4;
      const label=button.getAttribute('aria-label')||button.dataset.action||button.textContent.trim();
      const family=button.matches('.control')?'action':button.matches('.switch')?'switch':button.matches('.control--embedded')?'joined':button.matches('.support-code')?'media':button.matches('.status-bar')?'notification':'row';
      const proportionalRow=button.closest('.detail-compact')||button.matches('.settings-disclosure > summary,.settings-list > .link-row,.settings-list > .toggle-line,.settings-list > .setting-choice,.row,#home .current-card > .current-identity');
      const notification=button.closest('.status-notification');
      const expected=family==='action'||family==='switch'?height*.375:family==='joined'?0:family==='media'?12:family==='notification'?parseFloat(getComputedStyle(notification||button).height)*.375:button.matches('.section-link')?12:proportionalRow?height*.375:16;
      if(Math.abs(radius-expected)>.1)problems.push('控件圆角比例不一致：'+label);
      if(family==='action') {
        const icon=button.querySelector('.icon'),contentHeight=icon?parseFloat(getComputedStyle(icon).height):parseFloat(css.lineHeight);
        if((height-2*border-contentHeight)/2<floor-.1)problems.push('按钮内容贴近轮廓：'+label);
        if(!button.matches('.control--icon')&&parseFloat(css.paddingLeft)<floor-.1)problems.push('按钮横向留白不足：'+label);
      }
      if(family==='switch') {
        const thumb=button.querySelector('i'),a=button.getBoundingClientRect(),b=thumb.getBoundingClientRect();
        if(Math.min(b.top-a.top,a.bottom-b.bottom,b.left-a.left,a.right-b.right)<floor-.1)problems.push('开关滑块留白不足：'+label);
      }
      const operation=button.dataset.action||'';
      const content=(button.querySelector(':scope > .control-content')||button).textContent.trim();
      const confirmation=['execute-switch','execute-remove','adopt','start-add','start-reauth','install-update'].includes(operation)||['import-start','uninstall-start'].includes(operation)&&!content.startsWith('正在')||['use-reset','resume-clear'].includes(operation)&&content==='确认';
      const expectedWeight=confirmation?550:400;
      if(Number(css.fontWeight)!==expectedWeight)problems.push('操作按钮字重不一致：'+label);
      if(button.matches('.relay')&&Number(getComputedStyle(button.querySelector('.relay-label')).fontWeight)!==400)problems.push('首页接力操作文字过粗');
      if(button.scrollWidth>button.clientWidth+1)problems.push('控件内容被裁切：'+label);
      controls.push({family,label,operation,height,radius,weight:Number(css.fontWeight),confirmation,disabled:button.disabled||false});
    }
    if(surface?.querySelector('.resume-session-stats')||[...surface?.querySelectorAll('.resume-summary > strong')||[]].some(n=>n.textContent.includes('已接续')))problems.push('接续记录保留了多余汇总文字');
    const regions={};
    for(const selector of ['.header','.current-card','.relay','.section-link','.account-list','.row','.row .avatar','.footer','.sheet-head [data-action="back"]','.update-identity','.update-mark','.update-brand','.update-version','.update-github','.update-primary','.update-state','.update-description','.update-footer']){
      const node=surface?.querySelector(selector);
      if(node&&node.getBoundingClientRect().height)regions[selector]=bounds(node);
    }
    return {id,theme:document.documentElement.dataset.appearance,page:info.page,problems,regions,controls};
  }
  const waitForRest=()=>new Promise(resolve=>{
    const start=performance.now();
    function frame(){
      const active=window.NXLocalMotion?.active()||window.NXUsageMotion?.active()||[...document.getElementById('app').querySelectorAll('*')].some(n=>n.__nxMotionOwned||n.__nxMotionPlaceholder||n.__nxDisclosureOwned||n.__nxMotionRetained||n.__nxPopupActive);
      if(!active||performance.now()-start>1800)resolve();else requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  });
  function inspectLocalState(){
    const app=document.getElementById('app'),body=app.querySelector('#sheet .sheet-body');
    const groups=[...app.querySelectorAll('.segmented[data-segment]')].filter(node=>node.getBoundingClientRect().width).map(node=>{
      const a=node.getBoundingClientRect(),css=getComputedStyle(node),pseudo=getComputedStyle(node,'::before');
      const selected=node.querySelector('[aria-pressed="true"]'),b=selected.getBoundingClientRect();
      const scale=a.width/parseFloat(css.width),inset=parseFloat(css.paddingLeft);let x=0;
      try{x=new DOMMatrixReadOnly(pseudo.transform).m41;}catch{}
      const w=parseFloat(pseudo.width),extent=parseFloat(css.width)-inset-parseFloat(css.paddingRight);
      return {key:node.dataset.segment,value:selected.dataset.value,x,w,extent,
        indicatorLeft:a.left+(inset+x)*scale,indicatorWidth:w*scale,selectedLeft:b.left,selectedWidth:b.width,
        active:node.style.getPropertyValue('--segment-x')!=='',opacity:Number(css.opacity)};
    });
    const rows=[...app.querySelectorAll('[data-motion-list] > [data-email]')].map(node=>({email:node.dataset.email,...bounds(node),active:node.hasAttribute('data-local-moving')}));
    const pages=[...app.querySelectorAll('[data-motion-pages]')].filter(node=>node.getBoundingClientRect().width&&!node.closest('[hidden],[inert],details:not([open]) .disclosure-body')).map(node=>{
      const content=node.querySelector('.resume-page-content');let x=0;
      try{x=new DOMMatrixReadOnly(getComputedStyle(content).transform).m41;}catch{}
      return {key:node.dataset.motionPages,page:Number(node.dataset.page),offset:x,...bounds(node),
        tools:bounds(node.nextElementSibling),active:node.hasAttribute('data-page-moving'),
        ghosts:node.querySelectorAll('.resume-page-ghost').length,opacity:Number(getComputedStyle(content).opacity)};
    });
    return {at:performance.now(),groups,rows,pages,scroll:body?.scrollTop||0,bodyOpacity:body?Number(getComputedStyle(body).opacity):1};
  }
  async function inspectMotion(steps){
    const app=document.getElementById('app'),results=[];
    const rangeState=()=>{
      const group=app.querySelector('.usage-filter');if(!group)return null;
      const plot=app.querySelector('.trend'),layer=plot?.querySelector('.range-morph-layer'),pieces=layer?[...layer.children]:[];
      const filterCSS=getComputedStyle(group,'::before'),control=group.querySelector('[aria-pressed="true"]');
      const count=[...app.querySelectorAll('[data-count-value]')].map(node=>({key:node.dataset.countKey,value:node.dataset.countValue,text:node.textContent}));
      const samples=pieces.filter((_,i)=>i===0||i===Math.floor(pieces.length/2)||i===pieces.length-1).map(bounds);
      const summary=app.querySelector('.usage-summary'),body=summary.closest('.sheet-body');
      return {selected:control?.dataset.value,thumb:filterCSS.transform,count,pieces:pieces.length,samples,
        summary:bounds(summary),filter:bounds(group),transform:getComputedStyle(summary).transform,
        opacity:Number(getComputedStyle(summary).opacity)*Number(getComputedStyle(body).opacity),plotOpacity:Number(getComputedStyle(plot).opacity),
        card:bounds(app.querySelector('.current-card')),hiddenBars:[...plot.querySelectorAll(':scope > .trend-bar')].filter(node=>getComputedStyle(node).visibility==='hidden').length};
    };
    const cardSurface=()=>{
      const surface=app.querySelector('#sheet').hidden?app.querySelector('#home'):app.querySelector('#sheet');
      const node=surface.querySelector('.current-card');if(!node)return null;
      const color=getComputedStyle(node).backgroundColor,box=bounds(node);
      let opacity=1;for(let e=node;e&&e!==app;e=e.parentElement)opacity*=Number(getComputedStyle(e).opacity);
      const plates=[...surface.querySelectorAll('.motion-identity-plate')].map(plate=>{
        const css=getComputedStyle(plate),b=bounds(plate),overlap=Math.max(0,Math.min(box.x+box.w,b.x+b.w)-Math.max(box.x,b.x))*Math.max(0,Math.min(box.y+box.h,b.y+b.h)-Math.max(box.y,b.y));
        return {...b,color:css.backgroundColor,clip:css.clipPath,overlap};
      });
      return {...box,color,opacity,plates};
    };
    const originalRange=rangeState();let originalLocal=null;
    for(const step of steps){
      if(step.shared&&!originalLocal)originalLocal=inspectLocalState();
      const before=inspectLayout(),frames=[],start=performance.now();
      const beforeRange=rangeState();
      const beforeLocal=step.shared?inspectLocalState():null;
      let recording=true;
      const capture=()=>{
        if(!recording)return;
        const moving=[...app.querySelectorAll('*')].filter(n=>n.__nxMotionOwned&&n.style.position==='fixed'&&!n.__nxMotionDecoration);
        const body=app.querySelector('#sheet').hidden?app.querySelector('#home'):app.querySelector('#sheet .sheet-body');
        const secondary=[...app.querySelectorAll('#sheet .sheet-foot > .secondary')].filter(n=>n.getBoundingClientRect().height>0&&!n.closest('[hidden]')).map(n=>{const range=document.createRange();range.selectNodeContents(n);const text=range.getBoundingClientRect(),base=app.getBoundingClientRect();return {text:n.textContent,box:bounds(n),textBox:{x:text.x-base.x,y:text.y-base.y,w:text.width,h:text.height},flex:getComputedStyle(n).flex,opacity:Number(getComputedStyle(n).opacity)};});
        const entryContent=step.entry?[...body.querySelectorAll('.settings-group,.usage-summary,.usage-accounts,.roster,.footer,.relay')].map(n=>{let opacity=1;for(let e=n;e&&e!==app;e=e.parentElement)opacity*=Number(getComputedStyle(e).opacity);return {className:n.className,opacity};}):[];
        frames.push({time:performance.now()-start,card:step.cardBackdrop?cardSurface():null,secondary,entryContent,moving:moving.map(n=>({role:n.__nxMotionRole||(n.matches('.primary,.relay')?'primary':n.matches('.motion-surface')?'surface':'avatar'),...bounds(n),transform:getComputedStyle(n).transform})),slots:[...app.querySelectorAll('*')].filter(n=>n.__nxMotionPlaceholder).length,reveals:[...app.querySelectorAll('*')].filter(n=>n.__nxMotionRole==='reveal').map(n=>({opacity:Number(getComputedStyle(n).opacity),clip:getComputedStyle(n).clipPath,transform:getComputedStyle(n).transform})),bodyMotion:!!body?.getAnimations().length,local:step.shared?inspectLocalState():null,range:step.report||step.range||step.rangeSelection||step.immediate?rangeState():null,popups:[...app.querySelectorAll('*')].filter(n=>n.__nxPopupActive).length,disclosures:[...app.querySelectorAll('[data-disclosure]')].filter(n=>n.__nxDisclosureIntent!==undefined).map(n=>{const head=n.querySelector('summary,[aria-expanded]'),body=n.querySelector('.disclosure-body,.reset-credit-details,.resume-tasks,#update-notes-body'),css=head&&getComputedStyle(head);return {key:n.dataset.disclosure,...bounds(n),open:n.__nxDisclosureIntent,headHeight:head?.getBoundingClientRect().height||0,leftRadius:parseFloat(css?.borderBottomLeftRadius)||0,rightRadius:parseFloat(css?.borderBottomRightRadius)||0,bodyOpacity:body?Number(getComputedStyle(body).opacity):1};})});
        if(recording)requestAnimationFrame(capture);
      };
      capture();
      await applyStep({...step,wait:step.wait??420});
      if(!step.interrupt)await waitForRest();
      recording=false;
      const after=inspectLayout(),problems=after.problems.filter(p=>!(step.interrupt&&p==='动画结束后样式未释放'));
      if(frames.some(f=>f.moving.length>3||f.slots>3||new Set(f.moving.map(n=>n.role)).size!==f.moving.length||f.moving.some(n=>n.role==='primary')&&f.moving.some(n=>n.role==='surface')))problems.push('转场重复移动同一角色或抢占主按钮');
      if(frames.some(f=>f.moving.some(n=>n.x<-.75||n.y<-.75||n.x+n.w>app.clientWidth+.75||n.y+n.h>app.clientHeight+.75)))problems.push('移动元素超出面板');
      if(frames.some(f=>f.moving.some(n=>n.role==='primary'&&n.transform!=='none'&&!/^matrix\(1, 0, 0, 1,/.test(n.transform))))problems.push('主按钮文字发生缩放');
      if(step.stable){
        if(frames.some(f=>f.moving.length))problems.push('数据刷新重播切页动画');
        for(const [key,old] of Object.entries(before.regions)){
          const current=after.regions[key];
          if(current&&['x','y','w','h','font'].some(k=>Math.abs(current[k]-old[k])>.5))problems.push('原位操作改变布局：'+key);
        }
      }
      if(step.hero&&!frames.some(f=>f.moving.some(n=>n.role===step.hero)))problems.push('主要元素没有衔接动画');
      if(step.footer&&!step.interrupt){
        const values=frames.filter(f=>f.secondary.length).map(f=>f.secondary[0]);
        const end=values.at(-1);
        if(end&&values.some(n=>Math.abs(n.box.w-end.box.w)>.5||Math.abs(n.textBox.x-end.textBox.x)>.5||Math.abs(n.textBox.y-end.textBox.y)>.5))problems.push('返回或取消文字随占位释放跳变');
      }
      if(step.accountLink&&!frames.some(f=>f.moving.some(n=>n.role==='primary')&&f.moving.some(n=>n.role==='avatar')))problems.push('账号身份没有伴随主按钮衔接');
      if(step.navigationEntry&&window.NXMotion.enabled()){
        const positions=frames.flatMap(f=>f.moving.filter(n=>n.role==='entry'));
        if(!positions.length)problems.push('导航入口没有连续移动');
        if(!step.interrupt&&new Set(positions.map(n=>n.x.toFixed(2)+','+n.y.toFixed(2))).size<3)problems.push('导航入口缺少中间帧');
      }
      if(step.navigationStatic&&frames.some(f=>f.moving.some(n=>n.role==='entry')))problems.push('关闭动效后导航仍在移动');
      if(step.entry){
        if(!frames.some(f=>f.moving.some(n=>n.role==='entry')&&f.reveals.length))problems.push('首页入口与正文没有同步展开');
        if(frames.some(f=>f.bodyMotion||f.reveals.some(n=>n.opacity!==1)||f.entryContent.some(n=>Math.abs(n.opacity-1)>.001)))problems.push('首页入口正文退化成整页移动或淡入淡出');
      }
      if(step.contained){
        if(!frames.some(f=>f.reveals.length))problems.push('后续页面没有使用分组展开');
        if(frames.some(f=>f.bodyMotion||f.reveals.some(n=>n.opacity!==1)))problems.push('后续页面退回整页淡入或移动');
      }
      if(step.media&&!frames.some(f=>f.moving.some(n=>n.role==='media')))problems.push('图片没有从原图连续放大或缩回');
      if(step.identityLink&&!frames.some(f=>f.moving.some(n=>n.role==='avatar')))problems.push('列表身份没有接续到详情');
      if(step.disclosure&&!frames.some(f=>f.disclosures.length))problems.push('展开项没有平滑过渡');
      if(step.cardBackdrop){
        const cards=frames.map(f=>f.card).filter(Boolean);
        if(cards.some(n=>Math.abs(n.opacity-1)>.001))problems.push('顶部账号底框出现透明度闪动');
        if(cards.some(n=>n.plates.some(p=>p.overlap>1&&p.clip==='none'&&p.color!==n.color)))problems.push('移动衬底覆盖顶部灰色卡片');
      }
      if(step.fold&&window.NXMotion.enabled()){
        const all=frames.flatMap(f=>f.disclosures);
        const keys=step.fold===true?[...new Set(all.map(n=>n.key))]:Array.isArray(step.fold)?step.fold:[step.fold];
        if(!keys.length)problems.push('折叠区域没有连续中间帧');
        for(const key of keys){
          const samples=all.filter(n=>n.key===key);
          if(!samples.length||!step.interrupt&&new Set(samples.map(n=>n.h.toFixed(2))).size<3)problems.push('折叠高度没有连续变化：'+key);
          if(samples.some(n=>n.h>n.headHeight+.75&&(n.leftRadius>.1||n.rightRadius>.1)))problems.push('内容未收完就恢复标题圆角：'+key);
          if(samples.some(n=>Math.abs(n.bodyOpacity-1)>.001))problems.push('折叠内容提前淡出：'+key);
        }
      }
      if(step.foldStatic&&frames.some(f=>f.disclosures.length))problems.push('关闭动效后仍在折叠动画');
      if(step.group&&!frames.some(f=>f.bodyMotion))problems.push('普通切页没有整体过渡');
      if(step.popup&&!frames.some(f=>f.popups))problems.push('浮动提示没有显示或收起动画');
      if(step.shared){
        const localFrames=frames.map(frame=>frame.local).filter(Boolean),endLocal=inspectLocalState();
        if(localFrames.some(value=>value.bodyOpacity!==1||value.groups.some(group=>group.opacity!==1)))problems.push('分段切换淡入淡出');
        if(localFrames.some(value=>value.groups.some(group=>group.x<-.1||group.x+group.w>group.extent+.1)))problems.push('选中块超出控件留白');
        if(!step.interrupt){
          if(endLocal.groups.some(group=>group.active||Math.abs(group.indicatorLeft-group.selectedLeft)>.5||Math.abs(group.indicatorWidth-group.selectedWidth)>.5))problems.push('选中块没有对齐实际选项');
          if(endLocal.rows.some(row=>row.active))problems.push('排序结束后行位移未释放');
          if(endLocal.rows.some((row,i,array)=>i&&row.y<array[i-1].y+array[i-1].h-.5))problems.push('排序结束后账号行重叠');
        }
        if(step.sharedMove&&!localFrames.some(value=>value.groups.some(group=>group.active)))problems.push('分段控件没有连续移动');
        if(step.rowMove&&!localFrames.some(value=>value.rows.some(row=>row.active)))problems.push('额度排序没有平滑换位');
        if(step.immediateShared&&localFrames.some(value=>value.groups.some(group=>group.active)||value.rows.some(row=>row.active)))problems.push('关闭动效后仍有位移');
        if(step.expectSelection&&Object.entries(step.expectSelection).some(([key,value])=>endLocal.groups.find(group=>group.key===key)?.value!==value))problems.push('最后一次选择未生效');
        if(step.localReturn){
          const state=value=>JSON.stringify({groups:value.groups.map(group=>[group.key,group.value]),rows:value.rows.map(row=>row.email)});
          if(state(endLocal)!==state(originalLocal))problems.push('连续切换后状态未恢复');
        }
        if(step.pagination){
          const before=beforeLocal.pages[0],end=endLocal.pages[0];
          const references=new Map(beforeLocal.pages.map(page=>[page.key,page]));
          if(!end||end.page!==step.pagination)problems.push('换页没有保留最后一次选择');
          if(localFrames.some(value=>value.pages.some(page=>page.opacity!==1)))problems.push('换页出现淡入淡出');
          if(localFrames.some(value=>value.scroll!==beforeLocal.scroll||value.pages.some(page=>{const reference=references.get(page.key);return reference&&(['x','y','w','h'].some(key=>Math.abs(page[key]-reference[key])>.5)||['x','y','w','h'].some(key=>Math.abs(page.tools[key]-reference.tools[key])>.5));})))problems.push('换页改变了外框、按钮或滚动位置');
          if(step.pageMove&&!localFrames.some(value=>value.pages.some(page=>page.active&&Math.abs(page.offset)>.5)))problems.push('换页没有平滑移动');
          if(!step.interrupt&&end&&(end.active||end.ghosts||Math.abs(end.offset)>.01))problems.push('换页结束后临时内容未释放');
        }
      }
      if(step.range||step.rangeSelection||step.immediate){
        const rangeFrames=frames.map(frame=>frame.range).filter(Boolean),endRange=rangeState();
        if(rangeFrames.some(value=>value.opacity!==1||value.plotOpacity!==1))problems.push('时间范围切换出现淡入淡出');
        if(rangeFrames.some(value=>Object.keys(beforeRange.card).some(key=>Math.abs(value.card[key]-beforeRange.card[key])>.5)))problems.push('时间范围切换移动了账号卡片');
        if(!step.interrupt&&endRange&&(endRange.pieces||endRange.hiddenBars))problems.push('图表动画没有恢复真实柱形');
        if(step.range&&!rangeFrames.some(value=>value.pieces))problems.push('图表没有连续形变');
        if(step.range&&new Set(rangeFrames.filter(value=>value.pieces).map(value=>JSON.stringify(value.samples))).size<2)problems.push('柱形停留在同一动画帧');
        if(step.immediate&&rangeFrames.some(value=>value.pieces))problems.push('关闭动效后仍播放图表动画');
        if(step.rangeReturn&&JSON.stringify(endRange?.count)!==JSON.stringify(originalRange?.count))problems.push('来回切换后数值没有恢复');
      }
      if(step.report){
        const values=frames.map(frame=>frame.range).filter(Boolean),end=rangeState();
        if(values.some(value=>value.opacity!==1||value.plotOpacity!==1))problems.push('账号范围切换重新淡入用量内容');
        if(values.some(value=>value.transform!=='none'&&!/^matrix\(1, 0, 0, 1,/.test(value.transform)))problems.push('用量报告文字发生缩放');
        if(step.reportMove&&new Set(values.map(value=>value.summary.y.toFixed(2))).size<3)problems.push('用量报告没有连续移动');
        if(step.reportChart&&!values.some(value=>value.pieces))problems.push('账号范围切换没有延续图表形态');
        if(window.NXMotion.enabled()&&beforeRange&&values[1]&&Math.abs(values[1].summary.y-beforeRange.summary.y)>8)problems.push('报告移动第一帧出现跳变');
        if(!step.interrupt&&end&&(end.pieces||end.hiddenBars))problems.push('账号范围切换后图表未释放');
        if(step.reportReturn&&JSON.stringify(end?.count)!==JSON.stringify(originalRange?.count))problems.push('返回总览后数据没有恢复');
      }
      if(step.scroll&&step.top==='bottom'){
        const region=document.querySelector(step.scroll);
        if(region.scrollTop+region.clientHeight<region.scrollHeight-1)problems.push('长内容末尾不可到达');
      }
      results.push({step:step.click||step.simulate||step.scroll||(typeof step.motion==='boolean'?'motion:'+step.motion:''),frames,after,range:rangeState(),local:step.shared?inspectLocalState():null,problems});
    }
    return results;
  }
  addEventListener('error',event=>report('error',{message:event.message||'页面脚本异常'}));
  addEventListener('unhandledrejection',event=>report('error',{message:String(event.reason?.message||event.reason||'异步操作异常')}));
  async function applyStep(step) {
    if(typeof step.motion==='boolean'){window.NXMotion.setEnabled(step.motion);await wait(step.wait??40);return;}
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
  window.NXPreview.inspectLayout=inspectLayout;
  window.NXPreview.inspectMotion=inspectMotion;
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
