import {canonical} from './memory-records.mjs';
export const KNOWLEDGE_FORMAT='gernze-project-knowledge-v1';
const encoder=new TextEncoder();
const bytes=s=>encoder.encode(s).length;
const need=(v,message='课程资料不完整或已变化，原资料保留。')=>{if(!v)throw Error(message);};
const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const keys=(v,s)=>object(v)&&Object.keys(v).sort().join()===s.split(' ').sort().join();
export const knowledgeUUID=v=>typeof v==='string'&&/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(v);
const sha=v=>typeof v==='string'&&/^[0-9a-f]{64}$/.test(v);
// Unicode mode rejects lone surrogates, while preserving valid emoji pairs.
const text=(v,max)=>typeof v==='string'&&!!v.trim()&&!/[\u0000\ud800-\udfff]/u.test(v)&&bytes(v)<=max;
const integer=v=>Number.isSafeInteger(v)&&v>=0;
export const knowledgeHash=async s=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',encoder.encode(s))),b=>b.toString(16).padStart(2,'0')).join('');
export function validateCourseSelection(selected){
 need(Array.isArray(selected)&&selected.length<=100&&selected.every(knowledgeUUID)&&new Set(selected).size===selected.length,'请选择最多100门有效课程。');
 return [...selected];
}
export function validateKnowledgeCourses(courses){
 need(Array.isArray(courses)&&courses.length<=5000,'电脑课程目录无效。');
 const ids=new Set();
 for(const c of courses){need(keys(c,'id name')&&knowledgeUUID(c.id)&&text(c.name,500)&&!ids.has(c.id),'电脑课程目录无效。');ids.add(c.id);}
 return structuredClone(courses);
}
// Conservative command grammar: one direct, unquoted user command plus a query.
// Host must pass the actual user turn, never extracted text, model output or documents.
function searchQuery(value){
 if(typeof value!=='string'||value.length>8000)return null;
 const s=value.normalize('NFKC').trim();
 if(/[\r\n`"'“”‘’「」『』<>]/u.test(s)||/不要|不必|不用|无需|别|不需要|停止|取消/.test(s))return null;
 const m=s.match(/^(?:(?:请|帮我|麻烦|能否|能不能)\s*)?(?:(?:搜索|检索|查找|查阅|查一下)(?:一下)?\s*(?:我的|我们(?:的)?|这个)?(?:知识库|资料库)(?:里|中)?|从(?:我的|我们(?:的)?)?(?:知识库|资料库)(?:里|中)?(?:搜索|检索|查找))\s*[:：,，]?\s*(.+)$/u);
 return m?.[1]?.trim()||null;
}
export const explicitKnowledgeSearch=value=>searchQuery(value)!==null;
function queryTerms(query){
 return [...new Set(query.toLowerCase().match(/[a-z0-9_]+|[\p{Script=Han}]+/gu)||[])].slice(0,16);
}
export async function validateKnowledge(input,binding,selected,previous=null){
 const p=structuredClone(input);selected=validateCourseSelection(selected);
 need(keys(p,'format serverId scope_id libraryId sequence libraryFingerprint courses collections entries complete hash'));
 need(p.format===KNOWLEDGE_FORMAT&&p.complete===true&&integer(p.sequence)&&sha(p.libraryFingerprint)&&sha(p.hash));
 need(binding&&['serverId','scope_id','libraryId'].every(k=>knowledgeUUID(binding[k])&&p[k]===binding[k]),'课程来自不同电脑、配对空间或资料库，未自动混合。');
 validateKnowledgeCourses(p.courses);
 need(p.courses.length===selected.length&&canonical(p.courses.map(c=>c.id).sort())===canonical([...selected].sort()));
 need(Array.isArray(p.collections)&&p.collections.length<=5000&&Array.isArray(p.entries)&&p.entries.length<=1000);
 const ids=new Set(p.courses.map(c=>c.id)),collections=new Map(),entries=new Map();
 for(const c of p.collections){
  need(keys(c,'id revision title category course_id')&&knowledgeUUID(c.id)&&!ids.has(c.id)&&knowledgeUUID(c.revision)&&text(c.title,500)&&c.category==='course'&&selected.includes(c.course_id));
  ids.add(c.id);collections.set(c.id,c);
 }
 let total=0;
 for(const e of p.entries){
  need(keys(e,'id revision title type state category collection_id course_id origin source_ref body_hash body_bytes previous related related_revision review_status reply_use_granted body'));
  need(knowledgeUUID(e.id)&&!ids.has(e.id)&&knowledgeUUID(e.revision)&&text(e.title,500)&&e.type==='knowledge_note'&&e.state==='active'&&e.category==='course'&&selected.includes(e.course_id)&&collections.get(e.collection_id)?.course_id===e.course_id);
  need(['user','gpt_work','libao_work'].includes(e.origin)&&text(e.source_ref,2000)&&sha(e.body_hash)&&integer(e.body_bytes)&&e.body_bytes>0&&e.body_bytes<=32000&&text(e.body,32000)&&bytes(e.body)===e.body_bytes);
  need((e.previous===null||knowledgeUUID(e.previous))&&((e.related===null&&e.related_revision===null)||(knowledgeUUID(e.related)&&knowledgeUUID(e.related_revision)))&&e.review_status==='unverified'&&e.reply_use_granted===true);
  total+=e.body_bytes;need(total<=1500000);ids.add(e.id);entries.set(e.id,e);
 }
 need(bytes(canonical(p))<=2000000,'所选课程超过单次下载上限，请减少选课；原资料保留。');
 for(const e of p.entries){
  let c=e;const seen=new Set();
  while(c.related&&entries.has(c.related)){
   need(!seen.has(c.id)&&seen.size<16);seen.add(c.id);
   const parent=entries.get(c.related);need(parent.revision===c.related_revision&&parent.course_id===c.course_id);c=parent;
  }
  // A locally present collection/course cannot masquerade as a missing source note.
  if(c.related&&ids.has(c.related)&&!entries.has(c.related))need(false);
  need(await knowledgeHash(e.body)===e.body_hash);
 }
 const {hash,...unsigned}=p;need(await knowledgeHash(canonical(unsigned))===hash);
 if(previous){
  need(['serverId','scope_id','libraryId'].every(k=>previous[k]===p[k]),'课程来自不同资料库，未自动混合。');
  need(p.sequence>=previous.sequence,'电脑快照序号过旧，原资料保留。');
  if(previous.sequence===p.sequence)need(previous.libraryFingerprint===p.libraryFingerprint,'相同序号的全库指纹不一致，原资料保留。');
 }
 return p;
}
export function createKnowledgeCache({indexedDB=globalThis.indexedDB,name=KNOWLEDGE_FORMAT}={}){
 let opening=null,connection=null,closed=false;
 const transactions=new Set();
 const alive=()=>need(!closed,'课程缓存已关闭。');
 const open=()=>{
  alive();
  return opening??=new Promise((resolve,reject)=>{
   const r=indexedDB.open(name,1);let failed=false;
   const fail=message=>{failed=true;opening=null;reject(Error(message));};
   r.onupgradeneeded=()=>{for(const s of ['metadata','bodies','state'])r.result.createObjectStore(s);};
   r.onerror=()=>fail('课程缓存未打开。');
   r.onblocked=()=>fail('请关闭旧资料页后重试。');
   r.onsuccess=()=>{
    const db=r.result;if(failed||closed){db.close();reject(Error('课程缓存已关闭。'));return;}
    connection=db;const reset=()=>{db.close();if(connection===db){connection=null;opening=null;}};
    db.onversionchange=reset;db.onclose=reset;resolve(db);
   };
  });
 };
 async function tx(stores,mode,action,guard=()=>true,subscribe=()=>()=>{}){
  const db=await open();alive();need(guard(),'课程操作已暂停，原资料保留。');
  return new Promise((resolve,reject)=>{
   let t,result,error,unsubscribe=()=>{};
   try{t=db.transaction(stores,mode,mode==='readwrite'?{durability:'strict'}:undefined);}catch(e){reject(e);return;}
   transactions.add(t);
   const abort=e=>{error=e;try{t.abort();}catch{}};
   const check=()=>{alive();need(guard(),'课程操作已暂停，原资料保留。');};
   const cleanup=()=>{transactions.delete(t);unsubscribe();};
   t.oncomplete=()=>{cleanup();resolve(result);};
   t.onabort=()=>{cleanup();reject(error||t.error||Error('课程未保存，旧资料保留。'));};t.onerror=()=>{};
   try{
    unsubscribe=subscribe(()=>abort(Error('课程操作已取消，原资料保留。')))||(()=>{});
    check();
    if(mode==='readwrite')need(t.durability==='strict','当前WebView不支持可靠课程保存。');
    action(t,v=>result=v,abort,check);
   }catch(e){abort(e);}
  });
 }
 const state=()=>tx(['state'],'readonly',(t,set)=>{t.objectStore('state').get('snapshot').onsuccess=e=>set(e.target.result||null);});
 const assertStamp=async stamp=>need((await state())?.stamp===stamp,'读取期间课程已变化，请重新打开。');
 async function list({courseId=null}={}){
  need(courseId===null||knowledgeUUID(courseId));
  return tx(['state','metadata'],'readonly',(t,set)=>{
   t.objectStore('state').get('snapshot').onsuccess=e=>{
    const s=e.target.result;
    t.objectStore('metadata').getAll().onsuccess=e=>set({stamp:s?.stamp??null,receivedAt:s?.receivedAt??null,courses:s?.courses??[],collections:(s?.collections??[]).filter(c=>!courseId||c.course_id===courseId),entries:e.target.result.filter(m=>!courseId||m.course_id===courseId)});
   };
  });
 }
 async function read(id,revision,courseId,{stamp=null}={}){
  need([id,revision,courseId].every(knowledgeUUID),'资料引用或课程无效。');
  const value=await tx(['metadata','bodies','state'],'readonly',(t,set,abort)=>{
   t.objectStore('state').get('snapshot').onsuccess=e=>{try{
    const s=e.target.result;need(s&&(!stamp||s.stamp===stamp)&&s.courses.some(c=>c.id===courseId),'课程已变化或未下载。');
    t.objectStore('metadata').get(id).onsuccess=e=>{try{
     const m=e.target.result;need(m&&m.revision===revision&&m.course_id===courseId,'资料已变化或不属于当前课程。');
     // Subject/version guard precedes *every* body get.
     t.objectStore('bodies').get(id).onsuccess=e=>set({...m,body:e.target.result,stamp:s.stamp});
    }catch(error){abort(error);}};
   }catch(error){abort(error);}};
  });
  need(text(value.body,32000)&&bytes(value.body)===value.body_bytes&&await knowledgeHash(value.body)===value.body_hash,'本地正文校验失败，请重新下载。');
  await assertStamp(value.stamp);return value;
 }
 const reader=Object.freeze({state,list,read,
  async search({origin,userText,courseId}){
   need(origin==='user'&&explicitKnowledgeSearch(userText),'请明确输入“搜索知识库：关键词”；仅接受用户当前输入。');
   need(knowledgeUUID(courseId),'请先选择当前课程。');
   const before=await state();need(before?.courses.some(c=>c.id===courseId),'请先下载并选择当前课程。');
   const catalog=await list({courseId});need(catalog.stamp===before.stamp);
   const terms=queryTerms(searchQuery(userText));let scanned=0;const matches=[];
   for(const e of catalog.entries){
    if(!terms.length||scanned+e.body_bytes>256000)break;
    const r=await read(e.id,e.revision,courseId,{stamp:before.stamp});scanned+=e.body_bytes;
    const hay=(r.title+'\n'+r.body).normalize('NFKC').toLowerCase();
    const needles=terms.flatMap(t=>/[\p{Script=Han}]/u.test(t)&&t.length>2?Array.from({length:t.length-1},(_,i)=>t.slice(i,i+2)):[t]);
    const score=needles.filter(t=>hay.includes(t)).length;if(!score)continue;
    const hit=needles.find(t=>r.body.toLowerCase().includes(t)),at=hit?r.body.toLowerCase().indexOf(hit):0,start=Math.max(0,at-120);
    matches.push({id:r.id,revision:r.revision,course_id:r.course_id,title:r.title,source_ref:r.source_ref,origin:r.origin,review_status:r.review_status,body_hash:r.body_hash,excerpt:r.body.slice(start,start+1200),score});
   }
   await assertStamp(before.stamp);matches.sort((a,b)=>b.score-a.score);
   return {results:matches.slice(0,5).map(({score,...r})=>r),stamp:before.stamp,scanBytes:scanned};
  }
 });
 return Object.freeze({reader,
  async apply(input,binding,selected,options={}){
   // Capture all caller-owned inputs before the first await.
   const raw=structuredClone(input),bound=structuredClone(binding),chosen=structuredClone(selected);
   if(typeof options==='function')options={isEligible:options};
   const {isEligible=()=>true,subscribeInvalidation=()=>()=>{}}=options;
   let invalid=false;const unsubscribe=subscribeInvalidation(()=>{invalid=true;})||(()=>{});
   const allowed=()=>!closed&&!invalid&&isEligible();
   try{
    need(allowed(),'课程接回已暂停。');const before=await state();
    const p=await validateKnowledge(raw,bound,chosen,before);need(allowed(),'课程接回已暂停，旧课程保留。');
    return await tx(['metadata','bodies','state'],'readwrite',(t,set,abort,check)=>{
     t.objectStore('state').get('snapshot').onsuccess=e=>{try{
      check();need((e.target.result?.stamp??null)===(before?.stamp??null),'课程在接回期间已变化，请重试。');
      t.objectStore('metadata').clear();t.objectStore('bodies').clear();
      for(const e of p.entries){const {body,...m}=e;t.objectStore('metadata').put(m,e.id);t.objectStore('bodies').put(body,e.id);}
      const {entries,complete,...rest}=p;
      const s={...rest,stamp:crypto.randomUUID(),receivedAt:new Date().toISOString()};
      t.objectStore('state').put(s,'snapshot');
      // Last queued request is a precommit guard, not an async promise gap.
      t.objectStore('state').get('snapshot').onsuccess=()=>{try{check();set({count:p.entries.length,stamp:s.stamp});}catch(error){abort(error);}};
     }catch(error){abort(error);}};
    },allowed,subscribeInvalidation);
   }finally{unsubscribe();}
  },
  async close(){closed=true;for(const t of transactions){try{t.abort();}catch{}}connection?.close();connection=null;opening=null;}
 });
}
