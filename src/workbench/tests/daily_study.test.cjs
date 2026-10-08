// DOM integration, not browser screenshots: real bundled JS + local HTTP + SQLite.
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {spawn}=require('node:child_process');
const {JSDOM}=require('jsdom');
const project=path.resolve(__dirname,'../..');
const staticDir=path.join(project,'workbench/static');
const scriptNames=['theme.js','layout.js','runtime.js','frame.js','example.js','modules.js','app.js'];
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){const end=Date.now()+8000;while(Date.now()<end){if(check())return;await tick();}throw new Error('UI settlement timeout');}
async function setup(t){
  const fixture=spawn(process.env.HEBAO_PYTHON||'python3',['-u','tests/http_fixture.py'],{cwd:project,stdio:['pipe','pipe','pipe']});
  const config=await new Promise((resolve,reject)=>{
    let buf='';fixture.stdout.on('data',part=>{buf+=part;if(buf.includes('\n'))resolve(JSON.parse(buf.split('\n')[0]));});
    fixture.on('error',reject);fixture.on('exit',code=>{if(code)reject(new Error('fixture failed'));});
  });
  const token=new URL(config.url).hash.slice('#session='.length);
  const state={clipboard:'',failClipboard:false,requests:[],errors:[],failRefresh:false,gate:null};
  async function api(command,params={}){
    const res=await fetch(config.origin+'/api/call',{method:'POST',headers:{'Content-Type':'application/json','Origin':config.origin,'Authorization':'Bearer '+token},body:JSON.stringify({command,params})});
    const data=await res.json();if(!res.ok)throw new Error(data.error);return data.result;
  }
  let dom;
  async function open(useFragment=true,session=null){
    const html=await (await fetch(config.origin+'/')).text();
    dom=new JSDOM(html,{url:useFragment?config.url:config.origin+'/',runScripts:'outside-only',pretendToBeVisual:true});
    const w=dom.window;
    w.TextEncoder=TextEncoder;w.AbortController=AbortController;
    w.ResizeObserver=class{observe(){}disconnect(){}};
    Object.defineProperty(w.HTMLElement.prototype,'clientWidth',{get:()=>1280});
    w.console.error=(error)=>state.errors.push(String(error));
    w.navigator.clipboard={writeText:async text=>{if(state.failClipboard)throw new Error('clipboard unavailable');state.clipboard=text;}};
    if(session)w.sessionStorage.setItem('hebao.workbench.session',session);
    w.fetch=async(relative,options)=>{
      const value=JSON.parse(options.body);state.requests.push(value);
      if(state.failRefresh&&value.command==='state.summary')throw new Error('simulated refresh interruption');
      if(state.gate&&value.command==='daily.save')await state.gate;
      return fetch(new URL(relative,config.origin),{...options,headers:{...options.headers,Origin:config.origin}});
    };
    for(const name of scriptNames)w.eval(fs.readFileSync(path.join(staticDir,name),'utf8'));
    return w;
  }
  let w=await open();
  try{await until(()=>w.document.getElementById('study-report'));}
  catch(error){dom.window.close();fixture.stdin.end('\n');throw new Error(error.message+' '+state.errors.join(' | ')+' '+w.document.body.textContent);}
  t.after(async()=>{dom.window.close();fixture.stdin.end('\n');await new Promise(resolve=>fixture.on('exit',resolve));});
  const node=id=>w.document.getElementById(id);
  const action=name=>[...w.document.querySelectorAll('button')].find(el=>el.textContent===name);
  const fill=text=>{node('study-report').value=text;node('study-report').dispatchEvent(new w.Event('input',{bubbles:true}));};
  async function copy(){action('复制学习提示词').click();await until(()=>node('study-copy-status').textContent && action('复制学习提示词') && !action('复制学习提示词').disabled);return node('study-prompt').value;}
  function report(prompt){const value=JSON.parse(prompt.slice(prompt.lastIndexOf('\n{')+1));return {...value,discussion_completed:true,scenario:'question_help',user_report:{material:'纸质练习',details:'这句话里although是什么意思？',accuracy:null,accuracy_basis:''},summary:'完成因果题与让步句解释',evidence:'用户提供了原文两句依据',weak_points:[{point:'although让步关系需复查',evidence:'用户首次将although理解为原因'}],review_focus:'下一次检查一个让步句',activities:[{skill:'reading',task:'解释短文因果关系',response:'The route changed because it was no longer safe.',feedback:'网页基于原文给出的建议'}]};}
  async function save(){action('保存学习汇报')?.click();await until(()=>!node('study-report').readOnly && !node('study-save-status').textContent.includes('正在保存'));}
  return {state,api,node,action,fill,copy,report,save,get window(){return w;},async reload(){const session=w.sessionStorage.getItem('hebao.workbench.session');dom.window.close();w=await open(false,session);await until(()=>node('study-report'));},async nav(title){const el=w.document.querySelector('[data-module-id="'+title+'"]');assert.ok(el);el.click();await until(()=>title==='study'?node('study-report'):!node('study-report'));}};
}

