import {createChatJournal} from '../src/chat-journal.mjs';
import {validateResearchCache,mountResearchCache} from '../src/research-cache.mjs';
import {createResearchUse} from '../src/research-use.mjs';
import {createChatTransport} from '../src/chat-core.mjs';
import {uploadPhoneResearch} from '../src/research-raw-sync.mjs';
import {hashText} from '../src/research-use.mjs';
import {canonical} from '../src/memory-records.mjs';
export async function run(packets){
 const checks=[],ok=(v,label)=>{if(!v)throw Error(label);checks.push(label);},deny=async fn=>{try{await fn();return false;}catch{return true;}};
 const sample=packets.find(p=>p.format==='gernze-research-cache-v2'&&p.records.some(r=>r.phone_refs.length));if(!sample)throw Error('missing real Python v2 packet');
 const packet=n=>({...structuredClone(sample),sequence:n}),binding={serverId:sample.serverId,scope_id:sample.scope_id},derived=sample.records.find(r=>r.phone_refs.length);
 const name='synthetic-phone-summary-'+crypto.randomUUID(),journal=createChatJournal({name}),cache=journal.researchCache,host=document.getElementById('host');
 let bodyReads=0;const get=IDBObjectStore.prototype.get;IDBObjectStore.prototype.get=function(...args){if(this.name==='bodies')bodyReads++;return get.apply(this,args);};let ui,sync,transport;
 try{
  await cache.apply(packet(100),binding);await journal.setting('summaryEnabled',false);await journal.setting('layerSyncEnabled',false);
  ok((await cache.list()).some(r=>r.phone_refs.length===3)&&bodyReads===0,'Python derived summary and phone provenance cached without body reads');
  const use=createResearchUse({cache});await use.select({id:derived.id,revision:derived.revision,sessionId:'derived-use'});ok(bodyReads===0,'selecting phone-derived summary reads metadata only');
  let sent;transport=createChatTransport({journal,research:use,persona:'合成人设',sessionId:()=> 'derived-use',request:async p=>{sent=p;return {choices:[{finish_reason:'stop',message:{content:'{"text":"SYNTHETIC_DERIVED_ANSWER"}'}}]};}});
  const result=await transport.send({input:'SYNTHETIC_DERIVED_Q',messages:[{role:'user',content:'SYNTHETIC_DERIVED_Q'}]});
  ok(result.researchUse.status==='used'&&sent.messages[0].content.includes(derived.body),'actual chat uses selected phone-derived summary');
  const raw=await journal.readResearchTurn('derived-use',0);ok(raw.receipt.format==='gernze-phone-research-use-v2'&&canonical(raw.receipt.source.phone_refs)===canonical(derived.phone_refs),'saved receipt v2 keeps exact original phone refs');
  let digest='0'.repeat(64),next=0;const wire=[];
  const send=async p=>{wire.push(structuredClone(p));for(const turn of p.turns){digest=await hashText(canonical({previous:digest,turn}));next++;}return {format:p.format,sessionId:p.sessionId,baseStart:p.baseStart,next,chain:digest,serverId:binding.serverId};};
  const uploaded=await uploadPhoneResearch({journal,binding,send});ok(uploaded.complete&&wire.find(p=>p.turns.length).turns[0].research.format==='gernze-phone-research-use-v2','derived summary use returns through existing attributed raw uploader');
  window.__phoneSummaryWire=wire.filter(p=>p.turns.length);
  const loaded=await journal.load();await transport.send({input:'ORDINARY_NEXT',messages:[...loaded.messages,{role:'user',content:'ORDINARY_NEXT'}]});
  ok(!JSON.stringify(sent).includes('SYNTHETIC_DERIVED_ANSWER')&&!sent.messages[0].content.includes(derived.body),'ordinary next question excludes derived answer and body');transport.destroy();
  const malformed=packet(101);malformed.records.find(r=>r.phone_refs.length).phone_refs[0].index=-1;
  ok(await deny(()=>cache.apply(malformed,binding))&&(await cache.state()).sequence===100,'invalid original phone position rejects whole snapshot');
  const duplicated=packet(101);const d=duplicated.records.find(r=>r.phone_refs.length);d.phone_refs.push(structuredClone(d.phone_refs[0]));ok(await deny(()=>cache.apply(duplicated,binding)),'duplicate phone source refs rejected');
  const course=packet(101);const c=course.records.find(r=>r.phone_refs.length);c.restriction='study';c.courses=[crypto.randomUUID()];c.sources.forEach(s=>{s.restriction='study';s.courses=c.courses;});c.body=null;ok(await deny(()=>cache.apply(course,binding)),'course metadata cannot smuggle general phone-derived refs');
  const legacy={...packet(101),format:'gernze-research-cache-v1',records:sample.records.map(({phone_refs,...r})=>r)};
  ok(await deny(()=>cache.apply(legacy,binding))&&(await cache.state()).format==='gernze-research-cache-v2','v1 downgrade cannot silently delete stored v2 provenance');
  const oldReader=await new Promise(resolve=>{const r=indexedDB.open(name,4);r.onerror=()=>resolve(r.error.name);r.onsuccess=()=>{r.result.close();resolve('bad');};});ok(oldReader==='VersionError','journal v5 fences older v4 research readers');
  ui=mountResearchCache({container:host,cache,onSelect:()=>{}});await ui.ready;ok(host.textContent.includes('手机原文 3 轮'),'research directory explicitly labels phone-derived summary');ui.destroy();
  await use.select({id:derived.id,revision:derived.revision});await cache.apply({...packet(102),records:[]},binding);const reads=bodyReads;
  ok(await deny(()=>use.claim({id:crypto.randomUUID(),sessionId:'new',input:'q',origin:'user'}))&&bodyReads===reads,'withdrawal invalidates pending selection before reading any body');
  await cache.apply(packet(103),binding);
  await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='/sync-bundle.js';script.onload=resolve;script.onerror=reject;document.head.append(script);});
  let wrong=false,observed;window.__native={layerInfo:async()=>({...binding,reviewOn:'desktop',phoneRaw:'gernze-phone-raw-v1',phoneResearchRaw:'gernze-phone-research-raw-v1',researchCache:'gernze-research-cache-v1',researchCacheV2:'gernze-research-cache-v2'}),rawExchange:async({request})=>{
   if(request.format==='gernze-phone-raw-v1')return {format:request.format,sessionId:request.sessionId,next:0,chain:'0'.repeat(64),serverId:binding.serverId};
   return {format:request.format,sessionId:request.sessionId,baseStart:request.baseStart,next:request.start+request.turns.length,chain:request.turns.length?await request.turns.reduce(async(p,t)=>hashText(canonical({previous:await p,turn:t})),Promise.resolve(request.previous)):request.previous,serverId:binding.serverId};
  },layerExchange:async({request})=>{observed=request.capabilities;return {serverId:binding.serverId,packet:{synthetic:true},conflicts:[],research:wrong?legacy:packet(104)};}};
  localStorage.setItem('hebao.updates.v1',JSON.stringify({pair:{pairingId:crypto.randomUUID()}}));
  sync=await window.Stage10Sync.mountMemorySync({container:host,journal,layers:{research:cache,sync:{export:async()=>({packet:{synthetic:true},rowsSignature:'synthetic'}),apply:async()=>{},conflicts:async()=>null}}});
  const click=async()=>{host.querySelector('[data-now]').click();for(let i=0;i<200&&host.querySelector('[data-now]').disabled;i++)await new Promise(r=>setTimeout(r,10));if(host.querySelector('[data-now]').disabled)throw Error('sync not settled');};
  await click();ok(canonical(observed)==='["gernze-research-cache-v2"]'&&(await cache.state()).sequence===104,'actual sync adapter explicitly negotiates v2: '+host.textContent);
  wrong=true;await journal.setting('layerLastSync',0);await click();ok(await journal.setting('layerLastSync')===0&&(await cache.state()).format==='gernze-research-cache-v2'&&host.textContent.includes('未返回完整研究资料'),'wrong negotiated version is not marked synchronized');
  return checks;
 }finally{ui?.destroy();sync?.destroy();transport?.destroy();IDBObjectStore.prototype.get=get;await journal.close();await new Promise((resolve,reject)=>{const r=indexedDB.deleteDatabase(name);r.onsuccess=resolve;r.onerror=()=>reject(r.error);});}
}
