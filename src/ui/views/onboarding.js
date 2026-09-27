/* First use occupies the full panel, sharing the action-led workflow geometry. */
'use strict';
window.NXViews ??= {};
window.NXViews.onboarding = ({data,ui,config,esc,icon,tool,busy,statusBar,statusRegion,brandMark}) => {
  const saving=data.operation?.kind==='adopt', ready=!!data.pending, running=data.chatgpt_running!==false;
  const title=saving?'正在保存账号':ready?'账号已就绪':running?'等待你完成登录':'从这里，开始接力。';
  const subtitle=saving?'保存完成后进入首页。':ready?'确认后加入你的账号列表。':running?'在 ChatGPT 桌面端登录，完成后回到这里。':'先连接你的第一个 ChatGPT 账号。';
  const status=saving?data.operation.phase:ready?'已检测到桌面端登录账号':running?'正在等待登录':'ChatGPT 桌面端未运行';
  const actions=ready
    ?`<button class="btn secondary" data-action="launch-chatgpt" ${busy?'disabled':''}>回到桌面端</button><button class="btn primary" data-action="adopt" ${busy?'disabled':''}>确认保存账号 ${icon('arrow')}</button>`
    :`<button class="btn secondary" data-action="refresh-state" ${busy?'disabled':''}>重新检测</button><button class="btn primary" data-action="launch-chatgpt" ${busy?'disabled':''}>${running?'回到 ChatGPT':'启动 ChatGPT'} ${icon('arrow')}</button>`;
  return `<header class="onboarding-head"><div class="brand pywebview-drag-region">${brandMark()}ChatGPTnx</div>${config.demo?'<span class="demo-tag">演示</span>':''}${tool('settings','settings','设置')}</header>
    <div class="onboarding-main"><span class="eyebrow">首次设置</span><div class="flow-symbol">${icon(saving?'refresh':ready?'check':'baton',saving?'spinner':'')}</div><h1>${title}</h1><p class="flow-subtitle">${subtitle}</p>
    <ol class="flow-steps" aria-label="设置进度"><li class="${ready?'done':'active'}"><span>${ready?icon('check'):'1'}</span>登录桌面端</li><li class="${ready?'active':''}"><span>2</span>保存账号</li></ol>
    ${statusRegion(statusBar({text:data.last_error?'保存未完成 · 查看原因':ready&&!saving?data.pending:status,tone:data.last_error?'error':saving?'progress':ready?'success':'neutral',symbol:ready&&!saving?'user':running?'clock':'external',action:data.last_error?'error':''}))}</div>
    <footer class="onboarding-foot">${actions}</footer>`;
};
