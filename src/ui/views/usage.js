/* Flat usage report: identity, period pills, headline total and a full-width trend. */
'use strict';
window.NXViews ??= {};
window.NXViews.usage = c => {
  const {data,ui,esc,icon,name,plan,tool,disabled,scopeUsage,math,segmented,metricsRow,short,durText,statuses,brandMark,avatar,accountIdentity}=c;
  const u=scopeUsage(),all=ui.scope==='all',account=data.accounts.find(a=>a.email===ui.scope);
  const record=all?null:u?.rows?.[0],summary=!all&&['ready','missing_total'].includes(record?.status)?record.usage?.summary||{}:{};
  const lifetime=ui.days==='all',totalValue=!u?null:lifetime?(all?u.total_tokens:summary.lifetimeTokens):u.period.recorded_tokens;
  const totalFormat=math.compact(totalValue);
  const identity=all?`<div class="identity usage-source">${brandMark('usage-brand')}<div class="identity-copy"><span class="identity-title"><strong>所有账号</strong></span><small>${u?.unique_accounts??data.accounts.length} 个账号</small></div></div>`:accountIdentity(account);
  const filters=segmented({label:'用量时间范围',action:'usage-period',options:[[7,'7天'],[30,'30天'],[180,'180天'],['all','全部']],value:ui.days,className:'usage-filter quota-slot'});
  const header=`<section class="usage-context" aria-label="账号与时间范围"><div class="current-identity detail-profile usage-top">${identity}${tool('refresh','usage-refresh','刷新个人用量',disabled(),data.operation?.kind==='usage'?'spinner':'')}</div>${filters}</section>`;
  const hero=`<div class="usage-hero"><div class="eyebrow">累计 Tokens</div><div class="usage-total mono" aria-label="${math.exact(totalValue)} Tokens">${totalFormat.main}<span>${totalFormat.unit}</span></div></div>`;
  const {groups,groupLabel,chartStartLabel,chartEndLabel}=u?math.trendGroups(u,lifetime):{groups:[],groupLabel:'',chartStartLabel:'',chartEndLabel:''};
  const max=groups.reduce((m,g)=>g.tokens>m?g.tokens:m,1n);
  const bars=groups.map(g=>{
    const missing=!g.recorded,partial=g.complete<g.length,isToday=!lifetime&&g.first<=u.period.end&&g.last>=u.period.end;
    const height=missing?0:Math.max(g.tokens===0n?0:isToday?8:5,Number(g.tokens*10000n/max)/100);
    const range=g.label||`${g.first}${g.first===g.last?'':' — '+g.last}`,tip=`${range} · ${missing?'无记录':math.compactText(g.tokens)+' Tokens'}${partial?` · 已记录 ${g.recorded}/${g.length} 天`:''}`;
    return `<i class="trend-bar ${missing?'missing':partial?'partial':g.tokens===0n?'zero':''} ${isToday?'today':''}" style="height:${height}%" tabindex="0" role="img" aria-label="${esc(tip)}" data-float-tip="${esc(tip)}"></i>`;
  }).join('');
  const today=u?.daily?.find(d=>d.date===u.period.end);
  const chart=`<section class="usage-trend"><div class="usage-chart-heading"><strong>${lifetime?'月度用量':'用量趋势'}</strong><span>${groupLabel}${today?' · 今日 '+math.compactText(today.tokens):''}</span></div><div class="trend" role="group" aria-label="Token 用量趋势">${bars||`<span class="usage-chart-empty">${u?'暂无用量记录':'正在读取…'}</span>`}</div><div class="trend-labels"><span>${chartStartLabel}</span><span>${chartEndLabel}</span></div></section>`;
  const report=header+`<section class="usage-summary" aria-label="用量统计">${hero}${chart}</section>`;
  let lower;
  if(all){
    const rows=(ui.usage?.rows||[]).map(r=>{
      const a=data.accounts.find(a=>a.email===r.email),value=lifetime?(r.included?r.tokens:null):r.period_tokens;
      const share=value!==null&&totalValue&&math.count(totalValue)>0n?Number((BigInt(value)*1000n/BigInt(totalValue)))/10:null;
      const status=lifetime?statuses[r.status]:value===null?'区间无记录':r.status==='ready'?'已记录':statuses[r.status]||'已记录';
      return `<button class="account-usage-row" data-action="usage-account" data-email="${esc(r.email)}">${avatar(a)}<span class="identity-copy"><strong>${esc(name(a))}</strong><small>${esc(plan(a?.plan))} · ${esc(status)}</small></span><span class="usage-number mono">${value!==null?short(value):'—'}<small>${share==null?'查看详情':share.toFixed(1)+'%'}</small></span>${icon('chevron')}</button>`;
    }).join('');
    const count=lifetime?u?.included_accounts:(u?.rows||[]).filter(r=>r.period_tokens!==null).length;
    lower=`<section class="usage-accounts"><div class="section-title"><h3>账号</h3><span>${u?`${count}/${u.unique_accounts} ${lifetime?'已计入':'有记录'}`:'读取中'}</span></div><div class="account-usage-list">${rows||'<div class="inline-empty">暂无账号记录</div>'}</div></section>`;
  }else{
    const peak=(u?.daily||[]).reduce((m,d)=>math.count(d.tokens)>m?math.count(d.tokens):m,0n),span=u?.period?.span_days||0;
    const days=u?.daily||[],currentStreak=record?.usage?.summary?.currentStreakDays;
    const stats=metricsRow([['单日峰值',lifetime?short(summary.peakDailyTokens):days.length?short(String(peak)):'—'],['连续使用',Number.isInteger(currentStreak)&&currentStreak>=0?currentStreak+'天':'—'],['日均用量',days.length?short(String(days.reduce((sum,d)=>sum+math.count(d.tokens),0n)/BigInt(days.length))):'—']]);
    const sizedStats=stats.replace(/(<strong class="mono">)([\d.,]+)(万|亿|天)(<\/strong>)/g,'$1<span class="metric-number">$2</span><span class="metric-unit">$3</span>$4');
    lower=`<section class="usage-account-details">${sizedStats}</section><button class="usage-bottom-back" data-action="usage-all">全部账号 ${icon('chevron')}</button>`;
  }
  return report+lower+'<div id="float-tip" class="float-tip" hidden></div>';
};
