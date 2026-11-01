import {createResearchCache} from './research-cache.mjs';
import {validateUse,hashText,sourceMetadata} from './research-use.mjs';
import {pickSummary,summaryBlocked} from './summary-policy.mjs';
import {canonical,validateNote,revisionNode,memoryError} from './memory-records.mjs';
// Raw conversation and explicit notes stay distinct stores. One transaction commits
// a note revision and its context barrier; stale replies cannot pass that barrier.
export function validateSnapshot(value){
  if(!value||typeof value.id!=='string'||!value.id||value.id.length>100||!Array.isArray(value.messages)||value.messages.length%2)throw Error('会话记录无效。');
  for(let i=0;i<value.messages.length;i++)if(value.messages[i]?.role!==(i%2?'assistant':'user')||typeof value.messages[i]?.content!=='string'||value.messages[i].content.length>12000)throw Error('会话消息无效。');
  if(value.messageTimes!==undefined&&(!Array.isArray(value.messageTimes)||value.messageTimes.length!==value.messages.length||value.messageTimes.some(t=>t!==null&&(typeof t!=='string'||!Number.isFinite(Date.parse(t))))))throw Error('会话时间无效。');
  if(value.contextEpoch!==undefined&&(!Number.isSafeInteger(value.contextEpoch)||value.contextEpoch<0||!Number.isSafeInteger(value.contextStart)||value.contextStart<0||value.contextStart%2||value.contextStart>value.messages.length))throw Error('会话边界无效。');
  if(value.researchRanges!==undefined){
    let last=-2;const ids=new Set();
    if(!Array.isArray(value.researchRanges))throw Error('研究原文范围无效。');
    for(const r of value.researchRanges){
      if(!r||Object.keys(r).sort().join()!=='requestId,start'||!Number.isSafeInteger(r.start)||r.start%2||r.start<=last||r.start+1>=value.messages.length||typeof r.requestId!=='string'||!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(r.requestId)||ids.has(r.requestId))throw Error('研究原文范围无效。');
      last=r.start;ids.add(r.requestId);
    }
  }
  return structuredClone(value);
}
export function createChatJournal({indexedDB=globalThis.indexedDB,name='hebao-chat-journal-v1'}={}){
  let opening;
  function open(){
    if(!indexedDB)throw Error('手机会话存储不可用。');
    return opening??=new Promise((resolve,reject)=>{
      const r=indexedDB.open(name,5);let blocked=false;r.onupgradeneeded=()=>{
        for(const [store,options] of [['sessions',{keyPath:'id'}],['meta',undefined],['notes',{keyPath:'id'}],['revisions',{keyPath:'revision'}],['summaries',{keyPath:'id'}],['notePending',{keyPath:'revision'}],['metadata',undefined],['bodies',undefined],['state',undefined],['researchMessages',{keyPath:'key'}]])if(!r.result.objectStoreNames.contains(store))r.result.createObjectStore(store,options);
      };
      r.onerror=()=>{opening=null;reject(Error('手机会话存储未打开。'));};
      r.onblocked=()=>{blocked=true;opening=null;reject(Error('会话库正在升级，请重开莉宝。'));};
      r.onsuccess=()=>{if(blocked){r.result.close();return;}r.result.onversionchange=()=>{r.result.close();opening=null;};resolve(r.result);};
    });
  }
  async function read(stores,enqueue){const db=await open();return new Promise((resolve,reject)=>{
    const tx=db.transaction(stores,'readonly');let result;
    enqueue(tx,v=>result=v);tx.oncomplete=()=>resolve(result);tx.onabort=tx.onerror=()=>reject(Error('本机记录读取失败。'));
  });}
  const researchCache=createResearchCache({indexedDB,database:open});
  async function save(snapshot,{signal,expectedMemoryEpoch,expectedSession,researchUse=null}={}){
    const value=validateSnapshot(snapshot);
    if(researchUse){researchUse=structuredClone(researchUse);validateUse(researchUse,value);if(value.messages.length<2||await hashText(value.messages.at(-2).content)!==researchUse.request.inputHash)throw memoryError('研究提问与来源凭据不符。','context_changed');}
    if(signal?.aborted)throw memoryError('已取消保存。','cancelled');const db=await open();
    return new Promise((resolve,reject)=>{
      if(signal?.aborted){reject(memoryError('已取消保存。','cancelled'));return;}
      const tx=db.transaction(['sessions','meta','metadata','state','researchMessages'],'readwrite',{durability:'strict'});let changed=false,error;
      const abort=()=>{try{tx.abort();}catch{}};
      const conflict=()=>{changed=true;abort();};
      const guard=fn=>{try{fn();}catch(e){error=e;abort();}};
      signal?.addEventListener('abort',abort,{once:true});
      const done=fn=>{signal?.removeEventListener('abort',abort);fn();};
      tx.oncomplete=()=>done(resolve);tx.onabort=()=>done(()=>reject(signal?.aborted?memoryError('已取消保存。','cancelled'):changed?memoryError('记忆或资料已变化，本轮旧回复已作废。','context_changed'):error||Error('会话保存失败；请勿清除应用数据。')));tx.onerror=()=>{};
      const meta=tx.objectStore('meta'),sessions=tx.objectStore('sessions');
      meta.get('memoryEpoch').onsuccess=e=>guard(()=>{
        if(expectedMemoryEpoch!==undefined&&(e.target.result??0)!==expectedMemoryEpoch){conflict();return;}
        sessions.get(value.id).onsuccess=e=>guard(()=>{
          const previous=e.target.result||null;
          if((researchUse||previous?.researchRanges?.length)&&tx.durability!=='strict'){error=Error('当前WebView不支持可靠研究原文保存。');abort();return;}
          if(expectedSession!==undefined&&canonical(previous)!==canonical(expectedSession)){conflict();return;}
          const ranges=structuredClone(previous?.researchRanges||[]);
          if(value.researchRanges&&canonical(value.researchRanges)!==canonical(ranges)){conflict();return;}
          if(ranges.some(r=>r.start+1>=value.messages.length)){conflict();return;}
          for(const r of ranges){value.messages[r.start]={role:'user',content:''};value.messages[r.start+1]={role:'assistant',content:''};
            if(value.messageTimes)for(const i of [r.start,r.start+1])value.messageTimes[i]=previous.messageTimes?.[i]??null;}
          const commit=()=>{
            if(ranges.length)value.researchRanges=ranges;else delete value.researchRanges;
            meta.get('summaryClock:'+value.id).onsuccess=e=>guard(()=>{
              if(e.target.result===undefined){const old=previous||value,first=old.messageTimes?.find(t=>t&&Number.isFinite(Date.parse(t)))||old.updatedAt,clock=Date.parse(first);if(Number.isFinite(clock))meta.put(clock,'summaryClock:'+value.id);}
              sessions.put(value);meta.put(value.id,'selected');
            });
          };
          if(!researchUse){commit();return;}
          const index=value.messages.length-2;
          if(previous&&index!==previous.messages.length||ranges.some(r=>r.start===index||r.requestId===researchUse.request.id)){conflict();return;}
          tx.objectStore('state').get('snapshot').onsuccess=e=>guard(()=>{
            const state=e.target.result;
            if(!state||canonical({serverId:state.serverId,scope_id:state.scope_id,sequence:state.sequence,fingerprint:state.fingerprint})!==canonical(researchUse.cache)){conflict();return;}
            tx.objectStore('metadata').get(researchUse.source.id).onsuccess=e=>guard(()=>{
              if(!e.target.result||canonical(sourceMetadata(e.target.result))!==canonical(researchUse.source)){conflict();return;}
              const key=JSON.stringify([value.id,index]),messages=value.messages.slice(index),messageTimes=value.messageTimes?.slice(index)||[null,null];
              tx.objectStore('researchMessages').put({key,sessionId:value.id,start:index,messages,messageTimes,receipt:structuredClone(researchUse)});
              ranges.push({start:index,requestId:researchUse.request.id});value.messages[index]={role:'user',content:''};value.messages[index+1]={role:'assistant',content:''};commit();
            });
          });
        });
      });
    });
  }
  async function load(){return read(['sessions','meta'],(tx,set)=>{set(null);const id=tx.objectStore('meta').get('selected');id.onsuccess=()=>{if(id.result){const r=tx.objectStore('sessions').get(id.result);r.onsuccess=()=>{const v=r.result?validateSnapshot(r.result):null;if(v)for(const range of v.researchRanges||[]){v.messages[range.start].content='研究提问已保存在原文书架。';v.messages[range.start+1].content='研究回答已保存在原文书架。';}set(v);};}};});}
  async function readResearchTurn(sessionId,start){return read(['sessions','researchMessages'],(tx,set)=>{
    set(null);tx.objectStore('sessions').get(sessionId).onsuccess=e=>{
      const range=e.target.result?.researchRanges?.find(r=>r.start===start);if(!range)return;
      tx.objectStore('researchMessages').get(JSON.stringify([sessionId,start])).onsuccess=e=>{
        const raw=e.target.result;if(raw&&raw.sessionId===sessionId&&raw.start===start&&raw.receipt?.request?.id===range.requestId)set(structuredClone(raw));
      };
    };
  });}
  async function list(){return read('sessions',(tx,set)=>{const r=tx.objectStore('sessions').getAll();r.onsuccess=()=>set(r.result.map(validateSnapshot));});}
  async function context(sessionId){return read(['sessions','notes','meta','summaries'],(tx,set)=>{
    const v={epoch:0,records:[],session:null,summaries:[],summaryEnabled:true,summaryDays:7};set(v);
    tx.objectStore('meta').get('summaryDays').onsuccess=e=>v.summaryDays=e.target.result??7;
    tx.objectStore('meta').get('summaryClock:'+sessionId).onsuccess=e=>v.summaryClock=e.target.result;
    tx.objectStore('meta').get('summaryCycle:'+sessionId).onsuccess=e=>v.summaryCycle=e.target.result;
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
  // Read and validate the scheduling view inside the same write transaction as the claim/commit.
  function summaryView(tx,sessionId,ready){
    const view={epoch:0,summaries:[],session:null};let pending=7;
    const get=(store,key,assign)=>{const r=key===undefined?tx.objectStore(store).getAll():tx.objectStore(store).get(key);r.onsuccess=()=>{assign(r.result);if(!--pending)ready(view);};};
    get('meta','memoryEpoch',v=>view.epoch=v??0);
    get('meta','summaryEnabled',v=>view.summaryEnabled=v!==false);
    get('meta','summaryDays',v=>view.summaryDays=v??7);
    get('meta','summaryClock:'+sessionId,v=>view.summaryClock=v);
    get('meta','summaryCycle:'+sessionId,v=>view.summaryCycle=v);
    get('sessions',sessionId,v=>view.session=v);
    get('summaries',undefined,v=>view.summaries=v.filter(s=>s.sessionId===sessionId));
  }
  const matches=(plan,next)=>next&&plan.id===next.id&&plan.sessionId===next.sessionId&&plan.epoch===next.epoch&&plan.start===next.start&&plan.end===next.end&&plan.sourceText===next.sourceText&&plan.cycle?.id===next.cycle.id&&plan.cycle.epoch===next.cycle.epoch&&plan.cycle.end===next.cycle.end;
  async function claimSummary(plan,latest){const db=await open();return new Promise((resolve,reject)=>{
    const tx=db.transaction(['meta','sessions','summaries'],'readwrite');let accepted=false;const meta=tx.objectStore('meta');
    summaryView(tx,plan.sessionId,view=>{
      if(!matches(plan,pickSummary(view))||latest!==view.session.messages.length)return;
      meta.get('summaryAttempt:'+plan.sessionId).onsuccess=e=>{
        const a=e.target.result;
        // Only a committed success unlocks the next source range. Pending/failed/legacy claims keep the existing bill guard.
        if(a&&a.epoch===plan.epoch&&a.status!=='success'&&(latest<a.latest+6||Date.now()-(a.at||0)<86400000))return;
        meta.put(plan.cycle,'summaryCycle:'+plan.sessionId);
        const claimId=crypto.randomUUID();plan.claimId=claimId;
        meta.put({id:plan.id,claimId,epoch:plan.epoch,latest,at:Date.now(),status:'pending'},'summaryAttempt:'+plan.sessionId);accepted=true;
      };
    });
    tx.oncomplete=()=>resolve(accepted);tx.onabort=tx.onerror=()=>reject(Error('摘要状态未保存。'));
  });}
  async function commitSummary(plan,{signal}={}){
    const {id,sessionId,epoch,start,end,text,anchors,sourceText,sourceAt,updatedAt}=plan;
    if(typeof text!=='string'||text.length>2000||start%2||end%2||end<=start)throw Error('摘要无效。');
    if(signal?.aborted)return false;const db=await open();if(signal?.aborted)return false;
    return new Promise((resolve,reject)=>{
      const tx=db.transaction(['meta','sessions','summaries'],'readwrite');let accepted=false;
      const abort=()=>{try{tx.abort();}catch{}};signal?.addEventListener('abort',abort,{once:true});
      summaryView(tx,sessionId,view=>{
        if(signal?.aborted||!matches(plan,pickSummary(view)))return;
        const meta=tx.objectStore('meta');meta.get('summaryAttempt:'+sessionId).onsuccess=e=>{
          const attempt=e.target.result;if(signal?.aborted||attempt?.id!==id||attempt.claimId!==plan.claimId||attempt.status!=='pending')return;
          const saved={id,sessionId,epoch,start,end,text,anchors,sourceAt,updatedAt};
          tx.objectStore('summaries').put(saved);meta.put({...attempt,status:'success'},'summaryAttempt:'+sessionId);
          // Clock moves only when this frozen cycle has no eligible old batch left.
          const nextView={...view,summaries:[...view.summaries,saved]};
          if(!pickSummary(nextView)&&!summaryBlocked(nextView)){
            meta.delete('summaryCycle:'+sessionId);meta.put(Date.now(),'summaryClock:'+sessionId);
          }
          accepted=true;
        };
      });
      const done=fn=>{signal?.removeEventListener('abort',abort);fn();};
      tx.oncomplete=()=>done(()=>resolve(accepted));tx.onabort=tx.onerror=()=>done(()=>signal?.aborted?resolve(false):reject(Error('摘要未保存，原文仍在。')));
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
  return Object.freeze({researchVersion:1,researchCache,readResearchTurn,save,load,list,context,changeNote,setting,claimSummary,commitSummary,summaries,exportExchange,applyExchange,async close(){if(opening)(await opening).close();opening=null;}});
}
