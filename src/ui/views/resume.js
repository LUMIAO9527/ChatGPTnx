/* Pure view: state in, HTML out. */
'use strict';
window.NXViews ??= {};
window.NXViews.resume = context => {
  const {data,ui,esc,icon,name,now} = context;
  function resumeContent() {
    const sessions=[...(ui.resumeDetails||[])].sort((a,b)=>b.updated_at-a.updated_at);
    const reasons={
      automatic_send_unavailable:'自动发送尚未执行，可重新检查',
      user_attachment_present:'保留附件草稿，等待处理',
      input_guard_unavailable:'安全输入暂不可用',
      input_guard_timeout:'输入准备超时',
      input_focus_changed:'桌面焦点已变化',
      composer_selection_unavailable:'无法建立安全插入点',
      selection_not_collapsed:'输入区存在选中文本',
      invalid_resume_message:'接续消息无效',
      action_outcome_unknown:'已操作，结果未确认；请查看原任务',
      composer_in_use:'正在编辑，已暂停接续',
      account_guard_unavailable:'无法核对当前账号',
      desktop_not_running:'等待打开桌面端',
      desktop_window_ambiguous:'多个任务入口冲突，无法确定窗口',
      desktop_location_unreadable:'无法读取桌面窗口内容',
      task_identity_unavailable:'无法确认任务编号对应关系',
      task_navigation_unconfirmed:'原任务打开结果未确认，尚未发送',
      target_changed:'原任务页面已变化',
      invalid_saved_state:'记录状态异常',
      title_unavailable_or_ambiguous:'无法确认原任务页面',
      user_draft_present:'草稿已保留，等待输入区就绪',
      composer_unavailable:'未定位到输入框，已暂停',
      composer_state_unknown:'无法确认输入框状态，待确认',
      desktop_bridge_unavailable:'桌面接续接口尚未就绪',
      desktop_task_not_idle:'等待原任务结束运行',
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
      native_continue_ambiguous:'页面有多个继续按钮',
      target_not_visible:'原任务页面未显示',
      history_unavailable:'任务状态暂不可读',
      resume_expired:'接续等待已过期',
      continuation_disabled:'自动接续已关闭',
      unsnapshotted_active_turn:'无法确认任务在切号前运行',
      unrelated_failure:'任务因其他原因停止',
      task_already_running:'任务已在运行',
      newer_turn:'已有新回合',
      new_turn_observed:'已在原任务启动新回合'
      ,resume_auth_failed:'消息已送达，账号认证失败（401）'
      ,resumed_turn_failed:'消息已送达，后续回合失败'
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
        const reason=i.reason?(reasons[i.reason]||(i.state==='skipped'?'已跳过':'请查看原任务')):'';
        const retry=i.state==='failed'&&window.NX_RESUME_POLICY.retryable.includes(i.reason);
        const progress=i.state==='done'?'1/1':'0/1';
        const hint=`${i.title} · ${progress}${reason?' · '+reason:''}`;
        return `<div class="resume-task-row"><button class="resume-task" data-action="open-resume-task" data-value="${esc(i.thread_id)}" title="${esc(hint)}" aria-label="${esc(hint)}"><span class="resume-task-copy"><strong>${esc(i.title)}</strong>${reason?`<small>· ${esc(reason)}</small>`:''}</span><em class="resume-progress mono">${progressMarkup(progress,i.state==='failed'&&!attention(i))}</em>${icon('external')}</button>${retry?`<button class="resume-retry" data-action="retry-resume-task" data-session="${esc(s.id)}" data-value="${esc(i.thread_id)}">重新接续</button>`:''}</div>`;
      }).join(''):'';
      const progress=`${done}/${s.items.length}`;
      const hint=`${account?name(account):'账号接力'} · ${time} · ${progress}${failed?` · ${failed} 项需要查看`:''}`;
      return `<section class="resume-session"><button class="resume-summary" data-action="resume-toggle" data-value="${esc(s.id)}" aria-expanded="${expanded}" title="${esc(hint)}" aria-label="${esc(hint)}"><span>${esc(account?name(account):'账号接力')} · ${esc(time)}</span><strong class="resume-progress mono">${progressMarkup(progress,s.items.some(i=>i.state==='failed'&&!attention(i)))}</strong>${icon('chevron')}</button>${expanded?`<div class="resume-tasks">${rows}</div>`:''}</section>`;
    };
    return groups.filter(([,items])=>items.length).map(([label,items])=>`<section class="resume-group"><div class="resume-group-head"><strong>${label}</strong><span>${items.length} 次</span></div>${items.map(row).join('')}</section>`).join('');
  }
  return resumeContent();
};
