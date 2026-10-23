import {createLayerSync} from './layer-sync-core.mjs';
import {canonical} from './memory-records.mjs';
import {layersPrompt,selectLayerEntries,summaryEntry,reviewDue} from './memory-layers.mjs';
// Distinct capabilities/stores, one database transaction for L2/L3 and sync metadata.
// L1 remains external and read-only. L4 remains in the independent chat journal.
export function createLayeredMemory({core,indexedDB=globalThis.indexedDB,namespace='hebao-layers-v1',now=()=>new Date().toISOString()}={}){
 const fixed=structuredClone(core);layersPrompt({core:fixed});let connection,ready,serial=Promise.resolve();
 const gate=fn=>{const p=serial.then(fn,fn);serial=p.catch(()=>{});return p;};
 const receiptKey=row=>'review:'+row.key+':'+row.revision;
 function open(name,upgrade){return new Promise((resolve,reject)=>{
  const r=indexedDB.open(name,2);let blocked=false;
  r.onupgradeneeded=()=>{const db=r.result;for(const [store,options]of upgrade)if(!db.objectStoreNames.contains(store))db.createObjectStore(store,options);};
  r.onerror=()=>reject(Error('分层记忆未打开，请更新并重开莉宝。'));
  r.onblocked=()=>{blocked=true;reject(Error('旧版记忆页仍在使用，请关闭后重开莉宝。'));};
  r.onsuccess=()=>{if(blocked){r.result.close();return;}r.result.onversionchange=()=>r.result.close();resolve(r.result);};
 });}
 function transaction(db,mode,fn){return new Promise((resolve,reject)=>{
  const tx=db.transaction(['entries','working','meta'],mode,mode==='readwrite'?{durability:'strict'}:undefined);let error,result;
  const fail=e=>{error=e;try{tx.abort();}catch{}};
  tx.onabort=()=>reject(error||Error('分层记忆未保存，原资料保留。'));tx.onerror=()=>{};tx.oncomplete=()=>resolve(result);
  if(mode==='readwrite'&&tx.durability!=='strict'){fail(Error('系统WebView暂不支持可靠记忆保存。'));return;}
  const data={};let left=4;
  for(const [store,method,field]of [['entries','getAll','approved'],['working','getAll','working'],['meta','getAllKeys','keys'],['meta','getAll','values']]){
   const r=tx.objectStore(store)[method]();r.onsuccess=()=>{data[field]=r.result;if(--left===0){data.meta=Object.fromEntries(data.keys.map((k,i)=>[k,data.values[i]]));try{result=fn(data,tx);}catch(e){fail(e);}}};
  }
 });}
 async function database(){
  return ready??= (async()=>{
   const db=await open(namespace+'-approved',[['entries',{keyPath:'key'}],['meta'],['working',{keyPath:'key'}]]);connection=db;
   try{
    // Upgrade fences out v1 writers. Copy once; a failed migration has no marker
    // and is retried. The old working database is retained, never deleted.
    const done=await transaction(db,'readonly',d=>d.meta.workingMigratedV2);
    if(!done){
     const old=await open(namespace+'-working',[['entries',{keyPath:'key'}],['meta']]);let rows;
     try{rows=await new Promise((resolve,reject)=>{const t=old.transaction('entries','readonly'),r=t.objectStore('entries').getAll();t.oncomplete=()=>resolve(r.result);t.onabort=()=>reject(Error('旧摘要未读取。'));});}finally{old.close();}
     await transaction(db,'readwrite',(d,t)=>{if(d.meta.workingMigratedV2)return;for(const row of rows)if(!d.working.some(e=>e.key===row.key))t.objectStore('working').put(row);t.objectStore('meta').put(true,'workingMigratedV2');});
    }return db;
   }catch(e){db.close();connection=null;ready=null;throw e;}
  })();
 }
 const read=async()=>transaction(await database(),'readonly',d=>d);
 const write=async fn=>transaction(await database(),'readwrite',fn);
 function snapshot(d){const conflicts=d.meta.layerSyncConflicts||[];return {approved:d.approved.map(e=>({...e,syncConflict:conflicts.includes('2:'+e.key)})),working:d.working.map(row=>{
  const receipt=d.meta[receiptKey(row)];return {...row,...(receipt?{reviewed:row.revision,rejected:receipt.action==='reject'}:{}),syncConflict:conflicts.includes('3:'+row.key)};
 })};}
 function assertNoConflict(d,key){if((d.meta.layerSyncConflicts||[]).some(k=>k==='2:'+key||k==='3:'+key))throw Error('此条存在同步冲突，请先在同步入口选择版本。');}
 async function setting(key,value){if(key!=='reviewDays')throw Error('设置无效。');if(arguments.length===1)return (await read()).meta[key]??null;
  if(value!==null&&(!Number.isSafeInteger(value)||value<1||value>3650))throw Error('审查间隔须为1～3650天，或留空按需审查。');return write((d,t)=>t.objectStore('meta').put(value,key));}
 const chat=Object.freeze({
  async context(input,{epoch}={}){const {approved:a,working:w}=snapshot(await read()),blocked=new Set([...fixed.entries,...a].map(e=>e.key));return {core:structuredClone(fixed),counts:{core:fixed.entries.length,approved:a.filter(e=>!e.deleted&&!e.syncConflict).length,pending:w.filter(e=>!e.deleted&&!e.syncConflict&&!e.reviewed&&a.find(n=>n.key===e.key)?.sourceRevision!==e.revision).length},approved:selectLayerEntries(a,input),working:selectLayerEntries(w.filter(e=>!e.syncConflict&&!blocked.has(e.key)&&(e.remote||epoch===undefined||e.sourceEpoch===epoch)),input)};},
  async archive(){const {approved,working}=snapshot(await read());return {approved:approved.filter(e=>!e.deleted&&!e.syncConflict),working:working.filter(e=>!e.syncConflict&&!e.deleted&&!e.rejected&&!e.reviewed&&!approved.some(a=>a.key===e.key))};},
  syncSummaries(summaries){return gate(async()=>{
   if(!Array.isArray(summaries))throw Error('摘要列表无效。');const entries=summaries.map(summaryEntry);
   return write((d,t)=>{let rows=snapshot(d).working,changed=0;for(const data of entries){const old=rows.find(e=>e.key===data.key);
    if(old?.deleted||old&&old.body===data.body&&JSON.stringify(old.sourceAnchors)===JSON.stringify(data.sourceAnchors))continue;
    assertNoConflict(d,data.key);
    if(!old&&rows.filter(e=>!e.deleted&&!e.reviewed&&!e.rejected).length>=200)throw Error('第三层已有200条待审摘要，请先安排审查。');
    const entry={...data,revision:crypto.randomUUID(),approvedBaseRevision:d.approved.find(e=>e.key===data.key)?.revision??null,createdAt:old?.createdAt||now(),deleted:false,corrected:Boolean(old)};
    t.objectStore('working').put(entry);rows=rows.filter(e=>e.key!==entry.key);rows.push(entry);changed++;
   }return {changed};});
  });}
 });
 const review=Object.freeze({
  async list(){const data=await read(),{working,approved}=snapshot(data),days=data.meta.reviewDays??null;return {core:structuredClone(fixed),reviewOn:'desktop',legacyApproved:data.meta.legacyApproved||[],working,approved,pending:working.filter(w=>!w.deleted&&!w.syncConflict&&approved.find(a=>a.key===w.key)?.sourceRevision!==w.revision&&!w.reviewed),reviewDays:days,due:reviewDue(working,approved,days)};},
  decide(){return Promise.reject(Error('请在电脑端统一审查第三层记忆。'));},
  removeApproved(){return Promise.reject(Error('请在电脑端纠正或撤回已审核记忆。'));},
  setting
 });
 function syncRows(data){const {approved,working}=snapshot(data),rows=[];
  const source=e=>e.remoteSource||{sessionId:e.sourceSessionId||'',summaryId:e.sourceSummaryId||'',epoch:e.sourceEpoch||0,turnIds:[],messageIds:[],at:e.sourceAt||null,anchors:e.sourceAnchors||[],start:e.sourceStart??null,end:e.sourceEnd??null};
  for(const e of approved)rows.push({tier:2,entry:{key:e.key,revision:e.revision,body:e.body,deleted:Boolean(e.deleted),updatedAt:e.updatedAt,sourceRevision:e.sourceRevision||e.revision,source:source(e)}});
  for(const e of working)rows.push({tier:3,entry:{key:e.key,revision:e.revision,body:e.body,deleted:Boolean(e.deleted||e.reviewed||e.rejected),updatedAt:e.updatedAt,createdAt:e.createdAt||e.updatedAt,approvedBaseRevision:e.approvedBaseRevision??null,source:source(e)}});
  return rows.sort((a,b)=>a.tier-b.tier||a.entry.key.localeCompare(b.entry.key));
 }
 function project(data,packet,view){const next=structuredClone(data);if(!next.meta.desktopReviewCacheInitialized){next.meta.legacyApproved=next.approved;next.meta.desktopReviewCacheInitialized=true;}next.approved=[];
  for(const row of packet.graph.records){const m=packet.identities[row.id],area=m.tier===2?'approved':'working',old=next[area].find(e=>e.key===m.key);let value;
   if(row.deleted){if(!old){if(m.tier!==2)continue;value={key:m.key,body:'',deleted:true,revision:row.revision,updatedAt:now()};}else{if(old.deleted)continue;value={...old,body:'',deleted:true,revision:row.revision,updatedAt:now()};}}
   else{if(!view.active.some(r=>r.revision===row.revision))continue;const e=packet.payloads[row.revision].entry,src=e.source||{};if(old&&old.revision===e.revision&&old.body===e.body)continue;
    const base={key:e.key,revision:e.revision,body:e.body,deleted:false,updatedAt:e.updatedAt,remote:true,remoteSource:src,sourceSessionId:src.sessionId,sourceSummaryId:src.summaryId,sourceEpoch:src.epoch,sourceAt:src.at,sourceAnchors:src.anchors||[]};
    value=m.tier===2?{...base,sourceRevision:e.sourceRevision||e.revision,reviewedBy:'owner-paired-review'}:{...base,createdAt:e.createdAt||e.updatedAt,approvedBaseRevision:e.approvedBaseRevision??null,...(Number.isSafeInteger(src.start)&&Number.isSafeInteger(src.end)?{sourceStart:src.start,sourceEnd:src.end}:{})};
   }next[area]=next[area].filter(e=>e.key!==m.key);next[area].push(value);
  }
  next.meta.layerSyncConflicts=view.conflicts.map(id=>packet.identities[id].tier+':'+packet.identities[id].key);return {data:next,rows:syncRows(next)};
 }
 const sync=createLayerSync({core:fixed,read:async()=>{const data=await read();return {data,rows:syncRows(data),state:data.meta.layerSyncState??null};},project,
  commit:({before,state,projected})=>write((current,t)=>{
   // Compare the entire layer/meta snapshot inside the same writer transaction,
   // including receipts/conflicts changed by another tab or review window.
   if(canonical(current)!==canonical(before.data))throw Error('同步期间本机记忆有新改动，请重新同步。');
   if(projected){t.objectStore('entries').clear();t.objectStore('meta').put(projected.data.meta.legacyApproved||[],'legacyApproved');t.objectStore('meta').put(true,'desktopReviewCacheInitialized');for(const [area,store]of [['approved','entries'],['working','working']])for(const row of projected.data[area])t.objectStore(store).put(row);t.objectStore('meta').put(projected.data.meta.layerSyncConflicts,'layerSyncConflicts');}
   t.objectStore('meta').put(state,'layerSyncState');
  })
 });
 return Object.freeze({chat,review,sync,async close(){await ready?.catch(()=>{});connection?.close();connection=null;ready=null;}});
}
