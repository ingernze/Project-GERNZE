import {canonical} from './memory-records.mjs';
export const RESEARCH_CACHE_FORMAT='gernze-research-cache-v1';
export const RESEARCH_CACHE_V2='gernze-research-cache-v2';
const fail=()=>{throw Error('研究资料版本或来源无效，原缓存保留。');};
const requireValue=value=>{if(!value)fail();};
const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const keys=(v,list)=>object(v)&&Object.keys(v).sort().join()===list.slice().sort().join();
const uuid=v=>typeof v==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v);
const sha=v=>typeof v==='string'&&/^[0-9a-f]{64}$/.test(v);
const ids=v=>Array.isArray(v)&&v.length<=16&&v.every(uuid)&&canonical(v)===canonical([...new Set(v)].sort());
const text=v=>typeof v==='string'&&!v.includes('\0')&&!Array.from(v).some(c=>c.codePointAt(0)>=0xd800&&c.codePointAt(0)<=0xdfff);
const hash=async v=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(v))),b=>b.toString(16).padStart(2,'0')).join('');
const ref=v=>keys(v,['id','revision','body_hash'])&&uuid(v.id)&&uuid(v.revision)&&sha(v.body_hash);
export async function validateResearchCache(packet,binding,previous=null){
 requireValue(keys(packet,['format','serverId','scope_id','sequence','complete','records'])&&[RESEARCH_CACHE_FORMAT,RESEARCH_CACHE_V2].includes(packet.format)&&packet.complete===true);
 requireValue(uuid(packet.serverId)&&uuid(packet.scope_id)&&packet.serverId===binding.serverId&&packet.scope_id===binding.scope_id);
 requireValue(Number.isSafeInteger(packet.sequence)&&packet.sequence>0&&Array.isArray(packet.records)&&packet.records.length<=128&&new TextEncoder().encode(canonical(packet)).length<=1048576);
 if(previous?.format===RESEARCH_CACHE_V2)requireValue(packet.format===RESEARCH_CACHE_V2);
 if(previous)requireValue(previous.serverId===packet.serverId&&previous.scope_id===packet.scope_id&&packet.sequence>=previous.sequence);
 const seen=new Set();
 for(const item of packet.records){
  requireValue(keys(item,['id','revision','body_hash','restriction','courses','facets','trust','review','sources','parents','raw_refs','body',...(packet.format===RESEARCH_CACHE_V2?['phone_refs']:[])])&&ref({id:item.id,revision:item.revision,body_hash:item.body_hash})&&!seen.has(item.id));seen.add(item.id);
  requireValue(['general','study'].includes(item.restriction)&&ids(item.courses)&&(item.restriction==='study'?item.courses.length>0:item.courses.length===0));
  requireValue(item.trust==='research_summary'&&Array.isArray(item.facets)&&item.facets.length>0&&item.facets.length<=3&&item.facets.every(f=>['encounter','interest','course'].includes(f))&&(item.restriction==='study'||!item.facets.includes('course')));
  requireValue(keys(item.review,['status','reason'])&&['pending','supported','defer'].includes(item.review.status)&&text(item.review.reason)&&Array.from(item.review.reason).length<=300);
  requireValue(Array.isArray(item.sources)&&item.sources.length>0&&item.sources.length<=64&&Array.isArray(item.parents)&&item.parents.length<=64&&item.parents.every(ref));
  requireValue(object(item.raw_refs)&&Object.keys(item.raw_refs).length>0&&Object.keys(item.raw_refs).length<=256&&Object.entries(item.raw_refs).every(([id,h])=>uuid(id)&&sha(h)));
  const sourceIds=new Set(),courses=new Set();let study=false;
  for(const source of item.sources){
   requireValue(keys(source,['id','revision','body_hash','source_versions','restriction','courses'])&&ref({id:source.id,revision:source.revision,body_hash:source.body_hash})&&!sourceIds.has(source.id));sourceIds.add(source.id);
   requireValue(ids(source.courses)&&['general','study'].includes(source.restriction)&&(source.restriction==='study'?source.courses.length>0:source.courses.length===0));
   requireValue(object(source.source_versions)&&Object.keys(source.source_versions).length>0&&Object.keys(source.source_versions).length<=256&&Object.entries(source.source_versions).every(([id,revision])=>uuid(id)&&uuid(revision)));
   study ||= source.restriction==='study';for(const c of source.courses)courses.add(c);
  }
  requireValue(study===(item.restriction==='study')&&canonical([...courses].sort())===canonical(item.courses));
  if(packet.format===RESEARCH_CACHE_V2){
   requireValue(Array.isArray(item.phone_refs)&&item.phone_refs.length<=8&&(!study||item.phone_refs.length===0));const seenPhone=new Set();
   for(const r of item.phone_refs){requireValue(keys(r,['device','session','index','content_hash'])&&uuid(r.device)&&typeof r.session==='string'&&r.session.length>=1&&r.session.length<=100&&!/[\x00-\x1f]/.test(r.session)&&Number.isSafeInteger(r.index)&&r.index>=0&&r.index<100000&&sha(r.content_hash));const key=canonical([r.device,r.session,r.index]);requireValue(!seenPhone.has(key));seenPhone.add(key);}
  }
  if(study)requireValue(item.body===null);
  else requireValue(text(item.body)&&item.body.trim()&&Array.from(item.body).length<=1500&&await hash(item.body)===item.body_hash);
 }
 const fingerprint=await hash(canonical(packet));
 if(previous&&previous.sequence===packet.sequence)requireValue(previous.fingerprint===fingerprint);
 return {packet:structuredClone(packet),fingerprint};
}

