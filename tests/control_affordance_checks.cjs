/* Mouse, keyboard and confirmation regressions against synthetic offline data. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),output=path.resolve(process.argv[3]||path.join(root,'_wip/controls'));
fs.mkdirSync(output,{recursive:true});
(async()=>{
  const browser=await chromium.launch({executablePath:process.argv[2],headless:true});
  const records=[];
  try{
    for(const appearance of ['light','dark']){
      const context=await browser.newContext({viewport:{width:520,height:700},reducedMotion:'reduce'});
      await context.route('**/*',route=>route.abort());
      const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
      const html=fs.readFileSync(path.join(root,'_wip/build/resources/demo.html'),'utf8');
      async function load(query){
        await page.goto('about:blank');
        await page.setContent(html.replaceAll('location.search',JSON.stringify('?'+query+'&appearance='+appearance)));
        await page.waitForFunction(()=>window.NX_CASE_READY);
      }
      async function check(name,fn){await fn();records.push({appearance,name,passed:true});}
      async function hover(control){
        await control.scrollIntoViewIfNeeded();await page.mouse.move(0,0);
        const before=await control.evaluate(node=>({shadow:getComputedStyle(node).boxShadow,opacity:Number(getComputedStyle(node,'::after').opacity)}));
        await control.hover();
        const after=await control.evaluate(node=>({shadow:getComputedStyle(node).boxShadow,opacity:Number(getComputedStyle(node,'::after').opacity)}));
        assert(after.opacity>before.opacity||after.shadow!==before.shadow,'hover has no visible feedback');
      }
      await load('open=add');
      await check('secondary-button-visible-before-hover',async()=>{
        const back=page.locator('.sheet-foot .secondary');
        const css=await back.evaluate(node=>{const s=getComputedStyle(node);return {bg:s.backgroundColor,edge:s.borderTopColor,width:parseFloat(s.borderTopWidth),weight:s.fontWeight,r:parseFloat(s.borderRadius),height:node.getBoundingClientRect().height};});
        assert.notEqual(css.bg,'rgba(0, 0, 0, 0)');assert.notEqual(css.edge,'rgba(0, 0, 0, 0)');
        assert(css.width>=1);assert.equal(css.weight,'400');assert(Math.abs(css.r-css.height*.375)<.1);
        await hover(back);await page.locator('#app').screenshot({path:path.join(output,'add-'+appearance+'.png')});
        await back.click();assert.equal(await page.evaluate(()=>NXPreview.info().page),'home');
      });
      await load('open=relay-accounts');
      await check('compact-selection-hover-and-persistence',async()=>{
        const control=page.locator('[data-action="auto-relay-account"]').first(),email=await control.getAttribute('data-email');
        const box=await control.boundingBox();assert(Math.abs(box.width-22)<.1&&Math.abs(box.height-22)<.1);
        await hover(control);await control.click();
        await page.waitForFunction(email=>NXDemo.state().settings.auto_relay_excluded.includes(email),email);
        assert.equal(await control.getAttribute('aria-checked'),'false');
        await control.click();await page.waitForFunction(email=>!NXDemo.state().settings.auto_relay_excluded.includes(email),email);
      });
      await load('open=hotkeys');
      await check('keycap-idle-hover-record-clear-cancel',async()=>{
        const keycap=page.locator('[data-action="record-hotkey"]').first(),email=await keycap.getAttribute('data-email');
        assert.notEqual(await keycap.evaluate(node=>getComputedStyle(node).backgroundColor),'rgba(0, 0, 0, 0)');
        await hover(keycap);await keycap.click();await page.keyboard.press('Control+Alt+9');
        await page.waitForFunction(email=>NXDemo.state().hotkeys.find(item=>item.email===email).shortcut?.endsWith('9'),email);
        const shortcut=await keycap.innerText();await keycap.click();await page.keyboard.press('Escape');
        assert.equal(await keycap.innerText(),shortcut);
        await keycap.click();await page.keyboard.press('Backspace');
        await page.waitForFunction(email=>NXDemo.state().hotkeys.find(item=>item.email===email).shortcut===null,email);
        assert((await keycap.innerText()).includes('设置'));
      });
      await load('open=settings&scenario=resume-history&expand=resume-history');
      await check('full-width-history-hover-and-single-retry',async()=>{
        const retry=page.locator('.resume-inline-retry').first(),row=retry.locator('..').locator('..');
        await retry.scrollIntoViewIfNeeded();await page.mouse.move(0,0);
        const before=await row.evaluate(node=>getComputedStyle(node).backgroundColor);
        await row.hover({position:{x:30,y:20}});
        assert.notEqual(await row.evaluate(node=>getComputedStyle(node).backgroundColor),before);
        assert.equal(await row.evaluate(node=>node.getBoundingClientRect().width===node.closest('.settings-disclosure').getBoundingClientRect().width),true);
        assert.equal(await retry.innerText(),'重试');assert.equal(await row.getByText('未接续',{exact:true}).count(),0);
        assert.equal(await retry.evaluate(node=>getComputedStyle(node).fontWeight),'400');
        await hover(retry);await page.locator('#app').screenshot({path:path.join(output,'history-hover-'+appearance+'.png')});
        await retry.click();await page.waitForFunction(()=>!document.querySelector('.resume-inline-retry')?.textContent.includes('重试'));
      });
      await load('open=settings&scenario=resume-history&expand=resume-history');
      await check('pager-centers-and-clear-confirmation',async()=>{
        const next=page.locator('[data-action="resume-page"][data-value="next"]');
        await hover(next);
        const center=await next.evaluate(node=>{const a=node.getBoundingClientRect(),b=node.querySelector('svg').getBoundingClientRect();return {dx:(a.left+a.right-b.left-b.right)/2,dy:(a.top+a.bottom-b.top-b.bottom)/2};});
        assert(Math.abs(center.dx)<.2&&Math.abs(center.dy)<.2);
        const clear=page.locator('[data-action="resume-clear"]');await hover(clear);await clear.click();
        assert.equal(await clear.innerText(),'确认');assert.equal(await clear.evaluate(node=>getComputedStyle(node).fontWeight),'550');
        await page.keyboard.press('Escape');assert.equal(await clear.innerText(),'');
        assert.equal(await page.evaluate(async()=>{const history=await NXDemo.call('get_resume_details');return history.flatMap(s=>s.items).length;}),7);
        await clear.click();await clear.click();await page.waitForSelector('.resume-inline-row',{state:'detached'});
        assert.equal(await page.evaluate(()=>NXPreview.info().page),'settings');
        assert((await page.locator('[data-disclosure="resume-history"]').innerText()).includes('暂无接续记录'));
      });
      assert.deepEqual(errors,[]);await context.close();
    }
    fs.writeFileSync(path.join(output,'controls-results.json'),JSON.stringify(records,null,2));
    console.log('Control mouse/keyboard checks: '+records.length+'/'+records.length+' passed');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
