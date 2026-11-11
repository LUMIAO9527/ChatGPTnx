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

    const tool = (action,symbol,label,attrs='') => actionButton({action,content:icon(symbol),
      label,title:label,size:'small',iconOnly:true,className:'tool',
      attrs:`data-email="${esc(account.email)}" ${attrs}`});
    const copy = field => tool('vault-copy','copy','复制'+({email:'邮箱',password:'密码',code:'验证码'})[field],`data-value="${field}"`);
    const editing=ui.vaultEditor?.email===account.email;
    const extra=editing?editor(c):ui.mfa?`<div class="vault-inline-form">${mfa(c).body}<div class="vault-inline-actions">${mfa(c).foot}${actionButton({action:'vault-cancel',content:'取消',size:'small',className:'secondary'})}</div></div>`:ui.authTransfer?`<div class="vault-inline-form">${authenticator(c).body}${authenticatorActions(c)}${c.actionButton({action:'vault-cancel',content:'取消',size:'small',className:'secondary'})}</div>`:'';

    const body = expanded
      ? `<div id="vault-details" class="vault-details" role="region" aria-label="密码与 2FA">` +
        line('邮箱', account.email, copy('email')) +
        `<div class="vault-line"><span class="vault-label">密码</span>`+
          (entry?.has_password?`<button class="vault-value control--embedded mono" data-action="vault-reveal" data-email="${esc(account.email)}" aria-label="${revealing?'隐藏':'显示'}密码" title="${revealing?'隐藏密码':'显示密码 3 秒'}"><strong>${esc(masked)}</strong></button>`:`<strong>未保存</strong>`)+
          tool('vault-edit','edit','修改登录资料')+(entry?.has_password?copy('password'):'')+`</div>`+
        line('2FA', codeText(entry),
          `${remaining ? `<small class="vault-remain${expiring ? ' danger' : ''}">${esc(remaining)}</small>` : ''}` +
          `${actionButton({action:'mfa-open',content:hasSecret(entry)?'更换':'导入',label:hasSecret(entry)?'更换验证器':'导入验证器',size:'small',className:'secondary',attrs:`data-email="${esc(account.email)}"`})}${hasSecret(entry) ? copy('code') : ''}`,
          expiring ? ' danger' : '') +
        extra+
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

  function savedAccounts(c) {
    const entries=(c.data.vault||[]).filter(entry=>!c.data.accounts.some(a=>a.email.toLowerCase()===entry.email.toLowerCase()));
    if(!entries.length)return '';
    const rows=window.NXComponents.pagedList(c,'saved-login',entries,entry=>`<div class="saved-login-row collection-row"><span class="collection-name" title="${c.esc(entry.email)}">${c.esc(entry.label||entry.email)}</span>${c.actionButton({action:'vault-login',content:'登录',size:'small',className:'secondary',attrs:`data-email="${c.esc(entry.email)}" ${c.disabled()}`})}</div>`,{label:'已存登录资料'});
    return window.NXSettingsContent.disclosure(c,'saved-login','使用已存资料',rows,String(entries.length));
  }

  function authenticatorActions(c) {
    return `<div class="vault-inline-actions">${c.actionButton({action:'authenticator-choose',content:'选择二维码',size:'small',className:'secondary'})}${c.actionButton({action:'authenticator-commit',content:'导入',size:'small',tone:'primary',attrs:c.ui.authTransfer?.rows.some(row=>row.email)?'':'disabled'})}</div>`;
  }

  function imports(c) {
    const phone=authenticator(c);
    const batch=`<div class="vault-import"><textarea class="field" id="vault-import" rows="3" spellcheck="false" aria-label="登录资料" placeholder="邮箱----密码----2FA（可选）">${c.esc(c.ui.vaultDraft||'')}</textarea><p class="note">每行一个账号。</p>${c.actionButton({action:'vault-import',content:'导入',size:'small',tone:'primary',attrs:(c.ui.vaultDraft||'').trim()?'':'disabled'})}</div>`;
    return window.NXSettingsContent.disclosure(c,'authenticator-import','导入手机 2FA',`<div class="vault-form">${phone.body}${authenticatorActions(c)}</div>`)
      +window.NXSettingsContent.disclosure(c,'credential-import','导入登录资料',batch);
  }

  function editor(c) {
    const {ui,esc}=c,d=ui.vaultEditor||{},entry=find(c.data,d.email);
    const more=`${input(c,'vault-url','兑换链接',d.exchange_url,'url','可选')}
      ${entry?.has_exchange?`<div class="vault-form-actions"><button class="control secondary control--small" data-action="vault-open-exchange" data-email="${esc(d.email)}">打开兑换页</button><button class="control secondary control--small" data-action="vault-copy" data-email="${esc(d.email)}" data-value="exchange_code">复制兑换码</button></div>`:''}
      <label class="vault-field" for="vault-recovery"><span>恢复码</span><textarea class="field" id="vault-recovery" rows="2" placeholder="${entry?.has_recovery?'留空保留已存恢复码':'可选'}">${esc(d.recovery_codes||'')}</textarea></label>
      ${entry?.has_recovery?`<button class="control secondary control--small" data-action="vault-copy" data-email="${esc(d.email)}" data-value="recovery_codes">复制恢复码</button>`:''}
      ${entry?`<button class="control control--small ${c.ui.vaultForget===d.email?'control--confirmation danger':'secondary'}" data-action="vault-forget" data-email="${esc(d.email)}">${c.ui.vaultForget===d.email?'确认移除':'移除登录资料'}</button>`:''}`;
    return `<div class="vault-form vault-inline-form">${input(c,'vault-password','密码',d.password,'password',entry?.has_password?'留空保留已存密码':'登录密码')}
      ${input(c,'vault-material','2FA 资料',d.material,'password',entry?.has_secret?'留空保留已存密钥':'密钥、兑换码或完整链接')}
      ${window.NXSettingsContent.disclosure(c,'credential-more','其他资料',more)}
      <span id="form-error" class="field-feedback" role="alert"></span>
      <div class="vault-inline-actions">${c.actionButton({action:'vault-save',content:'保存',size:'small',tone:'primary'})}${c.actionButton({action:'vault-cancel',content:'取消',size:'small',className:'secondary'})}</div></div>`;
  }

  function mfa(c) {
    const {data,ui,esc}=c,d=ui.mfa||{},email=ui.email,entry=find(data,email);
    const pending=(data.mfa_pending||[]).find(p=>p.token===d.token),current=data.current?.toLowerCase()===email?.toLowerCase();
    const code=pending?.code||d.code||'',remaining=pending?.remain??d.remain;
    const button=(action,content,attrs='')=>c.actionButton({action,content,attrs,size:'small',tone:'primary'});
    const old='';
    const phone=c.actionButton({action:'authenticator-choose',content:'从手机导入',size:'small',className:'secondary'});
    const form=(content,foot)=>({body:`<div class="vault-form">${phone}${content}<span id="form-error" class="field-feedback" role="alert"></span></div>`,foot});
    if(!current)return form(
      `<p class="note">绑定新密钥需先切换到此账号。</p>`,
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

  return { find, stateText, codeText, summary, row, editor, mfa, authenticator, imports, savedAccounts };
})();
