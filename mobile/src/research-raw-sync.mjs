import {canonical} from './memory-records.mjs';
import {hashText,validateUse} from './research-use.mjs';
export const RESEARCH_RAW_FORMAT='gernze-phone-research-raw-v1';
const zero='0'.repeat(64),size=value=>new TextEncoder().encode(JSON.stringify(value)).length;
// Explicit paired sync only. This is an archive upload, never a model memory input.
export async function uploadPhoneResearch({journal,binding,send,eligible=()=>true,maxBatches=20,onProgress=()=>{}}){
 if(journal.researchVersion!==1||typeof journal.readResearchTurn!=='function')throw Error('研究原文需要新版手机存储。');
 const sessions=(await journal.list()).filter(s=>s.researchRanges?.length).sort((a,b)=>a.id.localeCompare(b.id));
 let batches=0,uploaded=0,total=0;
 const check=()=>{if(!eligible())throw Error('研究原文同步已暂停，回到前台后继续。');};
 for(const s of sessions){
  check();const baseStart=s.researchRanges[0].start/2;total+=s.messages.length/2-baseStart;
  const ranges=new Map(s.researchRanges.map(r=>[r.start/2,r]));
  const packet=(start,previous,turns)=>({format:RESEARCH_RAW_FORMAT,...binding,sessionId:s.id,baseStart,start,previous,turns});
  async function turn(index){
   check();let messages=s.messages.slice(index*2,index*2+2),times=s.messageTimes?.slice(index*2,index*2+2)||[null,null],receipt=null;
   if(ranges.has(index)){
    const raw=await journal.readResearchTurn(s.id,index*2);check();
    if(!raw||raw.receipt?.request?.id!==ranges.get(index).requestId||raw.start!==index*2||raw.sessionId!==s.id)throw Error('研究原文与范围标记不符，未上传。');
    messages=raw.messages;times=raw.messageTimes;receipt=raw.receipt;
    validateUse(receipt,{id:s.id,lastRequestId:receipt.request.id});
    if(receipt.cache.serverId!==binding.serverId||receipt.cache.scope_id!==binding.scope_id||await hashText(messages[0].content)!==receipt.request.inputHash)throw Error('研究原文的配对或输入来源不符，未上传。');
   }
   if(messages.length!==2||messages.some((m,i)=>m.role!==(i?'assistant':'user')||typeof m.content!=='string'||!m.content||m.content.length>12000))throw Error('研究原文不完整，未截断上传。');
   return {index,user:messages[0].content,assistant:messages[1].content,userAt:times[0]??null,assistantAt:times[1]??null,research:receipt};
  }
  const cursor=await send(packet(baseStart,zero,[]));check();
  if(cursor.format!==RESEARCH_RAW_FORMAT||cursor.sessionId!==s.id||cursor.baseStart!==baseStart||!Number.isSafeInteger(cursor.next)||cursor.next<baseStart||cursor.next>s.messages.length/2)throw Error('电脑研究原文进度不符，原资料保留。');
  let next=cursor.next,digest=zero;
  for(let i=baseStart;i<next;i++)digest=await hashText(canonical({previous:digest,turn:await turn(i)}));
  if(digest!==cursor.chain)throw Error('研究原文已变化，未覆盖电脑副本。');
  while(next<s.messages.length/2){
   if(batches>=maxBatches)return {complete:false,uploaded,total};check();
   const block=[],start=next,previous=digest;
   while(next<s.messages.length/2&&block.length<16){const row=await turn(next);if(size(packet(start,previous,[...block,row]))>520000)break;block.push(row);digest=await hashText(canonical({previous:digest,turn:row}));next++;}
   if(!block.length)throw Error('研究单轮连同来源超过上传上限，原文未截断。');check();
   const result=await send(packet(start,previous,block));check();
   if(result.format!==RESEARCH_RAW_FORMAT||result.sessionId!==s.id||result.baseStart!==baseStart||result.next!==next||result.chain!==digest)throw Error('电脑研究原文确认不一致，请重新同步。');
   uploaded+=block.length;batches++;onProgress({uploaded});
  }
 }
 return {complete:true,uploaded,total};
}
