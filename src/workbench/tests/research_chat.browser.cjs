const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {createRequire}=require('node:module');
const load=process.env.GERNZE_TEST_NODE_MODULES?createRequire(path.join(process.env.GERNZE_TEST_NODE_MODULES,'__runner__.cjs')):require;
const {chromium}=load('playwright');
const repository=path.resolve(process.env.GERNZE_TEST_SOURCE||path.join(__dirname,'../../..'));
const base=path.resolve(process.env.GERNZE_TEST_REPORT_DIR||process.cwd()),stage=path.join(process.env.GERNZE_TEST_OVERLAY||repository,'src/workbench/static'),live=path.join(repository,'src/workbench/static');
const files={};
for(const name of ['runtime.js','modules.js','scene-memory.js','scene-chat.js','chat-adapter.js','memory-books.js','style.css','scene-gold.css','alignment.css','memory-books.css'])files['/'+name]=fs.existsSync(path.join(stage,name))?path.join(stage,name):path.join(live,name);
const html=`<!doctype html><html lang="zh-CN" data-theme="dark"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="/style.css"><link rel="stylesheet" href="/scene-gold.css"><link rel="stylesheet" href="/alignment.css"><link rel="stylesheet" href="/memory-books.css">
<style>body{margin:0;padding:18px;background:#182b3e;color:#f2e9d6}#host{container-type:size;height:calc(100vh - 36px);position:relative;max-width:1000px;margin:auto}.desktop-dialogue{height:100%;min-height:0;display:flex;flex-direction:column}.desktop-chat-history{flex:1;overflow:auto;min-height:0}.desktop-study-selection{padding:8px}.desktop-books-shell{display:flex;flex-direction:column}.research-card{padding:8px}</style>
<main id="host"></main>
<script src="/runtime.js"></script><script src="/chat-adapter.js"></script><script src="/memory-books.js"></script><script src="/scene-memory.js"></script><script src="/scene-chat.js"></script><script src="/modules.js"></script><script>
window.failBookStatus=false;window.failUndated=false;window.undatedCount=0;window.calls=[];window.capability=true;window.itemState='active';window.used=1;window.failStudy=false;window.delayStudy=false;window.delayHistory=false;
window.material={id:'10000000-0000-4000-8000-000000000001',revision:'20000000-0000-4000-8000-000000000001',state:'active',trust:'agent_inferred',title:'<img src=x onerror=window.BAD=true> 合成课程'};
window.researchCapability=true;window.failResearch=false;window.researchItem={...material,id:'30000000-0000-4000-8000-000000000001',title:'<b>合成见闻</b>'};
window.saved={turns:[],hasMore:false,compressedTurns:0};
window.call=async(command,params={},signal)=>{
 calls.push({command,params});
 if(signal?.aborted)throw new DOMException('aborted','AbortError');
 if(command==='chat.config.get')return {configured:true};
 if(command==='chat.history'){if(delayHistory)return new Promise(resolve=>window.pendingHistory=()=>resolve({turns:[{id:'old',input:'OLD_HISTORY_SENTINEL',reply:'old',status:'complete'}],hasMore:false,compressedTurns:0}));return saved;}
 if(command==='chat.research.status')return {available:researchCapability,maxMaterials:8,scope:'one_request'};
 if(command==='chat.study.status')return {available:capability,maxMaterials:8,scope:'one_request'};
 if(command==='chat.research.groups'){
  if(window.failGroups)throw Error('合成目录读取失败');
  const value={shelfSync:window.shelfSync,groups:['approved','encounter','interest','course'].map(id=>({id,count:id==='approved'?0:1}))};
  if(window.delayGroups)return new Promise(resolve=>window.pendingGroups=()=>{window.delayGroups=false;resolve(value);});
  return value;
 }
 if(command==='chat.research.list')return {entries:params.category==='approved'?[]:[{...(params.category==='course'?material:researchItem),state:itemState}],next:null};
 if(command==='chat.research.read')return {body:'COURSE_VIEW_BODY_SENTINEL'};
 if(command==='chat.research.reply'){if(failResearch)throw Error('合成研究来源已变化');return {text:'合成研究回答',research_use:{status:used?'ready':'budget_omitted_before_body',used}};}
 if(command==='chat.study.reply'){
   if(failStudy)throw new Error('合成来源已变化，请重新选择。');
   const result={text:'合成课程回答',research_use:{status:used?'ready':'budget_omitted_before_body',used}};
   if(delayStudy)return new Promise(resolve=>window.pendingStudy=()=>resolve(result));return result;
 }
 if(command==='chat.reply'){const result={text:'合成普通回答'};saved={turns:[{id:params.request_id,seq:1,input:params.text,reply:result.text,status:'complete'}],hasMore:false,compressedTurns:0};return result;}
 if(command==='chat.cancel')return {cancelled:true};
 if(command==='chat.books.months')return [];
 if(command==='chat.books.status'){if(failBookStatus)throw Error('合成日期信息失败');return {undatedEntries:undatedCount};}
 if(command==='chat.books.undated'){if(failUndated)throw Error('合成无日期原文失败');return {entries:[{text:'SYNTHETIC_UNDATED_BODY'}]};}
 throw new Error('unexpected '+command);
};
window.registry=new HebaoRuntime.Registry();HebaoModules.register(registry);window.scope=new HebaoRuntime.Scope();
window.facade=HebaoRuntime.clientFor(registry.list().find(e=>e.id==='scene'),window.call);
window.controller=HecateSceneChat.mount(document.querySelector('#host'),{scope,call:facade,send:()=>{}});
</script></html>`;
const server=http.createServer((req,res)=>{if(req.url==='/'){res.writeHead(200,{'Content-Type':'text/html;charset=utf-8'});res.end(html);return;}const file=files[req.url];if(!file){res.writeHead(404);res.end();return;}res.writeHead(200,{'Content-Type':file.endsWith('.js')?'text/javascript;charset=utf-8':'text/css;charset=utf-8'});res.end(fs.readFileSync(file));});
let browser,page;const checks=[],errors=[];
const check=async(name,fn)=>{await fn();checks.push(name);};
const pickCategory=async id=>{await page.locator('.research-category-toggle').click();await page.locator('[data-category='+id+']').click();};
const choose=async()=>{await page.evaluate(()=>controller.openBooks());await pickCategory('course');await page.getByRole('button',{name:'用于下一次提问',exact:true}).waitFor();await page.getByRole('button',{name:'用于下一次提问',exact:true}).click();};
const send=async(text)=>{await page.locator('textarea').fill(text);await page.getByRole('button',{name:'发送',exact:true}).click();};
const idle=async()=>page.waitForFunction(()=>!document.querySelector('button[type=submit]').disabled);
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));browser=await chromium.launch({channel:'msedge',headless:true});page=await browser.newPage({viewport:{width:1120,height:900}});
 page.on('pageerror',e=>errors.push(e.message));await page.goto('http://127.0.0.1:'+server.address().port);await page.locator('form:not([hidden])').waitFor();
 await check('ordinary mount does not ask for course capability or metadata',async()=>{assert.equal(await page.evaluate(()=>calls.some(c=>c.command.startsWith('chat.study.')||c.command.startsWith('chat.research.'))),false);});
 await check('monthly artwork remains the default and categories are secondary',async()=>{
  await page.evaluate(()=>controller.openBooks());assert.equal(await page.locator('.desktop-books-host .mb-books[data-view=shelf]').isVisible(),true);assert.equal(await page.locator('.research-categories').isVisible(),false);assert.equal(await page.locator('.research-panel').isVisible(),false);
  assert.equal(await page.evaluate(()=>calls.some(c=>c.command==='chat.research.list'||c.command==='chat.research.read'||c.command==='chat.study.status')),false);
  await page.locator('.research-category-toggle').click();await page.keyboard.press('Escape');assert.equal(await page.locator('.research-categories').isVisible(),false);assert.equal(await page.locator('.desktop-books-overlay').isVisible(),true);await page.locator('.research-heading button').last().click();
 });
 await check('course directory reads metadata without body or model call',async()=>{
  await page.evaluate(()=>controller.openBooks());await pickCategory('course');await page.getByRole('button',{name:'用于下一次提问',exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>calls.some(c=>c.command==='chat.research.read'||c.command==='chat.study.reply')),false);
  assert.equal(await page.locator('.research-card strong').textContent(),'<img src=x onerror=window.BAD=true> 合成课程');assert.equal(await page.locator('.research-card img').count(),0);
 });
 await check('viewing a course does not select it for chat',async()=>{
  await page.getByRole('button',{name:'查看课程资料',exact:true}).click();await page.locator('.research-body').waitFor();assert.equal(await page.locator('.desktop-study-selection').isVisible(),false);
 });
 await check('explicit use clears viewed body and shows one-question scope',async()=>{
  await page.getByRole('button',{name:'用于下一次提问',exact:true}).click();assert.equal(await page.locator('.research-body').count(),0);assert.equal(await page.locator('.desktop-study-selection').isVisible(),true);assert.ok((await page.locator('.desktop-study-selection').textContent()).includes('仅下一次提问参考'));
 });
 await check('removing selection sends an ordinary request without materials',async()=>{
  await page.getByRole('button',{name:'移除资料',exact:true}).click();await send('普通问题一');await idle();const c=await page.evaluate(()=>calls.filter(c=>c.command==='chat.reply').at(-1));assert.equal(c.params.text,'普通问题一');assert.equal('materials' in c.params,false);
 });
 await check('selected material enters dedicated request once and answer stays visible',async()=>{
  await choose();await send('讲解所选资料');await idle();const c=await page.evaluate(()=>calls.filter(c=>c.command==='chat.study.reply').at(-1));assert.deepEqual(c.params.materials,[{id:'10000000-0000-4000-8000-000000000001',revision:'20000000-0000-4000-8000-000000000001'}]);
  assert.deepEqual(Object.keys(c.params).sort(),['materials','request_id','text']);assert.equal(await page.locator('.desktop-study-selection').isVisible(),false);assert.ok((await page.locator('.desktop-chat-log').innerText()).includes('合成课程回答'));
 });
 await check('next ordinary question does not retain a course selection',async()=>{
  const count=await page.evaluate(()=>calls.filter(c=>c.command==='chat.study.reply').length);await send('普通问题二');await idle();assert.equal(await page.evaluate(()=>calls.filter(c=>c.command==='chat.study.reply').length),count);assert.equal(await page.evaluate(()=>calls.filter(c=>c.command==='chat.reply').at(-1).params.text),'普通问题二');
 });
 await check('omitted material is reported without claiming it was used',async()=>{
  await page.evaluate(()=>window.used=0);await choose();await send('预算不足例子');await idle();assert.ok((await page.locator('.scene-chat > .scene-status').textContent()).includes('未带入所选资料'));await page.evaluate(()=>window.used=1);
 });
 await check('failed request consumes selection and retry is ordinary',async()=>{
  await choose();await page.evaluate(()=>window.failStudy=true);await send('失败例子');await idle();await page.waitForFunction(()=>document.querySelector('.scene-chat > .scene-status').textContent.includes('合成来源已变化'));
  assert.equal(await page.locator('.desktop-study-selection').isVisible(),false);await page.evaluate(()=>window.failStudy=false);await send('重试普通问题');await idle();assert.equal(await page.evaluate(()=>calls.at(-1).command==='chat.study.reply'),false);
 });
 await check('disabled host keeps local view but has no course-use button',async()=>{
  await page.evaluate(()=>window.capability=false);await page.evaluate(()=>controller.openBooks());await pickCategory('course');await page.getByRole('button',{name:'查看课程资料',exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'用于下一次提问',exact:true}).count(),0);await page.locator('.research-heading button').last().click();await page.evaluate(()=>window.capability=true);
 });
 await check('unavailable source cannot be selected',async()=>{
  await page.evaluate(()=>window.itemState='unavailable');await page.evaluate(()=>controller.openBooks());await pickCategory('course');await page.getByRole('button',{name:'用于下一次提问',exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'用于下一次提问',exact:true}).isDisabled(),true);await page.locator('.research-heading button').last().click();await page.evaluate(()=>window.itemState='active');
 });
 await check('late ordinary history cannot replace pending or completed course answer',async()=>{
  await choose();await page.evaluate(()=>{window.delayHistory=true;controller.refresh();});await page.waitForFunction(()=>Boolean(window.pendingHistory));await send('历史晚到例子');await idle();await page.evaluate(()=>{pendingHistory();window.delayHistory=false;});await page.waitForTimeout(25);assert.ok((await page.locator('.desktop-chat-log').textContent()).includes('历史晚到例子'));assert.equal((await page.locator('.desktop-chat-log').textContent()).includes('OLD_HISTORY_SENTINEL'),false);
 });
 await check('closing conversation clears unsent selection',async()=>{
  await choose();await page.evaluate(()=>{controller.close();controller.open();});assert.equal(await page.locator('.desktop-study-selection').isVisible(),false);
 });
 await check('cancel ignores delayed course answer and does not retain selection',async()=>{
  await choose();await page.evaluate(()=>window.delayStudy=true);await send('取消例子');await page.waitForFunction(()=>Boolean(window.pendingStudy));await page.getByRole('button',{name:'停止等待',exact:true}).click();await page.evaluate(()=>{pendingStudy();window.delayStudy=false;});await page.waitForTimeout(25);assert.equal(await page.locator('.desktop-study-selection').isVisible(),false);assert.ok(await page.evaluate(()=>calls.some(c=>c.command==='chat.cancel'&&c.params.request_id)));
 });

 const chooseGeneral=async(category='encounter')=>{await page.evaluate(()=>controller.openBooks());await pickCategory(category);await page.getByRole('button',{name:'用于下一次提问',exact:true}).waitFor();await page.getByRole('button',{name:'用于下一次提问',exact:true}).click();};
 await check('general selection is metadata-only and keeps source title literal',async()=>{
  const before=await page.evaluate(()=>calls.filter(c=>c.command==='chat.research.read'||c.command.endsWith('.reply')).length);
  await chooseGeneral();assert.equal(await page.locator('.desktop-study-selection').isVisible(),true);
  assert.ok((await page.locator('.desktop-study-selection').textContent()).includes('<b>合成见闻</b>'));assert.equal(await page.locator('.desktop-study-selection b').count(),0);
  assert.equal(await page.evaluate(()=>calls.filter(c=>c.command==='chat.research.read'||c.command.endsWith('.reply')).length),before);
 });
 await check('general material uses general endpoint with exact refs',async()=>{
  await send('解释合成见闻');await idle();const c=await page.evaluate(()=>calls.filter(c=>c.command==='chat.research.reply').at(-1));
  assert.deepEqual(c.params.materials,[{id:'30000000-0000-4000-8000-000000000001',revision:'20000000-0000-4000-8000-000000000001'}]);assert.deepEqual(Object.keys(c.params).sort(),['materials','request_id','text']);
  assert.ok((await page.locator('.desktop-chat-log').textContent()).includes('合成研究回答'));assert.equal(await page.locator('.desktop-study-selection').isVisible(),false);
 });
 await check('next question has no retained explicit general selection',async()=>{
  const count=await page.evaluate(()=>calls.filter(c=>c.command==='chat.research.reply').length);await send('下一普通问题');await idle();assert.equal(await page.evaluate(()=>calls.filter(c=>c.command==='chat.research.reply').length),count);
  assert.equal(await page.evaluate(()=>calls.filter(c=>c.command==='chat.reply').at(-1).params.text),'下一普通问题');
 });
 await check('interest group can select and remove without model call',async()=>{
  await chooseGeneral('interest');await page.getByRole('button',{name:'移除资料',exact:true}).click();await send('移除后的普通问题');await idle();assert.equal(await page.locator('.desktop-study-selection').isVisible(),false);assert.equal(await page.evaluate(()=>calls.filter(c=>c.command==='chat.reply').at(-1).params.text),'移除后的普通问题');
 });
 await check('general budget omission and failure do not claim use or retain selection',async()=>{
  await page.evaluate(()=>window.used=0);await chooseGeneral();await send('见闻预算不足');await idle();assert.ok((await page.locator('.scene-chat > .scene-status').textContent()).includes('未带入所选资料'));
  await page.evaluate(()=>{window.used=1;window.failResearch=true;});await chooseGeneral();await send('见闻失败');await idle();assert.equal(await page.locator('.desktop-study-selection').isVisible(),false);await page.evaluate(()=>window.failResearch=false);
 });
 await check('disabled general host and unavailable sources have no usable selection',async()=>{
  await page.evaluate(()=>window.researchCapability=false);await page.evaluate(()=>controller.openBooks());await pickCategory('encounter');await page.getByRole('button',{name:'查看内容',exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'用于下一次提问',exact:true}).count(),0);await page.locator('.research-heading button').last().click();
  await page.evaluate(()=>{window.researchCapability=true;window.itemState='unavailable';});await page.evaluate(()=>controller.openBooks());await pickCategory('interest');await page.getByRole('button',{name:'用于下一次提问',exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'用于下一次提问',exact:true}).isDisabled(),true);await page.locator('.research-heading button').last().click();await page.evaluate(()=>window.itemState='active');
 });
 await check('course selection after general selection retains dedicated route',async()=>{
  await chooseGeneral();await choose();await send('仍是课程请求');await idle();assert.equal(await page.evaluate(()=>calls.filter(c=>c.command.endsWith('.reply')).at(-1).command),'chat.study.reply');
 });
 await check('approved memory group never gains a manual material selector',async()=>{
  await page.evaluate(()=>controller.openBooks());await pickCategory('approved');await page.waitForFunction(()=>!document.querySelector('.research-rows').hasAttribute('aria-busy')||document.querySelector('.research-rows').getAttribute('aria-busy')==='false');assert.equal(await page.getByRole('button',{name:'用于下一次提问',exact:true}).count(),0);await page.locator('.research-heading button').last().click();
 });
 await check('archive status failure is visible and retries without replacing the artwork',async()=>{
  await page.evaluate(()=>{window.failBookStatus=true;});await page.evaluate(()=>controller.openBooks());assert.equal(await page.locator('.desktop-books-overlay').getByText('日期信息暂未取回，月册仍可正常查看。',{exact:true}).isVisible(),true);assert.equal(await page.locator('.desktop-books-host .mb-books[data-view=shelf]').isVisible(),true);
  await page.evaluate(()=>{window.failBookStatus=false;});await page.getByRole('button',{name:'重试日期信息',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.desktop-archive-notice').hidden);await page.locator('.research-heading button').last().click();
 });
 await check('undated raw failure is visible and retries inside the open section',async()=>{
  await page.evaluate(()=>{window.undatedCount=1;window.failUndated=true;});await page.evaluate(()=>controller.openBooks());await page.locator('.desktop-undated summary').click();await page.getByRole('button',{name:'重新读取原文',exact:true}).waitFor();assert.equal(await page.getByText('日期不明的原文暂未取回，请重试。',{exact:true}).isVisible(),true);
  await page.evaluate(()=>window.failUndated=false);await page.getByRole('button',{name:'重新读取原文',exact:true}).click();await page.getByText('SYNTHETIC_UNDATED_BODY',{exact:true}).waitFor();await page.locator('.research-heading button').last().click();await page.evaluate(()=>window.undatedCount=0);
 });
 await check('incomplete publication is explained without replacing the books or counts',async()=>{
  await page.evaluate(()=>{window.shelfSync={state:'waiting',message:'分类资料尚未更新，保留原书架。'};controller.openBooks();});await page.locator('.research-sync-state').waitFor();assert.equal(await page.locator('.research-sync-state').textContent(),'分类资料尚未更新，保留原书架。');assert.equal(await page.locator('.desktop-books-host .mb-books[data-view=shelf]').isVisible(),true);await pickCategory('interest');await page.getByRole('button',{name:'查看内容',exact:true}).waitFor();await page.locator('.research-heading button').last().click();
 });
 await check('successful next publication clears the warning on reopen',async()=>{
  await page.evaluate(()=>{window.shelfSync={state:'updated',message:'分类资料已更新。'};controller.openBooks();});await page.waitForFunction(()=>document.querySelector('.research-sync-state').hidden);await page.locator('.research-heading button').last().click();
 });
 await check('category waits for publication check while monthly archive opens immediately',async()=>{
  const before=await page.evaluate(()=>calls.filter(c=>c.command==='chat.research.list').length);
  await page.evaluate(()=>{window.delayGroups=true;controller.openBooks();});assert.equal(await page.locator('.desktop-books-host .mb-books[data-view=shelf]').isVisible(),true);
  await pickCategory('encounter');assert.equal(await page.evaluate(()=>calls.filter(c=>c.command==='chat.research.list').length),before);assert.equal(await page.locator('.research-card').count(),0);
  await page.evaluate(()=>{window.researchItem={...researchItem,revision:'30000000-0000-4000-8000-000000000099',title:'更新后的合成资料'};pendingGroups();});
  await page.getByRole('button',{name:'查看内容',exact:true}).waitFor();assert.equal(await page.locator('.research-card strong').textContent(),'更新后的合成资料');await page.locator('.research-heading button').last().click();
 });
 await check('closing a category awaiting publication discards its late continuation',async()=>{
  const before=await page.evaluate(()=>calls.filter(c=>c.command==='chat.research.list').length);
  await page.evaluate(()=>{window.delayGroups=true;controller.openBooks();});await pickCategory('interest');await page.locator('.research-heading button').last().click();await page.evaluate(()=>pendingGroups());
  assert.equal(await page.evaluate(()=>calls.filter(c=>c.command==='chat.research.list').length),before);assert.equal(await page.locator('.research-card').count(),0);assert.equal(await page.locator('.desktop-books-overlay').isVisible(),false);
 });
 await check('group transport failure is visible over archive and clears on successful reopen',async()=>{
  await page.evaluate(()=>{window.failGroups=true;controller.openBooks();});await page.locator('.research-sync-state').waitFor();assert.equal(await page.locator('.research-sync-state').textContent(),'分类资料暂未取回，保留原书架；重新打开后重试。');assert.equal(await page.locator('.desktop-books-host .mb-books[data-view=shelf]').isVisible(),true);
  await page.locator('.research-heading button').last().click();await page.evaluate(()=>{window.failGroups=false;controller.openBooks();});await page.waitForFunction(()=>document.querySelector('.research-sync-state').hidden);await page.locator('.research-heading button').last().click();
 });
 await check('narrow view remains within screen and teardown removes course scope',async()=>{
  await choose();await page.setViewportSize({width:420,height:850});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await page.evaluate(()=>scope.dispose());assert.equal(await page.locator('.scene-chat').count(),0);assert.deepEqual(errors,[]);
 });
 fs.writeFileSync(path.join(base,'RESEARCH-SELECTION-BROWSER.json'),JSON.stringify({success:true,checks,scriptErrors:errors,syntheticOnly:true,realModelCalls:0},null,2));console.log(JSON.stringify({success:true,checks:checks.length}));
})().catch(async e=>{if(page)await page.screenshot({path:path.join(base,'RESEARCH-SELECTION-BROWSER-FAILURE.png'),fullPage:true});fs.writeFileSync(path.join(base,'RESEARCH-SELECTION-BROWSER-FAILURE.json'),JSON.stringify({success:false,error:String(e),checks,errors},null,2));console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();await new Promise(r=>server.close(r));});
