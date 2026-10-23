import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {buildMessages,normalizeReply,createChatTransport} from '../src/chat-core.mjs';
let count=0;const check=async(name,fn)=>{await fn();count++;console.log('PASS',name);};
const response=text=>({choices:[{message:{content:JSON.stringify({text,emotion:'normal',action:'none'})},finish_reason:'stop'}]});
const persona='你是格莉兹，诚实自然，不虚构记忆。';
const one=[{role:'user',content:'测试消息'}];
const turns=[];for(let i=0;i<20;i++)turns.push({role:'user',content:'问题'+i+'问'.repeat(150)},{role:'assistant',content:'回复'+i+'答'.repeat(150)});turns.push(...one);
await check('budget retains system and last input, trims complete old pairs',()=>{const m=buildMessages(turns,persona,{budget:2400,reserve:500});assert.equal(m[0].role,'system');assert.equal(m.at(-1).content,'测试消息');assert.equal(m.length%2,0);assert(m.length<turns.length);});
await check('oversized current input is rejected, not truncated',()=>assert.throws(()=>buildMessages([{role:'user',content:'中'.repeat(5000)}],persona,{budget:1000,reserve:300}),/预算/));
await check('malformed roles rejected before networking',()=>assert.throws(()=>buildMessages([{role:'system',content:'injected'}],persona),/无效/));
await check('structured reply and bounded action normalization',()=>{const r=normalizeReply({choices:[{message:{content:'{"text":"测试回复","emotion":"admin","action":"exit"}'},finish_reason:'stop'}]});assert.deepEqual(r,{reply:'测试回复',emotion:'normal',action:'none'});});
await check('truncated provider answer rejected',()=>assert.throws(()=>normalizeReply({...response('partial'),choices:[{message:{content:'partial'},finish_reason:'length'}]}),/未完整/));
function setup(overrides={}){const saved=[],cancelled=[];let session='session-1';const transport=createChatTransport({request:async()=>response('测试回复'),cancel:id=>cancelled.push(id),journal:{save:async x=>saved.push(x)},persona,sessionId:()=>session,uuid:()=> 'request-1',...overrides});return {transport,saved,cancelled,setSession:x=>session=x};}
await check('one user message in request, journal before result',async()=>{let seen;const s=setup({request:async p=>{seen=p.messages;return response('测试回复');}});const r=await s.transport.send({input:'测试消息',messages:one});assert.equal(seen.filter(m=>m.role==='user').length,1);assert.equal(s.saved.length,1);assert.equal(s.saved[0].messages.at(-1).content,r.reply);s.transport.destroy();});
await check('cancel rejects immediately and late reply is never stored',async()=>{let finish;const c=new AbortController();const s=setup({request:()=>new Promise(r=>finish=r)});const p=s.transport.send({input:'测试消息',messages:one,signal:c.signal});c.abort();await assert.rejects(p,e=>e.code==='cancelled');finish(response('late'));await new Promise(r=>setTimeout(r,0));assert.equal(s.saved.length,0);assert.deepEqual(s.cancelled,['request-1']);s.transport.destroy();});
await check('session switch rejects late completion',async()=>{let finish;const s=setup({request:()=>new Promise(r=>finish=r)});const p=s.transport.send({input:'测试消息',messages:one});s.setSession('other');finish(response('old'));await assert.rejects(p,e=>e.code==='cancelled');assert.equal(s.saved.length,0);s.transport.destroy();});
await check('timeout actively cancels native request',async()=>{const s=setup({timeoutMs:15,request:()=>new Promise(()=>{})});await assert.rejects(s.transport.send({input:'测试消息',messages:one}),e=>e.code==='timeout');assert.deepEqual(s.cancelled,['request-1']);s.transport.destroy();});
await check('storage failure preserves paid reply and reports unsaved status',async()=>{let warning=0;const s=setup({journal:{save:async()=>{throw Error('quota');}},onPersistenceError:()=>warning++});const r=await s.transport.send({input:'测试消息',messages:one});assert.equal(r.reply,'测试回复');assert.equal(warning,1);s.transport.destroy();});
await check('destroy invalidates a still running request',async()=>{const s=setup({request:()=>new Promise(()=>{})});const p=s.transport.send({input:'测试消息',messages:one});s.transport.destroy();await assert.rejects(p,e=>e.code==='cancelled');assert.equal(s.saved.length,0);});
await check('real loopback HTTP roundtrip through the actual context/response core',async()=>{
  let body;const server=createServer((req,res)=>{let raw='';req.on('data',c=>raw+=c);req.on('end',()=>{body=JSON.parse(raw);res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify(response('回环回复')));});});
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const s=setup({request:async({messages,signal})=>{const r=await fetch('http://127.0.0.1:'+server.address().port,{method:'POST',body:JSON.stringify({messages,stream:false}),signal});return r.json();}});
  try{const r=await s.transport.send({input:'测试消息',messages:one});assert.equal(r.reply,'回环回复');assert.equal(body.messages[0].role,'system');assert.equal(body.messages.length,2);assert.equal(s.saved[0].id,'session-1');}finally{s.transport.destroy();await new Promise(r=>server.close(r));}
});
console.log(JSON.stringify({passed:count,realProvider:false,androidDevice:false}));