test('daily page has two main actions, empty save is disabled and startup has no side effects',async t=>{
 const x=await setup(t);assert.equal(x.window.document.querySelectorAll('.study-main-action').length,2);
 assert.equal(x.action('保存学习汇报').disabled,true);assert.equal(x.window.document.querySelectorAll('input,select').length,0);
 assert.equal((await x.api('state.summary')).progress.submission_count,0);
 assert.equal((await x.api('daily.workspace')).pending_prompt,null);
 assert.ok(!x.state.requests.some(r=>r.command==='daily.prompt'||r.command==='daily.save'));
});
test('copy prepares real prompt without counting; tab reload recovers pending prompt and local capability',async t=>{
 const x=await setup(t);const prompt=await x.copy();assert.equal(x.state.clipboard,prompt);assert.equal((await x.api('state.summary')).progress.submission_count,0);
 assert.equal(x.window.location.hash,'');await x.reload();assert.equal(x.node('study-prompt').value,prompt);
 assert.equal(await x.copy(),prompt);assert.deepEqual(x.state.errors,[]);
});
test('clipboard failure selects all text and gives manual-copy instructions',async t=>{
 const x=await setup(t);x.state.failClipboard=true;const prompt=await x.copy();const el=x.node('study-prompt');assert.equal(el.selectionStart,0);assert.equal(el.selectionEnd,prompt.length);
 assert.match(x.node('study-copy-status').textContent,/Ctrl\+C/);assert.equal(el.readOnly,true);
});
test('page switch preserves draft; explicit save uses edited input, persists and repeats once',async t=>{
 const x=await setup(t);const r=x.report(await x.copy());x.fill(JSON.stringify(r));await x.nav('memory');await x.nav('study');assert.equal(x.node('study-report').value,JSON.stringify(r));
 r.summary='切页后按实际作答修订的总结';x.fill(JSON.stringify(r));await x.save();assert.match(x.node('study-save-status').textContent,/已保存/);
 assert.equal((await x.api('daily.workspace')).history[0].summary,r.summary);assert.equal((await x.api('state.summary')).progress.submission_count,1);
 x.fill(JSON.stringify(r));await x.save();assert.match(x.node('study-save-status').textContent,/没有重复计数/);assert.equal((await x.api('state.summary')).progress.submission_count,1);
 assert.ok(x.action('查看全部历史'));assert.deepEqual(x.state.errors,[]);
});
test('malformed or wrong-number report produces a specific error without writes',async t=>{
 const x=await setup(t);x.fill('我学完了');await x.save();assert.match(x.node('study-save-status').textContent,/有效.*汇报/);assert.equal(x.node('study-save-status').getAttribute('role'),'alert');
 const r=x.report(await x.copy());r.handoff_id='not-local';x.fill(JSON.stringify(r));await x.save();assert.match(x.node('study-save-status').textContent,/编号/);
 assert.equal((await x.api('state.summary')).progress.submission_count,0);assert.equal(x.node('study-report').readOnly,false);
});
test('long report can be edited; over-100KB input rejects before sending or writing',async t=>{
 const x=await setup(t);x.fill('字'.repeat(34000));assert.equal(x.node('study-report').value.length,34000);await x.save();assert.match(x.node('study-save-status').textContent,/100KB/);
 assert.ok(!x.state.requests.some(r=>r.command==='daily.save'));assert.equal((await x.api('state.summary')).progress.submission_count,0);
 x.fill('');assert.equal(x.action('保存学习汇报').disabled,true);
});
test('busy save disables action and editing; rapid clicks send only one request',async t=>{
 const x=await setup(t);x.fill(JSON.stringify(x.report(await x.copy())));let release;x.state.gate=new Promise(r=>release=r);
 const btn=x.action('保存学习汇报');btn.click();assert.equal(btn.disabled,true);assert.equal(x.node('study-report').readOnly,true);btn.click();assert.equal(x.state.requests.filter(r=>r.command==='daily.save').length,1);
 release();await until(()=>!x.node('study-report').readOnly);assert.equal((await x.api('state.summary')).progress.submission_count,1);
});
test('successful save stays successful when subsequent refresh fails',async t=>{
 const x=await setup(t);x.fill(JSON.stringify(x.report(await x.copy())));x.state.failRefresh=true;await x.save();assert.match(x.node('study-save-status').textContent,/已保存.*未刷新/);
 assert.equal(x.node('study-save-status').getAttribute('role'),'status');assert.equal((await x.api('state.summary')).progress.submission_count,1);
});
test('late save after navigation does not repaint another page; retry finds stored receipt',async t=>{
 const x=await setup(t);const raw=JSON.stringify(x.report(await x.copy()));x.fill(raw);let release;x.state.gate=new Promise(r=>release=r);
 x.action('保存学习汇报').click();await x.nav('memory');release();await tick();await x.nav('study');assert.equal(x.node('study-report').value,raw);
 x.state.gate=null;await x.save();assert.equal((await x.api('state.summary')).progress.submission_count,1);assert.deepEqual(x.state.errors,[]);
});
test('new prompt after save clears consumed report; edited unsaved draft is retained',async t=>{
 const x=await setup(t);const first=await x.copy();x.fill(JSON.stringify(x.report(first)));await x.save();const next=await x.copy();assert.notEqual(next,first);assert.equal(x.node('study-report').value,'');assert.equal(x.action('保存学习汇报').disabled,true);
 x.fill('尚在整理的学习汇报');await x.copy();assert.equal(x.node('study-report').value,'尚在整理的学习汇报');
});
test('theme setting changes real theme and persists through HTTP; labels remain focusable',async t=>{
 const x=await setup(t);const el=x.node('study-report');assert.ok(el.closest('label'));el.focus();assert.equal(x.window.document.activeElement,el);
 await x.nav('settings');const toggle=x.window.document.querySelector('.theme-switch');toggle.click();await until(()=>!toggle.disabled);assert.equal(x.window.document.documentElement.dataset.theme,'light');
 await x.nav('study');assert.ok(x.node('study-report'));await x.reload();assert.equal(x.window.document.documentElement.dataset.theme,'light');
 assert.deepEqual(x.state.errors,[]);
});
for(const [name,caseName] of [['正常流程_演示.html','normal'],['具体答疑_演示.html','question'],['错误流程_演示.html','error']]){
 test('offline '+caseName+' demo executes current production module and labels itself as simulation',async t=>{
  const file=path.join(project,'docs/previews',name);
  const dom=new JSDOM(fs.readFileSync(file,'utf8'),{url:'file://'+file,runScripts:'outside-only',pretendToBeVisual:true});t.after(()=>dom.window.close());
  const w=dom.window;w.TextEncoder=TextEncoder;w.ResizeObserver=class{observe(){}disconnect(){}};Object.defineProperty(w.HTMLElement.prototype,'clientWidth',{get:()=>1280});
  for(const name of ['theme','layout','runtime','frame','modules'])w.eval(fs.readFileSync(path.join(staticDir,name+'.js'),'utf8'));
  w.eval(fs.readFileSync(path.join(project,'docs/previews/demo.js'),'utf8'));
  await until(()=>w.document.getElementById('study-report'));
  assert.match(w.document.body.textContent,/演示预览.*不写入/);
  if(caseName!=='error'){w.document.querySelector('.study-entry:nth-child(2) .study-main-action').click();await until(()=>w.document.getElementById('study-save-status').textContent.includes('已保存'));}
  else await until(()=>w.document.getElementById('study-save-status').getAttribute('role')==='alert');
 });
}
for(const scenario of ['exam_review','question_help']){
 test('paper '+scenario+' uses two actions, saves source distinctions and feeds the next prompt',async t=>{
  const x=await setup(t);const r=x.report(await x.copy());r.scenario=scenario;
  r.user_report.details=scenario==='exam_review'?'我做完纸上阅读，错误集中在连接词，阅读部分自述65%。':'句子中although为何不能理解为because？';
  r.user_report.accuracy=scenario==='exam_review'?65:null;r.user_report.accuracy_basis=scenario==='exam_review'?'用户自述阅读部分65%，不是整卷':' ';
  r.reference_findings=[{conclusion:'although表达让步',source:'用户提供的纸质解析',evidence:'解析注明although为尽管'}];r.basis='reference_material';
  x.fill(JSON.stringify(r));await x.save();assert.match(x.node('study-save-status').textContent,/已保存/);
  const text=x.window.document.querySelector('.study-receipt').textContent;
  assert.match(text,scenario==='exam_review'?/试卷复盘/:/具体问题答疑/);
  assert.match(text,scenario==='exam_review'?/用户自述正确率：65%/:/整体正确率未知/);
  assert.match(text,/参考支持的结论.*未独立核验/);assert.equal((await x.api('state.summary')).progress.submission_count,1);
  const next=await x.copy();assert.ok(next.includes(r.user_report.details));assert.ok(next.includes('用户提供的纸质解析'));
  await x.reload();assert.equal(x.node('study-prompt').value,next);assert.equal(x.window.document.querySelectorAll('.study-main-action').length,2);
 });
}
test('awaiting discussion report is rejected visibly and leaves submission count zero',async t=>{
 const x=await setup(t);const r=x.report(await x.copy());r.discussion_completed=false;x.fill(JSON.stringify(r));await x.save();
 assert.match(x.node('study-save-status').textContent,/没有完成实际复盘或答疑/);assert.equal((await x.api('state.summary')).progress.submission_count,0);
 assert.equal(x.node('study-report').value,JSON.stringify(r));
});
