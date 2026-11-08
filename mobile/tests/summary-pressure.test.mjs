import assert from 'node:assert/strict';
import {test} from 'node:test';
import {pickSummary,prepareSummary,SUMMARY_INPUT_BYTES} from '../src/summary-policy.mjs';
import {layersPrompt,summaryEntry} from '../src/memory-layers.mjs';

const now=new Date().toISOString();
function fixture(n=16){
 const messages=Array.from({length:n},(_,i)=>[
   {role:'user',content:i===0?'原话：确定先处理手机。':'话题'+i+'问题'.repeat(190)},
   {role:'assistant',content:'回复'+i+'正文'.repeat(400)}
 ]).flat();
 return {epoch:0,summaryEnabled:true,summaryDays:7,summaries:[],session:{id:'fixture',contextEpoch:0,contextStart:0,messages,messageTimes:messages.map(()=>now),updatedAt:now}};
}
test('fresh long session pressures earlier than timer while protecting the last six',()=>{
 const v=fixture(),before=JSON.stringify(v.session.messages);
 assert.equal(pickSummary(v),null);
 const plan=pickSummary(v,16000);
 assert.equal(plan.cycle.trigger,'pressure');
 assert(plan.cycle.end<=v.session.messages.length-12);
 assert.equal(plan.sourceText,JSON.stringify(v.session.messages.slice(plan.start,plan.end)));
 assert.equal(JSON.stringify(v.session.messages),before);
 assert.equal(pickSummary({...v,summaryEnabled:false},16000),null);
 assert.equal(pickSummary(fixture(6),16000),null);
 assert.equal(pickSummary(v,128*1024),null);
});
test('oversized pair can advance under pressure with an exact source and visible excerpt coverage',async()=>{
 const v=fixture();
 v.session.messages[0].content='前缀'.repeat(4400)+'纠正：青色。'+'末尾'.repeat(500);
 v.session.messages[1].content='很长的旧回答'.repeat(1400);
 const original=structuredClone(v.session.messages);
 let saved;
 const ok=await prepareSummary({view:v,historyRoom:16000,cancel:()=>{},journal:{commitSummary:async p=>{saved=p;return true;}},
   request:async({messages})=>{
     assert(new TextEncoder().encode(JSON.stringify(messages)).length<=SUMMARY_INPUT_BYTES);
     assert.match(JSON.parse(messages[1].content).new_block[0].content,/中间原文省略/);
     return {choices:[{message:{content:'{"text":"合成摘要"}'}}]};
   }});
 assert(ok&&saved.partial);
 assert.equal(saved.end,2);
 assert.equal(saved.sourceText,JSON.stringify(original.slice(0,2)));
 assert.match(saved.anchors[0].text,/纠正：青色/);
 assert.match(saved.text,/仅根据原文摘录/);
 assert.deepEqual(v.session.messages,original);
});
test('continuation can receive exact user excerpts without resurrecting a superseded working summary',()=>{
 const v=fixture(),p=pickSummary(v,16000),source=summaryEntry({...p,text:'摘要文本',updatedAt:now});
 const core={schemaVersion:1,entries:[{key:'core',body:'合成基础资料'}]};
 assert.match(layersPrompt({core,working:[source]}),/确定先处理手机/);
 assert.doesNotMatch(layersPrompt({core,approved:[{key:source.key,body:'已审结果'}],working:[source]}),/确定先处理手机/);
});
