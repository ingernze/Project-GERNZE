import {createChatJournal} from '../src/chat-journal.mjs';
import {createResearchUse,hashText} from '../src/research-use.mjs';
import {createChatTransport} from '../src/chat-core.mjs';
import {uploadPhoneRaw} from '../src/raw-sync.mjs';
import {uploadPhoneResearch,RESEARCH_RAW_FORMAT} from '../src/research-raw-sync.mjs';
import {canonical} from '../src/memory-records.mjs';
export async function run(packets){
 const checks=[],check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);},deny=async fn=>{try{await fn();return false;}catch{return true;}},sample=packets.find(p=>p.records.some(r=>r.restriction==='general'));
 const binding={serverId:sample.serverId,scope_id:sample.scope_id},general=sample.records.find(r=>r.restriction==='general'),name='synthetic-research-raw-'+crypto.randomUUID(),journal=createChatJournal({name});
 const zero='0'.repeat(64),pair=(q,a)=>[{role:'user',content:q},{role:'assistant',content:a}],stamp='2026-10-27T00:00:00Z',sid='cross-language-phone';
 let reads=0;const get=IDBObjectStore.prototype.get;IDBObjectStore.prototype.get=function(...args){if(this.name==='researchMessages')reads++;return get.apply(this,args);};
 const wire=[],states=new Map();let loseAck=false;
 const send=async p=>{
  wire.push(structuredClone(p));const research=p.format===RESEARCH_RAW_FORMAT,key=p.format+':'+p.sessionId,base=research?p.baseStart:0,state=states.get(key)||{next:base,chain:zero,rows:[]};
  if(p.turns.length){if(p.start!==state.next||p.previous!==state.chain)throw Error('synthetic server chain mismatch');for(const row of p.turns){state.chain=await hashText(canonical({previous:state.chain,turn:row}));state.rows.push(structuredClone(row));state.next++;}states.set(key,state);if(loseAck&&research){loseAck=false;throw Error('synthetic lost acknowledgement');}}
  return {format:p.format,serverId:binding.serverId,sessionId:p.sessionId,...research?{baseStart:base}:{},next:state.next,chain:state.chain,accepted:p.turns.length};
 };
 let transport,panel;
 try{
  await journal.researchCache.apply(sample,binding);await journal.setting('summaryEnabled',false);await journal.setting('layerSyncEnabled',false);
  await journal.save({id:sid,messages:pair('PLAIN_PREFIX','PLAIN_REPLY'),messageTimes:[stamp,stamp],updatedAt:stamp});
  const use=createResearchUse({cache:journal.researchCache});await use.select({id:general.id,revision:general.revision,sessionId:sid});
  let count=0;transport=createChatTransport({journal,research:use,sessionId:()=>sid,persona:'合成联调人设',request:async()=>({choices:[{finish_reason:'stop',message:{content:JSON.stringify({text:++count===1?'PHONE_RESEARCH_ANSWER':'PLAIN_AFTER_ANSWER'})}}]})});
  const input='RESEARCH_QUOTE "\\ 中文🙂\n新行';await transport.send({input,messages:[...pair('PLAIN_PREFIX','PLAIN_REPLY'),{role:'user',content:input}]});
  const stored=await journal.load();await transport.send({input:'PLAIN_AFTER_RESEARCH',messages:[...stored.messages,{role:'user',content:'PLAIN_AFTER_RESEARCH'}]});
  const before=reads,plain=await uploadPhoneRaw({journal,send});check(plain.researchDeferred===1&&plain.uploaded===1&&reads===before,'legacy uploader reads no research raw and sends only stable prefix');
  check(!JSON.stringify(wire).includes('PHONE_RESEARCH_ANSWER'),'research answer absent from ordinary channel');
  const r=await uploadPhoneResearch({journal,binding,send});check(r.complete&&r.uploaded===2,'new uploader sends research and later plain tail');
  const rows=states.get(RESEARCH_RAW_FORMAT+':'+sid).rows;check(rows[0].index===1&&rows[1].index===2&&rows[1].research===null,'original positions and ordinary-tail distinction preserved');
  check(rows[0].user===input&&rows[0].research.request.inputHash===await hashText(input)&&rows[0].research.source.raw_refs,'exact escaped input and complete host receipt uploaded together');
  check(!('body' in rows[0].research.source)&&!JSON.stringify(wire).includes('API_KEY'),'upload includes receipt metadata, no summary body or credential field');
  const again=await uploadPhoneResearch({journal,binding,send});check(again.uploaded===0&&states.get(RESEARCH_RAW_FORMAT+':'+sid).rows.length===2,'confirmed cursor resume never duplicates completed rows');
  window.__stage9Wire=wire.filter(p=>p.turns.length); // Independent Python receiver replays these exact packets.

  const wireLength=wire.length,readCount=reads;check(await deny(()=>uploadPhoneResearch({journal,binding,send,eligible:()=>false}))&&wire.length===wireLength&&reads===readCount,'background gate prevents body read and network post');
  check(await deny(()=>uploadPhoneResearch({journal:{...journal,researchVersion:0},binding,send})),'old journal cannot accidentally opt into attributed upload');
  const noBudget=await uploadPhoneResearch({journal,binding,send:async p=>({format:p.format,sessionId:p.sessionId,baseStart:p.baseStart,next:p.baseStart,chain:zero}),maxBatches:0});check(!noBudget.complete&&noBudget.uploaded===0,'bounded upload reports incomplete without a false success');
  const wrong=await deny(()=>uploadPhoneResearch({journal,binding:{...binding,serverId:crypto.randomUUID()},send:async p=>({format:p.format,sessionId:p.sessionId,baseStart:p.baseStart,next:p.baseStart,chain:zero})}));check(wrong,'foreign pairing receipt rejected before any text batch is sent');
  check(await deny(()=>uploadPhoneResearch({journal,binding,send:async p=>({format:p.format,sessionId:p.sessionId,baseStart:p.baseStart,next:999,chain:zero})})),'out-of-range receiver cursor rejected');
  check(await deny(()=>uploadPhoneResearch({journal,binding,send:async p=>({format:p.format,sessionId:p.sessionId,baseStart:p.baseStart,next:3,chain:zero})})),'mismatched confirmed chain rejected without overwrite');
  const savedState=states.get(RESEARCH_RAW_FORMAT+':'+sid);states.delete(RESEARCH_RAW_FORMAT+':'+sid);loseAck=true;
  check(await deny(()=>uploadPhoneResearch({journal,binding,send})),'lost response after receiver commit reports failure');
  const resumed=await uploadPhoneResearch({journal,binding,send});check(resumed.complete&&resumed.uploaded===0&&states.get(RESEARCH_RAW_FORMAT+':'+sid).rows.length===2,'retry after lost acknowledgement trusts verified committed cursor');states.set(RESEARCH_RAW_FORMAT+':'+sid,savedState);

  // The actual sync button negotiates before choosing the new payload format.
  await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='/sync-bundle.js';script.onload=resolve;script.onerror=reject;document.head.append(script);});
  const host=document.getElementById('host');let advertised=false,failResearch=false,sequence=sample.sequence+1;
  window.__native={layerInfo:async()=>({...binding,reviewOn:'desktop',phoneRaw:'gernze-phone-raw-v1',researchCache:'gernze-research-cache-v1',phoneResearchRaw:advertised?RESEARCH_RAW_FORMAT:null}),rawExchange:async({request})=>{if(failResearch&&request.format===RESEARCH_RAW_FORMAT)throw Error('synthetic research upload failed');return send(request);},layerExchange:async()=>({serverId:binding.serverId,packet:{synthetic:true},conflicts:[],research:{...structuredClone(sample),sequence:sequence++}})};
  localStorage.setItem('hebao.updates.v1',JSON.stringify({pair:{pairingId:crypto.randomUUID()}}));
  panel=await window.Stage9Sync.mountMemorySync({container:host,journal,layers:{research:journal.researchCache,sync:{export:async()=>({packet:{synthetic:true},rowsSignature:'synthetic'}),apply:async()=>{},conflicts:async()=>null}}});
  const click=async()=>{host.querySelector('[data-now]').click();for(let i=0;i<200&&host.querySelector('[data-now]').disabled;i++)await new Promise(r=>setTimeout(r,10));if(host.querySelector('[data-now]').disabled)throw Error('sync not settled');};
  await journal.setting('layerLastSync',0);const oldReads=reads;await click();check(reads===oldReads&&host.textContent.includes('电脑尚不支持带来源研究原文')&&await journal.setting('layerLastSync')===0,'old desktop capability keeps research local, reads no body, reports partial state');
  advertised=true;await click();check(host.textContent.includes('研究原文与来源已独立归档')&&await journal.setting('layerLastSync')>0,'new capability reports success only after attributed upload confirmation');
  failResearch=true;await journal.setting('layerLastSync',0);await click();check(host.textContent.includes('synthetic research upload failed')&&await journal.setting('layerLastSync')===0,'failed research channel never updates full sync success time');
  check(host.textContent.includes('第一层与密钥不传'),'existing paired memory boundary remains visible');
  return checks;
 }finally{transport?.destroy();panel?.destroy();IDBObjectStore.prototype.get=get;await journal.close();await new Promise((resolve,reject)=>{const r=indexedDB.deleteDatabase(name);r.onsuccess=resolve;r.onerror=()=>reject(r.error);});}
}
