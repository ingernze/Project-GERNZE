'use strict';
(function(global){
  const mounted=new WeakMap();
  const uid=()=>global.crypto?.randomUUID?.()||'dl-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
  function mount(options){
    const {container,onTurnComplete}=options;
    if(!container)throw Error('对话页需要容器');
    if(mounted.has(container))return mounted.get(container);
    const listeners=new AbortController();
    const motionPreference=global.matchMedia?.('(prefers-reduced-motion: reduce)'),motions=new Set(),motionByTarget=new WeakMap();
    let followQueued=false,sizedDraft=null;
    let disposed=false,visible=false,mode='live',liveTransport=options.transport||null,openMemoryCallback=options.openMemory||null;
    let sessionId=uid(),generation=0,active=null,turns=[],follow=true,memoryOpen=false,memoryEpoch=0,memoryHandle=null,savedScroll=0;
    let failDemoNext=false,baselineHeight=global.innerHeight||800;
    let historyCount=1,compressedRanges=[],historyGesture=false,expanding=false,touchY=null,gestureExpanded=false,lastWheel=0,scrollFrame=null;
    const views=new Map();
    const root=document.createElement('div');root.className='hebao-dialogue';
    root.innerHTML=`<div class="dl-main">
      <header class="dl-heading"><h2>对话</h2><div class="dl-session-tools"><p class="dl-connection" role="status"></p><details class="dl-demo-tools" hidden><summary aria-label="演示选项">···</summary><div class="dl-tools-popover"><p class="dl-modebar" hidden>界面演示 · 非真实对话，不保存</p><button type="button" class="dl-demo-long">填入长消息</button><button type="button" class="dl-demo-fail">下轮模拟失败：关</button><button type="button" class="dl-demo-exit">退出演示</button></div></details></div></header>
      <div class="dl-scroll" tabindex="0" aria-label="对话与记忆入口">
        <div class="dl-character-stage" data-dialogue-portrait-host><img alt="格莉兹静态半身展示"><small>静态立绘</small></div>
        <div class="dl-chat-card">
          <div class="dl-paper-ornament" aria-hidden="true"><svg viewBox="0 0 360 44" preserveAspectRatio="xMidYMid meet"><g fill="none" stroke="currentColor" stroke-width=".8"><path d="M5 36V20q0-8 8-8h123q10 0 15 9M355 36V20q0-8-8-8H224q-10 0-15 9M12 36V23q0-4 4-4h115M348 36V23q0-4-4-4H229"/><path d="M140 12q12-10 27-6M220 12q-12-10-27-6M148 25q-7-2-7-7q9-4 15 3M212 25q7-2 7-7q-9-4-15 3"/><circle cx="180" cy="16" r="13"/><circle cx="180" cy="16" r="10"/><path d="M180 8v2m8 6h-2m-6 8v-2m-8-6h2m6-5v5l4 3M180 0v3M176 0h8"/><path d="M25 12l3-3 3 3-3 3ZM329 12l3-3 3 3-3 3Z"/></g></svg></div>
          <div class="dl-card-heading"><div class="dl-speaker"><span aria-hidden="true">✧</span><strong>格莉兹</strong></div><span class="dl-presence" role="status">文字对话</span></div>
          <div class="dl-thread-label"><span>本次对话</span></div>
          <div class="dl-history-tools"><button class="dl-earlier" type="button" hidden>展开更早对话 ↑</button><button class="dl-collapse" type="button" hidden>只看最新</button><p class="dl-history-note" hidden></p></div>
          <div class="dl-log" role="log" aria-label="对话消息" aria-live="polite" aria-relevant="additions text"></div>
          <form class="dl-compose" hidden><div class="dl-compose-row"><textarea rows="2" maxlength="12000" aria-label="对话输入" placeholder="写下想说的话…"></textarea><span data-dialogue-voice-slot hidden></span><button class="dl-send" type="submit">发送</button></div><p class="dl-compose-note"><span class="dl-input-note"></span><span class="dl-shortcut">Ctrl/⌘ + Enter</span></p></form>
        </div>
        <button type="button" class="dl-books"><span class="dl-books-label"><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M3 5c4-1 6 0 9 2 3-2 5-3 9-2v14c-4-1-6 0-9 2-3-2-5-3-9-2V5Z"/><path d="M12 7v14M6 9l3 1M15 10l3-1"/></svg><span>记忆书架<small>每月一本，每天一页</small></span></span><span class="dl-books-arrow" aria-hidden="true">›</span></button>
      </div><button type="button" class="dl-more" hidden>回到最新消息 ↓</button>
    </div><section class="dl-memory" aria-label="记忆书架" hidden><header class="dl-memory-head"><button class="dl-back" type="button">‹ 返回对话</button><h2>记忆书架</h2></header><div id="dialogueMemoryHost" class="dl-memory-host"></div></section>`;
    container.replaceChildren(root);
    const $=s=>root.querySelector(s),main=$('.dl-main'),memoryPanel=$('.dl-memory'),host=$('#dialogueMemoryHost'),log=$('.dl-log'),input=$('textarea'),sendButton=$('.dl-send'),more=$('.dl-more'),connection=$('.dl-connection');
    $('.dl-character-stage img').src=options.portraitSrc||'portrait/original.png';
    const scroller=$('.dl-scroll'),card=$('.dl-chat-card'),composer=$('.dl-compose');
    root.style.setProperty('--dl-scene-image','url('+JSON.stringify(options.sceneSrc||global.OFFLINE_BACKGROUND||'scene/window-dusk.png')+')');
    // New background is original scene art. Keep the previous sceneSrc contract.
    const artSceneSrc=options.artSceneSrc||'scene/study-soft-classic.png';
    const artSceneValue='url('+JSON.stringify(artSceneSrc)+')';
    root.style.setProperty('--dl-art-scene',artSceneValue);
    container.closest('.shell')?.style.setProperty('--dl-art-scene',artSceneValue);
    const on=(target,event,fn,options={})=>target.addEventListener(event,fn,{...options,signal:listeners.signal});
    // The shelf entry and composer stay outside the message scroller. Long
    // replies can no longer push the entry away or drag the input with them.
    $('.dl-heading').append($('.dl-books'));
    main.append(composer);
    const shelfBack=document.createElement('button');shelfBack.type='button';shelfBack.className='dl-shelf-back';shelfBack.textContent='返回书架';shelfBack.hidden=true;$('.dl-memory-head').append(shelfBack);
    function cancelMotions(){for(const motion of motions){try{motion.cancel();}catch{}}motions.clear();}
    function entrance(element,distance=5){
      if(disposed||!visible||motionPreference?.matches||typeof element.animate!=='function')return;
      motionByTarget.get(element)?.cancel();
      const motion=element.animate([{opacity:.72,transform:'translateY('+distance+'px)'},{opacity:1,transform:'translateY(0)'}],{duration:180,easing:'cubic-bezier(.2,.7,.25,1)'});
      motions.add(motion);motionByTarget.set(element,motion);
      const done=()=>{motions.delete(motion);if(motionByTarget.get(element)===motion)motionByTarget.delete(element);};
      Promise.resolve(motion.finished).then(done,done);
    }
    function available(){return mode==='demo'||typeof liveTransport?.send==='function';}
    function updateControls(){
      composer.hidden=!available();root.dataset.chatReady=String(available());root.dataset.hasTurns=String(turns.length>0);
      sendButton.textContent=active?'停止':'发送';sendButton.dataset.stop=String(Boolean(active));sendButton.disabled=!active&&(!available()||!input.value.trim());
      sendButton.setAttribute('aria-label',active?'停止本轮回复':'发送消息');log.setAttribute('aria-busy',String(Boolean(active)));
      connection.textContent=mode==='demo'?'演示 · 非真实对话':available()?'对话已连接':'尚未连接API';
      root.dataset.replyState=active?.turn.state||'idle';$('.dl-presence').textContent=active?(active.turn.state==='streaming'?'回复中':'等待回复'):mode==='demo'?'界面演示':available()?'文字对话':'等待连接';
      $('.dl-modebar').hidden=mode!=='demo';$('.dl-demo-tools').hidden=mode!=='demo';
      $('.dl-input-note').textContent=mode==='demo'?'演示不调用API，也不保存对话':available()?'回复内容以实际连接的服务为准':'';
      $('.dl-demo-fail').textContent='下轮模拟失败：'+(failDemoNext?'开':'关');
      card.style.removeProperty('min-height');
      if(input.value!==sizedDraft)resizeInput();
    }
    function resizeInput(){input.style.height='auto';input.style.height=Math.min(input.scrollHeight||46,global.innerHeight<520?66:106)+'px';sizedDraft=input.value;}
    function latestEdge(){return Math.max(0,scroller.scrollHeight-scroller.clientHeight);}
    function afterUpdate(){
      if(follow&&!memoryOpen&&visible){if(followQueued)return;followQueued=true;requestAnimationFrame(()=>{followQueued=false;if(!disposed&&follow&&!memoryOpen&&visible&&turns.length)scroller.scrollTop=latestEdge();});}
      else if(turns.length)more.hidden=false;
    }
    function empty(){
      log.replaceChildren();views.clear();
      const box=document.createElement('div');box.className='dl-empty';
      const mark=document.createElement('div');mark.className='dl-empty-mark';mark.textContent='✧';
      const title=document.createElement('h3');title.textContent=mode==='demo'?'写下一句，看看对话展开':'从这里开始对话';
      const text=document.createElement('p');text.textContent=mode==='demo'?'界面演示不调用API，也不会写入记忆。':available()?'可以从下方输入框开始对话。':'连接API后可正式聊天，也可以先体验界面。';
      box.append(mark,title,text);
      if(mode==='live'&&!available()){
        const button=document.createElement('button');button.type='button';button.className='dl-demo-start';button.textContent='体验界面演示';button.onclick=enterDemo;box.append(button);
      }
      log.append(box);more.hidden=true;
    }
    function getView(turn){
      if(views.has(turn.id))return views.get(turn.id);
      if(views.size===0)log.replaceChildren();
      const article=document.createElement('article');article.className='dl-turn';
      function message(role,label){const node=document.createElement('div');node.className='dl-message dl-message-'+role;const meta=document.createElement('p');meta.className='dl-meta';meta.textContent=label;const bubble=document.createElement('div');bubble.className='dl-bubble';node.append(meta,bubble);article.append(node);return {node,meta,bubble};}
      const user=message('user','你'),assistant=message('assistant',turn.mode==='demo'?'演示回复':'格莉兹');const note=document.createElement('div');note.className='dl-result-note';article.append(note);log.append(article);
      const view={article,user,assistant,note,replyText:null,waitingShown:false,noteKey:null};views.set(turn.id,view);if(!memoryOpen&&active?.turn===turn){entrance(user.node,5);entrance(assistant.node,3);}return view;
    }
    function updateTurn(turn){
      const view=getView(turn);if(view.user.bubble.textContent!==turn.input)view.user.bubble.textContent=turn.input;
      view.assistant.node.dataset.state=turn.state;if(active?.turn===turn){root.dataset.replyState=turn.state;$('.dl-presence').textContent=turn.state==='streaming'?'回复中':'等待回复';}
      const label=turn.mode==='demo'?'演示回复 · 非真实对白':'格莉兹';if(view.assistant.meta.textContent!==label)view.assistant.meta.textContent=label;
      if(turn.state==='waiting'&&!turn.reply){
        if(!view.waitingShown){const star=document.createElement('span');star.className='dl-wait-star';star.setAttribute('aria-hidden','true');star.textContent='✦';view.assistant.bubble.replaceChildren(star,document.createTextNode('等待回复…'));view.waitingShown=true;view.replyText=null;}
      }else{
        const text=turn.reply||'本轮没有生成回复。';
        if(!view.replyText){view.replyText=document.createTextNode(text);view.assistant.bubble.replaceChildren(view.replyText);}
        else if(view.replyText.data!==text)view.replyText.data=text;
        view.waitingShown=false;
      }
      // Keep unchanged text and controls mounted across stream updates. This
      // avoids re-entering bubbles, losing text selection, or dropping focus.
      const noteKey=[turn.state,turn.mode,turn===turns.at(-1),Boolean(active),available()].join(':');
      if(noteKey===view.noteKey)return;view.noteKey=noteKey;view.note.replaceChildren();
      if(turn.state==='failed'||turn.state==='cancelled'){
        const text=document.createElement('span');text.textContent=turn.state==='failed'?'本轮发送未完成，请检查连接后重试。':'已停止 · 本轮未完成';view.note.append(text);
        if(turn===turns.at(-1)){const retry=document.createElement('button');retry.type='button';retry.className='dl-retry';retry.textContent='重试这一轮';retry.disabled=Boolean(active)||!available();retry.onclick=()=>run(turn);view.note.append(retry);}
      }else if(turn.state==='complete'&&turn.mode==='demo')view.note.textContent='界面测试文字，不是角色设定或真实记忆。';
    }
    function readableTurns(){
      let index=0;return turns.filter(turn=>{
        const start=index;if(turn.state==='complete')index+=2;
        return turn.state!=='complete'||!compressedRanges.some(r=>start>=r.start&&start+2<=r.end);
      });
    }
    function draw(){
      const readable=readableTurns(),shown=readable.slice(-historyCount),ids=new Set(shown.map(t=>t.id));
      for(const [id,view]of views)if(!ids.has(id)){view.article.remove();views.delete(id);}
      if(!turns.length)empty();else{
        if(!shown.length){log.replaceChildren();views.clear();const note=document.createElement('p');note.className='dl-empty';note.textContent='较早对话已整理成记忆，可以从下方继续聊天。';log.append(note);}
        for(const turn of shown)updateTurn(turn);
        for(let i=0;i<shown.length;i++){const node=views.get(shown[i].id).article;if(log.children[i]!==node)log.insertBefore(node,log.children[i]||null);}
      }
      const remaining=Math.max(0,readable.length-shown.length);
      $('.dl-earlier').hidden=!remaining;$('.dl-earlier').textContent='展开更早对话（'+remaining+'轮）↑';
      $('.dl-collapse').hidden=shown.length<=1;
      const note=$('.dl-history-note');note.hidden=!compressedRanges.length;
      note.textContent='已压缩的对话不在这里展开，原文仍保存在本机。';
      updateControls();
    }
    function collapseHistory(){historyCount=1;historyGesture=false;follow=true;draw();more.hidden=true;afterUpdate();}
    function expandEarlier(){
      if(expanding||!visible||memoryOpen||$('.dl-earlier').hidden)return;
      expanding=true;historyGesture=true;follow=false;
      const anchor=log.querySelector('.dl-turn'),before=anchor?.getBoundingClientRect().top,top=scroller.scrollTop;
      historyCount+=5;draw();
      if(anchor?.isConnected)scroller.scrollTop=top+anchor.getBoundingClientRect().top-before;
      requestAnimationFrame(()=>{expanding=false;});
    }
    function olderGesture(){historyGesture=true;follow=false;if(!gestureExpanded&&scroller.scrollTop<=50&&!$('.dl-earlier').hidden){gestureExpanded=true;expandEarlier();}}
    function history(until=null){
      const result=[];
      for(const turn of turns){if(turn===until)break;if(turn.state==='complete')result.push({role:'user',content:turn.input},{role:'assistant',content:turn.reply});}
      return result;
    }
    function valid(request){return !disposed&&active===request&&request.generation===generation&&request.session===sessionId;}
    function cancel(){
      if(!active)return false;const old=active;active=null;generation++;old.controller.abort();old.turn.state='cancelled';updateTurn(old.turn);updateControls();afterUpdate();return true;
    }
    function delay(ms,signal){return new Promise((resolve,reject)=>{if(signal.aborted)return reject(Error('aborted'));const abort=()=>{clearTimeout(timer);reject(Error('aborted'));};const timer=setTimeout(()=>{signal.removeEventListener('abort',abort);resolve();},ms);signal.addEventListener('abort',abort,{once:true});});}
    async function demoSend({signal,onDelta}){
      const shouldFail=failDemoNext;failDemoNext=false;updateControls();await delay(950,signal);if(shouldFail)throw Error('demo failure');
      const reply='【界面演示】\n这段文字只用于检查消息排版，不是格莉兹的实际回复。\n\n这里可以观察较长的文字如何换行、滚动，以及输入框是否保持可见。向上翻看时，新片段不会强行把页面拉回底部；需要时可以点“回到最新消息”。\n\n你也可以在等待期间点“停止”，或主动模拟一次失败后重试。停止和失败的半轮消息不会混入下一次请求。\n\n这里没有连接任何聊天API，也没有写入记忆、生成摘要或执行人物动作。';
      for(let i=0;i<reply.length;i+=18){await delay(95,signal);onDelta(reply.slice(i,i+18));}
      return {id:uid(),reply};
    }
    async function run(turn){
      if(disposed||active||!available()||turn!==turns.at(-1))return false;
      turn.state='waiting';turn.reply='';follow=true;more.hidden=true;
      const request={generation:++generation,session:sessionId,controller:new AbortController(),turn,mode};active=request;draw();afterUpdate();
      try{
        const payload={input:turn.input,messages:[...history(turn),{role:'user',content:turn.input}],signal:request.controller.signal,onDelta:delta=>{
          if(!valid(request)||typeof delta!=='string')return;
          if(turn.reply.length+delta.length>100000){active=null;turn.state='failed';request.controller.abort();draw();afterUpdate();return;}
          turn.reply+=delta;turn.state='streaming';updateTurn(turn);afterUpdate();
        }};
        const result=await(mode==='demo'?demoSend(payload):liveTransport.send(payload));
        if(!valid(request))return false;
        if(!result||typeof result.reply!=='string'||!result.reply.trim()||result.reply.length>100000)throw Error('invalid reply');
        // Final text replaces all streamed fragments; never append it a second time.
        turn.reply=result.reply;turn.state='complete';turn.responseId=typeof result.id==='string'?result.id:uid();active=null;draw();afterUpdate();
        const detail={id:turn.responseId,sessionId:request.session,messages:history(),createdAt:new Date().toISOString(),mode:request.mode};
        if(typeof onTurnComplete==='function')Promise.resolve().then(()=>{if(!disposed&&request.generation===generation&&request.session===sessionId)return onTurnComplete(detail);}).catch(()=>{if(!disposed&&request.generation===generation&&request.session===sessionId)$('.dl-input-note').textContent='回复已完成，接收结果尚未确认';});
        return true;
      }catch(error){if(!valid(request))return false;active=null;turn.state='failed';draw();afterUpdate();return false;}
    }
    function send(){
      if(active)return cancel();const text=input.value.trim();if(!text||!available()||disposed)return false;
      const turn={id:uid(),input:text,reply:'',state:'waiting',mode};turns.push(turn);input.value='';run(turn);return true;
    }
    function clearSession(id=uid()){
      cancel();cancelMotions();$('.dl-demo-tools').open=false;generation++;sessionId=id;turns=[];historyCount=1;compressedRanges=[];historyGesture=false;views.clear();follow=true;scroller.scrollTop=0;draw();
    }
    function enterDemo(){if(disposed||active||mode==='demo')return;closeMemory(false);mode='demo';clearSession();updateControls();input.focus();}
    function exitDemo(){if(mode!=='demo')return;cancel();mode='live';failDemoNext=false;clearSession();}
    function disposeMemory(handle){try{if(typeof handle==='function')handle();else if(typeof handle?.destroy==='function')handle.destroy();else handle?.close?.();}catch{}}
    function placeholder(text,small){const node=document.createElement('div');node.className='dl-memory-placeholder';const p=document.createElement('p');p.textContent=text;const hint=document.createElement('small');hint.textContent=small;node.append(p,hint);return node;}
    async function openMemory(){
      if(disposed||memoryOpen)return;$('.dl-demo-tools').open=false;memoryOpen=true;const ticket=++memoryEpoch;savedScroll=scroller.scrollTop;cancelMotions();main.hidden=true;memoryPanel.hidden=false;entrance(memoryPanel,6);
      root.dataset.memoryView='shelf';$('.dl-memory-head h2').textContent='记忆书架';shelfBack.hidden=true;
      const child=document.createElement('div');child.className='dl-memory-mount';child.dataset.memoryLayout='mobile';child.style.height='100%';host.replaceChildren(child);$('.dl-back').focus({preventScroll:true});
      if(typeof openMemoryCallback!=='function'){child.append(placeholder('记忆书架尚未接入','返回对话后，草稿和消息会留在原处。'));return;}
      try{
        const handle=await openMemoryCallback({container:child,onClose:()=>{if(ticket===memoryEpoch)closeMemory();}});
        if(disposed||!memoryOpen||ticket!==memoryEpoch){disposeMemory(handle);return;}memoryHandle=handle;
      }catch{if(ticket===memoryEpoch&&!disposed)child.replaceChildren(placeholder('记忆书架暂时打不开','可以先返回对话，稍后再试。'));}
    }
    function closeMemory(focus=true){
      if(!memoryOpen)return;memoryOpen=false;memoryEpoch++;const handle=memoryHandle;memoryHandle=null;disposeMemory(handle);host.replaceChildren();cancelMotions();memoryPanel.hidden=true;main.hidden=false;if(focus)entrance(main,3);
      const closeSession=sessionId,closeEpoch=memoryEpoch;requestAnimationFrame(()=>{if(!disposed&&!memoryOpen&&closeSession===sessionId&&closeEpoch===memoryEpoch){scroller.scrollTop=savedScroll;if(focus&&visible)$('.dl-books').focus({preventScroll:true});}});
    }
    function viewport(){
      if(disposed)return;const shell=container.closest('.shell');if(!shell)return;
      if(!visible){delete shell.dataset.dialogueKeyboard;shell.style.removeProperty('--dialogue-viewport-height');return;}
      const height=Math.min(global.innerHeight||800,global.visualViewport?.height||Infinity),focused=document.activeElement===input;
      if(!focused)baselineHeight=Math.max(height,global.innerHeight||height);
      shell.dataset.dialogueKeyboard=String(focused&&baselineHeight-height>120);
      shell.style.setProperty('--dialogue-viewport-height',Math.max(200,height)+'px');resizeInput();
    }
    on($('.dl-compose'),'submit',e=>{e.preventDefault();send();});
    on(input,'input',()=>{resizeInput();updateControls();if(follow&&turns.length)afterUpdate();});on(input,'focus',()=>{$('.dl-demo-tools').open=false;viewport();});on(input,'blur',()=>requestAnimationFrame(viewport));
    on(input,'keydown',e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)&&!e.isComposing&&e.keyCode!==229){e.preventDefault();send();}});
    on($('.dl-earlier'),'click',expandEarlier);on($('.dl-collapse'),'click',collapseHistory);
    on(scroller,'wheel',event=>{if(event.timeStamp-lastWheel>220)gestureExpanded=false;lastWheel=event.timeStamp;if(event.deltaY<0)olderGesture();else{historyGesture=false;gestureExpanded=false;}},{passive:true});
    on(scroller,'touchstart',event=>{touchY=event.touches[0]?.clientY;historyGesture=false;gestureExpanded=false;follow=false;},{passive:true});
    on(scroller,'touchmove',event=>{const y=event.touches[0]?.clientY;if(touchY!==null&&y-touchY>12)olderGesture();else if(touchY!==null&&y-touchY< -12)historyGesture=false;},{passive:true});
    on(scroller,'touchend',()=>{touchY=null;},{passive:true});on(scroller,'touchcancel',()=>{touchY=null;},{passive:true});
    on(scroller,'keydown',event=>{if(event.target===scroller&&['ArrowUp','PageUp','Home'].includes(event.key)){gestureExpanded=false;olderGesture();}});
    on(scroller,'scroll',()=>{if(scrollFrame!==null)return;scrollFrame=requestAnimationFrame(()=>{scrollFrame=null;if(disposed||!visible)return;if(historyGesture)olderGesture();if(!historyGesture&&!expanding)follow=latestEdge()-scroller.scrollTop<50;more.hidden=follow||!turns.length;});},{passive:true});
    on(more,'click',()=>{historyGesture=false;follow=true;more.hidden=true;scroller.scrollTop=latestEdge();});
    on($('.dl-demo-exit'),'click',()=>{$('.dl-demo-tools').open=false;exitDemo();});on($('.dl-demo-long'),'click',()=>{$('.dl-demo-tools').open=false;input.value='【合成长消息】\n这是一条用于查看窄屏排版的测试输入，不是真实聊天或记忆。\n\n'+('这一段用于检查长文字自动换行、输入框高度、消息滚动和键盘下的发送位置。'.repeat(8));updateControls();input.focus();});
    on($('.dl-demo-fail'),'click',()=>{failDemoNext=!failDemoNext;updateControls();});
    on($('.dl-books'),'click',openMemory);on($('.dl-back'),'click',()=>closeMemory());
    on(shelfBack,'click',()=>host.querySelector('[data-action="shelf"]')?.click());
    on(host,'memory-books:view',event=>{root.dataset.memoryView=event.detail.view;shelfBack.hidden=event.detail.view!=='reader';$('.dl-memory-head h2').textContent=event.detail.view==='reader'?event.detail.monthLabel:'记忆书架';});
    on(root,'pointerdown',event=>{if(!event.target.closest?.('.dl-demo-tools'))$('.dl-demo-tools').open=false;});
    on(root,'keydown',event=>{if(event.key==='Escape'&&$('.dl-demo-tools').open){$('.dl-demo-tools').open=false;$('.dl-demo-tools summary').focus({preventScroll:true});event.preventDefault();}});
    on(global,'resize',viewport);if(global.visualViewport){on(global.visualViewport,'resize',viewport);on(global.visualViewport,'scroll',viewport);}
    if(motionPreference?.addEventListener)on(motionPreference,'change',cancelMotions);
    function validateRanges(ranges,length){
      if(!Array.isArray(ranges))throw Error('压缩范围无效。');
      return ranges.filter(r=>Number.isSafeInteger(r.start)&&Number.isSafeInteger(r.end)&&r.start>=0&&r.end>r.start&&!(r.start%2)&&!(r.end%2)&&r.end<=length).map(({start,end})=>({start,end}));
    }
    const api=Object.freeze({
      setCompressedRanges({id,ranges}){if(disposed||id!==sessionId)return;compressedRanges=validateRanges(ranges,history().length);draw();afterUpdate();},
      setVisible(value){if(disposed)return;const wasVisible=visible;visible=Boolean(value);if(!visible){$('.dl-demo-tools').open=false;cancelMotions();cancel();closeMemory(false);}viewport();if(visible&&!wasVisible){collapseHistory();entrance(main,4);}},
      setTransport(value){if(disposed)return;if(value!==null&&typeof value?.send!=='function')throw Error('transport需要send函数');cancel();liveTransport=value;if(mode==='demo'){mode='live';clearSession();}draw();},
      setOpenMemory(value){if(disposed)return;if(value!==null&&typeof value!=='function')throw Error('openMemory需要函数');closeMemory(false);openMemoryCallback=value;},
      newSession({id=uid()}={}){if(disposed)return;if(typeof id!=='string'||!id)throw Error('无效会话编号');closeMemory(false);clearSession(id);input.value='';updateControls();},
      restoreSession({id,messages,draft='',compressed=[]}){
        if(disposed)return;
        if(typeof id!=='string'||!id||!Array.isArray(messages)||messages.length%2||messages.length>20000||typeof draft!=='string')throw Error('保存的会话不完整。');
        for(let i=0;i<messages.length;i++)if(messages[i]?.role!==(i%2?'assistant':'user')||typeof messages[i]?.content!=='string'||messages[i].content.length>12000)throw Error('保存的消息不完整。');
        closeMemory(false);mode='live';clearSession(id);
        for(let i=0;i<messages.length;i+=2)turns.push({id:'restored-'+i,input:messages[i].content,reply:messages[i+1].content,state:'complete',mode:'live'});
        compressedRanges=validateRanges(compressed,messages.length);input.value=draft.slice(0,12000);draw();afterUpdate();
      },
      getSnapshot(){return {id:sessionId,mode,draft:input.value,messages:history(),turns:turns.map(t=>({...t})),pending:Boolean(active),scrollTop:scroller.scrollTop,memoryOpen};},
      getVoiceSlot(){return $('[data-dialogue-voice-slot]');},
      openMemory,closeMemory,
      destroy(){if(disposed)return;cancel();closeMemory(false);disposed=true;generation++;cancelMotions();if(scrollFrame!==null)cancelAnimationFrame(scrollFrame);listeners.abort();const shell=container.closest('.shell');if(shell){delete shell.dataset.dialogueKeyboard;shell.style.removeProperty('--dialogue-viewport-height');shell.style.removeProperty('--dl-art-scene');}container.replaceChildren();mounted.delete(container);}
    });
    mounted.set(container,api);draw();return api;
  }
  global.HebaoDialoguePage=Object.freeze({mount});
})(window);
