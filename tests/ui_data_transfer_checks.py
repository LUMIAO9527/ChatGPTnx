"""Production panel -> native Bridge -> encrypted synthetic backup -> clean installation."""
import argparse,asyncio,json,sys,tempfile,time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tools'),str(ROOT/'tests')]
from build import panel,ui_source_digest
from nx.core import Service
from nx.desktop import Bridge
from nx.storage import Paths,account_identity_key
from nx.credentials import write_credential_bytes,read_credential_bytes
from nx.usage import SOURCE
from test_backup import auth
from test_core import FakeQuery,limits
from nx.quota import normalize_limits
from playwright.async_api import async_playwright

async def main(browser,output):
    checks=[];errors=[];services=[];calls=[]
    with tempfile.TemporaryDirectory() as temporary,ExitStack() as cleanup:
        task=Path(temporary);backup=task/'portable.nxbackup';email='portable@example.com'
        def setup(name,seed):
            paths=Paths(task/name,task/(name+'-desktop'))
            service=Service(paths,query=FakeQuery(),runner=Mock());services.append(service)
            def close():
                service.stop.set()
                for handler in list(service.log.handlers):handler.close();service.log.removeHandler(handler)
            cleanup.callback(close)
            if seed:
                service.accounts.write([email]);write_credential_bytes(paths.snapshot(email),auth(email))
                write_credential_bytes(paths.auth,auth(email))
                key=account_identity_key(paths.snapshot(email),email)
                service.state.update(account_meta={email:{'alias':'可移植账号','subscription_date':'2026-12-31'}},cache={'updated':int(time.time()),'current':email,'accounts':[normalize_limits(limits(),email)]},
                    usage={email:{'ok':True,'source':SOURCE,'identity_key':key,'fetched_at':int(time.time())-100,'summary':{'lifetimeTokens':123},'dailyUsageBuckets':[{'startDate':'2026-11-01','tokens':123}]}})
            host=Mock();host.choose_backup_file.return_value={'ok':True,'path':str(backup)}
            return service,Bridge(service,host)
        first,first_bridge=setup('first',True)
        second,second_bridge=setup('second',False)
        async with async_playwright() as p:
            engine=await p.chromium.launch(executable_path=str(browser),headless=True)
            async def load(bridge):
                page=await engine.new_page(viewport={'width':312,'height':458},reduced_motion='reduce')
                page.on('pageerror',lambda e:errors.append(str(e)))
                async def native(method,args):
                    calls.append(method)
                    return await asyncio.to_thread(getattr(bridge,method),*args)
                await page.expose_function('nativeCall',native)
                html=panel(demo=False).replace('window.NX_CONFIG=','window.pywebview={api:new Proxy({},{get:(_,method)=>(...args)=>window.nativeCall(method,args)})};window.NX_CONFIG=',1)
                await page.set_content(html);await page.evaluate("window.dispatchEvent(new Event('pywebviewready'))")
                await page.wait_for_selector('#home .header' if bridge._service.accounts.all() else '#home .onboarding-import')
                return page
            page=await load(first_bridge)
            await page.locator('[data-action="settings"]').click()
            await page.locator('[data-action="transfer-open"]').click()
            await page.locator('[data-action="transfer-export"]').click()
            await page.locator('#backup-password').fill('synthetic-password-2026')
            await page.locator('#backup-confirm').fill('synthetic-password-2026')
            await page.locator('.sheet-head [data-action="back"]').click()
            await page.locator('[data-action="transfer-export"]').click()
            checks.append({'name':'leaving-export-clears-password-fields','ok':await page.locator('#backup-password').input_value()=='' and await page.locator('#backup-confirm').input_value()==''})
            await page.locator('#backup-password').fill('synthetic-password-2026')
            await page.locator('#backup-confirm').fill('synthetic-password-2026')
            await page.locator('[data-action="export-save"]').click()
            await page.wait_for_function("document.querySelector('.transfer-outcome h3')?.textContent==='备份已导出'")
            checks.append({'name':'production-export-writes-encrypted-file','ok':backup.exists() and b'synthetic-refresh' not in backup.read_bytes() and email.encode() not in backup.read_bytes()})
            await page.close()
            page=await load(second_bridge)
            await page.locator('[data-action="transfer-import"]').click()
            await page.locator('[data-action="import-file"]').click()
            await page.locator('#backup-unlock').fill('incorrect-password')
            before=calls.count('backup_unlock')
            await page.locator('[data-action="import-unlock"]').evaluate('(b)=>{b.click();b.click();}')
            await page.wait_for_function("document.querySelector('#transfer-error')?.textContent.includes('密码不正确')")
            checks.append({'name':'wrong-password-stays-on-unlock','ok':await page.locator('#backup-unlock').is_visible() and not second.accounts.all()})
            checks.append({'name':'repeated-unlock-uses-one-operation','ok':calls.count('backup_unlock')==before+1})
            await page.locator('.sheet-head [data-action="back"]').click()
            await page.wait_for_function("document.querySelector('#sheet').hidden||!document.querySelector('#backup-unlock')")
            for _ in range(30):
                if second.backups.encrypted is None:break
                await asyncio.sleep(.02)
            checks.append({'name':'leaving-import-releases-native-buffer','ok':second.backups.encrypted is None and second.backups.document is None})
            await page.locator('[data-action="transfer-import"]').click()
            await page.locator('[data-action="import-file"]').click()
            await page.locator('#backup-unlock').fill('synthetic-password-2026')
            await page.locator('[data-action="import-unlock"]').click()
            await page.locator('[data-action="import-start"]').wait_for()
            checks.append({'name':'unlocked-preview-has-no-credential','ok':'synthetic-refresh' not in await page.content() and '可移植账号' in await page.content()})
            await page.locator('[data-action="import-start"]').click()
            await page.wait_for_function("document.querySelector('.transfer-outcome h3')?.textContent==='导入完成'")
            checks.append({'name':'production-import-restores-account','ok':second.accounts.all()==[email] and read_credential_bytes(second.paths.snapshot(email))==auth(email)})
            checks.append({'name':'production-import-restores-usage','ok':second.state.get('usage')[email]['summary']['lifetimeTokens']==123})
            checks.append({'name':'desktop-auth-remains-independent','ok':not second.paths.auth.exists()})
            await page.locator('[data-action="import-finish"]').click()
            await page.locator('.quota-overview-row').wait_for()
            checks.append({'name':'imported-account-is-visible','ok':'可移植账号' in await page.locator('#sheet').text_content()})
            await engine.close()
        for service in services:
            service.stop.set()
            for handler in list(service.log.handlers):handler.close();service.log.removeHandler(handler)
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps({'digest':ui_source_digest(),'checks':checks,'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
    failed=[r for r in checks if not r['ok']]
    print(json.dumps({'checks':len(checks),'failed':failed,'errors':errors},ensure_ascii=False))
    return bool(failed or errors)
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--browser',required=True,type=Path);parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    raise SystemExit(asyncio.run(main(args.browser,args.output)))
