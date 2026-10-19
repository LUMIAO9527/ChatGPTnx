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
  get classList(){return {contains:name=>this.className.split(/\s+/).includes(name)}}
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
  matches(selector){return selector.split(',').some(s=>{const ps=s.trim().split(/\s*>\s*|\s+/),simple=(n,p)=>{const attr=p.match(/^\[([^=]+)="([^"]+)"\]$/);return attr?n.getAttribute(attr[1])===attr[2]:p.startsWith('.')?p.slice(1).split('.').every(c=>n.className.split(/\s+/).includes(c)):p.startsWith('#')?n.id===p.slice(1):n.tagName.toLowerCase()===p.toLowerCase();};if(!simple(this,ps.pop()))return false;let n=this.parentNode;while(ps.length){const p=ps.pop();while(n&&!simple(n,p))n=n.parentNode;if(!n)return false;n=n.parentNode}return true})}
  querySelectorAll(selector){const result=[];for(const c of this.children){if(selector==='*'||c.matches(selector))result.push(c);result.push(...c.querySelectorAll(selector))}return result}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null}
  addEventListener(name,fn){if(!this.events.has(name))this.events.set(name,[]);this.events.get(name).push(fn)}
  emit(name,event={}){for(const fn of this.events.get(name)||[])fn(event)}
  getBoundingClientRect(){layoutReads++;let{left,top,width,height}=this._box;const scale=this._scale||1;if(this.style.position==='fixed'){let app=this;while(app&&app.id!=='app')app=app.parentNode;if(this.style.left!=='auto')left=(app?app._box.left:0)+parseFloat(this.style.left)*scale;if(this.style.top!=='auto')top=(app?app._box.top:0)+parseFloat(this.style.top)*scale;width=parseFloat(this.style.width)*scale;height=parseFloat(this.style.height)*scale}const m=this.style.transform.match(/translate\(([-.\d]+)px,([-.\d]+)px\)\s*scale\(([-.\d]+),([-.\d]+)\)/);if(m){left+=Number(m[1])*scale;top+=Number(m[2])*scale;width*=Number(m[3]);height*=Number(m[4])}else{const move=this.style.transform.match(/^translate\(([-.\d]+)px,([-.\d]+)px\)$/);if(move){left+=Number(move[1])*scale;top+=Number(move[2])*scale}}return{left,top,width,height,right:left+width,bottom:top+height}}
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
check('unrelated navigation moves the body as one group without per-section staggering',()=>{
  const e=setup(),old=e.surface('detail','c');e.mount(old.node);e.motion.begin(old.node,1,'b');
  const next=e.surface('detail','b'),second=e.el('section','second',14,378,299,25),offscreen=e.el('section','offscreen',14,500,299,25),foot=e.el('footer','sheet-foot',14,426,299,32);
  next.body.append(second,offscreen);next.node.append(foot);e.mount(next.node);e.motion.paint(next.node);
  const effect=next.body.animateCalls[0];assert.equal(effect.options.duration,240);assert.equal(effect.options.delay,0);assert.equal(effect.frames[0].transform,'translateY(4px)');
  assert.equal(next.content.animateCalls.length,0);assert.equal(second.animateCalls.length,0);assert.equal(offscreen.animateCalls.length,0);assert.equal(foot.animateCalls[0].options.delay,0);
  e.tick(245);assert.equal(e.test.page,null);assert.equal(animations.size,0);assert.equal(rafs.size,0);clean(e);
});
check('retargeted local curves preserve position velocity and acceleration',()=>{
  const e=setup(),curve=e.motion.curve;
  for(const [from,speed,acceleration,to] of [[0,0,0,180],[92,220,-1000,0],[1.4,-2,6,3]]){
    assert(curve(from,speed,acceleration,to,0,.3).every((value,i)=>Math.abs(value-[from,speed,acceleration][i])<1e-8));
    assert.deepEqual(Array.from(curve(from,speed,acceleration,to,.3,.3)),[to,0,0]);
    const at=curve(from,speed,acceleration,to,.08,.3),next=curve(...at,from,0,.3);
    assert(next.every((value,i)=>Math.abs(value-at[i])<1e-8));
    const dt=.00001,before=curve(...at,from,dt,.3);
    assert(Math.abs((before[0]-at[0])/dt-at[1])<.3);
  }
});
check('unrelated return uses one smaller body offset and resumes after data rebuild',()=>{
  const e=setup(),old=e.surface('detail','c');e.mount(old.node);e.motion.begin(old.node,-1,'b');
  const next=e.surface('detail','b');e.mount(next.node);e.motion.paint(next.node);assert.equal(next.body.animateCalls.at(-1).frames[0].transform,'translateY(-3px)');e.tick(30);
  const rebuilt=e.surface('detail','b');e.mount(rebuilt.node);e.motion.paint(rebuilt.node);assert.equal(rebuilt.body.animateCalls.at(-1).currentTime,30);
  e.tick(260);assert.equal(e.test.page,null);assert.equal(animations.size,0);clean(e);
});
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
check('production embeds the version and excludes demo controls and accounts',()=>{const version=fs.readFileSync(path.join(root,'src/nx/version.py'),'utf8').match(/APP_VERSION = "([^"]+)"/)[1];assert(html.includes('"version": '+JSON.stringify(version)));for(const s of['data-preview-density','data-preview-motion','layout-preview-tools','@example.com'])assert(!html.includes(s));assert.equal(html.split('window.NXMotion =').length-1,1);const app=fs.readFileSync(path.join(root,'src/ui/app.js'),'utf8');assert(app.includes('window.nxHidden=()=>{window.NXMotion?.stop();'));assert(app.includes('closeSheet(false)'));assert(app.includes('restoreScroll(sheet,saved.scroll);restoreFocus(sheet,saved.focus)'));assert(app.includes('patchHTML(sheet,markup,{preserveFields:preserve})'));assert(!app.includes('sheet.innerHTML=markup'))});
// A navigation chooses one spatial anchor. Other content fades as a group.
function primaryFixture(e,surface,action,box,footer=false){
  const parent=footer?e.el('footer','sheet-foot',14,394,299,64):surface.body;
  if(footer){surface.body._box.height=344;surface.node.append(parent);}
  const button=e.el('button','btn primary',...box,{'border-radius':'12px','font-size':'12px'});
  button.setAttribute('data-action',action);button.textContent=action;
  const copy=e.el('span','control-content',box[0]+12,box[1]+10,Math.max(30,box[2]-24),18);copy.textContent=action;
  button.append(copy);parent.append(button);return {button,copy,parent};
}
check('different primary actions morph across home body and confirmation footer',()=>{
  for(const scale of [1,1.25,1.75,2]){
    const e=setup(scale),old=e.surface('home','a'),from=primaryFixture(e,old,'relay',[14,173,299,62]);e.mount(old.node);e.motion.begin(old.node,1,'b');
    const next=e.surface('confirm','b'),to=primaryFixture(e,next,'execute-switch',[170,404,143,44],true);e.mount(next.node);e.motion.paint(next.node);
    const model=e.test.models.get('primary-action');assert(model);assert.equal(e.test.models.size,1);assert.equal(model.live,to.button);
    assert.equal(to.parent.animateCalls.length,0);assert.equal(to.copy.animateCalls.length,1);assert.equal(to.button.style.opacity,'');
    assert(!next.content.animateCalls[0].frames[0].transform);
    for(const step of [0,35,55,60,80,69.9]){
      e.tick(step);const r=to.button.getBoundingClientRect();
      assert(Math.abs((r.left-100)/scale-(model.pose.x-model.pose.w/2))<.001);
      assert(Math.abs((r.top-100)/scale-(model.pose.y-model.pose.h/2))<.001);
      assert(Math.abs(r.width/scale-model.pose.w)<.001);assert(!to.button.style.transform.includes('scale'));
    }
    e.tick(1);assert.equal(to.button.style.position,'');assert.equal(to.button.style.width,'');e.tick(1000);clean(e);
  }
});
check('rapid primary action reversal preserves position velocity and acceleration',()=>{
  const e=setup(),old=e.surface('home','a');primaryFixture(e,old,'relay',[14,173,299,62]);e.mount(old.node);e.motion.begin(old.node,1,'b');
  const next=e.surface('confirm','b');primaryFixture(e,next,'execute-switch',[170,404,143,44],true);e.mount(next.node);e.motion.paint(next.node);e.tick(90);
  const model=e.test.models.get('primary-action'),pose={...model.pose},velocity={...model.velocity},acceleration={...model.acceleration};
  e.motion.begin(next.node,-1);const back=e.surface('home','a');primaryFixture(e,back,'relay',[14,173,299,62]);e.mount(back.node);e.motion.paint(back.node);
  assert.equal(e.test.models.get('primary-action'),model);assert.deepEqual({...model.pose},pose);assert.deepEqual({...model.velocity},velocity);assert.deepEqual({...model.acceleration},acceleration);
  e.tick(1200);assert.equal(e.test.bindings.size,0);assert.equal(e.test.models.size,0);assert.equal(animations.size,0);clean(e);
});
check('a passive refresh keeps the primary clock and never starts an avatar too',()=>{
  const e=setup(),old=e.surface('home','a');primaryFixture(e,old,'relay',[14,173,299,62]);e.mount(old.node);e.motion.begin(old.node,1,'b');
  const next=e.surface('detail','b'),to=primaryFixture(e,next,'pick',[14,174,174,42]);e.mount(next.node);e.motion.paint(next.node);
  const model=e.test.models.get('primary-action'),slot=model.slot,start=model.start;
  for(let i=0;i<20;i++){e.tick(5);e.motion.paint(next.node);assert.equal(e.test.models.size,1);assert.equal(model.start,start);assert.equal(model.slot,slot);}
  e.tick(1200);assert.equal(to.button.style.transform,'');assert.equal(e.test.bindings.size,0);clean(e);
});
check('secondary primary controls fade while only the first primary surface moves',()=>{
  const e=setup(),old=e.surface('home','a');primaryFixture(e,old,'relay',[14,173,299,62]);e.mount(old.node);e.motion.begin(old.node,1);
  const next=e.surface('detail','b');primaryFixture(e,next,'pick',[14,174,174,42]);const secondary=primaryFixture(e,next,'extra',[194,174,119,42]);e.mount(next.node);e.motion.paint(next.node);
  assert.equal(e.test.models.size,1);assert.equal(secondary.button.style.position,'');assert.equal(secondary.button.animateCalls.length,1);assert(!secondary.button.animateCalls[0].frames[0].transform);
  e.motion.stop();clean(e);
});
check('primary slots retain the layout flex basis across horizontal and vertical parents',()=>{
  for(const [footer,flex,box] of [[false,'0 0 62px',[14,173,299,62]],[true,'1 1 0%',[170,404,143,44]]]){
    const e=setup(),old=e.surface('detail','b');primaryFixture(e,old,'pick',[14,174,174,42]);e.mount(old.node);e.motion.begin(old.node,1);
    const next=e.surface(footer?'confirm':'home','b'),to=primaryFixture(e,next,footer?'execute-switch':'relay',box,footer);to.button._css.flex=flex;
    e.mount(next.node);e.motion.paint(next.node);const model=e.test.models.get('primary-action');
    assert.equal(model.slot.style.flex,flex);assert.equal(model.slot.style.height,box[3]+'px');e.tick(400);clean(e);
  }
});
check('a passive primary paint never mistakes the live radius for a new goal',()=>{
  const e=setup(),old=e.surface('home','a'),from=primaryFixture(e,old,'relay',[14,173,299,62]);from.button._css['border-radius']='26px';e.mount(old.node);e.motion.begin(old.node,1);
  const next=e.surface('confirm','b');primaryFixture(e,next,'execute-switch',[170,404,143,44],true);e.mount(next.node);e.motion.paint(next.node);
  const model=e.test.models.get('primary-action');
  for(let i=0;i<20;i++){e.tick(10);e.motion.paint(next.node);assert.equal(model.goal.r,12);assert.equal(model.start,0);}
  e.tick(100);assert.equal(model.live.style.position,'');assert.equal(e.test.models.size,0);clean(e);
});
check('a floating action retains the border-box contribution beside a flexible return button',()=>{
  const e=setup(),old=e.surface('home','a');primaryFixture(e,old,'relay',[14,173,299,62]);e.mount(old.node);e.motion.begin(old.node,1);
  const next=e.surface('confirm','b'),to=primaryFixture(e,next,'execute-switch',[170,404,143,44],true);
  Object.assign(to.button._css,{flex:'1 1 0%', 'box-sizing':'border-box','padding-left':'11px','padding-right':'11px','border-left-width':'1px','border-right-width':'1px','min-width':'44px','min-height':'44px'});
  e.mount(next.node);e.motion.paint(next.node);const slot=e.test.models.get('primary-action').slot;
  const outerBasis=node=>parseFloat(node.style.paddingLeft)+parseFloat(node.style.paddingRight)+parseFloat(node.style.borderLeftWidth)+parseFloat(node.style.borderRightWidth);
  assert.equal(outerBasis(slot),24);assert.equal(slot.style.flex,'1 1 0%');assert.equal(slot.style.boxSizing,'border-box');assert.equal(slot.style.minWidth,'44px');
  e.tick(400);clean(e);
});
check('a footer action is not dropped while passing the body scroll boundary during refresh',()=>{
  const e=setup(),old=e.surface('confirm','b');primaryFixture(e,old,'execute-switch',[170,404,143,44],true);e.mount(old.node);e.motion.begin(old.node,-1,'b');
  const next=e.surface('detail','b');next.body._css['overflow-y']='auto';next.body._box.height=344;const target=primaryFixture(e,next,'pick',[14,174,174,42]);e.mount(next.node);e.motion.paint(next.node);
  const m=e.test.models.get('primary-action'),start=m.start;e.tick(40);const pose={...m.pose},velocity={...m.velocity};e.motion.paint(next.node);
  assert(e.test.models.get('primary-action')===m,'The travelling footer action must survive a passive paint');assert.equal(m.live,target.button);assert.equal(m.start,start);assert.deepEqual({...m.pose},pose);assert.deepEqual({...m.velocity},velocity);
  assert.equal(next.body.style.transform,'');e.tick(400);clean(e);
});
check('late primary controls retire an existing entrance on their ancestor path',()=>{
  const e=setup(),old=e.surface('home','a');primaryFixture(e,old,'relay',[14,173,299,62]);e.mount(old.node);e.motion.begin(old.node,1);
  const next=e.surface('detail','c'),actions=e.el('section','detail-actions',14,174,299,42);next.body.append(actions);e.mount(next.node);e.motion.paint(next.node);
  const entrance=next.body.animateCalls[0];assert(entrance.frames[0].transform);e.tick(60);
  const to=primaryFixture(e,next,'pick',[14,174,174,42]);actions.append(to.button);e.motion.paint(next.node);
  assert(entrance.cancelled);assert.equal(e.test.models.size,1);assert.equal(e.test.models.get('primary-action').live,to.button);e.tick(400);clean(e);
});
// Real view functions are exercised with synthetic data, without mounting a browser.
function contextFixture(surface,height){surface.profile.root.setAttribute('data-motion-surface','account-context');surface.profile.root._box.height=height;surface.profile.root._css['border-radius']='16px';surface.profile.root._css['background-color']='rgb(245, 245, 245)';}
check('account-context cards morph one background while their real content remains unscaled',()=>{
  const e=setup(),old=e.surface('home','a');contextFixture(old,112);e.mount(old.node);e.motion.begin(old.node,1);
  const next=e.surface('usage','all');contextFixture(next,72);e.mount(next.node);e.motion.paint(next.node);
  const model=e.test.models.get('context-surface');assert(model);assert.equal(model.kind,'surface');assert.equal(e.test.models.size,1);assert.equal(model.target,next.profile.root);
  assert.equal(next.profile.avatar.style.transform,'');assert.equal(next.profile.name.style.transform,'');assert.equal(next.profile.root.style.backgroundColor,'transparent');
  e.tick(120);e.motion.paint(next.node);assert.equal(model.start,0);assert.equal(model.goal.h,72);assert.equal(model.goal.r,16);
  e.tick(180);assert.equal(next.profile.root.style.backgroundColor,'');assert.equal(next.profile.root.querySelectorAll('.motion-surface').length,0);assert.equal(e.test.models.size,0);clean(e);
});
check('account-context background reversals retain the same continuous trajectory',()=>{
  const e=setup(),old=e.surface('home','a');contextFixture(old,112);e.mount(old.node);e.motion.begin(old.node,1);
  const next=e.surface('usage','all');contextFixture(next,72);e.mount(next.node);e.motion.paint(next.node);e.tick(80);
  const model=e.test.models.get('context-surface'),pose={...model.pose},velocity={...model.velocity},acceleration={...model.acceleration};
  e.motion.begin(next.node,-1);const back=e.surface('home','a');contextFixture(back,112);e.mount(back.node);e.motion.paint(back.node);
  assert.equal(e.test.models.get('context-surface'),model);assert.deepEqual({...model.pose},pose);assert.deepEqual({...model.velocity},velocity);assert.deepEqual({...model.acceleration},acceleration);
  e.tick(1000);assert.equal(e.test.bindings.size,0);assert.equal(e.app.querySelectorAll('.motion-surface').length,0);clean(e);
});
check('a stationary shared card yields the one moving role to the main action',()=>{
  const e=setup(),old=e.surface('home','a');contextFixture(old,112);primaryFixture(e,old,'relay',[14,173,299,62]);e.mount(old.node);e.motion.begin(old.node,1,'a');
  const next=e.surface('detail','a');contextFixture(next,112);primaryFixture(e,next,'current-status',[14,174,299,42]);e.mount(next.node);e.motion.paint(next.node);
  assert.equal(e.test.models.size,1);assert(e.test.models.has('primary-action'));assert(!e.test.models.has('context-surface'));e.tick(400);clean(e);
});
check('account entry keeps the black action and selected identity on continuous independent tracks',()=>{
  const e=setup(),old=e.surface('home','a');contextFixture(old,112);primaryFixture(e,old,'relay',[14,173,299,62]);e.mount(old.node);
  e.motion.begin(old.node,1,'b',{from:'home',to:'detail'});
  const next=e.surface('detail','b');contextFixture(next,112);next.profile.root._box.top+=25;primaryFixture(e,next,'pick',[14,174,174,42]);e.mount(next.node);e.motion.paint(next.node);
  assert.equal(e.test.models.has('context-surface'),false);
  assert(e.test.models.has('primary-action'));assert(e.test.models.has('b:avatar'));assert(e.test.models.has('b:label'));
  assert.equal(next.profile.name.style.opacity,'');assert(!next.profile.name.style.transform.includes('scale'));
  e.tick(65);const poses=new Map([...e.test.models].map(([key,m])=>[key,{model:m,pose:{...m.pose},velocity:{...m.velocity},acceleration:{...m.acceleration},start:m.start}]));
  e.motion.paint(next.node);for(const [key,saved]of poses)assert.equal(e.test.models.get(key).start,saved.start);
  e.motion.begin(next.node,-1,null,{from:'detail',to:'home'});const back=e.surface('home','a');contextFixture(back,112);primaryFixture(e,back,'relay',[14,173,299,62]);e.mount(back.node);e.motion.paint(back.node);
  for(const [key,saved]of poses){const m=e.test.models.get(key);assert.equal(m,saved.model);for(const part of ['pose','velocity','acceleration'])for(const property of Object.keys(saved[part]))assert(Math.abs(m[part][property]-saved[part][property])<.00001,key+' '+part+' continuity');}
  e.tick(1200);assert.equal(e.test.bindings.size,0);clean(e);
});
check('settings entry follows the action trajectory while real sections reveal without a page slide',()=>{
  const e=setup(),nav=(surface,home)=>{const button=e.el('button','control tool',home?279:14,12,32,32);button.setAttribute('data-action',home?'settings':'back');surface.head.append(button);return button;};
  const old=e.surface('home','a');nav(old,true);e.mount(old.node);e.motion.begin(old.node,1,null,{from:'home',to:'settings'});
  let current=e.surface('settings','a');nav(current,false);const section=e.el('section','settings-section',14,60,299,160);current.body.append(section);e.mount(current.node);e.motion.paint(current.node);
  assert(e.test.models.has('navigation-entry'));assert.equal(section.animateCalls.length,0);assert.equal(current.body.animateCalls.length,0);assert.equal(section.style.opacity,'');assert(section.style.clipPath.startsWith('inset('));
  for(let i=0;i<20;i++){
    e.tick(12);const m=e.test.models.get('navigation-entry'),saved={pose:{...m.pose},velocity:{...m.velocity},acceleration:{...m.acceleration}};
    const from=i%2?'home':'settings',to=i%2?'settings':'home';e.motion.begin(current.node,i%2?1:-1,null,{from,to});
    current=e.surface(to,'a');nav(current,to==='home');if(to==='settings')current.body.append(e.el('section','settings-section',14,60,299,160));e.mount(current.node);e.motion.paint(current.node);
    assert.equal(e.test.models.get('navigation-entry'),m);assert.deepEqual({...m.pose},saved.pose);assert.deepEqual({...m.velocity},saved.velocity);assert.deepEqual({...m.acceleration},saved.acceleration);
    assert.equal(current.body.animateCalls.length,0);
  }
  e.motion.setEnabled(false);assert.equal(e.test.bindings.size,0);assert.equal(e.test.models.size,0);assert.equal(e.app.querySelectorAll('*').filter(n=>n.__nxMotionRole).length,0);clean(e);
});
check('home usage reveals real sections alongside its context card on entry and return',()=>{
  const e=setup(),nav=(surface,home)=>{const button=e.el('button','control tool',home?252:14,12,28,28);button.setAttribute('data-action',home?'usage-all':'back');surface.head.append(button);};
  const old=e.surface('home','a');contextFixture(old,112);nav(old,true);e.mount(old.node);e.motion.begin(old.node,1,null,{from:'home',to:'usage'});
  const next=e.surface('usage','all');next.node.dataset.page='usage';contextFixture(next,72);nav(next,false);e.mount(next.node);e.motion.paint(next.node);
  assert(e.test.models.has('context-surface'));assert(e.test.models.has('navigation-entry'));assert.equal(next.content.__nxMotionRole,'reveal');assert.equal(next.content.animateCalls.length,0);assert.equal(next.body.animateCalls.length,0);
  e.tick(100);assert.equal(Number(computed(next.content).opacity),1);assert(next.content.style.clipPath.startsWith('inset('));assert.equal(next.profile.root.style.transform,'');
  const reveal=[...e.test.models.values()].find(model=>model.live===next.content),clock=reveal.start,pose={...reveal.pose};e.motion.paint(next.node);
  assert.equal([...e.test.models.values()].find(model=>model.live===next.content),reveal);assert.equal(reveal.start,clock);assert.deepEqual({...reveal.pose},pose);e.tick(300);
  e.motion.begin(next.node,-1,null,{from:'usage',to:'home'});const back=e.surface('home','a');contextFixture(back,112);nav(back,true);e.mount(back.node);e.motion.paint(back.node);
  assert(e.test.models.has('context-surface'));assert(e.test.models.has('navigation-entry'));assert.equal(back.content.__nxMotionRole,'reveal');assert.equal(back.content.animateCalls.length,0);
  e.tick(100);assert.equal(Number(computed(back.content).opacity),1);assert(back.content.style.clipPath.startsWith('inset('));e.tick(300);clean(e);
});
check('returning to a body entry never gives its moving control the content reveal role',()=>{
  const e=setup(),old=e.surface('quota-overview','a');old.profile.root.remove();const back=e.el('button','control tool',14,12,28,28);back.setAttribute('data-action','back');old.head.append(back);e.mount(old.node);
  e.motion.begin(old.node,-1,null,{from:'quota-overview',to:'home'});const next=e.surface('home','a'),entry=e.el('button','section-link',14,240,299,38);entry.setAttribute('data-action','quota-overview');next.row.root.parentNode.insertBefore(entry,next.row.root);e.mount(next.node);e.motion.paint(next.node);
  assert.equal(entry.__nxMotionRole,'entry');assert.equal(e.test.models.get('navigation-entry').live,entry);assert(![...e.test.models.values()].some(model=>model.kind==='reveal'&&model.live===entry));e.tick(400);clean(e);
});
check('list-to-detail identity includes its real text even when no black source action exists',()=>{
  const e=setup(),old=e.surface('quota-overview','a',true);old.profile.root.remove();old.row.root.className='quota-overview-row';e.mount(old.node);
  e.motion.begin(old.node,1,'b',{from:'quota-overview',to:'detail'});const next=e.surface('detail','b');e.mount(next.node);e.motion.paint(next.node);
  assert(e.test.models.has('b:avatar'));assert(e.test.models.has('b:label'));assert(!e.test.models.has('primary-action'));
  assert.equal(next.profile.name.style.fontSize,'');assert.equal(next.profile.name.style.opacity,'');e.tick(400);clean(e);
});
check('a media zoom reverses the actual image without creating a second copy',()=>{
  const e=setup(),old=e.surface('purchase','a'),button=e.el('button','support-code',210,325,86,86),small=e.el('img','',218,333,70,70);button.append(small);old.body.append(button);e.mount(old.node);
  e.motion.begin(old.node,1,null,{from:'purchase',to:'support-qr'});const next=e.surface('support-qr','a'),large=e.el('img','support-full-code',46,105,235,235);next.body.append(large);e.mount(next.node);e.motion.paint(next.node);e.tick(75);
  const m=e.test.models.get('support-media'),pose={...m.pose},velocity={...m.velocity};assert.equal(m.live,large);
  e.motion.begin(next.node,-1,null,{from:'support-qr',to:'purchase'});const back=e.surface('purchase','a'),target=e.el('button','support-code',210,325,86,86),image=e.el('img','',218,333,70,70);target.append(image);back.body.append(target);e.mount(back.node);e.motion.paint(back.node);
  assert.equal(e.test.models.get('support-media'),m);assert.equal(m.live,image);assert.deepEqual({...m.pose},pose);assert.deepEqual({...m.velocity},velocity);e.tick(400);clean(e);
});
check('usage scope changes translate the shared report without fading or scaling it',()=>{
  const e=setup(),old=e.surface('usage','all',true);old.node.dataset.page='usage';contextFixture(old,72);
  const original=e.el('section','usage-summary',14,180,299,148);old.body.append(original);e.mount(old.node);e.motion.begin(old.node,1,'b');
  const next=e.surface('usage','b');next.node.dataset.page='usage';contextFixture(next,112);
  const summary=e.el('section','usage-summary',14,222,299,148);next.body.append(summary);e.mount(next.node);e.motion.paint(next.node);
  const model=e.test.models.get('report:.usage-summary');assert(model);assert.equal(model.pose.y,254);assert.equal(model.goal.y,296);
  assert.equal(next.body.animateCalls.length,0);assert.equal(summary.animateCalls.length,0);assert(!summary.style.transform.includes('scale'));
  e.tick(90);const pose={...model.pose},velocity={...model.velocity},acceleration={...model.acceleration};
  e.motion.begin(next.node,-1,'all');const back=e.surface('usage','all',true);back.node.dataset.page='usage';contextFixture(back,72);
  const returned=e.el('section','usage-summary',14,180,299,148);back.body.append(returned);e.mount(back.node);e.motion.paint(back.node);
  assert.equal(e.test.models.get('report:.usage-summary'),model);assert.deepEqual({...model.pose},pose);assert.deepEqual({...model.velocity},velocity);assert.deepEqual({...model.acceleration},acceleration);
  e.tick(320);assert.equal(returned.style.transform,'');assert.equal(back.filter.style.transform,'');assert.equal(e.test.models.size,0);assert.equal(rafs.size,0);
});
function disclosureFixture(kind='details'){
  const e=setup(),surface=e.surface('detail','b');e.mount(surface.node);
  const source=fs.readFileSync(path.join(root,'src/ui/disclosure.js'),'utf8').replace('  return {transact,afterPatch,popup,stop,isOpen:desired};','  window.__disclosureTest={models,popups};\n  return {transact,afterPatch,popup,stop,isOpen:desired};');
  vm.runInNewContext(source,{window:e.window,Element,getComputedStyle:computed,performance:{now:()=>time},requestAnimationFrame:fn=>{const id=++sequence;rafs.set(id,fn);return id},cancelAnimationFrame:id=>rafs.delete(id)});
  const node=e.el(kind,kind==='details'?'settings-disclosure':'resume-session',14,180,299,44),head=e.el(kind==='details'?'summary':'button',kind==='details'?'control-header':'',14,180,299,44),body=e.el('div',kind==='details'?'disclosure-body':'resume-tasks',14,224,299,120);
  head.setAttribute('aria-expanded','false');node.setAttribute('data-disclosure','fixture');node.open=false;node.append(head);if(kind==='details')node.append(body);surface.body.append(node);
  let contentHeight=120;
  node.getBoundingClientRect=()=>{const h=parseFloat(node.style.height)||44+((kind==='details'?node.open:body.parentNode===node)?contentHeight:0);return {...node._box,height:h,bottom:node._box.top+h};};
  const set=open=>{head.setAttribute('aria-expanded',String(open));if(kind==='details')node.open=open;else open?node.append(body):body.remove();};
  return {...e,node,head,body,disclosure:e.window.NXDisclosure,inspect:e.window.__disclosureTest,set,setHeight:h=>contentHeight=h};
}
check('all inline disclosures smoothly reveal height and retire every owned style',()=>{
  const e=disclosureFixture();e.disclosure.transact(e.app,()=>e.set(true));const model=e.inspect.models.get(e.node);assert(model);assert.equal(model.pose.height,44);assert.equal(model.goal.height,164);
  e.tick(110);assert(parseFloat(e.node.style.height)>44&&parseFloat(e.node.style.height)<164);assert.equal(Number(computed(e.body).opacity),1);
  e.tick(110);assert.equal(e.node.style.height,'');assert.equal(e.body.style.opacity,'');assert.equal(e.node.open,true);assert.equal(e.inspect.models.size,0);assert.equal(rafs.size,0);
});
check('closing retains the real body only until the collapse reaches its endpoint',()=>{
  const e=disclosureFixture('section');e.set(true);e.disclosure.transact(e.app,()=>e.set(false));assert.equal(e.body.parentNode,e.node);assert.equal(e.body.__nxMotionRetained,true);assert.equal(e.body.inert,true);
  e.tick(100);assert(parseFloat(e.node.style.height)>44&&parseFloat(e.node.style.height)<164);assert.equal(Number(computed(e.body).opacity),1);e.tick(120);assert.equal(e.body.parentNode,null);assert.equal(e.body.__nxMotionRetained,undefined);assert.equal(e.inspect.models.size,0);
});
check('closing keeps the header joined and content opaque until the body retracts',()=>{
  const e=disclosureFixture();e.head.style.borderBottomLeftRadius='16px';e.head.style.borderBottomRightRadius='16px';e.set(true);
  e.disclosure.transact(e.app,()=>e.set(false));
  for(let i=0;i<5;i++){
    e.tick(40);assert(parseFloat(e.node.style.height)>44);assert.equal(e.node.open,true);
    assert.equal(Number(computed(e.body).opacity),1);assert.equal(e.head.style.borderBottomLeftRadius,'0px');assert.equal(e.head.style.borderBottomRightRadius,'0px');
  }
  e.tick(20);assert.equal(e.node.open,false);assert.equal(e.node.style.height,'');assert.equal(e.head.style.borderBottomLeftRadius,'16px');assert.equal(e.head.style.borderBottomRightRadius,'16px');assert.equal(e.inspect.models.size,0);
});
check('a rapid disclosure reversal retains height velocity and acceleration',()=>{
  const e=disclosureFixture();e.disclosure.transact(e.app,()=>e.set(true));e.tick(70);const previous=e.inspect.models.get(e.node),pose={...previous.pose},velocity={...previous.velocity},acceleration={...previous.acceleration};
  e.disclosure.transact(e.app,()=>e.set(false));const model=e.inspect.models.get(e.node);assert.deepEqual({...model.pose},pose);assert.deepEqual({...model.velocity},velocity);assert.deepEqual({...model.acceleration},acceleration);
  e.tick(220);assert.equal(e.node.open,false);assert.equal(e.node.style.height,'');assert.equal(e.inspect.models.size,0);
});
check('async disclosure content retargets once while unchanged refresh keeps its clock',()=>{
  const e=disclosureFixture();e.disclosure.transact(e.app,()=>e.set(true));e.tick(60);const model=e.inspect.models.get(e.node),pose={...model.pose};e.setHeight(200);e.disclosure.afterPatch(e.app);assert.equal(model.goal.height,244);assert.deepEqual({...model.pose},pose);const start=model.start;
  for(let i=0;i<10;i++){e.tick(5);e.disclosure.afterPatch(e.app);assert.equal(model.start,start);}e.tick(220);assert.equal(e.node.style.height,'');assert.equal(e.inspect.models.size,0);
});
check('reduced motion and explicit stop commit the intended disclosure state',()=>{
  const e=disclosureFixture();e.disclosure.transact(e.app,()=>e.set(true));e.tick(50);e.motion.setEnabled(false);assert.equal(e.node.open,true);assert.equal(e.node.style.height,'');assert.equal(rafs.size,0);
  e.disclosure.transact(e.app,()=>e.set(false));assert.equal(e.node.open,false);assert.equal(e.inspect.models.size,0);
});
check('floating popup refresh never replays its entrance and reverses on dismissal',()=>{
  const e=disclosureFixture(),node=e.el('div','status-dock',16,400,295,40);node.hidden=true;node.innerHTML='';e.app.append(node);
  e.disclosure.popup(node,'Ready');const first=node.animateCalls[0];for(let i=0;i<10;i++){e.tick(5);e.disclosure.popup(node,'Ready');}assert.equal(node.animateCalls.length,1);assert(!first.cancelled);
  e.disclosure.popup(node,'');assert(first.cancelled);assert.equal(node.inert,true);e.tick(50);e.disclosure.popup(node,'Again');e.tick(180);assert.equal(node.hidden,false);assert.equal(node.innerHTML,'Again');assert.equal(node.__nxPopupActive,undefined);
  e.disclosure.popup(node,'');e.tick(140);assert.equal(node.hidden,true);assert.equal(node.innerHTML,'');assert.equal(e.inspect.popups.size,0);
});
const viewCtx={window:{NX_BRAND_MARK:'<svg viewBox="0 0 32 32"></svg>'}};vm.createContext(viewCtx);
for(const file of ['components.js','usage.js','views/usage.js','views/accounts.js'])vm.runInContext(fs.readFileSync(path.join(root,'src/ui',file),'utf8'),viewCtx);
const C=viewCtx.window.NXComponents,M=viewCtx.window.NXMath;
const appSource=fs.readFileSync(path.join(root,'src/ui/app.js'),'utf8');
const accountSection=appSource.slice(appSource.indexOf('  function failure(a)'),appSource.indexOf('  function header()'));
Object.assign(viewCtx,{esc:C.esc,icon:C.icon,tool:C.tool,accountIdentity:C.accountIdentity,displayWindows:C.displayWindows,remaining:C.remaining,disabled:()=>'',now:()=>1900000000,dateTime:()=>'',reset:()=>'',});
vm.runInContext(accountSection+'\nwindow.testAccountCard=accountCard;',viewCtx);
const live={email:'fixture@example.test',alias:'测试账号',plan:'plus',ok:true,windows:[{label:'5h',duration_mins:300,used:17,resets_at:1900003600},{label:'周',duration_mins:10080,used:29,resets_at:1900300000}]};
Object.assign(viewCtx,{math:M});
vm.runInContext(appSource.slice(appSource.indexOf('  function countMarkup('),appSource.indexOf('  function metric('))+'\nwindow.testCountMarkup=countMarkup;',viewCtx);
const base={...C,countMarkup:viewCtx.window.testCountMarkup,math:M,esc:C.esc,name:C.accountName,plan:C.planLabel,tool:C.tool,disabled:()=>'',short:M.compactText,accountCard:viewCtx.window.testAccountCard,metricsRow:items=>'<div class="metrics-row">'+items.map(([k,v])=>`<div class="metric"><small>${k}</small><strong class="mono">${v}</strong></div>`).join('')+'</div>',scopeUsage:()=>null,data:{accounts:[live],current:live.email},ui:{scope:live.email,days:30,history:[]},duration:w=>w.duration_mins,reset:()=>'',quotaValue:()=>0,resetValue:()=>0};
check('compact formatting retains exact totals and one decimal',()=>{assert.equal(M.compactText('25149299'),'2514.9万');assert.equal(M.compactText('5341840'),'534.2万');assert.equal(M.compactText('100005000'),'1.0亿');assert.equal(M.compactText('9999'),'9999');assert.equal(M.compactText(null),'—');assert.equal(M.exact('25149299'),'25,149,299');assert.equal(M.compactText('10000000000000000000000000000000'),'100000000000000000000000.0亿')});
check('personal usage reuses the real account card and refresh action',()=>{const text=viewCtx.window.NXViews.usage(base),card=viewCtx.window.testAccountCard(live,true,'正在使用');assert(text.startsWith(card.replace('data-action="refresh-one"','data-action="usage-refresh"').replace('aria-label="刷新此账号额度"','aria-label="刷新个人用量"')));assert(text.includes('data-email="fixture@example.test"'));assert(!text.includes('data-action="refresh-one"'));assert(text.includes('data-motion-identity="fixture@example.test"'));assert(text.includes('usage-filter'));assert(text.includes('usage-account-details'))});
check('overview uses the shared brand and a single scrolling account list',()=>{const text=viewCtx.window.NXViews.usage({...base,ui:{...base.ui,scope:'all'}});assert(text.includes(C.brandMark('usage-brand')));assert(text.includes('data-motion-identity="all"'));assert(text.includes('分账号用量'));assert(!text.includes('已计入'));assert.equal((text.match(/usage-filter/g)||[]).length,1);assert(!text.includes('usage-account-details'));const css=fs.readFileSync(path.join(root,'src/ui/common.css'),'utf8');assert(/\.all-usage \.account-usage-list\s*\{[^}]*overflow: visible;/.test(css));assert(/\.sheet-body\.all-usage\s*\{[^}]*overflow-y: auto;/.test(css))});
check('usage return respects the overview history and other entry routes',()=>{const withHistory=viewCtx.window.NXViews.usage({...base,ui:{...base.ui,history:[{page:'usage',scope:'all'}]}});assert(withHistory.includes('返回总览'));const fromDetail=viewCtx.window.NXViews.usage({...base,ui:{...base.ui,history:[{page:'detail',scope:'all'}]}});assert(fromDetail.includes('全部账号'));assert(!fromDetail.includes('返回总览'));assert(appSource.includes("if(ui.page==='usage'&&ui.scope!=='all'&&previous?.page==='usage'&&previous.scope==='all')back();"))});
check('missing account data renders a safe identity instead of throwing',()=>{const text=viewCtx.window.NXViews.usage({...base,data:{accounts:[],current:null}});assert(text.includes('current-card'));assert(text.includes('未选择账号'));assert(!text.includes('data-action="usage-refresh"'))});
check('archived usage never offers a live refresh control',()=>{for(const ok of[true,false]){const archived={...live,archived:true,ok,windows:ok?live.windows:[]};const text=viewCtx.window.NXViews.usage({...base,data:{accounts:[],current:null},ui:{...base.ui,usage:{rows:[archived]}}});assert(text.includes('已归档'));assert(!text.includes('data-action="usage-refresh"'));assert(!text.includes('data-action="refresh-one"'));assert(!text.includes('data-action="reauth"'))}});
check('quota overview keeps known windows in explicit columns',()=>{const text=viewCtx.window.NXViews.accounts({...base,ui:{quotaScope:'relay',quotaMetric:'quota'}});assert(text.includes('data-window-minutes="300"'));assert(text.includes('data-window-minutes="10080"'));assert(text.includes('data-action="detail"'));const weekly={...live,windows:[live.windows[1]]};const single=viewCtx.window.NXViews.accounts({...base,data:{accounts:[weekly]},ui:{quotaScope:'week',quotaMetric:'quota'}});assert(single.includes('data-window-minutes="10080"'));assert(!single.includes('data-window-minutes="300"'))});
console.log(checks+' UI/motion checks passed');
