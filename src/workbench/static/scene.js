/* Core workbench scene. Existing Pixi portrait and accepted sway frames, loaded on entry. */
(function(root){
'use strict';
function mount(rootEl,ctx){
  const h=(tag,cls,text)=>{const e=document.createElement(tag);e.className=cls||'';if(text)e.textContent=text;return e};
  const page=h('section','scene-page'),heading=h('div','scene-heading');
  heading.append(h('h1','','人物场景'),h('p','subtle','窗边暮色'));
  const viewport=h('div','scene-viewport'),room=h('div','scene-room');
  const bg=h('img','scene-background');bg.src='scene/window-dusk.png';bg.alt='暮色中的窗景、山林与两根窗杆';
  const character=h('div','scene-character'),poster=h('canvas','scene-poster'),actionCanvas=h('canvas','scene-action');
  actionCanvas.hidden=true;
  const frame=h('iframe','scene-portrait');frame.title='莉宝人物';frame.hidden=true;
  const bubble=h('div','scene-dialogue');bubble.append(h('span','scene-speaker','莉宝'));
  const speech=h('p','','天色慢慢暗下来了。先在这里歇一会儿吧。');bubble.append(speech);
  const toolbar=h('div','scene-tools');
  function button(label){const b=h('button','scene-button',label);b.type='button';toolbar.append(b);return b}
  const sleep=button('睡一会儿'),sway=button('摆摆腿'),pet=button('摸摸头'),gentle=button('轻晃一下'),greet=button('换句台词'),pause=button('暂停动作'),retry=button('重新加载');
  retry.hidden=true;sleep.disabled=sway.disabled=pet.disabled=gentle.disabled=greet.disabled=pause.disabled=true;
  const breathLabel=h('label','scene-status','呼吸 '),breathing=h('select','scene-button');breathing.setAttribute('aria-label','呼吸幅度');
  for(const [value,label] of [['1.3','轻微'],['1.6','明显']]){const option=h('option','',label);option.value=value;breathing.append(option)}breathing.value='1.6';breathLabel.append(breathing);toolbar.append(breathLabel);
  ctx.scope.listen(breathing,'change',()=>send('hecate:breathing',{value:Number(breathing.value)}));
  const status=h('span','scene-status','正在准备动作…');status.role='status';toolbar.append(status);
  character.append(poster,frame,actionCanvas);room.append(bg,character,bubble);viewport.append(room);page.append(heading,viewport,toolbar);rootEl.append(page);
  let closed=false,ready=false,paused=false,actionActive=false,actionVersion=0,loadTimer=null,sequence=null,original=null;
  let actionCache=new Map(),automaticTimer=null,portraitBusy=false,chatBusy=false,actionKind=null,sleepSequence=null,sleeper=null,sleepAutomatic=false;
  const cue=name=>ctx.call('voice.scene_'+name,{}).catch(()=>{});
  const player=root.HebaoSceneActions.player({load:actionImage,render:im=>{actionCanvas.currentImage=im;draw(actionCanvas,im);actionCanvas.hidden=false;frame.hidden=true;poster.hidden=true;},onPhase:phase=>{
    if(actionKind!=='sleep')return;
    status.textContent=phase==='entry'?'正在入睡':phase==='exit'?'正在醒来':sleepAutomatic?'睡眠中 · 稍后自动醒来':'睡眠中 · 点叫醒她结束';
    if(phase==='entry')cue('sleep');
    if(phase==='loop'&&sleepAutomatic&&!player.state()?.wakeRequested)sleeper?.holding();
    if(phase==='exit'){sleep.disabled=true;sleep.textContent='正在醒来';sleeper?.cancelWake();cue('wake');}
  }});
  const portraitLabels={idle:"自然待机",blink:"眨眼中",pet:"摸头回应",pester:"让我缓一缓",sway:"轻晃与回稳",drag:"轻轻拖动中"};
  function updateControls(){sway.disabled=!ready||paused||actionActive||portraitBusy;sleep.disabled=!ready||!sleepSequence||paused||portraitBusy||(actionActive&&actionKind!=='sleep')||Boolean(player.state()?.wakeRequested)||player.state()?.phase==='exit';pet.disabled=gentle.disabled=greet.disabled=!ready||paused||actionActive;breathing.disabled=actionActive;}
  const send=(type,extra={})=>{if(type==='hecate:reply'&&actionActive){speech.textContent=extra.reply.text;return;}frame.contentWindow?.postMessage({type,...extra},location.origin);};
  function draw(canvas,image){
    const w=character.clientWidth,ht=character.clientHeight;if(!w||!ht)return;
    const dpr=Math.min(devicePixelRatio||1,1.5,2048/Math.max(w,ht));
    const width=Math.round(w*dpr),height=Math.round(ht*dpr);
    if(canvas.width!==width)canvas.width=width;if(canvas.height!==height)canvas.height=height;
    const c=canvas.getContext('2d');c.setTransform(dpr,0,0,dpr,0,0);c.clearRect(0,0,w,ht);
    const scale=Math.min((w-8)/830,(ht-12)/1254);
    c.drawImage(image,w/2-640*scale,ht/2-626*scale,1254*scale,1254*scale);
  }
  const loadImage=file=>new Promise((resolve,reject)=>{const im=new Image();im.decoding='async';im.onload=()=>{if(typeof im.decode==='function')im.decode().then(()=>resolve(im),()=>reject(Error('人物素材没有解码成功')));else resolve(im)};im.onerror=()=>reject(Error('人物素材没有加载成功'));im.src=file});
  loadImage('scene/original.png').then(im=>{if(!closed){original=im;draw(poster,im)}}).catch(()=>{if(!closed)status.textContent='静止人物没有加载成功，请重新加载'});
  const observer=new ResizeObserver(()=>{if(original)draw(poster,original);if(actionActive&&actionCanvas.currentImage)draw(actionCanvas,actionCanvas.currentImage)});observer.observe(character);
  function visibility(){if(ready)send('hecate:visibility',{visible:!document.hidden&&!paused&&!actionActive})}
  function cancelAction(normal=false){
    if(actionKind==='sleep'&&!normal)cue('stop');
    player.stop();sleeper?.cancel();actionVersion++;actionKind=null;sleepAutomatic=false;sleep.textContent='睡一会儿';
    actionActive=false;actionCanvas.hidden=true;actionCanvas.currentImage=null;actionCanvas.width=actionCanvas.height=1;actionCache.clear();frame.hidden=!ready;poster.hidden=ready;updateControls();visibility();
  }
  function scheduleAutomatic(){
    clearTimeout(automaticTimer);if(closed||!ready||paused||document.hidden||actionActive||portraitBusy||chatBusy)return;
    // Mean wait of 20 minutes. Only this idle page owns the timer.
    automaticTimer=setTimeout(()=>{automaticTimer=null;if(!closed&&!paused&&!document.hidden&&!actionActive&&!portraitBusy)runAction();else scheduleAutomatic()},Math.max(1000,-Math.log(1-Math.random())*20*60*1000));
  }
  async function actionImage(file){
    if(actionCache.has(file)){const pending=actionCache.get(file);actionCache.delete(file);actionCache.set(file,pending);return pending}
    const version=actionVersion,pending=loadImage(file);actionCache.set(file,pending);
    while(actionCache.size>3)actionCache.delete(actionCache.keys().next().value);
    try{return await pending;}catch(error){if(actionCache.get(file)===pending)actionCache.delete(file);throw error;}
    finally{if((closed||version!==actionVersion)&&actionCache.get(file)===pending)actionCache.delete(file);}
  }
  function canSleep(){return !closed&&ready&&!paused&&!document.hidden&&!actionActive&&!portraitBusy&&!chatBusy&&!page.querySelector('.scene-chat-input input:focus');}
  function resumeSchedules(){scheduleAutomatic();sleeper?.schedule();}
  async function prepareSleep(){
    try{
      const response=await fetch('scene/sleep.json',{signal:ctx.signal});if(!response.ok)throw Error('睡眠素材没有准备好');
      const value=await response.json();if(closed)return;sleepSequence=value;
      sleeper=root.HebaoSceneActions.sleepSchedule({prefs:{...value.defaults,sleep_enabled:false},available:canSleep,start:()=>{if(!canSleep())return false;runAction('sleep',true);return true;},wake:requestWake,isSleeping:()=>!closed&&actionKind==='sleep'&&actionActive&&!document.hidden});
      try{const saved=await ctx.call('behavior.get',{});if(!closed&&saved.available)sleeper.configure(saved.settings);}catch{}
      if(!closed){updateControls();sleeper.schedule();}
    }catch(error){if(!closed){sleep.disabled=true;sleep.title=error.message;}}
  }
  function requestWake(){if(actionKind!=='sleep'||!player.wake())return;sleeper?.cancelWake();sleep.disabled=true;sleep.textContent='等她醒来';status.textContent='已叫醒，等待当前动作自然结束';}
  async function runAction(kind='sway',automatic=false){
    if(!ready||closed||paused||document.hidden||actionActive||portraitBusy)return false;
    if(kind==='sleep'&&!sleepSequence)return false;
    clearTimeout(automaticTimer);sleeper?.cancelIdle(true);actionActive=true;actionKind=kind;sleepAutomatic=automatic;const version=++actionVersion;updateControls();
    if(kind==='sleep')sleep.textContent='叫醒她';
    try{
      if(kind==='sway'&&!sequence){const response=await fetch('scene/action.json',{signal:ctx.signal});if(!response.ok)throw Error('动作资源没有加载成功');sequence=await response.json();}
      if(version!==actionVersion||closed)return false;
      const cycles=kind==='sleep'?Infinity:1+Math.floor(Math.random()*3);
      status.textContent=kind==='sleep'?'正在准备睡眠':'摆腿 · '+cycles+' 轮';visibility();updateControls();
      const finished=await player.play(kind==='sleep'?sleepSequence:sequence,{cycles});
      if(!finished||closed||version!==actionVersion)return false;
      cancelAction(true);status.textContent='自然待机';resumeSchedules();return true;
    }catch(error){if(!closed&&version===actionVersion){cancelAction();status.textContent=error.message;resumeSchedules();}return false;}
  }
  function load(){
    cancelAction();clearTimeout(automaticTimer);clearTimeout(loadTimer);ready=false;paused=false;
    frame.hidden=true;poster.hidden=false;retry.hidden=true;sleep.disabled=sway.disabled=pet.disabled=gentle.disabled=greet.disabled=pause.disabled=true;pause.textContent='暂停动作';status.textContent='正在准备动作…';
    portraitBusy=false;frame.src='scene/portrait.html';
    loadTimer=setTimeout(()=>{if(!ready&&!closed){frame.removeAttribute('src');retry.hidden=false;status.textContent='动作准备超时，点击重新加载'}},25000);
  }
  ctx.scope.listen(window,'message',e=>{
    if(e.source!==frame.contentWindow||e.origin!==location.origin||closed)return;
    if(e.data?.type==='hecate:ready'){
      clearTimeout(loadTimer);ready=true;retry.hidden=true;sleep.disabled=sway.disabled=pet.disabled=gentle.disabled=greet.disabled=pause.disabled=false;frame.hidden=false;poster.hidden=true;status.textContent='自然待机';send('hecate:breathing',{value:Number(breathing.value)});visibility();updateControls();resumeSchedules();
    }else if(e.data?.type==='hecate:say'&&typeof e.data.text==='string'&&e.data.text.length<=4000){
      speech.textContent=e.data.text;
    }else if(e.data?.type==='hecate:state'&&typeof e.data.busy==='boolean'){
      const changed=portraitBusy!==e.data.busy;portraitBusy=e.data.busy;updateControls();if(changed){if(portraitBusy){clearTimeout(automaticTimer);sleeper?.cancelIdle(true);}else resumeSchedules();}if(ready&&!actionActive&&!paused&&portraitLabels[e.data.status])status.textContent=portraitLabels[e.data.status];
    }else if(e.data?.type==='hecate:error'){clearTimeout(loadTimer);ready=false;cancelAction();retry.hidden=false;status.textContent='人物动作没有启动成功，请重新加载'}
  });
  ctx.scope.listen(sway,'click',()=>runAction());
  ctx.scope.listen(sleep,'click',()=>actionKind==='sleep'?requestWake():runAction('sleep'));
  ctx.scope.listen(pet,'click',()=>send('hecate:pet'));
  ctx.scope.listen(gentle,'click',()=>send('hecate:sway'));
  const phrases=['窗外还有最后一点光。今天辛苦了。','不着急，我们一步一步来。','要开始学习了吗？我陪你。'];let phrase=0;
  ctx.scope.listen(greet,'click',()=>{speech.textContent=phrases[phrase++%phrases.length];send('hecate:blink')});
  ctx.scope.listen(pause,'click',()=>{paused=!paused;if(actionActive)cancelAction();pause.textContent=paused?'继续动作':'暂停动作';updateControls();status.textContent=paused?'动作已暂停':'自然待机';visibility();if(paused){clearTimeout(automaticTimer);sleeper?.cancelIdle(true);}else resumeSchedules()});
  ctx.scope.listen(retry,'click',load);
  ctx.scope.listen(document,'visibilitychange',()=>{if(document.hidden){cancelAction();clearTimeout(automaticTimer)}else resumeSchedules();visibility()});
  ctx.scope.own(()=>{closed=true;clearTimeout(loadTimer);clearTimeout(automaticTimer);cancelAction();sleeper?.destroy();observer.disconnect();cue('stop');send('hecate:dispose');frame.remove();poster.width=poster.height=1;original=null;sequence=null;page.remove()});
  root.HecateSceneChat.mount(page,{scope:ctx.scope,call:ctx.call,send,onBusy:value=>{chatBusy=value;if(value){clearTimeout(automaticTimer);sleeper?.cancelIdle(true);}else resumeSchedules();}});
  for(const event of ['focusin','focusout'])ctx.scope.listen(page,event,()=>queueMicrotask(()=>{if(closed)return;sleeper?.cancelIdle(true);sleeper?.schedule();}));
  load();prepareSleep();
}
root.HecateScene={mount};
})(window);
