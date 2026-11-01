import {NativeChatDouble} from './bridge.mjs';
import {cases} from './cases.mjs';
// Real page renderer; only Capacitor and external inputs are replaced by the lab.
import '../../www/dialogue-page.js';
(async()=>{
const which=new URL(location.href).searchParams.get('case')||'priority';
const prefix='gernze-native-ui-'+crypto.randomUUID()+'-',rawDB=window.indexedDB,names=new Set(),connections=new Set(),checks=[],events=[];
const actualSetTimeout=window.setTimeout.bind(window),sleep=ms=>new Promise(r=>actualSetTimeout(r,ms));
const check=(name,value)=>{if(!value)throw Error(name);checks.push(name);};
const until=async(fn,label,ms=6000)=>{const end=performance.now()+ms;while(performance.now()<end){if(await fn())return;await sleep(20);}throw Error('等待超时：'+label);};
const core={schemaVersion:1,entries:[{key:'synthetic.core',body:'合成只读核心，不能被模型改写。'}]};
const approved={key:'synthetic.approved',revision:crypto.randomUUID(),body:'合成电脑已审核条目',deleted:false,updatedAt:new Date().toISOString(),reviewedBy:'owner-paired-review'};
const clonedCore=JSON.stringify(core),clonedApproved=JSON.stringify(approved);
let saveShouldFail=false;
const originalPut=IDBObjectStore.prototype.put;
IDBObjectStore.prototype.put=function(value,...args){if(saveShouldFail&&this.name==='sessions'&&value?.lastRequestId)throw new DOMException('合成存储失败','QuotaExceededError');return originalPut.call(this,value,...args);};
// Isolate every default database name without replacing journal, transactions, or layered-memory logic.
Object.defineProperty(window,'indexedDB',{configurable:true,value:{open(name,version){const mapped=prefix+name;names.add(mapped);const r=version===undefined?rawDB.open(mapped):rawDB.open(mapped,version);r.addEventListener('success',()=>connections.add(r.result));return r;},deleteDatabase(name){return rawDB.deleteDatabase(prefix+name);}}});
// No production endpoint, pairing state, key, persona, or personal memory is consulted.
window.fetch=async input=>{const file=String(input).split('/').at(-1);if(file==='chat-persona.txt')return new Response('你是合成联调人物，不做任何真实模型请求。');if(file==='chat-core-memory.json')return new Response(JSON.stringify(core),{headers:{'content-type':'application/json'}});throw Error('联调禁止外部请求：'+String(input));};
const storage=new Map();Object.defineProperty(window,'localStorage',{configurable:true,value:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,String(v)),removeItem:k=>storage.delete(k)}});
const journalRead=async(store,key,dbName='hebao-chat-journal-v1')=>{
 const db=await new Promise((resolve,reject)=>{const r=rawDB.open(prefix+dbName);r.onsuccess=()=>{connections.add(r.result);resolve(r.result);};r.onerror=()=>reject(r.error);});
 return new Promise((resolve,reject)=>{const tx=db.transaction(store,'readonly'),r=key===undefined?tx.objectStore(store).getAll():tx.objectStore(store).get(key);tx.oncomplete=()=>resolve(r.result);tx.onabort=()=>reject(tx.error);});
};
const summaries=()=>journalRead('summaries');
const sessionId='synthetic-session',old=new Date(Date.now()-8*86400000).toISOString();
const raw={id:sessionId,contextEpoch:0,contextStart:0,messages:Array.from({length:40},(_,i)=>[{role:'user',content:'合成旧提问'+i},{role:'assistant',content:'合成旧回答'+i}]).flat(),messageTimes:Array(80).fill(old),updatedAt:old};
const seed=async()=>{
 const {createChatJournal}=await import('../../src/chat-journal.mjs');const j=createChatJournal();await j.save(raw);await j.setting('layerSyncEnabled',false);await j.close();
 await new Promise((resolve,reject)=>{const r=indexedDB.open('hebao-layers-v1-approved',2);r.onupgradeneeded=()=>{r.result.createObjectStore('entries',{keyPath:'key'});r.result.createObjectStore('working',{keyPath:'key'});r.result.createObjectStore('meta');};r.onsuccess=()=>{const tx=r.result.transaction(['entries','meta'],'readwrite');tx.objectStore('entries').put(approved);tx.objectStore('meta').put(true,'workingMigratedV2');tx.oncomplete=resolve;tx.onabort=()=>reject(tx.error);};r.onerror=()=>reject(r.error);});
};
const bridge=new NativeChatDouble({onRequest(task,b){
 events.push({type:'ui-at-request',purpose:task.purpose,id:task.id,replyShown:document.querySelector('.dl-log')?.textContent.includes('合成回复')||false,pending:window.HebaoDialogueController?.getSnapshot().pending});
 if(task.purpose==='chat')setTimeout(()=>b.finish(task.id),70);
}});window.__nativeUiBridge=bridge;
const sent=purpose=>bridge.events.filter(e=>e.type==='request'&&e.purpose===purpose);
const lastSummary=()=>sent('summary').at(-1);
const uiSend=async text=>{const input=document.querySelector('.dl-compose textarea');input.value=text;input.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('.dl-compose').requestSubmit();await until(()=>sent('chat').length>0,'实际表单触发chat');};
const replyVisible=()=>document.querySelector('.dl-log').textContent.includes('合成回复');
const click=id=>document.getElementById(id).click();
let result;
try{
 await seed();const {mountChat}=await import('../../src/native-chat.js');
 window.HebaoDialogueController=window.HebaoDialoguePage.mount({container:document.getElementById('dialogue'),...window.HebaoDialogueOptions,portraitSrc:'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>',sceneSrc:'',artSceneSrc:''});
 window.HebaoDialogueController.setVisible(true);mountChat();
 await until(()=>document.querySelector('.hebao-dialogue')?.dataset.chatReady==='true','真实native-chat挂载');
 check('未自动调用API',sent('chat').length===0&&sent('summary').length===0);
 if(which==='save-failure')saveShouldFail=true;
 if(which==='cancel-chat'){
   bridge.onRequest=()=>{};await uiSend('合成停止聊天');const id=sent('chat')[0].id;bridge.queueDelivery(id);document.querySelector('.dl-send').click();bridge.deliverQueued(id);await sleep(100);
   check('停止按钮取消等待',!window.HebaoDialogueController.getSnapshot().pending);check('停止后旧回复不落库',(await journalRead('sessions',sessionId)).messages.length===80);check('停止后不触发摘要',sent('summary').length===0);
 }else{
   await uiSend('合成本轮输入');await until(replyVisible,'回复展示');
   if(which==='save-failure'){
     await until(()=>document.getElementById('chatStatus').textContent.includes('未保存成功'),'保存失败提示');await sleep(80);check('保存失败仍显示已付费回复',replyVisible());check('未保存时没有摘要调用',sent('summary').length===0);check('旧原文仍在',(await journalRead('sessions',sessionId)).messages.length===80);
   }else{
     await until(()=>lastSummary(),'第一次摘要调用');const first=lastSummary(),saved=await journalRead('sessions',sessionId);
     check('触发摘要前原文已可靠保存',saved.messages.length===82&&!!saved.lastRequestId);check('摘要完整输入不超16000字节',first.inputBytes<=16000);
     if(which==='priority'){
       const timing=events.find(e=>e.purpose==='summary');check('摘要开始前回复已展示',timing.replyShown&&!timing.pending);
       bridge.finish(first.id);await until(()=>sent('summary').length===2,'第二次摘要');bridge.finish(lastSummary().id);await until(async()=> (await summaries()).length===2,'两批提交');await sleep(120);check('最多两次摘要',sent('summary').length===2);check('最近六轮仍留原文',(await journalRead('sessions',sessionId)).messages.length===82);
     }else if(which==='resume'){
       const count=sent('chat').length;await uiSend('合成再次发送');await until(()=>sent('chat').length===count+1,'新chat抢占');check('匹配摘要id被取消',bridge.events.some(e=>e.type==='cancel'&&e.id===first.id&&e.matched));check('取消完成先于新chat',bridge.events.findIndex(e=>e.type==='rejected-cancelled'&&e.id===first.id)<bridge.events.findIndex(e=>e.type==='request'&&e.purpose==='chat'&&e.id!==saved.lastRequestId));check('没有busy碰撞',!bridge.events.some(e=>e.type==='busy'));
     }else if(which==='native-busy'){
       bridge.cancelMode='hold';const count=sent('chat').length;await uiSend('合成等待底层停止');await until(()=>document.querySelector('.dl-turn.is-failed, .dl-retry, [data-state="failed"]')||!window.HebaoDialogueController.getSnapshot().pending,'忙碌返回',3000);await sleep(50);check('未重叠启动新chat',sent('chat').length===count);check('原生单槽仍由旧摘要持有',bridge.active?.id===first.id);check('已请求取消旧槽',bridge.events.some(e=>e.type==='cancel'&&e.id===first.id));bridge.finish(first.id);
     }else if(which==='timeout'){
       // Production 18s JS deadline; do not shorten production timeouts or make the double auto-release on abort.
       bridge.cancelMode='hold';await until(()=>bridge.events.some(e=>e.type==='cancel'&&e.id===first.id),'18秒摘要超时',21000);check('超时主动取消同id原生请求',bridge.events.some(e=>e.type==='cancel'&&e.id===first.id&&e.matched));bridge.finish(first.id);await sleep(120);check('超时结果不入库',(await summaries()).length===0);check('超时不续第二批',sent('summary').length===1);
     }else if(which==='layers'){
       bridge.finish(first.id);await until(()=>sent('summary').length===2,'第二批');bridge.finish(lastSummary().id);await until(async()=> (await summaries()).length===2,'摘要提交');const layerRows=await journalRead('entries',undefined,'hebao-layers-v1-approved');check('第一层合成输入未改写',JSON.stringify(core)===clonedCore);check('第二层未被模型字段改写',JSON.stringify(layerRows)===JSON.stringify([JSON.parse(clonedApproved)]));check('手机未出现审批写入口',!document.querySelector('[data-approve]'));
     }else{
       // Reproduce a response already resolved by native but delivered to JS after the stop event.
       bridge.queueDelivery(first.id);
       if(which==='disable')click('chatAutoSummary');
       if(which==='session')click('chatNewSession');
       if(which==='visibility'){Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));}
       if(which==='app')window.dispatchEvent(new CustomEvent('hebao:app-active',{detail:false}));
       if(which==='pagehide')window.dispatchEvent(new Event('pagehide'));
       bridge.deliverQueued(first.id);await sleep(150);check('晚到摘要未保存',(await summaries()).length===0);check('没有启动后续批次',sent('summary').length===1);
       if(which==='disable')check('关闭状态已保存',(await journalRead('meta','summaryEnabled'))===false);
       if(which==='session')check('新会话已切换',window.HebaoDialogueController.getSnapshot().id!==sessionId);
       if(which==='pagehide')check('传输已解除',document.querySelector('.hebao-dialogue').dataset.chatReady==='false');
     }
   }
 }
 check('没有模型字段越权更新L1',JSON.stringify(core)===clonedCore);
 result={case:which,name:cases.find(c=>c[0]===which)?.[1],status:'passed',checks,events:[...bridge.events,...events],realProviderCalls:0,realAndroid:false,bridge:'synthetic contract double',browserUI:true};
}catch(error){result={case:which,status:'failed',checks,error:error.stack,events:[...bridge.events,...events],realProviderCalls:0,realAndroid:false,browserUI:true};}
finally{
 saveShouldFail=false;window.dispatchEvent(new Event('pagehide'));await bridge.dispose();await sleep(50);for(const db of connections)try{db.close();}catch{}
 const cleanup=[];for(const name of names){cleanup.push(await new Promise(resolve=>{const r=rawDB.deleteDatabase(name);r.onsuccess=()=>resolve({name,status:'deleted'});r.onerror=()=>resolve({name,status:'failed',error:String(r.error)});r.onblocked=()=>resolve({name,status:'blocked'});}));}
 result.cleanup=cleanup;if(cleanup.some(r=>r.status!=='deleted')){result.status='failed';result.cleanupFailure=true;}
 document.getElementById('local-result').textContent=JSON.stringify(result,null,2);parent.postMessage({type:'gernze-native-ui-result',result},'*');
}

})().catch(error=>{document.getElementById('local-result').textContent=error.stack;parent.postMessage({type:'gernze-native-ui-result',result:{status:'failed',error:error.stack,realProviderCalls:0,realAndroid:false}},'*');});
