/* Built-in pages register through the same v1 module contract. */
(function (root) {
"use strict";
const h = (tag, cls, text) => {
  const el = document.createElement(tag); if (cls) el.className = cls;
  if (text !== undefined) el.textContent = text; return el;
};
const paths = {
  home:['M3 10 12 3l9 7','M5 9v12h5v-7h4v7h5V9'],
  book:['M3 4h6c2 0 3 1 3 3v14c0-2-1-3-3-3H3z','M21 4h-6c-2 0-3 1-3 3v14c0-2 1-3 3-3h6z'],
  chart:['M4 3v17h17','M8 15v-4','M13 15V7','M18 15V4'],
  note:['M5 3h14v18H5z','M8 7h8','M8 11h8','M8 15h5'],
  clock:['M12 7v5l3 2'], box:['M3 7l9-4 9 4-9 4z','M3 7v10l9 4 9-4V7','M12 11v10'],
  grid:['M3 3h7v7H3z','M14 3h7v7h-7z','M3 14h7v7H3z','M14 14h7v7h-7z'],
  hierarchy:['M9 2h6v5H9z','M2 17h5v5H2z','M9.5 17h5v5h-5z','M17 17h5v5h-5z','M12 7v5','M4.5 17v-5h15v5','M12 12v5'],
  list:['M8 5h13','M8 12h13','M8 19h13','M3 5h.01','M3 12h.01','M3 19h.01'],
  sun:['M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8','M12 2v2','M12 20v2','M2 12h2','M20 12h2','m5 5 1.5 1.5','m17.5 17.5 1.5 1.5','m5 19 1.5-1.5','m17.5 6.5 1.5-1.5'],
  moon:['M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11Z'],
  settings:['M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8','M12 2v3','M12 19v3','M2 12h3','M19 12h3','m5 5 2 2','m17 17 2 2','m5 19 2-2','m17 7 2-2'],
  rail:['M3 4h18v16H3z','M9 4v16'], plus:['M12 5v14','M5 12h14'],
  arrow:['M12 18V5','m6 11 6-6 6 6'], down:['m6 9 6 6 6-6'], cross:['m6 6 12 12','m6 18 12-12'],
  audio:['M7 7v10','M12 3v18','M17 7v10'], copy:['M8 8h12v13H8z','M16 8V3H3v13h5'],
};
function icon(name, size=18) {
  const el = document.createElementNS('http://www.w3.org/2000/svg','svg');
  for (const [key,value] of Object.entries({viewBox:'0 0 24 24',width:size,height:size,fill:'none',stroke:'currentColor','stroke-width':1.5,'stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'})) el.setAttribute(key,String(value));
  for (const d of paths[name] || paths.grid) { const p=document.createElementNS(el.namespaceURI,'path'); p.setAttribute('d',d); el.append(p); }
  if (name === 'clock') { const p=document.createElementNS(el.namespaceURI,'circle'); p.setAttribute('cx','12');p.setAttribute('cy','12');p.setAttribute('r','9');el.prepend(p); }
  return el;
}
function button(ctx, label, action, cls='button', settled) {
  const el = h('button',cls,label); el.type='button';
  ctx.scope.listen(el,'click', async () => {
    el.disabled=true;
    try { await action(); } catch(error) { if (!ctx.signal.aborted) ctx.notify(error.message); }
    finally { if (!ctx.signal.aborted) { if(settled)settled();else el.disabled=false; } }
  });
  return el;
}
function input(ctx,label,value='',type='text',onInput) {
  const wrap=h('label','field',label); const el=h(type==='textarea'?'textarea':'input',type==='textarea'?'text-area':'text-input');
  if(type!=='textarea') el.type=type; el.value=value; wrap.append(el);
  if(onInput) ctx.scope.listen(el,'input',()=>onInput(el.value));
  return {wrap,el};
}
function page(rootEl,title,subtitle) {
  const scroll=h('div','content-page'); const content=h('div','page-width');
  content.append(h('h1','',title),h('p','subtle',subtitle)); scroll.append(content); rootEl.append(scroll); return content;
}
function row(title,meta,body) {
  const el=h('div','record-row'); el.append(h('div','record-title',title),h('div','record-meta',meta));
  if(body) el.append(h('p','subtle plain-text',body)); return el;
}
const date = value => value ? new Date(value).toLocaleString('zh-CN',{hour12:false}) : '尚无提交';
const outcomes={correct:'答对',incorrect:'需要再看一遍',partial:'部分答对',unverified:'尚未核验'};
async function download(ctx,name,body,type='application/json') {
  const url=URL.createObjectURL(new Blob([body],{type}));
  const release=ctx.scope.own(()=>URL.revokeObjectURL(url));
  const a=h('a'); a.href=url; a.download=name; document.body.append(a); a.click(); a.remove();
  // Revoke after this user-triggered download, also reclaimed on module disposal.
  const timer=setTimeout(release,1000); ctx.scope.own(()=>clearTimeout(timer));
}
async function home(rootEl,ctx) {
  if(missingModule(rootEl,ctx,'cet6','中国英语六级学习'))return;
  const p=h('div','home-stage');const stack=h('div','home-content');p.append(stack);rootEl.append(p);
  const mark=h('img','hero-mark');mark.src='mark.svg';mark.alt='赫宝的怀表';
  stack.append(mark,h('div','home-heading','今天，从哪里开始？'),h('p','hero-caption','把卡住的一步，慢慢弄明白。'));
  const body=h('div','home-body'); const workspace=h('div','space-row');
  const place=button(ctx,'我的学习空间',()=>ctx.navigate('study'),'space-button');place.prepend(icon('book',15));workspace.append(place);body.append(workspace);
  const card=h('div','import-surface'); const text=h('textarea','home-text');
  text.setAttribute('aria-label','阅读材料'); text.placeholder='粘贴阅读材料，或导入附带答案与解析的题目 JSON。\n赫宝会帮你记下进度，再准备好给网页 GPT 的提示词。';
  text.value=ctx.drafts.home || '';ctx.scope.listen(text,'input',()=>{ctx.drafts.home=text.value;});card.append(text);
  const controls=h('div','import-controls');const tools=h('div','import-tools');
  const file=h('input');file.type='file';file.accept='.json,.txt';file.hidden=true; card.append(file);
  const add=button(ctx,'',()=>file.click(),'import-file');add.title='导入文件';add.setAttribute('aria-label','导入文件');add.append(icon('plus',17));tools.append(add,h('span','mode-chip','六级 · 阅读'));controls.append(tools);
  const trailing=h('div','import-actions');trailing.append(h('span','small-label','本地学习'));
  const importText=async value => {
    if(!value.trim()) throw new Error('先放进一份阅读材料吧。');
    const payload=value.trim().startsWith('{') ? JSON.parse(value) : {title:'新导入的阅读材料',source:'用户粘贴；未附参考答案',passage:value,questions:[{id:'1',stem:'把你对这份材料的理解写下来。',options:{},hints:[],rationale:''}]};
    const result=await ctx.call('lesson.import',{payload}); if(ctx.signal.aborted)return;
    ctx.drafts.home=''; await ctx.refresh();if(!ctx.signal.aborted)ctx.navigate('study',{lessonId:result.lesson_id});
  };
  const submit=button(ctx,'',()=>importText(text.value),'import-submit');submit.title='开始学习';submit.setAttribute('aria-label','开始学习');submit.append(icon('arrow',18));trailing.append(submit);controls.append(trailing);card.append(controls);const optional=h('details','study-aux');optional.append(h('summary','','自带材料（可选）'),card);body.append(optional);stack.append(body);
  ctx.scope.listen(file,'change',async()=> {
    const selected=file.files[0];if(!selected)return;
    try { if(selected.size>500000)throw new Error('文件须在 500KB 内。');const value=await selected.text();if(!ctx.signal.aborted)await importText(value); }
    catch(error){if(!ctx.signal.aborted)ctx.notify(error.message);}file.value='';
  });
  const links=h('div','home-links');
  for(const [label,name,id] of [['继续学习','book','study'],['查看进度','chart','progress'],['项目记录','note','memory']]) {
    const el=button(ctx,label,()=>ctx.navigate(id),'home-link');el.prepend(icon(name,14));links.append(el);
  }
  const example=button(ctx,ctx.preview?'看看示例':'导入示例',async()=> {
    if(ctx.preview) {ctx.navigate('study',{previewLesson:root.HebaoExample});return;}
    const result=await ctx.call('lesson.import',{payload:root.HebaoExample});await ctx.refresh();if(!ctx.signal.aborted)ctx.navigate('study',{lessonId:result.lesson_id});
  },'home-link');example.prepend(icon('plus',14));links.append(example);stack.append(links);
  const state=ctx.state();const summary=state.progress;const stats=h('div','home-stats');
  for(const [value,label] of [[summary.submission_count,'次学习提交'],[summary.learning_days,'个学习日'],[state.due_reviews.length,'份待复习']]) {
    const stat=h('span','',label);stat.prepend(h('strong','',String(value)));stats.append(stat);
  }
  stack.append(stats);
  rootEl.append(h('div','home-bottom',ctx.preview?'界面预览 · 不写入学习数据':'学习的节奏由你决定。成绩不会影响赫宝和你的关系。'));
}
async function study(rootEl,ctx) {
  if(missingModule(rootEl,ctx,'cet6','中国英语六级学习'))return;
  const content=page(rootEl,'六级学习','纸上做题，把复盘或疑问交给网页讲解，再把汇报带回来。');
  content.classList.add('daily-study-page');
  const draft=ctx.drafts.dailyStudy ||= {prompt:'',report:'',receipt:null,savedText:'',lessonId:null};
  const requested=ctx.payload?.lessonId || null;
  const data=await ctx.call('daily.workspace',{});if(ctx.signal.aborted)return;
  const pending=data.pending_prompt;
  if(pending && (!requested || pending.lesson_id===requested)) {
    draft.prompt=pending.prompt;draft.lessonId=pending.lesson_id;
  } else if(requested && requested!==draft.lessonId) {
    draft.prompt='';draft.lessonId=requested;
  }
  const intro=h('div','study-intro');
  intro.append(h('span','study-chip','CET-6'),h('p','subtle',data.next_step));
  content.append(intro);
  const grid=h('div','study-entry-grid');content.append(grid);
  const out=h('section','surface study-entry'),incoming=h('section','surface study-entry');
  out.setAttribute('aria-labelledby','study-output-title');incoming.setAttribute('aria-labelledby','study-input-title');
  grid.append(out,incoming);
  const outTitle=h('h2','','01 · 输出提示词');outTitle.id='study-output-title';
  out.append(outTitle,h('p','subtle','复制老师提示词到网页。提交试卷情况，或直接问题目、句子、词汇；无需另选模式。'));
  const output=input(ctx,'学习提示词',draft.prompt,'textarea');
  output.el.readOnly=true;output.el.id='study-prompt';output.el.rows=10;
  output.el.placeholder='点击复制按钮，提示词会准备在这里。';
  const copyStatus=h('p','study-status');copyStatus.setAttribute('role','status');copyStatus.id='study-copy-status';
  output.el.setAttribute('aria-describedby',copyStatus.id);
  let copying=false;
  const copyButton=button(ctx,'复制学习提示词',async()=>{
    if(copying)return;copying=true;copyStatus.setAttribute('role','status');copyButton.textContent='准备中…';copyButton.setAttribute('aria-busy','true');
    try {
      const result=await ctx.call('daily.prompt',requested?{lesson_id:requested}:{});
      if(ctx.signal.aborted)return;
      const old=draft.prompt;draft.prompt=result.prompt;draft.lessonId=result.lesson_id;output.el.value=result.prompt;
      if(draft.receipt && draft.report===draft.savedText && old!==result.prompt) {
        draft.report='';report.el.value='';draft.receipt=null;receiptArea.replaceChildren();saveButton.textContent='保存学习汇报';
      }
      try {
        await navigator.clipboard.writeText(result.prompt);
        if(!ctx.signal.aborted)copyStatus.textContent='已复制。去网页提交纸上练习情况或具体疑问吧。';
      } catch(error) {
        if(!ctx.signal.aborted) {
          output.el.focus();output.el.select();
          copyStatus.textContent='剪贴板暂不可用，全文已选中。按 Ctrl+C（Mac 用 Cmd+C）复制。';
        }
      }
    } catch(error) {
      if(!ctx.signal.aborted){copyStatus.textContent=error.message;copyStatus.setAttribute('role','alert');}
    } finally {
      copying=false;
      if(!ctx.signal.aborted){copyButton.textContent='复制学习提示词';copyButton.removeAttribute('aria-busy');updateSave();}
    }
  },'button primary study-main-action');
  out.append(output.wrap,copyButton,copyStatus,h('p','study-footnote','尊重纸上做题和笔记习惯。实际复盘或答疑后保存汇报，才记一次提交。'));
  const inTitle=h('h2','','02 · 输入学习汇报');inTitle.id='study-input-title';
  incoming.append(inTitle,h('p','subtle','这里粘贴网页复盘或答疑结束时的完整汇报，再点一次保存。编号自动识别。'));
  const report=input(ctx,'网页学习汇报',draft.report,'textarea',value=>{
    draft.report=value;draft.receipt=null;receiptArea.replaceChildren();saveStatus.textContent='';saveStatus.setAttribute('role','status');
    saveButton.textContent='保存学习汇报';updateSave();
  });
  report.el.id='study-report';report.el.rows=10;
  report.el.placeholder='可包含简短说明和一个 JSON 汇报代码块。';
  const saveStatus=h('p','study-status');saveStatus.id='study-save-status';saveStatus.setAttribute('role','status');
  report.el.setAttribute('aria-describedby',saveStatus.id);
  const receiptArea=h('div','study-receipt');
  let saving=false;
  const showReceipt=receipt=>{
    receiptArea.replaceChildren();
    receiptArea.append(h('h3','','这次已留好'),h('p','plain-text',receipt.summary));
    const scene=receipt.scenario==='exam_review'?'试卷复盘':receipt.scenario==='question_help'?'具体问题答疑':'旧版学习活动';
    receiptArea.append(h('p','study-footnote','本次记录：'+scene+'；保存不表示整卷完成或已掌握。'));
    const detail=h('details','study-aux');detail.append(h('summary','','查看自述、参考与下次建议'));
    if(receipt.user_report){
      const u=receipt.user_report;
      detail.append(h('p','plain-text','用户自述：'+u.details),h('p','study-footnote',u.accuracy===null?'整体正确率未知（用户未提供）。':'用户自述正确率：'+u.accuracy+'% · 口径：'+u.accuracy_basis));
    }
    for(const f of receipt.reference_findings || [])detail.append(h('p','study-footnote','参考支持的结论（网页依据用户资料，未独立核验）：'+f.conclusion+' · 来源：'+f.source+' · 依据：'+f.evidence));
    if(receipt.review_focus)detail.append(h('p','study-footnote','下次可关注：'+receipt.review_focus));
    if(detail.children.length>1)receiptArea.append(detail);
    const e=receipt.local_evaluation;
    if(e)receiptArea.append(h('p','study-footnote','本地按导入参考答案核对：本次提交'+e.submitted_count+'题，已比较'+e.graded_count+'题，其中一致'+e.correct_count+'题。'));
    receiptArea.append(h('p','study-footnote','网页分析和薄弱点仍是建议；没有自动设置提醒或计入实际学时。'));
    for(const warning of receipt.warnings || []) {
      if(warning.includes('旧提示词') || warning.includes('旧版'))receiptArea.append(h('p','study-footnote',warning));
    }
  };
  const saveButton=button(ctx,'保存学习汇报',async()=>{
    if(saving)return;saving=true;updateSave();report.el.readOnly=true;saveStatus.textContent='正在保存…';
    saveStatus.setAttribute('role','status');saveButton.textContent='保存中…';saveButton.setAttribute('aria-busy','true');
    const captured=report.el.value;
    try {
      if(new TextEncoder().encode(captured).length>100000)throw new Error('汇报超过100KB。请让网页按原模板精简后，重新复制完整汇报。');
      const result=await ctx.call('daily.save',{text:captured});
      if(ctx.signal.aborted)return;
      draft.receipt=result;draft.savedText=captured;showReceipt(result);
      saveStatus.textContent=result.already_saved?'这份汇报已经保存过，没有重复计数。':'已保存，记为一次学习提交。';
      saveButton.textContent='已保存';
      try {
        await ctx.refresh();
        if(!ctx.signal.aborted)paintHistory(await ctx.call('daily.workspace',{}));
      } catch(error) {
        if(!ctx.signal.aborted)saveStatus.textContent+=' 最新列表暂未刷新，切页重试即可。';
      }
    } catch(error) {
      if(!ctx.signal.aborted) {
        saveStatus.textContent=error.message;saveStatus.setAttribute('role','alert');saveButton.textContent='保存学习汇报';report.el.focus();
      }
    } finally {
      saving=false;
      if(!ctx.signal.aborted){report.el.readOnly=false;saveButton.removeAttribute('aria-busy');updateSave();}
    }
  },'button primary study-main-action',updateSave);
  function updateSave(){saveButton.disabled=saving || !report.el.value.trim();}
  incoming.append(report.wrap,saveButton,saveStatus,receiptArea);
  if(draft.receipt)showReceipt(draft.receipt);
  updateSave();
  const history=h('details','study-aux');history.append(h('summary','','学习背景与最近记录'));
  const historyBody=h('div','study-history');history.append(historyBody);content.append(history);
  function paintHistory(value) {
    if(ctx.signal.aborted)return;
    historyBody.replaceChildren(h('p','subtle','已保存 '+value.progress.submission_count+' 次 · '+value.progress.learning_days+' 个有保存的日期'));
    if(!value.history.length)historyBody.append(h('p','subtle','还没有学习记录。复制提示词就可以开始。'));
    for(const item of value.history) {
      const card=h('article','study-history-card');
      card.append(h('h3','',date(item.saved_at)+' · 保存'),h('p','plain-text',item.summary));
      if(item.user_report){const u=item.user_report;card.append(h('p','study-footnote','用户自述：'+u.details.slice(0,700)),h('p','study-footnote',u.accuracy===null?'整体正确率未知（用户未提供）。':'用户自述正确率：'+u.accuracy+'% · '+u.accuracy_basis));}
      if(item.review_focus)card.append(h('p','study-footnote','下次可关注：'+item.review_focus));
      for(const p of item.weak_points)card.append(h('p','study-footnote','建议复查：'+p.point+' · 依据：'+p.evidence));
      historyBody.append(card);
    }
  }
  paintHistory(data);
  history.append(button(ctx,'查看全部历史',()=>ctx.navigate('progress'),'button quiet'));
  const materials=ctx.state().lessons.filter(item=>!['hebao_cet6_daily_v1','hebao_cet6_paper_v1'].includes(item.id));
  if(materials.length) {
    const optional=h('details','study-aux');optional.append(h('summary','','已有材料（可选）'));
    const selection=h('select','select');selection.setAttribute('aria-label','已有学习材料');
    for(const item of materials){const option=h('option','',item.title);option.value=item.id;selection.append(option);}
    if(requested)selection.value=requested;
    optional.append(selection,button(ctx,'使用这份材料',()=>ctx.navigate('study',{lessonId:selection.value}),'button quiet'));
    content.append(optional);
  }
}
async function progress(rootEl,ctx) {
  if(missingModule(rootEl,ctx,'cet6','中国英语六级学习'))return;
  const content=page(rootEl,'学习进度','开始使用、最近提交和累计次数，按本地保存的记录展示。');
  const state=await ctx.refresh();if(ctx.signal.aborted)return;
  const summary=state.progress;const stats=h('div','stat-strip');
  for(const [value,label] of [[summary.submission_count,'累计提交'],[summary.learning_days,'学习日'],[summary.usage_span_days,'使用跨度 / 天']]) {
    const item=h('div');item.append(h('span','stat-value',String(value)),h('span','stat-label',label));stats.append(item);
  }content.append(stats,h('div','record-meta','开始使用：'+date(summary.first_used_at)+'　最近提交：'+date(summary.last_submission_at)));
  const due=h('section','surface');due.append(h('h2','','这次可以复习'));
  if(!state.due_reviews.length)due.append(h('p','subtle','目前没有已设置且到期的复习材料。日常学习保存不会自动安排日期或提醒。'));
  for(const lesson of state.due_reviews)due.append(button(ctx,lesson.title,()=>ctx.navigate('study',{lessonId:lesson.id}),'button quiet'));content.append(due);
  const history=await ctx.call('study.history',{});if(ctx.signal.aborted)return;
  content.append(h('h2','','最近提交'));
  if(!history.length)content.append(h('div','empty-message','还没有学习提交。每一次确认保存，都会在这里留下日期。'));
  for(const item of history)content.append(row(outcomes[item.outcome],date(item.recorded_at)+' · '+(item.minutes>0?item.minutes+' 分钟（旧记录）':'学时未记录'),item.tags.join(' · ') || item.note));
}
async function memory(rootEl,ctx) {
  const content=page(rootEl,'项目记录','记录想法、决定与进度。项目日志不会自动变成人物记忆。');
  const form=h('section','surface');const title=input(ctx,'标题',ctx.drafts.logTitle || '','text',v=>ctx.drafts.logTitle=v);
  const body=input(ctx,'正文',ctx.drafts.logBody || '','textarea',v=>ctx.drafts.logBody=v);
  const status=h('select','select-input');status.setAttribute('aria-label','决定状态');
  for(const [value,label] of [['candidate','候选想法'],['adopted','已采用'],['deferred','待定'],['rejected','不采用']]){const opt=h('option','',label);opt.value=value;status.append(opt);}
  form.append(title.wrap,body.wrap,status,button(ctx,'确认保存项目记录',async()=> {
    await ctx.call('memory.save',{title:title.el.value,body:body.el.value,decision:status.value});if(ctx.signal.aborted)return;
    ctx.drafts.logTitle='';ctx.drafts.logBody='';await ctx.refresh();if(!ctx.signal.aborted)ctx.navigate('memory');
  },'button primary'));content.append(form);
  const records=await ctx.call('memory.list',{});if(ctx.signal.aborted)return;
  if(!records.length)content.append(h('div','empty-message','还没有项目记录。'));
  for(const item of records)content.append(row(item.title,date(item.created_at)+' · '+item.decision,item.body));
}
async function reminders(rootEl,ctx) {
  const content=page(rootEl,'提醒','先查看已经保存的提醒。通知开关与安静模式继续由桌宠管理。');
  const records=await ctx.call('reminder.list',{});if(ctx.signal.aborted)return;
  content.append(h('div','notice','本轮工作台可查看提醒；创建和触发通知仍在现有桌宠工具窗口中操作。'));
  if(!records.length)content.append(h('div','empty-message','当前没有已保存的提醒。'));
  for(const item of records)content.append(row(item.title,date(item.due_epoch*1000)+' · '+item.status));
}
async function backup(rootEl,ctx) {
  const content=page(rootEl,'备份与资料','把当前学习和项目记录导出到自己选择的位置。');
  const card=h('section','surface');card.append(h('h2','','导出本地记录'),h('p','subtle','导出题目、学习提交、项目记录、提醒和交接信息。文件由浏览器下载保存。'));
  const action=button(ctx,'导出 JSON 备份',async()=> {
    const value=await ctx.call('backup.export',{});if(ctx.signal.aborted)return;
    await download(ctx,'赫宝_本地记录_'+new Date().toISOString().slice(0,10)+'.json',value.json);
  },'button primary');if(ctx.preview)action.disabled=true;card.append(action);content.append(card);
  content.append(h('p','subtle','桌宠原有的 SQLite 备份入口继续可用。工作台不会读取任意系统目录。'));
}
function missingModule(rootEl,ctx,key,title) {
  if(ctx.state?.().optional_modules?.[key]!==false)return false;
  const content=page(rootEl,title,'此模块尚未安装；已经保存的个人记录会保留。');
  content.append(button(ctx,'安装与移除模块',()=>ctx.call('modules.open',{}),'button primary'));
  return true;
}
async function extensions(rootEl,ctx) {
  const content=page(rootEl,'模块中心','按需安装功能。移除模块保留个人数据。');
  content.classList.add('module-center-page');
  const installed=ctx.state?.().optional_modules || {};
  const header=h('div','module-center-header'),intro=h('div','module-center-intro');
  intro.append(...content.children);
  const toggle=h('button','button quiet module-view-toggle');toggle.type='button';
  toggle.setAttribute('aria-controls','module-center-view');
  const tools=h('div','module-center-tools');
  tools.append(button(ctx,'刷新状态',async()=>{await ctx.refresh();if(!ctx.signal.aborted)await ctx.navigate('extensions');},'button quiet'),toggle);
  header.append(intro,tools);
  const viewport=h('div','module-center-view');viewport.id='module-center-view';
  const announced=h('span','sr-only');announced.setAttribute('role','status');
  content.replaceChildren(header,viewport,announced);
  let hierarchy=ctx.drafts.moduleCenterView==='hierarchy',viewScope=null;
  ctx.scope.own(()=>viewScope?.dispose());
  const catalogue=()=>{
    const current=ctx.registry.list().filter(x=>!['home','extensions','settings'].includes(x.id));
    const reserved=[
      {id:'vocabulary',title:'词汇与翻译',description:'阅读流程稳定后再扩展。',icon:'book',pending:true,navigationGroup:'learning'},
      {id:'custom',title:'更多模块',description:'统一注册入口，主区域与右侧详情均可扩展。',icon:'plus',pending:true},
    ];
    return [...current,...reserved.filter(item=>!ctx.registry.modules.has(item.id))];
  };
  const moduleKeys=item=>item.id==='voice'?['fixed_voice','voice_engine']:(item.navigationGroup==='learning'&&!item.pending?['cet6']:[]);
  const installState=key=>installed[key]===true?'已安装':installed[key]===false?'未安装':'待确认';
  const stateFor=item=>{
    if(item.pending)return '待接入';
    const keys=moduleKeys(item);if(!keys.length)return '已提供';
    const present=keys.filter(key=>installed[key]===true).length;
    if(present===keys.length)return '已安装';
    if(present)return '部分安装';
    return keys.every(key=>installed[key]===false)?'未安装':'待确认';
  };
  const descriptionFor=item=>item.id==='voice'?'固定台词、文字朗读与声音专用 API。':item.id==='study'?'中国英语六级 · 纸质复盘与答疑':item.description || '已接入工作台';
  const addInstallInfo=(target,item,viewCtx,{components=true,manage=true}={})=>{
    if(components&&item.id==='voice'){
      const components=h('div','module-components');
      for(const [key,title] of [['fixed_voice','固定场景语音'],['voice_engine','本地文字转语音']])components.append(h('p','module-component',title+' · '+installState(key)));
      target.append(components);
    }
    if(manage&&(item.id==='study'||item.id==='voice')){
      const manage=button(viewCtx,'安装与移除',()=>ctx.call('modules.open',{}),'button quiet module-manage');
      manage.setAttribute('aria-label',item.title+'：安装与移除模块');target.append(manage);
    }
  };
  const render=()=>{
    if(ctx.signal.aborted)return;
    viewScope?.dispose();viewScope=new root.HebaoRuntime.Scope();
    const viewCtx={...ctx,scope:viewScope};
    viewport.replaceChildren();
    toggle.replaceChildren(icon(hierarchy?'list':'hierarchy',16),h('span','',hierarchy?'列表视图':'层级视图'));
    toggle.setAttribute('aria-pressed',String(hierarchy));
    toggle.setAttribute('aria-label',hierarchy?'切换到列表视图':'切换到金字塔层级视图');
    const items=catalogue();
    if(!hierarchy){
      const list=h('div','module-list');list.setAttribute('aria-label','模块列表');
      for(const item of items){
        const el=h('div','extension-row');el.dataset.extensionId=item.id;const mark=h('div','extension-icon');mark.append(icon(item.icon));const info=h('div','extension-info');
        info.append(h('div','record-title',item.title),h('div','record-meta',descriptionFor(item)));
        addInstallInfo(info,item,viewCtx,{manage:false});
        el.append(mark,info,h('span','extension-state'+(item.pending?' pending':''),stateFor(item)));
        const actions=h('div','module-row-actions');
        addInstallInfo(actions,item,viewCtx,{components:false});
        if(!item.pending)actions.append(button(viewCtx,'打开',()=>ctx.navigate(item.id),'button quiet'));el.append(actions);list.append(el);
      }
      viewport.append(list);return;
    }
    const legend=h('div','module-map-legend');
    for(const [type,text] of [['solid','已有归属'],['dashed','待接入'],['peer','同排同级，无横向调用连线']]){
      const key=h('span','module-map-key');key.append(h('i','map-key-mark '+type),h('span','',text));legend.append(key);
    }
    viewport.append(legend);
    const scroll=h('div','module-map-scroll');scroll.tabIndex=0;scroll.setAttribute('role','region');
    scroll.setAttribute('aria-label','模块层级图。窄窗口可横向滚动，连线表示归属。');
    const map=h('div','module-map');
    const apex=h('div','module-map-apex');const top=h('div','module-map-root');
    const mark=h('img','brand-mark');mark.src='mark.svg';mark.alt='';
    top.append(mark,h('div','module-map-root-title','赫宝工作台'),h('span','module-map-root-caption','模块的共同入口'));apex.append(top);map.append(apex);
    const learning=items.filter(item=>item.navigationGroup==='learning');
    const peers=items.filter(item=>item.navigationGroup!=='learning'&&!(item.id==='custom'&&item.pending));
    const branches=learning.length?[{id:'learning',title:'学习',icon:'book',children:learning},...peers]:peers;
    map.style.setProperty('--map-min-width',String((learning.length?248:122)+Math.max(0,branches.length-1)*138+20)+'px');
    const tree=h('ul','module-map-branches');tree.setAttribute('aria-label','同级模块');
    tree.style.setProperty('--peer-count',String(Math.max(1,branches.length)));
    tree.style.setProperty('--peer-tail-count',String(Math.max(0,branches.length-1)));
    if(!learning.length)tree.classList.add('without-learning');
    if(branches.length===1)tree.classList.add('single-branch');
    const cardFor=item=>{
      const card=h('article','module-map-card'+(item.pending?' is-pending':''));card.dataset.extensionId=item.id;
      const head=h('div','module-map-card-title');head.append(icon(item.icon,17),h('h3','',item.title));card.append(head);
      if(item.children){card.append(h('p','module-map-card-caption','阅读和进度在同一个栏目里'));}
      else{
        card.append(h('span','extension-state'+(item.pending?' pending':''),stateFor(item)));
        addInstallInfo(card,item,viewCtx);
        if(!item.pending){const open=button(viewCtx,'打开',()=>ctx.navigate(item.id),'button quiet map-open');open.setAttribute('aria-label','打开'+item.title);card.append(open);}
      }
      return card;
    };
    for(const item of branches){
      const branch=h('li','module-map-branch'+(item.pending?' is-pending':''));branch.append(cardFor(item));
      if(item.children){
        const children=h('ul','module-map-children');children.setAttribute('aria-label','学习的子入口');
        children.style.setProperty('--child-count',String(item.children.length));
        for(const child of item.children){const node=h('li','module-map-child'+(child.pending?' is-pending':''));node.append(cardFor(child));children.append(node);}
        branch.append(children);
      }
      tree.append(branch);
    }
    map.append(tree);scroll.append(map);viewport.append(scroll);
    const future=h('div','module-map-expansion');future.append(icon('plus',16),h('span','','扩展位 · 更多模块可以加入这一层，也可以在已有栏目下增加子入口。'));viewport.append(future);
    viewport.append(h('p','module-map-note','连线只表示入口归属。同级入口之间没有调用连线；这张图不表示底层代码的依赖关系。'));
  };
  ctx.scope.listen(toggle,'click',()=>{
    hierarchy=!hierarchy;ctx.drafts.moduleCenterView=hierarchy?'hierarchy':'list';render();
    announced.textContent=hierarchy?'已切换到金字塔层级视图':'已切换到列表视图';
  });
  ctx.scope.own(ctx.registry.subscribe(render));render();
}
async function voice(rootEl,ctx) {
  const content=page(rootEl,'声音','固定台词和文字说话，沿用你已经选定的两套声音。');
  const status=h('p','study-status');status.setAttribute('role','status');content.append(status);
  let available=false;
  if(ctx.preview)status.textContent='这是界面预览。请从桌面赫宝打开工作台，使用声音模块。';
  else {
    try { available=Boolean((await ctx.call('voice.available',{})).available); }
    catch(error) { if(ctx.signal.aborted)return;status.textContent=error.message; }
    if(ctx.signal.aborted)return;
    if(!status.textContent)status.textContent=available?'已连接桌面声音模块。打开窗口后再选择播放，不会自动出声。':'请从桌面赫宝打开工作台，使用声音模块。';
  }
  const grid=h('div','study-entry-grid');content.append(grid);
  for(const [title,description,command,text] of [
    ['01 · 固定场景语音','查看已收录台词、触发场景和当前音量，选中后试听。','voice.fixed','打开固定语音'],
    ['02 · 文字与 API 说话','输入文字直接朗读；也可以让声音专用 API 回复。GPT、SoVITS 和参考音频分别选择。','voice.text','打开文字说话'],
  ]) {
    const card=h('section','surface');card.append(h('h2','',title),h('p','subtle',description));
    const absent=ctx.state?.().optional_modules?.[command==='voice.fixed'?'fixed_voice':'voice_engine']===false;
    const open=button(ctx,absent?'安装声音模块':text,async()=>{
      await ctx.call(absent?'modules.open':command,{});if(!ctx.signal.aborted)status.textContent='已请求打开桌面声音窗口；播放由你操作。';
    },'button primary');open.disabled=!available;card.append(open);grid.append(card);
  }
  const api=h('section','surface');api.append(h('h2','','声音专用 API'),h('p','subtle','这份接口设置只用于声音对话，固定录音和直接朗读不需要聊天 API。'));
  const settings=button(ctx,'打开声音 API 设置',async()=>{
    await ctx.call('voice.api',{});if(!ctx.signal.aborted)status.textContent='已请求打开声音专用 API 设置。';
  },'button quiet');settings.disabled=!available;api.append(settings);content.append(api);
}
async function activityTiming(content,ctx) {
  const section=h('section','surface activity-timing');
  section.append(h('h2','','眨眼、摆腿与睡眠'),h('p','subtle','平时按已保存的设置运行，需要调整时再展开。'));
  const disclosure=h('details','timing-disclosure');
  const toggle=h('summary','button quiet timing-toggle','调整眨眼、摆腿与睡眠');toggle.append(icon('down',15));
  const panel=h('div','timing-panel');disclosure.append(toggle,panel);section.append(disclosure);
  const status=h('p','timing-status','正在读取桌宠设置……');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  panel.append(status);content.append(section);
  if(ctx.preview){status.textContent='请从桌面赫宝打开工作台，调整眨眼、摆腿与睡眠。';return;}
  let snapshot;
  try{snapshot=await ctx.call('behavior.get',{});}
  catch(error){if(!ctx.signal.aborted){status.textContent=error.message;status.setAttribute('role','alert');}return;}
  if(ctx.signal.aborted)return;
  if(!snapshot.available){status.textContent='请从桌面赫宝打开工作台，调整眨眼、摆腿与睡眠。';return;}
  const values={...snapshot.settings,...(ctx.drafts.activityTiming || {})};const controls={};
  const form=h('form','timing-form');ctx.scope.listen(form,'submit',event=>event.preventDefault());
  let rangeIssue=false;
  const remember=()=>{ctx.drafts.activityTiming=read();validateRanges(true);};
  function read(){return Object.fromEntries(Object.entries(controls).map(([key,item])=>[key,item.toggle?item.value:item.el.type==='number'?Number(item.el.value):item.el.value]));}
  function validateRanges(show=false){
    let message='';
    for(const [minimum,maximum,label] of [['blink_min_s','blink_max_s','眨眼间隔'],['sleep_min_s','sleep_max_s','睡眠时长'],['foot_sway_min_cycles','foot_sway_max_cycles','摆腿轮数']]){
      const low=controls[minimum].el,high=controls[maximum].el;
      const invalid=Number.isFinite(low.valueAsNumber)&&Number.isFinite(high.valueAsNumber)&&low.valueAsNumber>high.valueAsNumber;
      const hint=invalid?`${label}：${minimum==='foot_sway_min_cycles'?'最少不能大于最多':'最短不能大于最长'}，请调整后再保存。`:'';
      low.setCustomValidity(hint);
      for(const el of [low,high]){if(invalid)el.setAttribute('aria-invalid','true');else el.removeAttribute('aria-invalid');}
      if(hint&&!message)message=hint;
    }
    if(show&&message){status.setAttribute('role','alert');status.textContent=message;rangeIssue=true;}
    else if(!message&&rangeIssue){status.setAttribute('role','status');status.textContent='有尚未保存的调整。';rangeIssue=false;}
    return !message;
  }
  function field(parent,key,label,type,min,max){
    const item=input(ctx,label,values[key],type);item.el.required=true;item.el.name=key;
    if(type==='number'){item.el.min=String(min);item.el.max=String(max);item.el.step='1';}
    controls[key]=item;ctx.scope.listen(item.el,'input',remember);parent.append(item.wrap);return item.el;
  }
  function switchRow(parent,key,label){
    const row=h('div','theme-setting-row');row.append(h('h3','',label));
    const el=h('button','theme-switch');el.type='button';el.setAttribute('role','switch');el.setAttribute('aria-label',label);
    const thumb=h('span','theme-switch-thumb');el.append(thumb);thumb.append(icon(key==='blink_enabled'?'sun':'moon',15));
    const state=h('span','timing-switch-state');const item={toggle:true,value:values[key],el,state};controls[key]=item;
    const paint=()=>{el.setAttribute('aria-checked',String(item.value));state.textContent=item.value?'已开启':'已关闭';};item.paint=paint;paint();
    ctx.scope.listen(el,'click',()=>{item.value=!item.value;paint();remember();});
    const trailing=h('div','timing-switch-control');trailing.append(state,el);row.append(trailing);parent.append(row);
  }
  const blink=h('fieldset','timing-group');blink.append(h('legend','','眨眼'));switchRow(blink,'blink_enabled','待机时眨眼');
  const blinkRange=h('div','timing-grid');field(blinkRange,'blink_min_s','最短间隔 · 秒','number',1,120);field(blinkRange,'blink_max_s','最长间隔 · 秒','number',1,120);blink.append(blinkRange);
  blink.append(h('p','timing-help','用于插画风格静息待机；为保持呼吸动作衔接，按循环边界触发，实际间隔可能略有浮动。像素风格保持原有眨眼节奏。'));
  const sway=h('fieldset','timing-group');sway.append(h('legend','','摆腿'));switchRow(sway,'foot_sway_enabled','待机时随机摆腿');
  field(sway,'foot_sway_mean_min','平均触发间隔 · 分钟','number',1,1440);
  const cycles=h('div','timing-grid');field(cycles,'foot_sway_min_cycles','最少轮数','number',1,3);field(cycles,'foot_sway_max_cycles','最多轮数','number',1,3);sway.append(cycles);
  sway.append(h('p','timing-help','仅用于插画风格原地静息待机。每次随机摆腿1～3轮，开始与结束各一次；不会打断抓取、走路、看书或睡眠。平均间隔是随机频率，不会到点必做。关闭只影响后续触发。'));
  const sleep=h('fieldset','timing-group');sleep.append(h('legend','','睡眠'));switchRow(sleep,'sleep_enabled','自动睡眠');
  const windowRow=h('div','timing-grid');field(windowRow,'sleep_window_start','更容易睡觉 · 从','time');field(windowRow,'sleep_window_end','到 · 支持跨午夜','time');sleep.append(windowRow);
  const rate=h('div','timing-grid');field(rate,'sleep_night_mean_min','高发时段 · 平均间隔（分钟）','number',1,1440);field(rate,'sleep_day_mean_min','其他时段 · 平均间隔（分钟）','number',1,1440);sleep.append(rate);
  const duration=h('div','timing-grid');field(duration,'sleep_min_s','睡眠最短时长 · 秒','number',1,3600);field(duration,'sleep_max_s','睡眠最长时长 · 秒','number',1,3600);sleep.append(duration);
  sleep.append(h('p','timing-help','“平均间隔”表示随机频率，不会到点必睡。只在静息待机时触发，不打断抓取、走路、看书或其他动作。睡眠时长从坐下后开始计算，到时自然醒来；关闭自动睡眠只影响后续触发。'));
  const buttons=h('div','timing-actions');
  const save=button(ctx,'保存动作设置',async()=>{
    if(!validateRanges(true)){form.reportValidity();return;}
    if(!form.reportValidity())return;
    try{
      const result=await ctx.call('behavior.set',{settings:read()});
      delete ctx.drafts.activityTiming;
      if(!ctx.signal.aborted){status.setAttribute('role','status');status.textContent=result.persisted?'已保存，重启后保留。正在睡眠的本次时长保持不变，下次使用新设置。':'设置未保存，请重试。';}
    }catch(error){if(!ctx.signal.aborted){status.setAttribute('role','alert');status.textContent=error.message;}throw error;}
  });
  const restore=button(ctx,'恢复默认值',()=>{
    for(const [key,item] of Object.entries(controls)){
      if(item.toggle){item.value=snapshot.defaults[key];item.paint();}else item.el.value=snapshot.defaults[key];
    }
    remember();status.setAttribute('role','status');status.textContent='已填入默认值，点击“保存动作设置”后生效。';
  },'button quiet');
  buttons.append(save,restore);form.append(blink,sway,sleep,buttons);panel.append(form);
  status.textContent=ctx.drafts.activityTiming?'有尚未保存的调整。':'当前设置已载入。修改后点击保存。';
  if(!snapshot.sleep_available)status.textContent+=' 当前画风缺少睡眠资源，暂不会自动睡觉。';
  validateRanges(true);
}

async function settings(rootEl,ctx) {
  const content=page(rootEl,'工作台设置','保持简单，安静运行。');
  const appearance=h('section','surface');appearance.append(h('h2','','外观主题'));
  const row=h('div','theme-setting-row'),info=h('div','theme-setting-info');
  const status=h('p','theme-setting-status');status.id='workbench-theme-status';status.setAttribute('role','status');
  info.append(h('h3','','浅色模式'),status);
  const toggle=h('button','theme-switch');toggle.type='button';toggle.setAttribute('role','switch');toggle.setAttribute('aria-label','浅色模式');toggle.setAttribute('aria-describedby',status.id);
  const thumb=h('span','theme-switch-thumb');toggle.append(thumb);row.append(info,toggle);appearance.append(row);
  appearance.append(h('p','subtle','深色是暖炭黑与银白；浅色是白底、浅灰侧栏和深灰文字。'));
  content.append(appearance);
  const paintTheme=(hint='')=>{
    const light=root.HebaoTheme.current()==='light';toggle.setAttribute('aria-checked',String(light));
    thumb.replaceChildren(icon(light?'sun':'moon',15));status.textContent='当前：'+(light?'浅色':'深色')+hint;
  };
  paintTheme();
  ctx.scope.listen(toggle,'click',async()=>{
    toggle.disabled=true;const theme=root.HebaoTheme.current()==='dark'?'light':'dark';root.HebaoTheme.apply(theme);paintTheme();
    try{
      if(ctx.preview){const remembered=root.HebaoTheme.rememberPreview(theme);paintTheme(remembered?' · 已在此浏览器记住':' · 此浏览器仅保留本次选择');}
      else{await ctx.call('appearance.set',{theme});if(!ctx.signal.aborted)paintTheme(' · 已记住');}
    }catch(error){if(!ctx.signal.aborted){paintTheme(' · 本次已切换，设置未保存');ctx.notify(error.message);}}
    finally{if(!ctx.signal.aborted)toggle.disabled=false;}
  });
  await activityTiming(content,ctx);
  if(ctx.signal.aborted)return;
  const about=h('section','surface');about.append(h('h2','','模块入口'),h('p','subtle','学习、进度与记录共用一个工作台。右侧显示当前需要的提示；新模块可以沿用统一入口。'));
  content.append(about);
}
function register(registry) {
  const entries=[
    ['home','首页','home',home,['lesson.import','modules.open'],0],
    ['study','六级学习','book',study,['daily.workspace','daily.prompt','daily.save','modules.open'],10,'learning'],
    ['progress','学习进度','chart',progress,['study.history','modules.open'],20,'learning'],
    ['memory','项目记录','note',memory,['memory.list','memory.save'],30],
    ['reminders','提醒','clock',reminders,['reminder.list'],40],
    ['backup','备份与资料','box',backup,['backup.export'],50],
    ['voice','声音','audio',voice,['voice.available','voice.fixed','voice.text','voice.api','modules.open'],60],
    ['extensions','模块中心','grid',extensions,['modules.open'],90],
    ['settings','设置','settings',settings,['appearance.set','behavior.get','behavior.set'],100],
  ];
  return entries.map(([id,title,name,mount,commands,order,navigationGroup])=>registry.register({apiVersion:1,id,title,icon:name,mount,commands,order,navigationGroup,description:id==='voice'?'固定场景语音、文字朗读与声音专用 API；已连接桌面模块。':undefined}));
}
root.HebaoUI={h,icon,button};root.HebaoModules={register};
})(window);
