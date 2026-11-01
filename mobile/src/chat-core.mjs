import protocol from '../../src/workbench/chat-protocol.json' with {type:'json'};
import {layersPrompt} from './memory-layers.mjs';
import {prepareSummary,selectSummaries,summaryPrompt,SUMMARY_CALLS_PER_SEND} from './summary-policy.mjs';
import {notePrompt} from './memory-records.mjs';
// Local limits use JS/Java UTF-16 code units; these are NOT bytes or tokens.
// Keep in step with journal.validateSnapshot and the renderer restore guard.
export const MAX_MESSAGE_UNITS=12000;
export const MAX_RESPONSE_CONTENT_UNITS=100000; // provider message.content, including JSON/fence
export const CONTEXT_SAFETY_BYTES=1024;
export const OUTPUT_BYTES_PER_TOKEN_ESTIMATE=8;
export const estimateMessageBytes=messages=>new TextEncoder().encode(JSON.stringify(messages)).length+messages.length*64;

export function replyBudgetFor(text,origin='user'){
  // Match the current desktop's finite rule. Source roles and mixed quotes
  // cannot promote themselves into a larger output allowance.
  const direct=typeof text==='string'?text.trim():'';
  const quoted=/```|["'“”「」『』>]/.test(direct);
  const detailed=origin==='user'&&!quoted&&/^(?:请|帮我|麻烦|能否|我想请你|能不能)?(?:再)?(?:详细|深入|全面|展开)(?:地)?(?:分析|解释|说明|讲解|比较|说说)/.test(direct);
  const maxTokens=detailed?1800:700;
  // Existing window guard counts UTF-8 bytes plus framing, not model tokens.
  // This deliberately padded conversion is a heuristic, not a tokenizer or a
  // guarantee for every provider/vocabulary. Keep the extra safety gap separate.
  const outputEstimateBytes=maxTokens*OUTPUT_BYTES_PER_TOKEN_ESTIMATE;
  return Object.freeze({maxTokens,outputEstimateBytes,safetyBytes:CONTEXT_SAFETY_BYTES,
    reserveBytes:outputEstimateBytes+CONTEXT_SAFETY_BYTES,countKind:'utf8_bytes_plus_framing_estimate'});
}

// Narrow JS -> native adapter, shared by the UI and offline connection checks.
// Credentials stay native; no headers, logging, retries or model classification.
export function createNativeChatRequest(bridge){
  return async({id,messages,purpose,maxTokens})=>(await bridge.request({id,messages,
    purpose:purpose||'chat',...(maxTokens===undefined?{}:{maxTokens})})).data;
}

// Provider-neutral text chat. Native bridge owns credentials and HTTPS; no tool execution.
const fail=(message,code='chat_failed')=>Object.assign(Error(message),{code});
export function buildMessages(messages,persona,{budget=32768,reserve=replyBudgetFor(Array.isArray(messages)?messages.at(-1)?.content:undefined).reserveBytes,notes=[],summaries=[],layers=null}={}){
  if(!Number.isSafeInteger(budget)||!Number.isSafeInteger(reserve)||budget<1||reserve<0)throw fail('上下文预算无效。','budget_exceeded');
  if(!Array.isArray(messages)||!messages.length||messages.length%2!==1)throw fail('对话轮次不完整。');
  if(typeof persona!=='string'||!persona.trim()||persona.length>8000)throw fail('人物设定未准备好。');
  const history=messages.map((m,i)=>{
    if(!m||m.role!==(i%2?'assistant':'user')||typeof m.content!=='string'||!m.content.trim()||m.content.length>MAX_MESSAGE_UNITS)throw fail('对话内容无效。');
    return {role:m.role,content:m.content};
  });
  const kept=summaries.slice(),layerView=layers?{...layers,approved:[...(layers.approved||[])],working:[...(layers.working||[])]}:null;
  const outputProtocol='\n'+protocol.instruction;
  const system={role:'system',content:''},current=history.at(-1),room=budget-reserve;
  const cost=estimateMessageBytes;
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
  let text=choice.message?.content;if(typeof text!=='string'||!text.trim()||text.length>MAX_RESPONSE_CONTENT_UNITS)throw fail('服务回复为空或超过原始内容上限（100000个UTF-16代码单元），未截断保存。','invalid_response');
  text=text.trim();const fenced=text.startsWith('```');
  if(fenced){
    if(!text.endsWith('```')||!text.includes('\n'))throw fail('回复围栏未完整结束，未保存。','invalid_response');
    text=text.slice(text.indexOf('\n')+1,text.lastIndexOf('```')).trim();
  }
  let value;try{value=JSON.parse(text);}catch{
    if(fenced||/^[{\[]/.test(text))throw fail('回复JSON损坏，未作为普通文字保存。','invalid_response');
    value={text};
  }
  if(!value||typeof value.text!=='string'||!value.text.trim())throw fail('回复格式不完整，请重试。');
  if(value.text.length>MAX_MESSAGE_UNITS)throw fail('回复超过本地正文上限（12000个UTF-16代码单元），未截断保存。','reply_too_long');
  return {reply:value.text.trim(),emotion:['normal','happy','annoyed'].includes(value.emotion)?value.emotion:'normal',action:value.action==='sway'?'sway':'none'};
}
export function createChatTransport({request,cancel=()=>{},persona,sessionId,journal,onPersistenceError=()=>{},uuid=()=>crypto.randomUUID(),timeoutMs=90000,budget,onSummaryStatus=()=>{},memory=null,onMemoryStatus=()=>{},research=null,onResearchStatus=()=>{}}={}){
  if(research&&journal?.researchVersion!==1)throw fail('研究资料需要新版会话存储。');
  let generation=0,active=null,disposed=false,summaryJob=null;
  const abortError=()=>fail('已停止本轮回复。','cancelled');
  function stop(){research?.clear();generation++;summaryJob?.controller.abort();if(active){const old=active;active=null;old.stop();}}
  async function yieldSummary(){
    const job=summaryJob;if(!job)return;job.controller.abort();let timer;
    // A cancelled native HTTP request must drain before using its single request slot.
    const drained=await Promise.race([job.done.then(()=>true),new Promise(r=>timer=setTimeout(()=>r(false),1000))]);clearTimeout(timer);
    if(!drained)throw fail('摘要请求尚在停止，请稍后重试聊天。','busy');
  }
  function startSummaries(session,ticket,epoch,mirror){
    if(!journal.commitSummary||disposed||ticket!==generation)return;
    const job={controller:new AbortController(),pending:null,done:null};summaryJob=job;
    const signal=job.controller.signal;
    job.done=Promise.resolve().then(async()=>{
      for(let i=0;i<SUMMARY_CALLS_PER_SEND;i++){
        if(signal.aborted||disposed||ticket!==generation||session!==sessionId())break;
        const view=await journal.context(session);
        if(signal.aborted||view.epoch!==epoch||session!==sessionId())break;
        const saved=await prepareSummary({view,journal,signal,cancel,onStatus:onSummaryStatus,onCommitted:s=>mirror([s]),request:payload=>{
          if(signal.aborted)throw abortError();
          const work=Promise.resolve(request(payload));job.pending=work.then(()=>{},()=>{});return work;
        }});
        if(!saved)break;
        if(!signal.aborted)onSummaryStatus('较早对话已保存为摘要；剩余积压在本次上限内继续，或留到下次发送。');
      }
    }).catch(error=>{if(!signal.aborted)onSummaryStatus(error.message||'摘要未完成，原文仍保留。');}).finally(async()=>{
      // Keep the job visible if cancellation/timeout returned before native HTTP settled.
      if(job.pending)await job.pending;
      if(summaryJob===job)summaryJob=null;
    });
  }
  return Object.freeze({
    async send({input,messages,signal,origin='user'}){
      if(disposed||signal?.aborted){research?.clear();throw abortError();}
      if(active)throw fail('上一轮还在处理中。','busy');
      if(messages?.at(-1)?.content!==input){research?.clear();throw fail('输入与会话内容不一致。');}
      const id=uuid(),session=sessionId(),ticket=++generation;if(typeof session!=='string'||!session)throw fail('会话尚未准备好。');
      let timer,abort,timeout=false,claim=null;
      const startedAt=new Date().toISOString(),controller=new AbortController();
      const stopped=new Promise((_,reject)=>{
        abort=()=>{controller.abort();Promise.resolve().then(()=>cancel(id)).catch(()=>{});reject(timeout?fail('请求超时，请稍后再试。','timeout'):abortError());};
        signal?.addEventListener('abort',abort,{once:true});timer=setTimeout(()=>{timeout=true;abort();},timeoutMs);
      });
      active={id,stop:abort};
      try{
        claim=research?await Promise.race([research.claim({id,sessionId:session,input,origin}),stopped]):null;
        if(summaryJob)await Promise.race([yieldSummary(),stopped]);
        if(disposed||controller.signal.aborted||ticket!==generation)throw abortError();
        let view=journal.context?await Promise.race([journal.context(session),stopped]):{epoch:0,records:[],session:null};
        if(disposed||controller.signal.aborted||ticket!==generation||session!==sessionId())throw abortError();
        const mirror=async segments=>{if(!memory)return;try{const r=await memory.syncSummaries(segments);if(r.changed)onMemoryStatus(r);}catch(error){onMemoryStatus({error:error.message});}};
        // Recover a missed local mirror without another model request; archives stay intact.
        if(memory&&journal.summaries)await mirror((await journal.summaries()).filter(s=>s.epoch===view.epoch));
        if(disposed||controller.signal.aborted||ticket!==generation||session!==sessionId())throw abortError();
        const old=view.session;
        const researchIndices=new Set((old?.researchRanges||[]).flatMap(r=>[r.start,r.start+1]));
        const prefixMatches=old&&old.messages.length===messages.length-1&&old.messages.every((m,i)=>m.role===messages[i].role&&(researchIndices.has(i)||m.content===messages[i].content));
        const sameEpoch=(old?.contextEpoch??0)===view.epoch;
        const contextStart=sameEpoch&&(!old||prefixMatches)?(old?.contextStart??0):messages.length-1;
        const summarized=selectSummaries(view,input);
        const covered=Math.max(contextStart,...(view.summaries||[]).filter(s=>s.epoch===view.epoch&&s.start>=contextStart).map(s=>s.end));
        const layerView=memory?await memory.context(input,{epoch:view.epoch}):null;
        if(layerView)layerView.originalStoredMessages=old?.messages.length??0;
        const replyBudget=replyBudgetFor(input,origin);
        const history=prefixMatches?[...old.messages,{role:'user',content:input}]:messages;
        const safeHistory=history.filter((m,i)=>i>=covered&&!(prefixMatches&&researchIndices.has(i)));
        let payload=buildMessages(safeHistory,persona,{budget,reserve:replyBudget.reserveBytes,notes:view.records,summaries:memory?[]:summarized,layers:layerView});
        const prepared=research?await research.prepare(claim,payload,{room:(budget??32768)-replyBudget.reserveBytes,measure:estimateMessageBytes}):{payload,receipt:null,status:'not_selected'};
        payload=prepared.payload;
        if(claim)await research.validate(claim);
        if(disposed||controller.signal.aborted||ticket!==generation||session!==sessionId())throw abortError();
        // Non-streaming first: never imitate tokens with a fake typewriter.
        const raw=await Promise.race([request({id,messages:payload,purpose:'chat',maxTokens:replyBudget.maxTokens,signal:controller.signal}),stopped]);
        if(disposed||signal?.aborted||ticket!==generation||session!==sessionId())throw abortError();
        if(claim)await research.validate(claim);
        if(controller.signal.aborted||ticket!==generation)throw abortError();
        const reply=normalizeReply(raw);
        const stamp=new Date().toISOString();
        const times=prefixMatches?(old.messageTimes??Array(messages.length-1).fill(null)):Array(messages.length-1).fill(null);
        const snapshot={id:session,messages:[...messages,{role:'assistant',content:reply.reply}],messageTimes:[...times,startedAt,stamp],contextEpoch:view.epoch,contextStart,updatedAt:stamp,lastRequestId:id};
        let persisted=true;
        try{await journal.save(snapshot,{signal:controller.signal,expectedMemoryEpoch:view.epoch,expectedSession:view.session??null,researchUse:prepared.receipt});}
        catch(error){if(controller.signal.aborted)throw abortError();if(error.code==='context_changed'||prepared.receipt)throw error;persisted=false;onPersistenceError(error);}
        if(disposed||signal?.aborted||ticket!==generation||session!==sessionId())throw abortError();

        if(persisted)startSummaries(session,ticket,view.epoch,mirror);
        const contextBudget={...replyBudget,windowBytes:budget??32768,inputLimitBytes:(budget??32768)-replyBudget.reserveBytes,inputEstimateBytes:estimateMessageBytes(payload)};
        onResearchStatus(prepared.status);
        return {id,...reply,contextBudget,researchUse:{status:prepared.status}};
      }finally{research?.finish(claim);clearTimeout(timer);signal?.removeEventListener('abort',abort);if(active?.id===id)active=null;}
    },cancel:stop,destroy(){stop();disposed=true;}
  });
}
