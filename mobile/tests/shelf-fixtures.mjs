import {BOOKSHELF_FORMAT,shelfHash} from '../src/bookshelf-cache.mjs';
export const uid=n=>'00000000-0000-4000-8000-'+String(n).padStart(12,'0');
export const sha=async s=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s))),b=>b.toString(16).padStart(2,'0')).join('');
export async function fixtures(sequence=1,{withdraw=false,large=true}={}){
 const binding={serverId:uid(90001),scope_id:uid(90002)},defs=[];
 if(large)for(let n=1;n<=230;n++)defs.push([n,'interest','歌曲专题 '+n,'合成歌曲资料 '+n]);
 if(!withdraw)defs.push([1000,'interest','月光奏鸣曲 研读取舍','月光奏鸣曲：这是一份合成测试笔记。SOURCE_ONLY_MOONSTONE。不代表用户偏好。']);
 defs.push([1001,'encounter','雨夜灯光 见闻','雨夜灯光来自合成的已保存见闻，目录没有阅读日期。'],[1002,'course','月光奏鸣曲 大学课程 FORBIDDEN_COURSE','COURSE_BODY_MUST_NOT_READ']);
 const bodies=new Map(),entries=[];
 for(const [n,category,title,body]of defs){const e={id:uid(n),revision:uid(n+10000+sequence),category,title,review:'partial',trust:'external_untrusted',bodyHash:await sha(body),bodyBytes:new TextEncoder().encode(body).length,sources:[[uid(n+20000),'a'.repeat(64)]],courses:category==='course'?[uid(80000)]:[]};entries.push(e);if(category!=='course')bodies.set(e.id,body);}
 entries.sort((a,b)=>a.id.localeCompare(b.id));const ordinary=entries.filter(e=>e.category!=='course');
 const manifest={format:BOOKSHELF_FORMAT,...binding,snapshotId:uid(99000+sequence),sequence,contentFingerprint:await shelfHash({entries,courseBodyPolicy:'metadata_only'}),entries,courseBodyPolicy:'metadata_only',complete:true,bodyEntryCount:ordinary.length,bodyBytesTotal:ordinary.reduce((s,e)=>s+e.bodyBytes,0)};manifest.manifestHash=await shelfHash(manifest);
 const keys=['format','serverId','scope_id','snapshotId','sequence','contentFingerprint','manifestHash'],bind=Object.fromEntries(keys.map(k=>[k,manifest[k]])),pages=[];
 for(let i=0;i<ordinary.length;i+=32){const end=Math.min(ordinary.length,i+32);pages.push({...bind,offset:i,entries:ordinary.slice(i,end).map(e=>({id:e.id,revision:e.revision,bodyHash:e.bodyHash,bodyBytes:e.bodyBytes,body:bodies.get(e.id)})),next:end===ordinary.length?null:end,complete:end===ordinary.length});}
 const attemptId=uid(99999);return {binding,bodies,metadata:entries.map(e=>({...e,restriction:e.category==='course'?'study':'general',body_hash:e.bodyHash})),packet:{manifest,pages,attemptId,confirmation:{...bind,phase:'finalize',count:ordinary.length,bytes:manifest.bodyBytesTotal,pages:pages.length,transferDigest:await shelfHash(await Promise.all(pages.map(p=>shelfHash(p)))),attemptId,directoryChecked:true}}};
}
export function makeStorage(){const m=new Map();return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v)};}
export const response=text=>({choices:[{message:{content:JSON.stringify({text,emotion:'normal'})},finish_reason:'stop'}]});
