"""5.7.6: final requested geometry, error recovery affordances and exclusive settings.

Uses production components with the isolated demo bridge, not Windows UIA.
Assertions measure actual elements; no screenshots are used as pass/fail proxies.
"""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from browser_session import browser_session,demo_html
CASES=[]
def add(name,q,body):
    setup="const active=()=>document.querySelector('#sheet:not([hidden])')||document.querySelector('#home'),$=s=>active().querySelector(s)||document.querySelector(s),$$=s=>[...active().querySelectorAll(s)],sleep=ms=>new Promise(r=>setTimeout(r,ms)),rect=n=>(typeof n==='string'?$(n):n).getBoundingClientRect(),near=(a,b)=>Math.abs(a-b)<.6,same=(a,b)=>['x','y','width','height'].every(k=>near(a[k],b[k])),input=(id,value)=>{const n=$('#'+id);n.value=value;n.dispatchEvent(new Event('input',{bubbles:true}));return n;};"
    CASES.append((name,q,'async()=>{'+setup+body+'}'))

add('reference/detail-original-42px-8px','open=detail',"const nodes=[$('.account-editor'),$('.detail-reset'),$('.detail-compact > .detail-line')];return nodes.every(n=>rect(n).height===42)&&nodes.slice(1).every((n,i)=>near(rect(n).top-rect(nodes[i]).bottom,8))&&parseFloat(getComputedStyle($('.detail-line')).paddingLeft)===12;")
add('reference/settings-matches-detail','open=settings',"const rows=$$('.settings-list > *'),heights=rows.map(n=>rect(n).height);return rows.length===13&&heights.every(h=>h===42)&&getComputedStyle($('.settings-list')).gap==='8px'&&$$('.settings-disclosure').every(n=>getComputedStyle(n).borderRadius==='12px');")
add('shapes/avatars-round-not-clickable','',"return $$('.avatar').every(n=>getComputedStyle(n).borderRadius==='50%'&&n.getAttribute('aria-hidden')==='true'&&!n.dataset.action)&&getComputedStyle($('.avatar')).boxShadow==='none';")
add('shapes/segmented-pills-concentric','open=notifications&scenario=notify-low',"return $$('.segmented').filter(n=>rect(n).height>0).every(n=>parseFloat(getComputedStyle(n).borderRadius)>=999&&[...n.querySelectorAll('button')].every(b=>parseFloat(getComputedStyle(b).borderRadius)>=999));")
add('shapes/usage-range-pill','open=usage',"return getComputedStyle($('.usage-filter')).borderRadius==='999px'&&$$('.usage-filter button').every(n=>getComputedStyle(n).borderRadius==='999px');")
add('roster/returned-windows-only','',"return $$('.account-list > .row').every(n=>{const a=NXDemo.state().accounts.find(a=>a.email===n.dataset.email),expected=NXComponents.displayWindows(a).map(w=>w.label),actual=[...n.querySelectorAll('.roster-quota em')].map(x=>x.textContent);return !n.querySelector(':scope > .icon')&&JSON.stringify(actual)===JSON.stringify(expected);});")
add('roster/labels-fixed-when-values-change','',"const rows=$$('.account-list > .row'),axes=rows.map(n=>[...n.querySelectorAll('.roster-quota em')].map(x=>rect(x).right));for(const r of rows)r.querySelectorAll('.roster-quota strong').forEach((n,i)=>n.textContent=i?'100%':'0.1%');return rows.every((n,i)=>[...n.querySelectorAll('.roster-quota em')].every((x,j)=>near(rect(x).right,axes[i][j])));")
add('roster/long-names-keep-both-quotas','scenario=long-names',"return $$('.account-list > .row').every(n=>{const q=rect(n.querySelector('.roster-quotas'));return q.width>0&&q.width<=150&&q.right<rect(n).right&&n.querySelector('.meta').scrollWidth<=n.querySelector('.meta').clientWidth+1;});")
add('dock/home-covers-third-avatar-and-copy','scenario=resume-progress',"const d=rect('.status-notification'),a=rect('.account-list > .row:nth-child(3) .avatar'),m=rect('.account-list > .row:nth-child(3) .meta');return d.height===40&&near((d.top+d.bottom)/2,(a.top+a.bottom)/2)&&d.top<=a.top&&d.bottom>=a.bottom&&d.top<=m.top&&d.bottom>=m.bottom;")
add('dock/home-scroll-does-not-move-slot','scenario=many',"NXDemo.simulate('start-resume');await NXPreview.refresh();const before=rect('.status-dock').toJSON();$('.account-list').scrollTop=100;await sleep(30);await NXPreview.refresh();return same(before,rect('.status-dock'));")
add('dock/detail-and-edit-and-settings-same-bottom','scenario=resume-progress',"for(const open of ['detail','edit','notifications']){await NXPreview.open(new URLSearchParams('open='+open));await sleep(20);if(!near(rect('#app').bottom-rect('.status-dock').bottom,12)||rect('.status-notification').height!==40)return false;}return true;")
add('dock/detail-opening-editor-does-not-raise','open=detail&scenario=resume-progress',"const b=rect('.status-dock').toJSON();$('.account-editor summary').click();await sleep(20);$('[data-action=toggle-reset-credits]').click();await sleep(20);return same(b,rect('.status-dock'))&&rect('.detail-footer').bottom===rect('#app').bottom;")
add('dock/detail-footer-focus-yields-without-moving','open=detail&email=backup@example.com&scenario=resume-progress',"const d=rect('.status-dock').toJSON(),f=rect('.detail-footer').toJSON(),button=$('[data-action=remove]');button.focus();await sleep(20);const yielded=getComputedStyle($('.status-dock')).visibility==='hidden';$('.sheet-head [data-action=back]').focus();await sleep(40);return yielded&&getComputedStyle($('.status-dock')).visibility==='visible'&&same(d,rect('.status-dock'))&&same(f,rect('.detail-footer'));")
add('dock/dismiss-allows-archive-click','open=detail&email=backup@example.com&scenario=resume-progress',"$('[data-action=dismiss-status]').click();const n=$('[data-action=remove]'),r=rect(n);return $('.status-dock').hidden&&n.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));")
add('dock/settings-fixed-through-exclusive-expansion','open=settings&scenario=resume-progress',"const b=rect('.status-dock').toJSON();for(const k of ['notifications','relay','message','hotkeys','appearance']){$('[data-disclosure='+k+'] > summary').click();await sleep(25);if(!same(b,rect('.status-dock')))return false;}return true;")
add('dock/first-launch-only-one-progress-surface','scenario=first-launch-pending',"const b=$('[data-action=launch-chatgpt]');if(!b.disabled)b.click();await sleep(30);return $$('.status-notification').length===1&&$$('.status-bar').length===1&&!!$('[data-action=launch-chatgpt]:disabled')&&!$('[data-action=launch-chatgpt] .control-feedback');")
add('usage/flat-hierarchy-not-transparent-cards','open=usage',"return !$('.usage-body .card,.usage-context-card,.usage-stats-card')&&getComputedStyle($('.usage-context')).backgroundColor==='rgba(0, 0, 0, 0)'&&getComputedStyle($('.usage-summary')).backgroundColor==='rgba(0, 0, 0, 0)'&&parseFloat(getComputedStyle($('.usage-summary')).borderTopWidth)===1&&rect('.trend').height===76;")
add('usage/scope-and-periods-identical-geometry','open=usage',"const parts=['.usage-context','.usage-summary','.usage-filter','.trend'],a=parts.map(s=>rect(s).toJSON());for(const q of ['open=usage&email=work-01@example.com&days=7','open=usage&days=all','open=usage&email=remote@example.com&days=180']){await NXPreview.open(new URLSearchParams(q));if(!parts.every((s,i)=>same(a[i],rect(s))))return false;}return true;")
add('usage/no-dash-after-today-if-missing','open=usage&scenario=usage-empty',"return !$('.usage-chart-heading').textContent.includes('—')&&!$('.usage-chart-heading').textContent.includes('今日')&&$('.usage-total').textContent.includes('—');")
add('usage/period-hides-accounts-with-no-records','open=usage&scenario=usage-empty',"return !$('.account-usage-row')&&$('.inline-empty')?.textContent.includes('暂无账号记录');")
add('usage/true-zero-stays-zero','open=usage&scenario=usage-zero',"return !$('.usage-total').textContent.includes('—')&&$('.usage-total').textContent.trim()==='0';")
add('usage/section-label-inset-aligned','open=usage',"return near(rect('.section-title h3').left,rect('.usage-hero').left);")
for case,scenario,params,action in [('timeout','detail-timeout-empty','','refresh-one'),('reauth','reauth','&email=remote@example.com','reauth'),('snapshot','detail-missing','','reauth'),('unsupported','detail-schema','',None)]:
    add('failure/'+case+'-readable-fixed-geometry','open=detail&scenario='+scenario+params,"const f=$('.quota-failure'),title=f.querySelector('strong'),copy=f.querySelector('small');return rect('.current-card').height===123&&rect(f).height===40&&parseFloat(getComputedStyle(title).fontSize)>=13&&parseFloat(getComputedStyle(copy).fontSize)>=11&&title.scrollWidth<=title.clientWidth+1&&copy.scrollWidth<=copy.clientWidth+1"+("&&rect(f.querySelector('button')).height>=34&&f.querySelector('button').dataset.action==='"+action+"'" if action else "&&!f.querySelector('button')")+';')
