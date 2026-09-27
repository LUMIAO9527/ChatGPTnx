"""Regression cases for maintained product flows; removed compact/manual-message UI retired in 5.7.5."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from browser_session import browser_session,demo_html

CASES = [
('first-use/full-panel-not-empty-dashboard', 'scenario=first-run', r'''()=>document.querySelector('#home').classList.contains('is-onboarding')&&!document.querySelector('.roster')&&!document.querySelector('[data-action="add"]')&&document.querySelector('.onboarding-foot').getBoundingClientRect().bottom<=document.querySelector('#app').getBoundingClientRect().bottom'''),
('first-use/waiting-has-clear-primary-action', 'scenario=first-waiting', r'''()=>document.querySelector('.onboarding-main').textContent.includes('等待你完成登录')&&document.querySelector('.onboarding-foot .primary').textContent.includes('回到 ChatGPT')'''),
('first-use/adoption-never-overlaps-write', 'scenario=first-saving', r'''()=>document.querySelector('[data-action="adopt"]').disabled&&document.querySelector('.onboarding-main').textContent.includes('正在保存')'''),
('home/long-relay-name-preserves-card-height-and-quota', 'scenario=long-names', r'''()=>{const relay=document.querySelector('.relay'),label=relay.querySelector('strong'),quota=relay.querySelector('small');return relay.clientHeight===68&&label.scrollWidth>label.clientWidth&&quota.scrollWidth<=quota.clientWidth+1;}'''),
('choices/participation-single-row-name-plan-switch', 'open=relay-accounts&scenario=long-names', r'''()=>[...document.querySelectorAll('.relay-account-row')].every(row=>{
 const name=row.querySelector('.relay-account-name'),plan=row.querySelector('.badge'),sw=row.querySelector('.switch');
 return name&&plan&&sw&&row.getBoundingClientRect().height===42&&!row.querySelector('.choice-quotas,.current-chip')&&name.getBoundingClientRect().right<=plan.getBoundingClientRect().left;})'''),
('choices/membership-does-not-get-clipped', 'open=relay-accounts&scenario=plan-types', r'''()=>[...document.querySelectorAll('.relay-account-row .badge')].every(q=>q.scrollWidth<=q.clientWidth+1)&&document.querySelector('[data-disclosure="relay"]').textContent.includes('Enterprise')'''),
('choices/toggle-is-persisted-across-refresh', 'open=relay-accounts', r'''async()=>{const sw=document.querySelector('.relay-account-row .switch'),email=sw.dataset.email;sw.click();await new Promise(r=>setTimeout(r,120));await NXPreview.refresh();return NXDemo.state().settings.auto_relay_excluded.includes(email)&&document.querySelector('.relay-account-row .switch').getAttribute('aria-checked')==='false';}'''),
('choices/switch-knob-stays-inside-control', 'open=relay-accounts', r'''()=>[...document.querySelectorAll('.relay-account-row .switch')].every(s=>s.querySelector('i').getBoundingClientRect().right<=s.getBoundingClientRect().right-1)'''),
('credits/unknown-stays-visible', 'open=detail', r'''()=>[...document.querySelectorAll('.detail-line')].some(n=>n.textContent==='Credits未提供')'''),
('credits/zero-is-not-hidden', 'open=detail&scenario=credits-zero', r'''()=>[...document.querySelectorAll('.detail-line')].some(n=>n.textContent==='Credits0.00')'''),
('credits/unlimited-is-not-zero', 'open=detail&scenario=credits-unlimited', r'''()=>[...document.querySelectorAll('.detail-line')].some(n=>n.textContent==='Credits不限额')'''),
('credits/precision-kept', 'open=detail&scenario=credits-precise', r'''()=>document.querySelector('.detail-compact').textContent.includes('123456789012345.6789')'''),
('credits/malformed-does-not-spoil-detail', 'open=detail&scenario=credits-invalid', r'''()=>document.querySelector('.detail-compact').textContent.includes('Credits数据异常')&&document.querySelectorAll('#sheet .quota-bars .track').length===2'''),
('credits/current-detail-fits-normal-frame', 'open=detail&scenario=detail-dense', r'''()=>{const b=document.querySelector('.sheet-body');return b.scrollHeight<=b.clientHeight+1;}'''),
('usage/single-account-fits', 'open=usage&email=work-01%40example.com', r'''()=>{const b=document.querySelector('.sheet-body');return b.scrollHeight<=b.clientHeight+1;}'''),
('demo/reset-invalidates-late-operations', '', r'''async()=>{await NXDemo.call('switch','work-02@example.com');NXDemo.scenario('first-run');await new Promise(r=>setTimeout(r,1650));return NXDemo.state().accounts.length===0&&NXDemo.state().current===null;}'''),
('demo/add-login-save-roundtrip', 'open=add', r'''async()=>{
 document.querySelector('[data-action="start-add"]').click();await new Promise(r=>setTimeout(r,1100));NXDemo.simulate('login');await NXPreview.refresh();
 const finish=document.querySelector('[data-action="finish-add"]');if(!finish||finish.disabled)return false;finish.click();await new Promise(r=>setTimeout(r,1100));return NXDemo.state().accounts.length===6&&!NXDemo.state().adding;}'''),
('demo/message-validation-matches-product', '', r'''async()=>{const before=NXDemo.state().settings.resume_message;const r=await NXDemo.call('set_preferences',{resume_message:'x\ny'});return r.ok===false&&NXDemo.state().settings.resume_message===before;}'''),
]

def main(browser,output):
 results=[]
 with browser_session(browser) as engine:
  for name,query,script in CASES:
   context=engine.new_context(viewport={'width':520,'height':680},reduced_motion='reduce');page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   try:
    page.set_content(demo_html(query));page.wait_for_function('window.NX_CASE_READY',timeout=5000)
    passed=page.evaluate("() => Promise.race([Promise.resolve().then(() => ("+script+")()),new Promise((_,reject)=>setTimeout(()=>reject(new Error('Behavior assertion timed out')),4000))])") is True
   except Exception as e:passed=False;errors.append(str(e))
   results.append({'name':name,'passed':passed and not errors,'errors':errors});context.close()
  # Exercise the delivered standalone file (injected because managed Chromium blocks file navigation).
  context=engine.new_context(viewport={'width':1440,'height':960});page=context.new_page();errors=[];requests=[]
  page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda req:requests.append(req.url))
  try:
   page.set_content((ROOT/'docs/ui-explorer.html').read_text())
   page.locator('#status').filter(has_text="可操作").wait_for(timeout=5000)
   frame=page.frames[1]
   results.append({'name':'explorer/initial-flow-operable','passed':frame.locator('.onboarding-main').count()==1,'errors':list(errors)})
   page.locator('[data-simulate="login"]').click();frame.wait_for_selector('[data-action="adopt"]');frame.locator('[data-action="adopt"]').click()
   frame.wait_for_selector('.current-card',timeout=5000)
   results.append({'name':'explorer/external-login-then-real-ui-save','passed':frame.evaluate('NXDemo.state().accounts.length')==1,'errors':list(errors)})
   page.locator('#search').fill('参与账号');page.locator('[data-case="relay-accounts"]').click()
   frame=page.frames[1];frame.wait_for_selector('.relay-account-row')
   page.locator('[data-theme="dark"]').click();frame.locator('html[data-appearance="dark"]').wait_for(timeout=5000)
   results.append({'name':'explorer/navigation-and-live-theme','passed':frame.locator('.relay-account-row').count()==5,'errors':list(errors)})
   results.append({'name':'explorer/no-network-requests','passed':not requests,'errors':requests})
  except Exception as e:results.append({'name':'explorer/runtime','passed':False,'errors':errors+[str(e)]})
  context.close()
 output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(results,ensure_ascii=False,indent=2))
 print(f"Iteration UI: {sum(r['passed'] for r in results)}/{len(results)}")
 for r in results:
  if not r['passed']:print(r)
 return int(any(not r['passed'] for r in results))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--browser',required=True,type=Path);p.add_argument('--output',type=Path,default=ROOT/'docs/validation/ui-iteration-tests.json');a=p.parse_args();raise SystemExit(main(a.browser,a.output))
