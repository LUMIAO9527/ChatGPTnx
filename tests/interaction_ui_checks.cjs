/* Offline fixture: all network requests are blocked, no real accounts or credits. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..');
const output=process.env.NX_TEST_OUTPUT||path.join(root,'_wip','interaction-ui');
fs.mkdirSync(output,{recursive:true});
(async()=>{
  const browser=await chromium.launch({executablePath:process.argv[2],headless:true});
  try{
    const context=await browser.newContext({viewport:{width:520,height:690}});
    await context.route('**/*',route=>route.abort());
    const page=await context.newPage(),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.setContent(fs.readFileSync(path.join(root,'_wip/build/resources/demo.html'),'utf8'));
    await page.waitForSelector('.current-card');
    const fresh=async(scenario='default')=>{
      await page.evaluate(async value=>{NXDemo.scenario(value);await nxShown();},scenario);
      await page.waitForTimeout(100);
    };
    const details=async email=>{
      await page.evaluate(async()=>{nxShown();await NXPreview.refresh();});
      await page.locator(`.account-list [data-email="${email}"]`).click();
      await page.waitForSelector('.detail-actions');
    };
    const choices=()=>page.evaluate(()=>({next:NXDemo.state().settings.relay_pick,waiting:NXDemo.state().relay_wait?.email||null}));
    assert.equal(await page.locator('.account-list .row').count(),4);
    const state=await page.evaluate(()=>NXDemo.state());
    assert.equal(await page.locator(`.account-list .row[data-email="${state.relay_email}"]`).count(),1);
    assert.equal(await page.locator(`.account-list .row[data-email="${state.current}"]`).count(),0);
    await page.screenshot({path:path.join(output,'home.png')});
    await page.locator('[data-action="settings"]').first().click();
    assert.equal(await page.locator('[data-action="diagnostics"]').count(),0);
    await fresh('relay-exhausted');
    await details('work-02@example.com');
    await page.locator('.detail-actions .primary').click();
    await page.waitForFunction(()=>NXDemo.state().relay_wait?.email==='work-02@example.com');
    await details('backup@example.com');
    await page.locator('.detail-actions .primary').click();
    await page.waitForFunction(()=>NXDemo.state().settings.relay_pick==='backup@example.com');
    assert.deepEqual(await choices(),{next:'backup@example.com',waiting:'work-02@example.com'});
    await page.locator('.detail-actions .primary').click();
    await page.waitForFunction(()=>!NXDemo.state().settings.relay_pick);
    assert.deepEqual(await choices(),{next:null,waiting:'work-02@example.com'});
    await details('backup@example.com');
    await page.locator('.detail-actions .primary').click();
    await page.waitForFunction(()=>NXDemo.state().settings.relay_pick==='backup@example.com');
    await details('work-02@example.com');
    await page.locator('.detail-actions .primary').click();
    await page.waitForFunction(()=>!NXDemo.state().relay_wait);
    assert.deepEqual(await choices(),{next:'backup@example.com',waiting:null});
    await fresh();
    await page.evaluate(()=>{
      const original=NXDemo.call;window.resetCalls=[];
      NXDemo.call=async(method,...args)=>{if(method==='consume_reset')resetCalls.push(args);return original(method,...args);};
    });
    await page.locator('#home .current-identity').click();
    await page.locator('.reset-summary').click();
    let use=page.locator('[data-action="use-reset"]').first();
    assert.equal(await use.innerText(),'使用');
    const row=page.locator('.reset-credit').first();
    const positions=await row.evaluate(element=>{
      const row=element.getBoundingClientRect(),copy=element.querySelector('.reset-credit-copy').getBoundingClientRect();
      const first=element.querySelector('.reset-credit-copy span').getBoundingClientRect(),expiry=element.querySelector('strong').getBoundingClientRect();
      const button=element.querySelector('button').getBoundingClientRect();
      const style=getComputedStyle(element);
      return {left:copy.left-row.left-parseFloat(style.paddingLeft),gap:expiry.left-first.right,end:row.right-button.right-parseFloat(style.paddingRight),overlap:expiry.right>button.left};
    });
    assert(positions.left<=1&&positions.gap>=8&&positions.gap<=12&&positions.end<=1&&!positions.overlap,JSON.stringify(positions));
    await use.click();
    await page.waitForFunction(()=>document.querySelector('[data-action="use-reset"]')?.textContent==='确认');
    assert.equal(await page.evaluate(()=>resetCalls.length),0);
    await page.locator('.reset-summary').click();
    await page.locator('.reset-summary').click();
    assert.equal(await use.innerText(),'使用');
    await page.evaluate(async()=>{NXDemo.appearance('dark');await NXPreview.refresh();});
    await page.screenshot({path:path.join(output,'reset-dark.png')});
    await page.evaluate(async()=>{NXDemo.appearance('light');await NXPreview.refresh();});
    await page.screenshot({path:path.join(output,'reset-light.png')});
    const originalCurrent=await page.evaluate(()=>NXDemo.state().current);
    await use.click();
    await use.click();
    await page.waitForFunction(()=>NXDemo.state().accounts[0].banked_resets.available_count===1);
    await page.evaluate(()=>NXPreview.refresh());
    assert.equal(await page.evaluate(()=>resetCalls.length),1);
    const sent=await page.evaluate(()=>resetCalls[0]);
    assert.equal(sent[0],originalCurrent);assert.equal(sent[1],'fixture-reset-1');
    assert.match(sent[2],/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    assert.equal(await page.evaluate(()=>NXDemo.state().current),originalCurrent);
    assert.match(await page.locator('.reset-summary').innerText(),/重置 · Credits\s*1 次/);
    const geometry=()=>page.evaluate(()=>{
      const rect=element=>{
        const {x,y,width,height}=element.getBoundingClientRect();
        return [x,y,width,height];
      };
      const body=document.querySelector('.detail-body');
      return {
        panel:rect(document.querySelector('#app')),
        scroll:[body.clientWidth,body.scrollWidth,body.scrollTop],
        vault:rect(document.querySelector('.detail-vault')),
        rows:[...body.querySelectorAll('.detail-line,.vault-line')].map(rect),
        copy:[...body.querySelectorAll('[data-action="vault-copy"]')].map(rect),
      };
    });
    const email='work-02@example.com', longPassword='NX-synthetic_123!?'.repeat(32).slice(0,512);
    for(const [width,appearance] of [[300,'dark'],[312,'light'],[327,'dark']]){
      await fresh();
      await page.evaluate(async ({width,appearance,email,longPassword})=>{
        window.NX_PREVIEW_QUERY='?width='+width;
        NXMotion.setEnabled(false);
        NXDemo.appearance(appearance);
        await NXDemo.call('vault_save',{email,password:longPassword});
        Object.defineProperty(navigator,'clipboard',{configurable:true,value:{
          writeText:async value=>{window.__passwordCopy=value;},
        }});
        window.__passwordCopy=null;
        await NXPreview.refresh();
      },{width,appearance,email,longPassword});
      await details(email);
      await page.locator('[data-action="toggle-vault"]').click();
      const password=page.locator('[data-action="vault-reveal"]');
      const edit=page.getByRole('button',{name:'更新本机密码记录'});
      const copy=page.locator('[data-action="vault-copy"][data-value="password"]');
      await page.locator('.detail-vault').scrollIntoViewIfNeeded();
      const masked=await geometry();
      assert.equal(masked.panel[2],width);
      assert.equal(masked.scroll[0],masked.scroll[1]);
      assert.equal(await edit.locator('svg').count(),1);
      assert.equal((await edit.innerText()).trim(),'');
      const editBox=await edit.boundingBox(),copyBox=await copy.boundingBox();
      assert.deepEqual([editBox.width,editBox.height],[copyBox.width,copyBox.height]);
      assert.equal(editBox.y,copyBox.y);
      await password.click();
      await page.waitForFunction(()=>document.querySelector('.vault-value')?.getAttribute('aria-label')==='隐藏密码');
      assert.deepEqual(await geometry(),masked);
      assert(await password.locator('strong').evaluate(node=>node.scrollWidth>node.clientWidth&&getComputedStyle(node).textOverflow==='ellipsis'));
      if(width===312){
        await page.locator('#app').screenshot({path:path.join(output,'long-password.png')});
        await page.waitForFunction(()=>document.querySelector('.vault-value')?.getAttribute('aria-label')==='显示密码');
      }else await password.click();
      assert.deepEqual(await geometry(),masked);
      await copy.click();
      await page.waitForFunction(value=>window.__passwordCopy===value,longPassword);
      await edit.click();
      const field=page.locator('#vault-password');
      await field.waitFor();
      await page.waitForFunction(()=>{
        const actions=document.querySelector('.credential-editor .vault-inline-actions');
        const body=document.querySelector('.detail-body');
        return actions&&actions.getBoundingClientRect().bottom<=body.getBoundingClientRect().bottom;
      });
      const beforeInput=await field.boundingBox();
      await field.fill(longPassword);
      assert.deepEqual(await field.boundingBox(),beforeInput);
      assert.equal((await page.locator('.detail-vault').boundingBox()).width,masked.vault[2]);
      await page.locator('[data-action="vault-cancel"]').click();
      assert.equal((await page.locator('.detail-vault').boundingBox()).width,masked.vault[2]);
    }
    assert.deepEqual(errors,[]);
    console.log('Password layout: 512-character display, mask, full copy, and pencil editor passed at 300/312/327 px.');
    console.log('Interaction UI: all noncurrent accounts, independent choices/cancellation, reset confirmation/cancellation/single request, UUID, left alignment, light/dark passed.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
