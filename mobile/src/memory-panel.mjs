// Functional settings only; the monthly bookshelf is supplied by branch 2.
export function mountMemoryPanel({container,journal,beforeChange=()=>{},afterChange=()=>{}}){
  const panel=document.createElement('section');panel.className='panel';panel.id='memorySettings';
  panel.innerHTML='<h3>记忆</h3><p class="hint">只保存你主动填写的内容，最多100条；最多6条勾选供聊天参考。纠正或忘记后，旧对话仍可查阅，但不会继续作为聊天上下文。双端记忆可在下方同步设置中手动同步，或在前台连通电脑时按周尝试。</p><form id="memoryForm"><label>标题<input name="title" maxlength="60" required></label><label>内容<textarea name="body" maxlength="500" rows="3" required></textarea></label><label>类型<select name="kind"><option value="preference">偏好</option><option value="agreement">约定</option><option value="event">事件</option><option value="other">其他</option></select></label><label>事件日期（可留空）<input name="event_date" type="date"></label><label><input name="chat_enabled" type="checkbox" checked> 用于聊天</label><label><input name="important" type="checkbox"> 重要</label><button class="primary" type="submit">保存记忆</button><button type="button" id="memoryReset">取消修改</button></form><p id="memoryStatus" class="hint" role="status"></p><div id="memoryList"></div>';
  container.append(panel);const form=panel.querySelector('form'),status=panel.querySelector('#memoryStatus'),list=panel.querySelector('#memoryList');let editing=null,busy=false,disposed=false;
  const field=name=>form.elements.namedItem(name),message=text=>status.textContent=text;
  const reset=()=>{editing=null;form.reset();form.querySelector('[type="submit"]').textContent='保存记忆';};
  async function refresh(){const view=await journal.context();if(disposed)return;list.replaceChildren();
    if(!view.records.length){const p=document.createElement('p');p.className='hint';p.textContent='还没有主动保存的记忆。';list.append(p);return;}
    for(const record of view.records.sort((a,b)=>Number(b.important)-Number(a.important)||b.updated_at.localeCompare(a.updated_at))){
      const row=document.createElement('article'),title=document.createElement('h4'),body=document.createElement('p'),hint=document.createElement('p');title.textContent=record.title;body.textContent=record.body;body.style.whiteSpace='pre-wrap';hint.className='hint';hint.textContent=(record.chat_enabled?'用于聊天':'仅保存')+(record.important?' · 重要':'')+(record.event_date?' · '+record.event_date:'');
      const edit=document.createElement('button');edit.type='button';edit.textContent='纠正';edit.onclick=()=>{if(busy)return;editing=record;for(const key of ['title','body','kind','event_date'])field(key).value=record[key];for(const key of ['chat_enabled','important'])field(key).checked=record[key];form.querySelector('[type="submit"]').textContent='保存纠正';field('title').focus();message('正在修改这条记忆。');};
      const forget=document.createElement('button');forget.type='button';forget.textContent='忘记';forget.onclick=()=>mutate(null,{id:record.id,revision:record.revision,forget:true});row.append(title,body,hint,edit,forget);list.append(row);
    }
  }
  async function mutate(note,options){if(busy||disposed)return;busy=true;panel.querySelectorAll('input,textarea,select,button').forEach(b=>b.disabled=true);beforeChange();let committed=false;
    try{await journal.changeNote(note,options);committed=true;reset();await refresh();message('已保存。下次聊天会使用更新后的记忆；旧在途回复已停止。');}
    catch(error){message(committed?'记忆已保存，但列表未刷新，请重开设置查看。':error.message||'记忆未保存。');}
    finally{busy=false;panel.querySelectorAll('input,textarea,select,button').forEach(b=>b.disabled=false);await afterChange({committed});}
  }
  form.addEventListener('submit',e=>{e.preventDefault();const note={};for(const key of ['title','body','kind','event_date'])note[key]=field(key).value;for(const key of ['chat_enabled','important'])note[key]=field(key).checked;void mutate(note,editing?{id:editing.id,revision:editing.revision}:{});});
  panel.querySelector('#memoryReset').onclick=()=>{if(!busy){reset();message('');}};
  const ready=refresh().catch(e=>{message(e.message);form.querySelectorAll('input,textarea,select,button').forEach(el=>el.disabled=true);});
  return {ready,refresh,destroy(){disposed=true;panel.remove();}};
}
