/* Account vault views: pure, state in, HTML out (same contract as accounts.js).
 *
 * Nothing here ever receives a plaintext password through the poll payload. The
 * row asks for it one account at a time and drops it again on collapse, so the
 * secret only exists while the detail sheet is open.
 */
'use strict';
window.NXVault = (() => {
  const LAST = {
    phone: '需手机号验证',
    email_code: '需邮箱验证码',
    human_check: '需人机验证',
    wrong_password: '密码待更新',
    otp_rejected: '2FA 待更新',
    timeout: '上次超时',
    stopped: '上次已停止',
    identity_mismatch: '登录的不是这个账号'
  };

  function find(data, email) {
    return (data.vault || []).find(entry => entry && entry.email.toLowerCase() === String(email||'').toLowerCase()) || null;
  }

  function hasSecret(entry) {
    return !!(entry && entry.has_secret);
  }

  function stateText(entry) {
    if (!entry) return '未保存';
    if(entry.has_exchange&&!entry.has_secret)return '待兑换 2FA';
    if(!entry.has_password&&!entry.has_secret)return '未保存';
    const last = entry.last_result && LAST[entry.last_result];
    if (last) return last;
    if(entry.secret_source==='enrolled')return 'NX 验证器';
    if (entry.has_password && entry.has_secret) return '已保存';
    return entry.has_password ? '仅密码' : '仅 2FA';
  }

  function codeText(entry) {
    if (!hasSecret(entry)) return '未绑定';
    const code = String(entry.code || '');
    return code.length === 6 ? code.slice(0, 3) + ' ' + code.slice(3) : '······';
  }

  function remainText(entry) {
    return hasSecret(entry) && Number.isFinite(entry.remain) ? entry.remain + 's' : '';
  }

  function summary(c, email) {
    const entry = find(c.data, email);
    const stale = entry && entry.last_result && LAST[entry.last_result];
    return { text: stateText(entry), tone: stale ? 'danger' : '' };
  }

  /* Detail sheet: one collapsible row that opens three lines. */
  function row(c, account) {
    const { data, ui, esc, icon } = c;
    const entry = find(data, account.email);
    const expanded = ui.vaultExpanded.has(account.email);
    const revealing = ui.vaultReveal && ui.vaultReveal.email === account.email;
    const masked = revealing ? (ui.vaultReveal.value || '—')
      : entry && entry.has_password ? '••••••••' : '—';
    const remaining = remainText(entry);
    const expiring = hasSecret(entry) && Number.isFinite(entry.remain) && entry.remain <= 5;
    const summaryText = summary(c, account.email);

    const line = (label, value, controls, extra = '') =>
      `<div class="vault-line"><span class="vault-label">${esc(label)}</span>` +
      `<strong class="mono${extra}">${esc(value)}</strong>${controls}</div>`;

    const copy = field =>
      `<button class="control secondary control--small" data-action="vault-copy" ` +
      `data-email="${esc(account.email)}" data-value="${field}">复制</button>`;

    const body = expanded
      ? `<div id="vault-details" class="vault-details" role="region" aria-label="密码与 2FA">` +
        line('邮箱', account.email, copy('email')) +
        line('密码', masked,
          entry && entry.has_password
            ? `<button class="control secondary control--small" data-action="vault-reveal" ` +
              `data-email="${esc(account.email)}">${revealing ? '隐藏' : '显示'}</button>${copy('password')}`
            : '') +
        line('2FA', codeText(entry),
          `${remaining ? `<small class="vault-remain${expiring ? ' danger' : ''}">${esc(remaining)}</small>` : ''}` +
          `${hasSecret(entry) ? copy('code') : ''}`,
          expiring ? ' danger' : '') +
        `<div class="vault-foot"><button class="link-row" data-action="vault-edit" data-email="${esc(account.email)}"><span>编辑登录资料</span>${icon('chevron')}</button>` +
        `<button class="link-row" data-action="mfa-open" data-email="${esc(account.email)}"><span>更换验证器</span>${icon('chevron')}</button>` +
        `<button class="link-row" data-action="vault-page">` +
        `${icon('key')}<span>管理账号库</span>${icon('chevron')}</button></div>` +
        `</div>`
      : '';

    return `<div class="detail-vault detail-item control-container${expanded ? ' is-open' : ''}" data-disclosure="vault:${esc(account.email)}">` +
      `<button class="detail-line detail-action vault-summary control-header" data-action="toggle-vault" ` +
      `data-email="${esc(account.email)}" aria-expanded="${expanded}" aria-controls="vault-details">` +
      `<span>密码与 2FA</span><span class="right">` +
      `<strong${summaryText.tone ? ` class="${summaryText.tone}"` : ''}>${esc(summaryText.text)}</strong>` +
      `${icon('chevron')}</span></button>${body}</div>`;
  }

  const input=(c,id,label,value='',type='text',placeholder='',readonly=false)=>
    `<label class="vault-field" for="${id}"><span>${c.esc(label)}</span><input class="field" id="${id}" type="${type}" value="${c.esc(value)}" placeholder="${c.esc(placeholder)}" ${readonly?'readonly':''} autocomplete="off" spellcheck="false"></label>`;

  function page(c) {
    const {data,ui,esc,disabled}=c,entries=data.vault||[];
    const cards=entries.map(entry=>`<div class="vault-card collection-row">
      <button class="vault-card-copy vault-card-edit" data-action="vault-edit" data-email="${esc(entry.email)}"><strong>${esc(entry.label||entry.email)}</strong><small>${esc(stateText(entry))}</small></button>
      <button class="control secondary control--small" data-action="vault-login" data-email="${esc(entry.email)}" ${disabled()}>${data.accounts.some(a=>a.email.toLowerCase()===entry.email.toLowerCase())?'重登':'登录'}</button>
      <button class="control ${ui.vaultForget===entry.email?'danger control--confirmation':'secondary'} control--small" data-action="vault-forget" data-email="${esc(entry.email)}">${ui.vaultForget===entry.email?'确认':'删除'}</button></div>`).join('');
    return `<div class="vault-content">${data.vault_error?`<p class="field-feedback" role="alert">${esc(data.vault_error)}</p>`:''}
      <div class="vault-entry-actions"><button class="control control--large secondary" data-action="vault-edit">添加登录资料</button>
      <button class="control control--large secondary" data-action="authenticator-open">导入手机验证器</button></div>
      <div class="vault-list">${cards||'<p class="note">账号库为空，添加资料或批量导入。</p>'}</div>
      <section class="vault-import"><h3 class="settings-heading">批量导入</h3>
      <textarea class="field" id="vault-import" rows="3" spellcheck="false" placeholder="邮箱----密码----2FA 资料----兑换链接（可选）">${esc(ui.vaultDraft||'')}</textarea>
      <button class="control control--large primary" data-action="vault-import" ${(ui.vaultDraft||'').trim()?'':'disabled'}>导入</button>
      <p class="note">一行一个账号，支持连续四个短横线、竖线或制表符分隔。2FA 可填密钥、兑换码或完整链接。</p></section></div>`;
  }

  function editor(c) {
    const {ui,esc}=c,d=ui.vaultEditor||{},entry=find(c.data,d.email);
    return `<div class="vault-form">${input(c,'vault-email','邮箱',d.email,'email','',!!d.locked)}
      ${input(c,'vault-password','密码',d.password,'password',entry?.has_password?'留空保留已存密码':'登录密码')}
      ${input(c,'vault-material','2FA 资料',d.material,'password',entry?.has_secret?'留空保留已存密钥':'密钥、兑换码或完整链接')}
      ${input(c,'vault-url','兑换链接',d.exchange_url,'url','可选')}
      <p class="note">${entry?.has_exchange?'已保存兑换资料，可复制后到对应网站获取验证码。':'密钥由 NX 在本机计算验证码；兑换资料按原样保存。'}</p>
      ${entry?.has_exchange?`<div class="vault-form-actions"><button class="control secondary control--small" data-action="vault-open-exchange" data-email="${esc(d.email)}">打开兑换网站</button><button class="control secondary control--small" data-action="vault-copy" data-email="${esc(d.email)}" data-value="exchange_code">复制兑换码</button><button class="control secondary control--small" data-action="vault-copy" data-email="${esc(d.email)}" data-value="exchange_url">复制链接</button></div>`:''}
      ${entry?.has_recovery?`<button class="control secondary control--small" data-action="vault-copy" data-email="${esc(d.email)}" data-value="recovery_codes">复制恢复码</button>`:''}
      <label class="vault-field" for="vault-recovery"><span>恢复码</span><textarea class="field" id="vault-recovery" rows="2" placeholder="可选，留空保留已存资料">${esc(d.recovery_codes||'')}</textarea></label>
      <span id="form-error" class="field-feedback" role="alert"></span></div>`;
  }

  function mfa(c) {
    const {data,ui,esc}=c,d=ui.mfa||{},email=ui.email,entry=find(data,email);
    const pending=(data.mfa_pending||[]).find(p=>p.token===d.token),current=data.current?.toLowerCase()===email?.toLowerCase();
    const code=pending?.code||d.code||'',remaining=pending?.remain??d.remain;
    const old=entry?.has_secret?`<div class="vault-current-code"><span>当前验证器</span><strong class="mono">${esc(codeText(entry))}</strong><button class="control secondary control--small" data-action="vault-copy" data-email="${esc(email)}" data-value="code">复制</button></div>`:'';
    if(!current)return `<div class="vault-form"><p class="note">先切换到 ${esc(email)}，再打开 ChatGPT 的安全设置。</p><button class="control control--large secondary" data-action="switch" data-email="${esc(email)}">切换到此账号</button></div>`;
    if(!d.token)return `<div class="vault-form">${old}<ol class="vault-steps"><li>打开 ChatGPT 设置 → 安全与登录 → 验证器应用。</li><li>移除旧验证器后重新添加，复制设置页提供的手动密钥。</li></ol>
      ${input(c,'mfa-secret','新的验证器密钥',d.secret,'password','粘贴设置页给出的密钥')}
      <span id="form-error" class="field-feedback" role="alert"></span></div>`;
    if(d.expires_at&&d.expires_at*1000<=Date.now())return `<div class="vault-form"><p class="note">本次密钥预览已过期，请重新录入设置页提供的密钥。</p><button class="control secondary control--large" data-action="mfa-open" data-email="${esc(email)}">重新录入</button></div>`;
    return `<div class="vault-form"><p class="note">将下方验证码填入 ChatGPT 的验证器设置。</p>
      <div class="vault-enroll-code"><strong class="mono">${esc(code.replace(/(\d{3})(\d{3})/,'$1 $2'))}</strong><span>${esc(remaining??'')}s</span><button class="control secondary control--small" data-action="mfa-copy">复制</button></div>
      <label class="vault-field" for="mfa-recovery"><span>恢复码（设置页提供时填写）</span><textarea class="field" id="mfa-recovery" rows="2">${esc(d.recovery_codes||'')}</textarea></label>
      <label class="vault-confirm"><input id="mfa-confirm" type="checkbox" ${d.confirmed?'checked':''}>我已在 ChatGPT 完成验证码确认</label>
      <p class="note">确认后，将新密钥保存到 ${esc(email)}。</p><span id="form-error" class="field-feedback" role="alert"></span></div>`;
  }

  function authenticator(c) {
    const {ui,esc}=c,transfer=ui.authTransfer;
    if(!transfer)return `<div class="vault-form"><ol class="vault-steps"><li>手机打开 Google Authenticator，选择“转移账号 → 导出账号”。</li><li>勾选要导入 NX 的账号，将二维码图片传到这台电脑。</li><li>一次选择本组全部图片，核对账号后导入。</li></ol>
      <button class="control control--large primary" data-action="authenticator-choose">选择二维码图片</button>
      <details class="authenticator-paste"><summary>粘贴验证器导出链接</summary><textarea class="field" id="authenticator-text" rows="3" spellcheck="false" placeholder="otpauth-migration://… 或 otpauth://…">${esc(ui.authText||'')}</textarea><button class="control secondary control--large" data-action="authenticator-preview">读取链接</button></details>
      <span id="form-error" class="field-feedback" role="alert"></span></div>`;
    return `<div class="vault-form"><p class="note">为每个验证器选择对应的账号。导入后，手机和 NX 可同时生成验证码。</p><div class="authenticator-list">${transfer.rows.map(row=>`<label class="vault-field"><span>${esc(row.name||row.issuer||'验证器账号')}</span><select class="field auth-map" data-id="${esc(row.id)}"><option value="">忽略此条</option>${transfer.emails.map(email=>`<option value="${esc(email)}" ${row.email===email?'selected':''}>${esc(email)}</option>`).join('')}</select>${row.replaces?'<small class="note">将更新此账号已保存的验证器。</small>':''}</label>`).join('')}</div><span id="form-error" class="field-feedback" role="alert"></span></div>`;
  }

  function cleanup(c) {
    const labels={cookies:['内置网页 Cookie','清除桌面端内置网页的登录状态'],storage:['内置网站存储','清除内置网页保存的本地资料'],cache:['页面缓存','清除内置页面与脚本缓存']};
    return `<div class="vault-form"><p class="note">清理时会关闭并重新打开 ChatGPT。若登录页面在 Chrome 或 Edge 打开，请在对应浏览器的网站设置中清理 auth.openai.com 和 chatgpt.com 的数据。</p>
      <div class="settings-list">${Object.entries(labels).map(([key,[title,hint]])=>`<div class="vault-cleanup-row"><span><strong>${title}</strong><small>${hint}</small></span>${c.selectionButton({label:title,checked:c.ui.storeGroups.has(key),action:'store-toggle',email:key})}</div>`).join('')}</div>
      </div>`;
  }

  return { find, stateText, codeText, summary, row, page, editor, mfa, cleanup, authenticator };
})();
