/* Roster windows come directly from returned data; no browser or account connection needed. */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ctx={window:{}};vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/ui/components.js'),'utf8'),ctx);
const C=ctx.window.NXComponents, results=[];
function check(name,fn){fn();results.push({name,passed:true});}
function values(a){return [...C.quotaColumns(a).matchAll(/<strong class="mono">([^<]+)<\/strong>/g)].map(m=>m[1]);}
function account(windows){return {ok:true,windows};}
check('roster/preserves-returned-window-order',()=>{
 const h=C.quotaColumns(account([{label:'周',used:30,duration_mins:10080},{label:'5h',used:20,duration_mins:300}]));
 assert.ok(h.indexOf('<em>周</em>')<h.indexOf('<em>5h</em>'));
 assert.deepEqual(values(account([{label:'周',used:30},{label:'5h',used:20}])),['70%','80%']);
});
check('roster/preserves-returned-label',()=>{
 assert.deepEqual(values(account([{label:'localized',duration_mins:300,used:10},{label:'localized',duration_mins:10080,used:25}])),['90%','75%']);
});
check('roster/weekly-only-has-no-five-hour-slot',()=>assert.deepEqual(values(account([{label:'周',used:1}])),['99%']));
check('roster/five-only-has-no-week-slot',()=>assert.deepEqual(values(account([{label:'5h',used:0}])),['100%']));
check('roster/exhausted-is-real-zero',()=>assert.deepEqual(values(account([{label:'5h',used:100},{label:'周',used:100}])),['0%','0%']));
check('roster/decimal-rounding-is-bounded',()=>assert.deepEqual(values(account([{label:'5h',used:66.6666667},{label:'周',used:99.96}])),['33.3%','0%']));
check('roster/auth-failure-does-not-render-stale-cache',()=>assert.deepEqual(values({ok:false,error_code:'reauth_required',windows:[{label:'5h',used:25},{label:'周',used:25}]}),[]));
check('roster/transient-refresh-failure-keeps-known-quota',()=>assert.deepEqual(values({ok:false,error_code:'network',windows:[{label:'5h',used:100},{label:'周',used:25}]}),['0%','75%']));
check('roster/invalid-values-never-become-zero',()=>{
 for(const used of [null,undefined,NaN,Infinity,-1,101,true,'33'])assert.deepEqual(values(account([{label:'5h',used}])),[]);
});
check('roster/unknown-window-is-not-relabeled-weekly',()=>assert.deepEqual(values(account([{label:'day',duration_mins:1440,used:12}])),['88%']));
check('roster/api-label-cannot-inject-markup',()=>{
 const h=C.quotaColumns(account([{label:'<img src=x onerror=alert(1)>',duration_mins:300,used:30}]));
 assert.ok(!h.includes('<img'));assert.ok(h.includes('70%'));
});
check('roster/unavailable-has-no-invented-window',()=>{
 const h=C.quotaColumns(null);assert.equal((h.match(/class="roster-quotas"/g)||[]).length,1);
 assert.equal(values(null).length,0);assert.ok(!h.includes('chevron'));
});
check('roster/low-balance-color-does-not-remove-label',()=>{
 const h=C.quotaColumns(account([{label:'周',used:95}]));
 assert.ok(h.includes('roster-quota danger'));assert.ok(h.includes('<em>周</em>'));
});
check('roster/weekly-only-never-invents-five-hour-label',()=>{
 const h=C.quotaColumns({...account([{label:'周',used:12}]),plan:'pro'});
 assert.ok(!h.includes('5h'));assert.ok(h.includes('<em>周</em>'));assert.ok(!h.includes('—'));
});
check('roster/plan-name-does-not-suppress-real-five-hour-window',()=>{
 const h=C.quotaColumns({...account([{label:'5h',used:12}]),plan:'pro'});
 assert.ok(h.includes('<em>5h</em>'));assert.deepEqual(values({...account([{label:'5h',used:12}]),plan:'pro'}),['88%']);
});
console.log(JSON.stringify(results,null,2));
