/* Account credentials and local authenticator views. */
'use strict';
window.NXVault = (() => {
  function find(data, email) {
    return (data.vault || []).find(entry =>
      entry && entry.email.toLowerCase() === String(email || '').toLowerCase()) || null;
  }

  function stateText(entry) {
    return entry && (entry.has_password || entry.has_secret) ? '已保存' : '未保存';
  }

  function codeText(entry) {
    if (!entry?.has_secret) return '未绑定';
    const code = String(entry.code || '');
    return code.length === 6 ? code.slice(0, 3) + ' ' + code.slice(3) : '······';
  }

  function summary(c, email) {
    return {text: stateText(find(c.data, email)), tone: ''};
  }

  function editor(c) {
    return `<label class="vault-line credential-field" for="vault-password">
      <span class="vault-label">密码</span>
      <input class="field" id="vault-password" type="password"
        value="${c.esc(c.ui.vaultEditor.password)}" placeholder="账号当前密码"
        aria-describedby="credential-error" autocomplete="off" spellcheck="false">
    </label>`;
  }

  function row(c, account) {
    const {data, ui, esc, icon, actionButton} = c;
    const entry = find(data, account.email);
    const bindingActive = ui.binding?.email === account.email;
    const pending = bindingActive ? window.NXBinding.preview(ui.binding, data) : null;
    const verifier = pending ? {...pending, has_secret: true} : entry;
    const expanded = ui.vaultExpanded.has(account.email);
    const editorState = ui.vaultEditor?.email === account.email ? ui.vaultEditor : null;
    const editing = !!editorState;
    const revealing = ui.vaultReveal?.email === account.email;
    const tool = (action, symbol, label, attrs = '') => actionButton({
      action, content: icon(symbol), label, title: label, size: 'small',
      iconOnly: true, className: 'tool', attrs: `data-email="${esc(account.email)}" ${attrs}`
    });
    const copy = field => tool('vault-copy', 'copy',
      '复制' + {email: '邮箱', password: '密码', code: '验证码'}[field],
      `data-value="${field}"`);
    let password;
    if (editing) {
      password = editor(c);
    } else {
      const edit = entry?.has_password
        ? tool('vault-edit', 'edit', '更新本机密码记录')
        : actionButton({
            action: 'vault-edit', content: '录入', label: '保存账号密码到 NX',
            size: 'small', className: 'secondary', attrs: `data-email="${esc(account.email)}"`
          });
      const value = entry?.has_password
        ? `<div class="vault-value-slot${revealing ? ' is-revealed' : ''}">
            <button type="button" class="vault-value control--embedded mono" data-action="vault-reveal"
              data-email="${esc(account.email)}" aria-label="${revealing ? '隐藏密码' : '显示密码'}">
              <strong>${esc(revealing ? ui.vaultReveal.value : '••••••••')}</strong>
            </button></div>${edit}${copy('password')}`
        : `<strong>未保存</strong>${edit}`;
      password = `<div class="vault-line"><span class="vault-label">密码</span>${value}</div>`;
    }
    const expiring = verifier?.has_secret && verifier.remain <= 5;
    const remaining = verifier?.has_secret && Number.isFinite(verifier.remain)
      ? `<small class="vault-remain${expiring ? ' danger' : ''}">${pending?.expired ? '' : esc(verifier.remain) + 's'}</small>` : '';
    const authenticator = verifier?.has_secret
      ? remaining + (pending ? tool('binding-copy', 'copy', '复制验证码', pending.expired ? 'disabled' : '') : copy('code'))
      : actionButton({
          action: bindingActive ? 'binding-cancel' : 'vault-import-authenticator',
          content: bindingActive ? '收起' : '绑定', size: 'small', className: 'secondary',
          attrs: `data-email="${esc(account.email)}" aria-expanded="${bindingActive}" aria-controls="account-binding-form"`
        });
    const actions = editing ? `<div class="vault-inline-actions">${actionButton({
        action: 'vault-cancel', content: '取消', size: 'large', className: 'secondary',
        attrs: editorState.saving ? 'disabled' : ''
      })}${actionButton({
        action: 'vault-save', content: '保存', size: 'large', tone: 'primary',
        attrs: editorState.saving || !editorState.password ? 'disabled' : ''
      })}</div><span id="credential-error" class="field-feedback" role="alert"></span>` : '';
    const binding = bindingActive ? `<div id="account-binding-form" class="binding-inline">${window.NXBinding.content(c)}</div>` : '';
    const body = expanded ? `<div id="vault-details" class="vault-details${editing ? ' credential-editor' : ''}"
        role="region" aria-label="密码与 2FA">
      <div class="vault-line"><span class="vault-label">邮箱</span>
        <strong class="mono" title="${esc(account.email)}">${esc(account.email)}</strong>${copy('email')}</div>
      ${password}
      <div class="vault-line vault-verifier"><span class="vault-label">2FA</span>
        <strong class="mono vault-code${expiring ? ' danger' : ''}">${esc(codeText(verifier))}</strong>${authenticator}</div>
      ${actions}${binding}</div>` : '';
    return `<div class="detail-vault detail-item control-container${expanded ? ' is-open' : ''}"
        data-disclosure="vault:${esc(account.email)}">
      <button class="detail-line detail-action vault-summary control-header" data-action="toggle-vault"
        data-email="${esc(account.email)}" aria-expanded="${expanded}" aria-controls="vault-details">
        <span>密码与 2FA</span><span class="right"><strong>${esc(stateText(entry))}</strong>${icon('chevron')}</span>
      </button>${body}</div>`;
  }

  function savedAccounts(c) {
    const entries = (c.data.vault || []).filter(entry =>
      !c.data.accounts.some(account => account.email.toLowerCase() === entry.email.toLowerCase()));
    if (!entries.length) return '';
    const rows = window.NXComponents.pagedList(c, 'saved-login', entries, entry =>
      `<div class="saved-login-row collection-row"><span class="collection-name"
        title="${c.esc(entry.email)}">${c.esc(entry.label || entry.email)}</span>${c.actionButton({
          action: 'vault-login', content: '登录', size: 'small', className: 'secondary',
          attrs: `data-email="${c.esc(entry.email)}" ${c.disabled()}`
        })}</div>`, {label: '已存登录资料'});
    return window.NXSettingsContent.disclosure(c, 'saved-login', '使用已存资料', rows, String(entries.length));
  }

  function imports(c) {
    const batch = `<div class="vault-import"><textarea class="field" id="vault-import" rows="3"
        spellcheck="false" aria-label="账号密码" placeholder="邮箱----密码">${c.esc(c.ui.vaultDraft || '')}</textarea>
      <p class="credential-hint">每行一个账号</p>${c.actionButton({
        action: 'vault-import', content: '导入', size: 'large', tone: 'primary',
        attrs: (c.ui.vaultDraft || '').trim() ? '' : 'disabled'
      })}</div>`;
    return window.NXSettingsContent.disclosure(c, 'credential-import', '导入账号密码', batch);
  }

  return {find, stateText, codeText, summary, row, editor, imports, savedAccounts};
})();
