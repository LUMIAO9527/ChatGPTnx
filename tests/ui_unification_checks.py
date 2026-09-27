"""5.7.5 fixed geometry, one presentation, collection rows and automatic-resume UX."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from browser_session import browser_session,demo_html
CASES=[]
def add(name,q,body):
 CASES.append((name,q,"async()=>{const $=s=>document.querySelector(s),sleep=ms=>new Promise(r=>setTimeout(r,ms)),rect=n=>(typeof n==='string'?$(n):n).getBoundingClientRect(),same=(a,b)=>['x','y','width','height'].every(k=>Math.abs(a[k]-b[k])<.1);"+body+'}'))
add('single/no-mode-controls-or-route','open=settings',"return NXPreview.info().height===520&&!$('[data-key=panel_mode]')&&!document.body.textContent.includes('精简面板')&&!document.body.textContent.includes('默认面板');")
add('single/old-demo-mode-does-not-open-old-ui','mode=compact',"return NXPreview.info().width===372&&NXPreview.info().height===520&&!!$('.current-card')&&!$('.compact-panel');")
add('geometry/home-detail-usage-share-card','',"const home=rect('.current-card').toJSON();$('.current-identity').click();await sleep(20);if(!same(home,rect('.current-card')))return false;$('[data-action=usage-account]').click();await sleep(60);return same(home,rect('.usage-context')); ")
add('geometry/home-aggregate-usage-share-card','',"const home=rect('.current-card').toJSON();$('[data-action=usage-all]').click();await sleep(60);return same(home,rect('.usage-context'));")
add('geometry/timeout-keeps-card-and-controls','open=detail',"const card=rect('.current-card').toJSON(),actions=rect('.detail-actions').toJSON();NXDemo.scenario('detail-timeout');await NXPreview.refresh();return same(card,rect('.current-card'))&&same(actions,rect('.detail-actions'))&&rect('.quota-failure .btn').height<=rect('.quota-failure').height;")
add('geometry/home-error-fixed-card','',"const card=rect('.current-card').toJSON();NXDemo.scenario('detail-timeout');await NXPreview.refresh();return same(card,rect('.current-card'));")
add('usage/scope-change-both-cards-identical','open=usage',"const a=rect('.usage-context').toJSON(),b=rect('.usage-summary').toJSON();$('[data-action=usage-account]').click();await sleep(60);if(!same(a,rect('.usage-context'))||!same(b,rect('.usage-summary')))return false;$('[data-action=usage-all]').click();await sleep(60);return same(a,rect('.usage-context'))&&same(b,rect('.usage-summary'));")
add('usage/loading-retains-both-card-skeletons','open=usage&scenario=usage-loading',"return rect('.usage-context').height===123&&rect('.usage-summary').height===224&&$('.usage-chart-empty').textContent.includes('正在读取');")
add('usage/no-token-caption-bigger-chart','open=usage',"return !$('.usage-caption,.coverage')&&rect('.trend').height>=88&&$('.usage-hero').children.length===2;")
add('usage/section-heading-aligned-to-card-text','open=usage',"return Math.abs(rect('.section-title').left+parseFloat(getComputedStyle($('.section-title')).paddingLeft)-rect('.usage-hero').left)<1&&Math.abs(rect('.section-title').right-parseFloat(getComputedStyle($('.section-title')).paddingRight)-rect('.usage-hero').right)<1;")
add('usage/statistics-progressive-no-extra-card','open=usage&email=work-01@example.com',"const y=rect('.usage-summary').toJSON();$('[data-disclosure=usage-metrics] > summary').click();await sleep(10);return same(y,rect('.usage-summary'))&&!!$('[data-disclosure=usage-metrics][open] .metrics-row')&&document.querySelectorAll('.usage-body > .card').length===0;")
add('settings/all-collapsed-rows-42','open=settings',"return [...document.querySelectorAll('.settings-list > *')].every(n=>rect(n).height===42)&&$('.sheet-body').scrollWidth===$('.sheet-body').clientWidth;")
add('settings/appearance-one-line-disclosure','open=settings',"const n=$('[data-disclosure=appearance]');if(n.open)return false;n.querySelector('summary').click();await sleep(10);const options=[...n.querySelectorAll('[data-key=appearance]')];return options.length===3&&options.every(b=>rect(b).height<=30)&&new Set(options.map(b=>rect(b).top)).size===1&&rect(n).height<=86;")
add('settings/appearance-save-does-not-collapse','open=settings',"$('[data-disclosure=appearance] > summary').click();$('[data-key=appearance][data-value=dark]').click();await sleep(60);await NXPreview.refresh();return document.documentElement.dataset.appearance==='dark'&&$('[data-disclosure=appearance]').open&&$('[data-key=appearance][data-value=dark]').getAttribute('aria-pressed')==='true';")
add('settings/expanded-summary-square-bottom','open=settings',"const n=$('[data-disclosure=notifications]'),s=n.querySelector('summary');s.click();await sleep(10);return getComputedStyle(s).borderBottomLeftRadius==='0px'&&getComputedStyle(s).borderBottomRightRadius==='0px'&&parseFloat(getComputedStyle(n).borderBottomLeftRadius)>0;")
add('settings/notification-inner-rows-42','open=notifications&scenario=notify-low',"return [...document.querySelectorAll('[data-disclosure=notifications] .toggle-line')].every(n=>rect(n).height===42);")
add('settings/heading-inset-like-detail','open=settings',"const h=$('.settings-heading'),summary=$('[data-disclosure=appearance] > summary');return Math.abs(rect(h).left+parseFloat(getComputedStyle(h).paddingLeft)-(rect(summary).left+parseFloat(getComputedStyle(summary).paddingLeft)))<=2;")
add('settings/history-is-second-page-and-back','open=settings&scenario=resume-history',"$('[data-action=resume-details]').click();await sleep(75);if(NXPreview.info().page!=='resume'||document.querySelectorAll('.resume-summary').length!==3)return false;$('[data-action=back]').click();await sleep(35);return NXPreview.info().page==='settings'&&!$('[data-disclosure=resume]');")
add('rows/detail-meta-reset-credits-same-height','open=detail',"return [$('.account-editor summary'),$('.reset-summary'),[...document.querySelectorAll('.detail-line')].find(n=>n.textContent.startsWith('Credits'))].every(n=>rect(n).height===42);")
add('rows/reset-items-42','open=detail&expand=reset',"return [...document.querySelectorAll('.reset-credit')].every(n=>rect(n).height===42);")
add('rows/reset-empty-42','open=detail&scenario=banked-zero&expand=reset',"return rect('.reset-credit-details .inline-empty').height===42;")
add('rows/participant-items-42-name-badge-adjacent','open=relay-accounts',"return [...document.querySelectorAll('.relay-account-row')].every(n=>{const b=rect(n.querySelector('.badge')),name=rect(n.querySelector('.relay-account-name'));return rect(n).height===42&&Math.abs(b.left-name.right-6)<1&&!n.querySelector('.current-chip,.choice-quotas');});")
add('rows/hotkey-items-42-help-not-a-row','open=hotkeys',"const h=$('.inline-help');return [...document.querySelectorAll('.hotkey-row')].every(n=>rect(n).height===42)&&rect(h).height<=20&&parseFloat(getComputedStyle(h).fontSize)===10;")
add('rows/archive-items-42','open=archives&scenario=archived',"return [...document.querySelectorAll('.archive-row')].every(n=>rect(n).height===42);")
add('rows/archive-empty-42','open=archives',"return rect('.archive-list .inline-empty').height===42;")
add('rows/history-empty-42','open=resume',"return rect('.resume-body > .empty').height===42&&parseFloat(getComputedStyle($('.resume-body h3')).fontSize)===10;")
add('rows/history-expanded-items-42','open=resume&scenario=resume-progress',"return [...document.querySelectorAll('.resume-task-row,.resume-summary')].every(n=>rect(n).height===42);")
add('dock/first-launch-only-one-feedback-surface','scenario=first-launch-pending',"const b=$('[data-action=launch-chatgpt]'),a=rect(b).toJSON(),text=b.textContent;b.click();await sleep(30);const now=$('[data-action=launch-chatgpt]');return same(a,rect(now))&&now.textContent===text&&now.disabled&&!now.querySelector('.control-feedback')&&document.querySelectorAll('.status-bar').length===1&&$('.status-dock').textContent.includes('打开');")
add('resume/no-copy-or-manual-route','open=resume&scenario=resume-auto-blocked',"return !$('[data-action=resume-manual],[data-action=copy-resume-message]')&&document.body.textContent.includes('自动发送')&&!!$('[data-action=retry-resume-task]');")
add('resume/automatic-recheck-queues-same-task','open=resume&scenario=resume-auto-blocked',"const before=(await NXDemo.call('get_resume_details'))[0].items[0].thread_id;$('[data-action=retry-resume-task]').click();await sleep(60);const s=(await NXDemo.call('get_resume_details'))[0];return s.items[0].thread_id===before&&s.phase==='resuming'&&s.items[0].state==='waiting'&&!$('[data-action=copy-resume-message]');")
add('resume/real-draft-waits-neutral','scenario=resume-draft-waiting',"return $('.resume-notice').textContent.includes('等待输入区就绪')&&!$('.resume-notice').classList.contains('error');")
add('resume/uncertain-outcome-no-send-retry','open=resume&scenario=resume-unknown',"return !$('[data-action=retry-resume-task]')&&document.body.textContent.includes('结果未确认');")
add('resume/automatic-result-confirmed-not-manual','open=resume&scenario=resume-auto-sending',"NXDemo.simulate('complete-resume');await NXPreview.refresh();return [...document.querySelectorAll('.resume-summary')].some(n=>n.textContent.includes('1/1'))&&NXDemo.state().resume?.phase==='done'&&NXDemo.state().resume?.waiting_reason===null&&(await NXDemo.call('get_resume_details'))[0].items[0].reason==='new_turn_observed';")
add('participants/direct-long-name-entry-no-overflow','open=relay-accounts&scenario=long-names',"const b=$('.sheet-body'),rows=[...document.querySelectorAll('.relay-account-row')];return b.scrollWidth===b.clientWidth&&rows.every(n=>{const r=rect(n),sw=rect(n.querySelector('.switch')),badge=rect(n.querySelector('.badge'));return sw.right<=r.right&&badge.right<sw.left&&r.height===42;});")
add('policy/retry-does-not-include-unknown-effects','',"return !NX_RESUME_POLICY.retryable.includes('action_outcome_unknown')&&!NX_RESUME_POLICY.retryable.includes('start_not_observed')&&!NX_RESUME_POLICY.retryable.includes('input_guard_timeout');")

def main(browser,output):
 results=[]
 with browser_session(browser) as engine:
  for theme in ('light','dark'):
   for name,q,js in CASES:
    context=engine.new_context(viewport={'width':520,'height':700},color_scheme=theme,reduced_motion='reduce');p=context.new_page();errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
    try:
     p.set_content(demo_html(q+'&appearance='+theme));p.wait_for_function('window.NX_CASE_READY',timeout=6000);passed=p.evaluate(js) is True
    except Exception as e:passed=False;errors.append(str(e))
    results.append({'name':name,'appearance':theme,'passed':passed and not errors,'errors':errors});context.close()
 output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(results,ensure_ascii=False,indent=2))
 print('Unified UI:',sum(r['passed'] for r in results),'/',len(results))
 for r in results:
  if not r['passed']:print(r)
 return int(any(not r['passed'] for r in results))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--browser',required=True,type=Path);p.add_argument('--output',type=Path,default=ROOT/'docs/validation/ui-unification-tests.json');a=p.parse_args();raise SystemExit(main(a.browser,a.output))
