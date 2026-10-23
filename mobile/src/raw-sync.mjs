import {canonical} from './memory-records.mjs';
const format='gernze-phone-raw-v1',zero='0'.repeat(64);
const hash=async value=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonical(value)))),b=>b.toString(16).padStart(2,'0')).join('');
const size=v=>new TextEncoder().encode(JSON.stringify(v)).length;
export async function uploadPhoneRaw({journal,send,eligible=()=>true,onProgress=()=>{},maxBatches=20}){
 const sessions=(await journal.list()).filter(s=>s.messages.length).sort((a,b)=>a.id.localeCompare(b.id));let batches=0,uploaded=0,total=0;
 for(const s of sessions){
  total+=s.messages.length/2;if(!eligible())throw Error('已暂停，回到前台后继续同步原文。');
  const turn=i=>({index:i,user:s.messages[i*2].content,assistant:s.messages[i*2+1].content,userAt:s.messageTimes?.[i*2]??null,assistantAt:s.messageTimes?.[i*2+1]??null});
  const packet=(start,previous,turns)=>({format,sessionId:s.id,start,previous,turns});
  const cursor=await send(packet(0,zero,[]));
  if(cursor.format!==format||cursor.sessionId!==s.id||!Number.isSafeInteger(cursor.next)||cursor.next<0||cursor.next>s.messages.length/2)throw Error('电脑原文进度与手机不一致，原资料保留，请核对。');
  let next=cursor.next,digest=zero;
  for(let i=0;i<next;i++)digest=await hash({previous:digest,turn:turn(i)});
  if(digest!==cursor.chain)throw Error('这段原文已变化，未覆盖电脑已有副本，请在电脑核对。');
  while(next<s.messages.length/2){
   if(batches>=maxBatches)return {complete:false,uploaded};
   if(!eligible())throw Error('已暂停，回到前台后继续同步原文。');
   const block=[],start=next,previous=digest;
   while(next<s.messages.length/2&&block.length<64){const row=turn(next);if(size(packet(start,previous,[...block,row]))>520000)break;block.push(row);digest=await hash({previous:digest,turn:row});next++;}
   if(!block.length)throw Error('原文单轮超过传输限制，未截断或删除。');
   const result=await send(packet(start,previous,block));
   if(result.format!==format||result.sessionId!==s.id||result.next!==next||result.chain!==digest)throw Error('电脑原文确认不一致，请重新同步。');
   uploaded+=block.length;batches++;onProgress({uploaded});
  }
 }
 return {complete:true,uploaded,total};
}
