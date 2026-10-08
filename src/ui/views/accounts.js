/* Pure view: state in, HTML out. */
'use strict';
window.NXViews ??= {};
window.NXViews.accounts = context => {
  const {data,ui,esc,icon,name,plan,duration,reset,quotaValue,resetValue,segmented,remaining} = context;
  function quotaOverviewContent(){
    const sorted=[...data.accounts].sort((a,b)=>{
      if(ui.quotaScope==='relay'&&ui.quotaMetric==='quota'){
        const order=data.relay_order||[],ai=order.indexOf(a.email),bi=order.indexOf(b.email);
        return (ai<0?Infinity:ai)-(bi<0?Infinity:bi) || name(a).localeCompare(name(b),'zh-CN');
      }
      const minutes=ui.quotaScope==='week'?10080:300;
      if(ui.quotaMetric==='time')return resetValue(a,minutes)-resetValue(b,minutes) || name(a).localeCompare(name(b),'zh-CN');
      return quotaValue(b,minutes)-quotaValue(a,minutes) || name(a).localeCompare(name(b),'zh-CN');
    });
    const rows=sorted.map(a=>{
      const windows=window.NXComponents.displayWindows(a).slice(0,2).map(w=>`<span class="quota-overview-window ${100-w.used<=10?'danger':''}"><em>${esc(w.label)}</em><strong class="mono">${remaining(w)}%</strong><small class="mono" data-duration="${duration(w)}" data-reset="${w.resets_at}">${reset(w.resets_at)}</small></span>`).join('');
      return `<button class="quota-overview-row" data-action="detail" data-email="${esc(a.email)}">${window.NXComponents.avatar(a)}<span class="quota-overview-main"><span class="identity-title"><strong title="${esc(name(a))}">${esc(name(a))}</strong><span class="badge">${esc(plan(a.plan))}</span>${a.email===data.current?'<span class="current-chip">当前</span>':''}</span><span class="quota-overview-windows">${windows||'<span class="muted small">额度暂不可用</span>'}</span></span>${icon('chevron')}</button>`;
    }).join('');
    const metrics=[['quota','额度'],['time','时间']],scopes=[['relay','接力'],['five','5h'],['week','周']];
    return `<div class="quota-overview-toolbar">${segmented({label:'排序依据',action:'quota-metric',options:metrics,value:ui.quotaMetric,className:'quota-metric'})}${segmented({label:'额度窗口',action:'quota-scope',options:scopes,value:ui.quotaScope,className:'quota-scope'})}</div><div class="quota-overview-list">${rows||'<div class="empty"><h3>暂无账号</h3></div>'}</div>`;
  }
  return quotaOverviewContent();
};
