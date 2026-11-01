import assert from 'node:assert/strict';
import {pickSummary,summaryBlocked,summaryReadiness,prepareSummary,SUMMARY_INPUT_BYTES,SUMMARY_BLOCKED_MESSAGE} from '../src/summary-policy.mjs';
let passed=0;const check=async(name,fn)=>{await fn();passed++;console.log('PASS',name);};
function fixture(body='中'.repeat(2500)){
  const old=new Date(Date.now()-8*86400000).toISOString();
  const messages=Array.from({length:20},(_,i)=>[{role:'user',content:'合成问题'+i},{role:'assistant',content:i<6?body:'最近原文'}]).flat();
  return {epoch:0,summaryEnabled:true,summaryDays:7,summaries:[],session:{id:'synthetic',contextEpoch:0,contextStart:0,messages,messageTimes:Array(messages.length).fill(old),updatedAt:old}};
}
await check('one complete long pair fits the exact16000 request despite old three-pair floor',()=>{
  const view=fixture(),raw=JSON.stringify(view.session),plan=pickSummary(view);
  assert.equal(plan.start,0);assert.equal(plan.end,2);
  assert.equal(plan.sourceText,JSON.stringify(view.session.messages.slice(0,2)));
  assert.equal(JSON.parse(plan.messages[1].content).new_block[1].content,view.session.messages[1].content);
  assert(new TextEncoder().encode(JSON.stringify(plan.messages)).length<=SUMMARY_INPUT_BYTES);
  assert.equal(JSON.stringify(view.session),raw);
});
await check('active frozen cycle drains last single pair without touching newest six',()=>{
  const view=fixture();view.summaryCycle={id:'synthetic-cycle',epoch:0,end:4};view.summaries=[{epoch:0,start:0,end:2,text:'合成摘要'}];view.summaryClock=Date.now();
  const plan=pickSummary(view);assert.equal(plan.start,2);assert.equal(plan.end,4);assert.equal(plan.cycle.end,4);assert(plan.end<=view.session.messages.length-12);
});
await check('oversized first pair is explicitly blocked and cannot skip ahead or fake a claim',async()=>{
  const view=fixture('中'.repeat(6000));let calls=0,claims=0;const notices=[];
  assert.equal(pickSummary(view),null);assert(summaryBlocked(view));assert.equal(summaryReadiness(view),SUMMARY_BLOCKED_MESSAGE);
  assert.equal(await prepareSummary({view,journal:{claimSummary:async()=>{claims++;},commitSummary:async()=>{throw Error('unexpected commit');}},request:async()=>{calls++;},cancel:()=>{},onStatus:x=>notices.push(x)}),false);
  assert.equal(calls,0);assert.equal(claims,0);assert.deepEqual(notices,[SUMMARY_BLOCKED_MESSAGE]);assert.equal(view.summaryCycle,undefined);assert.equal(view.session.messages[1].content.length,6000);
});
await check('valid prefix ends before oversized next pair and keeps the blocked cycle visible',()=>{
  const view=fixture('短合成');view.session.messages[3].content='中'.repeat(6000);
  const first=pickSummary(view);assert.equal(first.end,2);
  view.summaryCycle=first.cycle;view.summaries=[{...first,text:'合成摘要'}];view.summaryClock=Date.now();
  assert.equal(pickSummary(view),null);assert(summaryBlocked(view));assert.equal(summaryReadiness(view),SUMMARY_BLOCKED_MESSAGE);
});
await check('newest six and initial timing/count gate remain intact',()=>{
  const view=fixture();view.session.updatedAt=new Date().toISOString();view.session.messageTimes.fill(view.session.updatedAt);assert.equal(pickSummary(view),null);assert(!summaryBlocked(view));
  view.summaryEnabled=false;assert.equal(pickSummary(view),null);assert(!summaryBlocked(view));
  const short=fixture();short.session.messages=short.session.messages.slice(0,16);assert.equal(pickSummary(short),null);
});
await check('full system/wrapper escaping is counted before model request',()=>{
  const view=fixture('"\\\n'.repeat(950));const plan=pickSummary(view);assert(plan);
  assert(new TextEncoder().encode(JSON.stringify(plan.messages)).length<=SUMMARY_INPUT_BYTES);
  assert.equal(plan.sourceText,JSON.stringify(view.session.messages.slice(plan.start,plan.end)));
});
console.log(JSON.stringify({passed,realAPI:0,indexedDB:false}));
