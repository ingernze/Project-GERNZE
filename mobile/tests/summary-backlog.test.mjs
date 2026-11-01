import assert from 'node:assert/strict';
import {pickSummary,prepareSummary,summaryReadiness,SUMMARY_INPUT_BYTES} from '../src/summary-policy.mjs';
import {createChatTransport} from '../src/chat-core.mjs';
let passed=0;const check=async(name,fn)=>{await fn();passed++;console.log('PASS',name);};
const originalNow=Date.now;let now=Date.parse('2026-10-23T04:00:00Z');Date.now=()=>now;
const tick=()=>new Promise(r=>setTimeout(r,0));
const until=async fn=>{for(let i=0;i<100;i++){if(fn())return;await tick();}assert.fail('synthetic callback did not settle');};
const reply=text=>({choices:[{message:{content:JSON.stringify({text})},finish_reason:'stop'}]});
function fixture(turns=40){
  const old=new Date(now-8*86400000).toISOString();
  return {epoch:0,records:[],summaryDays:7,summaryEnabled:true,summaries:[],session:{id:'synthetic',contextEpoch:0,contextStart:0,messages:Array.from({length:turns},(_,i)=>[{role:'user',content:'合成问题'+i},{role:'assistant',content:'合成回答'+i}]).flat(),messageTimes:Array(turns*2).fill(old),updatedAt:old}};
}
// Scheduling harness only. Real IndexedDB claims/transactions are covered separately in the browser test.
function journalFor(view){return {context:async()=>structuredClone(view),summaries:async()=>structuredClone(view.summaries),save:async snapshot=>{view.session=structuredClone(snapshot);},claimSummary:async()=>true,commitSummary:async(plan,{signal}={})=>{
  if(signal?.aborted||plan.epoch!==view.epoch)return false;
  view.summaries.push(structuredClone(plan));view.summaryCycle=plan.cycle;
  if(!pickSummary(view)){delete view.summaryCycle;view.summaryClock=now;}return true;
}};}
const send=async(t,v)=>{const input='本轮合成输入';return t.send({input,messages:[...v.session.messages,{role:'user',content:input}]});};
try{
await check('fixed cycle bypasses clock only for old backlog; exact original pairs and last six retained',()=>{
  const v=fixture(),before=JSON.stringify(v.session.messages),first=pickSummary(v);v.summaryCycle=first.cycle;v.summaryClock=now;v.summaries=[first];
  const next=pickSummary(v);assert.equal(next.start,12);assert.equal(next.end,24);assert.equal(next.sourceText,JSON.stringify(v.session.messages.slice(12,24)));assert(next.end<=v.session.messages.length-12);
  const limit=first.cycle.end;v.session.messages.push(...fixture(20).session.messages);assert.equal(pickSummary(v).cycle.end,limit);assert.equal(JSON.stringify(v.session.messages.slice(0,80)),before);
  assert(summaryReadiness(v).includes('积压'));assert.equal(pickSummary({...v,summaryCycle:null}),null);
});
await check('full encoded input budget includes prompt, excerpts and previous summaries',()=>{
  const v=fixture();v.session.messages=v.session.messages.map(m=>({...m,content:'纠正，决定不要改为今天。'.repeat(8)}));
  v.summaries=[{epoch:0,start:0,end:6,text:'中'.repeat(2000)},{epoch:0,start:6,end:12,text:'文'.repeat(2000)}];
  const plan=pickSummary(v);assert(plan);assert(new TextEncoder().encode(JSON.stringify(plan.messages)).length<=SUMMARY_INPUT_BYTES);assert(plan.end-plan.start<=12);
});
await check('normal chat resolves before summary; two calls stop and next send resumes without a day wait',async()=>{
  const v=fixture(),journal=journalFor(v),purposes=[];let finish,held=true;
  const t=createChatTransport({persona:'合成人设',journal,sessionId:()=>v.session.id,request:p=>{purposes.push(p.purpose||'chat');if(p.purpose==='summary'&&held)return new Promise(r=>finish=r);return Promise.resolve(reply('合成回复'));}});
  try{
    assert.equal((await send(t,v)).reply,'合成回复');assert.equal(purposes[0],'chat');await until(()=>finish);assert.equal(v.summaries.length,0);
    held=false;finish(reply('合成摘要'));await until(()=>v.summaries.length===2);await tick();assert.deepEqual(purposes,['chat','summary','summary']);assert.equal(v.summaryClock,undefined);
    const end=v.summaries.at(-1).end;await send(t,v);await until(()=>v.summaries.length===4);await tick();assert.equal(v.summaries[2].start,end);assert.equal(purposes.filter(p=>p==='summary').length,4);
  }finally{t.destroy();}
});
await check('frozen cycle completes then new cycle waits seven days, including newly appended turns',async()=>{
  const v=fixture(),j=journalFor(v);let boundary;
  for(let i=0;i<10;i++){const p=pickSummary(v);if(!p)break;boundary??=p.cycle.end;v.summaryCycle=p.cycle;await j.commitSummary({...p,text:'合成摘要'});}
  assert.equal(v.summaries.at(-1).end,boundary);assert.equal(v.summaryCycle,undefined);assert.equal(v.summaryClock,now);
  v.session.messages.push(...fixture(20).session.messages);assert.equal(pickSummary(v),null);now+=6*86400000;assert.equal(pickSummary(v),null);now+=86400000;assert(pickSummary(v));
});
await check('failed model stops this send after one attempt and keeps all original text',async()=>{
  const v=fixture(),before=JSON.stringify(v.session.messages);let calls=0;
  const t=createChatTransport({persona:'合成人设',journal:journalFor(v),sessionId:()=>v.session.id,request:async p=>{if(p.purpose==='summary'){calls++;throw Error('fake offline');}return reply('合成回复');}});
  try{await send(t,v);await until(()=>calls===1);await tick();assert.equal(calls,1);assert.equal(v.summaries.length,0);assert.equal(JSON.stringify(v.session.messages.slice(0,80)),before);}finally{t.destroy();}
});
await check('new send cancels and drains summary before chat; ignored late summary never commits',async()=>{
  const v=fixture(),purposes=[];let finish,cancelled=false,summaryId;
  const t=createChatTransport({persona:'合成人设',journal:journalFor(v),sessionId:()=>v.session.id,request:p=>{purposes.push(p.purpose||'chat');if(p.purpose==='summary'){summaryId=p.id;return new Promise(r=>finish=r);}return Promise.resolve(reply('合成回复'));},cancel:id=>{if(id===summaryId){cancelled=true;finish(reply('晚到摘要'));}}});
  try{await send(t,v);await until(()=>finish);const again=send(t,v);await again;assert(cancelled);assert.equal(v.summaries.length,0);assert.deepEqual(purposes.slice(0,3),['chat','summary','chat']);}finally{t.destroy();if(finish)finish(reply('清理晚到'));}
});
await check('uncooperative native summary blocks overlapping payment with bounded busy response',async()=>{
  const v=fixture();let finish,calls=0;
  const t=createChatTransport({persona:'合成人设',journal:journalFor(v),sessionId:()=>v.session.id,request:p=>{if(p.purpose==='summary')return new Promise(r=>finish=r);calls++;return Promise.resolve(reply('合成回复'));}});
  try{await send(t,v);await until(()=>finish);await assert.rejects(send(t,v),e=>e.code==='busy');assert.equal(calls,1);assert.equal(v.summaries.length,0);}finally{t.destroy();finish(reply('晚到摘要'));await tick();}
});
for(const mode of ['cancel','destroy','disabled','epoch'])await check(mode+' prevents late summary and continuation',async()=>{
  const v=fixture();let finish,calls=0;const j=journalFor(v);
  const t=createChatTransport({persona:'合成人设',journal:j,sessionId:()=>v.session.id,request:p=>{if(p.purpose==='summary'){calls++;return new Promise(r=>finish=r);}return Promise.resolve(reply('合成回复'));}});
  try{await send(t,v);await until(()=>finish);if(mode==='epoch')v.epoch++;else if(mode==='disabled'){v.summaryEnabled=false;t.cancel();}else t[mode]();finish(reply('晚到摘要'));await tick();await tick();assert.equal(v.summaries.length,0);assert.equal(calls,1);}finally{t.destroy();}
});
await check('summary timeout cancels request and ignores its eventual response',async()=>{
  const v=fixture();let finish,cancelled=0,commits=0;
  const p=prepareSummary({view:v,journal:{commitSummary:async()=>{commits++;}},request:()=>new Promise(r=>finish=r),cancel:()=>{cancelled++;finish(reply('超时后摘要'));},timeoutMs:5});
  assert.equal(await p,false);assert.equal(cancelled,1);assert.equal(commits,0);
});
await check('missed third-layer receipt retries saved summary with zero repeated summary calls',async()=>{
  const v=fixture(12),j=journalFor(v);v.summaryEnabled=false;v.summaries=[{...pickSummary({...v,summaryEnabled:true}),text:'已有合成摘要'}];let mirrorCalls=0,summaryCalls=0;
  const t=createChatTransport({persona:'合成人设',journal:j,sessionId:()=>v.session.id,memory:{syncSummaries:async()=>{mirrorCalls++;if(mirrorCalls===1)throw Error('fake receipt failure');return {changed:true};},context:async()=>null},request:async p=>{if(p.purpose==='summary')summaryCalls++;return reply('合成回复');}});
  try{await send(t,v);await tick();await send(t,v);await tick();assert.equal(mirrorCalls,2);assert.equal(summaryCalls,0);assert.equal(v.summaries.length,1);}finally{t.destroy();}
});
console.log(JSON.stringify({passed,realAPI:0,indexedDB:false,androidDevice:false}));
}finally{Date.now=originalNow;}