add('failure/retry-keeps-card-and-actions','open=detail&scenario=detail-timeout-empty',"const a=rect('.current-card').toJSON(),b=rect('.detail-actions').toJSON();$('.quota-failure [data-action=refresh-one]').click();await sleep(40);return same(a,rect('.current-card'))&&same(b,rect('.detail-actions'));")
add('failure/temporary-query-keeps-known-quota','open=detail&scenario=detail-timeout',"return !!$('.quota-bars')&&!$('.quota-failure')&&$('.detail-compact').textContent.includes('未提供')&&$('.reset-summary').textContent.includes('2 次');")
add('failure/missing-snapshot-can-reauth','open=detail&scenario=detail-missing',"$('.quota-failure [data-action=reauth]').click();return NXPreview.info().page==='reauth'&&!!$('[data-action=start-reauth]');")
add('accordion/only-one-across-all-sections','open=settings',"for(const k of ['appearance','notifications','relay','message','hotkeys','archives','appearance']){$('[data-disclosure='+k+'] > summary').click();await sleep(30);const open=$$('.settings-body details[open]');if(open.length!==1||open[0].dataset.disclosure!==k)return false;}return true;")
add('accordion/poll-and-return-preserve-single-open','open=settings',"$('[data-disclosure=notifications] > summary').click();$('[data-disclosure=relay] > summary').click();await NXPreview.refresh();if($$('.settings-body details[open]').length!==1)return false;$('[data-action=resume-details]').click();await sleep(40);$('.sheet-head [data-action=back]').click();return $$('.settings-body details[open]').map(n=>n.dataset.disclosure).join()==='relay';")
add('accordion/message-draft-survives-switch','open=resume-message',"input('resume-message','还没有保存的消息');$('[data-disclosure=notifications] > summary').click();await NXPreview.refresh();$('[data-disclosure=message] > summary').click();return $('#resume-message').value==='还没有保存的消息'&&$$('.settings-body details[open]').length===1&&NXDemo.state().settings.resume_message==='继续';")
add('accordion/collapse-hotkey-cancels-recording','open=hotkeys',"let writes=0;const call=NXDemo.call;NXDemo.call=(m,...args)=>{if(m==='set_account_hotkey')writes++;return call(m,...args);};$('.keycap').click();$('[data-disclosure=appearance] > summary').click();document.dispatchEvent(new KeyboardEvent('keydown',{key:'2',ctrlKey:true,altKey:true,bubbles:true}));await sleep(40);return writes===0&&$('[data-disclosure=appearance]').open;")
add('accordion/queued-native-toggle-no-reopen','open=settings',"const keys=['notifications','relay','message','appearance'];for(let i=0;i<24;i++)$('[data-disclosure='+keys[i%4]+'] > summary').click();await NXPreview.refresh();await sleep(50);return $$('.settings-body details[open]').map(n=>n.dataset.disclosure).join()==='appearance';")
add('accordion/long-collection-width-no-jump','open=relay-accounts&scenario=many',"const w=$('.sheet-body').clientWidth;$('[data-action=collection-more]').click();$('[data-disclosure=hotkeys] > summary').click();return $$('.settings-body details[open]').length===1&&$('.sheet-body').clientWidth===w&&$('.sheet-body').scrollWidth===w;")
add('accordion/hover-shell-not-rounded-inner-bottom','open=notifications',"const d=$('[data-disclosure=notifications]'),s=d.querySelector('summary');return getComputedStyle(s).borderBottomLeftRadius==='0px'&&getComputedStyle(s).borderBottomRightRadius==='0px'&&getComputedStyle(d).borderBottomLeftRadius==='12px';")
add('safety/one-panel-no-manual-resume-route','open=settings',"return NXPreview.info().width===372&&NXPreview.info().height===520&&!$('[data-key=panel_mode],[data-action=resume-manual],[data-action=copy-resume-message]')&&!NX_RESUME_POLICY.retryable.includes('action_outcome_unknown');")

def main(browser,output):
    result=[]
    with browser_session(browser) as engine:
        for palette in ('light','dark'):
            for name,query,script in CASES:
                ctx=engine.new_context(viewport={'width':520,'height':700},color_scheme=palette,reduced_motion='reduce')
                p=ctx.new_page();errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
                try:
                    p.set_content(demo_html(query+'&appearance='+palette));p.wait_for_function('window.NX_CASE_READY',timeout=6000)
                    ok=p.evaluate('() => Promise.race([('+script+')(),new Promise((_,reject)=>setTimeout(()=>reject(new Error("Assertion timed out")),5000))])') is True
                except Exception as e:ok=False;errors.append(str(e))
                result.append({'name':name,'appearance':palette,'passed':ok and not errors,'errors':errors});ctx.close()
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print('Final UI:',sum(r['passed'] for r in result),'/',len(result))
    for r in result:
        if not r['passed']:print(r)
    return int(any(not r['passed'] for r in result))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--browser',required=True,type=Path);p.add_argument('--output',type=Path,default=ROOT/'docs/validation/ui-final-tests.json');a=p.parse_args();raise SystemExit(main(a.browser,a.output))
