/* Offline history display/navigation fixtures; all browser requests are blocked. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const output = path.join(root, '_wip', 'hardening-ui');
fs.mkdirSync(output, {recursive:true});

(async()=>{
  const browser = await chromium.launch({executablePath:process.argv[2],headless:true});
  const results=[];
  try {
    const context=await browser.newContext({viewport:{width:520,height:690}});
    await context.route('**/*',route=>route.abort());
    const page=await context.newPage(),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    const html=fs.readFileSync(path.join(root,'_wip/build/resources/demo.html'),'utf8');
    async function load(scenario,appearance){
      await page.goto('about:blank');
      await page.setContent(html.replaceAll('location.search',JSON.stringify('?open=resume&scenario='+scenario+'&appearance='+appearance)));
      await page.waitForFunction(()=>window.NX_CASE_READY===true);
      const summary=page.locator('.resume-summary').first();
      if(await summary.getAttribute('aria-expanded')!=='true')await summary.click();
      await page.waitForSelector('.resume-task-row');
    }
    async function check(name,fn){
      await fn();results.push({name,passed:true});
    }
    for(const appearance of ['light','dark']){
      const name=test=>appearance+'/'+test;
      await load('resume-subagent-history',appearance);
      await check(name('success-count-and-breakdown'),async()=>{
        assert((await page.locator('.resume-summary').innerText()).includes('已接续 2/6'));
        assert.equal(await page.locator('.resume-session-stats').innerText(),'成功 2 · 跳过 3 · 需查看 1');
        assert.equal(await page.locator('.resume-task-row').count(),6);
      });
      await check(name('children-retain-history-and-no-retry'),async()=>{
        const children=page.locator('.is-subagent');
        assert.equal(await children.count(),4);
        assert((await children.locator('strong').allTextContents()).every(text=>text.startsWith('后台子任务：')));
        assert((await page.locator('.resume-subagent-note').innerText()).includes('当前版本不单独接续'));
        assert((await children.nth(0).innerText()).includes('该回合已处理，未重复操作'));
        assert((await children.nth(3).innerText()).includes('结果未确认；已停止自动接续，请查看原任务'));
        assert.equal(await children.locator('[data-action="retry-resume-task"]').count(),0);
      });
      await page.evaluate(()=>{
        const call=NXDemo.call;window.resumeNavigationCalls=[];
        NXDemo.call=async(method,...args)=>{
          if(method==='open_resume_task')window.resumeNavigationCalls.push(args[0]);
          return call(method,...args);
        };
      });
      await check(name('child-opens-confirmed-main-task'),async()=>{
        const button=page.locator('.is-subagent .resume-task').first();
        assert((await button.getAttribute('aria-label')).includes('打开所属主任务：整理研究资料'));
        await button.click();
        await page.waitForFunction(()=>window.resumeNavigationCalls.length===1);
        assert.deepEqual(await page.evaluate(()=>window.resumeNavigationCalls),['67cc833f-6330-5bae-a638-9232b5ddfa21']);
      });
      await check(name('unknown-main-task-disables-navigation'),async()=>{
        const button=page.locator('.is-subagent .resume-task').nth(2);
        assert.equal(await button.isDisabled(),true);
        assert.equal(await button.getAttribute('data-action'),null);
        assert.equal(await button.getAttribute('data-value'),null);
        assert((await button.innerText()).includes('所属主任务未确认，不能独立打开'));
        await button.evaluate(element=>element.click());
        assert.equal(await page.evaluate(()=>window.resumeNavigationCalls.length),1);
      });
      await check(name('ordinary-task-keeps-own-navigation'),async()=>{
        const button=page.locator('.resume-task-row:not(.is-subagent) .resume-task').nth(1);
        await button.click();
        await page.waitForFunction(()=>window.resumeNavigationCalls.length===2);
        assert.equal(await page.evaluate(()=>window.resumeNavigationCalls[1]),'ea10a953-d3a4-53b9-b010-6361794c2a22');
      });
      await check(name('compact-panel-contains-titles'),async()=>{
        assert.equal(await page.evaluate(()=>{
          const body=document.querySelector('.sheet-body');
          const copy=[...document.querySelectorAll('.resume-task-copy')];
          const rect=element=>element.getBoundingClientRect();
          return NXPreview.info().width===372&&NXPreview.info().height===520
            &&body.scrollWidth<=body.clientWidth+1
            &&copy.every(element=>rect(element).width>0&&[...element.children].every(child=>rect(child).right<=rect(element).right+1))
            &&[...document.querySelectorAll('.is-subagent .resume-task-copy strong')].every(element=>getComputedStyle(element).textOverflow==='ellipsis');
        }),true);
      });
      await page.locator('.sheet-body').evaluate(element=>element.scrollTop=0);
      await page.screenshot({path:path.join(output,'resume-subagent-'+appearance+'.png')});
      await check(name('child-cannot-inherit-manual-retry'),async()=>{
        await page.evaluate(async()=>{
          const call=NXDemo.call,details=await call('get_resume_details');
          details[0].items[0].state='failed';details[0].items[0].reason='desktop_bridge_unavailable';
          NXDemo.call=(method,...args)=>method==='get_resume_details'?structuredClone(details):call(method,...args);
          await NXPreview.refresh();
        });
        assert.equal(await page.locator('.is-subagent [data-action="retry-resume-task"]').count(),0);
        assert((await page.locator('.is-subagent').first().innerText()).includes('桌面桥接不可用，未发送消息'));
      });
      await check(name('newly-skipped-child-has-specific-reason'),async()=>{
        await page.evaluate(async()=>{
          const call=NXDemo.call,details=await call('get_resume_details');
          details[0].items[0].state='skipped';details[0].items[0].reason='subagent_task';
          NXDemo.call=(method,...args)=>method==='get_resume_details'?structuredClone(details):call(method,...args);
          await NXPreview.refresh();
        });
        assert((await page.locator('.is-subagent').first().innerText()).includes('后台子任务，不单独接续'));
        assert.equal(await page.locator('.is-subagent [data-action="retry-resume-task"]').count(),0);
      });
      await load('resume-bridge-unavailable',appearance);
      await check(name('ordinary-task-retains-manual-retry'),async()=>{
        assert.equal(await page.locator('[data-action="retry-resume-task"]').count(),1);
        assert.equal(await page.locator('.resume-subagent-note').count(),0);
      });
    }
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(output,'resume-display-results.json'),JSON.stringify(results,null,2));
    console.log(`Resume display checks: ${results.length}/${results.length} passed (light and dark).`);
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
