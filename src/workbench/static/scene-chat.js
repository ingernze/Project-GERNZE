'use strict';
(function(root){
function mount(host,{scope,call,send,onBusy=()=>{}}) {
  const embedded=Boolean(host.closest('[data-scene-mode="room"]'));const stage=host.closest('.desktop-scene-stage');
  const h=(tag,cls,text)=>{const e=document.createElement(tag);e.className=cls||'';if(text!==undefined)e.textContent=text;return e;};
  const area=h('section','scene-chat desktop-dialogue'),header=h('header','desktop-chat-heading');header.append(h('div','', '对话'),h('span','desktop-chat-caption','格莉兹 · GERNZE'));
  const toolbar=h('div','desktop-history-tools'),earlier=h('button','scene-button','展开更早对话 ↑'),collapse=h('button','scene-button','只看最新一轮');earlier.type=collapse.type='button';earlier.hidden=collapse.hidden=true;toolbar.append(earlier,collapse);
  const history=h('div','desktop-chat-history');history.tabIndex=0;history.setAttribute('aria-label','已保存的聊天对话');const log=h('div','desktop-chat-log');log.setAttribute('role','log');log.setAttribute('aria-live','polite');history.append(log);
  const historyNote=h('p','subtle desktop-history-note');historyNote.hidden=true;
  const form=h('form','scene-chat-input'),input=h('textarea');input.rows=2;input.placeholder='写下想说的话…';input.maxLength=1000;input.setAttribute('aria-label','和格莉兹说句话');
  const submit=h('button','scene-button','发送'),cancel=h('button','scene-button','停止等待');submit.type='submit';cancel.type='button';cancel.hidden=true;form.append(input,submit,cancel);form.hidden=true;
  const status=h('p','scene-status','正在读取聊天设置…');status.role='status';const footer=h('div','desktop-chat-footer'),setup=h('button','scene-button desktop-open-settings','前往设置'),bookButton=h('button','scene-button desktop-books-button','记忆书架');setup.type=bookButton.type='button';setup.hidden=true;footer.append(setup,bookButton);area.append(header,toolbar,history,historyNote,form,status,footer);host.append(area);
  if(embedded)area.hidden=true;
  let started=false,revealFrame=null;
  let disposed=false,configured=false,busy=false,chat=null,activeId=null,turns=[],hasMore=false,before=null,historyVersion=0,historyBusy=false;
  const signal=new AbortController();scope.own(()=>signal.abort());
  function draw(){log.replaceChildren();if(!turns.length)log.append(h('p','desktop-chat-empty','从这里开始，慢慢聊。'));
    for(const t of turns){const article=h('article','desktop-chat-turn');article.dataset.turn=t.id;article.append(h('p','desktop-message-label','你'),h('p','desktop-message desktop-message-user',t.input));article.append(h('p','desktop-message-label','格莉兹'),h('p','desktop-message desktop-message-assistant',t.reply||(t.status==='pending'?'正在想…':'这一轮回复未完成，原文仍已保存。')));log.append(article);}
    earlier.hidden=!hasMore;collapse.hidden=turns.length<=1;
  }
  async function loadHistory(older=false){if(disposed||older&&historyBusy||older&&!hasMore)return;const n=++historyVersion;historyBusy=true;earlier.disabled=true;
    const oldHeight=history.scrollHeight,oldTop=history.scrollTop;
    try{const value=await call('chat.history',older?{limit:5,before}:{limit:1},signal.signal);if(disposed||n!==historyVersion)return;
      turns=older?[...value.turns,...turns.filter(t=>!value.turns.some(x=>x.id===t.id))]:value.turns;hasMore=value.hasMore;before=turns[0]?.seq??null;historyNote.hidden=!value.compressedTurns;historyNote.textContent='已压缩的轮次不在这里展开，原文仍可从记忆书架查看。';draw();
      history.scrollTop=older?oldTop+(history.scrollHeight-oldHeight):history.scrollHeight;
    }catch(e){if(!disposed&&n===historyVersion)status.textContent=e.message||'对话没有读取成功。';}
    finally{if(!disposed&&n===historyVersion){historyBusy=false;earlier.disabled=false;}}
  }
  function apply(config){configured=config.configured;form.hidden=!configured;setup.hidden=configured;status.textContent=configured?'Ctrl / ⌘ + Enter 发送':'聊天尚未启用，可前往设置配置连接。';}
  function setBusy(value){busy=value;onBusy(value);submit.disabled=value;cancel.hidden=!value;}
  function stop(){if(!busy&&!activeId)return;const id=activeId;chat.cancel();activeId=null;historyVersion++;historyBusy=false;const stopped=call('chat.cancel',id?{request_id:id}:{}).catch(()=>{});setBusy(false);status.textContent='已停止等待这条回复。';stopped.then(()=>{if(!disposed&&!busy)loadHistory();});}
  const memory=root.HecateSceneMemory.mount(embedded?host:area,{scope,call,bookshelfOnly:true,onOpen:stop,onChange:()=>{if(disposed)return;stop();loadHistory();status.textContent='记忆已更新，下一次发送使用当前版本。';}});
  chat=root.HebaoChat.create({requestReply:({text,signal})=>{
      activeId=crypto.randomUUID();turns=[{id:activeId,input:text,reply:'',status:'pending'}];draw();return call('chat.reply',{text,request_id:activeId},signal);
    },onReply:reply=>{if(disposed)return;send('hecate:reply',{reply});activeId=null;loadHistory();memory.refresh();},onStatus:(state,error)=>{if(disposed)return;setBusy(state==='loading');status.textContent=state==='loading'?'格莉兹正在想…':state==='error'?(error?.message||'回复未完成，请稍后重试。'):'已收到回复。';if(state==='error'){activeId=null;loadHistory();}}});
  scope.own(()=>{const id=activeId;disposed=true;historyVersion++;chat.destroy();if(id)call('chat.cancel',{request_id:id}).catch(()=>{});area.remove();});
  scope.listen(form,'submit',e=>{e.preventDefault();if(!configured||busy||!input.value.trim())return;const text=input.value;input.value='';chat.send(text);});
  scope.listen(input,'keydown',e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();form.requestSubmit();}});
  scope.listen(cancel,'click',stop);scope.listen(earlier,'click',()=>loadHistory(true));scope.listen(collapse,'click',()=>loadHistory());
  scope.listen(history,'wheel',e=>{if(e.deltaY<0&&history.scrollTop<28&&!busy)loadHistory(true);});scope.listen(history,'keydown',e=>{if(['ArrowUp','PageUp'].includes(e.key)&&history.scrollTop<28&&!busy)loadHistory(true);});
  scope.listen(setup,'click',()=>host.dispatchEvent(new CustomEvent('gernze:open-settings',{bubbles:true})));
  scope.listen(bookButton,'click',()=>memory.open());
  function initialize(){if(started||disposed)return;started=true;
    call('chat.config.get',{},signal.signal).then(c=>{if(!disposed)apply(c);}).catch(()=>{if(!disposed){status.textContent='请从本机启动器打开工作台。';setup.hidden=false;}});loadHistory();
  }
  function changed(open){host.dispatchEvent(new CustomEvent('gernze:conversation-visibility',{bubbles:true,detail:{open}}));}
  function open(){if(disposed)return;area.hidden=false;initialize();
    if(embedded){cancelAnimationFrame(revealFrame);revealFrame=requestAnimationFrame(()=>{if(!disposed&&!area.hidden)stage.classList.add('is-chat-view');});}
    changed(true);
  }
  function close(){if(disposed)return;stop();cancelAnimationFrame(revealFrame);area.hidden=true;stage?.classList.remove('is-chat-view');changed(false);}
  if(embedded){
    bookButton.remove();const fold=h('button','scene-button desktop-fold-chat','收起对话');fold.type='button';header.append(fold);scope.listen(fold,'click',close);
    scope.listen(area,'keydown',e=>{if(e.key==='Escape'&&!host.querySelector('.desktop-books-overlay:not([hidden])')){e.preventDefault();close();}});
  }else initialize();
  const controller=Object.freeze({refresh:()=>loadHistory(),memory,open,close,openBooks:()=>memory.open()});
  if(embedded)host.GernzeSceneConversation=controller;
  scope.own(()=>{cancelAnimationFrame(revealFrame);if(host.GernzeSceneConversation===controller)delete host.GernzeSceneConversation;});
  return controller;
}
function mountSettings(host,{scope,call}) {
  const h=(tag,cls,text)=>{const e=document.createElement(tag);e.className=cls||'';if(text!==undefined)e.textContent=text;return e;};
  const details=h('details','scene-chat-settings'),summary=h('summary','','聊天连接'),settings=h('form','scene-chat-config'),enabled=h('input');enabled.type='checkbox';enabled.id='scene-chat-enabled';
  const enabledLabel=h('label','scene-chat-enable');enabledLabel.append(enabled,document.createTextNode('启用聊天 API'));
  const endpoint=h('input'),model=h('input'),key=h('input');endpoint.type='url';endpoint.required=true;endpoint.maxLength=2048;model.required=true;model.maxLength=150;key.type='password';key.autocomplete='new-password';key.maxLength=4096;
  function field(label,input,id){input.id=id;const e=h('label');e.htmlFor=id;e.append(h('span','',label),input);return e;}
  const save=h('button','scene-button','保存连接'),remove=h('button','scene-button','移除密钥');save.type='submit';remove.type='button';const buttons=h('div','scene-chat-buttons');buttons.append(save,remove);
  settings.append(enabledLabel,field('接口地址',endpoint,'scene-chat-endpoint'),field('模型名称',model,'scene-chat-model'),field('API 密钥（留空保留已存密钥）',key,'scene-chat-key'),buttons,h('p','subtle','密钥保存在本机 Windows 凭据管理器。保存连接不会发送请求。'));details.append(summary,settings);
  summary.textContent='聊天 API';details.open=true;host.append(details);
  const status=h('p','scene-status','正在读取聊天设置…');status.role='status';host.append(status);
  const signal=new AbortController();let disposed=false,keyPresent=false;
  scope.own(()=>{disposed=true;signal.abort();key.value='';details.remove();status.remove();});
  function apply(config){enabled.checked=config.enabled;endpoint.value=config.endpoint;model.value=config.model;key.value='';keyPresent=config.key_present;remove.disabled=!keyPresent;status.textContent=config.configured?'聊天连接已就绪，发送后才连接服务。':'聊天未配置或已关闭。';}
  scope.listen(settings,'submit',async e=>{e.preventDefault();save.disabled=true;remove.disabled=true;const config={enabled:enabled.checked,endpoint:endpoint.value.trim(),model:model.value.trim()};if(key.value.trim())config.key=key.value.trim();try{const result=await call('chat.config.set',{settings:config},signal.signal);if(disposed)return;apply(result);status.textContent='连接已保存，尚未发送请求。';}catch(e){if(!disposed)status.textContent=e.message;}finally{key.value='';if(!disposed){save.disabled=false;remove.disabled=!keyPresent;}}});
  scope.listen(remove,'click',async()=>{remove.disabled=save.disabled=true;try{const result=await call('chat.key.delete',{},signal.signal);if(!disposed)apply(result);}catch(e){if(!disposed)status.textContent=e.message;}finally{if(!disposed){save.disabled=false;remove.disabled=!keyPresent;}}});
  call('chat.config.get',{},signal.signal).then(c=>{if(!disposed)apply(c);}).catch(()=>{if(!disposed){status.textContent='聊天设置暂时未能读取，请重新打开设置。';save.disabled=remove.disabled=true;}});
}
root.HecateSceneChat={mount,mountSettings};
})(window);