// Separate metadata/body stores. Chat requires the explicit one-use host adapter;
// this cache never projects into L2/L3 or uploads research as ordinary facts.
export function createResearchCache({indexedDB=globalThis.indexedDB,name='gernze-research-cache-v1',database=null,validator=validateResearchCache,beforeCommit=()=>{}}={}){
 let opening,connection;
 const open=()=>database?database():opening??=new Promise((resolve,reject)=>{
  if(!indexedDB){reject(Error('本机研究缓存不可用。'));return;}
  const request=indexedDB.open(name,1);let blocked=false;
  request.onupgradeneeded=()=>{for(const store of ['metadata','bodies','state'])request.result.createObjectStore(store);};
  request.onerror=()=>{opening=null;reject(Error('研究缓存未打开。'));};request.onblocked=()=>{blocked=true;opening=null;reject(Error('请关闭旧资料页后重试。'));};
  request.onsuccess=()=>{if(blocked){request.result.close();return;}connection=request.result;connection.onversionchange=()=>{connection.close();connection=null;opening=null;};resolve(connection);};
 });
 async function transaction(mode,action){const db=await open();return new Promise((resolve,reject)=>{
  const tx=db.transaction(['metadata','bodies','state'],mode,mode==='readwrite'?{durability:'strict'}:undefined);let result,error;
  const abort=e=>{error=e;try{tx.abort();}catch{}};
  tx.oncomplete=()=>resolve(result);tx.onabort=()=>reject(error||Error('研究缓存未保存，原资料保留。'));tx.onerror=()=>{};
  if(mode==='readwrite'&&tx.durability!=='strict'){abort(Error('当前WebView不支持可靠资料保存。'));return;}
  try{action(tx,value=>result=value,abort);}catch(e){abort(e);}
 });}
 const state=()=>transaction('readonly',(tx,set)=>{tx.objectStore('state').get('snapshot').onsuccess=e=>set(e.target.result||null);});
 return Object.freeze({
  async apply(input,binding){
   const before=await state(),{packet,fingerprint}=await validator(input,binding,before);
   return transaction('readwrite',(tx,set,abort)=>{
    tx.objectStore('state').get('snapshot').onsuccess=e=>{
     try{
     if(canonical(e.target.result||null)!==canonical(before)){abort(Error('研究资料在同步期间已变化，请重试。'));return;}
     beforeCommit();tx.objectStore('metadata').clear();tx.objectStore('bodies').clear();
     for(const record of packet.records){const {body,...metadata}=record;metadata._bodyWireBytes=body===null?0:new TextEncoder().encode(JSON.stringify(JSON.stringify(body))).length;tx.objectStore('metadata').put(metadata,record.id);if(body!==null)tx.objectStore('bodies').put(body,record.id);}
     tx.objectStore('state').put({format:packet.format,serverId:packet.serverId,scope_id:packet.scope_id,sequence:packet.sequence,fingerprint,receivedAt:new Date().toISOString()},'snapshot');set({count:packet.records.length});
     }catch(error){abort(error);}
    };
   });
  },
  async metadata(id,revision){return transaction('readonly',(tx,set,abort)=>{tx.objectStore('metadata').get(id).onsuccess=e=>{if(!e.target.result||e.target.result.revision!==revision){abort(Error('研究资料已变化，请重新选择。'));return;}set(e.target.result);};});},
  async list(){return transaction('readonly',(tx,set)=>{tx.objectStore('metadata').getAll().onsuccess=e=>set(e.target.result);});},
  async read(id,revision){const value=await transaction('readonly',(tx,set,abort)=>{
   tx.objectStore('metadata').get(id).onsuccess=e=>{
    const meta=e.target.result;
    if(!meta||meta.revision!==revision||meta.restriction!=='general'){abort(Error('资料已变化或属于课程，手机正文尚未开放。'));return;}
    tx.objectStore('bodies').get(id).onsuccess=e=>set({...meta,body:e.target.result});
   };
  });requireValue(text(value.body)&&await hash(value.body)===value.body_hash);return value;},
  state,
  async close(){if(database)return;await opening?.catch(()=>{});connection?.close();connection=null;opening=null;}
 });
}

