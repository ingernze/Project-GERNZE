import {createLayeredMemory} from '../src/memory-layer-store.mjs';
import {buildMessages} from '../src/chat-core.mjs';
const result=document.getElementById('result'),checks=[],ns='gernze-regression-'+crypto.randomUUID();
const core={schemaVersion:1,entries:[{key:'fixed',body:'合成固定核心'}]};let a,b;
function ok(name,condition){if(!condition)throw Error(name);checks.push(name);result.textContent=checks.join('\n');}
async function rejects(name,fn){let threw=false;try{await fn();}catch{threw=true;}ok(name,threw);}
const source=(id,text)=>({id,sessionId:'synthetic',epoch:0,start:0,end:2,text,updatedAt:new Date().toISOString()});
try{
 a=createLayeredMemory({core,namespace:ns});
 ok('普通聊天无审批权限',!a.chat.decide&&!a.chat.removeApproved);
 await a.chat.syncSummaries([source('a','旧说法A')]);
 const row=(await a.review.list()).pending[0],old={key:row.key,revision:row.revision,action:'approve'},correct={...old,action:'correct',text:'纠正B'};
 await a.review.decide([correct]);
 await rejects('旧批准不能覆盖纠正',()=>a.review.decide([old]));
 ok('纠正内容保持B',(await a.review.list()).approved[0].body==='纠正B');
 const duplicate=await a.review.decide([correct]);ok('同一纠正重复导入幂等',duplicate.applied===0&&duplicate.alreadyProcessed===1);
 let approved=(await a.review.list()).approved[0];await a.review.removeApproved(approved.key,approved.revision);
 await a.review.decide([correct]);await rejects('旧批准不能恢复已移出条目',()=>a.review.decide([old]));
 ok('移出仍然有效',(await a.review.list()).approved[0].deleted===true);
 ok('审批收据隐藏已处理候选',(await a.review.list()).pending.length===0);
 await a.close();a=createLayeredMemory({core,namespace:ns});
 await a.review.decide([correct]);ok('关闭重开后仍防复活',(await a.review.list()).approved[0].deleted===true);
 await a.chat.syncSummaries([source('a','新的来源C')]);let fresh=(await a.review.list()).pending[0];
 await rejects('原候选版本已过期',()=>a.review.decide([old]));
 await a.review.decide([{key:fresh.key,revision:fresh.revision,action:'correct',text:'用户本轮批准D'}]);
 ok('新来源可显式批准',(await a.review.list()).approved[0].body==='用户本轮批准D');
 await a.chat.syncSummaries([source('a','较早待审E')]);fresh=(await a.review.list()).pending[0];approved=(await a.review.list()).approved[0];
 await a.review.removeApproved(approved.key,approved.revision);
 await rejects('第二层变化后拒绝旧基线审批',()=>a.review.decide([{key:fresh.key,revision:fresh.revision,action:'approve'}]));
 await a.chat.syncSummaries([source('b','并发候选')]);fresh=(await a.review.list()).pending.find(e=>e.key==='summary:b');
 b=createLayeredMemory({core,namespace:ns});
 const first={key:fresh.key,revision:fresh.revision,action:'approve'},second={...first,action:'correct',text:'不同决定'};
 const race=await Promise.allSettled([a.review.decide([first]),b.review.decide([second])]);
 ok('两个实例同时审批只接受一个决定',race.filter(r=>r.status==='fulfilled').length===1);
 await a.chat.syncSummaries([source('c','批量新候选')]);fresh=(await a.review.list()).pending.find(e=>e.key==='summary:c');
 await rejects('无效批次整体拒绝',()=>a.review.decide([{key:fresh.key,revision:fresh.revision,action:'approve'},old]));
 ok('批次失败不部分写入',!(await a.review.list()).approved.some(e=>e.key==='summary:c'));
 const payload=buildMessages([{role:'user',content:'合成当前输入'}],'合成人设',{layers:{core,approved:[],working:[]}});
 ok('输出协议只注入一次',(payload[0].content.match(/输出JSON对象/g)||[]).length===1);
 ok('固定核心和本轮输入保留',payload[0].content.includes('合成固定核心')&&payload.at(-1).content==='合成当前输入');
 ok('第一层未改写',(await a.review.list()).core.entries[0].body==='合成固定核心');
 result.textContent='PASS '+checks.length+' 项\n'+checks.join('\n')+'\n无真实API或用户库写入。';result.dataset.status='passed';
}catch(error){result.textContent='FAIL '+error.stack+'\n'+checks.join('\n');result.dataset.status='failed';}
finally{await a?.close();await b?.close();for(const area of ['working','approved'])indexedDB.deleteDatabase(ns+'-'+area);}
