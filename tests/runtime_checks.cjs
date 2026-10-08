/* No browser, package manager or production bridge needed. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = {window: {}};
vm.createContext(context);
for(const file of ['runtime.js','components.js']){
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/ui',file),'utf8'),context);
}
const {readEpoch,coalescedRefresh} = context.window.NXRuntime;
const components=context.window.NXComponents;
const results=[];
async function check(name, run){await run();results.push({name,passed:true});}
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
(async()=>{
  await check('navigation/old-read-invalidated',()=>{
    const epoch=readEpoch(), first=epoch.ticket();epoch.invalidate();
    assert.equal(epoch.current(first),false);assert.equal(epoch.current(epoch.ticket()),true);
  });
  await check('poll/overlapping-passive-reads-coalesce',async()=>{
    const gate=deferred();let calls=0;const refresh=coalescedRefresh(()=>{calls++;return gate.promise;});
    const first=refresh();assert.equal(refresh(),first);assert.equal(refresh(),first);
    await Promise.resolve();gate.resolve();await first;assert.equal(calls,1);
  });
  await check('poll/write-demands-one-fresh-trailing-read',async()=>{
    const first=deferred(),second=deferred();let calls=0;
    const refresh=coalescedRefresh(()=> (++calls===1?first:second).promise);
    const pending=refresh();await Promise.resolve();refresh(true);refresh(true);
    first.resolve();await new Promise(resolve=>setImmediate(resolve));assert.equal(calls,2);
    second.resolve();await pending;assert.equal(calls,2);
  });
  await check('poll/rejection-does-not-poison-next-refresh',async()=>{
    let calls=0;const refresh=coalescedRefresh(()=>{if(!calls++)throw new Error('network');});
    await assert.rejects(refresh(),/network/);await refresh();assert.equal(calls,2);
  });
  await check('quota/non-finite-and-out-of-range-stay-unknown',()=>{
    for(const used of [null,undefined,true,'20',-1,101,Infinity,NaN]){
      assert.equal(components.displayWindows({ok:true,windows:[{used}]}).length,0);
      assert.ok(components.quotaSummary({ok:true,windows:[{used}]}).includes('额度暂不可用'));
    }
  });
  await check('quota/rounding-is-stable-and-labels-escaped',()=>{
    const html=components.quotaSummary({ok:true,windows:[{used:66.66666666,label:'<周>',resets_at:1900000000}]});
    assert.ok(html.includes('33.3%'));assert.ok(html.includes('&lt;周&gt;'));
    assert.ok(!html.includes('<周>'));
  });
  await check('quota/zero-is-data-not-unavailable',()=>{
    assert.ok(components.quotaSummary({ok:true,windows:[{used:100,label:'周',resets_at:1900000000}]}).includes('0%'));
  });
  await check('escaping/all-interpolation-metacharacters',()=>{
    assert.equal(components.esc(`<&>"'`),'&lt;&amp;&gt;&quot;&#39;');
  });
  console.log(JSON.stringify(results,null,2));
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
