/* Offline DOM/animation simulation. No browser, native app, credentials or network. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,'_wip/build/resources/panel.html'),'utf8');
const scripts=[...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)].map(m=>m[1]);
assert.equal(scripts.length,1);scripts.forEach(s=>new vm.Script(s));
const source=fs.readFileSync(path.join(root,'src/ui/motion.js'),'utf8');
const code=source.replace('  window.NXMotion = {','  window.__motionTest={models,bindings,trajectory,get page(){return page},get scene(){return scene}};\n  window.NXMotion = {');
assert.notEqual(code,source);
const kebab=p=>String(p).replace(/[A-Z]/g,c=>'-'+c.toLowerCase());
function style(){const values=new Map(),priorities=new Map(),api={setProperty(p,v,priority=''){values.set(p,String(v));priorities.set(p,priority)},getPropertyValue:p=>values.get(p)||'',getPropertyPriority:p=>priorities.get(p)||'',removeProperty(p){values.delete(p);priorities.delete(p)},copy(){const s=style();for(const [k,v]of values)s.setProperty(k,v,priorities.get(k));return s}};return new Proxy(api,{get:(t,p)=>p in t?t[p]:t.getPropertyValue(kebab(p)),set:(t,p,v)=>{t.setProperty(kebab(p),v);return true}})}
let time=0,sequence=0,rafs=new Map(),animations=new Set(),layoutReads=0,styleReads=0,allocations=0;
class Element{
  constructor(tag='div',cls='',box={left:0,top:0,width:1,height:1},css={}){this.tagName=tag.toUpperCase();this.attrs=new Map();this.dataset={};this.style=style();this.children=[];this.parentNode=null;this.hidden=false;this.inert=false;this.scrollTop=0;this._box={...box};this._css={display:'block',opacity:'1','font-size':'14px','font-weight':'650','font-family':'Segoe UI','line-height':'18px','background-color':'transparent','border-radius':'12px',...css};this.textContent='';this.events=new Map();this.animateCalls=[];this.className=cls;}
  get id(){return this.attrs.get('id')||''}set id(v){this.setAttribute('id',v)}
  get className(){return this.attrs.get('class')||''}set className(v){this.setAttribute('class',v)}
  get attributes(){return [...this.attrs].map(([name,value])=>({name,value}))}
  get isConnected(){return !!this.parentNode||this.id==='app'}
  setAttribute(n,v){this.attrs.set(n,String(v));if(n.startsWith('data-'))this.dataset[n.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=String(v)}
  getAttribute(n){return this.attrs.get(n)||null}
  removeAttribute(n){this.attrs.delete(n);if(n.startsWith('data-'))delete this.dataset[n.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]}
  append(...ns){for(const n of ns){n.remove();n.parentNode=this;this.children.push(n)}}
  insertBefore(n,before){n.remove();n.parentNode=this;const i=this.children.indexOf(before);if(i<0)this.children.push(n);else this.children.splice(i,0,n);if(n.__nxMotionPlaceholder&&before){n._box={...before._box};n._scale=before._scale}}
  contains(n){return this===n||this.children.some(c=>c.contains(n))}
  remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(n=>n!==this);this.parentNode=null}
  cloneNode(deep){const n=new Element(this.tagName,'',this._box,this._css);for(const a of this.attributes)n.setAttribute(a.name,a.value);n.style=this.style.copy();n.textContent=this.textContent;if(deep)n.append(...this.children.map(c=>c.cloneNode(true)));return n}
  matches(selector){return selector.split(',').some(s=>{const ps=s.trim().split(/\s*>\s*|\s+/),simple=(n,p)=>p.startsWith('.')?p.slice(1).split('.').every(c=>n.className.split(/\s+/).includes(c)):p.startsWith('#')?n.id===p.slice(1):n.tagName.toLowerCase()===p.toLowerCase();if(!simple(this,ps.pop()))return false;let n=this.parentNode;while(ps.length){const p=ps.pop();while(n&&!simple(n,p))n=n.parentNode;if(!n)return false;n=n.parentNode}return true})}
  querySelectorAll(selector){const result=[];for(const c of this.children){if(selector==='*'||c.matches(selector))result.push(c);result.push(...c.querySelectorAll(selector))}return result}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null}
  addEventListener(name,fn){if(!this.events.has(name))this.events.set(name,[]);this.events.get(name).push(fn)}
  emit(name,event={}){for(const fn of this.events.get(name)||[])fn(event)}
  getBoundingClientRect(){layoutReads++;let{left,top,width,height}=this._box;const scale=this._scale||1;if(this.style.position==='fixed'){let app=this;while(app&&app.id!=='app')app=app.parentNode;if(this.style.left!=='auto')left=(app?app._box.left:0)+parseFloat(this.style.left)*scale;if(this.style.top!=='auto')top=(app?app._box.top:0)+parseFloat(this.style.top)*scale;width=parseFloat(this.style.width)*scale;height=parseFloat(this.style.height)*scale}const m=this.style.transform.match(/translate\(([-.\d]+)px,([-.\d]+)px\)\s*scale\(([-.\d]+),([-.\d]+)\)/);if(m){left+=Number(m[1])*scale;top+=Number(m[2])*scale;width*=Number(m[3]);height*=Number(m[4])}return{left,top,width,height,right:left+width,bottom:top+height}}
  animate(frames,options){const a={frames,options,clock:time,elapsed:0,cancelled:false,finished:false,get currentTime(){return this.elapsed+time-this.clock},set currentTime(v){this.elapsed=v;this.clock=time},cancel(){this.cancelled=true;animations.delete(this);this.oncancel?.()}};this.animateCalls.push(a);animations.add(a);return a}
}
const easing=p=>{let lo=0,hi=1;for(let i=0;i<30;i++){const t=(lo+hi)/2,x=3*(1-t)**2*t*.2+3*(1-t)*t*t*.25+t**3;if(x<p)lo=t;else hi=t}const t=(lo+hi)/2;return 3*(1-t)**2*t*.7+3*(1-t)*t*t+t**3};
function computed(n){styleReads++;return new Proxy({getPropertyValue(p){if(p==='visibility'){for(let a=n;a;a=a.parentNode)if(a.id==='home'&&a.inert&&html.includes('#home[inert] { visibility: hidden; }'))return'hidden';return n.style.visibility||'visible'}if(p==='display'&&n.hidden)return'none';if(p==='opacity'){const a=n.animateCalls.filter(a=>!a.cancelled&&!a.finished&&a.frames.some(f=>'opacity'in f)).at(-1);if(a){const elapsed=a.currentTime-(a.options.delay||0);if(elapsed<0&&['backwards','both'].includes(a.options.fill))return String(a.frames[0].opacity);if(elapsed>=0&&elapsed<a.options.duration){const ratio=easing(elapsed/a.options.duration);return String(a.frames[0].opacity+(a.frames.at(-1).opacity-a.frames[0].opacity)*ratio)}}}return n.style.getPropertyValue(p)||n._css[p]||''}},{get:(t,p)=>p in t?t[p]:t.getPropertyValue(kebab(p))})}
function setup(scale=1,media=false){
  time=0;sequence=0;rafs=new Map();animations=new Set();layoutReads=0;styleReads=0;allocations=0;
  const pixel=(x,y,w,h)=>({left:100+x*scale,top:100+y*scale,width:w*scale,height:h*scale});
  const el=(t,c,x,y,w,h,css={})=>{const n=new Element(t,c,pixel(x,y,w,h),css);n._scale=scale;return n};
  const app=el('div','',0,0,327,458);app.id='app';app.clientWidth=327;app.clientHeight=458;
  const document={documentElement:{dataset:{}},hidden:false,events:new Map(),addEventListener:Element.prototype.addEventListener,emit:Element.prototype.emit,getElementById:id=>id==='app'?app:app.querySelector('#'+id),createElement:t=>{allocations++;return new Element(t)}};
  const window={events:new Map(),addEventListener:Element.prototype.addEventListener,emit:Element.prototype.emit};
  const preference={matches:media,events:new Map(),addEventListener:Element.prototype.addEventListener,change(value){this.matches=value;Element.prototype.emit.call(this,'change')}};
  vm.runInNewContext(code,{window,document,Element,getComputedStyle:computed,matchMedia:()=>preference,performance:{now:()=>time},requestAnimationFrame:fn=>{const id=++sequence;rafs.set(id,fn);return id},cancelAnimationFrame:id=>rafs.delete(id)});
  const identity=(node,uid,x,y,size=40)=>{node.setAttribute(node.className.includes('current-card')?'data-motion-identity':'data-email',uid);const avatar=el('span','avatar',x,y,size,size,{'border-radius':'50%','font-size':size===34?'12.75px':size===32?'12px':'15px'}),copy=el('div','identity-copy',x+size+10,y+3,120,34),title=el('span','identity-title',x+size+10,y+3,90,18),name=el('strong','account-name',x+size+10,y+3,66,18);avatar.textContent=uid;name.textContent='Account '+uid;title.append(name);copy.append(title);node.append(avatar,copy);return{root:node,avatar,name}};
  const surface=(kind,uid='b',all=false)=>{const home=kind==='home',node=el(home?'main':'section',home?'':'sheet',0,0,327,458,{'background-color':'rgb(255,255,255)'});node.id=home?'home':'sheet';const head=el('header',home?'header':'sheet-head',14,7,299,43),heading=el(home?'div':'h2',home?'brand':'',54,15,170,22);heading.textContent=kind;head.append(heading);node.append(head);const body=home?node:el('div','sheet-body',0,50,327,408);if(!home)node.append(body);const profile=identity(el('section','card current-card',14,53,299,all?70:112),all?'all':uid,32,68);body.append(profile.root);let row;if(home||all){const list=el('div',home?'roster':'usage-accounts',14,260,299,140);row=identity(el('button',home?'row':'account-usage-row',14,278,299,44),'b',21,283,34);row.root.setAttribute('data-action',home?'detail':'usage-account');list.append(row.root);body.append(list)}let filter;if(kind==='usage'){filter=el('div','usage-filter',14,all?129:171,299,32);for(const value of[7,30,180,'all']){const button=el('button','',14,172,74,26);button.setAttribute('data-action','usage-period');button.setAttribute('data-value',value);filter.append(button)}body.append(filter)}const content=el('div','content',14,220,299,150);body.append(content);return{node,head,heading,body,profile,row,filter,content}};
  let home=null,sheet=null;
  const mount=node=>{if(node.id==='home'){if(home&&home!==node)home.remove();if(!node.parentNode)app.append(node);home=node;home.inert=false;if(sheet)sheet.hidden=true}else{if(!home){home=surface('home','a').node;app.append(home)}home.inert=true;if(sheet&&sheet!==node)sheet.remove();if(!node.parentNode)app.append(node);sheet=node;sheet.hidden=false}};
  const tick=ms=>{time+=ms;for(const a of[...animations])if(a.currentTime>=a.options.duration+(a.options.delay||0)){a.finished=true;animations.delete(a);a.onfinish?.()}const pending=[...rafs.values()];rafs.clear();pending.forEach(fn=>fn(time))};
  return{app,document,window,preference,pixel,el,surface,mount,tick,motion:window.NXMotion,test:window.__motionTest};
}
function drawn(node){for(let a=node;a;a=a.parentNode)if(a.hidden||computed(a).visibility==='hidden'||computed(a).display==='none'||Number(computed(a).opacity)<.001)return false;return true}
const labels=e=>e.app.querySelectorAll('*').filter(n=>n.textContent&&drawn(n)).map(n=>n.textContent);
function clean(e){const roots=e.app.children.filter(n=>n.id==='home'||n.id==='sheet');assert.equal(roots.filter(drawn).length,1);roots.forEach(n=>assert.notEqual(computed(n).backgroundColor,'transparent'));assert.equal(e.app.querySelectorAll('.nx-motion-layer').length,0);assert(e.app.querySelectorAll('*').filter(n=>n.__nxMotionPlaceholder).length<=1);assert(e.test.models.size<=2);assert(rafs.size<=1)}
let checks=0;const check=(label,fn)=>{fn();checks++;console.log('PASS '+label)};
function entering(scale=1){const e=setup(scale),old=e.surface('home','a');e.mount(old.node);e.motion.begin(old.node,1,'b');const next=e.surface('detail','b');e.mount(next.node);e.motion.paint(next.node);return{e,old,next}}
check('persistent home and moving identity never overlay multiple pages',()=>{const{e,old,next}=entering();assert(e.app.children.includes(old.node));assert.equal(computed(old.node).visibility,'hidden');assert.equal(e.test.models.size,1);assert.equal(e.test.page.contentDelay,0);for(const t of[0,16,33,67,100,140,200,300,420]){e.tick(t-time);clean(e);const text=labels(e);assert(!text.includes('home'));assert(!text.includes('Account a'));assert(text.filter(x=>x==='Account b').length<=1);if(e.test.page&&t<e.test.page.contentDelay)assert.equal(Number(computed(next.content).opacity),0)}e.tick(800);assert.equal(e.test.scene,null);assert.equal(rafs.size,0);assert.equal(animations.size,0)});
check('detail to confirmation moves the real avatar and real text',()=>{const{e,next}=entering();e.tick(45);const confirm=e.surface('confirm','b');confirm.profile.root.className='confirm-account';confirm.profile.root.setAttribute('data-email','b');confirm.profile.avatar._box=e.pixel(35,244,40,40);confirm.profile.name._box=e.pixel(85,247,66,18);e.motion.begin(next.node,1,'b');e.mount(confirm.node);e.motion.paint(confirm.node);for(const dt of[0,16,34,50,80,100,200]){e.tick(dt);clean(e);assert(labels(e).filter(x=>x==='Account b').length<=1);assert(!labels(e).includes('detail'))}e.motion.stop()});
check('interrupted return preserves pose and velocity',()=>{const{e,next}=entering();e.tick(80);const m=e.test.models.get('b:avatar'),y=m.pose.y,v=m.velocity.y;e.motion.begin(next.node,-1);const back=e.surface('home','a');e.mount(back.node);e.motion.paint(back.node);assert.equal(e.test.models.get('b:avatar'),m);assert.equal(m.pose.y,y);assert.equal(m.velocity.y,v);assert.equal(m.goal.y,300);e.tick(1);assert(m.pose.y<y);e.tick(900);clean(e);assert.equal(rafs.size,0)});
check('asynchronous rebuild resumes one clock and does not replay',()=>{const{e}=entering();e.tick(75);const m=e.test.models.get('b:avatar'),y=m.pose.y,v=m.velocity.y,start=e.test.page.start,delay=e.test.page.contentDelay;const rebuilt=e.surface('detail','b');e.mount(rebuilt.node);e.motion.paint(rebuilt.node);assert.equal(e.test.models.get('b:avatar'),m);assert.equal(m.pose.y,y);assert.equal(m.velocity.y,v);assert.equal(m.live,rebuilt.profile.avatar);assert.equal(e.test.page.start,start);assert.equal(e.test.page.contentDelay,delay);e.tick(900);const late=e.surface('detail','b');e.mount(late.node);e.motion.paint(late.node);assert.equal(e.test.scene,null);assert.equal(late.content.animateCalls.length,0);clean(e)});
check('home details and personal usage keep matching cards stationary',()=>{const e=setup(),old=e.surface('home','b');e.mount(old.node);e.motion.begin(old.node,1,'b');const next=e.surface('detail','b');e.mount(next.node);e.motion.paint(next.node);assert.equal(e.test.models.size,0);assert.equal(e.test.page.contentDelay,0);assert.equal(next.profile.root.animateCalls.length,0);const usage=e.surface('usage','b');e.motion.begin(next.node,1,'b');e.mount(usage.node);e.motion.paint(usage.node);assert.equal(e.test.models.size,0);assert.equal(usage.profile.root.animateCalls.length,0);e.motion.stop()});
check('time range remains a live control while moving between usage views',()=>{const e=setup(),old=e.surface('usage','all',true);e.mount(old.node);e.motion.begin(old.node,1,'b');const next=e.surface('usage','b');e.mount(next.node);e.motion.paint(next.node);const m=e.test.models.get('usage-filter');assert(m);assert.equal(m.goal.y-m.pose.y,42);assert.equal(next.filter.animateCalls.length,0);assert(next.filter.children.every(n=>n.getAttribute('data-action')==='usage-period'&&!n.inert));e.tick(90);const y=m.pose.y,v=m.velocity.y;e.motion.begin(next.node,-1,'all');const back=e.surface('usage','all',true);e.mount(back.node);e.motion.paint(back.node);assert.equal(e.test.models.get('usage-filter'),m);assert.equal(m.pose.y,y);assert.equal(m.velocity.y,v);e.motion.setEnabled(false);assert.equal(back.filter.style.transform,'');assert.equal(e.test.bindings.size,0);clean(e)});
check('stationary time controls do not blink',()=>{const e=setup(),old=e.surface('usage','b');e.mount(old.node);e.motion.begin(old.node,1,'b');const next=e.surface('usage','b');e.mount(next.node);e.motion.paint(next.node);assert.equal(next.filter.animateCalls.length,0);assert.equal(e.test.models.size,0);e.motion.stop()});
check('reduced motion scrolling and static mode restore all styles',()=>{const{e,next}=entering();e.preference.change(true);assert.equal(e.test.scene,null);assert.equal(next.profile.avatar.style.opacity,'');assert.equal(rafs.size,0);e.preference.change(false);e.motion.begin(next.node,-1);const back=e.surface('home','a');e.mount(back.node);e.motion.paint(back.node);e.app.emit('wheel');assert.equal(e.test.scene,null);assert.equal(animations.size,0);clean(e)});
check('coordinate conversion handles a scaled surface',()=>{const e=setup(.8),old=e.surface('home','a');e.mount(old.node);e.motion.begin(old.node,1,'b');const next=e.surface('detail','b');e.mount(next.node);e.motion.paint(next.node);const m=e.test.models.get('b:avatar');assert(Math.abs(m.pose.y-300)<1e-8);assert(Math.abs(m.goal.y-88)<1e-8);assert(Math.abs(m.goal.w-40)<1e-8);clean(e);e.motion.stop()});
check('thirty rapid transitions have bounded layers and zero idle frames',()=>{const e=setup();let current=e.surface('home','a');e.mount(current.node);for(let i=0;i<30;i++){e.motion.begin(current.node,i%2?-1:1,'b');current=e.surface(i%2?'home':'detail',i%2?'a':'b');e.mount(current.node);e.motion.paint(current.node);e.tick(10);clean(e)}e.tick(1000);assert.equal(e.test.scene,null);assert.equal(e.test.models.size,0);assert.equal(rafs.size,0);assert.equal(animations.size,0)});
check('unrelated accounts remove previous moving labels',()=>{const{e,next}=entering();e.tick(30);e.motion.begin(next.node,1,'c');const other=e.surface('detail','c');e.mount(other.node);e.motion.paint(other.node);assert.equal(e.test.models.size,0);assert.equal(e.app.querySelectorAll('.nx-motion-layer').length,0);assert(!labels(e).includes('Account b'));clean(e);e.motion.stop()});
check('missing animation support uses the normal page',()=>{const animate=Element.prototype.animate;delete Element.prototype.animate;try{const e=setup(),old=e.surface('home','a');e.mount(old.node);e.motion.begin(old.node,1,'b');const next=e.surface('detail','b');e.mount(next.node);e.motion.paint(next.node);assert.equal(e.test.scene,null);clean(e)}finally{Element.prototype.animate=animate}});
check('content phases cap at 32 milliseconds and ignore offscreen content',()=>{const e=setup(),old=e.surface('detail','b');e.mount(old.node);e.motion.begin(old.node,1,'b');const next=e.surface('detail','b'),second=e.el('section','second',14,378,299,25),third=e.el('section','third',14,408,299,25),edge=e.el('section','edge',14,440,299,16),offscreen=e.el('section','offscreen',14,500,299,25),foot=e.el('footer','sheet-foot',14,426,299,32);next.body.append(second,third,edge,offscreen);next.node.append(foot);e.mount(next.node);e.motion.paint(next.node);const a=next.content.animateCalls.at(-1),b=second.animateCalls.at(-1),c=third.animateCalls.at(-1),d=edge.animateCalls.at(-1);assert.equal(a.options.duration,240);assert.equal(b.options.delay-a.options.delay,16);assert.equal(c.options.delay-a.options.delay,32);assert.equal(d.options.delay,c.options.delay);assert.equal(offscreen.animateCalls.length,0);assert.equal(a.frames[0].transform,'translateY(4px)');assert(!d.frames[0].transform);assert.equal(foot.animateCalls.at(-1).options.delay,c.options.delay);assert.equal(e.test.page.endElapsed,272);e.tick(245);assert(e.test.page);e.tick(35);assert.equal(e.test.page,null);assert.equal(animations.size,0);assert.equal(rafs.size,0);clean(e)});
check('time range feedback animates one chart and keeps totals fixed',()=>{const e=setup(),old=e.surface('usage','b');e.mount(old.node);const summary=e.el('section','usage-summary',14,220,299,110),total=e.el('div','usage-total',28,224,120,28),chart=e.el('div','trend',28,268,272,48);summary.append(total,chart);old.body.append(summary);e.motion.reveal(summary);assert.equal(summary.animateCalls.length,0);assert.equal(total.animateCalls.length,0);assert.equal(chart.animateCalls.length,1);assert.equal(chart.animateCalls[0].frames[0].opacity,.65);assert.equal(chart.animateCalls[0].options.duration,150);e.tick(200);assert.equal(animations.size,0);e.motion.begin(old.node,1,'b');const next=e.surface('detail','b');e.mount(next.node);e.motion.paint(next.node);e.motion.reveal(summary);assert.equal(chart.animateCalls.length,1);e.motion.stop();e.motion.setEnabled(false);e.motion.reveal(summary);assert.equal(chart.animateCalls.length,1)});
check('return uses a smaller offset and resumes after data rebuild',()=>{const e=setup(),old=e.surface('detail','b');e.mount(old.node);e.motion.begin(old.node,-1,'b');const next=e.surface('detail','b');e.mount(next.node);e.motion.paint(next.node);assert.equal(next.content.animateCalls.at(-1).frames[0].transform,'translateY(-3px)');e.tick(30);const rebuilt=e.surface('detail','b');e.mount(rebuilt.node);e.motion.paint(rebuilt.node);assert.equal(rebuilt.content.animateCalls.at(-1).currentTime,30);e.tick(260);assert.equal(e.test.page,null);assert.equal(animations.size,0);clean(e)});
check('hiding the panel and unloading remove temporary layers',()=>{const{e,next}=entering();e.tick(30);e.document.hidden=true;e.document.emit('visibilitychange');assert.equal(rafs.size,0);assert.equal(animations.size,0);assert.equal(e.test.scene,null);assert.equal(next.profile.avatar.style.opacity,'');clean(e);e.document.hidden=false;e.motion.begin(next.node,-1);const back=e.surface('home','a');e.mount(back.node);e.motion.paint(back.node);e.window.emit('pagehide');assert.equal(rafs.size,0);assert.equal(e.test.scene,null);clean(e)});
check('account names always use the real unscaled and unclipped element',()=>{
  const {e,next}=entering();
  for(const dt of [0,70,90,120,180]){
    e.tick(dt);
    assert.equal(next.profile.name.style.transform,'');
    assert.equal(next.profile.name.style.opacity,'');
    assert.equal(next.profile.name.style.width,'');
    assert.equal(next.profile.name.style.lineHeight,'');
    assert(![...e.test.models.values()].some(m=>m.kind==='name'));
    assert.equal(e.app.querySelectorAll('.nx-motion-layer').length,0);
    clean(e);
  }
});
check('shared elements reach exact bounds at 300ms without a settling tail',()=>{
  const {e,next}=entering(),model=e.test.models.get('b:avatar');
  e.tick(150);e.motion.paint(next.node);assert.equal(model.start,0);
  e.tick(150);
  for(const key of Object.keys(model.goal)){assert.equal(model.pose[key],model.goal[key]);assert.equal(model.velocity[key],0);}
  const finished={...model.pose};e.tick(30);assert.deepEqual({...model.pose},finished);
  e.motion.paint(next.node);assert.equal(model.start,0);assert.deepEqual({...model.pose},finished);
  e.tick(500);assert.equal(e.test.scene,null);assert.equal(rafs.size,0);
});
check('trajectory retains velocity and acceleration and rests at an exact endpoint',()=>{
  const e=setup();
  for(const speed of [-700,0,400])for(const acceleration of [-2500,0,3500]){
    assert.deepEqual(Array.from(e.test.trajectory(200,speed,acceleration,10,0,.3)),[200,speed,acceleration]);
    assert.deepEqual(Array.from(e.test.trajectory(200,speed,acceleration,10,.3,.3)),[10,0,0]);
    const [position,velocity,endAcceleration]=e.test.trajectory(200,speed,acceleration,10,.299999,.3);
    assert(Math.abs(position-10)<.0001);assert(Math.abs(velocity)<.01);assert(Math.abs(endAcceleration)<1);
  }
});
check('fractional native CSS dimensions do not shift the real avatar',()=>{
  const e=setup();e.app._box.width=326.857142857;e.app.clientWidth=327;
  e.app._css.width='326.857142857px';e.app._css.height='458px';
  const old=e.surface('home','a');e.mount(old.node);e.motion.begin(old.node,1,'b');
  const next=e.surface('detail','b');next.profile.avatar._css['font-size']='15px';e.mount(next.node);e.motion.paint(next.node);
  const model=e.test.models.get('b:avatar');
  assert(Math.abs(model.goal.x-52)<1e-9);assert.equal(model.goal.w,40);
  assert.equal(model.live,next.profile.avatar);assert.equal(computed(model.live).fontSize,'15px');
  e.tick(300);assert.equal(model.pose.x,52);assert.equal(model.pose.w,40);e.motion.stop();
});
check('background paints retain animation while measuring final bounds',()=>{
  const e=setup(),old=e.surface('usage','all',true);e.mount(old.node);e.motion.begin(old.node,1,'b');
  const next=e.surface('usage','b');e.mount(next.node);e.motion.paint(next.node);e.tick(60);
  const model=e.test.models.get('usage-filter'),goal={...model.goal},start=model.start;
  e.motion.paint(next.node);assert.deepEqual({...model.goal},goal);assert.equal(model.start,start);
  assert.equal(next.filter.children.filter(n=>n.inert).length,0);e.tick(800);clean(e);
});
check('disabled content finishes at its real opacity instead of flashing',()=>{
  const e=setup(),old=e.surface('detail','b');e.mount(old.node);e.motion.begin(old.node,1,'b');
  const next=e.surface('detail','b');next.content._css.opacity='.46';e.mount(next.node);e.motion.paint(next.node);
  assert.equal(next.content.animateCalls.at(-1).frames.at(-1).opacity,.46);
  e.tick(400);assert.equal(Number(computed(next.content).opacity),.46);assert.equal(animations.size,0);
});
check('repeated chart feedback cancels the prior fade and returns to base opacity',()=>{
  const e=setup(),summary=e.el('section','usage-summary',14,220,299,110),chart=e.el('div','trend',28,268,272,48);summary.append(chart);
  e.motion.reveal(summary);const first=chart.animateCalls[0];e.tick(50);e.motion.reveal(summary);
  assert(first.cancelled);assert.equal(chart.animateCalls[1].frames.at(-1).opacity,1);e.tick(200);assert.equal(animations.size,0);
});
check('navigation never clones an avatar or switches its opacity',()=>{
  const clone=Element.prototype.cloneNode;Element.prototype.cloneNode=()=>{throw Error('No avatar copies allowed')};
  try{
    const {e,next}=entering(),avatar=next.profile.avatar,parent=avatar.parentNode,model=e.test.models.get('b:avatar');
    assert.equal(model.live,avatar);assert.equal(avatar.style.position,'fixed');assert.equal(avatar.style.opacity,'');
    assert.equal(parent.children.filter(n=>n.__nxMotionPlaceholder).length,1);
    for(const dt of [16,16,16,32,64,80,76]){e.tick(dt);assert.equal(avatar.parentNode,parent);assert.equal(avatar.style.opacity,'');}
    assert.equal(avatar.style.position,'');assert.equal(parent.children.filter(n=>n.__nxMotionPlaceholder).length,0);
    assert.equal(parent.querySelectorAll('.avatar').length,1);assert.equal(e.test.scene,null);clean(e);
  }finally{Element.prototype.cloneNode=clone;}
});
check('passive refresh does not recreate animations or layout slots',()=>{
  const {e,next}=entering(),model=e.test.models.get('b:avatar'),slot=model.slot;
  const effect=next.content.animateCalls[0],heading=next.heading.animateCalls[0],allocated=allocations;
  for(let i=0;i<30;i++){e.tick(3);e.motion.paint(next.node);assert.equal(next.content.animateCalls.length,1);assert.equal(next.heading.animateCalls.length,1);assert.equal(model.slot,slot);assert(!effect.cancelled);assert(!heading.cancelled);}
  assert.equal(allocations,allocated);assert.equal(model.start,0);e.tick(500);clean(e);
});
check('frame loop performs no layout reads style reads or element allocation',()=>{
  const {e}=entering();
  for(let i=0;i<17;i++){
    const before=[layoutReads,styleReads,allocations];e.tick(16);
    assert.deepEqual([layoutReads,styleReads,allocations],before);
  }
  e.tick(100);assert.equal(rafs.size,0);assert.equal(animations.size,0);assert.equal(e.test.bindings.size,0);
});
check('the last live-avatar frame and resting layout have matching geometry',()=>{
  for(const scale of [0.8,1,1.25,1.5,1.75]){
    const e=setup(scale),old=e.surface('home','a');e.mount(old.node);e.motion.begin(old.node,1,'b');
    const next=e.surface('detail','b'),avatar=next.profile.avatar,rest=avatar.getBoundingClientRect();e.mount(next.node);e.motion.paint(next.node);
    const model=e.test.models.get('b:avatar');e.tick(299.9);const last=avatar.getBoundingClientRect();
    e.tick(.1);const settled=avatar.getBoundingClientRect();
    for(const key of ['left','top','width','height']){assert(Math.abs(last[key]-settled[key])<.001);assert.equal(settled[key],rest[key]);}
    assert.equal(avatar.style.transform,'');assert.equal(avatar.style.position,'');assert.equal(model.velocity.y,0);assert.equal(model.acceleration.y,0);
    assert.equal(e.test.models.size,0);assert.equal(e.test.scene,null);e.tick(500);assert.deepEqual(avatar.getBoundingClientRect(),settled);
  }
});
check('interrupted motion preserves acceleration as well as position and velocity',()=>{
  const {e,next}=entering();e.tick(95);const model=e.test.models.get('b:avatar');
  const before=[model.pose.y,model.velocity.y,model.acceleration.y];
  e.motion.begin(next.node,-1,'b');const back=e.surface('home','a');e.mount(back.node);e.motion.paint(back.node);
  assert.deepEqual([model.pose.y,model.velocity.y,model.acceleration.y],before);
  assert.deepEqual([model.origin.y,model.initialVelocity.y,model.initialAcceleration.y],before);
  e.tick(.01);assert(Math.abs(model.velocity.y-before[1])<2);assert(Math.abs(model.acceleration.y-before[2])<20);
  e.tick(800);clean(e);assert.equal(e.test.bindings.size,0);
});
check('parents of moving controls never add a second entrance transform',()=>{
  const {e,next}=entering();e.tick(120);e.motion.begin(next.node,-1,'b');
  const back=e.surface('home','a');e.mount(back.node);e.motion.paint(back.node);
  const model=e.test.models.get('b:avatar');
  for(let ancestor=model.live.parentNode;ancestor&&ancestor!==back.node;ancestor=ancestor.parentNode)assert.equal(ancestor.animateCalls.length,0);
  e.tick(400);clean(e);
});
check('a completed movement cannot restart during later data refreshes',()=>{
  const {e,next}=entering(),avatar=next.profile.avatar;e.tick(300);assert.equal(avatar.style.position,'');
  const allocated=allocations;for(let i=0;i<20;i++){e.motion.paint(next.node);e.tick(2);}
  assert.equal(allocations,allocated);assert.equal(e.test.models.size,0);assert.equal(avatar.style.opacity,'');clean(e);
});
check('frequent DOM rebuilds retain bounded references and clean old slots',()=>{
  const {e}=entering();let current;
  for(let i=0;i<70;i++){
    e.tick(2);current=e.surface('detail','b');e.mount(current.node);e.motion.paint(current.node);
    assert(e.test.page.sharedPath.size<10);assert(e.test.bindings.size<10);assert.equal(e.app.querySelectorAll('*').filter(n=>n.__nxMotionPlaceholder).length,1);
  }
  e.tick(400);assert.equal(e.test.scene,null);assert.equal(e.test.bindings.size,0);assert.equal(rafs.size,0);clean(e);
});
check('a button press cannot change the moving avatar coordinate system',()=>{
  const {e,next}=entering();e.tick(100);e.motion.begin(next.node,-1,'b');
  const back=e.surface('home','a');e.mount(back.node);e.motion.paint(back.node);
  const row=back.row.root,avatar=back.row.avatar;
  assert.equal(row.style.transform,'none');assert.equal(row.style.transition,'none');assert.equal(avatar.style.pointerEvents,'none');
  row._css.transform='scale(.995)';e.tick(20);assert.equal(computed(row).transform,'none');
  row._css.transform='none';e.tick(400);
  assert.equal(row.style.transform,'');assert.equal(row.style.transition,'');assert.equal(avatar.style.pointerEvents,'');clean(e);
});
check('real-avatar geometry follows its continuous trajectory in every frame',()=>{
  const {e,next}=entering(),model=e.test.models.get('b:avatar');
  for(let i=0;i<18;i++){
    e.tick(16);const box=next.profile.avatar.getBoundingClientRect();
    assert(Math.abs(box.left+box.width/2-100-model.pose.x)<.0001);assert(Math.abs(box.top+box.height/2-100-model.pose.y)<.0001);
    // Five decimal places in the scale matrix quantize a 40px avatar by at
    // most 0.0002px. Keep the physical geometry tolerance below 0.001px.
    assert(Math.abs(box.width-model.pose.w)<.001);assert(Math.abs(box.height-model.pose.h)<.001);
  }
  e.tick(20);clean(e);
});
check('paint containment keeps fixed motion inside the panel',()=>{
  const css=fs.readFileSync(path.join(root,'src/ui/common.css'),'utf8');
  assert(/#app\s*\{[^}]*contain:\s*paint/.test(css));assert(!source.includes('cloneNode('));
});
check('avatar motion retains its resting raster origin at fractional display scales',()=>{
  for(const scale of [1.25,1.5,1.75,2]){
    const {e,next}=entering(scale),model=e.test.models.get('b:avatar');
    assert.equal(model.live.style.left,'auto');assert.equal(model.live.style.top,'auto');
    for(const key of ['x','y','w','h'])assert(Math.abs(model.base[key]-model.goal[key])<.001);
    e.tick(500);assert.equal(next.profile.avatar.style.willChange,'');clean(e);
  }
  const css=fs.readFileSync(path.join(root,'src/ui/common.css'),'utf8');
  assert(/\.avatar, \.usage-brand\s*\{\s*will-change:\s*transform/.test(css));
  assert(/:root\[data-motion="on"\] :is\(#home > \*, \.sheet-body > \*, \.sheet-head h2,[\s\S]*?will-change: opacity/.test(css));
});
check('a passive layout shift rebases the native static origin without moving the avatar',()=>{
  const {e,next}=entering(1.75);e.tick(90);
  const model=e.test.models.get('b:avatar'),before=next.profile.avatar.getBoundingClientRect();
  model.slot._box.top+=17.5;next.profile.avatar._box.top+=17.5;
  e.motion.paint(next.node);
  const after=next.profile.avatar.getBoundingClientRect();
  for(const key of ['left','top','width','height'])assert(Math.abs(before[key]-after[key])<.001);
  assert(Math.abs(model.base.y-model.goal.y)<.001);e.tick(600);clean(e);
});
check('shared avatars stay above later surfaces without changing absolute page positioning',()=>{
  const e=setup(),old=e.surface('home','a');e.mount(old.node);e.motion.begin(old.node,1,'b');
  const next=e.surface('detail','b');next.node._css.position='absolute';next.profile.root._css['will-change']='opacity';e.mount(next.node);e.motion.paint(next.node);
  assert.equal(next.node.style.position,'');assert.equal(next.node.style.zIndex,'');
  assert.equal(next.profile.root.style.zIndex,'7');
  e.tick(500);assert.equal(next.node.style.zIndex,'');assert.equal(next.profile.root.style.zIndex,'');clean(e);
});
check('avatar glyph size matches the source and destination without a font swap',()=>{
  const {e,old,next}=entering(),model=e.test.models.get('b:avatar'),avatar=next.profile.avatar;
  const sourceFont=parseFloat(computed(old.row.avatar).fontSize),destinationFont=parseFloat(computed(avatar).fontSize);
  const initialScale=avatar.getBoundingClientRect().width/model.goal.w;
  assert.equal(destinationFont*initialScale,sourceFont);assert.equal(avatar.style.fontSize,'');
  e.tick(300);assert.equal(parseFloat(computed(avatar).fontSize),destinationFont);assert.equal(avatar.style.fontSize,'');clean(e);
  const css=fs.readFileSync(path.join(root,'src/ui/common.css'),'utf8');
  assert(/\.row \.avatar\s*\{[^}]*font-size: calc\(var\(--font-emphasis\) \* \.85\)/.test(css));
});
check('mixed rapid navigation stays finite within the panel and releases all work',()=>{
  const e=setup();let current=e.surface('home','a'),seed=918273;e.mount(current.node);
  const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296};
  for(let i=0;i<400;i++){
    e.motion.begin(current.node,i%2?-1:1,'b');
    const kind=['home','detail','confirm','usage'][Math.floor(random()*4)];current=e.surface(kind,kind==='home'?'a':'b');
    if(kind==='confirm'){current.profile.root.className='confirm-account';current.profile.root.setAttribute('data-email','b');current.profile.avatar._box=e.pixel(35,244,40,40);}
    e.mount(current.node);e.motion.paint(current.node);
    const steps=1+Math.floor(random()*10);for(let j=0;j<steps;j++){
      e.tick(8+random()*12);
      for(const model of e.test.models.values()){
        for(const value of [...Object.values(model.pose),...Object.values(model.velocity),...Object.values(model.acceleration)])assert(Number.isFinite(value));
        assert(model.pose.w>0&&model.pose.h>0);assert(model.pose.x>0&&model.pose.x<327);assert(model.pose.y>0&&model.pose.y<458);
      }
    }
    if(i%3===0)e.motion.paint(current.node);clean(e);
  }
  e.tick(1200);assert.equal(e.test.scene,null);assert.equal(e.test.bindings.size,0);assert.equal(e.test.models.size,0);
  assert.equal(rafs.size,0);assert.equal(animations.size,0);assert.equal(e.app.querySelectorAll('*').filter(n=>n.__nxMotionPlaceholder).length,0);
});
check('production embeds the version and excludes demo controls and accounts',()=>{assert(html.includes('"version": "1.0.2"'));for(const s of['data-preview-density','data-preview-motion','layout-preview-tools','@example.com'])assert(!html.includes(s));assert.equal(html.split('window.NXMotion =').length-1,1);const app=fs.readFileSync(path.join(root,'src/ui/app.js'),'utf8');assert(app.includes('window.nxHidden=()=>{window.NXMotion?.stop();'));assert(app.includes('closeSheet(false)'));assert(app.includes('restoreScroll(sheet,saved.scroll);restoreFocus(sheet,saved.focus)'));assert(app.includes('patchHTML(sheet,markup,{preserveFields:preserve})'));assert(!app.includes('sheet.innerHTML=markup'))});
// Real view functions are exercised with synthetic data, without mounting a browser.
const viewCtx={window:{NX_BRAND_MARK:'<svg viewBox="0 0 32 32"></svg>'}};vm.createContext(viewCtx);
for(const file of ['components.js','usage.js','views/usage.js','views/accounts.js'])vm.runInContext(fs.readFileSync(path.join(root,'src/ui',file),'utf8'),viewCtx);
const C=viewCtx.window.NXComponents,M=viewCtx.window.NXMath;
const appSource=fs.readFileSync(path.join(root,'src/ui/app.js'),'utf8');
const accountSection=appSource.slice(appSource.indexOf('  function failure(a)'),appSource.indexOf('  function header()'));
Object.assign(viewCtx,{esc:C.esc,icon:C.icon,tool:C.tool,accountIdentity:C.accountIdentity,displayWindows:C.displayWindows,remaining:C.remaining,disabled:()=>'',now:()=>1900000000,dateTime:()=>'',reset:()=>'',});
vm.runInContext(accountSection+'\nwindow.testAccountCard=accountCard;',viewCtx);
const live={email:'fixture@example.test',alias:'测试账号',plan:'plus',ok:true,windows:[{label:'5h',duration_mins:300,used:17,resets_at:1900003600},{label:'周',duration_mins:10080,used:29,resets_at:1900300000}]};
const base={...C,math:M,esc:C.esc,name:C.accountName,plan:C.planLabel,tool:C.tool,disabled:()=>'',short:M.compactText,accountCard:viewCtx.window.testAccountCard,metricsRow:items=>'<div class="metrics-row">'+items.map(([k,v])=>`<div class="metric"><small>${k}</small><strong class="mono">${v}</strong></div>`).join('')+'</div>',scopeUsage:()=>null,data:{accounts:[live],current:live.email},ui:{scope:live.email,days:30,history:[]},duration:w=>w.duration_mins,reset:()=>'',quotaValue:()=>0,resetValue:()=>0};
check('compact formatting retains exact totals and one decimal',()=>{assert.equal(M.compactText('25149299'),'2514.9万');assert.equal(M.compactText('5341840'),'534.2万');assert.equal(M.compactText('100005000'),'1.0亿');assert.equal(M.compactText('9999'),'9999');assert.equal(M.compactText(null),'—');assert.equal(M.exact('25149299'),'25,149,299');assert.equal(M.compactText('10000000000000000000000000000000'),'100000000000000000000000.0亿')});
check('personal usage reuses the real account card and refresh action',()=>{const text=viewCtx.window.NXViews.usage(base),card=viewCtx.window.testAccountCard(live,true,'正在使用');assert(text.startsWith(card.replace('data-action="refresh-one"','data-action="usage-refresh"').replace('aria-label="刷新此账号额度"','aria-label="刷新个人用量"')));assert(text.includes('data-email="fixture@example.test"'));assert(!text.includes('data-action="refresh-one"'));assert(text.includes('data-motion-identity="fixture@example.test"'));assert(text.includes('usage-filter'));assert(text.includes('usage-account-details'))});
check('overview uses the shared brand and a single scrolling account list',()=>{const text=viewCtx.window.NXViews.usage({...base,ui:{...base.ui,scope:'all'}});assert(text.includes(C.brandMark('usage-brand')));assert(text.includes('data-motion-identity="all"'));assert(text.includes('分账号用量'));assert(!text.includes('已计入'));assert.equal((text.match(/usage-filter/g)||[]).length,1);assert(!text.includes('usage-account-details'));const css=fs.readFileSync(path.join(root,'src/ui/common.css'),'utf8');assert(/\.all-usage \.account-usage-list\s*\{[^}]*overflow: visible;/.test(css));assert(/\.sheet-body\.all-usage\s*\{[^}]*overflow-y: auto;/.test(css))});
check('usage return respects the overview history and other entry routes',()=>{const withHistory=viewCtx.window.NXViews.usage({...base,ui:{...base.ui,history:[{page:'usage',scope:'all'}]}});assert(withHistory.includes('返回总览'));const fromDetail=viewCtx.window.NXViews.usage({...base,ui:{...base.ui,history:[{page:'detail',scope:'all'}]}});assert(fromDetail.includes('全部账号'));assert(!fromDetail.includes('返回总览'));assert(appSource.includes("if(ui.page==='usage'&&ui.scope!=='all'&&previous?.page==='usage'&&previous.scope==='all')back();"))});
check('missing account data renders a safe identity instead of throwing',()=>{const text=viewCtx.window.NXViews.usage({...base,data:{accounts:[],current:null}});assert(text.includes('current-card'));assert(text.includes('未选择账号'));assert(!text.includes('data-action="usage-refresh"'))});
check('archived usage never offers a live refresh control',()=>{for(const ok of[true,false]){const archived={...live,archived:true,ok,windows:ok?live.windows:[]};const text=viewCtx.window.NXViews.usage({...base,data:{accounts:[],current:null},ui:{...base.ui,usage:{rows:[archived]}}});assert(text.includes('已归档'));assert(!text.includes('data-action="usage-refresh"'));assert(!text.includes('data-action="refresh-one"'));assert(!text.includes('data-action="reauth"'))}});
check('quota overview keeps known windows in explicit columns',()=>{const text=viewCtx.window.NXViews.accounts({...base,ui:{quotaScope:'relay',quotaMetric:'quota'}});assert(text.includes('data-window-minutes="300"'));assert(text.includes('data-window-minutes="10080"'));assert(text.includes('data-action="detail"'));const weekly={...live,windows:[live.windows[1]]};const single=viewCtx.window.NXViews.accounts({...base,data:{accounts:[weekly]},ui:{quotaScope:'week',quotaMetric:'quota'}});assert(single.includes('data-window-minutes="10080"'));assert(!single.includes('data-window-minutes="300"'))});
check('compact personal usage fits the product geometry on paper',()=>{const width=327,height=458,header=50,top=3,bottom=6,card=112,pills=32,summary=148,stats=52,back=30,gaps=4*6;assert(width>=2*14+299);assert(card+pills+summary+stats+back+gaps+top+bottom<=height-header);const css=fs.readFileSync(path.join(root,'src/ui/common.css'),'utf8'),tokens=fs.readFileSync(path.join(root,'src/ui/tokens.css'),'utf8');assert(tokens.includes('--sheet-header-height: 50px; --content-top: 3px;'));assert(!css.includes('data-preview-'));assert(css.includes('width:max-content;max-width:100%;padding:0 10px'));assert(/\.sheet-body\.personal-usage\s*\{[^}]*display: grid;/.test(css))});
console.log(checks+' UI/motion checks passed');
