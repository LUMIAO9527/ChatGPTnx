/* Relay page rendering, navigation, and cancellable bridge coordination. */
'use strict';
(() => {
  const config = window.NX_CONFIG;
  const math = window.NXMath;
  const {readEpoch, coalescedRefresh, focusKey, restoreFocus, captureScroll, restoreScroll} = window.NXRuntime;
  const navigation = readEpoch();
  const poll = coalescedRefresh(performPoll);
  function homeContent() {
    const c=current()||(data.adding?data.accounts.find(a=>a.email===data.add_state?.previous):null);
    const next=data.adding?null:relay();
    const accounts=data.accounts.filter(a=>a.email!==c?.email&&a.email!==next?.email);
    const main=c?accountCard(c,false,data.adding?'添加前账号':'正在使用'):'';
    return header()+statusRegion(notice())+main+(data.adding?'':relayButton())+`<section class="roster"><button class="section-head section-link" data-action="quota-overview" aria-label="查看全部账号额度"><span>其他账号</span><span>${accounts.length} 个 · 查看全部 ${icon('chevron')}</span></button><div class="account-list">${accounts.map(accountRow).join('')||'<div class="roster-empty" role="status"><span>没有其他账号</span></div>'}</div></section>`+footer();
  }
  const $ = (q, root = document) => root.querySelector(q);
  const {esc, icon, tool, segmented, systemSettings, autoRelaySetting, taskContinuationSetting,
         notificationSettings, quotaSummary, quotaColumns, remaining, displayWindows, planLabel, accountName, accountChoice, creditValue, brandMark, avatar, accountIdentity} = window.NXComponents;
  const defaults = {appearance:'system', autostart:false,
    auto_relay:false, auto_relay_excluded:[], early_anchor:false, early_anchor_accounts:[], task_continuation:true, resume_message:'继续',
    notify_credential:true, notify_low:false, notify_reset_expiry:true, relay_pick:null};
  let data = {accounts:[], current:null, updated:null, settings:{...defaults}, hotkeys:[]};
  let workflowResume = false;
  const ui = {page:null, email:null, history:[], scope:'all', days:30, usage:null, usageRevision:-1, submitted:null, recording:null, switchKind:'manual', quotaMetric:'quota', quotaScope:'relay', resumeDetails:[], resumeExpanded:new Set(), resumeCollapsed:new Set(), resetExpanded:new Set(), disclosures:new Set(), fullCollections:new Set(), inlineLoading:{archives:'idle'}, inlineRequests:{}, messageDraft:null, metaDrafts:new Map(), fieldRevisions:new Map()};
  let connected = false, bridgeError = '', acting = false, previousFocus = null, previousFocusKey = null, freshSignature = '', lastErrorId = '', pollTimer = null, panelVisible = !!config.demo;
  const app = $('#app');
  app.innerHTML = '<main id="home"></main><section id="sheet" class="sheet" role="dialog" aria-modal="true" aria-labelledby="sheet-title" hidden></section><div id="announcer" class="sr-only" role="status" aria-live="polite" aria-atomic="true"></div>';
  const home = $('#home'), sheet = $('#sheet');
  const {status:statusBar} = window.NXFeedback;
  const feedback = window.NXFeedback.create({root:app,announce:message=>{$('#announcer').textContent=message;}});
  let controlOperation=null;
  let notification=null,notificationTimer=null,dismissedStatus=null,activeStatusKey='',lastAnnouncedStatus='';
  const statusDock=window.NXFeedback.createDock({root:app});
  function settingValue(key,source=data) {
    if(key.startsWith('anchor:'))return (source.settings.early_anchor_accounts||[]).includes(key.slice(7));
    return key.startsWith('account:')?!(source.settings.auto_relay_excluded||[]).includes(key.slice(8)):source.settings[key];
  }
  function projectSetting(key,value,target=data) {
    if(key.startsWith('anchor:')){
      const selected=new Set(target.settings.early_anchor_accounts||[]),email=key.slice(7);
      value?selected.add(email):selected.delete(email);target.settings.early_anchor_accounts=[...selected];return;
    }
    if(key.startsWith('account:')){
      const excluded=new Set(target.settings.auto_relay_excluded||[]),email=key.slice(8);
      value?excluded.delete(email):excluded.add(email);target.settings.auto_relay_excluded=[...excluded];
    }else target.settings[key]=value;
  }
  const preferences=window.NXPreferences.create({
    read:key=>settingValue(key),project:projectSetting,
    write:(key,value)=>key.startsWith('anchor:')?api('set_early_anchor_account',key.slice(7),value):key.startsWith('account:')?api('set_auto_relay_account',key.slice(8),value):api('set_preferences',{[key]:value}),
    changed:()=>{applyAppearance(data.settings.appearance);render();},
    failed:error=>notify(error.message||'设置未保存，已恢复原状态',{tone:'error'}),
    settled:()=>poll(true)
  });
  // Inert metadata carries workflow-specific status; visible feedback exists
  // exactly once, in the active surface's dock (inside the modal when open).
  function statusRegion(fallback='') {
    return `<template class="status-source" data-default="${esc(fallback)}"></template>`;
  }
  function wrapStatus(html,action='dismiss-status') {
    return `<div class="status-notification">${html}<button class="status-dismiss" data-action="${action}" aria-label="收起状态提示" title="收起提示，记录仍保留">${icon('close')}</button></div>`;
  }
  function notificationMarkup() {
    if(!notification)return '';
    return wrapStatus(statusBar({text:notification.text,tone:notification.tone,action:'feedback-details'}),'dismiss-feedback');
  }
  function paintNotifications() {
    const surface=ui.page&&!sheet.hidden?sheet:home;
    const contextual=[...surface.querySelectorAll('template.status-source')].map(n=>n.dataset.default).find(Boolean);
    const fallback=controlOperation?statusBar({text:controlOperation.text,tone:'progress'}):contextual||(['error','resume','resume-clear'].includes(ui.page)?'':notice());
    activeStatusKey=fallback+'|'+(data.last_error?.id||'')+'|'+(data.resume?.id||'');
    const html=notificationMarkup()||(fallback&&dismissedStatus!==activeStatusKey?wrapStatus(fallback):'');
    statusDock.paint(surface,html);
    if(html&&html!==lastAnnouncedStatus){lastAnnouncedStatus=html;$('#announcer').textContent=statusDock.host.querySelector('.status-text')?.textContent||'';}
    if(!html)lastAnnouncedStatus='';
  }
  function clearNotification(){clearTimeout(notificationTimer);notification=null;paintNotifications();}

  const now = () => Math.floor(Date.now()/1000);
  const name = accountName;
  const email = a => a?.email || '';
  const plan = planLabel;
  const current = () => data.accounts.find(a=>a.email===data.current);
  const hotkey = raw => data.hotkeys?.find(item=>item.email===raw) || {};
  const hotkeyLabel = value => value ? value.split('+').map(part=>part==='ctrl'?'Ctrl':part[0].toUpperCase()+part.slice(1)).join(' ') : '未设置';
  const busy = () => acting || !!data.operation || !!data.switching;
  const disabled = () => busy() ? 'disabled' : '';
  const fresh = a => !!a?.ok && Number.isFinite(a.fetched_at) && now()-(a.fetched_at)>=-60 && now()-(a.fetched_at)<=600;
  const valid = a => fresh(a) && a.windows?.length > 0 && a.windows.every(w=>Number.isFinite(w.used) && w.used>=0 && w.used<=100 && w.resets_at>now());
  const duration = w => w.duration_mins || ({'5h':300,'周':10080}[w.label] || w.label);
  const remainingFor = (a,minutes) => {const w=(a.windows||[]).find(w=>duration(w)===minutes);return w?100-w.used:null;};
  function relay() {
    return data.accounts.find(a=>a.email===data.relay_email && a.email!==data.current) || null;
  }
  function age(ts) {
    if (!ts) return '尚未更新';
    const n=Math.max(0,now()-ts); return n<60?'刚刚更新':n<3600?`${Math.floor(n/60)} 分钟前更新`:`${Math.floor(n/3600)} 小时前更新`;
  }
  function reset(ts) {
    if (!Number.isFinite(ts)) return '时间未知';
    const sec=Math.max(0,Math.ceil(ts-now())); if (!sec) return '到点待核验';
    const mins=Math.ceil(sec/60), h=Math.floor(mins/60), m=mins%60;
    return h>=24?`${Math.floor(h/24)}天${h%24}时${String(m).padStart(2,'0')}分`:`${h}时${String(m).padStart(2,'0')}分`;
  }
  const dt=ts=>ts?new Date(ts*1000).toLocaleDateString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit'}):'未提供';
  const recordedDate=value=>typeof value==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(value)?value.replaceAll('-','/'):null;
  const dateTime=ts=>new Date(ts*1000).toLocaleString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
  function failure(a) {
    const code=a?.error_code;
    if(code==='query_policy_unavailable')return {title:'查询保护暂不可用',detail:'检查目录权限后，点击恢复查询',action:'retry-query',label:'恢复查询'};
    if(code==='reauth_required'||code===401)return {title:'登录需要恢复',detail:'重新登录后更新额度',action:'reauth',label:'重新登录'};
    if(code===403)return {title:'查询已暂停',detail:'服务拒绝访问；确认权限恢复后再试',action:'retry-query',label:'恢复查询'};
    if(a?.retry_at>now())return {title:code===429?'请求过频，已暂停':'连接异常，稍后再试',detail:`下次查询：${dateTime(a.retry_at)}`};
    if(code===-32603||code==='-32603')return {title:'查询暂未完成',detail:'查询服务暂时不可用',action:'refresh-one',label:'重试'};
    if(code===-32601||code==='-32601')return {title:'暂不支持额度查询',detail:'请检查桌面端版本'};
    if(code==='timeout')return {title:'查询超时',detail:'请稍后重试',action:'refresh-one',label:'重试'};
    if(code==='missing_snapshot')return {title:'登录快照缺失',detail:'重新登录以恢复凭据',action:'reauth',label:'重新登录'};
    return {title:'额度暂不可用',detail:a?.err||'请稍后重试',action:'refresh-one',label:'重试'};
  }
  function bars(a,retry=false) {
    if (!displayWindows(a).length) {
      const state=failure(a);
      return `<div class="quota-failure quota-slot" role="group" aria-label="${esc(state.title)}">${icon('info')}<span class="quota-failure-copy"><strong>${esc(state.title)}</strong><small title="${esc(state.detail)}">${esc(state.detail)}</small></span>${retry&&state.action?`<button class="btn secondary" data-action="${state.action}" data-email="${esc(a.email)}" ${disabled()}>${esc(state.label)}</button>`:''}</div>`;
    }
    const duo=displayWindows(a).length>1;
    return `<div class="quota-bars quota-slot ${duo?'duo':''}">${displayWindows(a).slice(0,2).map(w=>`<div class="${100-w.used<=10?'low':''}"><div class="quota-bar-head"><span class="quota-label">${esc(w.label)}剩余 <span class="reset mono" data-reset="${w.resets_at}">${reset(w.resets_at)}</span></span><b class="mono">${remaining(w)}%</b></div><div class="track"><span style="width:${remaining(w)}%"></span></div></div>`).join('')}</div>`;
  }
  const identity=accountIdentity;
  function accountCard(a, detail=false, note='') {
    const top=detail
      ? `<div class="current-identity detail-profile">${identity(a,note)}${tool('refresh','refresh-one','刷新此账号额度',`data-email="${esc(a.email)}" ${disabled()}`)}</div>`
      : `<button class="current-identity" data-action="detail" data-email="${esc(a.email)}">${identity(a,note)}${icon('chevron')}</button>`;
    return `<section class="card current-card${detail?' detail-overview':''}">${top}${bars(a,detail)}</section>`;
  }
  function header() {
    return `<header class="header"><div class="brand pywebview-drag-region">${brandMark()}ChatGPTnx${config.demo?'<span class="demo-tag">演示</span>':''}</div>${tool('chart','usage-all','个人用量：总览与分账号')}${tool('settings','settings','设置')}</header>`;
  }
  function relayButton(a=relay()) {
    if (!data.accounts.length) return '';
    if (data.chatgpt_running === false) return `<button class="relay" data-action="launch-chatgpt" ${busy()||data.adding?'disabled':''} aria-label="启动 ChatGPT 桌面端"><span><strong class="relay-label">${icon('baton')}启动 ChatGPT</strong><small>桌面端未运行</small></span><span class="relay-arrow">${icon('arrow')}</span></button>`;
    if (!a) return `<button class="relay" data-action="refresh" ${disabled()}><span><strong class="relay-label">${icon('baton')}等待可用接力账号</strong><small>等待额度恢复 · 点击刷新</small></span>${icon('refresh')}</button>`;
    return `<button class="relay" data-action="relay" ${busy()||data.adding?'disabled':''} aria-label="下一棒，切换到${esc(name(a))}"><span><strong class="relay-label">${icon('baton')}下一棒 · ${esc(name(a))}</strong><small>${esc(plan(a.plan))} · ${displayWindows(a).map(w=>`${esc(w.label)} 剩 ${remaining(w)}%`).join('　')}${fresh(a)?'':' · 缓存'}</small></span><span class="relay-arrow">${icon('arrow')}</span></button>`;
  }
  function accountRow(a) {
    return `<button class="row" data-action="detail" data-email="${esc(a.email)}">${avatar(a)}<span class="meta"><strong class="account-name" title="${esc(name(a))}">${esc(name(a))}</strong><small>${esc(plan(a.plan))}${a.ok&&!fresh(a)?' · 缓存':''}</small></span>${quotaColumns(a)}</button>`;
  }
  function footer() {
    const refreshing=data.operation?.kind==='refresh';
    return `<footer class="footer slim"><button class="refresh-status" data-action="refresh" aria-label="刷新全部额度" ${disabled()}>${icon('refresh',refreshing?'spinner':'')}<span>${refreshing?esc(data.operation.phase):age(data.updated)}</span></button><button class="btn compact add" data-action="add" ${disabled()}>${icon('plus')}添加账号</button></footer>`;
  }
  const quotaValue=(a,minutes)=>remainingFor(a,minutes) ?? -1;
  const resetValue=(a,minutes)=>a.windows?.find(w=>duration(w)===minutes)?.resets_at ?? Number.MAX_SAFE_INTEGER;
  const quotaOverviewContent=()=>window.NXViews.accounts(viewContext());
  function resumeNotice() {
    const r=data.resume;if(!r)return '';
    const active=['switching','resuming'].includes(r.phase),waiting=r.phase==='waiting_account';
    const text=waiting?`等待可用接力账号 ${r.done}/${r.total}`:active?`任务接续中 ${r.done}/${r.total}`:r.failed?`任务接续失败 ${r.failed}/${r.total}`:`任务接续完成 ${r.done}/${r.total}`;
    return statusBar({text,tone:waiting?'neutral':active?'progress':r.failed?'error':'success',symbol:waiting?'clock':'',action:'resume-details',className:'resume-notice'});
  }
  function notice() {
    if(bridgeError)return statusBar({text:'本地连接中断 · 点击重新连接',tone:'warning',action:'refresh-state'});
    if(data.reauth)return statusBar({text:'等待完成重新登录',action:'reauth',symbol:'user',attrs:`data-email="${esc(data.reauth.email)}"`});
    if(data.adding)return statusBar({text:'正在添加账号，返回完成',action:'add',symbol:'user'});
    if(data.operation&&data.operation.kind!=='refresh')return statusBar({text:data.operation.phase,tone:'progress'});
    if(data.monitor_health?.state==='degraded')return statusBar({text:'任务监控暂不可用 · 正在延迟重试',tone:'warning',action:'diagnostics'});
    if(data.resume)return resumeNotice();
    if(data.last_error)return statusBar({text:data.last_error.message||'上次操作未完成',tone:'error'});
    if(data.relay_wait&&!(ui.page==='detail'&&ui.email===data.relay_wait.email)){
      const waiting=data.accounts.find(a=>a.email===data.relay_wait.email);
      if(waiting)return statusBar({text:`${name(waiting)} · 等待额度恢复后接力`,action:'detail',symbol:'clock',attrs:`data-email="${esc(waiting.email)}"`});
    }
    const c=current();
    if(!data.settings.auto_relay&&valid(c)&&c.windows.some(w=>w.used>=100))
      return statusBar({text:'额度已耗尽 · 自动接力未开启',action:'settings',symbol:'info'});
    return '';
  }
  const resumeContent=()=>window.NXViews.resume(viewContext());
  async function api(method,...args) {
    if (config.demo) return window.NXDemo.call(method,...args);
    const bridge=window.pywebview?.api;
    if (typeof bridge?.[method]!=='function') throw new Error('本地接口尚未就绪或版本不匹配');
    return await bridge[method](...args);
  }
  function setSize(view) {
    const size=config.sizes[view] || config.sizes.home;
    if (config.demo) {
      app.style.width=Math.min(size[0], Math.max(280, window.innerWidth-16))+'px';
      app.style.height=size[1]+'px';
    } else api('resize_panel',view).catch(()=>{});
  }
  function notify(message,{tone='neutral',duration=5000}={}) {
    clearTimeout(notificationTimer);
    notification={text:String(message||'操作未完成'),tone};
    $('#announcer').textContent=notification.text;paintNotifications();
    notificationTimer=setTimeout(clearNotification,duration);
  }
  function formError(message) {
    const label=$('#form-error');if(label)label.textContent=message;
    $('#announcer').textContent=message;
  }
  function fieldError(field,message) {
    const input=$(field),label=$('#form-error');if(!input||!label)return false;
    label.textContent=message;input.setAttribute('aria-invalid','true');input.setAttribute('aria-describedby','form-error');
    input.focus({preventScroll:true});return true;
  }
  function renderHome() {
    const position=captureScroll(home),key=focusKey(document.activeElement);
    if (!connected) {
      home.innerHTML=header()+statusRegion()+`<div class="empty"><h3>连接本地应用</h3><p class="note">${esc(bridgeError||'正在连接桌面服务…')}</p><button class="btn secondary" data-action="refresh-state">重新连接</button></div>`;
      feedback.paint();if(!ui.page)paintNotifications();return;
    }
    const wasOnboarding=home.classList.contains('is-onboarding');
    const onboarding=!data.accounts.length&&!data.adding;
    home.classList.toggle('is-onboarding',onboarding);
    home.innerHTML=onboarding?window.NXViews.onboarding({...viewContext(),busy:busy()}):homeContent();
    if(onboarding||wasOnboarding)setSize('home');
    if(!ui.page)paintNotifications();restoreScroll(home,position);restoreFocus(home,key);feedback.paint();
  }
  function render() {
    const focused=document.activeElement, key=focusKey(focused);
    renderHome();
    if(ui.page) renderSheet();
    if(key&&!focused?.isConnected) restoreFocus(ui.page?sheet:home,key);
    feedback.paint();paintNotifications();
  }
  function pageHead(title,actions='') {
    return `<header class="sheet-head">${tool('back','back','返回')}<h2 id="sheet-title" tabindex="-1">${esc(title)}</h2>${actions}${config.demo?'<span class="demo-tag">演示</span>':''}</header>`;
  }
  function show(page, target=null, push=true, saved=null) {
    const aliases={automation:null,notifications:'notifications','relay-accounts':'relay',hotkeys:'hotkeys',archives:'archives','resume-message':'message'};
    const initial=page;
    if(Object.hasOwn(aliases,page))page='settings';
    if(page==='edit')page='detail';
    if(page==='settings'){ui.disclosures.clear();ui.fullCollections.clear();}
    if(page==='detail'){ui.disclosures.clear();ui.resetExpanded.clear();}
    if(page==='resume'){ui.resumeExpanded.clear();ui.resumeCollapsed.clear();}
    if(Object.hasOwn(aliases,initial)&&aliases[initial])selectSettingDisclosure(aliases[initial]);
    if(initial==='edit')ui.disclosures.add('meta:'+target);
    feedback.clear();clearNotification();
    if (!ui.page) {previousFocus=document.activeElement;previousFocusKey=focusKey(previousFocus);}
    if (push && ui.page) ui.history.push({page:ui.page,email:ui.email,scope:ui.scope,
      scroll:captureScroll(sheet),focus:focusKey(document.activeElement)});
    navigation.invalidate();ui.recording=null;
    ui.page=page;ui.email=target;
    home.inert=true;sheet.hidden=false;
    setSize('workspace');renderSheet(false);
    if(saved){restoreScroll(sheet,saved.scroll);restoreFocus(sheet,saved.focus);}
    if(!saved?.focus) $('#sheet-title')?.focus({preventScroll:true});
  }
  function closeSheet() {
    feedback.clear();clearNotification();navigation.invalidate();ui.recording=null;
    ui.page=null;ui.email=null;ui.history=[];sheet.hidden=true;home.inert=false;
    setSize('home');renderHome();
    restoreFocus(home,previousFocusKey);
    if(!home.contains(document.activeElement))home.querySelector('button')?.focus({preventScroll:true});
  }
  function back() {
    const saved=ui.history.pop();if(!saved){closeSheet();return;}
    ui.scope=saved.scope;show(saved.page,saved.email,false,saved);
  }
  const link=(i,label,action,attrs='')=>`<button class="link-row" data-action="${action}" ${attrs}>${i?icon(i):''}<span>${esc(label)}</span>${icon('chevron')}</button>`;
  const settingsGroup=(label,...groups)=>`<section class="settings-section"><h3 class="settings-heading">${esc(label)}</h3>${groups.map(content=>`<div class="settings-list">${content}</div>`).join('')}</section>`;
  const detail=(label,value,hint='')=>`<div class="detail-line"><span>${esc(label)}</span><span class="right"><strong>${esc(value)}</strong>${hint?`<small>${esc(hint)}</small>`:''}</span></div>`;
  function resetCredits(a) {
    const bank=a.ok?a.banked_resets:null;
    const count=Number.isSafeInteger(bank?.available_count)&&bank.available_count>=0?bank.available_count:null;
    const expanded=ui.resetExpanded.has(a.email);
    const items=Array.isArray(bank?.items)?bank.items:[];
    let content='';
    if(count===null) content='<div class="inline-empty">暂未读到重置次数。</div>';
    else if(count===0) content='<div class="inline-empty">暂无可用的额度重置次数。</div>';
    else if(!items.length) content='<div class="inline-empty">到期时间暂未提供。</div>';
    else {
      content=items.map((item,index)=>{
        const expiry=!item.expires_known?'未提供':item.expires_at===null?'无到期时间':dateTime(item.expires_at);
        const status=item.status==='redeeming'?' · 使用中':item.status==='redeemed'?' · 已使用':'';
        return `<div class="reset-credit"><span>第 ${index+1} 次${status}</span><strong>${esc(expiry)}${item.expires_known&&item.expires_at!==null?' 到期':''}</strong></div>`;
      }).join('');
      if(count>items.length) content+=`<p>另有 ${count-items.length} 次未提供逐项详情。</p>`;
    }
    if(a.query_warning?.scope==='reset_credits'&&a.query_warning.paused) content+=`<p>重置详情查询已暂停，主额度查询正常。</p><button class="btn secondary" data-action="retry-query" data-email="${esc(a.email)}">恢复详情查询</button>`;
    return `<div class="detail-reset"><button class="detail-line detail-action reset-summary" data-action="toggle-reset-credits" data-email="${esc(a.email)}" aria-expanded="${expanded}"><span>重置次数</span><span class="right"><strong>${count===null?'暂不可用':`${count} 次`}</strong>${icon('chevron')}</span></button>${expanded?`<div class="reset-credit-details">${content}</div>`:''}</div>`;
  }
  function scopeUsage() {
    if (!ui.usage) return null;
    if(ui.scope==='all')return ui.usage;
    const r=ui.usage.rows.find(r=>r.email===ui.scope), a=data.accounts.find(a=>a.email===ui.scope)||r;
    return a?math.aggregate([a],{[a.email]:r?.usage},ui.days):null;
  }
  function metric(label,value) { return `<div class="metric"><small>${esc(label)}</small><strong class="mono">${esc(value)}</strong></div>`; }
  const metricsRow=items=>`<div class="metrics-row">${items.map(([l,v])=>metric(l,v)).join('')}</div>`;
  const durText=s=>{if(s==null)return '—';const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);return d?`${d}天${h}小时`:h?`${h}小时${m}分`:`${m}分钟`;};
  const short=math.compactText;
  const statuses={ready:'已计入',pending:'尚未读取',unavailable:'查询失败',missing_total:'未提供累计',duplicate:'重复身份 · 未重复计入',identity_changed:'身份已变 · 请重查'};
  const usageContent=()=>window.NXViews.usage(viewContext());
  function viewContext(){
    return {data,ui,config,esc,icon,tool,name,plan,now,duration,reset,quotaValue,resetValue,
      remaining,segmented,disabled,scopeUsage,math,metricsRow,short,durText,statuses,
      link,settingsGroup,systemSettings,autoRelaySetting,taskContinuationSetting,
      notificationSettings,quotaSummary,accountChoice,statusBar,statusRegion,hotkeyLabel,dt,resumeContent,
      accountCard,accountRow,header,footer,notice,relayButton,current,relay,age,creditValue,brandMark,avatar,accountIdentity};
  }
  let composingField=null, deferredSheet=false;
  function renderSheet(preserve=true) {
    if(preserve&&composingField?.isConnected&&sheet.contains(composingField)){deferredSheet=true;return;}
    const position=preserve?captureScroll(sheet):null;
    const key=preserve?focusKey(document.activeElement):null;
    const a=data.accounts.find(a=>a.email===ui.email), attr=`data-email="${esc(a?.email||'')}"`;
    let title='',body='',foot='',cls='',headActions='',footClass='';
    switch(ui.page){
      case 'usage':
        title='个人用量';body=usageContent();cls='usage-body';foot='';break;
      case 'quota-overview':
        title='额度总览';body=quotaOverviewContent();cls='quota-overview-body';break;
      case 'detail': {
        if(!a){closeSheet();return;}
        title='账号详情';const m=a.membership||{},isCurrent=a.email===data.current;
        const manualDate=recordedDate(a.manual_subscription_date);
        const expiryNote=manualDate?`${manualDate} 到期`:m.date?`${dt(m.date)} 到期`:'未录入到期时间';
        const waiting=data.relay_wait?.email===a.email,picked=data.settings.relay_pick===a.email;
        const exhausted=a.ok&&a.windows?.some(w=>Number.isFinite(w.used)&&w.used>=100);
        const pickLabel=waiting?'取消等待':picked?'取消下一棒':exhausted?'恢复后接力':'设为下一棒';
        const pickIcon=waiting||picked?'close':exhausted?'clock':'baton';
        const actionArea=isCurrent?
          `<div class="detail-actions is-current"><button class="btn primary current-status" data-action="home" aria-label="当前使用，返回首页">${icon('check')}当前使用</button></div>`:
          `<div class="detail-actions"><button class="btn primary" data-action="pick" ${attr} ${!waiting&&!picked&&(busy()||data.adding||data.reauth)?'disabled':''} aria-pressed="${waiting||picked}" title="${exhausted&&!waiting?'额度恢复并核验后自动接力':pickLabel}">${icon(pickIcon)}${pickLabel}</button><button class="btn secondary" data-action="switch" ${attr} ${busy()||data.adding?'disabled':''}>切换到此账号 ${icon('arrow')}</button></div>`;
        const archive=isCurrent?`<button class="danger-row unavailable" disabled title="切换到其他账号后可归档">${icon('archive')}归档账号</button>`:`<button class="danger-row" data-action="remove" ${attr}>${icon('archive')}归档账号</button>`;
        body=`${accountCard(a,true,isCurrent?'当前账号':'')}${actionArea}${link('chart','个人用量','usage-account',attr)}<div class="detail-compact">${window.NXEditors.account(viewContext(),a)}${resetCredits(a)}${detail('Credits',creditValue(a))}</div>`;
        cls=`detail-body ${isCurrent?'is-current':''} has-credits`;foot=`<div class="detail-bottom">${archive}<div class="detail-expiry-note">${esc(expiryNote)}</div></div>`;footClass='detail-footer';break;}
      case 'confirm': {
        const quota=quotaSummary(a);
        title=ui.switchKind==='relay'?'账号接力':'切换账号';body=`<div class="confirm-mark">${icon('baton')}</div><h3 class="confirm-title">${ui.switchKind==='relay'?'下一棒，交给':'切换到'}<br>${esc(name(a))}</h3><p class="note">将重启 ChatGPT 桌面端。</p><button class="confirm-account" data-action="detail" ${attr} aria-label="查看 ${esc(name(a))} 的账号详情">${avatar(a)}<span class="confirm-account-copy"><span class="identity-title"><strong title="${esc(name(a))}">${esc(name(a))}</strong><span class="badge">${esc(plan(a?.plan))}</span></span><span class="confirm-account-quota">${quota}</span></span><span class="confirm-account-more">详情 ${icon('chevron')}</span></button>${data.operation?statusRegion(statusBar({text:data.operation.phase,tone:'progress',className:'operation-notice'})):''}`;
        foot=`<button class="btn secondary" data-action="back" ${data.switching?'disabled':''}>返回</button><button class="btn primary" data-action="execute-switch" ${attr} ${disabled()}>${ui.switchKind==='relay'?'开始接力':'确认切换'} ${icon('arrow')}</button>`;break;
      }
      case 'settings':
        ({title,body,cls}=window.NXViews.settings(viewContext()));break;
      case 'diagnostics':
        title='诊断摘要';cls='diagnostics-body';
        body=`<p class="note">仅含版本、错误类别和匿名账号序号。先检查内容，再决定是否分享。</p><textarea class="diagnostics-preview" aria-label="脱敏诊断摘要" readonly spellcheck="false">${esc(ui.diagnostics||'正在读取…')}</textarea>`;
        foot='<button class="btn secondary" data-action="diagnostics-refresh">重新读取</button><button class="btn primary" data-action="copy-diagnostics">复制摘要</button>';break;
      case 'purchase':
        ({title,body,cls}=window.NXViews.purchase(viewContext()));break;
      case 'resume':
        title='任务接续';body=resumeContent();cls='resume-body';headActions=tool('archive','resume-clear','清理已结束记录',ui.resumeDetails.some(s=>!['switching','resuming','waiting_account'].includes(s.phase))?'':'disabled');break;
      case 'resume-clear':
        title='清理记录';body='<h3 class="confirm-title">清理已结束的接续记录？</h3><p class="note">保留进行中的接续；不会删除桌面端任务。</p>';foot='<button class="btn secondary" data-action="back">取消</button><button class="btn primary" data-action="execute-resume-clear">清理记录</button>';break;
      case 'remove':
        title='归档账号';body=`<div class="confirm-mark">${icon('archive')}</div><h3 class="confirm-title">收起 ${esc(name(a))}？</h3><p class="note">凭据归档保留，可以恢复；该账号的快捷键分配也会保留。</p>`;foot=`<button class="btn secondary" data-action="back">保留</button><button class="btn primary" data-action="execute-remove" ${attr} ${disabled()}>确认归档</button>`;break;
      case 'add':
        title='添加账号';{
          const status=data.add_login_status,ready=status==='ready';
          const heading=!data.adding?'添加新的账号':ready?'新账号已就绪':'等待新账号登录';
          const copy=!data.adding?'将重启桌面端，打开登录窗口。':ready?'确认后加入账号清单。':'取消会恢复添加前的账号。';
          const state=data.operation?data.operation.phase:ready?'账号凭据已准备完成':status==='unchanged'?'仍是添加前的账号，请登录新账号':status==='existing'?'这个账号已经在清单里':status==='waiting'?'等待登录新账号':'等待打开登录窗口';
          const steps=`<ol class="add-progress"><li class="${ready?'done':'current'}">在 ChatGPT 桌面端登录新账号</li><li class="${ready?'current':''}">${ready?'确认保存这个账号':'登录完成后，回到这里确认保存'}</li></ol>`;
          body=`<div class="confirm-mark">${icon(ready?'check':'plus')}</div><h3 class="confirm-title">${heading}</h3><p class="note">${copy}</p>${steps}${statusRegion(statusBar({text:state,tone:data.operation?'progress':ready?'success':'neutral',symbol:ready?'check':'clock',className:'flow-status'}))}`;
          foot=data.adding?`<button class="btn secondary" data-action="cancel-add" ${disabled()}>取消并恢复</button><button class="btn primary" data-action="finish-add" ${disabled()||!ready?'disabled':''}>确认保存</button>`:`<button class="btn secondary" data-action="back">返回</button><button class="btn primary" data-action="start-add" ${disabled()}>打开登录窗口</button>`;break;
        }
      case 'reauth': {
        if(!a){closeSheet();return;}
        title='重新登录';const pending=data.reauth?.email===a.email,started=pending&&data.reauth.phase!=='ready';
        body=`<div class="confirm-mark">${icon('user')}</div><h3 class="confirm-title">重新登录<br>${esc(name(a))}。</h3><p class="note">${started?'请在 ChatGPT 中完成“继续登录”或网页登录，然后回来验证。':'会重启桌面端，暂时退出当前账号。'}</p>${statusRegion(statusBar({text:data.operation?data.operation.phase:started?'登录完成后，点击“验证并保存”。':'取消可恢复原账号。',tone:data.operation?'progress':'neutral',className:'flow-status'}))}`;
        foot=started?`<button class="btn secondary" data-action="cancel-reauth" ${disabled()}>取消并恢复</button><button class="btn primary" data-action="finish-reauth" ${disabled()}>验证并保存</button>`:`<button class="btn secondary" data-action="${pending?'cancel-reauth':'back'}">返回</button><button class="btn primary" data-action="start-reauth" ${attr} ${disabled()}>打开登录窗口</button>`;break;}
      case 'scenarios':
        title='演示场景';body=`<div class="menu-list">${[['default','正常 · 含 1 个失败账号'],['detail-dense','详情含双额度与 Credits'],['banked-partial','重置次数有部分详情'],['banked-unknown','重置次数未提供'],['resume-progress','任务接续中'],['resume-waiting','等待可用接力账号'],['resume-failed','任务接续失败'],['reauth','账号需要重新登录'],['chatgpt-off','ChatGPT 桌面端未运行'],['complete','所有账号用量可读'],['usage-empty','所有用量均未提供'],['stale','额度缓存过期'],['expired','窗口到点待核验'],['fail-switch','下一次接力失败'],['many','14 个账号'],['empty','空账号清单'],['member-none','会员日期未提供']].map(([key,label])=>`<button class="btn secondary" data-action="scenario" data-value="${key}">${label}</button>`).join('')}</div>`;break;
      case 'error':
        closeSheet();return;
      default:closeSheet();return;
    }
    sheet.dataset.page=ui.page;
    const oldError=preserve?sheet.querySelector('#form-error')?.textContent:'';
    const oldFields=[...sheet.querySelectorAll('.field')].map(n=>({node:n,id:n.id,value:n.value,invalid:n.getAttribute('aria-invalid'),focused:n===document.activeElement,start:n.selectionStart,end:n.selectionEnd}));
    sheet.innerHTML=pageHead(title,headActions)+`<div class="sheet-body ${cls}">${statusRegion()}${body}</div>`+(foot?`<footer class="sheet-foot ${footClass}">${foot}</footer>`:'');
    if(preserve)for(const saved of oldFields){const node=document.getElementById(saved.id);if(node&&sheet.contains(node)){node.replaceWith(saved.node);const live=saved.node;live.value=saved.value;if(saved.invalid)live.setAttribute('aria-invalid',saved.invalid);if(saved.focused){live.focus({preventScroll:true});try{live.setSelectionRange(saved.start,saved.end);}catch{}}}}
    if(oldError&&sheet.querySelector('#form-error'))sheet.querySelector('#form-error').textContent=oldError;
    paintNotifications();restoreScroll(sheet,position);restoreFocus(sheet,key);feedback.paint();
  }
  const inlineWrites=new Map();
  async function saveInline(source,{id,key,method,args,value,commit,clear}) {
    if(inlineWrites.has(key))return;
    const ticket=navigation.ticket(),revision=ui.fieldRevisions.get(key)||0;
    const error=$('#form-error');if(error)error.textContent='';
    const write={};inlineWrites.set(key,write);const token=feedback.begin(source,'正在保存…');
    try {
      const result=await api(method,...args);
      if(!result||result.ok!==true)throw new Error(result?.error||'保存未完成，请重试');
      commit(result);
      if(inlineWrites.get(key)===write)inlineWrites.delete(key);
      const unchanged=(ui.fieldRevisions.get(key)||0)===revision;
      if(unchanged)clear();
      if(navigation.current(ticket)){
        if(unchanged){const field=$('#'+id);if(field)field.value=value;}
        render();
        feedback.finish(token,{text:unchanged?'已保存':'先前内容已保存，当前修改尚未保存'});
      }else feedback.finish(token);
      // Refresh is observation after a committed write, never a second save.
      await poll(true);
    } catch(error) {
      feedback.finish(token);
      if(navigation.current(ticket))formError(error.message||'保存未完成，输入已保留');
    } finally {if(inlineWrites.get(key)===write)inlineWrites.delete(key);}
  }
  async function saveAccountField(source,email,field) {
    const id=field==='alias'?'alias':'manual-date',node=$('#'+id);
    if(!node)return;
    const value=field==='alias'?node.value.trim():node.value;
    if(field==='alias'&&([...value].length>24||/\p{C}/u.test(value))){fieldError('#'+id,'昵称最多 24 个可显示字符');return;}
    if(field==='subscription_date'&&!node.validity.valid){fieldError('#'+id,'请输入有效的到期日期');return;}
    await saveInline(source,{id,key:email+':'+id,method:'update_account_meta',args:[email,{[field]:value|| (field==='alias'?'':null)}],value,
      commit:result=>{const a=data.accounts.find(a=>a.email===email);if(a){if(field==='alias')a.alias=result.meta.alias;else a.manual_subscription_date=result.meta.subscription_date;}},
      clear:()=>{const draft=ui.metaDrafts.get(email);if(draft){delete draft[field];if(!Object.keys(draft).length)ui.metaDrafts.delete(email);}}});
  }
  const actionLabels={
    retry_query:'正在恢复查询…',
    launch_chatgpt:'正在打开 ChatGPT…',refresh:'正在刷新…',refresh_one:'正在刷新…',
    set_preferences:'正在保存…',set_account_meta:'正在保存…',set_auto_relay_account:'正在保存…',
    set_relay_pick:'正在设置…',set_account_hotkey:'正在保存…',adopt_current:'正在保存…',
    add_start:'正在打开…',add_finish:'正在保存…',add_cancel:'正在恢复…',
    reauth_start:'正在打开…',reauth_finish:'正在验证…',reauth_cancel:'正在恢复…',
    switch:'正在切换…',relay:'正在接力…',remove:'正在归档…',restore:'正在恢复…',
    clear_resume_history:'正在清理…',open_resume_task:'正在定位…',retry_resume_task:'正在排队…',copy_text:'正在复制…'
  };
  const actionResults={launch_chatgpt:'已请求打开',set_preferences:'已保存',set_auto_relay_account:'已保存',set_relay_pick:'已设置',copy_text:'已复制'};
  async function actionFrom(source,method,...args) {
    if(acting)return null;
    const ticket=navigation.ticket();
    if(['set_preferences','set_account_meta'].includes(method)){const error=$('#form-error');if(error)error.textContent='';}
    acting=true;
    const dockAction=new Set(['launch_chatgpt','adopt_current','add_start','add_finish','add_cancel','reauth_start','reauth_finish','reauth_cancel','switch','relay','remove','restore','open_resume_task']);
    const usesDock=dockAction.has(method),operation={text:actionLabels[method]||'处理中…',ticket};
    if(usesDock)controlOperation=operation;
    const token=usesDock?null:feedback.begin(source,actionLabels[method]||'处理中…');render();
    try {
      const result=await api(method,...args);
      if(result?.ok===false)throw new Error(result.error||result.err||'操作未被接受');
      await poll(true);
      feedback.finish(token,{text:method==='set_relay_pick'?result?.message||actionResults[method]:actionResults[method]||''});
      return result;
    } catch(error) {
      feedback.finish(token);
      if(navigation.current(ticket)) {
        if($('#form-error')&&['set_account_meta','set_preferences'].includes(method))formError(error.message||'保存失败，请重试');
        else notify(error.message||'本地操作失败',{tone:'error'});
      }
      return null;
    } finally {if(controlOperation===operation)controlOperation=null;acting=false;render();}
  }
  const action=(method,...args)=>actionFrom(null,method,...args);
  async function performPoll() {
    try{
      const settingsTicket=preferences.readTicket();
      const value=await api('get_data');if(!value||!Array.isArray(value.accounts))throw new Error('状态格式不正确');
      const previousAddStatus=data.add_login_status,revealAdd=workflowResume,recovered=!!bridgeError;
      const prev=JSON.stringify(data);data={...value,settings:{...defaults,...value.settings}};preferences.reconcile(data,settingsTicket);connected=true;bridgeError='';workflowResume=false;
      applyAppearance(data.settings.appearance);
      let extraChanged=false;
      const ticket=navigation.ticket(),period=ui.days;
      const usageRevision=Number(value.usage_revision||0);
      if(ui.page?.startsWith('usage') && (ui.usage==null || usageRevision!==ui.usageRevision)) {
        const usage=await api('read_usage_all',ui.days);
        const signature=v=>JSON.stringify(v ? {...v,generated_at:0} : v);
        if(navigation.current(ticket)&&ui.page==='usage'&&ui.days===period){extraChanged=signature(usage)!==signature(ui.usage);ui.usage=usage;ui.usageRevision=usageRevision;}
      }
      if(ui.page==='settings'&&ui.disclosures.has('archives')&&ui.inlineLoading.archives==='ready') {
        const archives=await api('get_archives');
        if(navigation.current(ticket)&&(ui.page==='settings'&&ui.disclosures.has('archives')&&ui.inlineLoading.archives==='ready')){extraChanged=JSON.stringify(archives)!==JSON.stringify(ui.archives);ui.archives=archives;}
      }
      if(ui.page==='resume') {
        const details=await api('get_resume_details');
        if(navigation.current(ticket)&&(ui.page==='resume')){
        extraChanged=JSON.stringify(details)!==JSON.stringify(ui.resumeDetails)||extraChanged;
        ui.resumeDetails=details;
        const ids=new Set(details.map(s=>s.id));
        ui.resumeExpanded=new Set([...ui.resumeExpanded].filter(id=>ids.has(id)));
        ui.resumeCollapsed=new Set([...ui.resumeCollapsed].filter(id=>ids.has(id)));
        }
      }
      if(prev!==JSON.stringify(data)||extraChanged||recovered)render();
      if(navigation.current(ticket)&&data.adding&&(revealAdd||data.add_login_status==='ready'&&previousAddStatus!=='ready')&&ui.page!=='add')show('add');
      const terminal=ui.submitted&&((data.recent_results||[]).find(r=>r.id===ui.submitted)||(data.last_result?.id===ui.submitted?data.last_result:null));
      if(terminal){
        const done=terminal;ui.submitted=null;
        if(done.ok && data.current===done.target){if(navigation.current(ui.submittedEpoch))closeSheet();notify('已切换到 '+name(current()),{tone:'success'});}
        else if(!done.ok){if(data.reauth&&navigation.current(ui.submittedEpoch))show('reauth',data.reauth.email);notify(data.last_error?.message||'接力未完成',{tone:'error'});}
      }
      // Backend errors already have one persistent status entry; never echo a second toast.
    }catch(e){bridgeError=e.message;renderHome();}
    finally{schedulePoll();}
  }
  async function loadUsage() {
    const ticket=navigation.ticket(),period=ui.days;
    try {
      const result=await api('read_usage_all',period);
      if(navigation.current(ticket)&&ui.page==='usage'&&period===ui.days){ui.usage=result;ui.usageRevision=Number(data.usage_revision||0);renderSheet();}
    } catch(error){if(navigation.current(ticket))notify(error.message||'用量读取失败');}
  }
  async function openUsage(scope='all',force=false) {
    if(scope!=='all'&&!data.accounts.some(a=>a.email===scope)&&!ui.usage?.rows?.some(r=>r.email===scope&&r.archived))scope='all';
    if(ui.page!=='usage'||ui.scope!==scope){
      if(ui.page)ui.history.push({page:ui.page,email:ui.email,scope:ui.scope,scroll:captureScroll(sheet),focus:focusKey(document.activeElement)});
      ui.scope=scope;show('usage',null,false);
    }
    const ticket=navigation.ticket();
    await loadUsage();
    if(!navigation.current(ticket))return;
    if(scope!=='all'&&ui.usage?.rows?.some(r=>r.email===scope&&r.archived))return;
    // Refresh is a bridge transaction; leaving the screen never causes navigation.
    if(force) await action(scope==='all'?'get_usage_all':'get_usage',...(scope==='all'?[true]:[scope,true]));
    else {try{await api(scope==='all'?'get_usage_all':'get_usage',...(scope==='all'?[false]:[scope,false]));}catch(error){if(navigation.current(ticket))notify(error.message);}}
  }
  async function openResumeDetails() {
    show('resume');const ticket=navigation.ticket();
    try {
      const details=await api('get_resume_details');
      if(!navigation.current(ticket))return;
      ui.resumeDetails=details;
      renderSheet();
      if(data.resume?.id) await api('mark_resume_seen',data.resume.id);
      await poll(true);
    }catch(error){if(navigation.current(ticket))notify(error.message||'接续记录读取失败');}
  }
  async function loadInline(key,force=false) {
    const spec={archives:['get_archives','archives']}[key];
    const ticket=navigation.ticket(),previous=ui.inlineRequests[key];
    if(!spec||!force&&ui.inlineLoading[key]==='ready'||!force&&ui.inlineLoading[key]==='loading'&&previous?.ticket===ticket)return;
    const request={ticket};ui.inlineRequests[key]=request;ui.inlineLoading[key]='loading';renderSheet();
    try {
      const value=await api(spec[0]);
      if(ui.inlineRequests[key]!==request)return;
      if(!navigation.current(ticket)){ui.inlineLoading[key]='idle';return;}
      ui[spec[1]]=value;ui.inlineLoading[key]='ready';renderSheet();
    }catch(error){
      if(ui.inlineRequests[key]!==request)return;
      ui.inlineLoading[key]=navigation.current(ticket)?'error':'idle';
      if(navigation.current(ticket))renderSheet();
    }
  }
  const settingDisclosureKeys=new Set(['appearance','notifications','relay','early-anchor','message','hotkeys','archives']);
  function selectSettingDisclosure(key) {
    for(const k of settingDisclosureKeys)if(k!==key)ui.disclosures.delete(k);
    ui.disclosures.add(key);
    for(const node of sheet.querySelectorAll('.settings-body details[data-disclosure]')) {
      if(node.dataset.disclosure!==key)node.open=false;
    }
    if(key!=='hotkeys')ui.recording=null;
  }
  function syncDisclosure(d) {
    const key=d.dataset?.disclosure;if(!key||!d.isConnected||!sheet.contains(d))return;
    if(d.open){
      if(ui.page==='settings'&&settingDisclosureKeys.has(key))selectSettingDisclosure(key);
      else {ui.disclosures.add(key);if(ui.page==='detail'&&key.startsWith('meta:')&&ui.resetExpanded.size){ui.resetExpanded.clear();renderSheet();}}
      if(ui.inlineLoading[key]!=='error')loadInline(key);
    }else {
      ui.disclosures.delete(key);
      if(key==='hotkeys')ui.recording=null;
    }
    statusDock.refresh();
  }
  // Native toggle events are queued. Record clicks synchronously so a fast
  // save or refresh cannot rebuild an accordion using its previous state.
  app.addEventListener('toggle',event=>syncDisclosure(event.target),true);
  async function requestSwitch(target, kind='manual') {
    if(!target||target===data.current||busy()||data.adding)return;
    ui.switchKind=kind;
    show('confirm',target);
  }
  async function executeSwitch(target,source=null) {
    if(ui.page!=='confirm')show('confirm',target);
    ui.submittedEpoch=navigation.ticket();
    const r=await actionFrom(source,ui.switchKind==='relay'?'relay':'switch',target);
    if(r?.already_current){closeSheet();return;}
    if(r?.operation_id){ui.submitted=r.operation_id;await poll();}
  }
  app.addEventListener('click',async e=>{
    const summary=e.target.closest('details[data-disclosure] > summary');
    if(summary){
      e.preventDefault();const d=summary.parentElement,opening=!d.open;
      if(opening&&ui.page==='settings')selectSettingDisclosure(d.dataset.disclosure);
      d.open=opening;syncDisclosure(d);
      // Collapsing a preceding section may move the new heading above the
      // viewport. Reveal the heading only; never reset the whole page scroll.
      if(opening&&d.isConnected){const body=d.closest('.sheet-body'),r=summary.getBoundingClientRect(),v=body?.getBoundingClientRect();if(v&&r.top<v.top)body.scrollTop-=v.top-r.top;}
      return;
    }
    const b=e.target.closest('[data-action]');if(!b||b.disabled)return;
    if(b.dataset.rootNav==='true'&&ui.page)closeSheet();
    const target=b.dataset.email,val=b.dataset.value;
    const ticket=navigation.ticket(),run=(method,...args)=>actionFrom(b,method,...args);
    try { switch(b.dataset.action){
      case 'refresh-state':{const token=feedback.begin(b,'正在检测…');await poll(true);feedback.finish(token,{text:bridgeError?'':'已重新检测'});break;}
      case 'refresh':if(data.accounts.length)await run('refresh');else show('add');break;
      case 'refresh-one':await run('refresh_one',target);break;
      case 'retry-query':await run('retry_query',target);break;
      case 'diagnostics':
      case 'diagnostics-refresh':{
        if(ui.page!=='diagnostics')show('diagnostics');
        const epoch=navigation.ticket();
        const result=await api('get_diagnostics');
        if(navigation.current(epoch)){ui.diagnostics=result?.text||'诊断摘要暂不可用';renderSheet(false);}
        break;
      }
      case 'copy-diagnostics':{
        const field=$('.diagnostics-preview');if(!field||!ui.diagnostics)break;
        field.focus({preventScroll:true});field.select();
        let copied=false;
        try {if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(field.value);copied=true;}}catch{}
        if(!copied){try {copied=document.execCommand('copy');}catch{}}
        notify(copied?'诊断摘要已复制':'请选中摘要手动复制',{tone:copied?'success':'error'});break;
      }
      case 'reauth':show('reauth',target);break;
      case 'hide':if(config.demo){app.style.opacity='.35';notify('演示：窗口已隐藏，点击任意位置恢复');app.onclick=()=>{app.style.opacity='1';app.onclick=null;};}else await api('hide');break;
      case 'dismiss-status':
        dismissedStatus=activeStatusKey;paintNotifications();
        if(data.resume&&!['switching','resuming','waiting_account'].includes(data.resume.phase)){
          try{await api('mark_resume_seen',data.resume.id);await poll(true);}
          catch(error){notify(error.message||'提示收起未保存，请稍后重试');}
        }
        break;
      case 'dismiss-feedback':clearNotification();break;
      case 'feedback-details':{clearNotification();break;}
      case 'settings':show('settings');break;
      case 'purchase-account':show('purchase');break;
      case 'copy-purchase-qq':{
        const field=$('#purchase-qq');if(!field)break;
        let copied=false;
        try {if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(field.value);copied=true;}}catch{}
        if(!navigation.current(ticket))break;
        if(!copied&&field.isConnected){
          field.focus({preventScroll:true});field.select();
          try {copied=document.execCommand('copy');}catch{}
          if(copied&&b.isConnected)b.focus({preventScroll:true});
        }
        notify(copied?'QQ号已复制':'复制未完成，请选中QQ号手动复制',{tone:copied?'success':'error'});
        break;
      }
      case 'automation':show('automation');break;
      case 'notifications':show('notifications');break;
      case 'resume-clear':show('resume-clear');break;
      case 'execute-resume-clear':if(await run('clear_resume_history')&&navigation.current(ticket)){const details=await api('get_resume_details');if(navigation.current(ticket)){ui.resumeDetails=details;back();}}break;
      case 'relay-accounts':show('relay-accounts');break;
      case 'resume-details':await openResumeDetails();break;
      case 'resume-message':show('resume-message');break;
      case 'save-resume-message':{
        const message=$('#resume-message').value.trim();
        if(!message||[...message].length>200||!/^\P{C}+$/u.test(message)){
          fieldError('#resume-message','请输入 1–200 个可显示字符，不能换行');break;
        }
        await saveInline(b,{id:'resume-message',key:'message',method:'set_preferences',args:[{resume_message:message}],value:message,
          commit:()=>{data.settings.resume_message=message;},clear:()=>{ui.messageDraft=null;}});
        break;}
      case 'resume-toggle':{
        const session=ui.resumeDetails.find(s=>s.id===val);
        if(!session)break;
        const set=ui.resumeExpanded;
        if(set.has(val))set.clear();
        else {set.clear();set.add(val);}
        renderSheet();break;}
      case 'open-resume-task':await run('open_resume_task',val);break;
      case 'retry-resume-task':await run('retry_resume_task',b.dataset.session,val);break;
      case 'home':closeSheet();break;
      case 'detail':show('detail',target);break;
      case 'toggle-reset-credits':if(ui.resetExpanded.has(target))ui.resetExpanded.delete(target);else {ui.resetExpanded.add(target);ui.disclosures.delete('meta:'+target);}renderSheet();break;
      case 'back':back();break;
      case 'relay':await requestSwitch(relay()?.email,'relay');break;
      case 'launch-chatgpt':await run('launch_chatgpt');break;
      case 'switch':await requestSwitch(target);break;
      case 'execute-switch':await executeSwitch(target,b);break;
      case 'toggle':preferences.set(b.dataset.key,!data.settings[b.dataset.key]);break;
      case 'auto-relay-account':preferences.set('account:'+target,b.getAttribute('aria-checked')!=='true');break;
      case 'early-anchor-account':preferences.set('anchor:'+target,b.getAttribute('aria-checked')!=='true');break;
      case 'pref':preferences.set(b.dataset.key,val);break;
      case 'collection-more':ui.fullCollections.has(val)?ui.fullCollections.delete(val):ui.fullCollections.add(val);renderSheet();break;
      case 'inline-reload':await loadInline(val,true);break;
      case 'hotkeys':show('hotkeys');break;
      case 'record-hotkey':ui.recording=target;renderSheet();break;
      case 'pick':{const clearing=data.settings.relay_pick===target||data.relay_wait?.email===target;await run('set_relay_pick',clearing?null:target);break;}
      case 'quota-overview':show('quota-overview');break;
      case 'quota-metric':ui.quotaMetric=val;if(val==='time'&&ui.quotaScope==='relay')ui.quotaScope='five';renderSheet();break;
      case 'quota-scope':ui.quotaScope=val;if(val==='relay')ui.quotaMetric='quota';renderSheet();break;
      case 'usage-all':await openUsage('all');break;
      case 'usage-account':await openUsage(target);break;
      case 'usage-refresh':await openUsage(ui.scope,true);break;
      case 'usage-period':ui.days=val==='all'?'all':Number(val);navigation.invalidate();await loadUsage();break;
      case 'edit':{if(ui.page!=='detail'||ui.email!==target)show('detail',target);ui.disclosures.add('meta:'+target);renderSheet();$('#alias')?.focus({preventScroll:true});break;}
      case 'save-alias':await saveAccountField(b,target,'alias');break;
      case 'save-expiry':await saveAccountField(b,target,'subscription_date');break;
      case 'remove':show('remove',target);break;
      case 'execute-remove':if(await run('remove',target)&&navigation.current(ticket))closeSheet();break;
      case 'add':show('add');break;
      case 'adopt':await run('adopt_current');break;
      case 'start-add':await run('add_start');break;
      case 'cancel-add':if(await run('add_cancel')&&navigation.current(ticket))closeSheet();break;
      case 'finish-add':if(await run('add_finish')&&navigation.current(ticket))closeSheet();break;
      case 'start-reauth':await run('reauth_start',target);break;
      case 'cancel-reauth':if(await run('reauth_cancel')&&navigation.current(ticket))closeSheet();break;
      case 'finish-reauth':if(await run('reauth_finish')&&navigation.current(ticket))closeSheet();break;
      case 'archives':show('archives');await loadInline('archives');break;
      case 'restore':if(await run('restore',val)&&navigation.current(ticket)){const archives=await api('get_archives');if(navigation.current(ticket)){ui.archives=archives;renderSheet();}}break;
      case 'scenarios':show('scenarios');break;
      case 'scenario':window.NXDemo.scenario(val);ui.usage=null;closeSheet();await poll();break;
      case 'error':if(data.last_error?.id)await run('dismiss_error',data.last_error.id);else {clearNotification();render();}break;
    }} catch(error){if(navigation.current(ticket))notify(error.message||'操作未完成，请重试',{tone:'error'});}
  });
  app.addEventListener('compositionstart',event=>{if(event.target.matches('.field'))composingField=event.target;});
  app.addEventListener('compositionend',()=>{composingField=null;if(deferredSheet){deferredSheet=false;renderSheet();}});
  app.addEventListener('input',event=>{
    if(!event.target.matches('.field'))return;
    const id=event.target.id;
    if(id==='resume-message')ui.messageDraft=event.target.value;
    if(ui.page==='detail'&&['alias','manual-date'].includes(id)){
      const field=id==='alias'?'alias':'subscription_date',draft=ui.metaDrafts.get(ui.email)||{};
      ui.metaDrafts.set(ui.email,{...draft,[field]:event.target.value});
    }
    const key=id==='resume-message'?'message':ui.email+':'+id;
    ui.fieldRevisions.set(key,(ui.fieldRevisions.get(key)||0)+1);
    event.target.removeAttribute('aria-invalid');const error=$('#form-error');if(error)error.textContent='';
  });
  function floatTip(el){
    const tip=$('#float-tip');if(!tip||!el?.dataset.floatTip)return;
    tip.textContent=el.dataset.floatTip;tip.hidden=false;
    const r=el.getBoundingClientRect();requestAnimationFrame(()=>{
      const w=tip.offsetWidth,h=tip.offsetHeight;
      tip.style.left=Math.max(8,Math.min(window.innerWidth-w-8,r.left+r.width/2-w/2))+'px';
      tip.style.top=Math.max(8,r.top-h-8)+'px';
    });
  }
  for(const event of ['mouseover','focusin'])app.addEventListener(event,e=>{const el=e.target.closest('[data-float-tip]');if(el)floatTip(el);});
  app.addEventListener('mousemove',e=>{const el=e.target.closest('[data-float-tip]');if(el)floatTip(el);});
  for(const event of ['mouseout','focusout'])app.addEventListener(event,e=>{if(e.target.closest('[data-float-tip]')){const tip=$('#float-tip');if(tip)tip.hidden=true;}});
  document.addEventListener('keydown',async e=>{
    if(ui.recording){
      e.preventDefault();e.stopPropagation();
      if(e.key==='Escape'){ui.recording=null;renderSheet();return;}
      const target=ui.recording;
      if(e.key==='Backspace'||e.key==='Delete'){ui.recording=null;await action('set_account_hotkey',target,null);return;}
      if(!/^[1-9]$/.test(e.key)||e.metaKey){notify('请按两个以上修饰键加数字 1–9');return;}
      const modifiers=[e.ctrlKey?'ctrl':null,e.altKey?'alt':null,e.shiftKey?'shift':null].filter(Boolean);
      if(modifiers.length<2){notify('至少同时使用 Ctrl、Alt、Shift 中的两个');return;}
      ui.recording=null;await action('set_account_hotkey',target,[...modifiers,e.key].join('+'));return;
    }
    if(e.key==='Enter'&&!e.isComposing&&e.keyCode!==229&&e.target.matches('.inline-field input')){e.preventDefault();e.target.closest('.inline-field').querySelector('.save-check:not(:disabled)')?.click();return;}
    if(e.key==='Escape'){e.preventDefault();if(ui.page)back();else api('hide').catch(()=>{});}
    if(e.key==='Tab'&&ui.page&&sheet.getAttribute('aria-modal')==='true'){const items=[...sheet.querySelectorAll('button:not(:disabled),input,textarea,summary,[tabindex="0"]')].filter(n=>n.offsetParent!==null);if(!items.length)return;const first=items[0],last=items.at(-1);if(e.shiftKey&&(document.activeElement===first||document.activeElement.id==='sheet-title')){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}
  });
  window.addEventListener('blur',()=>{if(!config.demo&&!data.adding&&!data.reauth&&!data.operation&&!document.hasFocus())api('hide','blur').catch(()=>{});});
  window.nxRequestSwitch=target=>requestSwitch(target);
  const systemAppearance=window.matchMedia('(prefers-color-scheme: dark)');
  function applyAppearance(value){
    document.documentElement.dataset.appearance=['light','dark'].includes(value)?value:systemAppearance.matches?'dark':'light';
  }
  systemAppearance.addEventListener('change',()=>applyAppearance(data.settings.appearance));
  window.nxShown=()=>{panelVisible=true;workflowResume=true;closeSheet();setSize('home');poll();};
  window.nxHidden=()=>{panelVisible=false;clearTimeout(pollTimer);pollTimer=null;};
  window.addEventListener('pywebviewready',poll);
  window.addEventListener('resize',()=>{if(config.demo)setSize(ui.page?'workspace':'home');});
  setInterval(()=>{
    if(!panelVisible && !config.demo) return;
    for(const el of app.querySelectorAll('[data-reset]'))el.textContent=reset(Number(el.dataset.reset));
    const sig=data.accounts.map(a=>`${a.email}:${valid(a)}`).join('|');if(sig!==freshSignature){freshSignature=sig;renderHome();}
  },1000);
  function schedulePoll(delay=null){
    clearTimeout(pollTimer);pollTimer=null;
    if(!panelVisible && !config.demo) return;
    const wait=delay ?? ((busy()||ui.submitted)?800:5000);
    pollTimer=setTimeout(()=>poll(),wait);
  }
  applyAppearance(data.settings.appearance);
  setSize('home');renderHome();poll();
  if(config.demo) {
    window.NXPreview={
      async open(params) {
        await poll(true);
        const page=params.get('open');
        if(!page)return;
        if(page==='usage'){
          const period=params.get('days');ui.days=period==='all'?'all':[7,30,180].includes(Number(period))?Number(period):30;
          await openUsage(params.get('email')||'all');return;
        }
        if(page==='resume'){await openResumeDetails();return;}
        const target=['detail','edit','remove','reauth'].includes(page)?data.accounts.find(a=>a.email===params.get('email'))||current()||data.accounts.find(a=>a.error_code==='reauth_required'):page==='confirm'?relay():null;
        if(page==='confirm')ui.switchKind=params.get('kind')==='relay'?'relay':'manual';
        show(page,target?.email||null);
        if(page==='detail'&&params.get('expand')==='reset'&&target){ui.resetExpanded.add(target.email);renderSheet();}
        if(page==='archives')await loadInline('archives');
      },
      refresh:()=>poll(true),
      appearance:async value=>{window.NXDemo.appearance(value);applyAppearance(value);},
      info:()=>({page:ui.page||(home.classList.contains('is-onboarding')?'onboarding':'home'),width:app.clientWidth,height:app.clientHeight})
    };
    window.NXPreviewReady=window.NXPreview.open(new URLSearchParams(window.NX_PREVIEW_QUERY??location.search));
  }
})();
