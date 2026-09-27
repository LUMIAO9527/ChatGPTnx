"""Regression cases for maintained product flows; removed compact/manual-message UI retired in 5.7.5."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from browser_session import browser_session,demo_html

CASES = [
('detail/date-presence-does-not-move-any-action', 'open=detail', r'''async()=>{
 const box=()=>[...document.querySelectorAll('#sheet button')].map(n=>[n.dataset.action,n.getBoundingClientRect().y,n.getBoundingClientRect().height]);const before=box();
 NXDemo.scenario('member-none');await NXPreview.refresh();return JSON.stringify(before)===JSON.stringify(box())&&document.querySelector('.detail-expiry-note').textContent.includes('未录入到期时间');
}'''),
('detail/missing-date-is-reserved-text-not-a-button', 'open=detail&scenario=member-none', r'''()=>{
 const note=document.querySelector('.detail-expiry-note');note.click();return NXPreview.info().page==='detail'&&note.tagName==='DIV'&&!note.hasAttribute('tabindex')&&!note.hasAttribute('data-action');
}'''),
('detail/date-save-roundtrip-no-success-bar-shift', 'open=detail&scenario=member-none', r'''async()=>{
 const before=document.querySelector('.danger-row').getBoundingClientRect().y;
 document.querySelector('.account-editor summary').click();document.querySelector('#manual-date').value='2027-03-15';document.querySelector('[data-action="save-expiry"]').click();await new Promise(r=>setTimeout(r,80));document.querySelector('.account-editor summary').click();
 return NXPreview.info().page==='detail'&&document.querySelector('.detail-expiry-note').textContent.includes('2027/03/15')&&document.querySelector('.danger-row').getBoundingClientRect().y===before&&!document.querySelector('#sheet .status-notification')&&NXDemo.state().accounts[0].manual_subscription_date==='2027-03-15';
}'''),
('detail/clearing-date-keeps-placeholder-and-height', 'open=detail&scenario=membership-manual', r'''async()=>{
 const before=document.querySelector('.danger-row').getBoundingClientRect().y;document.querySelector('.account-editor summary').click();document.querySelector('#manual-date').value='';document.querySelector('[data-action="save-expiry"]').click();await new Promise(r=>setTimeout(r,80));document.querySelector('.account-editor summary').click();
 return document.querySelector('.danger-row').getBoundingClientRect().y===before&&NXDemo.state().accounts[0].manual_subscription_date===null&&!!document.querySelector('.detail-expiry-note');
}'''),
('edit/failure-keeps-fields-date-focus-and-button', 'open=edit&scenario=save-failed', r'''async()=>{
 const field=document.querySelector('#alias'),date=document.querySelector('#manual-date'),b=document.querySelector('[data-action="save-alias"]');field.value='未保存的名字';date.value='2027-06-18';const top=b.getBoundingClientRect().y;
 b.click();await new Promise(r=>setTimeout(r,80));return document.querySelector('#alias')===field&&field.value==='未保存的名字'&&date.value==='2027-06-18'&&document.querySelector('#form-error').textContent.includes('文件')&&b.getBoundingClientRect().y===top&&!b.disabled&&!field.hasAttribute('aria-invalid');
}'''),
('edit/background-refresh-preserves-date-selection', 'open=edit', r'''async()=>{
 const date=document.querySelector('#manual-date');date.value='2027-09-22';date.focus();await NXDemo.call('set_preferences',{notify_low:true});await NXPreview.refresh();
 return document.querySelector('#manual-date')===date&&document.activeElement===date&&date.value==='2027-09-22';
}'''),
('feedback/launch-one-dock-original-action-label', 'scenario=first-waiting', r'''async()=>{
 const sel='[data-action="launch-chatgpt"]',snapshot=()=>{const b=document.querySelector(sel),r=b.getBoundingClientRect(),s=getComputedStyle(b);return [r.x,r.y,r.width,r.height,s.backgroundColor,s.borderRadius];};
 let release,calls=0;const real=NXDemo.call;NXDemo.call=(m,...a)=>m==='launch_chatgpt'?(calls++,new Promise(r=>release=r)):real(m,...a);
 const before=snapshot();document.querySelector(sel).click();await new Promise(r=>setTimeout(r,20));document.querySelector(sel).click();
 const during=snapshot(),busy=document.querySelector(sel).disabled&&document.querySelectorAll('.status-dock .status-bar').length===1&&!document.querySelector(sel).querySelector('.control-feedback');
 release({ok:true});await new Promise(r=>setTimeout(r,40));return calls===1&&busy&&JSON.stringify(before)===JSON.stringify(during)&&JSON.stringify(before)===JSON.stringify(snapshot())&&!document.querySelector('#toast,.toast,[data-action=dismiss-feedback]')&&document.querySelectorAll('.status-notification').length===1&&document.querySelector('.status-bar').textContent.includes('等待登录')&&document.querySelector(sel).textContent.includes('回到 ChatGPT');
}'''),
('feedback/launch-error-one-status-and-retryable', 'scenario=first-launch-failed', r'''async()=>{
 document.querySelector('[data-action="launch-chatgpt"]').click();await new Promise(r=>setTimeout(r,700));
 const b=document.querySelector('[data-action="launch-chatgpt"]');return !b.disabled&&!b.hasAttribute('aria-busy')&&document.querySelectorAll('.status-notification').length===1&&document.querySelector('.status-bar').offsetHeight===38&&!document.querySelector('#toast');
}'''),
('feedback/dismiss-restores-underlying-wait-status', 'scenario=first-launch-failed', r'''async()=>{
 document.querySelector('[data-action="launch-chatgpt"]').click();await new Promise(r=>setTimeout(r,700));document.querySelector('[data-action="dismiss-feedback"]').click();return document.querySelectorAll('.status-notification').length===1&&!document.querySelector('[data-action="dismiss-feedback"]')&&document.querySelector('.status-bar').textContent.includes('等待登录');
}'''),
('feedback/old-timer-cannot-clear-new-ticket', '', r'''()=>{
 const root=document.createElement('div');root.innerHTML='<button data-action="test">保存</button>';document.body.append(root);const timers=[];const manager=NXFeedback.create({root,clock:{setTimeout:f=>(timers.push(f),timers.length),clearTimeout:()=>{}}});
 const b=root.querySelector('button'),first=manager.begin(b);manager.finish(first,{text:'第一次完成'});const second=manager.begin(b,'第二次保存');timers[0]();manager.finish(first,{text:'旧返回'});
 const good=b.disabled&&b.getAttribute('aria-busy')==='true'&&b.textContent.includes('第二次保存');manager.finish(second);const restored=!b.disabled&&b.textContent==='保存';root.remove();return good&&restored;
}'''),
('feedback/aria-state-escapes-text-and-restores', '', r'''()=>{
 const root=document.createElement('div');root.innerHTML='<button data-action="test" aria-label="原标签">测试</button>';document.body.append(root);const manager=NXFeedback.create({root}),b=root.querySelector('button'),t=manager.begin(b,'<img src=x onerror=alert(1)>');
 const safe=!b.querySelector('img')&&b.getAttribute('aria-label').startsWith('原标签，')&&b.getAttribute('aria-busy')==='true';manager.finish(t);const restored=b.getAttribute('aria-label')==='原标签'&&!b.hasAttribute('aria-busy')&&!b.disabled;root.remove();return safe&&restored;
}'''),
('feedback/late-save-never-overwrites-new-edit', 'open=edit', r'''async()=>{
 const real=NXDemo.call;let release;NXDemo.call=(m,...a)=>m==='update_account_meta'?new Promise(r=>release=()=>real(m,...a).then(r)):real(m,...a);
 document.querySelector('#alias').value='保存原账号';document.querySelector('[data-action="save-alias"]').click();await new Promise(r=>setTimeout(r,20));
 document.querySelector('#sheet [data-action="back"]').click();await NXPreview.open(new URLSearchParams('open=edit&email=backup@example.com'));
 const f=document.querySelector('#alias');f.value='新页面尚未保存';release();await new Promise(r=>setTimeout(r,80));
 return NXPreview.info().page==='detail'&&document.querySelector('#alias')===f&&f.value==='新页面尚未保存'&&!document.querySelector('.status-notification');
}'''),
('feedback/late-clear-never-navigates-current-page', 'scenario=resume-history&open=resume', r'''async()=>{
 const real=NXDemo.call;let release;NXDemo.call=(m,...a)=>m==='clear_resume_history'?new Promise(r=>release=()=>real(m,...a).then(r)):real(m,...a);
 document.querySelector('[data-action="resume-clear"]').click();document.querySelector('[data-action="execute-resume-clear"]').click();await new Promise(r=>setTimeout(r,20));
 await NXPreview.open(new URLSearchParams('open=edit'));const f=document.querySelector('#alias');f.value='保留清理期间编辑';release();await new Promise(r=>setTimeout(r,80));
 return NXPreview.info().page==='detail'&&document.querySelector('#alias')===f&&f.value==='保留清理期间编辑';
}'''),
('feedback/late-restore-never-replaces-current-edit', 'scenario=archived&open=archives', r'''async()=>{
 const real=NXDemo.call;let release;NXDemo.call=(m,...a)=>m==='restore'?new Promise(r=>release=()=>real(m,...a).then(r)):real(m,...a);
 document.querySelector('[data-action="restore"]').click();await new Promise(r=>setTimeout(r,20));await NXPreview.open(new URLSearchParams('open=edit'));
 const f=document.querySelector('#alias');f.value='保留恢复期间编辑';release();await new Promise(r=>setTimeout(r,80));return NXPreview.info().page==='detail'&&document.querySelector('#alias')===f&&f.value==='保留恢复期间编辑';
}'''),
('feedback/settings-failure-no-false-toggle', 'scenario=preference-failed&open=settings', r'''async()=>{
 const b=document.querySelector('[data-action="toggle"]'),key=b.dataset.key,before=NXDemo.state().settings[key];b.click();await new Promise(r=>setTimeout(r,60));
 return NXDemo.state().settings[key]===before&&document.querySelector('[data-action="toggle"]').getAttribute('aria-checked')===String(before)&&document.querySelector('.status-notification .status-bar').offsetHeight===38;
}'''),
('feedback/long-message-no-horizontal-overflow', '', r'''()=>{
 const root=document.createElement('div');root.style.width='260px';root.innerHTML=NXFeedback.status({text:'非常长的状态信息'.repeat(80),tone:'error',action:'error'});document.body.append(root);const bar=root.firstElementChild;
 const result=bar.offsetHeight===40&&bar.clientWidth>=258&&bar.scrollWidth<=bar.clientWidth+1&&bar.title.length>300&&bar.querySelector('.status-text').scrollWidth>bar.querySelector('.status-text').clientWidth;root.remove();return result;
}'''),
('feedback/refresh-detection-in-control-not-toast', 'scenario=first-waiting', r'''async()=>{
 const b=document.querySelector('[data-action="refresh-state"]'),rect=b.getBoundingClientRect();b.click();await new Promise(r=>setTimeout(r,50));const after=document.querySelector('[data-action="refresh-state"]');
 return after.getBoundingClientRect().width===rect.width&&after.getBoundingClientRect().height===rect.height&&after.textContent.includes('已重新检测')&&!document.querySelector('#toast,[data-action=dismiss-feedback]')&&document.querySelectorAll('.status-notification').length===1&&document.querySelector('.status-bar').textContent.includes('等待登录');
}'''),
('demo/pending-state-theme-can-change-without-restarting', 'scenario=first-launch-pending', r'''async()=>{
 document.querySelector('[data-action="launch-chatgpt"]').click();await new Promise(r=>setTimeout(r,20));await NXPreview.appearance('dark');
 return document.documentElement.dataset.appearance==='dark'&&document.querySelector('[data-action="launch-chatgpt"]').disabled&&document.querySelector('.status-dock').textContent.includes('打开');
}'''),
('status/anatomy-home-resume', 'scenario=resume-progress', r'''()=>{const root=document.querySelector('#sheet:not([hidden])')||document.querySelector('#home'),bars=[...root.querySelectorAll('.status-bar')].filter(n=>n.offsetParent!==null);return bars.length>0&&bars.every(n=>n.offsetHeight===38&&getComputedStyle(n).borderRadius==='999px'&&n.querySelector('.status-text')&&n.scrollWidth<=n.clientWidth+1);}'''),
('status/anatomy-home-waiting', 'scenario=resume-waiting', r'''()=>{const root=document.querySelector('#sheet:not([hidden])')||document.querySelector('#home'),bars=[...root.querySelectorAll('.status-bar')].filter(n=>n.offsetParent!==null);return bars.length>0&&bars.every(n=>n.offsetHeight===38&&getComputedStyle(n).borderRadius==='999px'&&n.querySelector('.status-text')&&n.scrollWidth<=n.clientWidth+1);}'''),
('status/anatomy-home-error', 'scenario=error-home', r'''()=>{const root=document.querySelector('#sheet:not([hidden])')||document.querySelector('#home'),bars=[...root.querySelectorAll('.status-bar')].filter(n=>n.offsetParent!==null);return bars.length>0&&bars.every(n=>n.offsetHeight===38&&getComputedStyle(n).borderRadius==='999px'&&n.querySelector('.status-text')&&n.scrollWidth<=n.clientWidth+1);}'''),
('status/anatomy-add', 'scenario=adding-home&open=add', r'''()=>{const root=document.querySelector('#sheet:not([hidden])')||document.querySelector('#home'),bars=[...root.querySelectorAll('.status-bar')].filter(n=>n.offsetParent!==null);return bars.length>0&&bars.every(n=>n.offsetHeight===38&&getComputedStyle(n).borderRadius==='999px'&&n.querySelector('.status-text')&&n.scrollWidth<=n.clientWidth+1);}'''),
('status/anatomy-reauth', 'scenario=reauth-login&open=reauth&email=remote@example.com', r'''()=>{const root=document.querySelector('#sheet:not([hidden])')||document.querySelector('#home'),bars=[...root.querySelectorAll('.status-bar')].filter(n=>n.offsetParent!==null);return bars.length>0&&bars.every(n=>n.offsetHeight===38&&getComputedStyle(n).borderRadius==='999px'&&n.querySelector('.status-text')&&n.scrollWidth<=n.clientWidth+1);}'''),
('status/anatomy-onboarding', 'scenario=first-saving', r'''()=>{const root=document.querySelector('#sheet:not([hidden])')||document.querySelector('#home'),bars=[...root.querySelectorAll('.status-bar')].filter(n=>n.offsetParent!==null);return bars.length>0&&bars.every(n=>n.offsetHeight===38&&getComputedStyle(n).borderRadius==='999px'&&n.querySelector('.status-text')&&n.scrollWidth<=n.clientWidth+1);}'''),
('status/anatomy-switch', 'scenario=switching&open=confirm', r'''()=>{const root=document.querySelector('#sheet:not([hidden])')||document.querySelector('#home'),bars=[...root.querySelectorAll('.status-bar')].filter(n=>n.offsetParent!==null);return bars.length>0&&bars.every(n=>n.offsetHeight===38&&getComputedStyle(n).borderRadius==='999px'&&n.querySelector('.status-text')&&n.scrollWidth<=n.clientWidth+1);}'''),
]

def main(browser:Path,output:Path,appearance:str='both'):
 results=[]
 with browser_session(browser) as engine:
  for theme in (['light','dark'] if appearance=='both' else [appearance]):
   for name,query,script in CASES:
    context=engine.new_context(viewport={'width':520,'height':680},color_scheme=theme,reduced_motion='reduce')
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    try:
     page.set_content(demo_html(query+'&appearance='+theme));page.wait_for_function('window.NX_CASE_READY',timeout=5000)
     passed=page.evaluate("() => Promise.race([Promise.resolve().then(() => ("+script+")()),new Promise((_,reject)=>setTimeout(()=>reject(new Error('Behavior assertion timed out')),4000))])") is True
    except Exception as error:passed=False;errors.append(str(error))
    results.append({'name':name,'appearance':theme,'passed':passed and not errors,'errors':errors});context.close();print(theme,name,passed and not errors,errors,flush=True)
 output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(results,ensure_ascii=False,indent=2))
 print(f'Feedback UI: {sum(r["passed"] for r in results)}/{len(results)}')
 for r in results:
  if not r['passed']:print(r)
 return int(any(not r['passed'] for r in results))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--browser',required=True,type=Path);p.add_argument('--output',type=Path,default=ROOT/'docs/validation/ui-feedback-tests.json');p.add_argument('--appearance',choices=['light','dark','both'],default='both');a=p.parse_args();raise SystemExit(main(a.browser,a.output,a.appearance))
