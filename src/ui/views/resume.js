/* Shared history semantics survive the move from a separate page to settings. */
'use strict';
window.NXResumeDisplay=(()=>{
  const reasons={
      invalid_resume_message:'接续消息无效',
      action_outcome_unknown:'结果未确认；已停止自动接续，请查看原任务',
      account_guard_unavailable:'无法核对当前账号',
      desktop_not_running:'桌面端未运行，未执行接续',
      desktop_window_ambiguous:'多个任务入口冲突，无法确定窗口',
      desktop_location_unreadable:'无法读取桌面窗口内容',
      task_identity_unavailable:'无法确认任务编号对应关系',
      task_navigation_unconfirmed:'原任务打开结果未确认，尚未发送',
      target_changed:'原任务页面已变化',
      invalid_task_id:'任务编号无效',
      task_state_changed:'原任务状态已变化，未执行接续',
      resume_state_unavailable:'接续记录无法验证，已停止自动接续',legacy_route_removed:'旧接续路径已停用，请查看原任务',
      duplicate_attempt:'该回合已处理，未重复操作',
      subagent_task:'后台子任务，不单独接续',
      desktop_bridge_ambiguous:'存在多个桌面桥接，未发送消息',
      resume_source_unavailable:'接续连接暂不可用，请打开一条主任务后重试',
      native_turn_resumed:'原任务已恢复运行',
      invalid_saved_state:'记录状态异常',
      title_unavailable_or_ambiguous:'无法确认原任务页面',
      desktop_bridge_unavailable:'等待桌面连接恢复',
      desktop_request_rejected:'桌面端未接受请求，请查看原任务后重试',
      desktop_task_not_idle:'原任务状态不符合接续条件',
      bridge_target_mismatch:'接续接口返回了其他任务，已停止',
      resume_source_unconfigured:'接续连接配置无效',
      resume_source_is_target:'接续来源任务不能向自身发送',
      account_changed:'接续前账号已变化',
      switch_not_completed:'账号切换未完成',
      switch_failed:'账号切换未完成',
      switch_boundary_ambiguous:'切号期间无法确认任务所属账号',
      relay_not_available:'没有可用的接力账号',
      start_not_observed:'未检测到任务启动',
      native_continue_unavailable:'未找到原生继续按钮',
      native_continue_not_ready:'原生继续按钮不可用',
      native_continue_ambiguous:'页面有多个继续按钮',
      target_not_visible:'原任务页面未显示',
      history_unavailable:'任务状态暂不可读',
      resume_expired:'接续等待已过期',
      continuation_disabled:'自动接续已关闭',
      unrelated_failure:'任务因其他原因停止',
      task_already_running:'任务已在运行',
      newer_turn:'已有新回合',
      new_turn_observed:'已在原任务启动新回合',
      resume_auth_failed:'接续回合账号认证失败（401）',
      resumed_turn_overloaded:'接续回合遇到模型繁忙',
      resumed_turn_network:'接续回合遇到网络错误',
      resumed_turn_limit:'接续回合再次遇到额度限制',
      resumed_turn_failed:'接续回合失败',
      resumed_turn_completed:'接续回合已完成',
      resumed_turn_interrupted:'接续后被中断'
    };
  const valid=id=>typeof id==='string'&&/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(id);
  const target=item=>item.is_subagent
    ? valid(item.parent_thread_id)&&item.parent_thread_id!==item.thread_id?item.parent_thread_id:null
    : valid(item.thread_id)?item.thread_id:null;
  const reason=item=>reasons[item.reason]||(item.state==='failed'?'接续失败，请查看原任务':'');
  return {reasons,target,reason};
})();

/* Pure view: state in, HTML out. */
'use strict';
window.NXViews ??= {};
window.NXViews.resume = context => {
  const {data,ui,esc,icon,name,now} = context;
  function resumeContent() {
    const sessions=[...(ui.resumeDetails||[])].sort((a,b)=>b.updated_at-a.updated_at);
    const reasons=window.NXResumeDisplay.reasons;
    if(!sessions.length)return '<div class="empty"><h3>暂无接续记录</h3></div>';
    const day=new Date();day.setHours(0,0,0,0);
    const activePhases=['switching','resuming','waiting_account'];
    const groups=[['进行中',sessions.filter(s=>activePhases.includes(s.phase))],
      ['今天',sessions.filter(s=>!activePhases.includes(s.phase)&&s.updated_at*1000>=day.getTime())],
      ['近 7 天',sessions.filter(s=>!activePhases.includes(s.phase)&&s.updated_at*1000<day.getTime())]];
    const row=s=>{
      const attention=i=>window.NX_RESUME_POLICY.attention.includes(i.reason);
      const done=s.items.filter(i=>i.state==='done').length,failed=s.items.filter(i=>i.state==='failed').length;
      const skipped=s.items.filter(i=>i.state==='skipped').length,pending=s.items.length-done-failed-skipped;
      const active=activePhases.includes(s.phase);
      const expanded=ui.resumeExpanded.has(s.id);
      const account=data.accounts.find(a=>a.email===(s.target||s.origin));
      const scheduled=Number.isFinite(s.scheduled_at)?new Date(s.scheduled_at*1000):null;
      const time=s.phase==='waiting_account'
        ? scheduled && s.scheduled_at>now()
          ? `预计 ${scheduled.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}`
          : scheduled?'正在核验额度':'等待额度刷新'
        : new Date(s.updated_at*1000).toLocaleString('zh-CN',s.updated_at*1000<day.getTime()?{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}:{hour:'2-digit',minute:'2-digit'});
      const progressMarkup=(progress,failed=false)=>progress==='0/1'&&failed?'<span class="resume-zero">0</span>/1':esc(progress);
      const rows=expanded?window.NXComponents.pagedList(context,'resume:'+s.id,s.items,i=>window.NXSettingsContent.resumeRecord(context,s,i,true),{label:'接续任务'}):'';
      const progress=`${done}/${s.items.length}`;
      const counts=`成功 ${done} · 跳过 ${skipped} · 需查看 ${failed}${pending?' · 待处理 '+pending:''}`;
      const hint=`${account?name(account):'账号接力'} · ${time} · 已接续 ${progress} · ${counts}`;
      const explanation=s.items.some(i=>i.is_subagent===true)?'<p class="resume-subagent-note">后台子任务，当前版本不单独接续；可点击的记录打开所属主任务。原处理结果保留如下。</p>':'';
      return `<section class="resume-session control-container" data-disclosure="resume:${esc(s.id)}"><button class="resume-summary control-header" data-action="resume-toggle" data-value="${esc(s.id)}" aria-expanded="${expanded}" title="${esc(hint)}" aria-label="${esc(hint)}"><span>${esc(account?name(account):'账号接力')} · ${esc(time)}</span><strong class="resume-progress mono">${progressMarkup(progress,s.items.some(i=>i.state==='failed'&&!attention(i)))}</strong>${icon('chevron')}</button>${expanded?`<div class="resume-tasks">${explanation}${rows}</div>`:''}</section>`;
    };
    return groups.filter(([,items])=>items.length).map(([label,items])=>`<section class="resume-group"><div class="resume-group-head"><strong>${label}</strong><span>${items.length} 次</span></div>${items.map(row).join('')}</section>`).join('');
  }
  return resumeContent();
};
