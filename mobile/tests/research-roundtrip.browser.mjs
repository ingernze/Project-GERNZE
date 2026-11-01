import {createChatJournal} from '../src/chat-journal.mjs';
import {createResearchUse} from '../src/research-use.mjs';
import {createChatTransport} from '../src/chat-core.mjs';
import {uploadPhoneResearch} from '../src/research-raw-sync.mjs';
export async function run(config){
 const checks=[],ok=(v,label)=>{if(!v)throw Error(label);checks.push(label);};
 const post=async(op,body={})=>{const r=await fetch('/fixture/'+op,{method:'POST',headers:{Authorization:'Bearer '+config.key,'Content-Type':'application/json'},body:JSON.stringify(body)});const value=await r.json();if(!r.ok)throw Error(JSON.stringify(value));return value;};
 const exchange=()=>post('layers',{snapshot:config.snapshot,capabilities:['gernze-research-cache-v2']});
 const name='synthetic-roundtrip-'+crypto.randomUUID(),sessionId='synthetic-phone';let journal=createChatJournal({name}),transport;
 try{
  await journal.setting('summaryEnabled',false);await journal.setting('layerSyncEnabled',false);
  let cache=journal.researchCache,packet=await exchange();await cache.apply(packet.research,config.binding);
  ok(packet.research.format==='gernze-research-cache-v2','real paired TLS negotiates v2');
  let records=await cache.list();const root=records.find(r=>r.restriction==='general'&&!r.phone_refs.length);
  ok(root?.review.status==='supported'&&!JSON.stringify(packet).includes('SYNTHETIC_COURSE_DO_NOT_SEND'),'desktop reviewed root arrives without course body');
  const use=createResearchUse({cache});let sent=[];
  transport=createChatTransport({journal,research:use,persona:'合成人设',sessionId:()=>sessionId,request:async p=>{sent.push(p);return {choices:[{finish_reason:'stop',message:{content:JSON.stringify({text:'SYNTHETIC_PHONE_ANSWER_'+sent.length})}}]};}});
  for(let i=0;i<12;i++){
   await use.select({id:root.id,revision:root.revision,sessionId});
   const input='PHONE_ROUNDTRIP_Q'+i,previous=await journal.load();
   const reply=await transport.send({input,messages:[...(previous?.messages||[]),{role:'user',content:input}]});
   if(reply.researchUse.status!=='used')throw Error('selected source not used');
  }
  ok(sent.length===12&&sent.every(p=>p.messages[0].content.includes('SYNTHETIC_DESKTOP_ROOT')),'actual phone request builder uses the selected desktop summary');
  ok(!JSON.stringify(sent).includes('SYNTHETIC_COURSE_DO_NOT_SEND'),'ordinary phone requests exclude course body');
  const uploaded=await uploadPhoneResearch({journal,binding:config.binding,send:p=>post('raw',p)});
  ok(uploaded.complete&&uploaded.uploaded===12,'12 attributed phone originals traverse real TLS receiver');
  const replay=await uploadPhoneResearch({journal,binding:config.binding,send:p=>post('raw',p)});
  ok(replay.complete&&replay.uploaded===0,'acknowledged replay adds no duplicate originals');
  const result=await post('derive');ok(result.researchTypes.phone===1&&result.userFactsWritten===0,'desktop summarizes and independently reviews without writing user facts');
  packet=await exchange();await cache.apply(packet.research,config.binding);records=await cache.list();const derived=records.find(r=>r.phone_refs.length);
  ok(derived?.phone_refs.length===3&&derived.review.status==='supported'&&derived.trust==='research_summary','derived phone summary returns with exact provenance and research identity');
  ok((await cache.read(derived.id,derived.revision)).body==='SYNTHETIC_PHONE_DERIVED','derived body survives the complete downlink');
  transport.destroy();transport=null;await journal.close();journal=createChatJournal({name});cache=journal.researchCache;
  ok((await journal.readResearchTurn(sessionId,0)).messages[0].content==='PHONE_ROUNDTRIP_Q0','phone database reopen retains attributed originals');
  await post('restart');packet=await exchange();await cache.apply(packet.research,config.binding);
  ok((await cache.list()).some(r=>r.id===derived.id&&r.review.status==='supported'),'desktop and publisher restart retain review and pairing');
  const pending=createResearchUse({cache});await pending.select({id:derived.id,revision:derived.revision,sessionId});
  const withdrawn=await post('withdraw',{sessionId});packet=await exchange();await cache.apply(packet.research,config.binding);
  ok(withdrawn.rawKept&&withdrawn.state==='changed','withdrawal preserves archived originals and marks changed source');
  ok(!(await cache.list()).some(r=>r.restriction==='general'),'next complete snapshot removes withdrawn root and derived summary');
  let denied=false;try{await pending.claim({id:crypto.randomUUID(),sessionId,input:'synthetic',origin:'user'});}catch{denied=true;}
  ok(denied,'withdrawn selection cannot enter the next request');
  return checks;
 }finally{transport?.destroy();await journal.close();await new Promise((resolve,reject)=>{const r=indexedDB.deleteDatabase(name);r.onsuccess=resolve;r.onerror=()=>reject(r.error);});}
}
