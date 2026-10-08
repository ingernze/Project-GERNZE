/* Shared V23 alpha media; media-time cues, finite callbacks, no idle polling. */
(function(root){
 'use strict';
 let active=null;
 function play(options){
  if(active)active.cancel();
  const app=options.app||document.getElementById('app');
  const oldInert=app?app.inert:false;
  const layer=document.createElement('div');layer.className='hebao-arrival-layer';
  const video=document.createElement('video');video.className='hebao-arrival-video';video.setAttribute('aria-hidden','true');video.muted=true;video.playsInline=true;video.preload='auto';video.playbackRate=options.rate||1;
  const fallback=document.createElement('button');fallback.type='button';fallback.className='hebao-arrival-resume';fallback.textContent='播放入场';fallback.hidden=true;
  const skip=document.createElement('button');skip.type='button';skip.className='hebao-arrival-skip';skip.textContent='跳过入场';
  const oldFocus=document.activeElement;
  layer.append(video,fallback,skip);document.body.append(layer);if(app)app.inert=true;skip.focus({preventScroll:true});
  let finished=false,pausedForVisibility=false;
  let loadDeadline=null,frameJob=null,cueSent=false;
  const cueAt=Number.isFinite(options.cueAt)?Math.max(0,options.cueAt):null;
  const frameCue=typeof video.requestVideoFrameCallback==='function'&&typeof video.cancelVideoFrameCallback==='function';
  function cue(time){
   if(finished||cueSent||cueAt===null||video.paused||document.hidden||time<cueAt)return;
   cueSent=true;if(options.onCue)options.onCue({mediaTime:time});
  }
  function frame(_now,metadata){
   frameJob=null;if(finished||cueSent)return;
   cue(metadata.mediaTime);
   if(!finished&&!cueSent)frameJob=video.requestVideoFrameCallback(frame);
  }
  function timeupdate(){if(!frameCue)cue(video.currentTime);}
  function cleanup(reason){
   if(finished)return;finished=true;
   clearTimeout(loadDeadline);loadDeadline=null;
   if(frameJob!==null){video.cancelVideoFrameCallback(frameJob);frameJob=null;}
   video.removeEventListener('timeupdate',timeupdate);
   document.removeEventListener('keydown',keydown);
   fallback.removeEventListener('click',resume);skip.removeEventListener('click',skipped);
   document.removeEventListener('visibilitychange',visibility);
   video.removeEventListener('playing',playing);video.removeEventListener('ended',ended);video.removeEventListener('error',failed);
   video.pause();video.removeAttribute('src');video.load();layer.remove();
   if(app)app.inert=oldInert;if(active===controller)active=null;
   if(layer.contains(document.activeElement)||document.activeElement===document.body){
    if(oldFocus?.isConnected&&!oldFocus.closest('[inert]'))oldFocus.focus({preventScroll:true});
   }
   if(options.onFinish)options.onFinish(reason);
  }
  function playing(){
   clearTimeout(loadDeadline);loadDeadline=null;layer.classList.add('is-playing');fallback.hidden=true;
   if(cueAt!==null&&!cueSent){
    if(frameCue){if(frameJob===null)frameJob=video.requestVideoFrameCallback(frame);}
    else timeupdate();
   }
  }
  function ended(){cleanup('ended');}
  function failed(){cleanup('error');}
  function skipped(){cleanup('skipped');}
  function keydown(event){if(event.key==='Escape'){event.preventDefault();skipped();}}
  async function resume(){
   if(finished)return;
   try{await video.play();}catch(_error){if(!finished)fallback.hidden=false;}
  }
  function visibility(){
   if(finished)return;
   if(document.hidden){pausedForVisibility=!video.paused;video.pause();}
   else if(pausedForVisibility){pausedForVisibility=false;resume();}
  }
  const controller={cancel:()=>cleanup('cancelled'),isActive:()=>!finished};active=controller;
  video.addEventListener('playing',playing);video.addEventListener('ended',ended);video.addEventListener('error',failed);video.addEventListener('timeupdate',timeupdate);
  fallback.addEventListener('click',resume);skip.addEventListener('click',skipped);document.addEventListener('keydown',keydown);document.addEventListener('visibilitychange',visibility);
  loadDeadline=setTimeout(()=>cleanup('load-timeout'),10000);
  video.src=options.source;resume();return controller;
 }
 root.HebaoArrivalV23={play,cancel:()=>active?.cancel(),isActive:()=>Boolean(active)};
})(window);
