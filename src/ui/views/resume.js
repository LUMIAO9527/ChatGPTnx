/* Pure view: state in, HTML out. */
'use strict';
window.NXViews ??= {};
window.NXViews.resume = context => {
  const {data,ui,esc,icon,name,now} = context;
  function resumeContent() {
    const sessions=[...(ui.resumeDetails||[])].sort((a,b)=>b.updated_at-a.updated_at);
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
      desktop_bridge_ambiguous:'存在多个桌面桥接，未发送消息',
      resume_source_unavailable:'无法确认接续来源任务',
      native_turn_resumed:'原任务已恢复运行',
      invalid_saved_state:'记录状态异常',
      title_unavailable_or_ambiguous:'无法确认原任务页面',
      desktop_bridge_unavailable:'桌面桥接不可用，未发送消息',
      desktop_task_not_idle:'原任务状态不符合接续条件',
      bridge_target_mismatch:'接续接口返回了其他任务，已停止',
      resume_source_unconfigured:'尚未配置接续消息来源',
      resume_source_is_target:'接续来源任务不能向自身发送',
      account_changed:'接续前账号已变化',
      switch_not_completed:'账号切换未完成',
      switch_failed:'账号切换未完成',
      switch_boundary_ambiguous:'切号期间无法确认任务所属账号',
      relay_not_available:'没有可用的接力账号',
      start_not_observed:'未确认新回合已开始',
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
      new_turn_observed:'已在原任务启动新回合'
      ,resume_auth_failed:'接续回合账号认证失败（401）'
      ,resumed_turn_failed:'接续回合失败'
      ,resumed_turn_completed:'接续回合已完成'
      ,resumed_turn_interrupted:'接续后被中断'
    };
    if(!sessions.length)return '<div class="empty"><h3>暂无接续记录</h3></div>';
    const day=new Date();day.setHours(0,0,0,0);
    const activePhases=['switching','resuming','waiting_account'];
    const groups=[['进行中',sessions.filter(s=>activePhases.includes(s.phase))],
      ['今天',sessions.filter(s=>!activePhases.includes(s.phase)&&s.updated_at*1000>=day.getTime())],
      ['近 7 天',sessions.filter(s=>!activePhases.includes(s.phase)&&s.updated_at*1000<day.getTime())]];
    const row=s=>{
      const attention=i=>window.NX_RESUME_POLICY.attention.includes(i.reason);
      const done=s.items.filter(i=>i.state==='done').length,failed=s.items.filter(i=>i.state==='failed').length;
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
      const rows=expanded?s.items.map(i=>{
        const reason=i.state==='failed'?(reasons[i.reason]||'接续失败，请查看原任务')
          :i.state==='skipped'?(reasons[i.reason]||'已跳过'):'';
        const retry=i.state==='failed'&&window.NX_RESUME_POLICY.retryable.includes(i.reason);
        const status={waiting:'等待中',acting:'接续中'}[i.state]||(!['done','failed','skipped'].includes(i.state)?'处理中':'');
        const accessibleState=i.state==='done'?'成功':i.state==='failed'?'失败':i.state==='skipped'?'已跳过':status;
        const hint=`${i.title} · ${accessibleState}${reason&&reason!==accessibleState?' · '+reason:''}`;
        return `<div class="resume-task-row"><button class="resume-task" data-action="open-resume-task" data-value="${esc(i.thread_id)}" title="${esc(hint)}" aria-label="${esc(hint)}"><span class="resume-task-copy"><strong>${esc(i.title)}</strong>${reason?`<small class="${i.state==='failed'?'resume-failure-reason':''}">· ${esc(reason)}</small>`:''}</span>${status?`<em class="resume-progress">${esc(status)}</em>`:''}${icon('external')}</button>${retry?`<button class="resume-retry" data-action="retry-resume-task" data-session="${esc(s.id)}" data-value="${esc(i.thread_id)}">重新接续</button>`:''}</div>`;
      }).join(''):'';
      const progress=`${done}/${s.items.length}`;
      const hint=`${account?name(account):'账号接力'} · ${time} · ${progress}${failed?` · ${failed} 项需要查看`:''}`;
      return `<section class="resume-session"><button class="resume-summary" data-action="resume-toggle" data-value="${esc(s.id)}" aria-expanded="${expanded}" title="${esc(hint)}" aria-label="${esc(hint)}"><span>${esc(account?name(account):'账号接力')} · ${esc(time)}</span><strong class="resume-progress mono">${progressMarkup(progress,s.items.some(i=>i.state==='failed'&&!attention(i)))}</strong>${icon('chevron')}</button>${expanded?`<div class="resume-tasks">${rows}</div>`:''}</section>`;
    };
    return groups.filter(([,items])=>items.length).map(([label,items])=>`<section class="resume-group"><div class="resume-group-head"><strong>${label}</strong><span>${items.length} 次</span></div>${items.map(row).join('')}</section>`).join('');
  }
  return resumeContent();
};
