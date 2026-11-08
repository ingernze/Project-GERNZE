import {KNOWLEDGE_FORMAT,knowledgeUUID,validateKnowledgeCourses,validateCourseSelection} from './knowledge-cache.mjs';
const need=(v,message)=>{if(!v)throw Error(message);};
export function createKnowledgeSync({transport,cache,getPairingId,isEligible=()=>true,subscribeInvalidation=()=>()=>{},window:win=globalThis.window,document:doc=globalThis.document}){
 let closed=false,busy=false,generation=0,active=true;
 const pending=new Set();
 const invalidate=()=>{generation++;for(const callback of [...pending])callback();};
 const app=e=>{active=e.detail!==false;if(!active)invalidate();};
 const visibility=()=>{if(doc.hidden)invalidate();};
 const listen=(target,event,handler)=>target?.addEventListener(event,handler);
 listen(win,'hebao:app-active',app);listen(win,'hebao:pairing-changed',invalidate);listen(win,'pagehide',invalidate);listen(doc,'visibilitychange',visibility);
 const removeExternal=subscribeInvalidation(invalidate)||(()=>{});
 function context(eligible){
  const pairingId=getPairingId(),ownGeneration=generation;let invalid=false;
  const allowed=()=>{
   if(closed||ownGeneration!==generation||!active||doc?.hidden||!isEligible()||!eligible()||getPairingId()!==pairingId)invalid=true;
   return !invalid;
  };
  const check=()=>need(allowed(),'课程接回已暂停或配对已变化，原资料保留。');
  need(typeof pairingId==='string'&&pairingId.trim(),'请先配对电脑。');check();
  return {pairingId,allowed,check};
 }
 async function info(ctx){
  const value=structuredClone(await transport.layerInfo({pairingId:ctx.pairingId}));ctx.check();
  need(value&&knowledgeUUID(value.serverId)&&knowledgeUUID(value.scope_id),'电脑身份无效。');
  const k=value.knowledgeLibrary;
  need(k&&Object.keys(k).sort().join()==='courses,format,libraryId'&&k.format===KNOWLEDGE_FORMAT&&knowledgeUUID(k.libraryId),'电脑尚不支持课程离线资料。');
  const courses=validateKnowledgeCourses(k.courses),binding={serverId:value.serverId,scope_id:value.scope_id,libraryId:k.libraryId};
  const old=await cache.reader.state();ctx.check();
  need(!old||Object.keys(binding).every(key=>old[key]===binding[key]),'现有课程来自不同电脑或资料库，未自动混合。');
  return {binding,courses};
 }
 async function run(action){
  need(!closed,'课程同步已关闭。');need(!busy,'课程接回正在进行，请稍候。');busy=true;
  try{return await action();}finally{busy=false;}
 }
 return Object.freeze({
  discover({eligible=()=>true}={}){return run(async()=>{
   const ctx=context(eligible),catalog=await info(ctx);ctx.check();return catalog;
  });},
  sync({courseIds,eligible=()=>true}={}){return run(async()=>{
   const selected=validateCourseSelection(courseIds),ctx=context(eligible),catalog=await info(ctx);
   need(selected.every(id=>catalog.courses.some(c=>c.id===id)),'选课已失效，请刷新目录。');ctx.check();
   const snapshot=await transport.layerExchange({pairingId:ctx.pairingId,request:{knowledge:{format:KNOWLEDGE_FORMAT,course_ids:selected}}});ctx.check();
   const result=await cache.apply(snapshot,catalog.binding,selected,{
    isEligible:ctx.allowed,
    subscribeInvalidation(callback){pending.add(callback);return ()=>pending.delete(callback);}
   });
   ctx.check();return result;
  });},
  close(){if(closed)return;closed=true;invalidate();removeExternal();
   win?.removeEventListener('hebao:app-active',app);win?.removeEventListener('hebao:pairing-changed',invalidate);win?.removeEventListener('pagehide',invalidate);doc?.removeEventListener('visibilitychange',visibility);
  }
 });
}
