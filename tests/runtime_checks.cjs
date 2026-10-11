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
  matches(selector){return selector==='.field'&&(this.getAttribute('class')||'').split(' ').includes('field');}
  insertBefore(node,cursor){node.remove();const index=cursor?this.childNodes.indexOf(cursor):this.childNodes.length;if(index<0)throw Error('Invalid cursor');this.childNodes.splice(index,0,node);node.parentNode=this;return node;}
  remove(){if(this.parentNode){const siblings=this.parentNode.childNodes;siblings.splice(siblings.indexOf(this),1);this.parentNode=null;}}
}
const text=value=>new DomNode('#text',{text:value});
const node=(tag,attrs={},children=[])=>new DomNode(tag,attrs,children);
const patch=(root,next)=>{dom.next=next;context.window.NXRuntime.patchHTML(root,'fixture');};
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
