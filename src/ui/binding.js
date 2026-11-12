/* The account detail owns the target email throughout authenticator setup. */
'use strict';
window.NXBinding = (() => {
  function initial(email) {
    return {email, pending: null, error: '', busy: false};
  }

  function preview(binding, data) {
    if (!binding?.pending) return null;
    const {token, expires_at} = binding.pending;
    const expired = expires_at * 1000 <= Date.now();
    const entry = (data.mfa_pending || []).find(item => item.token === token) || binding.pending;
    return {...entry, expired, code: expired ? '' : entry.code};
  }

  function content(c) {
    const {ui, data, esc, actionButton} = c;
    const binding = ui.binding;
    const pending = preview(binding, data);
    let title, hint;
    if (pending?.expired) {
      title = '重新读取二维码';
      hint = '读取结果已过期，请重选二维码。';
    } else if (pending) {
      title = '核对验证码';
      hint = pending.account_matched === false
        ? '二维码未标邮箱，请核对归属后保存。'
        : '核对上方六位验证码，确认后保存。';
    } else {
      title = binding.busy ? '正在读取二维码…' : '读取验证器二维码';
      hint = '如有多张二维码图片，请一次选齐。';
    }
    const action = (name, text, primary = false, disabled = false) => actionButton({
      action: name, content: esc(text), size: 'large', tone: primary ? 'primary' : 'neutral',
      className: primary ? '' : 'secondary',
      attrs: `data-email="${esc(binding.email)}" ${binding.busy || disabled ? 'disabled' : ''}`
    });
    const actions = pending
      ? action('binding-reselect', '重选二维码')
        + action('binding-confirm', '保存验证器', true, pending.expired)
      : action('binding-read', '读取截图')
        + action('binding-file', '选择二维码图片', true);
    return `<div class="binding-content">
      <div class="binding-guide">
        <div class="binding-guide-title"><strong>${esc(title)}</strong></div>
        <p class="binding-instruction" ${binding.error ? 'hidden' : ''}>${esc(hint)}</p>
        <p class="binding-instruction binding-error" role="alert" ${binding.error ? '' : 'hidden'}>${esc(binding.error)}</p>
      </div>
      <div class="vault-inline-actions binding-actions">${actions}</div></div>`;
  }

  return {initial, preview, content};
})();