export function mountResearchCache({container,cache,onSelect=null}){
 const root=document.createElement('section');root.className='panel';root.hidden=true;
 const title=document.createElement('h3');title.textContent='研究资料 · 电脑接回';
 const hint=document.createElement('p');hint.className='hint';hint.textContent=onSelect?'研究资料按最近一次同步显示，不等于已审用户事实。普通摘要可用于下一次提问，用后自动取消；课程仍只显示目录。':'只读缓存，按最近一次同步显示。来源核对不等于已审用户事实；暂不用于手机聊天。课程只显示目录，正文仍留电脑。';
 const refreshButton=document.createElement('button');refreshButton.type='button';refreshButton.textContent='刷新研究目录';
 const status=document.createElement('p'),list=document.createElement('div'),body=document.createElement('p');body.style.whiteSpace='pre-wrap';status.setAttribute('role','status');
 root.append(title,hint,refreshButton,status,list,body);container.append(root);let closed=false,generation=0;
 async function refresh(){const ticket=++generation;body.textContent='';const [records,state]=await Promise.all([cache.list(),cache.state()]);if(closed||ticket!==generation)return;
  root.hidden=!state;list.replaceChildren();status.textContent=state?'已接回 '+records.length+' 项 · '+new Date(state.receivedAt).toLocaleString('zh-CN'):'尚未接回研究资料。';
  const labels={encounter:'见闻',interest:'兴趣',course:'课程'},reviews={pending:'待核对',supported:'与所附输入相符',defer:'保留待核对'};
  for(const item of records){const row=document.createElement('article'),label=document.createElement('p');label.textContent=(item.restriction==='study'?['课程',...item.facets.filter(f=>f!=='course').map(f=>labels[f])]:item.facets.map(f=>labels[f])).join(' / ')+' · '+reviews[item.review.status]+' · 来源 '+item.sources.length+' 项'+(item.phone_refs?.length?' · 手机原文 '+item.phone_refs.length+' 轮':'');row.append(label);
   if(item.restriction==='study'){const p=document.createElement('p');p.textContent='课程正文仍在电脑，手机未下载。';row.append(p);}
   else {const button=document.createElement('button');button.type='button';button.textContent='查看摘要';button.onclick=async()=>{const selected=++generation;body.textContent='';try{const value=await cache.read(item.id,item.revision);if(!closed&&selected===generation)body.textContent=value.body;}catch(e){if(!closed&&selected===generation)body.textContent=e.message;}};row.append(button);}
   if(onSelect&&item.restriction==='general'){const use=document.createElement('button');use.type='button';use.textContent='用于下一次提问';use.onclick=()=>{Promise.resolve(onSelect({id:item.id,revision:item.revision})).catch(e=>status.textContent=e.message);};row.append(use);}
   list.append(row);
  }
 }
 const changed=()=>{if(!closed)void refresh().catch(e=>{if(!closed)status.textContent=e.message;});};
 refreshButton.onclick=changed;window.addEventListener('hebao:memory-changed',changed);const ready=refresh().catch(e=>{if(!closed)status.textContent=e.message;});
 return {ready,refresh,destroy(){closed=true;generation++;window.removeEventListener('hebao:memory-changed',changed);root.remove();}};
}
