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
// DOM contract fixture for node identity, ordering and refresh behavior.
const dom={next:null,createElement(){return {set innerHTML(value){this.content=dom.next;}};}};
class DomNode {
  constructor(tag,attrs={},children=[]){
    this.nodeType=tag==='#text'?3:1;this.nodeName=tag.toUpperCase();this.namespaceURI=this.nodeType===1?'html':null;
    this.attrs=new Map(Object.entries(attrs));this.childNodes=[];this.parentNode=null;this.ownerDocument=dom;
    this.nodeValue=this.nodeType===3?attrs.text:null;this.scrollTop=0;
    for(const child of children)this.insertBefore(child,null);
  }
  get firstChild(){return this.childNodes[0]||null;}
  get nextSibling(){return this.parentNode?.childNodes[this.parentNode.childNodes.indexOf(this)+1]||null;}
  get id(){return this.getAttribute('id')||'';}
  get attributes(){return [...this.attrs].map(([name,value])=>({name,value}));}
  get dataset(){return Object.fromEntries([...this.attrs].filter(([k])=>k.startsWith('data-')).map(([k,v])=>[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase()),v]));}
  getAttribute(name){return this.attrs.get(name)??null;}
  hasAttribute(name){return this.attrs.has(name);}
  setAttribute(name,value){this.attrs.set(name,String(value));}
  removeAttribute(name){this.attrs.delete(name);}
  matches(selector){return selector.startsWith('.')&&(this.getAttribute('class')||'').split(' ').includes(selector.slice(1));}
  querySelectorAll(selector){const found=[];for(const child of this.childNodes){if(child.matches(selector))found.push(child);found.push(...child.querySelectorAll(selector));}return found;}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  contains(other){return this===other||this.childNodes.some(child=>child.contains(other));}
  insertBefore(node,cursor){node.remove();const index=cursor?this.childNodes.indexOf(cursor):this.childNodes.length;if(index<0)throw Error('Invalid cursor');this.childNodes.splice(index,0,node);node.parentNode=this;return node;}
  remove(){if(this.parentNode){const siblings=this.parentNode.childNodes;siblings.splice(siblings.indexOf(this),1);this.parentNode=null;}}
}
const text=value=>new DomNode('#text',{text:value});
const node=(tag,attrs={},children=[])=>new DomNode(tag,attrs,children);
const patch=(root,next,options)=>{dom.next=next;context.window.NXRuntime.patchHTML(root,'fixture',options);};
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
  await check('refresh/unchanged-elements-and-text-keep-their-identity',()=>{
    const name=text('Account'),avatar=node('span',{class:'avatar'},[text('A')]);
    const card=node('section',{'data-motion-identity':'account'},[avatar,node('strong',{},[name])]);
    const root=node('div',{},[card]);card.scrollTop=37;
    patch(root,node('div',{},[node('section',{'data-motion-identity':'account'},[node('span',{class:'avatar'},[text('A')]),node('strong',{},[text('Account')])])]));
    assert.equal(root.firstChild,card);assert.equal(card.firstChild,avatar);assert.equal(card.childNodes[1].firstChild,name);assert.equal(card.scrollTop,37);
  });
  await check('refresh/quota-change-does-not-replace-account-name',()=>{
    const name=node('strong',{},[text('Account')]),value=text('97%');
    const root=node('section',{},[name,node('b',{},[value])]);
    patch(root,node('section',{},[node('strong',{},[text('Account')]),node('b',{},[text('96%')])]));
    assert.equal(root.firstChild,name);assert.equal(root.childNodes[1].firstChild,value);assert.equal(value.nodeValue,'96%');
  });
  await check('refresh/keyed-account-reorder-reuses-existing-rows',()=>{
    const row=email=>node('button',{'data-action':'detail','data-email':email},[text(email)]);
    const a=row('a'),b=row('b'),root=node('div',{},[a,b]);
    patch(root,node('div',{},[row('b'),row('c'),row('a')]));
    assert.equal(root.childNodes[0],b);assert.equal(root.childNodes[2],a);assert.equal(root.childNodes[1].dataset.email,'c');
    patch(root,node('div',{},[row('a')]));assert.equal(root.childNodes.length,1);assert.equal(root.firstChild,a);assert.equal(b.parentNode,null);
  });
  await check('refresh/editing-field-keeps-caret-composition-and-validation',()=>{
    const field=node('input',{id:'alias',class:'field','aria-invalid':'true',value:'saved'});field.value='正在输入';field.selectionStart=2;field.composing=true;
    const root=node('div',{},[field]);patch(root,node('div',{},[node('input',{id:'alias',class:'field',value:'server'})]));
    assert.equal(root.firstChild,field);assert.equal(field.value,'正在输入');assert.equal(field.selectionStart,2);assert.equal(field.composing,true);assert.equal(field.getAttribute('aria-invalid'),'true');
  });
  await check('refresh/live-motion-style-survives-attribute-update',()=>{
    const control=node('button',{'data-action':'refresh',style:'opacity:0','aria-label':'Refresh'});control.__nxMotionOwned=true;
    const root=node('div',{},[control]);patch(root,node('div',{},[node('button',{'data-action':'refresh',disabled:'','aria-label':'Refreshing'})]));
    assert.equal(root.firstChild,control);assert.equal(control.getAttribute('style'),'opacity:0');assert(control.hasAttribute('disabled'));assert.equal(control.getAttribute('aria-label'),'Refreshing');
  });
  await check('refresh/live-avatar-slot-is-preserved-without-replacing-its-glyph',()=>{
    const slot=node('span',{'aria-hidden':'true'});slot.__nxMotionPlaceholder=true;
    const glyph=text('A'),avatar=node('span',{class:'avatar',style:'position:fixed'},[glyph]);avatar.__nxMotionOwned=true;
    const name=node('strong',{},[text('Account')]),root=node('div',{},[slot,avatar,name]);
    for(let i=0;i<20;i++)patch(root,node('div',{},[node('span',{class:'avatar'},[text('A')]),node('strong',{},[text('Account')])]));
    assert.deepEqual(root.childNodes,[slot,avatar,name]);assert.equal(avatar.firstChild,glyph);
    assert.equal(avatar.getAttribute('style'),'position:fixed');assert(slot.__nxMotionPlaceholder);
    slot.remove();assert.deepEqual(root.childNodes,[avatar,name]);
  });
  await check('refresh/slots-do-not-disturb-keyed-sibling-order-or-cleanup',()=>{
    const slot=node('span');slot.__nxMotionPlaceholder=true;
    const avatar=node('span',{class:'avatar'},[text('A')]);
    const row=id=>node('button',{'data-action':'detail','data-email':id},[text(id)]);
    const a=row('a'),b=row('b'),root=node('div',{},[a,slot,avatar,b]);
    patch(root,node('div',{},[row('b'),node('span',{class:'avatar'},[text('A')]),row('a')]));
    assert.deepEqual(root.childNodes.filter(n=>!n.__nxMotionPlaceholder),[b,avatar,a]);assert.equal(slot.parentNode,root);
    patch(root,node('div',{},[row('a')]));assert.deepEqual(root.childNodes.filter(n=>!n.__nxMotionPlaceholder),[a]);
    slot.remove();assert.deepEqual(root.childNodes,[a]);
  });
  await check('navigation/same-account-card-and-text-survive-route-changes',()=>{
    const glyph=text('A'),name=text('Account A'),avatar=node('span',{class:'avatar'},[glyph]);
    const card=node('section',{'data-motion-identity':'a'},[avatar,node('strong',{},[name])]);
    const body=node('div',{class:'sheet-body detail-body'},[card]),root=node('section',{},[body]);
    patch(root,node('section',{},[node('div',{class:'sheet-body usage-body'},[
      node('section',{'data-motion-identity':'a'},[node('span',{class:'avatar'},[text('A')]),node('strong',{},[text('Account A')])])
    ])]),{preserveFields:false});
    assert.equal(root.firstChild,body);assert.equal(body.firstChild,card);assert.equal(card.firstChild,avatar);
    assert.equal(avatar.firstChild,glyph);assert.equal(card.childNodes[1].firstChild,name);
    assert.equal(body.getAttribute('class'),'sheet-body usage-body');
  });
  await check('navigation/fields-reset-while-passive-refresh-keeps-the-draft',()=>{
    const field=node('input',{id:'alias',class:'field',value:'Account A'});field.value='unsaved A';
    const root=node('section',{},[field]);
    patch(root,node('section',{},[node('input',{id:'alias',class:'field',value:'Account A'})]));
    assert.equal(root.firstChild,field);assert.equal(field.value,'unsaved A');
    const incoming=node('input',{id:'alias',class:'field',value:'Account B'});
    patch(root,node('section',{},[incoming]),{preserveFields:false});
    assert.equal(root.firstChild,incoming);assert.notEqual(root.firstChild,field);assert.equal(root.firstChild.getAttribute('value'),'Account B');
    assert.equal(field.parentNode,null);
  });
  await check('navigation/real-route-renderer-reuses-the-card-and-resets-only-new-route-scroll',()=>{
    const app=fs.readFileSync(path.join(__dirname,'../src/ui/app.js'),'utf8');
    const start=app.indexOf('  function renderSheet('),end=app.indexOf('  const inlineWrites=',start),renderer=app.slice(start,end);
    const avatar=node('span',{class:'avatar'},[text('A')]),card=node('section',{'data-motion-identity':'a'},[avatar]);
    const body=node('div',{class:'sheet-body detail-body'},[card]),sheet=node('section',{},[body]);body.scrollTop=57;
    const incoming=()=>node('section',{},[node('div',{class:'sheet-body usage-body'},[node('section',{'data-motion-identity':'a'},[node('span',{class:'avatar'},[text('A')])])])]);
    const env={sheet,ui:{page:'usage',scope:'a'},data:{accounts:[]},composingField:null,document:{activeElement:null},window:{NXMotion:{paint(){}}},
      esc:components.esc,captureScroll:context.window.NXRuntime.captureScroll,restoreScroll:context.window.NXRuntime.restoreScroll,focusKey:()=>null,restoreFocus(){},
      usageContent:()=>'',pageHead:()=>'',statusRegion:()=>'',paintNotifications(){},feedback:{paint(){}},patchHTML:context.window.NXRuntime.patchHTML};
    dom.next=incoming();vm.runInNewContext(renderer+'renderSheet(false);',env);
    assert.equal(sheet.firstChild,body);assert.equal(body.firstChild,card);assert.equal(card.firstChild,avatar);assert.equal(body.scrollTop,0);
    body.scrollTop=41;dom.next=incoming();vm.runInNewContext(renderer+'renderSheet(true);',env);
    assert.equal(card.firstChild,avatar);assert.equal(body.scrollTop,41);
  });
  await check('tooltip/coordinates-stay-local-to-the-contained-and-scaled-panel',()=>{
    const app=fs.readFileSync(path.join(__dirname,'../src/ui/app.js'),'utf8');
    const start=app.indexOf('  function floatTip('),end=app.indexOf('  for(const event',start),code=app.slice(start,end);
    for(const [left,top,scale,x,y] of [[0,0,1,148,220],[100,80,1,148,220],[50,80,.8,204,300]]){
      const tip={offsetWidth:120,offsetHeight:30,style:{},hidden:true};
      const panel={getBoundingClientRect:()=>({left,top,width:327*scale,height:458*scale})};
      const el={dataset:{floatTip:'Fixture'},getBoundingClientRect:()=>({left:left+(x-4)*scale,top:top+y*scale,width:8*scale})};
      vm.runInNewContext(code+'floatTip(el);',{$:()=>tip,app:panel,el,requestAnimationFrame:fn=>fn(),getComputedStyle:()=>({width:'327px',height:'458px'})});
      assert(Math.abs(parseFloat(tip.style.left)-Math.max(8,Math.min(199,x-60)))<1e-10);
      assert(Math.abs(parseFloat(tip.style.top)-(y-38))<1e-10);assert.equal(tip.hidden,false);
    }
  });
  await check('refresh/changed-widget-type-and-removed-attributes-are-applied',()=>{
    const root=node('div',{},[node('button',{'data-action':'refresh',disabled:''}),node('span',{},[text('old')])]);
    patch(root,node('div',{},[node('button',{'data-action':'refresh'}),node('p',{},[text('new')])]));
    assert(!root.firstChild.hasAttribute('disabled'));assert.equal(root.childNodes[1].nodeName,'P');assert.equal(root.childNodes[1].firstChild.nodeValue,'new');
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
