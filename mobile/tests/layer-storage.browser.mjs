export async function run(){
 const {createLayeredMemory}=await import('../src/memory-layer-store.mjs');
 const {canonical,revisionNode}=await import('../src/memory-records.mjs');
 const {createChatJournal}=await import('../src/chat-journal.mjs');
 const core={schemaVersion:1,entries:[]},reports=[];
 const check=(value,label)=>{if(!value)throw Error(label);reports.push(label);};
 const summary=text=>({id:'summary',sessionId:'session',epoch:0,start:0,end:2,text,updatedAt:'2026-10-20T00:00:00Z'});
 const hash=async p=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonical(p)))),b=>b.toString(16).padStart(2,'0')).join('');
 async function conflict(base){const packet=structuredClone(base.packet),old=packet.graph.records[0],payload=structuredClone(packet.payloads[old.revision]);payload.entry.body='CONFLICT_B';payload.entry.revision=crypto.randomUUID();const row={...old,revision:payload.entry.revision,device_id:crypto.randomUUID(),body:await hash(payload)};packet.graph.records.push(row);packet.graph.revisions.push(await revisionNode(row));packet.payloads[row.revision]=payload;return {packet,conflicts:[{id:row.id}],fingerprint:'SYNTHETIC'};}
 function seed(name,stores,rows){return new Promise((resolve,reject)=>{const r=indexedDB.open(name,1);r.onupgradeneeded=()=>{for(const n of stores)r.result.createObjectStore(n,n==='entries'?{keyPath:'key'}:undefined);};r.onerror=()=>reject(r.error);r.onsuccess=()=>{const db=r.result,t=db.transaction(stores,'readwrite');for(const [store,value,key]of rows)key===undefined?t.objectStore(store).put(value):t.objectStore(store).put(value,key);t.oncomplete=()=>{db.close();resolve();};t.onabort=()=>{db.close();reject(t.error);};};});}
 const migrated='migration-'+crypto.randomUUID(),key='summary:summary',revision=crypto.randomUUID();
 await seed(migrated+'-approved',['entries','meta'],[['meta',7,'reviewDays']]);
 await seed(migrated+'-working',['entries','meta'],[['entries',{key,revision,body:'LEGACY_WORKING',updatedAt:'2026-10-20T00:00:00Z',sourceSessionId:'session',sourceSummaryId:'summary',sourceEpoch:0}]]);
 let layers=createLayeredMemory({core,namespace:migrated});
 check((await layers.review.list()).pending[0].body==='LEGACY_WORKING','legacy L3 migrated without data loss');await layers.close();
 layers=createLayeredMemory({core,namespace:migrated});check((await layers.review.list()).pending.length===1,'migration is idempotent');
 check(await new Promise(resolve=>{const r=indexedDB.open(migrated+'-approved',1);r.onerror=()=>resolve(r.error.name==='VersionError');r.onsuccess=()=>{r.result.close();resolve(false);};}),'v1 writer fenced by schema version');await layers.close();
 // Two independent runtimes have distinct in-process queues; only DB transactions serialize them.
 const namespace='cross-tab-'+crypto.randomUUID(),a=createLayeredMemory({core,namespace}),b=createLayeredMemory({core,namespace});
 const scope=crypto.randomUUID(),serverId=crypto.randomUUID(),binding={scope_id:scope,serverId};
 try{
  await a.chat.syncSummaries([summary('CONFLICT_A')]);const cached=(await a.review.list()).pending[0],base=await a.sync.export(scope),result={...await conflict(base),serverId};
  await b.sync.apply(result,binding,base.rowsSignature);
  let error;try{await a.review.decide([{key:cached.key,revision:cached.revision,action:'approve'}]);}catch(e){error=e.message;}
  check(Boolean(error)&&(await a.review.list()).approved.length===0,'phone cannot approve even with a cached pre-conflict decision');
 }finally{await a.close();await b.close();}
 const ns='sync-cas-'+crypto.randomUUID(),c=createLayeredMemory({core,namespace:ns}),d=createLayeredMemory({core,namespace:ns});
 try{
  await c.chat.syncSummaries([summary('LOCAL_A')]);const base=await c.sync.export(scope),result={...await conflict(base),serverId},cached=(await c.review.list()).pending[0];
  const digest=crypto.subtle.digest.bind(crypto.subtle);let release,entered;const waiting=new Promise(r=>entered=r),held=new Promise(r=>release=r);let first=true;
  crypto.subtle.digest=async(...args)=>{if(first){first=false;entered();await held;}return digest(...args);};
  const apply=c.sync.apply(result,binding,base.rowsSignature).then(()=>null,e=>e.message);await waiting;
  await d.chat.syncSummaries([summary('NEW_WORKING_REVISION')]);release();const error=await apply;crypto.subtle.digest=digest;
  check(Boolean(error)&&(await c.review.list()).working[0].body==='NEW_WORKING_REVISION','sync final CAS preserves concurrent working revision');
 }finally{await c.close();await d.close();}
 const journal=createChatJournal({name:'journal-'+crypto.randomUUID()});
 try{for(const [k,v]of [['layerSyncEnabled',true],['layerSyncDays',7],['layerLastSync',123],['layerSyncBinding',binding]]){await journal.setting(k,v);check(canonical(await journal.setting(k))===canonical(v),'journal setting '+k);}let error;try{await journal.setting('layerSyncDays',0);}catch(e){error=e;}check(!!error,'invalid sync period rejected');}finally{await journal.close();}
 return reports;
}
