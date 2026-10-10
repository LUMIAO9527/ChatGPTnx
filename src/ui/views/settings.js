/* Short settings expand in place. Long task history has its own page. */
'use strict';
window.NXViews ??= {};
window.NXSettingsContent = (()=>{
  function disclosure(c,key,label,content,count='') {
    const {ui,esc,icon}=c;
    return `<details class="settings-disclosure" ${ui.page==='settings'?'name="nx-settings"':''} data-disclosure="${esc(key)}" ${ui.disclosures.has(key)?'open':''}><summary><span>${esc(label)}</span><span class="disclosure-meta">${esc(count)}</span>${icon('chevron')}</summary><div class="disclosure-body">${content}</div></details>`;
  }
  function collection(c,key,items,render) {
    if(!items.length)return '<div class="inline-empty" role="status">暂无条目</div>';
    const expanded=c.ui.fullCollections.has(key),limit=8;
    return (expanded?items:items.slice(0,limit)).map(render).join('')
      +(items.length>limit?`<button class="collection-more" data-action="collection-more" data-value="${key}">${expanded?'收起长名单':`显示其余 ${items.length-limit} 项`}</button>`:'');
  }
  function relay(c) {
    const {data,esc,name,plan}=c,excluded=new Set(data.settings.auto_relay_excluded||[]);
    return `<div class="relay-account-list">${collection(c,'relay',data.accounts,a=>`<div class="relay-account-row collection-row"><span class="relay-account-identity"><span class="relay-account-name" title="${esc(name(a))} · ${esc(a.email)}">${esc(name(a))}</span><span class="badge">${esc(plan(a.plan))}</span></span><button class="switch" role="switch" aria-label="${esc(name(a))}参与自动接力" aria-checked="${!excluded.has(a.email)}" data-action="auto-relay-account" data-email="${esc(a.email)}"><i></i></button></div>`)}</div>`;
  }
  function hotkeys(c) {
    const {data,ui,esc,name,hotkeyLabel}=c;
    return `<div class="hotkey-list">${collection(c,'hotkeys',data.accounts,a=>{
      const h=(data.hotkeys||[]).find(x=>x.email===a.email)||{},recording=ui.recording===a.email;
      return `<div class="hotkey-row collection-row"><strong class="collection-name" title="${esc(a.email)}">${esc(name(a))}</strong><button class="keycap ${recording?'recording':''}" data-action="record-hotkey" data-email="${esc(a.email)}" title="${h.registered===false?'快捷键被占用':esc(a.email)}">${recording?'请按组合键':esc(hotkeyLabel(h.shortcut))}</button></div>`;
    })}</div><p class="inline-help">点击录制 · Backspace 清除 · Esc 取消</p>`;
  }
  function earlyAnchor(c) {
    const {data,esc,name,plan}=c,selected=new Set(data.settings.early_anchor_accounts||[]);
    const accounts=data.accounts.filter(a=>a.plan==='plus');
    return `<div class="toggle-line"><span>工作期间自动预热</span><button class="switch" role="switch" aria-label="工作期间自动预热" aria-checked="${!!data.settings.early_anchor}" data-action="toggle" data-key="early_anchor"><i></i></button></div>`
      +'<p class="inline-help">工作期间，提前启动所选备用 Plus 的 5h 计时，消耗极少额度；额度恢复后继续下一轮。</p>'
      +`<div class="relay-account-list">${collection(c,'early-anchor',accounts,a=>`<div class="relay-account-row collection-row"><span class="relay-account-identity"><span class="relay-account-name" title="${esc(name(a))}">${esc(name(a))}</span><span class="badge">${esc(plan(a.plan))}</span></span><button class="switch" role="switch" aria-label="${esc(name(a))}接力预热" aria-checked="${selected.has(a.email)}" data-action="early-anchor-account" data-email="${esc(a.email)}"><i></i></button></div>`)}</div>`;
  }
  function archives(c) {
    const {ui,esc,dt}=c;
    if(ui.inlineLoading.archives==='loading')return '<div class="inline-empty" role="status">正在读取…</div>';
    if(ui.inlineLoading.archives==='error')return '<button class="collection-more" data-action="inline-reload" data-value="archives">读取未完成，点击重试</button>';
    return `<div class="archive-list">${collection(c,'archives',ui.archives||[],x=>`<div class="archive-row collection-row"><strong class="collection-name" title="${esc(x.email)} · ${dt(x.archived_at)}">${esc(x.email)}</strong><button class="btn secondary small-action" data-action="restore" data-value="${esc(x.key)}">恢复</button></div>`)}</div>`;
  }
  function message(c) {
    return window.NXEditors.row({id:'resume-message',label:'接续消息',value:String(c.ui.messageDraft??c.data.settings.resume_message).replace(/\r\n?|\n/g,' '),action:'save-resume-message'})
      +'<span id="form-error" class="field-feedback" role="alert"></span>';
  }
  return {disclosure,relay,hotkeys,archives,message,earlyAnchor};
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
      +link('','任务接续记录','resume-details'))
    +settingsGroup('账号',x.disclosure(c,'hotkeys','账号快捷键',x.hotkeys(c),`${(data.hotkeys||[]).filter(h=>h.shortcut).length} 个`)
      +x.disclosure(c,'archives','已归档账号',x.archives(c),ui.archives?`${ui.archives.length} 个`:'')
      +link('','购买账号','purchase-account'));
  return {title:'设置',body,cls:'settings-body'};
};
window.NXViews.purchase = () => ({
  title:'购买账号',cls:'purchase-body',
  body:`<p class="purchase-intro">联系作者，咨询账号与服务。</p>
    <section class="purchase-services" aria-label="可咨询的服务">
      <div class="purchase-service"><h3>Plus 账号</h3><p>购买与组合咨询</p></div>
      <div class="purchase-service"><h3>接码服务</h3><p>适用平台与服务咨询</p></div>
    </section>
    <section class="purchase-contact" aria-labelledby="purchase-contact-title">
      <h3 id="purchase-contact-title">QQ联系</h3>
      <input id="purchase-qq" class="purchase-qq" aria-label="QQ号" value="210037309" readonly spellcheck="false">
      <button class="btn primary fill" data-action="copy-purchase-qq">复制QQ号</button>
      <p>添加时请备注“ChatGPTnx”</p>
    </section>
    <p class="purchase-note">具体价格与服务内容请通过QQ咨询。</p>`
});
