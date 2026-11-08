// Short explicit speech sessions. Only a final result can reach the input adapter.
const messages={
 model_missing:'本地中文语音模型尚未准备，请由主干配置模型资源；仍可打字。',
 model_invalid:'本地中文模型校验失败，未开始收音；原草稿保留。',
 model_storage:'本地语音模型准备失败，请检查手机存储空间；原草稿保留。',
 engine_unavailable:'本地语音库缺失或无法加载，未回填文字；仍可打字。',
 engine_error:'本地中文识别未完成，原草稿保留。',
 engine_init:'本地中文模型初始化失败，未开始收音；原草稿保留。',
 audio_limit:'本次录音超过30秒上限，未回填或截断；请分成短句。',
 dialog_blocked:'手机系统拒绝打开语音窗口，未回填文字。可以使用输入法自带的语音输入。',
 dialog_start_failed:'系统语音窗口未能打开，未回填文字。可以使用输入法自带的语音输入。',
 dialog_unavailable:'手机没有提供可用的系统语音窗口。可点击输入框，使用输入法自带的语音输入。',
 start_timeout:'本地语音初始化未能完成，未开始收音；原草稿保留。',
 lifecycle_unavailable:'本地语音暂不可用，仍可打字。',
 unavailable:'本地中文语音尚未准备，仍可打字。',
 permission_required:'麦克风授权准备已失效，原草稿保留。',
 permission_denied:'未允许麦克风，原草稿保留。可重试或在系统设置检查权限。',
 permission_blocked:'麦克风未获允许，请在系统设置检查权限；仍可打字。',
 permission_pending:'系统权限窗口尚未结束，请先处理该窗口再重试。',
 busy:'本地语音正在处理或释放资源，请稍后重试。',no_speech:'没有听到语音，原草稿保留。',
 no_match:'没有识别清楚，原草稿保留。',empty_result:'没有可用的识别文字，原草稿保留。',
 network:'系统识别网络异常，原草稿保留。',network_timeout:'系统识别网络超时，原草稿保留。',
 audio:'麦克风暂不可用，原草稿保留。',timeout:'语音识别等待超时，原草稿保留。',
 disconnected:'系统识别服务已断开，原草稿保留。',service_error:'本地识别未完成，原草稿保留。',
 start_failed:'语音识别未能启动，原草稿保留。',client:'语音识别已中断，原草稿保留。',
 too_many_requests:'系统识别请求过于频繁，请稍后重试。',
 language_unsupported:'系统识别服务不支持中文，仍可打字或使用输入法语音。',
 language_unavailable:'系统中文识别暂不可用，本应用不会自动下载模型。',
 too_long:'识别文字超过输入上限，未回填也未截断；原草稿保留。',
 stale:'输入或页面已变化，本次识别未回填。',background:'已离开输入页，本次语音已取消。'
};
export function createSpeechController({bridge,input,onState=()=>{},onPreview=()=>{},timeoutMs=120000,finalTimeoutMs=12000,callTimeoutMs=10000,permissionTimeoutMs=45000,setTimer=setTimeout,clearTimer=clearTimeout,makeId=()=>globalThis.crypto?.randomUUID?.()||'stt-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)}={}){
 let dead=false,foreground=true,active=null,listener=null,capability=null,phase='checking',lastDetail='';
 const publish=(state,detail='')=>{phase=state;lastDetail=detail;const version=Number.isSafeInteger(capability?.buildCode)?'（本机构建'+capability.buildCode+'）':'';if(!dead)onState({state,detail:detail?detail+version:detail,available:capability?.available===true,active:!!active,permissionPreparation:active?.preparing===true,foreground});};
 function bounded(promise,ms=callTimeoutMs){let timer;return Promise.race([Promise.resolve(promise),new Promise((_,reject)=>{timer=setTimer(()=>reject(Error('timeout')),ms);})]).finally(()=>clearTimer(timer));}
 const removeListener=handle=>{try{void Promise.resolve(handle.remove()).catch(()=>{});}catch{}};
 const cancelNative=id=>{try{return bounded(bridge.cancel({sessionId:id})).catch(()=>{});}catch{return Promise.resolve();}};
 function finish(session,state,detail){if(active!==session)return false;active=null;clearTimer(session.timer);publish(state,detail);return true;}
 function cancel(reason='cancelled'){
  const old=active;if(!old)return Promise.resolve();
  finish(old,'idle',reason==='cancelled'?'已取消语音，原草稿保留。':messages[reason]||messages.stale);
  return cancelNative(old.id);
 }
 function wait(session){if(session.waiting)return;session.waiting=true;clearTimer(session.timer);session.timer=setTimer(()=>{if(finish(session,'error',messages.timeout))void cancelNative(session.id);},finalTimeoutMs);}
 function event(value){
  const session=active;if(dead||!session||value?.sessionId!==session.id)return;
  if(!input.getVoiceContext().active){void cancel('background');return;}
  if(!foreground){void cancel('background');return;}
  if(value.state==='preview'){
   if(phase==='listening'&&!session.waiting)onPreview({text:typeof value.text==='string'?value.text.slice(0,12000):'',level:Math.min(100,Math.max(0,Number(value.level)||0))});
   return;
  }
  if(['requesting','starting','listening','waiting'].includes(value.state)){
   // A duplicate ready/end callback cannot move an already stopped view back.
   if(session.waiting&&value.state!=='waiting')return;
   if(value.state==='waiting')wait(session);
   publish(value.state,{requesting:'正在准备本地语音…',starting:'正在初始化本地中文模型，尚未收音…',listening:'正在识别。可以结束后编辑，也可以直接点发送。',waiting:'已结束收音，正在等待最终文字…'}[value.state]);return;
  }
  if(value.state==='final'){
   const text=typeof value.text==='string'?value.text:'';
   // Clear ownership before dispatching the ordinary input event on insertion.
   if(!finish(session,'idle'))return;
   const result=input.insertVoiceText(session.context,text);
   const sent=result.applied&&session.sendRequested&&input.sendVoiceText?.()===true;
   publish(result.applied?'idle':'error',result.applied?(sent?'语音文字已发送。':'文字已填入，可修改后发送。'):messages[result.code]||messages.stale);
  }else if(value.state==='error')finish(session,'error',messages[value.code]||messages.service_error);
  else if(value.state==='cancelled')finish(session,'idle',messages[value.code]||'已取消语音，原草稿保留。');
 }
 const listening=Promise.resolve().then(()=>bridge.addListener('speech',event)).then(handle=>{
  if(dead){removeListener(handle);return;}listener=handle;
 });
 const ready=bounded(listening).then(()=>dead?null:bounded(bridge.capabilities())).then(value=>{
  if(dead)return;if(value.available&&value.engine!=='sherpa-local')value={...value,available:false,code:'engine_unavailable'};capability=value;publish(value.available?'idle':'unavailable',value.available?'本地语音可用，点麦克风开始。':messages[value.code]||messages.unavailable);
 }).catch(()=>{if(!dead)publish('unavailable','本地语音暂不可用，仍可打字。');});
 async function start(){
  if(dead||active)return;
  const context=input.getVoiceContext();
  if(!foreground||!context.active||context.composing)return;
  const session={id:makeId(),context,timer:null,waiting:false};active=session;publish('requesting','正在检查本地中文模型…');
  session.timer=setTimer(()=>{if(finish(session,'error',messages.timeout))void cancelNative(session.id);},timeoutMs);
  try{
   await ready;if(dead||active!==session)return;
   if(!listener)throw Error('unavailable');
   // Native prepare/start still verify model availability and microphone permission.
   const value=capability?.available?capability:await bounded(bridge.capabilities());
   if(active!==session||dead)return;
   capability=value;if(!value.available){finish(session,'unavailable',messages[value.code]||messages.unavailable);return;}
   const current=input.getVoiceContext();
   if(!foreground||!current.active||current.epoch!==context.epoch||current.id!==context.id||current.value!==context.value){void cancel('stale');return;}
   // This candidate only invokes the explicit local engine, never a system dialog.
   if(value.engine!=='sherpa-local'){finish(session,'unavailable',messages.engine_unavailable);return;}
   session.preparing=true;
   publish('requesting','正在准备麦克风权限，授权后返回当前输入页将继续…');
   const prepared=await bounded(bridge.prepare({sessionId:session.id}),permissionTimeoutMs);
   if(active!==session||dead){void cancelNative(session.id);return;}
   session.preparing=false;
   if(!prepared?.prepared){finish(session,'error',messages[prepared?.code]||messages.start_failed);return;}
   const afterPermission=input.getVoiceContext();
   if(!foreground||!afterPermission.active||afterPermission.epoch!==context.epoch||afterPermission.id!==context.id||afterPermission.value!==context.value){void cancel('stale');return;}
   const ack=await bounded(bridge.start({sessionId:session.id}));
   if(active!==session||dead){void cancelNative(session.id);return;}
   if(!ack?.accepted)finish(session,'error',messages[ack?.code]||messages.start_failed);
  }catch(error){if(finish(session,'error',error?.message==='timeout'?(phase==='starting'?messages.start_timeout:messages.timeout):messages.start_failed))void cancelNative(session.id);}
 }
 async function stop({send=false}={}){
  const session=active;if(!session||dead||session.waiting)return;
  session.sendRequested=send===true;
  wait(session);publish('waiting',send?'已结束收音，等最终文字后发送…':'已结束收音，正在整理文字…');
  try{await bounded(bridge.stop({sessionId:session.id}));}
  catch{if(finish(session,'error',messages.service_error))void cancelNative(session.id);}
 }
 const unsubscribe=input.subscribeVoiceContext(reason=>{if(reason==='destroy'){destroy();return;}if(active)void cancel('stale');else if(!dead)publish(phase,lastDetail);});
 function setForeground(value,{permissionOverlay=false}={}){
  const changed=foreground!==Boolean(value);
  foreground=Boolean(value);
  const session=active;
  if(session?.preparing&&(foreground||permissionOverlay)){
   // Only visibility suspension during the explicit prepare RPC is provisional.
   // Native onStop/screen-off and the app-active(false) route always cancel.
   try{void bounded(bridge.setPageForeground({sessionId:session.id,foreground})).catch(()=>{if(active===session)void cancel('background');});}
   catch{void cancel('background');}
  }else if(!foreground&&session)void cancel('background');
  if(changed&&!active&&!dead){
   if(foreground&&capability?.available&&lastDetail===messages.background)publish('idle','本地语音可用，点麦克风开始。');
   else publish(phase,lastDetail);
  }
 }
 function destroy(){if(dead)return;void cancel();dead=true;phase='closed';unsubscribe();if(listener)removeListener(listener);listener=null;onState({state:'closed',detail:'',available:false,active:false});}
 return Object.freeze({ready,start,stop,cancel,setForeground,destroy,getState:()=>({state:phase,active:!!active})});
}
