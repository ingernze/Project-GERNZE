import {createChatJournal} from '../src/chat-journal.mjs';
import {mountResearchCache} from '../src/research-cache.mjs';
import {createResearchUse} from '../src/research-use.mjs';
export async function run(packets){
 const checks=[],ok=(v,label)=>{if(!v)throw Error(label);checks.push(label);};
 const take=label=>structuredClone(packets.find(p=>p.case===label).snapshot);
 const name='synthetic-phone-review-'+crypto.randomUUID(),journal=createChatJournal({name}),cache=journal.researchCache;
 const host=document.getElementById('host');let ui,reads=0;const get=IDBObjectStore.prototype.get;
 IDBObjectStore.prototype.get=function(...args){if(this.name==='bodies')reads++;return get.apply(this,args);};
 try{
  const supported=take('supported'),binding={serverId:supported.serverId,scope_id:supported.scope_id};
  const derived=supported.records.find(r=>r.phone_refs.length);let sequence=200;
  const apply=async p=>{p.serverId=binding.serverId;p.scope_id=binding.scope_id;p.sequence=sequence++;return cache.apply(p,binding);};
  await apply(supported);ui=mountResearchCache({container:host,cache,onSelect:()=>{}});await ui.ready;
  ok(host.textContent.includes('与所附输入相符')&&host.textContent.includes('手机原文 3 轮'),'supported phone summary displays input-match and original provenance');
  ok(reads===0,'reviewed directory reads no bodies');
  const metadata=await cache.metadata(derived.id,derived.revision);
  ok(metadata.trust==='research_summary'&&metadata.review.status==='supported','supported remains research trust, not approved user memory');
  const use=createResearchUse({cache});await use.select({id:derived.id,revision:derived.revision,sessionId:'phone-review'});
  ok(reads===0,'selection reads metadata only');
  // Distinct fixtures have distinct ids. Keep the selected real source and change
  // only its review metadata to model the same source receiving a later verdict.
  const deferred=structuredClone(supported);deferred.records.find(r=>r.id===derived.id).review={status:'defer',reason:'输入不足，保留待核对'};
  await apply(deferred);await ui.refresh();
  ok(host.textContent.includes('保留待核对'),'defer label arrives through the same cache');
  const before=reads;let denied=false;
  try{await use.claim({id:crypto.randomUUID(),sessionId:'phone-review',input:'synthetic',origin:'user'});}catch{denied=true;}
  ok(denied&&reads===before,'review snapshot change invalidates pending use before body');
  const record=await cache.read(derived.id,derived.revision);
  ok(record.review.status==='defer'&&record.trust==='research_summary'&&record.body===derived.body,'deferred body stays intact and low trust');
  const rejected=structuredClone(supported);rejected.records=rejected.records.filter(r=>r.id!==derived.id);await apply(rejected);await ui.refresh();
  ok(!(await cache.list()).some(r=>r.id===derived.id),'rejection removes derived summary in complete replacement');
  // Also validate the exact defer and rejection packets emitted by Python.
  await apply(take('defer'));ok((await cache.list()).some(r=>r.phone_refs.length&&r.review.status==='defer'),'actual Python defer packet is accepted');
  await apply(take('rejected'));ok(!(await cache.list()).some(r=>r.phone_refs.length),'actual Python rejected packet contains no rejected phone body');
  return checks;
 }finally{ui?.destroy();IDBObjectStore.prototype.get=get;await journal.close();await new Promise((resolve,reject)=>{const r=indexedDB.deleteDatabase(name);r.onsuccess=resolve;r.onerror=()=>reject(r.error);});}
}
