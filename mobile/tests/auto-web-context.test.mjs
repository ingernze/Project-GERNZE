import assert from 'node:assert/strict';
import {test} from 'node:test';
import {buildMessages,createChatTransport,estimateMessageBytes,DEEPSEEK_CONTEXT_BYTES} from '../src/chat-core.mjs';
import {createWebUse} from '../src/web-use.mjs';

const persona='你是合成测试人物。';
const reply=text=>({choices:[{finish_reason:'stop',message:{content:JSON.stringify({text})}}]});
const tool=query=>({choices:[{finish_reason:'tool_calls',message:{tool_calls:[{type:'function',function:{name:'search_public_web',arguments:JSON.stringify({query})}}]}}]});
const webResult=id=>({id,data:{sources:[
  {url:'https://www.iana.org/help/example-domains',title:'资料甲',basis:'body',text:'公开资料正文'.repeat(500)},
  {url:'https://www.iana.org/about',title:'资料乙',basis:'body',text:'另一份正文'.repeat(500)}
]}});
function setup({request=()=>reply('你好'),run=({id})=>webResult(id),enabled=true,budget=DEEPSEEK_CONTEXT_BYTES}={}){
 const calls=[],lookups=[],saved=[],cancelled=[];
 const web=createWebUse({sessionId:()=> 'fixture',bridge:{
   getConfig:async()=>({provider:enabled?'deepseek':'none',keyPresent:enabled}),
   run:async args=>{lookups.push(args);return run(args);},cancel:()=>{}
 }});
 const transport=createChatTransport({persona,sessionId:()=> 'fixture',budget,allowAutoWeb:true,web,uuid:()=> 'turn',
   journal:{save:async row=>saved.push(row)},cancel:id=>cancelled.push(id),
   request:async req=>{calls.push(req);return request(req);}
 });
 return {calls,lookups,saved,cancelled,send(input,history=[],signal){
   return transport.send({input,messages:[...history,{role:'user',content:input}],signal});
 }};
}
const pairs=Array.from({length:45},(_,i)=>[
 {role:'user',content:'问题'+i+'内容'.repeat(300)},
 {role:'assistant',content:'回答'+i+'信息'.repeat(500)}
]).flat();

test('ordinary phrasing lets model choose web once, keeps the newest complete turns, saves only the final reply',async()=>{
 const s=setup({request:({allowWebSearch})=>allowWebSearch?tool('影子诗 新卡组'):reply('根据来源整理。')});
 const result=await s.send('影子诗现在有什么新卡组？',pairs);
 assert.equal(s.calls.length,2);
 assert.equal(s.calls[0].allowWebSearch,true);
 assert.equal(s.calls[1].allowWebSearch,undefined);
 assert.equal(s.lookups.length,1);
 assert.equal(s.lookups[0].value,'影子诗 新卡组');
 assert(s.calls[1].messages.at(-1).content.includes('公开资料正文'));
 assert(s.calls[1].messages.some(m=>m.content===pairs.at(-2).content));
 assert(estimateMessageBytes(s.calls[1].messages)<=result.contextBudget.inputLimitBytes);
 assert(result.contextBudget.inputEstimateBytes>32768);
 assert(result.reply.includes('本轮来源'));
 assert.equal(s.saved.length,1);
 assert.equal(s.saved[0].messages.at(-1).content,result.reply);
 assert.equal(s.saved[0].messages.at(-2).content,'影子诗现在有什么新卡组？');
});

test('no tool decision, explicit opt-out, private material and disabled settings cause zero lookups',async()=>{
 const noTool=setup();await noTool.send('你好');
 assert.equal(noTool.calls[0].allowWebSearch,true);
 for(const input of ['不要查，影子诗是什么','我的课程资料在哪','看书架里有什么']){
  const s=setup();await s.send(input);assert.equal(s.calls[0].allowWebSearch,undefined);assert.equal(s.lookups.length,0);
 }
 const off=setup({enabled:false});await off.send('影子诗有哪些新卡组');
 assert.equal(off.calls[0].allowWebSearch,undefined);
 assert.equal(off.lookups.length+noTool.lookups.length,0);
});

test('tool cannot export words from prior private context or bypass one-call limit',async()=>{
 const s=setup({request:({allowWebSearch})=>allowWebSearch?tool('私人未公开书名'):reply('可说明能核对的部分。')});
 const result=await s.send('影子诗的新卡组有哪些？',[
   {role:'user',content:'私人未公开书名'},{role:'assistant',content:'明白。'}
 ]);
 assert.equal(s.lookups.length,0);
 assert.equal(s.calls.length,2);
 assert.match(result.reply,/没有可安全发送/);
});

test('explicit search with a crowded context has room, and search errors still produce a grounded fallback',async()=>{
 const s=setup({budget:32768});const ok=await s.send('帮我去看看影子诗',pairs);
 assert.equal(s.calls.length,1);assert.equal(s.lookups.length,1);assert.match(ok.reply,/本轮来源/);
 const offline=setup({run:()=>{throw Object.assign(Error('fixture'),{code:'network_failed'});}});
 const failed=await offline.send('帮我去看看影子诗',pairs);
 assert.equal(offline.calls.length,1);assert.equal(offline.saved.length,1);
 assert.match(failed.reply,/网络读取失败/);
 assert.match(offline.calls[0].messages[0].content,/不能声称已查证/);
});

test('required input that leaves no space for a source still gets a response',async()=>{
 const s=setup({budget:7600});
 const result=await s.send('帮我去看看'+ '影'.repeat(120));
 assert.equal(s.lookups.length,1);assert.equal(s.calls.length,1);
 assert.match(result.reply,/网页资料未纳入回答/);
});

test('recent turns win over optional long memories',()=>{
 const core={schemaVersion:1,entries:[{key:'core',body:'基础资料'}]};
 const layers={core,approved:[{key:'extra',body:'记忆'.repeat(1000)}],working:[]};
 const history=[
   {role:'user',content:'最近问题'+'问'.repeat(300)},
   {role:'assistant',content:'最近答复'+'答'.repeat(400)},
   {role:'user',content:'继续刚才的话题'}
 ];
 const selected=buildMessages(history,persona,{budget:4800,reserve:500,layers});
 assert.equal(selected.length,4);
 assert.match(selected[0].content,/基础资料/);
 assert(!selected[0].content.includes('记忆'.repeat(300)));
});

test('cancelling during final request cancels that native request and never saves a stale reply',async()=>{
 const controller=new AbortController();let started,finish;
 const final=new Promise(r=>started=r);
 const s=setup({request:({allowWebSearch})=>allowWebSearch?tool('影子诗'):new Promise(r=>{finish=r;started();})});
 const pending=s.send('影子诗怎么样？',[],controller.signal);
 await final;controller.abort();
 await assert.rejects(pending,e=>e.code==='cancelled');
 finish(reply('晚到的内容'));
 assert.deepEqual(s.cancelled,['turn-final']);
 assert.equal(s.saved.length,0);
});
