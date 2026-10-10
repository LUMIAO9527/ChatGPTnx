/* Local fixture only; requires Playwright plus an already installed browser. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const output = process.env.NX_TEST_OUTPUT || path.join(root, '_wip', 'hardening-ui');
fs.mkdirSync(output, {recursive:true});
(async()=>{
  const browser = await chromium.launch({executablePath:process.argv[2],headless:true});
  try {
    const context = await browser.newContext({viewport:{width:520,height:690}});
    await context.route('**/*', route=>route.abort());
    const page = await context.newPage(), errors=[];
    page.on('pageerror', e=>errors.push(e.message));
    const html=fs.readFileSync(path.join(root,'_wip/build/resources/demo.html'),'utf8');
    await page.setContent(html);
    await page.waitForSelector('[data-action="settings"]');
    await page.locator('[data-action="settings"]').first().click();
    assert.equal(await page.locator('[data-action="diagnostics"]').count(),0);
    const overflow=await page.locator('#sheet').evaluate(el=>el.scrollWidth>el.clientWidth+1);
    assert.equal(overflow,false);
    await page.screenshot({path:path.join(output,'settings.png')});
    for(const scenario of ['query-forbidden','reset-forbidden','query-cooling','monitor-degraded']) {
      await page.goto('about:blank');
      await page.setContent(html.replace('location.search',JSON.stringify('?scenario='+scenario)));
      await page.waitForSelector('.current-card');
      if(scenario==='query-forbidden') {
        await page.locator('.current-card [data-action="detail"]').click();
        await page.waitForSelector('[data-action="retry-query"]');
        assert((await page.locator('.detail-overview').innerText()).includes('查询已暂停'));
      } else if(scenario==='reset-forbidden') {
        await page.locator('.current-card [data-action="detail"]').click();
        await page.locator('[data-action="toggle-reset-credits"]').click();
        const button=page.locator('.reset-credit-details [data-action="retry-query"]');
        assert.equal(await button.innerText(),'恢复详情查询');
        await button.click();
        await button.waitFor({state:'detached'});
      } else if(scenario==='query-cooling') {
        assert.equal(await page.locator('.current-card .quota-bars').count(),1);
        assert.equal(await page.locator('.current-card .quota-failure').count(),0);
        assert.equal(await page.locator('.current-card [data-action="reauth"]').count(),0);
      } else {
        assert((await page.locator('.notice').innerText()).includes('监控暂不可用'));
        assert.equal(await page.locator('[data-action="diagnostics"]').count(),0);
      }
      await page.screenshot({path:path.join(output,scenario+'.png')});
    }
    assert.deepEqual(errors,[]);
    console.log('Hardening UI: no diagnostics setting, no overflow, 403, optional 403 recovery, 429, degraded monitor passed.');
    if(process.argv[3]) {
      const broad=await context.newPage();
      await broad.setContent(fs.readFileSync(process.argv[3],'utf8'));
      await broad.waitForSelector('#nx-check-results',{state:'attached',timeout:60000});
      const checks=JSON.parse(Buffer.from(await broad.locator('#nx-check-results').innerText(),'base64').toString());
      fs.writeFileSync(path.join(output,'browser-results.json'),JSON.stringify(checks,null,2));
      const failed=checks.filter(c=>!c.passed);
      console.log(`Existing browser checks: ${checks.length-failed.length}/${checks.length}`);
      for(const item of failed)console.log(JSON.stringify(item));
      assert.equal(failed.length,0);
    }
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
