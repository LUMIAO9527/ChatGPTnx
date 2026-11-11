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
    const { data, ui, esc, icon, actionButton } = c;
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
        `<div class="vault-detail-actions">${[
          ['vault-edit','编辑资料','编辑登录资料',account.email],
          ['mfa-open','换绑 2FA','更换验证器',account.email],
          ['vault-page','账号库','管理账号库']
        ].map(([action,content,label,email])=>actionButton({
          action,content,label,size:'small',className:'secondary',
          attrs:email?`data-email="${esc(email)}"`:''
        })).join('')}</div>` +
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
      <div class="vault-entry-actions"><button class="control control--large secondary" data-action="vault-edit">添加资料</button>
      <button class="control control--large secondary" data-action="authenticator-open">导入 2FA</button></div>
      <div class="vault-list">${cards||'<p class="note">暂无登录资料</p>'}</div>
      <section class="vault-import"><h3 class="settings-heading">批量导入</h3>
      <textarea class="field" id="vault-import" rows="3" spellcheck="false" placeholder="邮箱----密码----2FA 资料----兑换链接（可选）">${esc(ui.vaultDraft||'')}</textarea>
      <button class="control control--large primary" data-action="vault-import" ${(ui.vaultDraft||'').trim()?'':'disabled'}>导入</button>
      <p class="note">每行一个账号。2FA 可填密钥、兑换码或链接。</p></section></div>`;
  }

  function editor(c) {
    const {ui,esc}=c,d=ui.vaultEditor||{},entry=find(c.data,d.email);
    return `<div class="vault-form">${input(c,'vault-email','邮箱',d.email,'email','',!!d.locked)}
      ${input(c,'vault-password','密码',d.password,'password',entry?.has_password?'留空保留已存密码':'登录密码')}
      ${input(c,'vault-material','2FA 资料',d.material,'password',entry?.has_secret?'留空保留已存密钥':'密钥、兑换码或完整链接')}
      ${input(c,'vault-url','兑换链接',d.exchange_url,'url','可选')}
      ${entry?.has_exchange?`<div class="vault-form-actions"><button class="control secondary control--small" data-action="vault-open-exchange" data-email="${esc(d.email)}">打开兑换页</button><button class="control secondary control--small" data-action="vault-copy" data-email="${esc(d.email)}" data-value="exchange_code">复制兑换码</button><button class="control secondary control--small" data-action="vault-copy" data-email="${esc(d.email)}" data-value="exchange_url">复制链接</button></div>`:''}
      ${entry?.has_recovery?`<button class="control secondary control--small" data-action="vault-copy" data-email="${esc(d.email)}" data-value="recovery_codes">复制恢复码</button>`:''}
      <label class="vault-field" for="vault-recovery"><span>恢复码（可选）</span><textarea class="field" id="vault-recovery" rows="2" placeholder="${entry?.has_recovery?'留空保留已存恢复码':''}">${esc(d.recovery_codes||'')}</textarea></label>
      <span id="form-error" class="field-feedback" role="alert"></span></div>`;
  }

  function mfa(c) {
    const {data,ui,esc}=c,d=ui.mfa||{},email=ui.email,entry=find(data,email);
    const pending=(data.mfa_pending||[]).find(p=>p.token===d.token),current=data.current?.toLowerCase()===email?.toLowerCase();
    const code=pending?.code||d.code||'',remaining=pending?.remain??d.remain;
    const button=(action,content,attrs='')=>c.actionButton({action,content,attrs,size:'large',tone:'primary'});
    const old=entry?.has_secret?`<div class="vault-current-code"><span>当前验证码</span><strong class="mono">${esc(codeText(entry))}</strong><button class="control secondary control--small" data-action="vault-copy" data-email="${esc(email)}" data-value="code">复制</button></div>`:'';
    const form=(content,foot)=>({body:`<div class="vault-form">${content}<span id="form-error" class="field-feedback" role="alert"></span></div>`,foot});
    if(!current)return form(
      `<p class="note">请先切换到 ${esc(email)}。</p>`,
      button('switch','切换到此账号',`data-email="${esc(email)}"`));
    if(!d.token)return form(
      `${old}<p class="note">在 ChatGPT 安全设置中添加验证器，复制新密钥。</p>
      ${input(c,'mfa-secret','新密钥',d.secret,'password','粘贴密钥')}`,
      button('mfa-preview','生成验证码'));
    if(d.expires_at&&d.expires_at*1000<=Date.now())return form(
      `${old}<p class="note">验证码预览已过期。</p>`,button('mfa-reset','重新录入'));
    return form(`${old}<div class="vault-enroll-code"><span>填入 ChatGPT</span>
      <strong class="mono">${esc(code.replace(/(\d{3})(\d{3})/,'$1 $2'))}</strong><span class="vault-remain">${esc(remaining??'')}s</span>
      <button class="control secondary control--small" data-action="mfa-copy">复制</button></div>
      <label class="vault-field" for="mfa-recovery"><span>恢复码（可选）</span><textarea class="field" id="mfa-recovery" rows="2">${esc(d.recovery_codes||'')}</textarea></label>
      <label class="vault-confirm"><input id="mfa-confirm" type="checkbox" ${d.confirmed?'checked':''}>已在 ChatGPT 完成绑定</label>`,
      button('mfa-commit','保存',d.confirmed?'':'disabled'));
  }

  function authenticator(c) {
    const {ui,esc}=c,transfer=ui.authTransfer;
    const paste=window.NXSettingsContent.disclosure(c,'authenticator-link','粘贴导出链接',
      `<textarea class="field" id="authenticator-text" rows="2" spellcheck="false" placeholder="otpauth-migration://…">${esc(ui.authText||'')}</textarea>
      <button class="control secondary control--large" data-action="authenticator-preview">读取链接</button>`,
      '',{className:'authenticator-paste'});
    const content=transfer?`<p class="note">核对每条 2FA 对应的邮箱。</p>
      <div class="authenticator-list">${transfer.rows.map(row=>`<label class="vault-field">
        <span>${esc(row.name||row.issuer||'验证器账号')}${row.replaces?' · 更新':''}</span>
        <select class="field auth-map" data-id="${esc(row.id)}"><option value="">忽略此条</option>${transfer.emails.map(email=>`<option value="${esc(email)}" ${row.email===email?'selected':''}>${esc(email)}</option>`).join('')}</select>
      </label>`).join('')}</div>`:
      `<p class="note">Google Authenticator → 转移账号 → 导出账号。一次选齐全部二维码图片。</p>${paste}`;
    return {
      body:`<div class="vault-form">${content}<span id="form-error" class="field-feedback" role="alert"></span></div>`,
      foot:c.actionButton({action:'authenticator-choose',content:'选择图片',label:'选择二维码图片',size:'large',className:'secondary'})+
        c.actionButton({action:'authenticator-commit',content:'导入',size:'large',tone:'primary',
          attrs:transfer?.rows.some(row=>row.email)?'':'disabled'})
    };
  }

  function cleanup(c) {
    const labels={
      cookies:['Cookie 与连接记录','网页可能需要重新登录'],
      storage:['站点存储','本地存储、会话存储、IndexedDB 等'],
      cache:['缓存','网页、脚本及图形缓存']
    };
    return `<div class="vault-form"><p class="note">范围为 ChatGPT 桌面端内置网页。清理时会重启正在运行的 ChatGPT。</p>
      <div class="settings-list">${Object.entries(labels).map(([key,[title,hint]])=>`<div class="setting-choice">
        <span class="settings-link-copy">${title}<small>${hint}</small></span>
        ${c.selectionButton({label:title,checked:c.ui.storeGroups.has(key),action:'store-toggle',email:key})}
      </div>`).join('')}</div></div>`;
  }

  return { find, stateText, codeText, summary, row, page, editor, mfa, cleanup, authenticator };
})();
