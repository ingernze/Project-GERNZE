import {Capacitor,registerPlugin} from '@capacitor/core';
import {createSpeechController} from './speech-controller.mjs';

const bridge=registerPlugin('HebaoSpeech');
let mounted=null;
export function mountSpeech(){
 if(mounted)return mounted;
 if(!Capacitor.isNativePlatform()||Capacitor.getPlatform()!=='android')return ()=>{};
 const events=new AbortController();let uiEvents=null,speech=null,owner=null,slot=null,status=null,button=null,cancel=null,preview=null,warmActive=false,dead=false,appActive=true,permissionPreparation=false;
 const listen=(node,name,fn)=>node.addEventListener(name,fn,{signal:events.signal});
 function syncWarmup(active=appActive&&!document.hidden&&owner?.getVoiceContext()?.active){
  const wanted=Boolean(active);
  if(wanted===warmActive)return;
  warmActive=wanted;
  void Promise.resolve().then(()=>bridge.warmup({active:wanted})).catch(()=>{});
 }
 function attach(){
  if(dead)return;const controller=window.HebaoDialogueController;
  if(!controller?.getVoiceContext||controller===owner)return;
  syncWarmup(false);uiEvents?.abort();speech?.destroy();slot?.replaceChildren();status?.remove();preview?.remove();uiEvents=new AbortController();
  owner=controller;slot=controller.getVoiceSlot();if(!slot)return;
  slot.hidden=false;slot.classList.add('dl-voice-controls');
  button=document.createElement('button');button.type='button';button.className='dl-voice-button';
  const microphone=document.createElementNS('http://www.w3.org/2000/svg','svg');microphone.setAttribute('viewBox','0 0 24 24');microphone.setAttribute('aria-hidden','true');microphone.innerHTML='<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M6 10v2a6 6 0 0 0 12 0v-2M12 18v3M9 21h6"/>';button.append(microphone);button.setAttribute('aria-label','开始本地中文语音输入');
  cancel=document.createElement('button');cancel.type='button';cancel.className='dl-voice-cancel';cancel.textContent='取消';cancel.hidden=true;
  status=document.createElement('p');status.className='dl-speech-status';status.role='status';status.textContent='正在检查本地中文语音…';slot.closest('form').append(status);
  slot.append(button,cancel);
  preview=document.createElement('div');preview.className='dl-voice-preview';preview.hidden=true;
  const voiceTitle=document.createElement('strong'),voiceText=document.createElement('div'),avatars=document.createElement('span');
  voiceTitle.className='dl-voice-title';voiceText.className='dl-voice-text';avatars.className='dl-voice-avatars';avatars.setAttribute('aria-hidden','true');
  const sprites=Array.from({length:3},()=>{const img=document.createElement('img');img.src='progress-libao.png';img.alt='';img.width=26;img.height=26;avatars.append(img);return img;});
  preview.append(voiceTitle,avatars,voiceText);slot.closest('form').prepend(preview);
  speech=createSpeechController({bridge,input:controller,onPreview:({text,level})=>{
   if(dead||owner!==controller||preview.hidden)return;
   const draft=text||'正在听你说…';
   if(voiceText.textContent!==draft)voiceText.textContent=draft;
   for(const [i,img] of sprites.entries())img.style.setProperty('--voice-lift',(-Math.round(level*[.09,.14,.11][i]))+'px');
  },onState:value=>{
   if(dead||owner!==controller)return;
   const preparing=value.permissionPreparation===true;
   if(preparing!==permissionPreparation){permissionPreparation=preparing;window.dispatchEvent(new CustomEvent('hebao:speech-permission',{detail:preparing}));}
   if(value.state==='closed'){syncWarmup(false);controller.setVoiceSubmit(null);uiEvents?.abort();slot?.replaceChildren();if(slot)slot.hidden=true;status?.remove();preview?.remove();owner=null;slot=status=preview=null;return;}
   const context=controller.getVoiceContext(),recording=value.state==='listening';
   syncWarmup(value.available&&appActive&&!document.hidden&&context.active);
   controller.setVoiceSubmit(recording?()=>{void speech.stop({send:true});return true;}:null,value.active&&!recording);
   preview.hidden=!value.active;
   voiceTitle.textContent=recording?'正在识别':value.state==='waiting'?'正在整理文字':'正在准备语音';
   if(!recording)for(const img of sprites)img.style.removeProperty('--voice-lift');
   if(!value.active||value.state==='requesting'||value.state==='starting')voiceText.textContent='';
   if(recording&&!voiceText.textContent)voiceText.textContent='正在听你说…';
   if(recording)button.textContent='结束';else button.replaceChildren(microphone);button.setAttribute('aria-label',recording?'结束收音并等待文字':'开始本地中文语音输入');button.setAttribute('aria-pressed',String(recording));
   button.disabled=value.foreground===false||!context.active||context.composing||(!recording&&value.active)||(!value.active&&!value.available);
   cancel.hidden=!value.active;const detail=value.detail||'本地中文识别，最长30秒；文字填入后请手动发送。';if(status.textContent!==detail)status.textContent=detail;
  }});
  speech.setForeground(appActive&&!document.hidden);
  button.addEventListener('click',()=>{if(speech.getState().state==='listening')void speech.stop();else void speech.start();},{signal:uiEvents.signal});
  cancel.addEventListener('click',()=>void speech.cancel(),{signal:uiEvents.signal});
 }
 listen(window,'hebao:dialogue-ready',attach);
 listen(window,'hebao:page-change',event=>{if(event.detail?.page!=='dialogue'){syncWarmup(false);void speech?.cancel('background');}else queueMicrotask(()=>syncWarmup());});
 listen(document,'visibilitychange',()=>{speech?.setForeground(appActive&&!document.hidden,{permissionOverlay:appActive});syncWarmup();});
 listen(window,'hebao:app-active',event=>{appActive=event.detail!==false;speech?.setForeground(appActive&&!document.hidden,{permissionOverlay:appActive});syncWarmup();});
 function dispose(){if(dead)return;dead=true;syncWarmup(false);owner?.setVoiceSubmit(null);events.abort();uiEvents?.abort();speech?.destroy();slot?.replaceChildren();if(slot)slot.hidden=true;status?.remove();preview?.remove();if(mounted===dispose)mounted=null;}
 listen(window,'pagehide',dispose);mounted=dispose;attach();return dispose;
}
