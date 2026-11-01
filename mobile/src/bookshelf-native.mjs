import {registerPlugin} from '@capacitor/core';
import {BOOKSHELF_FORMAT,createBookshelfCache,validateShelfManifest,validateShelfPage,shelfHash} from './bookshelf-cache.mjs';
const native=registerPlugin('HebaoUpdateTransport');
export function createBookshelfSync({transport=native,cache=createBookshelfCache()}={}){
 let busy=false,closed=false,active=true,generation=0;
 const pair=()=>{try{return JSON.parse(localStorage.getItem('hebao.updates.v1')||'{}').pair?.pairingId;}catch{return null;}};
 const app=e=>{active=e.detail!==false;if(!active)generation++;},visibility=()=>{if(document.hidden)generation++;};window.addEventListener('hebao:app-active',app);document.addEventListener('visibilitychange',visibility);
 const run=async({pairingId=pair(),eligible=()=>true,onProgress=()=>{}}={})=>{
  if(busy)throw Error('分类书架正在接回，请稍候。');
  const ownGeneration=generation;
  const allowed=()=>ownGeneration===generation&&!closed&&active&&!document.hidden&&eligible()&&pair()===pairingId&&!window.HebaoDialogueController?.getSnapshot().pending;
  const check=()=>{if(!allowed())throw Error('分类接回已暂停，原书架保留；回到前台后重试。');};
  if(!pairingId)throw Error('先在“电脑更新”配对电脑。');check();busy=true;
  const progress=(detail,loaded,total,done=false)=>onProgress({state:done?'done':'running',...(total?{steps:{completed:loaded,total}}:{}),detail});
  try{
   progress('正在连接电脑…');const info=await transport.layerInfo({pairingId});check();
   if(info.bookshelfCache!==BOOKSHELF_FORMAT)throw Error('电脑更新窗口尚不支持分类资料，原书架保留。');
   const binding={serverId:info.serverId,scope_id:info.scope_id},state=await cache.state();check();
   if(state&&(state.serverId!==binding.serverId||state.scope_id!==binding.scope_id))throw Error('分类书架来自另一台电脑，未自动混合。');
   const previous=state?Object.fromEntries(['serverId','scope_id','sequence','snapshotId','manifestHash'].map(k=>[k,state[k]])):null;
   const send=async request=>{check();const value=await transport.layerExchange({pairingId,request:{bookshelf:{format:BOOKSHELF_FORMAT,...request}}});check();return value;};
   const manifest=await send({phase:'manifest',previous});await validateShelfManifest(manifest,binding,previous);check();
   if(state?.sequence===manifest.sequence){progress('分类书架已是最新。',1,1,true);return {unchanged:true};}
   const pages=[],hashes=[];let offset=0,loaded=0;
   while(offset<manifest.bodyEntryCount){
    if(pages.length>=256)throw Error('资料页数超过接回上限，原书架保留。');
    const page=await send({phase:'bodies',snapshotId:manifest.snapshotId,manifestHash:manifest.manifestHash,offset});
    offset=await validateShelfPage(page,manifest,offset);check();pages.push(page);hashes.push(await shelfHash(page));
    loaded+=page.entries.reduce((n,r)=>n+r.bodyBytes,0);
    progress('已核对 '+offset+'/'+manifest.bodyEntryCount+' 份正文（'+loaded+'/'+manifest.bodyBytesTotal+'字节）；仍待最终保存。',offset,manifest.bodyEntryCount+2);
   }
   const attemptId=crypto.randomUUID(),confirmation=await send({phase:'finalize',snapshotId:manifest.snapshotId,manifestHash:manifest.manifestHash,attemptId,count:offset,bytes:loaded,pages:pages.length,transferDigest:await shelfHash(hashes)});check();
   progress('目录已核对，正在保存完整书架…',offset+1,manifest.bodyEntryCount+2);await cache.apply({manifest,pages,confirmation,attemptId},binding,allowed);check();
   progress('已接回 '+manifest.entries.length+' 份分类资料，课程仅目录。',1,1,true);window.dispatchEvent(new Event('hebao:bookshelf-changed'));return {count:manifest.entries.length};
  }finally{busy=false;}
 };
 run.cache=cache;run.close=async()=>{closed=true;generation++;window.removeEventListener('hebao:app-active',app);document.removeEventListener('visibilitychange',visibility);await cache.close();};return run;
}
