/* First use occupies the full panel, sharing the action-led workflow geometry. */
'use strict';
window.NXViews ??= {};
window.NXViews.onboarding = ({data,ui,config,esc,icon,tool,busy,statusBar,statusRegion,brandMark,connected=true,bridgeError=''}) => {
  const header=tools=>`<header class="onboarding-head"><div class="brand pywebview-drag-region">${brandMark()}ChatGPTnx</div>${config.demo?'<span class="demo-tag">演示</span>':''}${tools?tool('settings','settings','设置'):''}</header>`;
  if(data.location){
    const installing=data.operation?.kind==='location';
    const changed=ui.locationTarget&&ui.locationTarget!==data.location.recommended;
    const target=changed?ui.locationTarget:data.location.recommended;
    const canRelocate=data.location.can_relocate!==false;
    const ready=connected&&!bridgeError;
    const footer=canRelocate
      ?`<footer class="onboarding-foot"><button class="control control--large secondary" data-action="location-keep" ${busy?'disabled':''} title="当前：${esc(data.location.current)}">继续使用当前位置</button><button class="control control--large primary" data-action="location-install" ${busy?'disabled':''}>${changed?'安装到所选位置':'安装到推荐位置'} ${icon('arrow')}</button></footer>`
      :`<footer class="onboarding-foot single"><button class="control control--large primary" data-action="location-keep" ${busy?'disabled':''}>继续使用当前位置 ${icon('arrow')}</button></footer>`;
    return `${header(false)}
    <div class="onboarding-main"><span class="eyebrow">首次设置</span><div class="flow-symbol">${icon('folder')}</div><h1>${installing?'正在安装…':'选择程序文件夹'}</h1><p class="flow-subtitle">${installing?(data.operation.phase||'正在准备…'):'程序和账号数据都会保存在这里。'}</p>
    <button class="location-row" data-action="location-browse" title="${esc(target)}" ${busy||!ready?'disabled':''}><span class="location-mark">${icon('folder')}</span><span class="location-copy"><strong class="location-path">${esc(target)}</strong><span class="location-label">${!ready?'正在连接本地应用…':changed?'所选位置':'推荐位置'}</span></span>${icon('chevron')}</button>
    ${statusRegion('')}</div>
    ${ready?footer:''}`;
  }
  const saving=data.operation?.kind==='adopt', ready=!!data.pending, running=data.chatgpt_running!==false, failed=!!data.last_error;
  const failure=!saving&&failed;
  const failCode=failed?(data.last_error?.code||''):'';
  const failCopy=failCode==='credential'
    ?{sub:'登录凭据正在更新。',steps:['在 ChatGPT 桌面端重新登录','回到这里再点“确认保存账号”']}
    :failCode==='protect'
    ?{sub:'当前 Windows 用户无法加密凭据。',steps:['用平时登录的 Windows 用户运行程序','重启电脑后再试']}
    :failCode==='write'
    ?{sub:'程序文件夹暂时无法写入。',steps:['把程序文件夹换到 D:\\ChatGPTnx','重新打开后再点“确认保存账号”']}
    :{sub:'保存时遇到意外问题。',steps:['重启程序后再试','仍失败请在“设置 → 关于”联系支持']};
  const title=!connected?'从这里，开始接力。':saving?'正在保存账号':failure?'保存未完成':ready?'账号已就绪':running?'等待你完成登录':'从这里，开始接力。';
  const subtitle=!connected?'连接本地应用后，继续设置你的第一个账号。':saving?'保存完成后进入首页。':failure?failCopy.sub:ready?'确认后加入你的账号列表。':running?'在 ChatGPT 桌面端登录，完成后回到这里。':'先连接你的第一个 ChatGPT 账号。';
  const status=!connected?'正在连接本地应用…':saving?data.operation.phase:failure?'保存未完成':ready?'已检测到桌面端登录账号':running?'正在等待登录':'ChatGPT 桌面端未运行';
  const flow=failed
    ?`<ol class="flow-steps flow-steps--advice" aria-label="处理提示">${failCopy.steps.map((step,index)=>`<li><span>${index+1}</span>${esc(step)}</li>`).join('')}</ol>`
    :`<ol class="flow-steps" aria-label="设置进度"><li class="${ready?'done':'active'}"><span>${ready?icon('check'):'1'}</span>登录桌面端</li><li class="${ready?'active':''}"><span>2</span>保存账号</li></ol>`;
  const actions=ready
    ?`<button class="control control--large secondary" data-action="launch-chatgpt" ${busy?'disabled':''}>回到桌面端</button><button class="control control--large primary control--confirmation" data-action="adopt" ${busy?'disabled':''}>确认保存账号 ${icon('arrow')}</button>`
    :`<button class="control control--large secondary" data-action="refresh-state" ${busy?'disabled':''}>重新检测</button><button class="control control--large primary" data-action="launch-chatgpt" ${busy?'disabled':''}>${running?'回到 ChatGPT':'启动 ChatGPT'} ${icon('arrow')}</button>`;
  return `${header(true)}
    <div class="onboarding-main"><span class="eyebrow">首次设置</span><div class="flow-symbol">${icon(saving?'refresh':failed?'info':ready?'check':'baton',saving?'spinner':'')}</div><h1>${title}</h1><p class="flow-subtitle">${subtitle}</p>
    ${flow}
    ${statusRegion(statusBar({text:failed?'保存未完成 · 未加入账号列表':ready&&!saving?data.pending:status,tone:failed?'error':saving?'progress':ready?'success':'neutral',symbol:failed?'info':ready&&!saving?'user':running?'clock':'external'}))}</div>
    ${connected&&!bridgeError?`<footer class="onboarding-foot">${actions}</footer>`:''}`;
};