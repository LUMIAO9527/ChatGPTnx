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
    let extra='';
    if(ui.mfa){
      const {body,foot}=mfa(c);
      extra=`<div class="vault-inline-form">${body}<div class="vault-inline-actions">${cancelButton(c)}${foot}</div></div>`;
    }else if(ui.authTransfer){
      extra=`<div class="vault-inline-form">${authenticator(c)}</div>`;
    }

    const body = expanded
      ? `<div id="vault-details" class="vault-details${editing?' credential-editor':''}" role="region" aria-label="密码与 2FA">` +
        line('邮箱', account.email, copy('email')) +
        (editing?editor(c):`<div class="vault-line"><span class="vault-label">密码</span>`+
          (entry?.has_password?`<button class="vault-value control--embedded mono" data-action="vault-reveal" data-email="${esc(account.email)}" aria-label="${revealing?'隐藏':'显示'}密码" title="${revealing?'隐藏密码':'显示密码 3 秒'}"><strong>${esc(masked)}</strong></button>`:`<strong>未保存</strong>`)+
          tool('vault-edit','edit','修改登录资料')+(entry?.has_password?copy('password'):'')+`</div>`+
        line('2FA', codeText(entry),
          `${remaining ? `<small class="vault-remain${expiring ? ' danger' : ''}">${esc(remaining)}</small>` : ''}` +
          `${actionButton({action:'mfa-open',content:hasSecret(entry)?'更换':'导入',label:hasSecret(entry)?'更换验证器':'导入验证器',size:'small',className:'secondary',attrs:`data-email="${esc(account.email)}"`})}${hasSecret(entry) ? copy('code') : ''}`,
          expiring ? ' danger' : '')) +
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

  const input=(c,id,label,value='',type='text',placeholder='')=>
    `<label class="vault-field" for="${id}"><span>${c.esc(label)}</span><input class="field" id="${id}" type="${type}" value="${c.esc(value)}" placeholder="${c.esc(placeholder)}" aria-describedby="credential-error" autocomplete="off" spellcheck="false"></label>`;
  const cancelButton=c=>c.actionButton({action:'vault-cancel',content:'取消',size:'large',className:'secondary'});

  function savedAccounts(c) {
    const entries=(c.data.vault||[]).filter(entry=>!c.data.accounts.some(a=>a.email.toLowerCase()===entry.email.toLowerCase()));
    if(!entries.length)return '';
    const rows=window.NXComponents.pagedList(c,'saved-login',entries,entry=>`<div class="saved-login-row collection-row"><span class="collection-name" title="${c.esc(entry.email)}">${c.esc(entry.label||entry.email)}</span>${c.actionButton({action:'vault-login',content:'登录',size:'small',className:'secondary',attrs:`data-email="${c.esc(entry.email)}" ${c.disabled()}`})}</div>`,{label:'已存登录资料'});
    return window.NXSettingsContent.disclosure(c,'saved-login','使用已存资料',rows,String(entries.length));
  }

  function authenticatorActions(c) {
    const {ui,actionButton}=c,link=ui.authMethod==='link',review=!!ui.authTransfer;
    let action=link?'authenticator-preview':'authenticator-choose',label=link?'读取链接':'选择二维码';
    if(review){
      if(ui.page==='detail'){action='vault-cancel';label='取消';}
      else if(link){action='authenticator-reset';label='重新录入';}
      else label='重新选择';
    }
    const readDisabled=ui.authBusy||(link&&!review&&!ui.authText.trim());
    const importDisabled=ui.authBusy||!ui.authTransfer?.rows.some(row=>row.email);
    return `<div class="vault-inline-actions">${actionButton({
      action,content:label,size:'large',tone:review?'neutral':'primary',className:review?'secondary':'',attrs:readDisabled?'disabled':''
    })}${actionButton({
      action:'authenticator-commit',content:'导入',size:'large',tone:review?'primary':'neutral',className:review?'':'secondary',attrs:importDisabled?'disabled':''
    })}</div>`;
  }

  function imports(c) {
    const batch=`<div class="vault-import"><textarea class="field" id="vault-import" rows="3" spellcheck="false" aria-label="登录资料" placeholder="邮箱----密码----2FA（可选）">${c.esc(c.ui.vaultDraft||'')}</textarea><p class="credential-hint">每行一个账号</p>${c.actionButton({action:'vault-import',content:'导入',size:'large',tone:'primary',attrs:(c.ui.vaultDraft||'').trim()?'':'disabled'})}</div>`;
    return window.NXSettingsContent.disclosure(c,'authenticator-import','导入手机 2FA',authenticator(c))
      +window.NXSettingsContent.disclosure(c,'credential-import','导入登录资料',batch);
  }

  function editor(c) {
    const {ui,esc}=c,d=ui.vaultEditor||{},entry=find(c.data,d.email);
    const more=`${input(c,'vault-url','兑换链接',d.exchange_url,'url')}
      ${entry?.has_exchange?`<div class="vault-form-actions"><button class="control secondary control--small" data-action="vault-open-exchange" data-email="${esc(d.email)}">打开兑换页</button><button class="control secondary control--small" data-action="vault-copy" data-email="${esc(d.email)}" data-value="exchange_code">复制兑换码</button></div>`:''}
      <label class="vault-field" for="vault-recovery"><span>恢复码</span><textarea class="field" id="vault-recovery" rows="2">${esc(d.recovery_codes||'')}</textarea></label>
      ${entry?.has_recovery?`<button class="control secondary control--small" data-action="vault-copy" data-email="${esc(d.email)}" data-value="recovery_codes">复制恢复码</button>`:''}
      ${entry?`<button class="control control--small credential-forget ${c.ui.vaultForget===d.email?'control--confirmation danger':'secondary'}" data-action="vault-forget" data-email="${esc(d.email)}">${c.ui.vaultForget===d.email?'确认移除':'移除登录资料'}</button>`:''}`;
    const field=(id,label,value,placeholder='')=>`<label class="vault-line credential-field" for="${id}"><span class="vault-label">${label}</span><input class="field" id="${id}" type="password" value="${esc(value||'')}" placeholder="${esc(placeholder)}" aria-describedby="credential-hint credential-error" autocomplete="off" spellcheck="false"></label>`;
    return `${field('vault-password','密码',d.password)}${field('vault-material','2FA',d.material,'密钥 / 兑换码')}
      ${window.NXSettingsContent.disclosure(c,'credential-more','其他资料',more,'',{className:'credential-extras'})}
      <div class="credential-feedback"><p id="credential-hint" class="credential-hint">留空项保持不变</p>
        <span id="credential-error" class="field-feedback" role="alert"></span></div>
      <div class="vault-inline-actions">${cancelButton(c)}${c.actionButton({action:'vault-save',content:'保存',size:'large',tone:'primary'})}</div>`;
  }

  function mfa(c) {
    const {data,ui,esc}=c,d=ui.mfa||{},email=ui.email;
    const pending=(data.mfa_pending||[]).find(p=>p.token===d.token),current=data.current?.toLowerCase()===email?.toLowerCase();
    const code=pending?.code||d.code||'',remaining=pending?.remain??d.remain;
    const button=(action,content,attrs='')=>c.actionButton({action,content,attrs,size:'large',tone:'primary'});
    const phone=c.actionButton({action:'authenticator-choose',content:'从手机导入',size:'small',className:'secondary'});
    const form=(content,foot)=>({body:`<div class="vault-form">${phone}${content}<span id="credential-error" class="field-feedback" role="alert"></span></div>`,foot});
    if(!current)return form(
      `<p class="note">绑定新密钥需先切换到此账号。</p>`,
      button('switch','切换到此账号',`data-email="${esc(email)}"`));
    if(!d.token)return form(
      `<p class="note">从 ChatGPT 安全设置复制新密钥。</p>
      ${input(c,'mfa-secret','新密钥',d.secret,'password','粘贴密钥')}`,
      button('mfa-preview','生成验证码'));
    if(d.expires_at&&d.expires_at*1000<=Date.now())return form(
      `<p class="note">验证码预览已过期。</p>`,button('mfa-reset','重新录入'));
    return form(`<div class="vault-enroll-code"><span>填入 ChatGPT</span>
      <strong class="mono">${esc(code.replace(/(\d{3})(\d{3})/,'$1 $2'))}</strong><span class="vault-remain">${esc(remaining??'')}s</span>
      <button class="control secondary control--small" data-action="mfa-copy">复制</button></div>
      <label class="vault-field" for="mfa-recovery"><span>恢复码</span><textarea class="field" id="mfa-recovery" rows="2">${esc(d.recovery_codes||'')}</textarea></label>
      <label class="vault-confirm"><input id="mfa-confirm" type="checkbox" ${d.confirmed?'checked':''}>已在 ChatGPT 完成绑定</label>`,
      button('mfa-commit','保存',d.confirmed?'':'disabled'));
  }

  function authenticator(c) {
    const {ui,esc,data}=c,transfer=ui.authTransfer,method=ui.authMethod||'image';
    const methods=ui.page==='detail'?'':c.segmented({
      label:'导入方式',action:'authenticator-method',
      options:[['image','二维码'],['link','导出链接']],value:method,className:'authenticator-methods'
    });
    let content;
    if(transfer){
      const options=transfer.emails.map(email=>{
        const entry=find(data,email);
        const account=data.accounts.find(item=>item.email.toLowerCase()===email.toLowerCase());
        return {email,label:entry?.label||(account&&c.name(account))||email,updates:entry?.has_secret};
      });
      const counts=new Map();
      for(const {label} of options)counts.set(label,(counts.get(label)||0)+1);
      const rows=transfer.rows.map(row=>{
        const prefix=row.issuer?row.issuer+':':'';
        const label=(prefix&&row.name?.startsWith(prefix)?row.name.slice(prefix.length).trim():row.name)||row.issuer||'验证器';
        const choices=options.map(item=>{
          const display=counts.get(item.label)===1?item.label:item.email;
          return `<option value="${esc(item.email)}" title="${esc(item.email)}" ${row.email===item.email?'selected':''}>${esc(display)}${item.updates?' · 更新':''}</option>`;
        }).join('');
        return `<label class="auth-map-row"><span class="auth-map-name" title="${esc(row.name||label)}">${esc(label)}</span>
          <select class="field auth-map" id="auth-map-${ui.authRevision}-${esc(row.id)}" data-id="${esc(row.id)}" aria-label="${esc(label)} 对应的账号" title="${esc(row.email||'忽略此条')}"><option value="">忽略</option>${choices}</select></label>`;
      }).join('');
      content=`<div class="authenticator-list" role="region" tabindex="0" aria-label="验证器对应账号">${rows}</div>`;
    }else if(method==='link'){
      content=`<textarea class="field authenticator-text" id="authenticator-text" rows="3" spellcheck="false" aria-label="验证器导出链接" aria-describedby="authenticator-error" placeholder="粘贴验证器导出链接">${esc(ui.authText)}</textarea>`;
    }else{
      content=`<div class="authenticator-empty"><strong>Google Authenticator</strong><span>转移账号 → 导出账号</span><span>一次选齐本批二维码图片</span></div>`;
    }
    const total=transfer?.rows.filter(row=>row.email).length||0;
    const status=ui.authBusy?'处理中…':transfer?`已选 ${total} / ${transfer.rows.length} 项`:'';
    return `<div class="authenticator-form">${methods}<div class="authenticator-source">${content}</div>
      <div class="authenticator-feedback"><span class="credential-hint" role="status">${status}</span><span id="authenticator-error" class="field-feedback" role="alert"></span></div>
      ${authenticatorActions(c)}</div>`;
  }

  return { find, stateText, codeText, summary, row, editor, mfa, authenticator, imports, savedAccounts };
})();
