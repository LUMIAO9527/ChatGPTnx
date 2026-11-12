/* Shared data-management views and native bridge coordination. */
'use strict';
window.NXDataTransfer = (() => {
  const pages=new Set(['data-transfer','data-export','data-import','uninstall']);
  let state=null,context=null,ticket=0;
  const authenticatorKey='authenticator-import';
  let authenticator=null;
  const filename=()=>`ChatGPTnx-${new Date().toLocaleDateString('sv-SE')}.nxbackup`;
  function reset(c){
    ticket++;
    resetAuthenticator(c);
    state={selected:new Set(c.data.accounts.map(a=>a.email)),usage:true,preferences:true,archived:false,
      password:'',confirm:'',exportStage:'edit',importStage:'choose',file:'',unlock:'',error:'',
      merge:'merge',importSelected:new Set(),keep:true,uninstallStage:'confirm',blocked:false,
      imported:false,openAccounts:false,loadedAccounts:null,archivedCount:0,exportFilename:'',result:null,pending:false};
  }
  function init(params,c){reset(c);window.NXDataDemo?.init(params,c,state);}
  function button(c,text,action,options={}){
    return c.actionButton({content:c.esc(text),action,size:options.small?'small':'large',
      tone:options.danger?'danger':options.secondary?'neutral':'primary',
      confirmation:!!options.confirm,className:options.secondary?'secondary':'',
      attrs:options.disabled?'disabled':''});
  }
  function cancelAuthenticator(c,review){
    if(review?.token)c.api('authenticator_cancel',review.token).catch(()=>{});
  }
  function resetAuthenticator(c){
    cancelAuthenticator(c,authenticator?.review);
    authenticator={review:null,selected:new Set(),working:'',error:'',saved:0};
  }
  const matched=row=>!!row.email&&!row.problem;
  function authenticatorView(c){
    const {review,selected,working,error,saved}=authenticator;
    const picker=button(c,working==='read'?'正在读取…':review?'重选二维码图片':'选择二维码图片',
      'authenticator-choose',{secondary:!!review,disabled:!!working});
    let confirmation='';
    if(review){
      const rows=window.NXComponents.pagedList(c,authenticatorKey,review.rows,row=>{
        const match=matched(row),account=match&&c.data.accounts.find(item=>item.email===row.email);
        const title=match?(account?c.name(account):row.email):row.source;
        const subtitle=match?row.email:row.problem;
        const selectedRow=selected.has(row.id);
        const status=match&&(saved?(selectedRow?'已保存':'已跳过'):row.replaces?'更新':'');
        const checkbox=match&&!saved?c.selectionButton({label:`导入 ${row.email}`,checked:selectedRow,
          action:'authenticator-toggle',email:row.id}):'';
        return `<div class="transfer-account"><span class="transfer-copy"><strong title="${c.esc(title)}">${c.esc(title)}</strong>
          <small title="${c.esc(subtitle)}">${c.esc(subtitle)}</small></span>
          ${status?`<span class="transfer-state">${c.esc(status)}</span>`:''}${checkbox}</div>`;
      },{label:'验证器账号'});
      const outcome=saved
        ? `<div class="authenticator-outcome" role="status">${c.icon('check')}已保存 ${saved} 个验证器</div>`
        : button(c,working==='save'?'正在保存…':selected.size?`保存 ${selected.size} 个验证器`:'保存验证器',
          'authenticator-save',{disabled:!!working||!selected.size});
      confirmation=`<div class="authenticator-review"><div class="authenticator-review-head"><strong>核对账号</strong>
        ${saved?'':`<span class="transfer-state">已选 ${selected.size} / ${review.rows.length} 项</span>`}</div>${rows}${outcome}</div>`;
    }
    const content=`<div class="vault-import authenticator-import" aria-busy="${!!working}">
      <p class="credential-hint">从 Google Authenticator 导出账号后，选齐二维码图片。</p>${picker}
      ${error?`<p class="transfer-error" role="alert">${c.esc(error)}</p>`:''}${confirmation}</div>`;
    return window.NXSettingsContent.disclosure(c,authenticatorKey,'导入手机 2FA',content);
  }
  function setAuthenticatorReview(c,flow,review){
    cancelAuthenticator(c,flow.review);
    flow.review=review;
    flow.saved=0;
    flow.selected=new Set((review?.rows||[]).filter(matched).map(row=>row.id));
    c.ui.collectionPages[authenticatorKey]=1;
  }
  function revealAuthenticatorReview(c,flow){
    const reveal=()=>{
      if(flow!==authenticator||!c.ui.disclosures.has(authenticatorKey))return;
      const card=document.querySelector('#sheet [data-disclosure="authenticator-import"]');
      const review=card?.querySelector('.authenticator-review'),viewport=card?.closest('.sheet-body');
      if(!review||!viewport)return;
      if(card.__nxDisclosureOwned){requestAnimationFrame(reveal);return;}
      const bounds=review.getBoundingClientRect(),visible=viewport.getBoundingClientRect();
      const overflow=Math.min(bounds.bottom-visible.bottom+8,bounds.top-visible.top-8);
      if(overflow>0)viewport.scrollBy({top:overflow,behavior:window.NXMotion?.enabled()?'smooth':'instant'});
    };
    requestAnimationFrame(reveal);
  }
  async function readAuthenticator(c){
    const flow=authenticator;
    let reviewed=false;
    flow.working='read';flow.error='';c.render();
    try{
      const result=await c.api('authenticator_choose');
      if(flow!==authenticator){cancelAuthenticator(c,result);return;}
      if(result?.cancelled)return;
      if(!result?.ok)throw new Error(result?.error||'二维码读取未完成');
      setAuthenticatorReview(c,flow,result);
      reviewed=true;
    }catch(error){
      if(flow!==authenticator)return;
      setAuthenticatorReview(c,flow,null);
      flow.error=error.message;
    }finally{
      if(flow===authenticator){
        flow.working='';c.disclose(c.render);
        if(reviewed)revealAuthenticatorReview(c,flow);
      }
    }
  }
  async function saveAuthenticator(c){
    const flow=authenticator;
    flow.working='save';flow.error='';c.render();
    try{
      const selections=flow.review.rows.filter(row=>flow.selected.has(row.id)).map(({id,email})=>({id,email}));
      const result=await c.api('authenticator_commit',{token:flow.review.token,selections});
      if(flow!==authenticator)return;
      if(!result?.ok)throw new Error(result?.error||'保存未完成');
      flow.saved=result.imported;flow.review.token=null;
      await c.refresh();
    }catch(error){if(flow===authenticator)flow.error=error.message;}
    finally{if(flow===authenticator){flow.working='';c.disclose(c.render);}}
  }
  function option(c,title,note,key,checked,row=false){
    return `<div class="transfer-option${row?' collection-row':''}"><span class="transfer-copy"><strong>${c.esc(title)}</strong><small>${c.esc(note)}</small></span>${c.selectionButton({label:title,checked,action:'transfer-toggle',email:key})}</div>`;
  }
  function field(c,id,label,value,autocomplete='new-password'){
    return `<label class="transfer-field" for="${id}"><span>${c.esc(label)}</span><input class="field" type="password" id="${id}" value="${c.esc(value)}" autocomplete="${autocomplete}" maxlength="256" aria-describedby="transfer-error transfer-password-help"></label>`;
  }
  function error(){return `<p id="transfer-error" class="transfer-error" role="alert" ${state.error?'':'hidden'}>${window.NXComponents.esc(state.error)}</p>`;}
  function count(c){return c.data.accounts.filter(a=>state.selected.has(a.email)).length+(state.archived?state.archivedCount:0);}
  function validPassword(){const size=[...state.password].length;return size>=8&&size<=128&&state.password===state.confirm;}
  function packageRows(c){
    return `<div class="transfer-facts"><div><span>账号资料</span><strong>${count(c)} 个账号</strong></div><div><span>用量与额度</span><strong>${state.usage?'已包含':'未包含'}</strong></div><div><span>通用设置</span><strong>${state.preferences?'已包含':'未包含'}</strong></div></div>`;
  }
  function outcome(c,heading,description,details='',working=false){
    return `<div class="transfer-outcome"><div class="confirm-mark">${c.icon(working?'refresh':'check',working?'spinner':'')}</div><h3>${c.esc(heading)}</h3><p>${c.esc(description)}</p></div>${details}`;
  }
  function exportView(c){
    let body='',foot='';
    if(state.exportStage==='working'){
      body=outcome(c,'正在导出','正在加密账号与所选记录…','',true);
      foot=button(c,'正在导出…','export-save',{disabled:true});
    }else if(state.exportStage==='done'){
      body=outcome(c,'备份已导出','在另一台电脑的 NX 中选择“导入备份”。',`<div class="transfer-file-note">${c.icon('archive')}<span>${c.esc(state.exportFilename||filename())}</span></div>${packageRows(c)}`);
      foot=button(c,'完成','transfer-finish');
    }else{
      const accounts=window.NXComponents.pagedList(c,'transfer-accounts',c.data.accounts,a=>`<div class="transfer-account collection-row"><span class="transfer-copy"><strong title="${c.esc(a.alias||a.email)}">${c.esc(c.name(a))}</strong><small title="${c.esc(a.email)}">${c.esc(a.email)}</small></span>${c.selectionButton({label:'导出 '+c.name(a),checked:state.selected.has(a.email),action:'export-account',email:a.email})}</div>`,{label:'导出账号',empty:'暂无账号'});
      const chooser=`<div class="transfer-select-head"><span>昵称、会员信息与登录状态</span>${button(c,state.selected.size===c.data.accounts.length?'取消全选':'全选','export-all',{small:true,secondary:true})}</div>${accounts}`;
      body=`<p class="transfer-intro">将账号与记录保存为加密备份。</p>
        ${window.NXSettingsContent.disclosure(c,'transfer-accounts','选择账号',chooser,`${state.selected.size} 个`)}
        <div class="transfer-data-options">${window.NXSettingsContent.disclosure(c,'export-data','随附资料',window.NXComponents.pagedList(c,'export-data',[
          ['已归档账号','一并备份归档的账号及资料','archived',state.archived],
          ['用量与额度','历史统计、最近额度及更新时间','usage',state.usage],
          ['通用设置','外观、通知与接续消息','preferences',state.preferences]
        ],item=>option(c,...item,true),{label:'随附资料'}),[state.usage?'用量':'',state.preferences?'设置':'',state.archived?'归档':''].filter(Boolean).join('、')||'仅账号')}</div>
        <div class="transfer-passwords">${field(c,'backup-password','备份密码',state.password)}${field(c,'backup-confirm','确认密码',state.confirm)}</div>
        <p id="transfer-password-help" class="transfer-help">8–128 位，导入时需要此密码。</p>${error()}`;
      foot=button(c,'导出加密备份','export-save',{disabled:!count(c)||!validPassword()});
    }
    return {title:'导出数据',body,foot,cls:'transfer-body',footClass:'transfer-footer'};
  }
  function importCounts(c){
    const rows=(state.loadedAccounts||[]).filter(a=>state.importSelected.has(a.email));
    return {rows,added:rows.filter(a=>!a.duplicate).length,merged:rows.filter(a=>a.duplicate).length};
  }
  function importView(c){
    let body='',foot='';
    if(state.importStage==='choose'){
      body=`<p class="transfer-intro">从 NX 备份中恢复账号与记录。</p><button class="transfer-file-row" data-action="import-file">${c.icon('folder')}<span class="transfer-copy"><strong>选择备份文件</strong><small>.nxbackup · 加密备份</small></span>${c.icon('chevron')}</button><p class="transfer-help">选择文件后，输入导出时设置的密码。</p>${error()}`;
    }else if(state.importStage==='unlock'){
      body=`<p class="transfer-intro">输入密码以查看备份内容。</p><div class="transfer-file-note">${c.icon('archive')}<span>${c.esc(state.file)}</span></div><button class="control secondary control--small" data-action="import-file">重新选择</button><div class="transfer-passwords">${field(c,'backup-unlock','备份密码',state.unlock,'current-password')}</div><p id="transfer-password-help" class="transfer-help">使用导出这份备份时设置的密码。</p>${error()}`;
      foot=button(c,'查看备份内容','import-unlock',{disabled:!state.unlock});
    }else if(state.importStage==='review'){
      const f=(state.loadedAccounts||[]),totals=importCounts(c);
      const chooser=window.NXComponents.pagedList(c,'import-accounts',f,a=>`<div class="transfer-account collection-row"><span class="transfer-copy"><strong title="${c.esc(c.name(a))}">${c.esc(c.name(a))}</strong><small title="${c.esc(a.email)}">${c.esc(a.email)}</small></span><span class="transfer-state">${a.duplicate?'已存在':'新增'}</span>${c.selectionButton({label:'导入 '+c.name(a),checked:state.importSelected.has(a.email),action:'import-account',email:a.email})}</div>`,{label:'导入账号'});
      body=`<p class="transfer-intro">备份包含 ${f.length} 个账号，${f.filter(a=>a.duplicate).length} 个已在此设备。</p>${window.NXSettingsContent.disclosure(c,'import-accounts','选择账号',chooser,`${state.importSelected.size} 个`)}
        <section class="transfer-merge"><h3>重复账号</h3>${c.segmented({label:'重复账号处理',action:'import-merge',options:[['merge','合并资料'],['skip','跳过']],value:state.merge,className:'compact'})}<p class="transfer-help">${state.merge==='merge'?'保留现有昵称，补充缺失资料；用量按日期合并，重复记录保留较新的一份。':'仅导入此设备尚未保存的账号。'}</p></section>
        <div class="transfer-card">${option(c,'用量与额度','恢复历史统计与最近一次额度记录','usage',state.usage)}${option(c,'通用设置','应用备份中的外观、通知与接续消息','preferences',state.preferences)}</div><p class="transfer-help">额度保留原采集时间，导入后刷新。</p>${error()}`;
      const n=totals.added+(state.merge==='merge'?totals.merged:0);
      foot=button(c,`确认导入 ${n} 个账号`,'import-start',{confirm:true,disabled:!n});
    }else if(state.importStage==='working'){
      body=outcome(c,'正在导入','正在保存账号与记录…','',true);
      foot=button(c,'正在导入…','import-start',{disabled:true});
    }else{
      const n=state.result||importCounts(c),needs=state.result?.needs_login??n.rows.filter(a=>a.needsLogin).length;
      body=outcome(c,'导入完成',`新增 ${n.added} 个账号${state.merge==='merge'&&n.merged?`，合并 ${n.merged} 个账号资料`:''}。`,
        `<div class="transfer-facts"><div><span>用量与额度</span><strong>${state.usage?'已恢复':'未导入'}</strong></div><div><span>通用设置</span><strong>${state.preferences?'已恢复':'未导入'}</strong></div></div>${needs?`<p class="transfer-help">${needs} 个账号需要重新登录，可在账号详情中继续。</p>`:''}`);
      foot=button(c,'查看账号','import-finish');
    }
    return {title:'导入备份',body,foot,cls:'transfer-body',footClass:'transfer-footer'};
  }
  function uninstallView(c){
    let body='',foot='';
    if(state.uninstallStage==='working'){
      body=outcome(c,'正在卸载','正在退出程序并清理应用文件…','',true);
      foot=button(c,'正在卸载…','uninstall-start',{disabled:true});
    }else if(state.uninstallStage==='done'){
      body=outcome(c,'卸载完成',state.keep?'账号与数据已保留。重新安装到原位置后可继续使用。':'程序及此设备上的 NX 数据已移除。');
      foot=button(c,'关闭','uninstall-finish');
    }else{
      const blocked=state.blocked||!!(c.data.operation||c.data.adding||c.data.reauth||['switching','resuming'].includes(c.data.resume?.phase));
      body=`<section class="update-identity uninstall-identity">${c.brandMark('update-mark')}<h3 class="update-brand">ChatGPTnx</h3><p class="update-version">当前版本 ${c.esc(c.config.version)}</p></section><p class="transfer-intro">卸载后将退出程序，清理应用文件、旧版本与开机启动项。</p><div class="transfer-card">${option(c,'保留账号与数据','再次安装时可继续使用','keep',state.keep)}</div><p class="transfer-help ${state.keep?'':'transfer-danger'}">${state.keep?'保留账号、用量记录及设置。':`将删除此设备保存的 ${c.data.accounts.length} 个账号、用量记录及设置。`}</p>${error()}${blocked?'<p class="transfer-error" role="status">请先完成当前的切号、登录或更新。</p>':''}`;
      foot=button(c,'取消','back',{secondary:true})+button(c,state.keep?'确认卸载':'卸载并删除数据','uninstall-start',{confirm:true,danger:!state.keep,disabled:blocked});
    }
    return {title:'卸载 ChatGPTnx',body,foot,cls:'transfer-body uninstall-body',footClass:'transfer-footer'};
  }
  function view(page,c){
    if(!pages.has(page))return null;
    context=c;if(!state)reset(c);
    if(page==='data-export')return exportView(c);
    if(page==='data-import')return importView(c);
    if(page==='uninstall')return uninstallView(c);
    return {title:'导入与导出',cls:'transfer-body',body:`<div class="transfer-overview">
      ${c.settingsGroup('备份',c.link('','导出备份','transfer-export')+c.link('','导入备份','transfer-import'))}
      ${c.settingsGroup('账号资料',window.NXVault.imports(c)+authenticatorView(c))}
    </div>`};
  }
  function busy(page){return pages.has(page)&&!!(state?.pending||page==='data-export'&&state?.exportStage==='working'||page==='data-import'&&state?.importStage==='working'||page==='uninstall'&&state?.uninstallStage==='working');}
  function clearPasswords(){
    if(!state)return;
    state.password=state.confirm=state.unlock='';
    for(const id of ['backup-password','backup-confirm','backup-unlock']){
      const input=document.getElementById(id);
      if(input){input.value='';input.removeAttribute('value');}
    }
  }
  function leave(page,next,c){
    if(!pages.has(page)||page===next||!state)return;
    clearPasswords();
    if(page==='data-transfer')resetAuthenticator(c);
    if(page==='data-import'){
      ticket++;state.loadedAccounts=null;state.file='';state.importSelected.clear();state.importStage='choose';
      c.api('backup_clear').catch(()=>{});
    }
  }
  function hidden(page,c){if(busy(page))clearPasswords();else leave(page,null,c);}
  async function perform(c,key,page,method,args=[],done=null){
    const previous=state[key],current=++ticket;
    state[key]='working';state.error='';c.render();
    try{
      const result=await c.api(method,...args);
      if(current!==ticket)return;
      if(!result?.ok)throw new Error(result?.error||'操作未完成，请重试');
      if(result.cancelled){state[key]=previous;c.render();return;}
      done?.(result);state[key]='done';
      await c.refresh();
    }catch(error){if(current!==ticket)return;state[key]=previous;state.error=error.message||'操作未完成，请重试';}
    if(c.ui.page===page)c.render();
  }
  async function choose(c){
    const current=++ticket;state.error='';state.pending=true;c.render();
    try{
      const result=await c.api('backup_choose');
      if(current!==ticket)return;
      if(!result?.ok)throw new Error(result?.error||'无法选择备份');
      if(result.cancelled)return;
      state.file=result.filename;state.unlock='';state.importStage='unlock';state.loadedAccounts=null;
    }catch(error){if(current===ticket)state.error=error.message;}
    finally{if(current===ticket){state.pending=false;c.render();}}
  }
  async function unlock(c){
    const current=++ticket;state.error='';state.pending=true;c.render();
    try{
      const result=await c.api('backup_unlock',state.unlock);
      if(current!==ticket)return;
      if(!result?.ok)throw new Error(result?.error||'无法解锁备份');
      state.loadedAccounts=result.accounts;state.importSelected=new Set(result.accounts.map(a=>a.email));
      state.usage=result.usage;state.preferences=result.preferences;state.importStage='review';state.unlock='';
    }catch(error){if(current===ticket)state.error=error.message;}
    finally{if(current===ticket){state.pending=false;c.render();}}
  }
  function handle(b,c){
    const action=b.dataset.action;
    if(!/^(transfer-|export-|import-|uninstall-|authenticator-)/.test(action))return false;
    if(busy(c.ui.page))return true;
    context=c;if(!state)reset(c);
    if(action.startsWith('authenticator-')&&
      (c.ui.page!=='data-transfer'||!c.ui.disclosures.has(authenticatorKey)||authenticator.working))return true;
    const key=b.dataset.email;
    switch(action){
      case 'transfer-open':{
        reset(c);c.show('data-transfer');const current=ticket;
        c.api('backup_info').then(result=>{if(current===ticket&&result?.ok){state.archivedCount=result.archived_count;c.render();}}).catch(()=>{});break;}
      case 'transfer-export':state.exportStage='edit';state.error='';c.show('data-export');break;
      case 'transfer-import':reset(c);state.importStage='choose';c.show('data-import');break;
      case 'authenticator-choose':readAuthenticator(c);break;
      case 'authenticator-toggle':
        if(!authenticator.saved&&authenticator.review?.rows.some(row=>row.id===key&&matched(row))){
          authenticator.selected.has(key)?authenticator.selected.delete(key):authenticator.selected.add(key);
          c.render();
        }
        break;
      case 'authenticator-save':
        if(authenticator.review?.token&&authenticator.selected.size)saveAuthenticator(c);
        break;
      case 'transfer-finish':c.back();break;
      case 'transfer-toggle':state[key]=!state[key];c.render();break;
      case 'export-account':state.selected.has(key)?state.selected.delete(key):state.selected.add(key);c.render();break;
      case 'export-all':state.selected=state.selected.size===c.data.accounts.length?new Set():new Set(c.data.accounts.map(a=>a.email));c.render();break;
      case 'export-save':if(validPassword()&&count(c))perform(c,'exportStage','data-export','backup_export',[{accounts:[...state.selected],usage:state.usage,preferences:state.preferences,archived:state.archived},state.password],result=>{state.exportFilename=result.filename;state.password=state.confirm='';});break;
      case 'import-file':choose(c);break;
      case 'import-unlock':unlock(c);break;
      case 'import-account':state.importSelected.has(key)?state.importSelected.delete(key):state.importSelected.add(key);c.render();break;
      case 'import-merge':state.merge=b.dataset.value;c.render();break;
      case 'import-start':perform(c,'importStage','data-import','backup_import',[{accounts:[...state.importSelected],merge:state.merge,usage:state.usage,preferences:state.preferences}],result=>{state.result=result;});break;
      case 'import-finish':c.show('quota-overview');break;
      case 'uninstall-open':reset(c);c.show('uninstall');break;
      case 'uninstall-start':if(!state.blocked)perform(c,'uninstallStage','uninstall','uninstall_app',[state.keep]);break;
      case 'uninstall-finish':c.back();break;
    }
    return true;
  }
  document.addEventListener('input',event=>{
    if(!state||!context)return;
    const keys={'backup-password':'password','backup-confirm':'confirm','backup-unlock':'unlock'};
    const key=keys[event.target.id];if(!key)return;
    state[key]=event.target.value;state.error='';
    const mismatch=key!=='unlock'&&!!state.confirm&&state.password!==state.confirm;
    const errorNode=document.getElementById('transfer-error');
    if(errorNode){errorNode.hidden=!mismatch;errorNode.textContent=mismatch?'两次输入的密码不一致。':'';}
    const button=document.querySelector('[data-action="export-save"]');
    if(button)button.disabled=!count(context)||!validPassword();
    const unlock=document.querySelector('[data-action="import-unlock"]');if(unlock)unlock.disabled=!state.unlock;
  });
  return {init,view,handle,busy,leave,hidden};
})();
