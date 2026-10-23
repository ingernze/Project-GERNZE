import {validateNote,revisionNode,memoryError} from './memory-records.mjs';
// Raw conversation and explicit notes stay distinct stores. One transaction commits
// a note revision and its context barrier; stale replies cannot pass that barrier.
export function validateSnapshot(value){
  if(!value||typeof value.id!=='string'||!value.id||value.id.length>100||!Array.isArray(value.messages)||value.messages.length%2)throw Error('会话记录无效。');
  for(let i=0;i<value.messages.length;i++)if(value.messages[i]?.role!==(i%2?'assistant':'user')||typeof value.messages[i]?.content!=='string'||value.messages[i].content.length>12000)throw Error('会话消息无效。');
  if(value.messageTimes!==undefined&&(!Array.isArray(value.messageTimes)||value.messageTimes.length!==value.messages.length||value.messageTimes.some(t=>t!==null&&(typeof t!=='string'||!Number.isFinite(Date.parse(t))))))throw Error('会话时间无效。');
  if(value.contextEpoch!==undefined&&(!Number.isSafeInteger(value.contextEpoch)||value.contextEpoch<0||!Number.isSafeInteger(value.contextStart)||value.contextStart<0||value.contextStart%2||value.contextStart>value.messages.length))throw Error('会话边界无效。');
  return structuredClone(value);
}
export function createChatJournal({indexedDB=globalThis.indexedDB,name='hebao-chat-journal-v1'}={}){
  let opening;
  function open(){
    if(!indexedDB)throw Error('手机会话存储不可用。');
    return opening??=new Promise((resolve,reject)=>{
      const r=indexedDB.open(name,3);r.onupgradeneeded=()=>{
        for(const [store,options] of [['sessions',{keyPath:'id'}],['meta',undefined],['notes',{keyPath:'id'}],['revisions',{keyPath:'revision'}],['summaries',{keyPath:'id'}],['notePending',{keyPath:'revision'}]])if(!r.result.objectStoreNames.contains(store))r.result.createObjectStore(store,options);
      };
      r.onerror=()=>{opening=null;reject(Error('手机会话存储未打开。'));};
      r.onblocked=()=>{opening=null;reject(Error('会话库正在升级，请重开莉宝。'));};
      r.onsuccess=()=>{r.result.onversionchange=()=>{r.result.close();opening=null;};resolve(r.result);};
    });
  }
  async function read(stores,enqueue){const db=await open();return new Promise((resolve,reject)=>{
    const tx=db.transaction(stores,'readonly');let result;
    enqueue(tx,v=>result=v);tx.oncomplete=()=>resolve(result);tx.onabort=tx.onerror=()=>reject(Error('本机记录读取失败。'));
  });}
  async function save(snapshot,{signal,expectedMemoryEpoch}={}){
    const value=validateSnapshot(snapshot);if(signal?.aborted)throw memoryError('已取消保存。','cancelled');const db=await open();
    return new Promise((resolve,reject)=>{
      if(signal?.aborted){reject(memoryError('已取消保存。','cancelled'));return;}
      const tx=db.transaction(['sessions','meta'],'readwrite');let changed=false;
      const abort=()=>{try{tx.abort();}catch{}};signal?.addEventListener('abort',abort,{once:true});
      const r=tx.objectStore('meta').get('memoryEpoch');r.onsuccess=()=>{
        if(expectedMemoryEpoch!==undefined&&(r.result??0)!==expectedMemoryEpoch){changed=true;tx.abort();return;}
        tx.objectStore('sessions').put(value);tx.objectStore('meta').put(value.id,'selected');
      };
      const done=fn=>{signal?.removeEventListener('abort',abort);fn();};
      tx.oncomplete=()=>done(resolve);tx.onabort=tx.onerror=()=>done(()=>reject(changed?memoryError('记忆已变化，本轮旧回复已作废。','context_changed'):Error('会话保存失败；请勿清除应用数据。')));
    });
  }
  async function load(){return read(['sessions','meta'],(tx,set)=>{set(null);const id=tx.objectStore('meta').get('selected');id.onsuccess=()=>{if(id.result){const r=tx.objectStore('sessions').get(id.result);r.onsuccess=()=>set(r.result?validateSnapshot(r.result):null);}};});}
  async function list(){return read('sessions',(tx,set)=>{const r=tx.objectStore('sessions').getAll();r.onsuccess=()=>set(r.result.map(validateSnapshot));});}
  async function context(sessionId){return read(['sessions','notes','meta','summaries'],(tx,set)=>{
    const v={epoch:0,records:[],session:null,summaries:[],summaryEnabled:true,summaryDays:7};set(v);
    tx.objectStore('meta').get('summaryDays').onsuccess=e=>v.summaryDays=e.target.result??7;
    tx.objectStore('meta').get('summaryClock:'+sessionId).onsuccess=e=>v.summaryClock=e.target.result;
    tx.objectStore('meta').get('summaryEnabled').onsuccess=e=>v.summaryEnabled=e.target.result!==false;
    tx.objectStore('summaries').getAll().onsuccess=e=>v.summaries=e.target.result.filter(s=>s.sessionId===sessionId);
    tx.objectStore('meta').get('summaryAttempt:'+sessionId).onsuccess=e=>v.summaryAttempt=e.target.result;
    tx.objectStore('meta').get('memoryEpoch').onsuccess=e=>v.epoch=e.target.result??0;
    tx.objectStore('notes').getAll().onsuccess=e=>v.records=e.target.result.filter(n=>!n.deleted);
    if(sessionId)tx.objectStore('sessions').get(sessionId).onsuccess=e=>v.session=e.target.result?validateSnapshot(e.target.result):null;
  });}
  async function changeNote(input,{id,revision,forget=false}={}){
    if(Boolean(id)!==Boolean(revision)||forget&&!id)throw memoryError('纠正或忘记需要原编号和版本。');
    const view=await context(),old=id?view.records.find(n=>n.id===id):null;
    if(id&&(!old||old.revision!==revision))throw memoryError('这条记忆已变化，请刷新后再改。','memory_conflict');
    const fields=forget?{title:'',body:'',kind:'other',event_date:'',chat_enabled:false,important:false}:validateNote(input);
    if(!old&&view.records.length>=100)throw memoryError('最多保存100条记忆，请先整理。');
    if(fields.chat_enabled&&view.records.filter(n=>n.chat_enabled&&n.id!==id).length>=6)throw memoryError('聊天最多参考6条记忆，请先取消一条。');
    const db=await open();
    // Stable local device identity; a future sync scope must come from pairing, not this value.
    const existingDevice=await read('meta',(tx,set)=>{tx.objectStore('meta').get('memoryDevice').onsuccess=e=>set(e.target.result);});
    const stamp=new Date().toISOString(),device=existingDevice||crypto.randomUUID();
    const record={id:id||crypto.randomUUID(),revision:crypto.randomUUID(),parent_revision:revision||null,device_id:device,...fields,created_at:old?.created_at||stamp,updated_at:stamp,deleted:forget};
    const node=await revisionNode(record);
    await new Promise((resolve,reject)=>{
      // Reuse the strict-durability guard already used by the device-event store.
      const tx=db.transaction(['notes','meta','revisions'],'readwrite',{durability:'strict'});let conflict=false,full=false;
      if(tx.durability!=='strict'){tx.abort();reject(Error('当前手机不支持可靠记忆保存，请先更新系统WebView。'));return;}
      const meta=tx.objectStore('meta'),r=meta.get('memoryEpoch');r.onsuccess=()=>{
        if((r.result??0)!==view.epoch){conflict=true;tx.abort();return;}
        const n=tx.objectStore('revisions').count();n.onsuccess=()=>{
          if(n.result>=8192){full=true;tx.abort();return;}
          tx.objectStore('notes').put(record);tx.objectStore('revisions').put(node);meta.put(view.epoch+1,'memoryEpoch');meta.put(device,'memoryDevice');
        };
      };
      tx.oncomplete=resolve;tx.onabort=tx.onerror=()=>reject(conflict?memoryError('记忆已变化，请刷新后重试。','memory_conflict'):Error(full?'记忆修订记录已满，请先导出整理。':'记忆未保存，原内容保留。'));
    });
    return record;
  }
  async function setting(key,value){
    if(key==='summaryDays'&&arguments.length>1&&(!Number.isSafeInteger(value)||value<1))throw Error('摘要间隔至少一天。');
    if(!['summaryEnabled','summaryDays','syncEnabled','lastSync','syncBinding','syncReport','layerSyncEnabled','layerSyncDays','layerLastSync','layerSyncBinding'].includes(key))throw Error('设置无效。');
    if(arguments.length>1){
      if(key==='layerSyncEnabled'&&typeof value!=='boolean')throw Error('同步开关无效。');
      if(key==='layerSyncDays'&&(!Number.isSafeInteger(value)||value<1||value>3650))throw Error('同步间隔须为1～3650天。');
      if(key==='layerLastSync'&&(!Number.isSafeInteger(value)||value<0))throw Error('同步时间无效。');
      if(key==='layerSyncBinding'&&(!value||Object.keys(value).sort().join()!=='scope_id,serverId'||!['scope_id','serverId'].every(k=>typeof value[k]==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value[k]))))throw Error('同步绑定无效。');
    }
    if(arguments.length===1)return read('meta',(tx,set)=>{tx.objectStore('meta').get(key).onsuccess=e=>set(e.target.result);});
    const db=await open();return new Promise((resolve,reject)=>{const tx=db.transaction('meta','readwrite');tx.objectStore('meta').put(value,key);tx.oncomplete=resolve;tx.onabort=tx.onerror=()=>reject(Error('设置未保存。'));});
  }
  async function claimSummary(plan,latest){const db=await open();return new Promise((resolve,reject)=>{
    const tx=db.transaction('meta','readwrite');let accepted=false;const meta=tx.objectStore('meta');
    meta.get('memoryEpoch').onsuccess=e=>{if((e.target.result??0)!==plan.epoch)return;
      meta.get('summaryAttempt:'+plan.sessionId).onsuccess=e=>{const a=e.target.result;if(a&&a.epoch===plan.epoch&&(latest<a.latest+6||Date.now()-(a.at||0)<86400000))return;meta.put({epoch:plan.epoch,latest,at:Date.now()},'summaryAttempt:'+plan.sessionId);accepted=true;};};
    tx.oncomplete=()=>resolve(accepted);tx.onabort=tx.onerror=()=>reject(Error('摘要状态未保存。'));
  });}
  async function commitSummary(plan){
    const {id,sessionId,epoch,start,end,text,anchors,sourceText,sourceAt,updatedAt}=plan;
    if(typeof text!=='string'||text.length>2000||start%2||end%2||end<=start)throw Error('摘要无效。');
    const db=await open();return new Promise((resolve,reject)=>{
      const tx=db.transaction(['meta','sessions','summaries'],'readwrite');let accepted=false;
      tx.objectStore('meta').get('memoryEpoch').onsuccess=e=>{if((e.target.result??0)!==epoch)return;
        tx.objectStore('sessions').get(sessionId).onsuccess=e=>{if(!e.target.result||JSON.stringify(e.target.result.messages.slice(start,end))!==sourceText)return;
          tx.objectStore('summaries').put({id,sessionId,epoch,start,end,text,anchors,sourceAt,updatedAt});tx.objectStore('meta').put(Date.now(),'summaryClock:'+sessionId);accepted=true;};};
      tx.oncomplete=()=>resolve(accepted);tx.onabort=tx.onerror=()=>reject(Error('摘要未保存，原文仍在。'));
    });
  }
  async function summaries(){return read('summaries',(tx,set)=>{tx.objectStore('summaries').getAll().onsuccess=e=>set(e.target.result);});}
  async function exportExchange(scope){return read(['notes','notePending','revisions','meta'],(tx,set)=>{
    const state={format:'hebao-memory-exchange',version:1,scope_id:scope,records:[],revisions:[],epoch:0};set(state);
    tx.objectStore('notes').getAll().onsuccess=e=>state.records.push(...e.target.result);
    tx.objectStore('notePending').getAll().onsuccess=e=>state.records.push(...e.target.result);
    tx.objectStore('revisions').getAll().onsuccess=e=>state.revisions=e.target.result;
    tx.objectStore('meta').get('memoryEpoch').onsuccess=e=>state.epoch=e.target.result??0;
  });}
  async function applyExchange(result,expectedEpoch,binding){
    const db=await open();return new Promise((resolve,reject)=>{
      const tx=db.transaction(['meta','notes','notePending','revisions'],'readwrite',{durability:'strict'});let conflict=false,changed=false;
      if(tx.durability!=='strict'){tx.abort();reject(Error('当前WebView不支持可靠记忆保存。'));return;}
      const meta=tx.objectStore('meta');meta.get('memoryEpoch').onsuccess=e=>{if((e.target.result??0)!==expectedEpoch){conflict=true;tx.abort();return;}
        const notes=tx.objectStore('notes');notes.getAll().onsuccess=e=>{
          const projection=new Map(result.active_records.map(r=>[r.id,r]));
          for(const r of result.snapshot.records)if(r.deleted&&!projection.has(r.id))projection.set(r.id,r);
          const previous=JSON.stringify(e.target.result.sort((a,b)=>a.id.localeCompare(b.id))),next=[...projection.values()].sort((a,b)=>a.id.localeCompare(b.id));
          changed=previous!==JSON.stringify(next);notes.clear();for(const r of next)notes.put(r);
          const pending=tx.objectStore('notePending');pending.clear();for(const r of result.snapshot.records)if(projection.get(r.id)?.revision!==r.revision)pending.put(r);
          const revisions=tx.objectStore('revisions');revisions.clear();for(const n of result.snapshot.revisions)revisions.put(n);
          if(changed)meta.put(expectedEpoch+1,'memoryEpoch');meta.put(binding,'syncBinding');meta.put(Date.now(),'lastSync');meta.put({status:result.status,conflicts:result.conflicts,limits:result.limits,fingerprint:result.fingerprint},'syncReport');
        };
      };
      tx.oncomplete=()=>resolve({changed});tx.onabort=tx.onerror=()=>reject(memoryError(conflict?'同步期间记忆有新改动，已保留，稍后重试。':'同步结果未保存。',conflict?'memory_conflict':'memory_invalid'));
    });
  }
  return Object.freeze({save,load,list,context,changeNote,setting,claimSummary,commitSummary,summaries,exportExchange,applyExchange,async close(){if(opening)(await opening).close();opening=null;}});
}
