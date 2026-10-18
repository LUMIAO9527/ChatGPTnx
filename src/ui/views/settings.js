/* Settings and paginated task history expand in one flat settings panel. */
'use strict';
window.NXViews ??= {};
window.NXSettingsContent = (()=>{
  function disclosure(c,key,label,content,count='') {
    const {ui,esc,icon}=c;
    return `<details class="settings-disclosure control-container" data-disclosure="${esc(key)}" ${ui.disclosures.has(key)?'open':''}><summary class="control-header" aria-expanded="${ui.disclosures.has(key)}"><span>${esc(label)}</span><span class="disclosure-meta">${esc(count)}</span>${icon('chevron')}</summary><div class="disclosure-body">${content}</div></details>`;
  }
  function collection(c,key,items,render) {
    if(!items.length)return '<div class="inline-empty" role="status">暂无条目</div>';
    const expanded=c.ui.fullCollections.has(key),limit=8;
    return (expanded?items:items.slice(0,limit)).map(render).join('')
      +(items.length>limit?`<button class="control control--small collection-more" data-action="collection-more" data-value="${key}">${expanded?'收起长名单':`显示其余 ${items.length-limit} 项`}</button>`:'');
  }
  function relay(c) {
    const {data,esc,name,plan,icon}=c,excluded=new Set(data.settings.auto_relay_excluded||[]);
    return `<div class="relay-account-list">${collection(c,'relay',data.accounts,a=>`<div class="relay-account-row collection-row"><span class="relay-account-identity"><span class="relay-account-name" title="${esc(name(a))} · ${esc(a.email)}">${esc(name(a))}</span><span class="badge">${esc(plan(a.plan))}</span></span>${c.selectionButton({label:name(a)+'参与自动接力',checked:!excluded.has(a.email),action:'auto-relay-account',email:a.email})}</div>`)}</div>`;
  }
  function hotkeys(c) {
    const {data,ui,esc,name,hotkeyLabel}=c;
    return `<div class="hotkey-list">${collection(c,'hotkeys',data.accounts,a=>{
      const h=(data.hotkeys||[]).find(x=>x.email===a.email)||{},recording=ui.recording===a.email;
      const conflict=!!h.shortcut&&h.registered===false&&!recording;
      const label=recording?'请按组合键':hotkeyLabel(h.shortcut);
      const hint=recording?'按组合键设置；Backspace 清除，Esc 取消':conflict?'快捷键已被占用，点击重新设置':'点击修改快捷键';
      return `<div class="hotkey-row collection-row"><strong class="collection-name" title="${esc(a.email)}">${esc(name(a))}</strong><button type="button" class="keycap control control--small control--field ${recording?'recording':conflict?'conflict':!h.shortcut?'unset':''}" data-action="record-hotkey" data-email="${esc(a.email)}" aria-label="${esc(name(a)+'，'+label+'，'+hint)}" aria-describedby="hotkey-instructions" title="${esc(hint)}">${esc(label)}</button></div>`;
    })}</div><p id="hotkey-instructions" class="inline-help" aria-live="polite">${ui.recording?'按组合键 · Backspace 清除 · Esc 取消':'点击快捷键修改'}</p>`;
  }
  function earlyAnchor(c) {
    const {data,esc,name,plan,icon}=c,selected=new Set(data.settings.early_anchor_accounts||[]);
    const accounts=data.accounts.filter(a=>a.plan==='plus');
    return `<div class="toggle-line"><span>提前开始 5h 计时<span class="toggle-note">（消耗少许额度）</span></span>${c.switchButton({label:'提前开始 5h 计时（消耗少许额度）',checked:data.settings.early_anchor,key:'early_anchor'})}</div>`
      +`<div class="relay-account-list">${collection(c,'early-anchor',accounts,a=>`<div class="relay-account-row collection-row"><span class="relay-account-identity"><span class="relay-account-name" title="${esc(name(a))}">${esc(name(a))}</span><span class="badge">${esc(plan(a.plan))}</span></span>${c.selectionButton({label:name(a)+'接力预热',checked:selected.has(a.email),action:'early-anchor-account',email:a.email})}</div>`)}</div>`;
  }
  function archives(c) {
    const {ui,esc,dt}=c;
    if(ui.inlineLoading.archives==='loading')return '<div class="inline-empty" role="status">正在读取…</div>';
    if(ui.inlineLoading.archives==='error')return '<button class="control control--small collection-more" data-action="inline-reload" data-value="archives">读取未完成，点击重试</button>';
    return `<div class="archive-list">${collection(c,'archives',ui.archives||[],x=>`<div class="archive-row collection-row"><strong class="collection-name" title="${esc(x.email)} · ${dt(x.archived_at)}">${esc(x.email)}</strong><button class="control secondary small-action control--small" data-action="restore" data-value="${esc(x.key)}">恢复</button></div>`)}</div>`;
  }
  function message(c) {
    return window.NXEditors.row({id:'resume-message',label:'接续消息',value:String(c.ui.messageDraft??c.data.settings.resume_message).replace(/\r\n?|\n/g,' '),action:'save-resume-message'})
      +'<span id="form-error" class="field-feedback" role="alert"></span>';
  }

  const activeResumePhases=new Set(['switching','resuming','waiting_account']);
  function resumeClearControl(c) {
    const {ui,icon,actionButton}=c;
    if(!(ui.resumeDetails||[]).some(s=>!activeResumePhases.has(s.phase)))return '';
    const confirming=ui.resumeClearConfirm||ui.resumeClearPending;
    return actionButton({content:confirming?'确认':icon('archive'),action:'resume-clear',size:'small',iconOnly:!confirming,
      tone:confirming?'danger':'neutral',confirmation:confirming,className:'resume-inline-clear',
      label:confirming?'确认清理已结束记录':'清理已结束记录',
      title:confirming?'再次点击确认清理；进行中的接续会保留':'清理已结束记录',
      attrs:`aria-busy="${!!ui.resumeClearPending}" ${ui.resumeClearPending?'disabled':''}`});
  }

  function resumeHistory(c) {
    const {ui,esc,icon,name,data,actionButton}=c;
    if(ui.inlineLoading['resume-history']==='loading')return '<div class="inline-empty" role="status">正在读取…</div>';
    if(ui.inlineLoading['resume-history']==='error')return '<button class="control control--small collection-more" data-action="inline-reload" data-value="resume-history">读取未完成，点击重试</button>';
    const active=activeResumePhases;
    const sessions=[...(ui.resumeDetails||[])].sort((a,b)=>Number(active.has(b.phase))-Number(active.has(a.phase))||b.updated_at-a.updated_at);
    const records=sessions.flatMap(s=>s.items.map(i=>({s,i})));
    if(!records.length)return '<div class="inline-empty" role="status">暂无接续记录</div>';
    const pageSize=5,totalPages=Math.max(1,Math.ceil(records.length/pageSize));
    const page=Math.max(1,Math.min(totalPages,Number(ui.resumePage)||1));
    ui.resumePage=page;
    const rows=records.slice((page-1)*pageSize,page*pageSize).map(({s,i})=>{
      const target=window.NXResumeDisplay.target(i),subagent=!!i.is_subagent;
      const rawTitle=i.title||'未命名任务';
      const title=subagent&&!rawTitle.startsWith('后台子任务：')?'后台子任务：'+rawTitle:rawTitle;
      const status=({done:'已接续',failed:subagent?'失败':'重试',skipped:'已跳过',acting:'接续中',waiting:'等待中'})[i.state]||'处理中';
      const reason=window.NXResumeDisplay.reason(i);
      const navigation=subagent?(target?'打开所属主任务'+(i.parent_title?'：'+i.parent_title:''):'所属主任务未确认，不能独立打开'):target?'打开原任务':'任务编号未确认';
      const stateClass=({done:'done',failed:'failed',skipped:'skipped',acting:'active',waiting:'waiting'})[i.state]||'pending';
      const date=new Date(s.updated_at*1000),today=date.toDateString()===new Date().toDateString();
      const time=(today?'今天 ':'')+date.toLocaleString('zh-CN',today?{hour:'2-digit',minute:'2-digit'}:{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
      const compactTime=time;
      const retry=!i.is_subagent&&i.state==='failed'&&window.NX_RESUME_POLICY.retryable.includes(i.reason);
      const result=i.state==='failed'&&!subagent?actionButton({content:'重试',action:'retry-resume-task',size:'small',tone:'danger',className:'resume-inline-retry',label:'重试接续：'+title,title:retry?'重试接续':(reason+'；此记录暂不可重试，点击任务查看'),attrs:`data-session="${esc(s.id)}" data-value="${esc(i.thread_id)}" ${retry?'':'disabled'}`}):esc(status);
      const hint=[title,i.state==='failed'?'接续失败':status,reason,compactTime,navigation].filter(Boolean).join(' · ');
      return `<div class="resume-inline-row interaction-row${subagent?' is-subagent':''}"><button class="resume-inline-task control--embedded" ${target?`data-action="open-resume-task" data-value="${esc(target)}"`:'disabled'} aria-label="${esc(hint)}" title="${esc(hint)}"><i class="resume-inline-dot state-${stateClass}" aria-hidden="true"></i><span class="resume-inline-title">${esc(title)}</span><span class="resume-inline-time">${esc(compactTime)}</span></button><span class="resume-inline-result ${i.state==='failed'?'is-failed':''}">${result}</span></div>`;
    }).join('');
    const pager=totalPages>1?`<div class="resume-inline-pager" tabindex="-1" aria-label="接续记录分页" style="--resume-page-width:${String(totalPages).length*2+3}ch">${actionButton({content:icon('chevron'),action:'resume-page',size:'small',iconOnly:true,className:'resume-inline-page',label:'上一页',attrs:`data-value="prev" ${page===1?'disabled':''}`})}<span class="resume-inline-page-count" role="status" aria-live="polite" aria-atomic="true">${page} / ${totalPages}</span>${actionButton({content:icon('chevron'),action:'resume-page',size:'small',iconOnly:true,className:'resume-inline-page',label:'下一页',attrs:`data-value="next" ${page===totalPages?'disabled':''}`})}</div>`:'<span></span>';
    const clear=resumeClearControl(c);
    const tools=totalPages>1||clear?`<div class="resume-inline-tools">${pager}${clear?`<span class="resume-inline-clear-slot">${clear}</span>`:''}</div>`:'';
    return `<div class="resume-inline-list${totalPages>1?' has-pagination':''}" data-motion-pages="resume" data-page="${page}" data-page-count="${totalPages}"><div class="resume-page-content">${rows}</div></div>${tools}`;
  }

  return {disclosure,relay,hotkeys,archives,message,earlyAnchor,resumeHistory,resumeClearControl};
})();
window.NXViews.settings = c => {
  const {data,ui,settingsGroup,systemSettings,autoRelaySetting,taskContinuationSetting,notificationSettings,segmented,link}=c;
  const x=window.NXSettingsContent,n=data.accounts.filter(a=>!(data.settings.auto_relay_excluded||[]).includes(a.email)).length;
  const options=[['system','系统'],['light','浅色'],['dark','深色']];
  const appearance=x.disclosure(c,'appearance','外观',segmented({label:'外观',action:'pref',key:'appearance',options,value:data.settings.appearance,className:'compact'}),options.find(([v])=>v===data.settings.appearance)?.[1]||'系统');
  const body=settingsGroup('系统',systemSettings(data.settings)+appearance+x.disclosure(c,'notifications','通知',notificationSettings(data.settings)))
    +settingsGroup('接力与接续',x.disclosure(c,'relay','自动接力',autoRelaySetting(data.settings)+x.relay(c),data.settings.auto_relay?`${n} 个账号`:'未开启')
      +x.disclosure(c,'early-anchor','接力预热',x.earlyAnchor(c),data.settings.early_anchor?`${data.accounts.filter(a=>a.plan==='plus'&&(data.settings.early_anchor_accounts||[]).includes(a.email)).length} 个账号`:'未开启')
      +x.disclosure(c,'message','任务接续',taskContinuationSetting(data.settings)+'<p class="inline-help">接续消息</p>'+x.message(c),data.settings.task_continuation?'已开启':'未开启')
      +x.disclosure(c,'resume-history','任务接续记录',x.resumeHistory(c),(()=>{const count=(ui.resumeDetails||[]).reduce((n,s)=>n+(s.items?.length||0),0);return count?`${count} 条`:''})()))
    +settingsGroup('账号',x.disclosure(c,'hotkeys','账号快捷键',x.hotkeys(c),`${(data.hotkeys||[]).filter(h=>h.shortcut).length} 个`)
      +x.disclosure(c,'archives','已归档账号',x.archives(c),ui.archives?`${ui.archives.length} 个`:''))
    +settingsGroup('关于',link('','版本更新','open-update')
      +link('','联系与支持','purchase-account'));
  return {title:'设置',body:`<div class="settings-content" style="min-height:${ui.settingsScrollFloor||0}px">${body}</div>`,cls:'settings-body'};
};
window.NXViews.purchase = c => ({
  title:'联系与支持',cls:'purchase-body',
  body:`<section class="purchase-contact" aria-labelledby="purchase-contact-title">
      <h3 id="purchase-contact-title">咨询</h3>
      <p class="purchase-services">Plus 账号 · 接码服务 · 使用咨询</p>
      <div class="purchase-number"><label for="purchase-qq">QQ号：</label><input id="purchase-qq" class="purchase-qq" aria-label="QQ号" value="210037309" readonly spellcheck="false"></div>
      <p class="purchase-note">添加时请备注“ChatGPTnx”</p>
      <button class="control control--large primary purchase-copy" data-action="copy-purchase-qq" aria-label="复制 QQ 号">${c.icon('copy')}<span>复制 QQ 号</span></button>
    </section>
    <section class="support-card"><div class="support-copy"><h3>打赏作者</h3>
      <p>如果这个工具帮到了你，<br>欢迎随意打赏。</p>
      <p class="support-scan">支付宝 · 点击放大</p></div>
      <button class="support-code" data-action="support-qr" aria-label="放大支付宝收款码"><img src="${window.NX_SUPPORT_QR||''}" alt="支付宝收款二维码" width="528" height="528"></button>
    </section>`
});
window.NXViews.supportQr = () => ({
  title:'支付宝收款码',cls:'support-body support-zoom',
  body:`<img class="support-full-code" src="${window.NX_SUPPORT_QR||''}" alt="支付宝收款二维码" width="528" height="528"><p class="support-note">打开支付宝扫一扫</p>`
});
window.NXViews.update = c => {
  const {data,esc,icon}=c,u=data.update||{},status=u.status||'idle';
  const working=['checking','downloading','installing'].includes(status);
  const blocked=!!(data.adding||data.reauth||data.operation||['switching','resuming'].includes(data.resume?.phase));
  const action=status==='ready'?'install-update':status==='available'||status==='error'&&u.available?'download-update':'check-update';
  const label={checking:'正在检查…',downloading:`下载中 ${Number(u.progress)||0}%`,installing:'正在重启…',ready:'重启并更新',available:'下载更新'}[status]||(status==='error'?'重试':'检查更新');
  const disabled=working||status==='ready'&&blocked||action==='download-update'&&u.installable===false;
  const hasNotes=!!(u.available&&u.notes),notesOpen=hasNotes&&c.ui.disclosures.has('update-notes');
  const stateTitle={idle:'检查是否有新版本',checking:'正在检查更新…',current:'当前已是最新版本',available:'发现新版本',downloading:'正在下载更新…',ready:'更新已准备好',installing:'正在重启并更新…',error:'更新未完成'}[status]||'检查是否有新版本';
  const description=status==='ready'&&blocked?'请完成登录、切号或任务接续后更新。':status==='error'?u.message:u.available?`新版本 ${u.version}${u.installable===false?' · 内置更新仅适用于独立 EXE':status==='ready'?' · 已通过校验':''}`:'从 GitHub 获取最新正式版。';
  const versionLabel=`新版本 ${u.version||''}`;
  const versionEntry=hasNotes?`<button id="update-notes-toggle" class="control control--large update-notes-toggle" data-action="toggle-update-notes" aria-controls="update-notes-body" aria-expanded="${notesOpen}" aria-label="${notesOpen?'收起':'查看'}${esc(versionLabel)}的更新说明">${esc(versionLabel)}${icon('chevron')}</button>`:esc(description);
  const contextMessage=hasNotes?(status==='error'?u.message:status==='ready'&&blocked?'请完成登录、切号或任务接续后更新。':u.installable===false?'内置更新仅适用于独立 EXE':status==='ready'?'已通过校验':''):'';
  return {title:'版本更新',cls:'update-body',
    body:`<section class="update-identity">${c.brandMark('update-mark')}<h3 class="update-brand">ChatGPTnx</h3><p class="update-version">当前版本 ${esc(data.version||window.NX_CONFIG.version)}</p>
      <button class="control control--large update-github" data-action="open-github" title="github.com/LUMIAO9527/ChatGPTnx">${icon('github')}<span>GitHub 项目</span>${icon('external')}</button></section>
      <button id="update-primary" class="control control--large primary update-primary${action==='install-update'?' control--confirmation':''}" data-action="${action}" aria-busy="${working}" aria-describedby="update-description update-context" ${disabled?'disabled':''}>${icon(!working&&action==='download-update'?'download':'refresh',working?'spinner':'')}<span>${esc(label)}</span></button>
      <section class="update-state" aria-live="polite"><h3 class="update-message">${esc(stateTitle)}</h3>
      <div class="update-release" data-disclosure="update-notes"><div id="update-description" class="update-description">${versionEntry}</div>
      <div id="update-notes-body" class="update-notes-body" tabindex="0" role="region" aria-label="更新内容" ${notesOpen?'':'hidden'}>${esc(u.notes||'')}</div></div>
      <div class="update-tools" ${status==='downloading'||contextMessage?'':'hidden'}><button class="control control--large update-cancel" data-action="cancel-update-download" ${status==='downloading'?'':'hidden'}>取消下载</button>
      <p id="update-context" class="update-context" aria-live="polite" ${contextMessage?'':'hidden'}>${esc(contextMessage||'')}</p>
      <progress class="update-progress" max="100" value="${Number(u.progress)||0}" aria-label="更新下载进度" ${status==='downloading'?'':'hidden'}></progress></div></section>`,
    foot:'<p class="update-preserve">更新后保留账号与设置</p>',footClass:'update-footer'};
};
