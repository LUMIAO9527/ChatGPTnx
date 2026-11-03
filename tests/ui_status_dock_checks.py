"""Rendered dock placement across the maintained catalog, including scaled previews."""
import argparse,asyncio,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from build import panel,ui_source_digest
from screen_catalog import CASES
from playwright.async_api import async_playwright

PROBE=r'''()=>{
 const $=s=>document.querySelector(s),surface=$('#sheet:not([hidden])')||$('#home'),dock=surface.querySelector('.status-dock'),note=dock?.querySelector('.status-notification');
 if(!dock||dock.hidden||!note)return {problems:['missing-dock']};
 const r=n=>n.getBoundingClientRect(),b=r(surface),d=r(dock),sx=b.width/surface.offsetWidth,sy=b.height/surface.offsetHeight;
 const f=surface.querySelector(':scope > footer'),row=surface.querySelector('.account-list > .row:nth-child(3)'),home=surface.id==='home'&&!surface.classList.contains('is-onboarding');
 const problems=[],near=(a,b)=>Math.abs(a-b)<.75;
 if(home&&row){
   const a=r(row),scroll=surface.querySelector('.account-list').scrollTop*sy;
   if(!near(d.left,a.left)||!near(d.width,a.width)||!near(d.top,a.top+scroll)||!near(d.height,a.height))problems.push('third-row-box-mismatch');
   if(getComputedStyle(note).borderRadius!==getComputedStyle(row).borderRadius)problems.push('third-row-radius-mismatch');
 }else if(!home){
   const footer=f&&!f.hidden&&r(f).height>0;
   if(!near(d.bottom,footer?r(f).top-8*sy:b.bottom-12*sy))problems.push('footer-or-base-inset-mismatch');
 }
 const h=r(note).height/sy,radius=parseFloat(getComputedStyle(note).borderTopLeftRadius);
 if(!near(radius,h*.375))problems.push('radius-scale-mismatch');
 return {problems,box:{x:d.x,y:d.y,width:d.width,height:d.height},footer:f?r(f).height:0};
}'''

async def run(browser,output,all_cases):
    cases=CASES if all_cases else [c for c in CASES if c['id'] in ('home','home-many','detail','detail-other','settings','data-export','data-import-review','data-uninstall','first-location','version-update','resume-history')]
    queue=asyncio.Queue();checks=[]
    for theme in ('light','dark'):
        for material in ('glass','solid'):
            for case in cases:queue.put_nowait((theme,material,case))
    async with async_playwright() as p:
        engine=await p.chromium.launch(executable_path=str(browser),headless=True)
        async def worker():
            page=await engine.new_page(viewport={'width':720,'height':620},device_scale_factor=2,reduced_motion='reduce');errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            while not queue.empty():
                try:theme,material,case=queue.get_nowait()
                except asyncio.QueueEmpty:break
                errors.clear();record={'case':case['id'],'theme':theme,'material':material,'problems':[]}
                try:
                    q='?'+case['query']+'&appearance='+theme+'&material='+material
                    html=panel(demo=True).replace('window.NX_CONFIG=','window.NX_PREVIEW_QUERY='+json.dumps(q)+';window.NX_PREVIEW_CASE='+json.dumps(case['id'])+';window.NX_CONFIG=',1)
                    await page.goto('about:blank');await page.set_content(html)
                    await page.wait_for_function('window.NX_CASE_READY||window.NX_CASE_ERROR',timeout=15000)
                    if 'dismissed' in case['id']:
                        beforeHidden=await page.locator('#sheet:not([hidden]) .status-dock,#home:not([hidden]) .status-dock').evaluate('n=>n.hidden')
                        if not beforeHidden:record['problems'].append('catalog-dismiss-did-not-hide')
                    await page.evaluate("async()=>{NXDemo.simulate('start-resume');await NXPreview.refresh();}")
                    await page.wait_for_timeout(50)
                    if 'dismissed' in case['id'] and await page.locator('#sheet:not([hidden]) .status-dock,#home:not([hidden]) .status-dock').evaluate('n=>n.hidden'):
                        record['dismissed']=True
                        checks.append(record);continue
                    initial=await page.evaluate(PROBE);record.update(initial)
                    for scale in (1.25,2):
                        await page.evaluate('(scale)=>{document.querySelector("#app").style.transform=`scale(${scale})`;window.dispatchEvent(new Event("resize"));}',scale)
                        await page.wait_for_timeout(40)
                        scaled=await page.evaluate(PROBE);record['problems']+=['scale-'+str(scale)+':'+x for x in scaled['problems']]
                    await page.evaluate("document.querySelector('#app').style.transform='none'")
                    if case['id'] in ('home','home-many'):
                        await page.evaluate("document.querySelector('.account-list').scrollTop=10000")
                        await page.evaluate('NXPreview.refresh()');record['problems']+=(await page.evaluate(PROBE))['problems']
                    footer=page.locator('#sheet:not([hidden]) > footer')
                    if await footer.count():
                        await footer.evaluate("n=>n.style.paddingTop='26px'");await page.wait_for_timeout(70)
                        record['problems']+=['footer-resize:'+x for x in (await page.evaluate(PROBE))['problems']]
                    record['problems']+=errors
                except Exception as e:record['problems'].append(str(e))
                checks.append(record)
                if len(checks)%80==0:print('progress '+str(len(checks))+'/'+str(len(cases)*4),flush=True)
            await page.close()
        await asyncio.gather(*(worker() for _ in range(4)));await engine.close()
    failed=[r for r in checks if r['problems']]
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps({'digest':ui_source_digest(),'checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checks':len(checks),'failed':failed},ensure_ascii=False))
    return bool(failed)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--browser',required=True,type=Path);p.add_argument('--output',required=True,type=Path);p.add_argument('--all',action='store_true');a=p.parse_args()
    raise SystemExit(asyncio.run(run(a.browser,a.output,a.all)))
