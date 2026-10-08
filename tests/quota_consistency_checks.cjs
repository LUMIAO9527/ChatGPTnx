/* Offline cross-view checks: no native bridge, account login, or network. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),output=process.argv[3]||path.join(root,'_wip','quota-ui');
fs.mkdirSync(output,{recursive:true});
(async()=>{
  const browser=await chromium.launch({executablePath:process.argv[2],headless:true});
  const checks=[],errors=[];
  try{
    for(const appearance of ['light','dark']){
      const context=await browser.newContext({viewport:{width:520,height:700},reducedMotion:'reduce'});
      await context.route('**/*',r=>r.abort());
      const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
      for(const code of ['network','timeout',429,500,503,403,'reauth_required']){
        for(const used of [0,100]){
          await page.setContent(fs.readFileSync(path.join(root,'_wip/build/resources/demo.html'),'utf8'));
          await page.waitForFunction(()=>window.NX_CASE_READY===true);
          const fixture=await page.evaluate(async({code,used,appearance})=>{
            const data=NXDemo.state(),now=Date.now()/1000;
            data.accounts=data.accounts.slice(0,3);data.settings.appearance=appearance;
            for(const a of data.accounts.slice(0,2)){
              a.ok=false;a.error_code=code;a.fetched_at=now-20;
              a.windows=[{label:'5h',duration_mins:300,used:a.email===data.current?20:used,resets_at:now+7200},
                {label:'周',duration_mins:10080,used:20,resets_at:now+500000}];
              a.credits='12.50';a.credit_info={status:'known',balance:'12.50'};
              a.banked_resets={available_count:2,items:[]};
            }
            const target=data.accounts[1],soft=NXComponents.displayWindows(target).length>0;
            const reserve=data.accounts[2];
            data.settings.relay_pick=reserve.email;data.relay_email=reserve.email;
            data.relay_order=[reserve.email,...(soft&&used<100?[target.email]:[])];
            const original=NXDemo.call;window.__quotaFixture=data;
            NXDemo.call=async(method,...args)=>method==='get_data'?structuredClone(window.__quotaFixture):original(method,...args);
            await NXPreview.refresh();return {email:target.email,soft};
          },{code,used,appearance});
          const row=page.locator('.account-list .row').first();
          assert.equal(await row.locator('.roster-quota').count(),fixture.soft?2:0);
          if(fixture.soft)assert((await row.innerText()).includes(used===100?'0%':'100%'));
          assert(!(await page.locator('#app').innerText()).includes('缓存'));
          await page.locator('[data-action="quota-overview"]').click();
          const overview=page.locator(`.quota-overview-row[data-email="${fixture.email}"]`);
          assert.equal(await overview.locator('.quota-overview-window').count(),fixture.soft?2:0);
          if(fixture.soft)assert(!(await overview.innerText()).includes('暂不可用'));
          await page.locator('.sheet-head [data-action="back"]').click();
          await row.click();
          assert.equal(await page.locator('.detail-body .quota-bars').count(),fixture.soft?1:0);
          const details=await page.locator('.detail-compact').innerText();
          if(fixture.soft){
            assert(details.includes('12.50'));assert(details.includes('2 次'));
            const pick=page.locator('.detail-actions .btn.primary');
            assert.equal(await pick.innerText(),used===100?'恢复后接力':'设为下一棒');
            if(used===100){
              await page.evaluate(async()=>{__quotaFixture.relay_wait={id:'fixture',email:__quotaFixture.accounts[1].email,origin:__quotaFixture.current};await NXPreview.refresh();});
              assert.equal(await pick.innerText(),'取消等待');
              if(code==='network')await page.screenshot({path:path.join(output,`known-zero-${appearance}.png`)});
            }
          }else assert(!details.includes('12.50'));
          assert(await page.locator('.detail-body').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
          checks.push({name:`quota/${code}/${used===100?'zero':'available'}/${appearance}`,passed:true});
        }
      }
      await page.evaluate(async()=>{__quotaFixture.accounts=__quotaFixture.accounts.slice(0,2);__quotaFixture.accounts[1].windows=[];__quotaFixture.accounts[1].error_code='network';__quotaFixture.relay_email=null;__quotaFixture.relay_wait=null;await NXPreview.refresh();});
      await page.locator('.sheet-head [data-action="back"]').click();
      assert(!(await page.locator('.relay').innerText()).includes('等待额度恢复'));
      checks.push({name:`quota/missing-data-is-not-exhausted/${appearance}`,passed:true});
      await context.close();
    }
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(output,'quota-ui-results.json'),JSON.stringify(checks,null,2));
    console.log(`Quota consistency: ${checks.length}/${checks.length} light/dark checks passed.`);
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
