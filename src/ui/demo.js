/* Offline demonstration only. This file is NEVER linked into production panel.html. */
'use strict';
window.NXDemo = (() => {
  const clone=v=>JSON.parse(JSON.stringify(v));
  let state, usages, archives=[], resumeDetails=[], serial=0, failNext=false, previous=null, generation=0;
  const sec=()=>Math.floor(Date.now()/1000);
  function demoRelayOrder() {
    const usable=a=>Number.isFinite(a.fetched_at)&&a.fetched_at>=0&&a.fetched_at<=sec()+60&&window.NXComponents.displayWindows(a).length>0&&window.NXComponents.displayWindows(a).every(w=>w.used<100&&w.resets_at>sec());
    const rank=a=>{
      const five=a.windows.find(w=>w.duration_mins===300),week=a.windows.find(w=>w.duration_mins===10080);
      const floor=Math.min(...a.windows.map(w=>100-w.used));
      const tier=five?(floor>=50?5:floor>=20?4:floor>=5?2:1):(floor>=20?3:floor>=5?2:1);
      const limiting=a.windows.filter(w=>100-w.used===floor&&Number.isFinite(w.resets_at));
      return [tier,floor,!!five,limiting.length?-Math.min(...limiting.map(w=>w.resets_at)):-Infinity,
        five?100-five.used:-1,week?100-week.used:-1];
    };
    const compare=(a,b)=>{const x=rank(a),y=rank(b);for(let i=0;i<x.length;i++)if(x[i]!==y[i])return y[i]-x[i];return 0;};
    return state.accounts.filter(usable).sort(compare).map(a=>a.email);
  }
  function seed(){
    generation++;
    const n=sec(), day=86400;
    const defs=[['work-01@example.com','工作 01','plus',58,92],['work-02@example.com','工作 02','plus',17,29],
      ['studio@example.com','长任务','prolite',null,36],['backup@example.com','备用','plus',44,77],['remote@example.com','远程','plus',23,48]];
    const accounts=defs.map(([email,alias,plan,h,w],i)=>({email,alias,plan,identity_key:'email:'+email,ok:i!==4,
      err:i===4?'Codex 查询服务暂时出错，请稍后重试':null,error_code:i===4?-32603:null,bucket:'codex',fetched_at:n-60,
      windows:[...(h===null?[]:[{label:'5h',duration_mins:300,used:h,resets_at:n+3600+i*1200}]),{label:'周',duration_mins:10080,used:w,resets_at:n+(2+i)*day+13200}],
      credits:i===2?'12.50':null,snapshot_at:n-day*(i+1),
      banked_resets:i===0?{available_count:2,items:[
        {id:'fixture-reset-1',title:'完整额度重置',description:'可重置 5 小时与周额度',status:'available',reset_type:'codexRateLimits',granted_at:n-day,expires_at:n+8*day,expires_known:true},
        {id:'fixture-reset-2',title:'完整额度重置',description:null,status:'available',reset_type:'codexRateLimits',granted_at:n-day,expires_at:n+20*day,expires_known:true}
      ]}:i===1?{available_count:0,items:[]}:null,
      membership:{status:i===0?'cached_hint':'not_provided',date:i===0?n+12*day:null,date_kind:i===0?'entitlement_hint':null,
        source:i===0?'credential_claim':'not_available',verified:false,checked_at:null,observed_at:n-day,account_checked_online:false}}));
    state={version:window.NX_CONFIG.version,accounts,current:accounts[0].email,updated:n-60,switching:null,operation:null,adding:false,reauth:null,resume:null,
      last_error:null,last_result:null,recent_results:[],chatgpt_running:true,pending:null,relay_wait:null,
      hotkeys:accounts.map((a,i)=>({email:a.email,shortcut:`ctrl+alt+${i+1}`,registered:true})),
      settings:{appearance:'system',autostart:false,auto_relay:false,auto_relay_excluded:[],
        early_anchor:false,early_anchor_accounts:[],
        task_continuation:true,resume_message:'继续',notify_credential:true,
        notify_low:false,notify_reset_expiry:true,relay_pick:null}};
    usages={};const totals=[18420680,26480300,60241200,9421800,5483200];
    accounts.forEach((a,i)=>{
      if(i===4){usages[a.email]={ok:false,err:'该账号暂时无法查询用量',attempted_at:n,identity_key:a.identity_key};return;}
      const today=new Date(n*1000);
      const end=Date.UTC(today.getFullYear(),today.getMonth(),today.getDate());
      const buckets=Array.from({length:90},(_,j)=>({startDate:new Date(end-(89-j)*day*1000).toISOString().slice(0,10),tokens:Math.round((Math.sin(j*.41+i)+1.2)*(i+1)*55000+(j%8)*13000)})).filter((_,j)=>!(i===0&&j===72));
      usages[a.email]={ok:true,source:'account/usage/read',scope:'chatgpt_account_activity',fetched_at:n-60,identity_key:a.identity_key,
        summary:{lifetimeTokens:totals[i],peakDailyTokens:Math.max(...buckets.map(b=>b.tokens)),currentStreakDays:[8,12,6,3][i],longestStreakDays:[24,31,18,9][i],longestRunningTurnSec:[720,1080,2160,480][i]},dailyUsageBuckets:buckets};
    });
    archives=[];resumeDetails=[];failNext=false;previous=null;
  }
  function operation(kind,target,job){
    if(state.operation)return {ok:false,error:'当前操作尚未完成'};
    if(state.adding&&!['add_cancel','add_finish'].includes(kind))return {ok:false,error:'请先完成或取消添加'};
    const ticket=generation, id='demo-'+(++serial);state.last_error=null;state.last_result=null;
    state.operation={id,kind,target,phase:kind==='switch'?'保存当前快照 · 正在接力':kind==='usage'?'读取用量…':kind==='subscription'?'自动读取会员信息':kind==='refresh'?'准备中':'正在处理…',started_at:sec()};
    if(kind==='switch')state.switching=target;
    setTimeout(()=>{
      if(ticket!==generation)return;
      try{job();state.last_result={id,kind,target,ok:true,message:state.operation.message};}
      catch(e){state.last_result={id,kind,target,ok:false};state.last_error={id,kind,target,message:e.message};}
      state.recent_results=(state.recent_results.concat([state.last_result])).slice(-8);
      state.operation=null;state.switching=null;
    },kind==='switch'?1500:550);
    return {ok:true,accepted:true,operation_id:id};
  }
  function commitSwitch(email){
    state.current=email;
    if(state.settings.relay_pick===email)state.settings.relay_pick=null;
    if(state.relay_wait?.email===email)state.relay_wait=null;
    else if(state.relay_wait)state.relay_wait.origin=email;
  }
  async function call(method,...args){
    const [email,force]=args;
    switch(method){
      case 'get_diagnostics':return {ok:true,text:JSON.stringify({version:window.NX_CONFIG.version,monitor:{state:'ok'},accounts:[{account:1,ok:true,paused:false}]},null,2)};
      case 'retry_query':return operation('refresh',email,()=>{const a=state.accounts.find(a=>a.email===email);if(a){a.ok=true;a.error_code=null;a.paused=false;a.retry_at=null;delete a.query_warning;a.fetched_at=sec();}});
      case 'get_data':{
        if(state.demo_connection_error)throw new Error('演示：本地服务暂时不可用');
        const known=new Map(state.hotkeys.map(item=>[item.email,item]));
        state.hotkeys=state.accounts.map((a,i)=>known.get(a.email)||{email:a.email,shortcut:i<9?`ctrl+alt+${i+1}`:null,registered:i<9});
        state.relay_order=demoRelayOrder();
        state.relay_email=(state.settings.relay_pick&&state.relay_order.includes(state.settings.relay_pick)?state.settings.relay_pick:null)
          ||state.relay_order.find(email=>email!==state.current)||null;
        state.auto_relay_email=state.settings.auto_relay_excluded.includes(state.current)?null:
          state.relay_order.find(email=>email!==state.current&&!state.settings.auto_relay_excluded.includes(email))||null;
        if(state.relay_wait&&(state.relay_wait.email===state.current||!state.accounts.some(a=>a.email===state.relay_wait.email)))state.relay_wait=null;
        if(state.relay_wait&&!state.operation&&!state.adding&&!state.reauth&&state.chatgpt_running&&state.relay_order.includes(state.relay_wait.email)){
          const target=state.relay_wait.email;
          operation('switch',target,()=>commitSwitch(target));
          state.operation.source='recovery';
        }
        return clone(state);}
      case 'dismiss_error':if(state.last_error?.id===email)state.last_error=null;return {ok:true};
      case 'clear_resume_history':resumeDetails=resumeDetails.filter(s=>['switching','resuming','waiting_account'].includes(s.phase));if(state.resume&&!['switching','resuming','waiting_account'].includes(state.resume.phase))state.resume=null;return {ok:true};
      case 'get_resume_details':return clone(resumeDetails);
      case 'mark_resume_seen':if(state.resume?.id===email&&!['switching','resuming','waiting_account'].includes(state.resume.phase))state.resume=null;return {ok:true};
      case 'open_resume_task':return {ok:true};
      case 'retry_resume_task':{
        const session=resumeDetails.find(s=>s.id===email);
        const item=session?.items.find(i=>i.thread_id===args[1]&&i.state==='failed'&&window.NX_RESUME_POLICY.retryable.includes(i.reason));
        if(!item)return {ok:false,error:'该任务不能重试'};
        item.state='waiting';item.reason='';session.phase='resuming';
        state.resume={id:session.id,phase:'resuming',done:0,failed:0,total:session.items.length};
        return {ok:true};}
      case 'read_usage_all':if(state.demo_usage_loading)return null;return window.NXMath.aggregate([...state.accounts,...archives.map(x=>({...x.account,archived:true}))],usages,args[0]||30);
      case 'read_usage':return clone(usages[email]||null);
      case 'get_usage_all':
        if(!args[0])return {ok:true,accepted:false};
        return operation('usage',null,()=>state.accounts.forEach(a=>{if(usages[a.email]?.ok)usages[a.email].fetched_at=sec();}));
      case 'get_usage':
        if(!force&&usages[email])return clone(usages[email]);
        return operation('usage',email,()=>{if(usages[email]?.ok)usages[email].fetched_at=sec();});
      case 'get_subscription':{
        const a=state.accounts.find(a=>a.email===email);if(!a)return {ok:false,error:'账号不存在'};
        if(!force&&a.membership.checked_at)return {ok:true,accepted:false};
        return operation('subscription',email,()=>{a.membership.checked_at=sec();a.membership.account_read_ok=a.ok;a.membership.error=a.ok?null:'网络或凭据暂不可用';});}
      case 'refresh':return operation('refresh',null,()=>{state.updated=sec();state.accounts.forEach(a=>{if(a.ok){a.fetched_at=sec();a.windows.forEach(w=>{if(w.resets_at<=sec())w.resets_at=sec()+600;});}});});
      case 'refresh_one':return operation('refresh',email,()=>{const a=state.accounts.find(a=>a.email===email);if(a?.ok)a.fetched_at=sec();});
      case 'switch':
        if(state.current===email)return {ok:true,already_current:true};
        return operation('switch',email,()=>{if(failNext){failNext=false;throw new Error('模拟：凭据文件被占用，仍保留原账号。');}commitSwitch(email);});
      case 'relay':
        if(state.current===email)return {ok:true,already_current:true};
        return operation('switch',email,()=>{if(failNext){failNext=false;throw new Error('模拟：凭据文件被占用，仍保留原账号。');}commitSwitch(email);});
      case 'remove':return operation('remove',email,()=>{if(email===state.current)throw new Error('请先切换，再归档当前账号');const a=state.accounts.find(a=>a.email===email);if(!a)throw new Error('账号不存在');archives.push({key:'archived-'+serial,email,archived_at:sec(),account:a});state.accounts=state.accounts.filter(a=>a.email!==email);});
      case 'get_archives':return clone(archives);
      case 'restore':return operation('restore',null,()=>{const a=archives.find(a=>a.key===email);if(a){state.accounts.push(a.account);archives=archives.filter(x=>x.key!==email);}});
      case 'add_start':return operation('add_start',null,()=>{previous=state.current;state.current=null;state.adding=true;state.add_state={previous,phase:'login'};state.add_login_status='waiting';});
      case 'adopt_current':{
        if(!state.pending)return {ok:false,error:'桌面端尚未登录；请先在 ChatGPT 桌面端完成登录'};
        const who=state.pending;return operation('adopt',null,()=>{state.pending=null;
          const a={email:who,alias:'',identity_key:who.split('@')[0],plan:'plus',ok:true,bucket:'codex',
            windows:[{label:'5h',used:0,resets_at:sec()+18000,duration_mins:300},{label:'周',used:0,resets_at:sec()+604800,duration_mins:10080}],
            fetched_at:sec(),membership:{status:'not_provided',date:null,verified:false}};
          state.accounts.push(a);state.current=who;});}
      case 'add_cancel':return operation('add_cancel',null,()=>{state.current=previous;state.adding=false;state.add_state=null;state.add_login_status=null;});
      case 'add_finish':if(state.add_login_status!=='ready')return {ok:false,error:'请先完成新账号登录'};return operation('add_finish',null,()=>{const id=state.accounts.length+1;const a={email:`new-${id}@example.com`,alias:`新账号 ${id}`,identity_key:`new-${id}`,plan:'plus',ok:true,bucket:'codex',windows:[{label:'5h',used:0,resets_at:sec()+18000,duration_mins:300},{label:'周',used:0,resets_at:sec()+604800,duration_mins:10080}],fetched_at:sec(),membership:{status:'not_provided',date:null,verified:false}};state.accounts.push(a);state.current=a.email;state.adding=false;state.add_state=null;state.add_login_status=null;});
      case 'reauth_start':return operation('reauth_start',email,()=>{previous=state.current;state.current=null;state.reauth={email,previous,phase:'login'};});
      case 'reauth_cancel':return operation('reauth_cancel',null,()=>{state.current=state.reauth?.previous||previous;state.reauth=null;});
      case 'reauth_finish':return operation('reauth_finish',state.reauth?.email,()=>{state.current=state.reauth.email;const a=state.accounts.find(a=>a.email===state.current);if(a){a.ok=true;a.err=null;a.error_code=null;a.fetched_at=sec();}state.reauth=null;});
      case 'set_preferences':{
        const update={...args[0]};
        if(state.demo_preference_error)return {ok:false,error:'设置写入失败，请重试'};
        if(state.demo_hold_preference)return new Promise(()=>{});
        if(Object.hasOwn(update,'resume_message')){
          const message=String(update.resume_message).trim();
          if(!message||Array.from(message).length>200||/[\r\n]/.test(message))return {ok:false,error:'接续消息须为 1–200 个字符的单行文本'};
          update.resume_message=message;
        }
        Object.assign(state.settings,update);return {ok:true};}

      case 'set_auto_relay_account':{
        if(!state.accounts.some(a=>a.email===email))return {ok:false,error:'账号不存在'};
        const excluded=new Set(state.settings.auto_relay_excluded);
        if(args[1])excluded.delete(email);else excluded.add(email);
        state.settings.auto_relay_excluded=[...excluded];return {ok:true};}
      case 'set_early_anchor_account':{
        if(!state.accounts.some(a=>a.email===email&&a.plan==='plus'))return {ok:false,error:'请选择 Plus 账号'};
        const selected=new Set(state.settings.early_anchor_accounts||[]);
        if(args[1])selected.add(email);else selected.delete(email);
        state.settings.early_anchor_accounts=[...selected];return {ok:true};}
      case 'set_relay_pick':{
        const a=state.accounts.find(a=>a.email===email);
        if(email&&(!a||email===state.current))return {ok:false,error:'这个账号不能设为下一棒'};
        if(email&&(state.operation||state.adding||state.reauth))return {ok:false,error:'请先完成当前操作'};
        const exhausted=a?.ok&&a.windows?.some(w=>Number.isFinite(w.used)&&w.used>=100);
        if(exhausted){
          state.relay_wait={id:(++serial).toString(16).padStart(32,'0'),email,origin:state.current};
          if(state.settings.relay_pick===email)state.settings.relay_pick=null;
        }else{
          state.settings.relay_pick=email||null;
          if(!email||state.relay_wait?.email===email)state.relay_wait=null;
        }
        const mode=exhausted?'waiting':email?'picked':'cancelled';
        return {ok:true,mode,message:{waiting:'已安排，额度恢复后自动接力',picked:'已设为下一棒',cancelled:'已取消'}[mode]};}
      case 'cancel_relay_pick':
        if(state.settings.relay_pick===email)state.settings.relay_pick=null;
        if(state.relay_wait?.email===email)state.relay_wait=null;
        return {ok:true,message:'已取消'};
      case 'consume_reset':{
        const a=state.accounts.find(a=>a.email===email),credit=a?.banked_resets?.items?.find(r=>r.id===args[1]&&r.status==='available');
        if(!credit)return {ok:false,error:'这次重置已不可用'};
        return operation('reset',email,()=>{
          a.banked_resets.items=a.banked_resets.items.filter(r=>r.id!==credit.id);
          a.banked_resets.available_count=Math.max(0,a.banked_resets.available_count-1);
          a.windows.forEach(w=>{w.used=0;});a.fetched_at=sec();
          state.operation.message='额度已重置';
        });}
      case 'launch_chatgpt':{
        const ticket=generation;
        if(state.demo_hold_launch)return new Promise(()=>{}); // Catalog-only fixed pending sample.
        await new Promise(resolve=>setTimeout(resolve,650));
        if(ticket!==generation)return {ok:false,error:'演示场景已更换'};
        if(state.demo_launch_error)return {ok:false,error:'未能打开 ChatGPT，请检查桌面端是否可用'};
        state.chatgpt_running=true;return {ok:true};}
      case 'chatgpt_status':return {running:state.chatgpt_running};
      case 'set_account_hotkey':{
        const item=state.hotkeys.find(item=>item.email===email);if(!item)return {ok:false,error:'账号不存在'};
        if(args[1]&&state.hotkeys.some(other=>other.email!==email&&other.shortcut===args[1]))return {ok:false,error:'这个快捷键已分配给其他账号'};
        item.shortcut=args[1]||null;item.registered=!!item.shortcut;return {ok:true};}
      case 'update_account_meta':{
        if(state.demo_save_error)return {ok:false,error:'保存失败，文件暂时被占用'};
        if(state.demo_hold_save)return new Promise(()=>{});
        const a=state.accounts.find(a=>a.email===email),p=args[1];
        if(!a)return {ok:false,error:'账号不存在'};
        if(Object.hasOwn(p,'alias'))a.alias=p.alias;
        if(Object.hasOwn(p,'subscription_date'))a.manual_subscription_date=p.subscription_date;
        return {ok:true,meta:{alias:a.alias,subscription_date:a.manual_subscription_date??null}};}
      case 'set_account_meta':{
        if(state.demo_save_error)return {ok:false,error:'保存失败，文件暂时被占用'};
        if(state.demo_hold_save)return new Promise(()=>{});
        const a=state.accounts.find(a=>a.email===email);if(a){a.alias=args[1];a.manual_subscription_date=args[2];}return {ok:true};}
      case 'resize_panel':case 'hide':case 'quit':return {ok:true};
      default:throw new Error('演示适配器不支持 '+method);
    }
  }
  function scenario(which){
    seed();
    if(which==='launch-pending')state.demo_hold_launch=true;
    if(which==='launch-failed')state.demo_launch_error=true;
    if(which==='first-launch-pending'||which==='first-launch-failed'){
      state.accounts=[];state.current=null;state.pending=null;
      state.demo_hold_launch=which==='first-launch-pending';state.demo_launch_error=which==='first-launch-failed';
    }
    if(which==='save-failed')state.demo_save_error=true;
    if(which==='save-pending')state.demo_hold_save=true;
    if(which==='preference-failed')state.demo_preference_error=true;
    if(which==='preference-pending')state.demo_hold_preference=true;
    if(which==='week-exhausted-auto-off'){state.accounts[0].windows[0].used=90;state.accounts[0].windows[1].used=100;}
    if(['relay-exhausted','relay-waiting','relay-exhausted-both'].includes(which)){
      state.accounts[1].windows[0].used=100;
      if(which==='relay-exhausted-both')state.accounts[1].windows[1].used=100;
      if(which==='relay-waiting')state.relay_wait={id:'00000000000000000000000000000001',email:state.accounts[1].email,origin:state.current};
    }
    if(which==='resume-progress'||which==='resume-failed'){
      const failed=which==='resume-failed';
      state.resume={id:'demo-resume',phase:failed?'failed':'resuming',done:failed?1:1,failed:failed?1:0,total:3};
      resumeDetails=[{id:'demo-resume',target:state.accounts[1].email,phase:state.resume.phase,updated_at:sec(),items:[
        {thread_id:'67cc833f-6330-5bae-a638-9232b5ddfa21',title:'研究任务 A',state:'done',reason:'new_turn_observed'},
        {thread_id:'ea10a953-d3a4-53b9-b010-6361794c2a22',title:'研究任务 B',state:failed?'failed':'acting',reason:failed?'title_unavailable_or_ambiguous':''},
        {thread_id:'c6145efd-1ac7-5980-869c-909481558def',title:'研究任务 C',state:'waiting',reason:''}
      ]}];
    }
    if(which==='resume-waiting'){
      const origin=state.accounts[0].email;
      state.settings.auto_relay=true;
      state.resume={id:'waiting:'+origin,phase:'waiting_account',done:0,failed:0,total:2};
      resumeDetails=[{id:state.resume.id,origin,target:null,phase:'waiting_account',updated_at:sec(),scheduled_at:sec()+5*3600,items:[
        {thread_id:'67cc833f-6330-5bae-a638-9232b5ddfa21',title:'等待账号的任务 A',state:'waiting',reason:''},
        {thread_id:'ea10a953-d3a4-53b9-b010-6361794c2a22',title:'等待账号的任务 B',state:'waiting',reason:''}
      ]}];
    }
    if(which==='resume-history'){
      const item=(thread_id,title,state,reason)=>({thread_id,title,state,reason});
      resumeDetails=[
        {id:'history-today',target:state.accounts[1].email,phase:'done',updated_at:sec(),items:[
          item('67cc833f-6330-5bae-a638-9232b5ddfa21','今天的任务','done','new_turn_observed')]},
        {id:'history-old',target:state.accounts[2].email,phase:'failed',updated_at:sec()-2*86400,items:[
          item('ea10a953-d3a4-53b9-b010-6361794c2a22','较早的任务','failed','switch_not_completed')]},
        {id:'history-draft',target:state.accounts[1].email,phase:'failed',updated_at:sec()-86400,items:[
          item('c6145efd-1ac7-5980-869c-909481558def','桥接不可用的任务','failed','desktop_bridge_unavailable')]}
      ];
    }
    if(which==='stale')state.accounts.forEach(a=>a.fetched_at=sec()-3600);
    if(which==='expired')state.accounts[0].windows[1].resets_at=sec()-1;
    if(which==='fail-switch')failNext=true;
    if(which==='empty'){state.accounts=[];state.current=null;usages={};state.pending='fresh-login@example.com';}
    if(which==='adding-home'){previous=state.current;state.current=null;state.adding=true;state.add_state={previous,phase:'login'};state.add_login_status='waiting';}
    if(which==='adding-ready'){previous=state.current;state.current=null;state.adding=true;state.add_state={previous,phase:'login'};state.add_login_status='ready';}
    if(which==='relay-week-priority'){
      state.current=state.accounts[0].email;
      state.accounts[1]={...state.accounts[1],alias:'上方账号',ok:true,windows:[{label:'5h',duration_mins:300,used:0,resets_at:sec()+18000},{label:'周',duration_mins:10080,used:88,resets_at:sec()+604800}]};
      state.accounts[2]={...state.accounts[2],alias:'下方账号',ok:true,plan:'plus',windows:[{label:'5h',duration_mins:300,used:54,resets_at:sec()+18000},{label:'周',duration_mins:10080,used:8,resets_at:sec()+604800}]};
      state.accounts=state.accounts.slice(0,3);
    }
    if(which==='relay-continuity'){
      const n=sec(),window=(label,duration,remaining,reset)=>({label,duration_mins:duration,used:100-remaining,resets_at:n+reset});
      state.accounts=[
        {...state.accounts[2],email:'current@example.com',alias:'当前 Pro',plan:'prolite',ok:true,windows:[window('周',10080,47,360000)]},
        {...state.accounts[1],email:'ample@example.com',alias:'充足账号',plan:'plus',ok:true,windows:[window('5h',300,100,18000),window('周',10080,53,500000)]},
        {...state.accounts[1],email:'emergency@example.com',alias:'应急账号',plan:'plus',ok:true,windows:[window('5h',300,1,10000),window('周',10080,53,580000)]},
        {...state.accounts[1],email:'stable-49@example.com',alias:'稳定 49',plan:'plus',ok:true,windows:[window('5h',300,100,18000),window('周',10080,49,400000)]},
        {...state.accounts[1],email:'stable-37@example.com',alias:'稳定 37',plan:'plus',ok:true,windows:[window('5h',300,100,18000),window('周',10080,37,300000)]},
        {...state.accounts[1],email:'empty@example.com',alias:'不可用账号',plan:'plus',ok:true,windows:[window('5h',300,100,18000),window('周',10080,0,80000)]},
      ];
      state.current=state.accounts[0].email;
      state.hotkeys=[];
    }
    if(which==='error-home'){
      state.accounts.push({...clone(state.accounts[1]),email:'sixth@example.com',alias:'第六个账号',identity_key:'sixth'});
      state.last_error={id:'demo-error',kind:'refresh',target:null,message:'操作失败；原数据未被主动删除，请重试'};
    }
    if(which==='first-run'){state.accounts=[];state.current=null;state.pending=null;state.chatgpt_running=false;usages={};}
    if(which==='long-names')state.accounts.forEach((a,i)=>a.alias=`业务自动化研发与技术支持账号 ${i+1} · 很长的账号名称用于布局回归`);
    if(which==='no-relay')state.accounts.forEach(a=>a.windows.forEach(w=>w.used=100));
    if(which==='resume-transitioning'||which==='resume-auto-sending'){
      const waiting=which==='resume-transitioning',reason=waiting?'desktop_transitioning':'';
      state.resume={id:'auto-current',phase:'resuming',done:0,failed:0,total:1};
      resumeDetails=[{id:'auto-current',target:state.current,phase:'resuming',updated_at:sec(),items:[
        {thread_id:'67cc833f-6330-5bae-a638-9232b5ddfa21',title:'核对尚未完成的步骤',state:waiting?'waiting':'acting',reason}]}];
    }
    if(which==='resume-auto-blocked'){
      state.resume={id:'automatic-blocked',phase:'failed',done:0,failed:1,attention:0,total:1};
      resumeDetails=[{id:'automatic-blocked',target:state.current,phase:'failed',updated_at:sec(),items:[
        {thread_id:'67cc833f-6330-5bae-a638-9232b5ddfa21',title:'等待自动接续的任务',state:'failed',reason:'desktop_bridge_unavailable'}]}];
    }
    if(which==='archived'){
      const account={...clone(state.accounts[1]),email:'archived@example.com',identity_key:'archived-demo'};
      archives=[{key:'demo-archive',email:account.email,archived_at:sec()-86400,account}];
      usages[account.email]={...clone(usages[state.accounts[1].email]),identity_key:account.identity_key};
    }
    if(which==='usage-empty')usages={};
    if(which==='usage-loading')state.demo_usage_loading=true;
    if(which==='usage-duplicate'){state.accounts[2].identity_key=state.accounts[1].identity_key;usages[state.accounts[2].email].identity_key=state.accounts[1].identity_key;}
    if(which==='usage-identity-changed')usages[state.accounts[0].email].identity_key='another-member';
    if(which==='chatgpt-off')state.chatgpt_running=false;
    if(which==='member-none')state.accounts.forEach(a=>a.membership={status:'not_provided',date:null,verified:false,account_checked_online:false});
    if(which==='banked-partial')state.accounts[0].banked_resets={available_count:2,items:state.accounts[0].banked_resets.items.slice(0,1)};
    if(which==='banked-unknown')state.accounts[0].banked_resets=null;
    if(which==='detail-dense')state.accounts[0].credits='12.50';
    if(which==='detail-dense-other'){state.accounts[0].credits='12.50';state.current=state.accounts[2].email;}
    if(which==='reauth'){const a=state.accounts.at(-1);a.ok=false;a.error_code='reauth_required';a.err='登录状态需要恢复';state.current=state.accounts[0].email;}
    if(which==='complete'){
      const a=state.accounts[4];a.ok=true;a.err=null;
      usages[a.email]={...clone(usages[state.accounts[0].email]),identity_key:a.identity_key,summary:{lifetimeTokens:5483200,currentStreakDays:3,longestStreakDays:10,peakDailyTokens:210000},dailyUsageBuckets:usages[state.accounts[0].email].dailyUsageBuckets.map(b=>({...b,tokens:Math.round(b.tokens*.3)}))};
    }
    if(which==='first-waiting'){state.accounts=[];state.current=null;state.pending=null;state.chatgpt_running=true;usages={};}
    if(which==='first-saving'){state.accounts=[];state.current=null;state.pending='first-account@example.com';state.operation={kind:'adopt',phase:'正在保存账号快照'};usages={};}
    if(which==='first-failed'){state.accounts=[];state.current=null;state.pending='first-account@example.com';state.last_error={id:'first-save-error',message:'演示：数据目录暂不可写，请检查权限后重试。'};usages={};}
    if(which==='connection-error')state.demo_connection_error=true;
    if(which==='refreshing')state.operation={kind:'refresh',phase:'正在读取额度 2/5'};
    if(which==='switching'){state.operation={kind:'switch',target:state.accounts[1].email,phase:'正在恢复目标账号快照'};state.switching=state.accounts[1].email;}
    if(which==='credits-zero')state.accounts[0].credits='0.00';
    if(which==='credits-unlimited')state.accounts[0].credit_info={status:'unlimited',balance:null};
    if(which==='credits-invalid')state.accounts[0].credit_info={status:'invalid',balance:null};
    if(which==='credits-precise')state.accounts[0].credits='123456789012345.6789';
    if(which==='membership-manual')state.accounts[0].manual_subscription_date='2027-01-18';
    if(which==='banked-zero')state.accounts[0].banked_resets={available_count:0,items:[]};
    if(which==='banked-many'){const a=state.accounts[0];a.banked_resets={available_count:8,items:Array.from({length:8},(_,i)=>({...a.banked_resets.items[0],expires_at:sec()+(i+1)*86400,status:i===1?'redeeming':'available'}))};}
    if(which==='single-account')state.accounts=state.accounts.slice(0,1);
    if(which==='three-accounts')state.accounts=state.accounts.slice(0,3);
    if(which==='four-accounts')state.accounts=state.accounts.slice(0,4);
    if(which==='plan-types'){const plans=['pro','plus','free','go','business','enterprise','edu','unknown'];state.accounts=plans.map((plan,i)=>({...clone(state.accounts[i%4]),email:`plan-${i}@example.com`,alias:`${plan} 账号`,plan}));state.current=state.accounts[0].email;}
    if(which==='excluded-some')state.settings.auto_relay_excluded=[state.accounts[1].email,state.accounts[3].email];
    if(which==='excluded-all')state.settings.auto_relay_excluded=state.accounts.map(a=>a.email);
    if(which==='automation-on'){state.settings.auto_relay=true;state.settings.task_continuation=true;}
    if(which==='automation-off'){state.settings.auto_relay=false;state.settings.task_continuation=false;}
    if(which==='notify-low')state.settings.notify_low=true;
    if(which==='hotkey-conflict')state.hotkeys[0].registered=false;
    if(which==='adding-unchanged'||which==='adding-existing'||which==='adding-opening'||which==='adding-saving'||which==='adding-cancelling'){
      previous=state.current;state.current=null;state.adding=true;state.add_state={previous,phase:'login'};
      state.add_login_status=which==='adding-existing'?'existing':which==='adding-unchanged'?'unchanged':'waiting';
      if(which==='adding-opening')state.operation={kind:'add_start',phase:'正在打开登录窗口'};
      if(which==='adding-saving'){state.add_login_status='ready';state.operation={kind:'add_finish',phase:'正在保存新账号'};}
      if(which==='adding-cancelling')state.operation={kind:'add_cancel',phase:'正在恢复添加前的账号'};
    }
    if(which==='reauth-login'||which==='reauth-saving'||which==='reauth-cancelling'){
      const a=state.accounts[4];a.ok=false;a.error_code='reauth_required';previous=state.current;state.current=null;state.reauth={email:a.email,previous,phase:'login'};
      if(which==='reauth-saving')state.operation={kind:'reauth_finish',phase:'正在验证并保存登录'};
      if(which==='reauth-cancelling')state.operation={kind:'reauth_cancel',phase:'正在恢复原账号'};
    }
    if(which==='detail-timeout'){state.accounts[0].ok=false;state.accounts[0].error_code='timeout';}
    if(which==='detail-timeout-empty'){state.accounts[0].ok=false;state.accounts[0].error_code='timeout';state.accounts[0].windows=[];}
    if(which==='query-forbidden'){state.accounts[0].ok=false;state.accounts[0].error_code=403;state.accounts[0].paused=true;}
    if(which==='reset-forbidden')state.accounts[0].query_warning={scope:'reset_credits',paused:true,error_code:403};
    if(which==='query-cooling'){state.accounts[0].ok=false;state.accounts[0].error_code=429;state.accounts[0].retry_at=sec()+600;}
    if(which==='monitor-degraded')state.monitor_health={state:'degraded',failures:3,retry_at:sec()+60};
    if(which==='detail-missing'){state.accounts[0].ok=false;state.accounts[0].error_code='missing_snapshot';}
    if(which==='detail-schema'){state.accounts[0].ok=false;state.accounts[0].error_code=-32601;}
    if(which==='usage-zero')Object.values(usages).forEach(u=>{if(u.ok){Object.keys(u.summary).forEach(k=>u.summary[k]=0);u.dailyUsageBuckets.forEach(b=>b.tokens=0);}});
    if(which==='usage-refreshing')state.operation={kind:'usage',phase:'正在更新个人用量'};
    const specialResume={
      'resume-unknown':['action_outcome_unknown','failed'],
      'resume-bridge-unavailable':['desktop_bridge_unavailable','failed'],
      'resume-bridge-ambiguous':['desktop_bridge_ambiguous','failed'],
      'resume-native-missing':['native_continue_unavailable','failed'],
      'resume-no-window':['desktop_not_running','failed'],
      'resume-ambiguous':['desktop_window_ambiguous','failed'],
      'resume-success':['new_turn_observed','done'],
      'resume-skipped':['task_already_running','skipped'],
      'resume-switching':['','waiting']
    };
    if(specialResume[which]){
      const [reason,status]=specialResume[which],phase=which==='resume-switching'?'switching':status==='failed'?'failed':'done';
      resumeDetails=[{id:'single-resume',target:state.accounts[1].email,phase,updated_at:sec(),items:[{thread_id:'67cc833f-6330-5bae-a638-9232b5ddfa21',title:'继续处理项目中的任务',state:status,reason}]}];
      state.resume={id:'single-resume',phase,done:status==='done'?1:0,failed:status==='failed'?1:0,attention:0,total:1};
    }
    if(which==='resume-subagent-history'){
      const parents=['67cc833f-6330-5bae-a638-9232b5ddfa21','ea10a953-d3a4-53b9-b010-6361794c2a22'];
      const child=(suffix,label,state,reason,parent=parents[0])=>({thread_id:`10000000-0000-4000-8000-0000${suffix}`,title:'后台子任务：'+label,is_subagent:true,parent_thread_id:parent,parent_title:parent?'整理研究资料':null,state,reason});
      resumeDetails=[{id:'subagent-history',target:state.accounts[1].email,phase:'failed',updated_at:sec(),items:[
        child('00000001','资料核对','skipped','duplicate_attempt'),
        child('00000002','规则检查','skipped','duplicate_attempt'),
        child('00000003','来源复核','skipped','duplicate_attempt',null),
        child('00000004','历史检查','failed','action_outcome_unknown'),
        {thread_id:parents[0],title:'整理研究资料',state:'done',reason:'new_turn_observed'},
        {thread_id:parents[1],title:'检查桌面应用',state:'done',reason:'new_turn_observed'}
      ]}];
      state.resume={id:'subagent-history',phase:'failed',done:2,failed:1,total:6};
    }
    if(which==='many')for(let i=5;i<14;i++)state.accounts.push({...clone(state.accounts[1]),email:`extra-${i}@example.com`,alias:`账号 ${i+1}`,identity_key:`extra-${i}`});
  }
  function simulate(event) {
    if(event==='login'){
      state.chatgpt_running=true;
      if(state.adding)state.add_login_status='ready';
      else if(state.reauth)state.reauth.demo_login_complete=true;
      else if(!state.accounts.length)state.pending='first-account@example.com';
    }else if(event==='complete-resume'){
      for(const session of resumeDetails){session.phase='done';for(const item of session.items){item.state='done';item.reason='new_turn_observed';}}
      if(state.resume)Object.assign(state.resume,{phase:'done',done:state.resume.total,failed:0,waiting_reason:null});
    }else if(event==='start-resume'){
      resumeDetails=[{id:'dynamic-resume',target:state.accounts[1]?.email,phase:'resuming',updated_at:sec(),items:[{thread_id:'67cc833f-6330-5bae-a638-9232b5ddfa21',title:'继续检查当前任务',state:'waiting',reason:''}]}];
      state.resume={id:'dynamic-resume',phase:'resuming',done:0,failed:0,total:1};
    }else if(event==='clear-status'){state.resume=null;state.last_error=null;}
    else if(event==='recover-service')state.demo_connection_error=false;
    else if(event==='restore-quota'){
      state.accounts.forEach(a=>{a.ok=true;a.err=null;a.error_code=null;a.fetched_at=sec();a.windows.forEach(w=>{w.used=20;w.resets_at=sec()+3600;});});
    }else throw new Error('未知演示事件');
  }
  seed();
  const params=new URLSearchParams(window.NX_PREVIEW_QUERY??location.search),requested=params.get('scenario');
  if(requested)scenario(requested);
  if(['light','dark'].includes(params.get('appearance')))state.settings.appearance=params.get('appearance');
  return {call,scenario,simulate,appearance:value=>{if(['light','dark'].includes(value))state.settings.appearance=value;},state:()=>clone(state)};
})();
