/* Shared controls for the single Relay panel. */
'use strict';
window.NXComponents = (() => {
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const paths = {
    close:'M4 4l10 10M14 4L4 14', arrow:'M4 9h10M10 4l5 5-5 5', back:'M14 9H4M8 4L3 9l5 5',
    more:'M4 9h.01M9 9h.01M14 9h.01', refresh:'M14.6 6A6 6 0 1 0 15 11M15 2v4h-4',
    plus:'M9 3v12M3 9h12', chart:'M3 15V9M9 15V3M15 15V6', check:'M3 9l4 4 8-8',
    chevron:'M7 4l5 5-5 5', baton:'M6 11l5-6a2 2 0 0 1 3 3l-5 6a2 2 0 0 1-3-3Z',
    archive:'M3 6h12v9H3zM2 3h14v3H2zM7 9h4', user:'M12 5a3 3 0 1 1-6 0 3 3 0 0 1 6 0M3 16v-2a6 6 0 0 1 12 0v2',
    edit:'M11 3l4 4M3 15l4-1L15 6 12 3 3 12v3', info:'M9 8v5M9 5h.01M16 9A7 7 0 1 1 2 9a7 7 0 0 1 14 0',
    expand:'M3 7V3h4M11 3h4v4M15 11v4h-4M7 15H3v-4', stack:'M9 2l7 4-7 4-7-4 7-4M2 9l7 4 7-4M2 12l7 4 7-4',
    external:'M10 3h5v5M15 3L8 10M7 4H3v11h11v-4', clock:'M9 5v4l3 2M16 9A7 7 0 1 1 2 9a7 7 0 0 1 14 0',
    keyboard:'M2 5h14v9H2zM4 8h1M7 8h1M10 8h1M13 8h1M4 11h7M13 11h1',
    settings:'M9 6.5A2.5 2.5 0 1 1 9 11.5 2.5 2.5 0 0 1 9 6.5ZM9 2v2M9 14v2M2 9h2M14 9h2M4 4l1.4 1.4M12.6 12.6 14 14M14 4l-1.4 1.4M5.4 12.6 4 14'
  };
  const icon = (n, c='') => `<svg class="icon ${c}" viewBox="0 0 18 18" aria-hidden="true"><path d="${paths[n] || paths.info}"></path></svg>`;
  const tool = (i, action, label, attrs='', iconClass='') => `<button class="tool" data-action="${action}" aria-label="${esc(label)}" ${attrs}>${icon(i,iconClass)}</button>`;

  const system = [
    {key:'autostart', label:'开机自启'},
  ];
  const automation = [
    {key:'auto_relay', label:'额度耗尽时自动接力'},
    {key:'task_continuation', label:'切号后自动接续任务'},
  ];
  const notifications = [
    {key:'notify_credential', label:'凭据失效提醒'},
    {key:'notify_low', label:'低额度提醒'},
    {key:'notify_reset_expiry', label:'重置次数到期提醒'},
  ];
  function segmented({label, action, options, value, key, className=''}) {
    const buttons = options.map(([id, text]) => `<button data-action="${esc(action)}" data-value="${esc(id)}" ${key ? `data-key="${esc(key)}"` : ''} aria-pressed="${String(value)===String(id)}" class="${String(value)===String(id)?'active':''}">${esc(text)}</button>`).join('');
    return `<div class="segmented ${className}" role="group" aria-label="${esc(label)}">${buttons}</div>`;
  }
  function settingRow(item, settings) {
    const {key, label, options} = item;
    const copy = `<span>${esc(label)}</span>`;
    if (options) {
      const className = `setting-choice ${key==='appearance'?'appearance-choice':''}`;
      return `<div class="${className}">${copy}${segmented({label, action:'pref', key, options, value:settings[key]??options[0][0], className:'compact'})}</div>`;
    }
    return `<div class="toggle-line">${copy}<button class="switch" role="switch" aria-label="${esc(label)}" aria-checked="${!!settings[key]}" data-action="toggle" data-key="${esc(key)}"><i></i></button></div>`;
  }
  const systemSettings = settings => system.map(item=>settingRow(item,settings)).join('');
  const autoRelaySetting = settings => settingRow(automation[0],settings);
  const taskContinuationSetting = settings => settingRow(automation[1],settings);
  function notificationSettings(settings) {
    return notifications.map(item=>settingRow(item,settings)).join('');
  }
  const planLabel = value => ({plus:'Plus',prolite:'Pro',pro:'Pro',free:'Free',go:'Go',team:'Team',business:'Business',enterprise:'Enterprise',edu:'Edu'}[value] || (typeof value==='string'&&value!=='unknown'?'其他':'待查询'));
  const accountName = account => account?.alias || account?.email?.split('@')[0] || '未选择账号';
  // One glyph and one avatar recipe across all product surfaces.
  const brandMark = (className='') => `<span class="mark ${className}" role="img" aria-label="n×" title="n× · 多个账号，一次接力">${window.NX_BRAND_MARK||''}</span>`;
  const avatar = (account,className='') => `<span class="avatar ${className}" aria-hidden="true">${esc(Array.from(accountName(account))[0]||'·')}</span>`;
  function accountIdentity(account,extra='') {
    const label=accountName(account);
    return `<div class="identity">${avatar(account)}<div class="identity-copy"><span class="identity-title"><strong title="${esc(label)}">${esc(label)}</strong><span class="badge">${account?.archived?'已归档':esc(planLabel(account?.plan))}</span></span><small>${esc(extra||account?.email||'')}</small></div></div>`;
  }
  // A missing balance is not zero. Keep legacy snapshots readable and never format objects/NaN.
  function creditValue(account) {
    if (!readableQuota(account)) return '暂不可用';
    const info=account.credit_info;
    if(info?.status==='unlimited')return '不限额';
    if(info?.status==='invalid')return '数据异常';
    const balance=info?.balance ?? account.credits;
    if(balance===null||balance===undefined||balance==='')return '未提供';
    if(!['string','number'].includes(typeof balance)||!/^\d+(?:\.\d+)?$/.test(String(balance).trim())||!Number.isFinite(Number(balance)))return '数据异常';
    return String(balance).trim();
  }
  // Every choice list uses the same hierarchy: name first; membership and quotas second.
  function accountChoice(account, currentEmail, {showCurrent=true}={}) {
    const label=accountName(account);
    return `${avatar(account)}<span class="account-choice-copy"><span class="account-title"><strong title="${esc(label)}">${esc(label)}</strong>${showCurrent&&account.email===currentEmail?'<span class="current-chip">当前</span>':''}</span><span class="account-secondary"><span class="account-plan">${esc(planLabel(account.plan))}</span><span class="choice-quotas">${quotaSummary(account)}</span></span></span>`;
  }
  const readableQuota = account => account?.ok === true ||
    ['network','timeout','cancelled','schema','response_too_large',429,408,'-32603',-32603,'query_policy_unavailable'].includes(account?.error_code) ||
    (Number.isInteger(account?.error_code) && account.error_code>=500 && account.error_code<=599);
  const displayWindows = account => readableQuota(account) && Array.isArray(account?.windows) &&
    account.windows.every(w => w && Number.isFinite(w.used) && w.used>=0 && w.used<=100 &&
      Number.isFinite(w.resets_at) && w.resets_at>0 && w.resets_at<253402300800) ? account.windows : [];
  const remaining = window => Math.round((100-window.used)*10)/10;
  const quotaSummary = account => {
    const windows=displayWindows(account);
    return windows.length ? windows.slice(0,2).map(w=>`<span class="${remaining(w)<=10?'danger':''}"><em>${esc(w.label)}</em><strong class="mono">${remaining(w)}%</strong></span>`).join('')
      : '<span class="unavailable">额度暂不可用</span>';
  };
  function quotaColumns(account) {
    const windows=displayWindows(account);
    const cells=windows.map(w=>{
      return `<span class="roster-quota ${remaining(w)<=10?'danger':''}"><em>${esc(w.label)}</em><strong class="mono">${remaining(w)}%</strong></span>`;
    }).join('');
    return `<span class="roster-quotas" style="--quota-count:${Math.max(1,windows.length)}" aria-label="${esc(windows.length?'剩余额度':'额度暂不可用')}" title="${esc(windows.length?'剩余额度':'额度暂不可用')}">${cells||'<span class="unavailable">额度暂不可用</span>'}</span>`;
  }
  return {esc, icon, tool, segmented, systemSettings, autoRelaySetting, taskContinuationSetting,
          notificationSettings, quotaSummary, quotaColumns, remaining, displayWindows, readableQuota, planLabel, accountName, accountChoice, creditValue, brandMark, avatar, accountIdentity};
})();
