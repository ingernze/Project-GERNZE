const test = require('node:test');
const assert = require('node:assert/strict');
const {Scope, Registry, clientFor, PanelHost} = require('../static/runtime.js');
const {resolveLayout,limits} = require('../static/layout.js');

test('module removal and switch release every resource even after one cleanup fails', () => {
  const errors=[], events=[]; const scope = new Scope(error=>errors.push(error.message));
  scope.own(()=>events.push('first'));
  scope.own(()=>{throw new Error('cleanup failed');});
  scope.own(()=>events.push('last'));
  scope.dispose();scope.dispose();scope.own(()=>events.push('late'));
  assert.deepEqual(events,['last','first','late']);assert.deepEqual(errors,['cleanup failed']);
});
test('duplicate or incompatible modules never replace an existing registration', () => {
  const registry=new Registry();const entry={id:'home',title:'Home',apiVersion:1,commands:[],mount:()=>{}};
  const remove=registry.register(entry);
  assert.throws(()=>registry.register(entry),/重复/);
  assert.throws(()=>registry.register({...entry,id:'later',apiVersion:2}),/不兼容/);
  assert.equal(registry.list().length,1);remove();remove();assert.equal(registry.list().length,0);
});
test('a module gets only its declared facade commands', async () => {
  const calls=[];const call=clientFor({commands:['lesson.get']},async command=>{calls.push(command);return 'ok';});
  await assert.rejects(call('shell.exec'),/没有申请/);
  assert.equal(await call('lesson.get'),'ok');assert.deepEqual(calls,['lesson.get']);
});
test('an async mount settling after navigation releases its late resource and aborts old work', async () => {
  const registry=new Registry();const element={replaceChildren(){}};const errors=[];
  let resolve, signal, released=0;
  registry.register({id:'home',title:'Home',apiVersion:1,commands:[],mount:()=>{}});
  const remove=registry.register({id:'study',title:'Study',apiVersion:1,commands:[],mount:(_el,ctx)=>{signal=ctx.signal;return new Promise(r=>resolve=r);}});
  const host=new PanelHost(registry,element,{closeDetails(){},transport(){}},error=>errors.push(error));
  host.open('study');host.open('home');assert.equal(signal.aborted,true);
  resolve(()=>released++);await Promise.resolve();assert.equal(released,1);
  host.open('study');remove();assert.equal(host.current,'home');assert.equal(signal.aborted,true);
  resolve(()=>released++);await Promise.resolve();assert.equal(released,2);
  host.dispose();assert.deepEqual(errors,[]);
});
test('small screens use floating panels without consuming the workspace track',()=>{
  const prefs={collapsed:false,mobileExpanded:false,navWidth:limits.nav,detailWidth:limits.detail,detailOpen:true};
  const narrow=resolveLayout(380,prefs);
  assert.equal(narrow.navTrack,64);assert.equal(narrow.overlay,true);assert.equal(narrow.detailTrack,0);
  const expanded=resolveLayout(380,{...prefs,mobileExpanded:true});
  assert.equal(expanded.floating,true);assert.equal(expanded.navTrack,64);
  const wide=resolveLayout(1280,prefs);
  assert.equal(wide.overlay,false);assert.equal(wide.detailTrack,344);assert.equal(wide.navTrack,256);
  assert.equal(resolveLayout(1280,{...prefs,collapsed:true}).navTrack,64);
});
