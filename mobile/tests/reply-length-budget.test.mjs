import assert from 'node:assert/strict';
import {buildMessages,normalizeReply,createChatTransport,replyBudgetFor,estimateMessageBytes,MAX_MESSAGE_UNITS,createNativeChatRequest} from '../src/chat-core.mjs';
import {validateSnapshot} from '../src/chat-journal.mjs';
let count=0;const checks=[];const check=async(name,fn)=>{await fn();count++;checks.push(name);console.log('PASS',name);};
const raw=(content,finish_reason='stop')=>({choices:[{message:{content},finish_reason}]});
const reply=text=>raw(JSON.stringify({text}));
const text='合成'.repeat(2998)+'尾部验证';
const persona='合成只读人设。';
await check('6000-unit Chinese reply is complete through normalization and journal validator',()=>{
  assert.equal(text.length,6000);assert.equal(normalizeReply(reply(text)).reply,text);
  const s=validateSnapshot({id:'synthetic',messages:[{role:'user',content:'测试'},{role:'assistant',content:text}]});assert.equal(s.messages[1].content,text);
  const m=buildMessages([...s.messages,{role:'user',content:'继续聊'}],persona);assert.equal(m[2].content,text);
});
await check('body boundary uses UTF-16 units and never slices',()=>{
  assert.equal(normalizeReply(reply('中'.repeat(MAX_MESSAGE_UNITS))).reply.length,MAX_MESSAGE_UNITS);
  assert.equal(normalizeReply(reply('😀'.repeat(MAX_MESSAGE_UNITS/2))).reply.length,MAX_MESSAGE_UNITS);
  for(const content of ['中'.repeat(MAX_MESSAGE_UNITS+1),'😀'.repeat(MAX_MESSAGE_UNITS/2+1)])assert.throws(()=>normalizeReply(reply(content)),e=>e.code==='reply_too_long');
  assert.throws(()=>validateSnapshot({id:'synthetic',messages:[{role:'user',content:'输入'},{role:'assistant',content:'x'.repeat(12001)}]}));
});
await check('raw content cap is independent from decoded escaped body cap',()=>{
  const escaped='{"text":"'+'\\u4e2d'.repeat(12000)+'"}';assert(escaped.length>12000);assert.equal(normalizeReply(raw(escaped)).reply.length,12000);
  assert.throws(()=>normalizeReply(raw('x'.repeat(100001))),e=>e.code==='invalid_response');
  assert.throws(()=>normalizeReply(raw('{"text":"'+'\\u4e2d'.repeat(12001)+'"}')),e=>e.code==='reply_too_long');
});
await check('damaged structured replies and fences cannot masquerade as successful prose',()=>{
  for(const content of ['{"text":"unfinished','[unfinished','```json\n{"text":"ok"}','```json\nnot json\n```','```','{"text":42}','[]','null'])assert.throws(()=>normalizeReply(raw(content)));
  assert.equal(normalizeReply(raw('```json\n{"text":"有效回复"}\n```')).reply,'有效回复');
  assert.equal(normalizeReply(raw('完整普通文字，含 {一个例子}。')).reply,'完整普通文字，含 {一个例子}。');
});
await check('missing/null finish reason keeps desktop compatibility; explicit incomplete status fails',()=>{
  for(const reason of [undefined,null,'stop']){const value=reply('完整正文');value.choices[0].finish_reason=reason;assert.equal(normalizeReply(value).reply,'完整正文');}
  for(const reason of ['length','content_filter','tool_calls',false,0])assert.throws(()=>normalizeReply(raw('{"text":"看似完整"}',reason)),/未完整/);
});
await check('duplicate-key boundary is explicit: stock JSON.parse keeps last value, not detection',()=>{
  assert.equal(normalizeReply(raw('{"text":"先值","text":"后值"}')).reply,'后值');
});
await check('same finite Chinese detail rule as desktop, quoted/history/source text cannot upgrade',()=>{
  for(const input of ['请详细解释这个问题','帮我深入分析原因','再全面比较两种方法','展开说说'])assert.equal(replyBudgetFor(input).maxTokens,1800);
  for(const input of ['普通问题','Please explain in detail','这个问题能多讲一点吗','“请详细解释”','引用：请详细解释','请详细解释“这个词”','> 详细分析','```\n详细解释\n```'])assert.equal(replyBudgetFor(input).maxTokens,700);
  for(const origin of ['quote','fiction','external_ai','assistant','inference'])assert.equal(replyBudgetFor('请详细分析',origin).maxTokens,700);
});
await check('transport reserves and forwards the same one-turn decision, with separate safety bytes',async()=>{
  for(const input of ['普通问题','请详细解释这个问题','请详细解释“引文”']){
    let sent,saved;const t=createChatTransport({persona,sessionId:()=> 'synthetic',request:async p=>{sent=p;return reply('完整合成回复');},journal:{save:async s=>saved=s}});
    try{const result=await t.send({input,messages:[{role:'user',content:input}]});const plan=replyBudgetFor(input);assert.equal(sent.purpose,'chat');assert.equal(sent.maxTokens,plan.maxTokens);assert.equal(result.contextBudget.reserveBytes,plan.outputEstimateBytes+plan.safetyBytes);assert.equal(result.contextBudget.inputEstimateBytes,estimateMessageBytes(sent.messages));assert(result.contextBudget.inputEstimateBytes<=result.contextBudget.inputLimitBytes);assert.equal(saved.messages.at(-1).content,result.reply);}finally{t.destroy();}
  }
});
await check('malformed/oversized/incomplete replies never save or automatically retry',async()=>{
  for(const bad of [raw('{"text":"unfinished'),reply('中'.repeat(12001)),raw('完整普通文字','length')]){
    let requests=0,saves=0;const t=createChatTransport({persona,sessionId:()=> 'synthetic',request:async()=>{requests++;return bad;},journal:{save:async()=>saves++}});
    try{await assert.rejects(t.send({input:'普通问题',messages:[{role:'user',content:'普通问题'}]}));assert.equal(requests,1);assert.equal(saves,0);}finally{t.destroy();}
  }
});
await check('native adapter forwards chat allowance; absent summary field stays absent for legacy500',async()=>{
  const calls=[];const request=createNativeChatRequest({request:async x=>{calls.push(x);return {data:reply('合成')};}});
  await request({id:'synthetic-chat',messages:[],maxTokens:1800});await request({id:'synthetic-summary',messages:[],purpose:'summary'});
  assert.equal(calls[0].maxTokens,1800);assert.equal(calls[0].purpose,'chat');assert.equal(calls[1].purpose,'summary');assert(!Object.hasOwn(calls[1],'maxTokens'));
});
console.log(JSON.stringify({passed:count,checks,realAPI:0,androidDevice:false,indexedDB:false}));
