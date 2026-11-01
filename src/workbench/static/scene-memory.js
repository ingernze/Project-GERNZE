/* Monthly books and owner-delegated desktop AI review; no manual-add entry. */
(function(root){
'use strict';
let shelfSerial=0;
function mount(host,{scope,call,onChange=()=>{},onOpen=()=>{},onStudy=null,onResearch=null,settingsOnly=false,bookshelfOnly=false}){
  const h=(tag,cls,text)=>{const e=document.createElement(tag);e.className=cls||'';if(text!==undefined)e.textContent=text;return e;};
  const panel=h('section','desktop-memory'),heading=h('div','desktop-memory-heading');
  heading.append(h('div','', '记忆与原文'));
  const open=h('button','scene-button','打开记忆书架'),refresh=h('button','scene-button','刷新保存状态');open.type=refresh.type='button';heading.append(open,refresh);
  const state=h('p','scene-status','按需读取保存状态。');state.role='status';panel.append(heading,state);
  const groups=h('div','desktop-memory-groups');panel.append(groups);if(!bookshelfOnly)host.append(panel);
  const signal=new AbortController();let disposed=false,busy=false,version=0,snapshot=null,books=null,returnFocus=null;
  const overlay=h('div','desktop-books-overlay');overlay.hidden=true;overlay.setAttribute('role','dialog');overlay.setAttribute('aria-modal','true');overlay.setAttribute('aria-label','记忆书架');
  const shell=h('div','desktop-books-shell'),bookHost=h('div','desktop-books-host'),unknown=h('details','desktop-undated');unknown.append(h('summary','','日期不明的原文'));bookHost.dataset.memoryLayout='gold';const archiveNotice=h('div','desktop-archive-notice');archiveNotice.hidden=true;archiveNotice.setAttribute('role','status');shell.append(bookHost,archiveNotice,unknown);overlay.append(shell);
  const shelfHeading=h('div','research-heading'),shelfTitle=h('h2','','记忆书架'),shelfClose=h('button','scene-button','返回');shelfClose.type='button';const categoryToggle=h('button','scene-button research-category-toggle','分类资料 ▾');categoryToggle.type='button';categoryToggle.setAttribute('aria-expanded','false');shelfHeading.append(shelfTitle,categoryToggle,shelfClose);
  const categoryNav=h('nav','research-categories');categoryNav.setAttribute('aria-label','记忆分类');categoryNav.id='memory-categories-'+(++shelfSerial);categoryNav.hidden=true;categoryToggle.setAttribute('aria-controls',categoryNav.id);
  const categoryLabels={approved:'聊天积累的已审记忆',encounter:'莉宝的见闻与兴趣',interest:'关于你的兴趣专题',course:'大学课程资料'};
  const categoryButtons=new Map();for(const [id,label] of Object.entries(categoryLabels)){const b=h('button','scene-button',label);b.type='button';b.dataset.category=id;b.setAttribute('aria-pressed','false');categoryButtons.set(id,b);categoryNav.append(b);}
  const archiveButton=h('button','scene-button research-archive-button','按日期翻看原文');archiveButton.type='button';categoryNav.append(archiveButton);
  const researchPanel=h('section','research-panel'),researchHint=h('p','subtle'),researchState=h('p','scene-status'),researchRows=h('div','research-rows'),researchMore=h('button','scene-button','继续查看');researchState.role='status';researchMore.type='button';researchMore.hidden=true;researchPanel.append(researchHint,researchState,researchRows,researchMore);
  const shelfSyncState=h('p','scene-status research-sync-state');shelfSyncState.hidden=true;shelfSyncState.setAttribute('role','status');shell.prepend(shelfHeading,shelfSyncState,categoryNav,researchPanel);bookHost.hidden=true;unknown.hidden=true;
  let undatedVersion=0;
  let categoryVersion=0,overviewVersion=0,overviewReady=Promise.resolve(),categorySignal=null,selectedCategory='archive',nextCategoryPage=null,studyAvailable=false,researchAvailable=false;
  const shelfSize=new ResizeObserver(()=>{const width=bookHost.clientWidth;if(!disposed&&width>0)bookHost.style.setProperty('--memory-shelf-scale',String(Math.min(1,width/520)));});shelfSize.observe(bookHost);scope.own(()=>shelfSize.disconnect());
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
  const progressHost=h('div'),reviewProgress=root.GernzeTaskProgress?.mount(progressHost,{label:'电脑记忆审查'});reviewProgress?.setVisible(false);let reviewTimer=null,reviewRunning=false;
  function reviewFailure(run){
    if(run?.code==='not_complete'&&run.completion?.finish_reason==='length')return '本轮思考或回复达到输出上限，待审摘要仍保留。';
    const labels={io_timeout:'等待审查服务响应超时，待审摘要仍保留。',deadline_exceeded:'本轮审查超时，待审摘要仍保留。',connection_failed:'审查连接中断，待审摘要仍保留。',connect_failed:'未能连接审查服务，待审摘要仍保留。',http_error:'审查服务返回错误，请检查当前连接。',http_status:'审查服务返回错误，请检查当前连接。',invalid_json:'审查结果不是有效JSON，待审摘要仍保留。',review_shape:'审查结果格式不符，待审摘要仍保留。',review_fields:'审查结果字段不符，待审摘要仍保留。',review_scope:'审查结果与本次候选不符，待审摘要仍保留。',review_incomplete_or_unsupported_quote:'审查引用与完整原文不一致，已保留待审。',review_quote:'审查引用无法核对，已保留待审。',review_evidence:'审查证据格式不符，已保留待审。',review_unsupported_text:'审查文字不能逐字对应证据，已保留待审。',review_approve_changed_text:'审查结果改变了候选内容，已保留待审。',review_nonapproval_fields:'审查结果字段不符，已保留待审。',review_preparation_changed:'准备期间来源已变化，请刷新保存状态。',review_context_changed:'审查期间聊天或设置已变化，请刷新保存状态。',review_basis_changed:'审查期间来源已变化，旧结果未写入。',review_stopped_before_commit:'审查已停止，旧结果未写入。',cancelled:'审查已取消，待审摘要仍保留。',not_complete:'审查回复未完整结束，待审摘要仍保留。',review_output_too_large:'审查回复超过接收上限，待审摘要仍保留。'};
    return Object.prototype.hasOwnProperty.call(labels,run?.code)?labels[run.code]:'审查未完成，待审摘要仍保留；旧记录没有更详细的原因。';
  }
  function reviewOutcome(run){
    if(!Array.isArray(run?.decisions))return '审查流程完成';
    if(run.kind==='research')return '研究摘要：与输入相符'+run.decisions.filter(d=>d.action==='supported').length+'条，保留待核对'+run.decisions.filter(d=>d.action==='defer').length+'条，排除'+run.decisions.filter(d=>d.action==='reject').length+'条；未写入用户事实。';
    let written=0,deferred=0,excluded=0;
    for(const d of run.decisions){if(d.action==='approve'||d.action==='correct')written++;else if(d.action==='defer')deferred++;else if(d.action==='reject')excluded++;}
    return '写入'+written+'条，保留待审'+deferred+'条，排除'+excluded+'条';
  }
  function showReview(a){
    reviewRunning=a.running;autoEnabled.checked=a.enabled;autoNow.disabled=a.running;
    const p=a.progress||{state:a.running?'running':'idle',message:a.running?'正在核对原文来源':'等待审查'};
    reviewProgress?.setVisible(a.running||p.state==='complete'||p.state==='error'||p.state==='paused');
    reviewProgress?.update({state:a.running?'running':p.state,steps:p.steps||null,value:!a.running&&p.state==='complete'?1:null,label:'电脑记忆审查',detail:p.state==='error'&&a.recent[0]?.status==='failed'?reviewFailure(a.recent[0]):p.message});
    autoState.textContent=a.running?p.message:(a.enabled?'电脑自动审查已开启。':'电脑自动审查已暂停。')+(a.recent[0]?' 最近结果：'+(a.recent[0].status==='failed'?reviewFailure(a.recent[0]):(a.recent[0].status==='completed'?reviewOutcome(a.recent[0]):a.recent[0].status==='deferred'?'保留待审':a.recent[0].status)):' 尚无审查记录。');
    clearTimeout(reviewTimer);if(a.running&&!disposed)reviewTimer=setTimeout(async()=>{try{const next=await call('chat.layers.auto_review.status',{},signal.signal);if(disposed)return;showReview(next);if(!next.running)await reload();}catch(e){if(!disposed){reviewProgress?.update({state:'error',steps:p.steps||null,detail:'暂未读取到进度，点击刷新保存状态重试。'});}}},700);
  }
  const manualReview=h('details');manualReview.append(h('summary','','手动核对与导入（可选）'),copy,importBox);
  working.append(prefs,field('电脑自动审查第三层',autoEnabled),autoNow,autoState,progressHost,h('p','subtle','电脑工作台运行且已配置聊天API时，按审查间隔核对原文。通过的进入第二层，疑问继续待审；无需逐条手动审批。每批最多3条，审查会使用当前API额度。压缩和同步间隔独立；审查间隔留空则暂停定期审查。'),reviewLog,manualReview,workingRows);raw.append(rawState);legacy.append(legacyRows);
  function lock(value){busy=value;for(const b of panel.querySelectorAll('button,input,textarea'))b.disabled=value;if(!value&&snapshot){copy.disabled=!snapshot.pending.length;autoNow.disabled=reviewRunning;}}
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
      if(!overlay.hidden){loadCategoryOverview();showCategory(selectedCategory);}
      return;
    }
    try{const [v,l,s,c,a]=await Promise.all([call('chat.layers.get',{},signal.signal),call('chat.memory.list',{},signal.signal),call('chat.books.status',{},signal.signal),call('chat.layers.conflicts',{},signal.signal),call('chat.layers.auto_review.status',{},signal.signal)]);if(disposed||n!==version)return;snapshot=v;
      showReview(a);reviewRecords.replaceChildren();for(const run of a.recent){const row=h('article','desktop-memory-card');row.append(h('p','subtle',new Date(run.at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+' · '+({'completed':'审查完成','failed':'审查未完成','deferred':'保留待审'}[run.status]||run.status)));if(run.status==='completed')row.append(h('p','subtle',reviewOutcome(run)));if(run.status==='failed')row.append(h('p','subtle',reviewFailure(run)));for(const d of run.decisions||[])row.append(h('p','desktop-memory-body',(run.kind==='research'?({supported:'与输入相符',defer:'保留待核对',reject:'排除'}[d.action]||'未确认'):d.action)+' · '+d.reason));reviewRecords.append(row);}
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
  function toggleCategories(value){categoryNav.hidden=!value;categoryToggle.setAttribute('aria-expanded',String(value));}
  function closeBooks(){if(overlay.hidden)return;overlay.hidden=true;toggleCategories(false);undatedVersion++;categoryVersion++;overviewVersion++;categorySignal?.abort();researchRows.replaceChildren();unknown.querySelector('.desktop-undated-content')?.remove();sceneRoom?.classList.remove('is-books-focused');books?.setVisible(false);returnFocus?.focus();}
  const source={listMonths:({signal})=>call('chat.books.months',{},signal),listDays:({month,signal})=>call('chat.books.days',{month},signal),loadDay:({day,signal})=>call('chat.books.day',{day},signal)};
  function loadCategoryOverview(){const n=++overviewVersion;overviewReady=(async()=>{try{const value=await call('chat.research.groups',{},signal.signal);if(disposed||overlay.hidden||n!==overviewVersion)return;shelfSyncState.hidden=value.shelfSync?.state!=='waiting';shelfSyncState.textContent=shelfSyncState.hidden?'':value.shelfSync.message;for(const item of value.groups||[]){const b=categoryButtons.get(item.id);if(b)b.textContent=categoryLabels[item.id]+(item.id==='interest'?'':'（'+item.count+'）');}}catch(e){if(!disposed&&!overlay.hidden&&n===overviewVersion){shelfSyncState.hidden=false;shelfSyncState.textContent='分类资料暂未取回，保留原书架；重新打开后重试。';}}})();return overviewReady;}
  function categoryCard(item,index,n,category){
    const row=h('article','desktop-memory-card research-card'),title=h('strong','',item.title||(category==='approved'?'已审记忆 '+index:'已保存资料 '+index));
    const trust={user_confirmed:'已审核',external_untrusted:'外部资料 · 未核实',agent_inferred:'莉宝的认识 · 待核实',user_reported_unreviewed:'你的陈述 · 待审'};
    row.append(title,h('p','subtle',trust[item.trust]||'核实状态未知'));
    const review={reported_reviewed:'交付方记录：报告已审读',reported_verified:'交付方记录：局部验证通过',partial:'交付方记录：部分完成',unverified:'尚无核验记录'};
    if(item.reviewStatus)row.append(h('p','subtle',review[item.reviewStatus]||'核验范围待确认'));
    if(item.reviewScope)row.append(h('p','subtle',item.reviewScope));
    const button=action(row,category==='course'?'查看课程资料':'查看内容',async()=>{
      const old=row.querySelector('.research-body');if(old){old.remove();button.textContent=category==='course'?'查看课程资料':'查看内容';return;}
      button.disabled=true;button.textContent='正在读取…';
      try{const value=await call('chat.research.read',{category,id:item.id,revision:item.revision,purpose:category==='course'?'study_material':'browse'},categorySignal.signal);if(disposed||overlay.hidden||n!==categoryVersion||!row.isConnected)return;
        row.append(h('p','desktop-memory-body research-body',value.body));button.textContent='收起内容';
      }catch(e){if(!disposed&&!overlay.hidden&&n===categoryVersion){button.textContent=category==='course'?'查看课程资料':'查看内容';researchState.textContent=e.message||'资料没有读取成功，请刷新分类。';}}
      finally{if(!disposed&&n===categoryVersion)button.disabled=false;}
    });
    if(item.state!=='active'){button.disabled=true;button.textContent='来源变化或有冲突，暂不读取';}
    const choose=category==='course'&&studyAvailable?onStudy:['encounter','interest'].includes(category)&&researchAvailable?onResearch:null;
    if(choose){
      const use=action(row,'用于下一次提问',()=>{if(disposed||overlay.hidden||n!==categoryVersion)return;closeBooks();choose({id:item.id,revision:item.revision,title:item.title||'资料 '+index});});
      use.disabled=item.state!=='active';
    }
    return row;
  }
  async function showCategory(category,append=false){
    if(disposed||overlay.hidden)return;selectedCategory=category;shell.dataset.category=category;categoryToggle.textContent=category==='archive'?'分类资料 ▾':categoryLabels[category]+' ▾';if(!append){categorySignal?.abort();categorySignal=new AbortController();categoryVersion++;}const n=categoryVersion,readSignal=categorySignal.signal;
    for(const [id,b] of categoryButtons)b.setAttribute('aria-pressed',String(id===category));archiveButton.setAttribute('aria-pressed',String(category==='archive'));
    books?.setVisible(false);bookHost.hidden=true;archiveNotice.hidden=true;archiveNotice.replaceChildren();undatedVersion++;unknown.hidden=true;unknown.open=false;unknown.querySelector('.desktop-undated-content')?.remove();researchPanel.hidden=category==='archive';
    if(category==='archive'){
      researchRows.replaceChildren();bookHost.hidden=false;
      if(!books)books=root.HebaoMemoryBooks.mount({container:bookHost,source,timeZone:'Asia/Shanghai',onClose:closeBooks});
      await books.open();
      if(disposed||overlay.hidden||n!==categoryVersion)return;
      try{const s=await call('chat.books.status',{},readSignal);if(disposed||overlay.hidden||n!==categoryVersion)return;unknown.hidden=!s.undatedEntries;unknown.firstElementChild.textContent='日期不明的原文（'+s.undatedEntries+'）';}catch(e){if(!disposed&&!overlay.hidden&&n===categoryVersion){archiveNotice.replaceChildren(h('span','','日期信息暂未取回，月册仍可正常查看。'));action(archiveNotice,'重试日期信息',()=>showCategory('archive'));archiveNotice.hidden=false;}}
      return;
    }
    if(!append){researchRows.replaceChildren();nextCategoryPage=null;}
    researchHint.textContent=category==='course'?'点开一份资料后才读取正文；查看书架不会向 AI 发送请求。':category==='approved'?'经审查保留的聊天记忆；旧记忆保持原有归属。':'资料保留自己的来源和核实状态，不因分类自动成为已审记忆。';
    researchState.textContent='正在读取目录…';researchMore.hidden=true;researchRows.setAttribute('aria-busy','true');
    try{
      await overviewReady;if(disposed||overlay.hidden||n!==categoryVersion)return;
      if(category==='course'&&onStudy){const capability=await call('chat.study.status',{},readSignal);if(disposed||overlay.hidden||n!==categoryVersion)return;studyAvailable=capability.available===true;}
      if(['encounter','interest'].includes(category)&&onResearch){const capability=await call('chat.research.status',{},readSignal);if(disposed||overlay.hidden||n!==categoryVersion)return;researchAvailable=capability.available===true;}
      const value=await call('chat.research.list',{category,...(append&&nextCategoryPage?{after:nextCategoryPage}:{})},readSignal);if(disposed||overlay.hidden||n!==categoryVersion)return;
      if(['encounter','interest','course'].includes(category)&&root.GernzeShelfCollections){
        const items=[...value.entries],seen=new Set(items.map(e=>e.id));let after=value.next;
        for(let page=0;after&&page<166;page++){
          const next=await call('chat.research.list',{category,after},readSignal);if(disposed||overlay.hidden||n!==categoryVersion)return;
          for(const item of next.entries){if(seen.has(item.id))throw Error('目录已变化，请重新打开此分类。');seen.add(item.id);items.push(item);}
          after=next.next;
        }
        if(after||items.length>5000)throw Error('目录过大，请缩小专题范围。');
        const grouped=root.GernzeShelfCollections.render(researchRows,items.map(item=>({...item,category})),{createCard:(item,i)=>categoryCard(item,i,n,category),current:()=>!disposed&&!overlay.hidden&&n===categoryVersion});
        nextCategoryPage=null;researchMore.hidden=true;categoryButtons.get(category).textContent=categoryLabels[category]+'（'+grouped.rootCount+'个专题）';researchState.textContent='已收纳 '+items.length+' 份资料；展开专题后可搜索标题，未明确归属的继续单列。';return;
      }
      const start=researchRows.children.length;for(const [i,item] of value.entries.entries())researchRows.append(categoryCard(item,start+i+1,n,category));
      nextCategoryPage=value.next;researchMore.hidden=!nextCategoryPage;researchState.textContent=researchRows.children.length?'已显示 '+researchRows.children.length+' 条。':value.researchStatus==='unsupported'?'这批资料的版本暂不支持查看，请保留原文件。':'这里还没有资料。';
    }catch(e){if(!disposed&&!overlay.hidden&&n===categoryVersion)researchState.textContent=e.message||'目录没有读取成功，请重新打开此分类。';}
    finally{if(!disposed&&n===categoryVersion)researchRows.setAttribute('aria-busy','false');}
  }
  async function openBooks(){if(disposed)return;onOpen();returnFocus=document.activeElement;overlay.hidden=false;sceneRoom?.classList.add('is-books-focused');
    toggleCategories(false);categoryToggle.focus();loadCategoryOverview();await showCategory('archive');
  }
  scope.listen(categoryToggle,'click',()=>{toggleCategories(categoryNav.hidden);if(!categoryNav.hidden)(categoryButtons.get(selectedCategory)||archiveButton).focus();});
  function chooseCategory(id){toggleCategories(false);categoryToggle.focus();showCategory(id);}
  for(const [id,b] of categoryButtons)scope.listen(b,'click',()=>chooseCategory(id));
  scope.listen(archiveButton,'click',()=>chooseCategory('archive'));scope.listen(shelfClose,'click',closeBooks);scope.listen(researchMore,'click',()=>showCategory(selectedCategory,true));
  scope.listen(open,'click',openBooks);scope.listen(refresh,'click',reload);scope.listen(overlay,'keydown',e=>{if(e.key==='Escape'){e.preventDefault();if(!categoryNav.hidden){toggleCategories(false);categoryToggle.focus();}else closeBooks();return;}
    if(e.key==='Tab'){const items=[...overlay.querySelectorAll('button,input,select,textarea,[tabindex="0"],summary')].filter(e=>e.getClientRects().length&&!e.disabled),a=items[0],b=items.at(-1);if(e.shiftKey&&document.activeElement===a){e.preventDefault();b?.focus();}else if(!e.shiftKey&&document.activeElement===b){e.preventDefault();a?.focus();}}
  });
  scope.listen(overlay,'click',e=>{if(e.target===overlay)closeBooks();else if(!categoryNav.hidden&&!categoryNav.contains(e.target)&&!categoryToggle.contains(e.target))toggleCategories(false);});
  async function loadUndated(){
    if(disposed||overlay.hidden||!unknown.open||selectedCategory!=='archive')return;
    const n=categoryVersion,request=++undatedVersion,box=h('div','desktop-undated-content');box.setAttribute('aria-busy','true');box.append(h('p','subtle','正在读取日期不明的原文…'));unknown.querySelector('.desktop-undated-content')?.remove();unknown.append(box);
    const current=()=>!disposed&&!overlay.hidden&&unknown.open&&n===categoryVersion&&request===undatedVersion&&selectedCategory==='archive';
    try{const r=await call('chat.books.undated',{},categorySignal.signal);if(!current())return;box.replaceChildren();for(const e of r.entries)box.append(h('p','desktop-memory-body',e.text));if(!r.entries.length)box.append(h('p','subtle','没有日期不明的原文。'));}
    catch(e){if(current()){box.replaceChildren(h('p','subtle','日期不明的原文暂未取回，请重试。'));action(box,'重新读取原文',loadUndated);}}
    finally{if(current())box.setAttribute('aria-busy','false');}
  }
  scope.listen(unknown,'toggle',()=>{if(!unknown.open){undatedVersion++;unknown.querySelector('.desktop-undated-content')?.remove();return;}loadUndated();});
  scope.listen(prefs,'submit',e=>{e.preventDefault();mutate('chat.layers.settings',{settings:{reviewDays:reviewDays.value===''?null:Number(reviewDays.value),summaryDays:Number(days.value),summaryEnabled:summaryEnabled.checked}});});
  scope.listen(autoEnabled,'change',()=>mutate('chat.layers.auto_review.configure',{enabled:autoEnabled.checked}));
  scope.listen(autoNow,'click',()=>mutate('chat.layers.auto_review.run',{}));
  scope.listen(copy,'click',async()=>{await reload();if(disposed||!snapshot)return;const packet={format:'hebao-memory-review-v1',entries:snapshot.pending};try{await navigator.clipboard.writeText(JSON.stringify(packet,null,2));if(!disposed)state.textContent='已复制待审摘要与原文来源，不含第一、第二层。';}catch{if(disposed)return;decisions.value=JSON.stringify(packet,null,2);importBox.open=true;state.textContent='待审包已放在文本框，可手动复制。';}});
  scope.listen(apply,'click',()=>{try{const data=JSON.parse(decisions.value);if(data.format!=='hebao-memory-decisions-v1'||!Array.isArray(data.decisions))throw Error('审查结果格式应为 hebao-memory-decisions-v1。');mutate('chat.layers.decide',{decisions:data.decisions});}catch(e){state.textContent=e.message;}});
  scope.own(()=>{disposed=true;version++;categoryVersion++;categorySignal?.abort();clearTimeout(reviewTimer);reviewProgress?.destroy();signal.abort();sceneRoom?.classList.remove('is-books-focused');books?.destroy();overlay.remove();panel.remove();});
  if(settingsOnly){heading.firstElementChild.textContent='分层记忆与保存状态';open.textContent='查看记忆书架';}
  reload();return Object.freeze({open:openBooks,close:closeBooks,refresh:reload});
}
root.HecateSceneMemory=Object.freeze({mount});
})(window);
