const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {JSDOM}=require('jsdom');
const {Registry,Scope}=require('../static/runtime.js');
async function setup(available=true,preview=false){
 const dom=new JSDOM('<main></main>',{runScripts:'outside-only'}),w=dom.window;
 w.eval(fs.readFileSync(path.join(__dirname,'../static/modules.js'),'utf8'));
 const registry=new Registry();w.HebaoModules.register(registry);const calls=[],notices=[],scope=new Scope();
 const ctx={registry,scope,signal:new AbortController().signal,preview,notify:s=>notices.push(s),call:async name=>{calls.push(name);return name==='voice.available'?{available}:{queued:true};}};
 await registry.modules.get('voice').mount(w.document.querySelector('main'),ctx);
 return {dom,w,registry,calls,notices,scope};
}
test('voice is an installed module with fixed, text and dedicated API entries',async()=>{
 const x=await setup();assert.equal(x.registry.list().filter(e=>e.id==='voice').length,1);
 for(const [text,command] of [['打开固定语音','voice.fixed'],['打开文字说话','voice.text'],['打开声音 API 设置','voice.api']]){
  const b=[...x.w.document.querySelectorAll('button')].find(b=>b.textContent===text);assert.equal(b.disabled,false);b.click();b.click();await new Promise(r=>setImmediate(r));assert.equal(x.calls.filter(c=>c===command).length,1);assert.equal(b.disabled,false);
 }
 assert.deepEqual(x.notices,[]);assert.ok(!x.w.document.body.textContent.includes('待接入'));x.scope.dispose();x.dom.window.close();
});
test('standalone and preview cannot silently queue nonexistent desktop windows',async()=>{
 for(const preview of [false,true]){
  const x=await setup(false,preview);assert.ok([...x.w.document.querySelectorAll('button')].every(b=>b.disabled));
  assert.match(x.w.document.body.textContent,/从桌面赫宝打开/);assert.deepEqual(x.calls,preview?[]:['voice.available']);x.scope.dispose();x.dom.window.close();
 }
});
