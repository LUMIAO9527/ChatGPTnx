"""Rendered update discovery and explicit handoff choice, using synthetic data."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from build import panel,ui_source_digest
from playwright.async_api import async_playwright


async def run(browser,output):
    checks=[];errors=[]
    async with async_playwright() as p:
        engine=await p.chromium.launch(executable_path=str(browser),headless=True)
        for theme in ('light','dark'):
            for material in ('glass','solid'):
                page=await engine.new_page(viewport={'width':500,'height':600},reduced_motion='reduce')
                page.on('pageerror',lambda e:errors.append(str(e)))
                query=f'?appearance={theme}&material={material}'
                html=panel(demo=True).replace('window.NX_CONFIG=','window.NX_PREVIEW_QUERY='+json.dumps(query)+';window.NX_CONFIG=',1)
                await page.set_content(html);await page.wait_for_function('window.NX_CASE_READY')
                def record(name,ok):checks.append({'theme':theme,'material':material,'name':name,'ok':ok})
                await page.evaluate("async()=>{await NXDemo.call('set_relay_pick','backup@example.com');await NXPreview.refresh();}")
                record('picked-account-on-home','备用' in await page.locator('#home [data-action="relay"]').text_content())
                state=await page.evaluate("NXDemo.call('get_data')")
                record('automatic-and-home-use-the-same-choice',state['relay_email']==state['auto_relay_email']=='backup@example.com')
                await page.locator('#home [data-action="relay"]').click()
                record('manual-relay-confirmation-uses-pick',await page.locator('[data-action="execute-switch"]').get_attribute('data-email')=='backup@example.com')
                await page.locator('.sheet-head [data-action="back"]').click()
                await page.evaluate("async({theme,material})=>{NXDemo.scenario('update-available');await NXDemo.call('set_preferences',{appearance:theme,window_material:material});await NXPreview.refresh();}",{'theme':theme,'material':material})
                notice=page.locator('#home .status-dock [data-action="open-update"]')
                await notice.wait_for()
                if theme=='light' and material=='glass':
                    await page.locator('#app').screenshot(path=str(output.parent/'update-notice.png'))
                record('available-update-has-panel-entry','更新' in await notice.text_content())
                record('update-example-is-newer',await page.evaluate("async()=>{const d=await NXDemo.call('get_data');return d.update.version!==NX_CONFIG.version&&d.update.version.split('.').map(Number).at(-1)>NX_CONFIG.version.split('.').map(Number).at(-1);}"))
                await notice.click()
                record('update-entry-opens-existing-page',await page.locator('#sheet-title').text_content()=='版本更新')
                record('download-remains-user-initiated',await page.locator('[data-action="download-update"]').is_enabled())
                await page.locator('.sheet-head [data-action="back"]').click()
                await page.locator('#home [data-action="dismiss-status"]').click()
                await page.evaluate('NXPreview.refresh()')
                record('dismissed-update-stays-dismissed',await page.locator('#home .status-dock').evaluate('n=>n.hidden'))
                await page.evaluate('nxOpenUpdate()')
                record('native-notification-opens-update-page',await page.locator('#sheet-title').text_content()=='版本更新')
                await page.close()
        await engine.close()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({'digest':ui_source_digest(),'checks':checks,'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
    failed=[c for c in checks if not c['ok']]
    print(json.dumps({'checks':len(checks),'failed':failed,'errors':errors},ensure_ascii=False))
    return bool(failed or errors)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--browser',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();raise SystemExit(asyncio.run(run(args.browser,args.output)))
