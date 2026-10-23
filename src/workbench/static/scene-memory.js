/* Monthly books and owner-delegated desktop AI review; no manual-add entry. */
(function(root){
'use strict';
function mount(host,{scope,call,onChange=()=>{},onOpen=()=>{},settingsOnly=false,bookshelfOnly=false}){
  const h=(tag,cls,text)=>{const e=document.createElement(tag);e.className=cls||'';if(text!==undefined)e.textContent=text;return e;};
  const panel=h('section','desktop-memory'),heading=h('div','desktop-memory-heading');
  heading.append(h('div','', '记忆与原文'));
  const open=h('button','scene-button','打开记忆书架'),refresh=h('button','scene-button','刷新保存状态');open.type=refresh.type='button';heading.append(open,refresh);
  const state=h('p','scene-status','按需读取保存状态。');state.role='status';panel.append(heading,state);
  const groups=h('div','desktop-memory-groups');panel.append(groups);if(!bookshelfOnly)host.append(panel);
  const signal=new AbortController();let disposed=false,busy=false,version=0,snapshot=null,books=null,returnFocus=null;
  const overlay=h('div','desktop-books-overlay');overlay.hidden=true;overlay.setAttribute('role','dialog');overlay.setAttribute('aria-modal','true');overlay.setAttribute('aria-label','记忆书架');
  const shell=h('div','desktop-books-shell'),bookHost=h('div','desktop-books-host'),unknown=h('details','desktop-undated');unknown.append(h('summary','','日期不明的原文'));bookHost.dataset.memoryLayout='gold';shell.append(bookHost,unknown);overlay.append(shell);
  const sceneRoom=host.querySelector('.scene-room');if(sceneRoom){overlay.classList.add('desktop-books-focus');sceneRoom.append(overlay);}else host.append(overlay);
  function group(label,hint){const d=h('details','desktop-memory-group');d.append(h('summary','',label));if(hint)d.append(h('p','subtle',hint));groups.append(d);return d;}
  const core=group('第一层 · 核心与基础资料','随构建加载，聊天 API 只读。'),approved=group('第二层 · 已审核记忆','仅你或你指定的审查流程批准；可以纠正或撤回。'),working=group('第三层 · 摘要与待审核','由已保存原文压缩产生；生成摘要不等于批准记忆。'),raw=group('第四层 · 聊天原文','原文独立保留，已压缩的轮次仍可在书架查看。'),legacy=group('旧主动笔记 · 只读旧资料','原记录与历史确认标记保留，没有自动成为新版第二层，也不会自动带入聊天。');
  const conflictRows=h('div','desktop-sync-conflicts');working.append(conflictRows);
  const coreRows=h('div'),approvedRows=h('div'),workingRows=h('div'),rawState=h('p','subtle'),legacyRows=h('div');core.append(coreRows);approved.append(approvedRows);
  const prefs=h('form','desktop-memory-prefs'),summaryEnabled=h('input'),days=h('input'),reviewDays=h('input');summaryEnabled.type='checkbox';days.type=reviewDays.type='number';days.min=reviewDays.min='1';days.max=reviewDays.max='3650';days.step=reviewDays.step='1';days.required=true;
  function field(label,input){const e=h('label');e.append(h('span','',label),input);return e;}
  const prefsButton=h('button','scene-button','保存记忆设置');prefsButton.type='submit';prefs.append(field('自动压缩较早对话',summaryEnabled),field('压缩间隔（天，最短1天）',days),field('审查间隔（天，留空按需）',reviewDays),prefsButton);
  const copy=h('button','scene-button','复制待审包'),importBox=h('details','desktop-review-import');copy.type='button';importBox.append(h('summary','','接收指定审查流程的结果'));
  const decisions=h('textarea');decisions.rows=4;decisions.maxLength=500000;decisions.setAttribute('aria-label','审查结果 JSON');const apply=h('button','scene-button','应用审查结果');apply.type='button';importBox.append(decisions,apply);
  const autoEnabled=h('input');autoEnabled.type='checkbox';const autoNow=h('button','scene-button','电脑立即审查'),autoState=h('p','subtle'),reviewLog=h('details');autoNow.type='button';reviewLog.append(h('summary','','查看电脑审查记录'));const reviewRecords=h('div');reviewLog.append(reviewRecords);
  const manualReview=h('details');manualReview.append(h('summary','','手动核对与导入（可选）'),copy,importBox);
  working.append(prefs,field('电脑自动审查第三层',autoEnabled),autoNow,autoState,h('p','subtle','电脑工作台运行且已配置聊天API时，按审查间隔核对原文。通过的进入第二层，疑问继续待审；无需逐条手动审批。每批最多3条，审查会使用当前API额度。压缩和同步间隔独立；审查间隔留空则暂停定期审查。'),reviewLog,manualReview,workingRows);raw.append(rawState);legacy.append(legacyRows);
  function lock(value){busy=value;for(const b of panel.querySelectorAll('button,input,textarea'))b.disabled=value;if(!value&&snapshot)copy.disabled=!snapshot.pending.length;}
  function rows(box,entries,empty,actions){box.replaceChildren();if(!entries.length){box.append(h('p','subtle',empty));return;}
    for(const e of entries){const row=h('article','desktop-memory-card');row.append(h('strong','',e.title||e.key),h('p','desktop-memory-body',e.body));
      if(e.source_turn_ids?.length)row.append(h('p','subtle','来源：第四层原文 '+e.source_turn_ids.map(x=>x.slice(0,8)).join('、')));
      if(e.updatedAt!==undefined)row.append(h('small','subtle',e.day||'日期不明'));
      if(e.source_at)row.append(h('small','subtle','来源时间：'+new Date(e.source_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})));
      if(e.phoneSource)action(row,'查看手机原文',async()=>{try{const source=await call('chat.layers.phone_source',{key:e.key,revision:e.revision},signal.signal);row.querySelector('.phone-source')?.remove();const box=h('div','phone-source');box.append(h('p','subtle',source.complete?'手机来源原文（只读）':'原文尚未传齐，请先在手机同步'));for(const t of source.turns)box.append(h('p','desktop-memory-body','第'+(t.index+1)+'轮\n你：'+t.user+'\n\n莉宝：'+t.assistant));row.append(box);}catch(error){state.textContent=error.message;}});
      actions?.(row,e);box.append(row);}
  }
  function action(row,label,run){const b=h('button','scene-button',label);b.type='button';b.onclick=run;row.append(b);return b;}
  async function mutate(command,params){if(busy||disposed)return;lock(true);onOpen();
    try{const result=await call(command,params,signal.signal);if(disposed)return;onChange();await reload();if(!disposed)state.textContent+=' · '+(result.alreadyProcessed&&!result.applied?'该审查结果已处理，未覆盖后续纠正。':'已保存；第一层和第四层原文保持不变。');}
    catch(e){if(!disposed)state.textContent=e.message||'没有保存，请刷新后重试。';}finally{if(!disposed)lock(false);}
  }
  function correct(row,e,fromPending){let form=row.querySelector('.desktop-correction');if(form){form.querySelector('textarea').focus();return;}
    form=h('form','desktop-correction');const input=h('textarea'),save=h('button','scene-button',fromPending?'纠正并通过':'保存纠正'),cancel=h('button','scene-button','取消');input.value=e.body;input.maxLength=1000;input.rows=4;input.required=true;input.setAttribute('aria-label','纠正内容');save.type='submit';cancel.type='button';form.append(input,save,cancel);row.append(form);input.focus();
    cancel.onclick=()=>form.remove();form.onsubmit=ev=>{ev.preventDefault();if(!input.value.trim())return;if(fromPending)mutate('chat.layers.decide',{decisions:[{key:e.key,revision:e.revision,action:'correct',text:input.value}]});else mutate('chat.layers.correct',{key:e.key,revision:e.revision,text:input.value});};
  }
  async function reload(){const n=++version;
    if(bookshelfOnly){
      try{const s=await call('chat.books.status',{},signal.signal);if(disposed||n!==version)return;
        unknown.hidden=!s.undatedEntries;unknown.firstElementChild.textContent='日期不明的原文（'+s.undatedEntries+'）';
      }catch(e){if(!disposed&&n===version)state.textContent=e.message;}
      return;
    }
    try{const [v,l,s,c,a]=await Promise.all([call('chat.layers.get',{},signal.signal),call('chat.memory.list',{},signal.signal),call('chat.books.status',{},signal.signal),call('chat.layers.conflicts',{},signal.signal),call('chat.layers.auto_review.status',{},signal.signal)]);if(disposed||n!==version)return;snapshot=v;
      autoEnabled.checked=a.enabled;autoNow.disabled=a.running;autoState.textContent=a.running?'电脑正在核对第三层来源…':(a.enabled?'电脑自动审查已开启。':'电脑自动审查已暂停。')+(a.recent[0]?' 最近结果：'+({'completed':'审查完成','deferred':'保留待审','failed':'本次未完成，原记忆保留'}[a.recent[0].status]||a.recent[0].status):' 尚无审查记录。');reviewRecords.replaceChildren();for(const run of a.recent){const row=h('article','desktop-memory-card');row.append(h('p','subtle',new Date(run.at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+' · '+run.status));for(const d of run.decisions||[])row.append(h('p','desktop-memory-body',d.action+' · '+d.reason));reviewRecords.append(row);}
      conflictRows.replaceChildren();for(const conflict of c.conflicts){const row=h('article','desktop-memory-card');row.append(h('strong','','同步冲突 · '+conflict.key),h('p','subtle','暂不用于聊天；在电脑选择保留的版本，再审查是否进入第二层。'));for(const choice of conflict.choices){const box=h('div');box.append(h('p','desktop-memory-body',choice.body));action(box,'保留这份',()=>mutate('chat.layers.resolve_conflict',{id:conflict.id,revision:choice.revision,fingerprint:c.fingerprint,delete:false}));row.append(box);}action(row,'撤回此条',()=>mutate('chat.layers.resolve_conflict',{id:conflict.id,revision:null,fingerprint:c.fingerprint,delete:true}));conflictRows.append(row);}

      state.textContent=`第一层 ${v.core.entries.length} 条 · 第二层 ${v.approved.filter(a=>!a.deleted).length} 条 · 待审 ${v.pending.length} 条 · 已保存原文 ${s.storedMessages} 条`+(v.due?' · 已到你设置的审查时间':'')+(v.deferredCount?' · 另有 '+v.deferredCount+' 条旧摘要等待接收，审查后会继续接收':'');
      rows(coreRows,v.core.entries,'此公开构建没有个人基础资料；核心人设仍随请求加载。');
      rows(approvedRows,v.approved.filter(a=>!a.deleted),'还没有通过审查的记忆。',(row,e)=>{
        action(row,'纠正',()=>correct(row,e,false));const b=action(row,'撤回',()=>{b.hidden=true;const confirm=action(row,'确认撤回',()=>mutate('chat.layers.withdraw',{key:e.key,revision:e.revision}));const cancel=action(row,'保留',()=>{confirm.remove();cancel.remove();b.hidden=false;});});
      });
      rows(workingRows,v.pending,'暂无待审摘要。原文仍会保存；到达压缩条件后才生成第三层。',(row,e)=>{action(row,'通过',()=>mutate('chat.layers.decide',{decisions:[{key:e.key,revision:e.revision,action:'approve'}]}));action(row,'纠正后通过',()=>correct(row,e,true));action(row,'排除',()=>mutate('chat.layers.decide',{decisions:[{key:e.key,revision:e.revision,action:'reject'}]}));});
      summaryEnabled.checked=v.settings.summaryEnabled;days.value=v.settings.summaryDays;reviewDays.value=v.settings.reviewDays??'';
      rawState.textContent=`共 ${s.storedMessages} 条原文（手机同步 ${s.phoneStoredMessages||0} 条）；按 Asia/Shanghai 归档。${s.undatedEntries?'另有 '+s.undatedEntries+' 条日期不明的内容。':''} 第二、三层可在已配对热点下同步；手机第四层简版原文也会上传，统一在电脑审查；第一层和密钥不传。`;
      unknown.hidden=!s.undatedEntries;unknown.firstElementChild.textContent='日期不明的原文（'+s.undatedEntries+'）';
      rows(legacyRows,l.records,'没有旧主动笔记。');copy.disabled=!v.pending.length;
    }catch(e){if(!disposed&&n===version)state.textContent=e.message||'保存状态未读取，请重试。';}
  }
  function closeBooks(){if(overlay.hidden)return;overlay.hidden=true;sceneRoom?.classList.remove('is-books-focused');books?.setVisible(false);returnFocus?.focus();}
  const source={listMonths:({signal})=>call('chat.books.months',{},signal),listDays:({month,signal})=>call('chat.books.days',{month},signal),loadDay:({day,signal})=>call('chat.books.day',{day},signal)};
  async function openBooks(){if(disposed)return;onOpen();returnFocus=document.activeElement;overlay.hidden=false;sceneRoom?.classList.add('is-books-focused');
    if(!books)books=root.HebaoMemoryBooks.mount({container:bookHost,source,timeZone:'Asia/Shanghai',onClose:closeBooks});
    await books.open();if(!disposed&&!overlay.hidden)bookHost.querySelector('button')?.focus();
  }
  scope.listen(open,'click',openBooks);scope.listen(refresh,'click',reload);scope.listen(overlay,'keydown',e=>{if(e.key==='Escape'){e.preventDefault();closeBooks();return;}
    if(e.key==='Tab'){const items=[...overlay.querySelectorAll('button,input,select,textarea,[tabindex="0"],summary')].filter(e=>e.getClientRects().length&&!e.disabled),a=items[0],b=items.at(-1);if(e.shiftKey&&document.activeElement===a){e.preventDefault();b?.focus();}else if(!e.shiftKey&&document.activeElement===b){e.preventDefault();a?.focus();}}
  });
  scope.listen(overlay,'click',e=>{if(e.target===overlay)closeBooks();});
  scope.listen(unknown,'toggle',async()=>{if(!unknown.open)return;try{const r=await call('chat.books.undated',{},signal.signal);if(disposed||overlay.hidden)return;unknown.querySelector('.desktop-undated-content')?.remove();const box=h('div','desktop-undated-content');for(const e of r.entries)box.append(h('p','desktop-memory-body',e.text));unknown.append(box);}catch(e){if(!disposed)state.textContent=e.message;}});
  scope.listen(prefs,'submit',e=>{e.preventDefault();mutate('chat.layers.settings',{settings:{reviewDays:reviewDays.value===''?null:Number(reviewDays.value),summaryDays:Number(days.value),summaryEnabled:summaryEnabled.checked}});});
  scope.listen(autoEnabled,'change',()=>mutate('chat.layers.auto_review.configure',{enabled:autoEnabled.checked}));
  scope.listen(autoNow,'click',()=>mutate('chat.layers.auto_review.run',{}));
  scope.listen(copy,'click',async()=>{await reload();if(disposed||!snapshot)return;const packet={format:'hebao-memory-review-v1',entries:snapshot.pending};try{await navigator.clipboard.writeText(JSON.stringify(packet,null,2));if(!disposed)state.textContent='已复制待审摘要与原文来源，不含第一、第二层。';}catch{if(disposed)return;decisions.value=JSON.stringify(packet,null,2);importBox.open=true;state.textContent='待审包已放在文本框，可手动复制。';}});
  scope.listen(apply,'click',()=>{try{const data=JSON.parse(decisions.value);if(data.format!=='hebao-memory-decisions-v1'||!Array.isArray(data.decisions))throw Error('审查结果格式应为 hebao-memory-decisions-v1。');mutate('chat.layers.decide',{decisions:data.decisions});}catch(e){state.textContent=e.message;}});
  scope.own(()=>{disposed=true;version++;signal.abort();sceneRoom?.classList.remove('is-books-focused');books?.destroy();overlay.remove();panel.remove();});
  if(settingsOnly){heading.firstElementChild.textContent='分层记忆与保存状态';open.textContent='查看记忆书架';}
  reload();return Object.freeze({open:openBooks,close:closeBooks,refresh:reload});
}
root.HecateSceneMemory=Object.freeze({mount});
})(window);
