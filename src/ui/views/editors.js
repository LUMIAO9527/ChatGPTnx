/* Shared single-line editors. Persistence lives in app.js, never in a view. */
'use strict';
window.NXEditors = (() => {
  const {esc,icon}=window.NXComponents;
  function row({id,label,value='',action,email='',type='text',max=400}) {
    return `<div class="inline-field" data-inline-field="${esc(id)}"><label class="sr-only" for="${esc(id)}">${esc(label)}</label><input class="field" id="${esc(id)}" type="${type}" value="${esc(value)}" placeholder="${esc(label)}" aria-label="${esc(label)}" aria-describedby="form-error" ${type==='text'?`maxlength="${max}" autocomplete="off"`:'min="0001-01-01" max="9999-12-31"'}><button class="tool save-check" data-action="${action}" data-email="${esc(email)}" title="保存${esc(label)}" aria-label="保存${esc(label)}">${icon('check')}</button></div>`;
  }
  function account(c,a) {
    const key='meta:'+a.email,draft=c.ui.metaDrafts.get(a.email)||{};
    const body=row({id:'alias',label:'昵称',value:draft.alias??a.alias??'',action:'save-alias',email:a.email,max:48})
      +row({id:'manual-date',label:'会员期限',type:'date',value:draft.subscription_date??a.manual_subscription_date??'',action:'save-expiry',email:a.email})
      +'<span id="form-error" class="field-feedback" role="alert"></span>';
    return `<div class="account-editor">${window.NXSettingsContent.disclosure(c,key,'昵称与会员期限',body,a.alias||'未设置')}</div>`;
  }
  return {row,account};
})();
