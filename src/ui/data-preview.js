/* Synthetic backup and uninstall adapter for the offline explorer. */
'use strict';
window.NXDataDemo=(()=>{
  let state=null,context=null;
  const copy=value=>JSON.parse(JSON.stringify(value));
  const filename=()=>`ChatGPTnx-${new Date().toLocaleDateString('sv-SE')}.nxbackup`;
  function fixture(c){
    if(state.loadedAccounts)return state.loadedAccounts;
    const existing=c.data.accounts.slice(0,2).map(a=>({...copy(a),duplicate:true}));
    const names=[['travel@example.com','出行'],['study@example.com','研究'],['team@example.com','协作']];
    const template=c.data.accounts[0]||{plan:'plus',windows:[],fetched_at:Math.floor(Date.now()/1000)-3600};
    return state.loadedAccounts=[...existing,...names.map(([email,alias],i)=>({...copy(template),email,alias,identity_key:'email:'+email,
      duplicate:false,needsLogin:i===2,archived:false}))];
  }
  function init(params,c,model){
    state=model;context=c;state.archivedCount=1;
    const flow=params.get('flow')||'';
    if(flow.startsWith('export-'))state.exportStage=flow.slice(7);
    if(flow==='export-ready'){state.exportStage='edit';state.password=state.confirm='nx-demo-2026';}
    if(flow==='export-mismatch'){state.exportStage='edit';state.password='nx-demo-2026';state.confirm='different';state.error='两次输入的密码不一致。';}
    if(flow==='export-long'){state.openAccounts=true;c.ui.disclosures.add('transfer-accounts');}
    if(flow.startsWith('import-')){
      state.file=filename();state.importStage=flow.slice(7);
      if(flow==='import-long'){
        const sample=fixture(c),template=sample.at(-1);
        state.loadedAccounts=sample.concat(Array.from({length:9},(_,i)=>({...copy(template),email:`import-${i+1}@example.com`,alias:`备份账号 ${i+6}`,identity_key:`import-${i+1}`,duplicate:false})));
        state.importStage='review';
      }
      state.importSelected=new Set(fixture(c).map(a=>a.email));
      if(flow==='import-wrong'){state.importStage='unlock';state.error='密码不正确，请重新输入。';}
      if(flow==='import-invalid'){state.importStage='choose';state.error='这个文件不是 NX 备份，请重新选择。';}
      if(flow==='import-damaged'){state.importStage='choose';state.error='备份文件不完整，请重新导出后再试。';}
    }
    if(flow==='uninstall-delete')state.keep=false;
    if(flow==='uninstall-busy')state.blocked=true;
    if(flow==='uninstall-working')state.uninstallStage='working';
    if(flow==='uninstall-done')state.uninstallStage='done';
  }
  const handles=method=>['backup_info','backup_choose','backup_unlock','backup_export','backup_import','uninstall_app'].includes(method);
  async function call(method,...args){
    const c=context;
    if(method==='backup_info')return {ok:true,archived_count:1};
    if(method==='backup_choose')return {ok:true,filename:filename()};
    if(method==='backup_unlock')return args[0]==='nx-demo-2026'?{ok:true,accounts:fixture(c),usage:true,preferences:true}:{ok:false,error:'密码不正确，请重新输入。'};
    await new Promise(resolve=>setTimeout(resolve,1000));
    if(method==='backup_export')return {ok:true,filename:filename()};
    if(method==='uninstall_app')return {ok:true};
    if(method==='backup_import'){
      const options=args[0],rows=fixture(c).filter(a=>options.accounts.includes(a.email));
      for(const a of rows){
        if(a.duplicate)continue;
        const entry=copy(a);delete entry.duplicate;delete entry.needsLogin;
        if(a.needsLogin){entry.ok=false;entry.error_code='reauth_required';entry.windows=[];entry.err='请重新登录';}
        window.NXDemo.importAccount(entry);
      }
      return {ok:true,added:rows.filter(a=>!a.duplicate).length,merged:options.merge==='merge'?rows.filter(a=>a.duplicate).length:0,needs_login:rows.filter(a=>a.needsLogin).length};
    }
  }
  return {init,handles,call};
})();
