import protocol from '../../src/workbench/chat-protocol.json' with {type:'json'};
import {layersPrompt} from './memory-layers.mjs';
import {prepareSummary,selectSummaries,summaryPrompt} from './summary-policy.mjs';
import {notePrompt} from './memory-records.mjs';
// Provider-neutral text chat. Native bridge owns credentials and HTTPS; no tool execution.
const fail=(message,code='chat_failed')=>Object.assign(Error(message),{code});
const bytes=s=>new TextEncoder().encode(s).length;
export function buildMessages(messages,persona,{budget=32768,reserve=4096,notes=[],summaries=[],layers=null}={}){
  if(!Array.isArray(messages)||!messages.length||messages.length%2!==1)throw fail('对话轮次不完整。');
  if(typeof persona!=='string'||!persona.trim()||persona.length>8000)throw fail('人物设定未准备好。');
  const history=messages.map((m,i)=>{
    if(!m||m.role!==(i%2?'assistant':'user')||typeof m.content!=='string'||!m.content.trim()||m.content.length>12000)throw fail('对话内容无效。');
    return {role:m.role,content:m.content};
  });
  const kept=summaries.slice(),layerView=layers?{...layers,approved:[...(layers.approved||[])],working:[...(layers.working||[])]}:null;
  const outputProtocol='\n'+protocol.instruction;
  const system={role:'system',content:''},current=history.at(-1),room=budget-reserve;
  const cost=items=>bytes(JSON.stringify(items))+items.length*64;
  const rebuild=()=>system.content=(layerView?'第一层 · 只读核心人设：\n':'')+persona+(layerView?layersPrompt(layerView):'')+notePrompt(notes)+summaryPrompt(kept)+outputProtocol;
  rebuild();let selected=[system,current];
  while(cost(selected)>room){if(kept.length)kept.shift();else if(layerView?.working.length)layerView.working.pop();else if(layerView?.approved.length)layerView.approved.pop();else break;rebuild();}
  if(room<=0||cost(selected)>room)throw fail('这条消息超出当前上下文预算，请缩短后发送。','budget_exceeded');
  for(let i=history.length-3;i>=0;i-=2){const next=[system,...history.slice(i,i+2),...selected.slice(1)];if(cost(next)>room)break;selected=next;}
  return selected;
}
export function normalizeReply(response){
  if(!response||typeof response!=='object')throw fail('服务没有返回有效回复。');
  const choice=response.choices?.[0];
  if(!choice||!['stop',undefined,null].includes(choice.finish_reason))throw fail('回复未完整生成，请重试。');
  let text=choice.message?.content;if(typeof text!=='string'||!text.trim()||text.length>100000)throw fail('服务没有返回有效回复。');
  text=text.trim();if(text.startsWith('```')&&text.endsWith('```'))text=text.replace(/^```[^\n]*\n/,'').replace(/```$/,'').trim();
  let value;try{value=JSON.parse(text);}catch{value={text};}
  if(!value||typeof value.text!=='string'||!value.text.trim())throw fail('回复格式不完整，请重试。');
  return {reply:value.text.trim().slice(0,4000),emotion:['normal','happy','annoyed'].includes(value.emotion)?value.emotion:'normal',action:value.action==='sway'?'sway':'none'};
}
export function createChatTransport({request,cancel=()=>{},persona,sessionId,journal,onPersistenceError=()=>{},uuid=()=>crypto.randomUUID(),timeoutMs=90000,budget,onSummaryStatus=()=>{},memory=null,onMemoryStatus=()=>{}}={}){
  let generation=0,active=null,disposed=false;
  const abortError=()=>fail('已停止本轮回复。','cancelled');
  function stop(){generation++;if(active){const old=active;active=null;old.stop();}}
  return Object.freeze({
    async send({input,messages,signal}){
      if(disposed||signal?.aborted)throw abortError();
      if(active)throw fail('上一轮还在处理中。','busy');
      if(messages?.at(-1)?.content!==input)throw fail('输入与会话内容不一致。');
      const id=uuid(),session=sessionId(),ticket=++generation;if(typeof session!=='string'||!session)throw fail('会话尚未准备好。');
      let timer,abort,timeout=false;
      const startedAt=new Date().toISOString(),controller=new AbortController();
      const stopped=new Promise((_,reject)=>{
        abort=()=>{controller.abort();Promise.resolve().then(()=>cancel(id)).catch(()=>{});reject(timeout?fail('请求超时，请稍后再试。','timeout'):abortError());};
        signal?.addEventListener('abort',abort,{once:true});timer=setTimeout(()=>{timeout=true;abort();},timeoutMs);
      });
      active={id,stop:abort};
      try{
        let view=journal.context?await Promise.race([journal.context(session),stopped]):{epoch:0,records:[],session:null};
        if(disposed||controller.signal.aborted||ticket!==generation||session!==sessionId())throw abortError();
        const mirror=async segments=>{if(!memory)return;try{const r=await memory.syncSummaries(segments);if(r.changed)onMemoryStatus(r);}catch(error){onMemoryStatus({error:error.message});}};
        if(journal.commitSummary){await prepareSummary({view,journal,request,cancel,signal:controller.signal,onStatus:onSummaryStatus,onCommitted:s=>mirror([s])});view=await journal.context(session);}
        // Recover a missed local mirror without another model request; archives stay intact.
        if(memory&&journal.summaries)await mirror((await journal.summaries()).filter(s=>s.epoch===view.epoch));
        if(disposed||controller.signal.aborted||ticket!==generation||session!==sessionId())throw abortError();
        const old=view.session;
        const prefixMatches=old&&old.messages.length===messages.length-1&&old.messages.every((m,i)=>m.role===messages[i].role&&m.content===messages[i].content);
        const sameEpoch=(old?.contextEpoch??0)===view.epoch;
        const contextStart=sameEpoch&&(!old||prefixMatches)?(old?.contextStart??0):messages.length-1;
        const summarized=selectSummaries(view,input);
        const covered=Math.max(contextStart,...(view.summaries||[]).filter(s=>s.epoch===view.epoch&&s.start>=contextStart).map(s=>s.end));
        const layerView=memory?await memory.context(input,{epoch:view.epoch}):null;
        if(layerView)layerView.originalStoredMessages=old?.messages.length??0;
        const payload=buildMessages(messages.slice(covered),persona,{budget,notes:view.records,summaries:memory?[]:summarized,layers:layerView});
        // Non-streaming first: never imitate tokens with a fake typewriter.
        const raw=await Promise.race([request({id,messages:payload,signal:controller.signal}),stopped]);
        if(disposed||signal?.aborted||ticket!==generation||session!==sessionId())throw abortError();
        const reply=normalizeReply(raw);
        const stamp=new Date().toISOString();
        const times=prefixMatches?(old.messageTimes??Array(messages.length-1).fill(null)):Array(messages.length-1).fill(null);
        const snapshot={id:session,messages:[...messages,{role:'assistant',content:reply.reply}],messageTimes:[...times,startedAt,stamp],contextEpoch:view.epoch,contextStart,updatedAt:stamp,lastRequestId:id};
        try{await journal.save(snapshot,{signal:controller.signal,expectedMemoryEpoch:view.epoch});}
        catch(error){if(controller.signal.aborted)throw abortError();if(error.code==='context_changed')throw error;onPersistenceError(error);}
        if(disposed||signal?.aborted||ticket!==generation||session!==sessionId())throw abortError();

        return {id,...reply};
      }finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);if(active?.id===id)active=null;}
    },cancel:stop,destroy(){stop();disposed=true;}
  });
}
