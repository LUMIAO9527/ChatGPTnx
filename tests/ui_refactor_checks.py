"""Regression cases for maintained product flows; removed compact/manual-message UI retired in 5.7.5."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from browser_session import browser_session,demo_html

CASES = [
('editing/alias-survives-refresh', 'open=edit', r'''async () => {
 const field=document.querySelector('#alias');field.value='未保存的昵称';field.focus();
 await NXDemo.call('set_preferences',{notify_low:true});window.dispatchEvent(new Event('pywebviewready'));
 await new Promise(r=>setTimeout(r,150));
 return document.querySelector('#alias')===field&&field.value==='未保存的昵称';
}'''),
('editing/message-survives-refresh', 'open=resume-message', r'''async () => {
 const field=document.querySelector('#resume-message');field.value='尚未保存的接续消息';
 await NXDemo.call('set_preferences',{notify_low:true});window.dispatchEvent(new Event('pywebviewready'));
 await new Promise(r=>setTimeout(r,150));
 return document.querySelector('#resume-message')===field&&field.value==='尚未保存的接续消息';
}'''),
('navigation/late-usage-does-not-reopen', '', r'''async () => {
 const real=NXDemo.call;let release;NXDemo.call=(method,...args)=>method==='read_usage_all'?new Promise(r=>release=()=>real(method,...args).then(r)):real(method,...args);
 document.querySelector('[data-action="usage-all"]').click();await new Promise(r=>setTimeout(r,20));
 document.querySelector('#sheet [data-action="back"]').click();document.querySelector('[data-action="settings"]').click();
 release();await new Promise(r=>setTimeout(r,120));return document.querySelector('#sheet-title').textContent==='设置';
}'''),
('navigation/late-archives-does-not-reopen', 'open=settings', r'''async () => {
 const real=NXDemo.call;let release;NXDemo.call=(method,...args)=>method==='get_archives'?new Promise(r=>release=()=>real(method,...args).then(r)):real(method,...args);
 document.querySelector('[data-disclosure="archives"] > summary').click();await new Promise(r=>setTimeout(r,20));
 document.querySelector('#sheet [data-action="back"]').click();document.querySelector('.current-identity').click();
 release();await new Promise(r=>setTimeout(r,120));return NXPreview.info().page==='detail';
}'''),
('navigation/roster-scroll-and-focus-restored', 'scenario=many&open=quota-overview', r'''async () => {
 let body=document.querySelector('.sheet-body');body.scrollTop=260;
 const row=document.querySelectorAll('.quota-overview-row')[7];row.focus({preventScroll:true});
 const top=body.scrollTop,width=body.clientWidth,email=row.dataset.email;row.click();
 document.querySelector('#sheet [data-action="back"]').click();await new Promise(r=>setTimeout(r,40));
 body=document.querySelector('.sheet-body');return body.scrollTop===top&&body.clientWidth===width&&document.activeElement.dataset.email===email;
}'''),
('roster/participation-identities-fit-with-long-names', 'scenario=long-names&open=relay-accounts', r'''() => {
 const rows=[...document.querySelectorAll('.relay-account-row')];return rows.length===NXDemo.state().accounts.length&&rows.every(row=>{
 const name=row.querySelector('.relay-account-name'),plan=row.querySelector('.badge'),r=plan.getBoundingClientRect(),b=row.getBoundingClientRect();
 return name.textContent.trim()&&plan.textContent.trim()&&r.left>=b.left&&r.right<=b.right&&plan.scrollWidth<=plan.clientWidth+1&&!row.querySelector('.choice-quotas,.current-chip');
 });
}'''),
('resume/history-is-newest-first', 'scenario=resume-history&open=resume', r'''() =>
 [...document.querySelectorAll('.resume-summary')].map(x=>x.dataset.value).join(',')==='history-today,history-draft,history-old'
'''),
('resume/clear-requires-confirmation', 'scenario=resume-history&open=resume', r'''async () => {
 document.querySelector('[data-action="resume-clear"]').click();
 if((await NXDemo.call('get_resume_details')).length!==3)return false;
 document.querySelector('[data-action="execute-resume-clear"]').click();await new Promise(r=>setTimeout(r,120));
 return document.querySelector('#sheet-title').textContent==='任务接续'&&(await NXDemo.call('get_resume_details')).length===0;
}'''),
('onboarding/no-login-cannot-save', 'scenario=first-run', r'''async () => {
 const button=document.querySelector('[data-action="adopt"]');
 return (!button||button.disabled)&&!!document.querySelector('[data-action="launch-chatgpt"]')&&(await NXDemo.call('adopt_current')).ok===false;
}'''),
('relay/no-account-has-explicit-waiting-state', 'scenario=no-relay', r'''() =>
 document.querySelector('.relay').textContent.includes('等待可用接力账号')&&!document.querySelector('[data-action="relay"]')
'''),
('settings/index-keeps-reference-rows-and-scrolls', 'open=settings', r'''() => {
 const body=document.querySelector('.sheet-body');body.scrollTop=body.scrollHeight;return body.scrollWidth===body.clientWidth&&body.querySelector('[data-disclosure=archives]').getBoundingClientRect().bottom<=body.getBoundingClientRect().bottom&&document.querySelectorAll('.settings-section').length===3;
}'''),
('resume/waiting-is-not-a-red-failure', 'scenario=resume-waiting&open=resume', r'''() =>
 !document.querySelector('.resume-zero')&&document.querySelector('.resume-body').textContent.includes('预计')&&document.querySelectorAll('.resume-task').length===2
'''),
]

def main(browser: Path, output: Path):
    results=[]
    with browser_session(browser) as engine:
        for name,query,script in CASES:
            context=engine.new_context(viewport={'width':520,'height':680},reduced_motion='reduce')
            page=context.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                page.set_content(demo_html(query));page.wait_for_timeout(260)
                passed=page.evaluate("() => Promise.race([Promise.resolve().then(() => ("+script+")()),new Promise((_,reject)=>setTimeout(()=>reject(new Error('Behavior assertion timed out')),4000))])") is True
                results.append({'name':name,'passed':passed and not errors,'errors':errors})
            except Exception as error:
                results.append({'name':name,'passed':False,'errors':errors+[str(error)]})
            finally:context.close()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"UI behavior: {sum(r['passed'] for r in results)}/{len(results)}")
    for row in results:
        if not row['passed']:print(row)
    return int(any(not r['passed'] for r in results))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--browser',required=True,type=Path)
    p.add_argument('--output',type=Path,default=ROOT/'_wip/validation/ui-behavior.json')
    args=p.parse_args();raise SystemExit(main(args.browser,args.output))
