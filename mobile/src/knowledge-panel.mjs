// Everything from a course, including titles and sources, is rendered as text.
export function mountKnowledgePanel({container,cache,sync,onCourseChange=()=>{}}){
 const doc=container.ownerDocument,root=doc.createElement('section'),listeners=[];
 let destroyed=false,viewGeneration=0,catalog=null,available=[],selected=new Set(),current=null,downloadBusy=false;
 root.className='knowledge-panel';root.style.cssText='background:#f6f1e6;color:#334f60;border:1px solid #bdc9c9;border-radius:14px;padding:16px;margin:0 6px 12px';
 const el=(tag,text,parent=root)=>{const n=doc.createElement(tag);if(text!==undefined)n.textContent=text;parent.append(n);return n;};
 const on=(n,type,fn)=>{n.addEventListener(type,fn);listeners.push(()=>n.removeEventListener(type,fn));};
 const button=(text,parent=root)=>{const n=el('button',text,parent);n.type='button';n.style.cssText='min-height:44px;border:1px solid #b4c1c8;border-radius:10px;background:#e7eceb;color:#334f60;padding:6px 10px';return n;};
 el('h3','课程离线资料');
 el('p','下载后电脑可关机。本地资料未核实；这里只供查看和搜索。');
 const last=el('p'),status=el('p');status.setAttribute('role','status');
 const remote=el('fieldset');el('legend','选择要下载的课程',remote);
 const filterLabel=el('label','筛选课程 ',remote),filter=el('input',undefined,filterLabel);filter.type='search';filter.setAttribute('aria-label','筛选课程');
 const choices=el('div',undefined,remote),refresh=button('刷新电脑课程目录',remote),download=button('下载所选课程到手机',remote);
 const currentLabel=el('label','当前课程 '),course=el('select',undefined,currentLabel);course.setAttribute('aria-label','当前课程');
 const directory=el('div');directory.setAttribute('aria-label','本地课程目录');
 const form=el('form'),searchLabel=el('label','本地搜索 ',form),query=el('input',undefined,searchLabel);query.type='search';query.placeholder='关键词';query.setAttribute('aria-label','本地搜索');
 const search=button('搜索当前课程',form);search.type='submit';
 const results=el('div'),body=el('article');body.setAttribute('aria-label','课程正文');
 const live=()=>!destroyed&&root.isConnected;
 const message=value=>{if(live())status.textContent=value;};
 const invalidateView=()=>{viewGeneration++;body.replaceChildren();results.replaceChildren();};
 const valid=async(token,stamp)=>live()&&token===viewGeneration&&(await cache.reader.state())?.stamp===stamp&&live()&&token===viewGeneration;
 function chooseCourse(id){current=id||null;invalidateView();onCourseChange(current);drawDirectory();}
 function drawChoices(){
  choices.replaceChildren();const term=filter.value.normalize('NFKC').toLowerCase();
  for(const c of available.filter(c=>c.name.normalize('NFKC').toLowerCase().includes(term))){
   const label=el('label',undefined,choices);label.style.display='block';const checkbox=el('input',undefined,label);checkbox.type='checkbox';checkbox.value=c.id;checkbox.checked=selected.has(c.id);checkbox.disabled=downloadBusy;
   label.append(doc.createTextNode(c.name));
   // Re-rendered controls disappear with their node; delegation avoids retained listeners.
  }
  if(!choices.childElementCount)el('p',available.length?'没有匹配课程。':'暂无可下载课程。',choices);
 }
 on(choices,'change',e=>{if(e.target.type==='checkbox'){e.target.checked?selected.add(e.target.value):selected.delete(e.target.value);}});
 function drawDirectory(){
  directory.replaceChildren();if(!current){el('p','暂无当前课程，请选择已下载课程。',directory);return;}
  const collections=(catalog?.collections??[]).filter(c=>c.course_id===current);
  if(!collections.length)el('p','本课程暂无专题目录。',directory);
  for(const c of collections){
   const details=el('details',undefined,directory);el('summary',c.title,details);
   const rows=catalog.entries.filter(e=>e.collection_id===c.id&&e.course_id===current);
   if(!rows.length)el('p','本专题暂无资料。',details);
   for(const m of rows){const b=button(m.title,details);b.dataset.entry=m.id;b.dataset.revision=m.revision;b.dataset.course=m.course_id;}
  }
 }
 async function show(id,revision,courseId,stamp){
  const token=++viewGeneration;body.replaceChildren();
  try{
   const r=await cache.reader.read(id,revision,courseId,{stamp});
   if(!await valid(token,r.stamp))return;
   el('h4',r.title,body);el('p',`来源：${r.source_ref} · ${r.origin} · 未核实`,body);
   const pre=el('pre',r.body,body);pre.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;font:inherit';
  }catch(e){if(live()&&token===viewGeneration)message(e.message);}
 }
 on(directory,'click',e=>{const b=e.target.closest('button[data-entry]');if(b)void show(b.dataset.entry,b.dataset.revision,b.dataset.course,catalog.stamp);});
 on(results,'click',e=>{const b=e.target.closest('button[data-entry]');if(b)void show(b.dataset.entry,b.dataset.revision,b.dataset.course,b.dataset.stamp);});
 async function loadLocal(){
  const token=++viewGeneration;body.replaceChildren();results.replaceChildren();const next=await cache.reader.list();
  if(!live()||token!==viewGeneration)return;
  catalog=next;course.replaceChildren();const empty=el('option','请选择课程',course);empty.value='';
  for(const c of next.courses){const option=el('option',c.name,course);option.value=c.id;}
  if(!next.courses.some(c=>c.id===current))current=null;course.value=current??'';onCourseChange(current);
  last.textContent=next.receivedAt?`最后完整同步：${next.receivedAt}。离线期间电脑的修改将在下次完整同步后生效。`:'尚未下载课程。';drawDirectory();
 }
 async function discover(){
  refresh.disabled=true;
  try{const value=await sync.discover({eligible:live});if(!live())return;
   available=value.courses;drawChoices();message('目录已刷新，请主动选择课程。');
  }catch(e){message(e.message);}finally{if(live())refresh.disabled=false;}
 }
 on(filter,'input',drawChoices);on(refresh,'click',()=>void discover());
 on(download,'click',async()=>{
  if(downloadBusy)return;downloadBusy=true;download.disabled=true;refresh.disabled=true;drawChoices();invalidateView();
  const courseIds=[...selected];
  try{await sync.sync({courseIds,eligible:live});if(!live())return;await loadLocal();message(courseIds.length?'所选课程已完整保存。':'空选课已保存，下载课程已清空。');}
  catch(e){message(e.message);}finally{if(live()){downloadBusy=false;download.disabled=false;refresh.disabled=false;drawChoices();}}
 });
 on(course,'change',()=>chooseCourse(course.value));
 on(form,'submit',async e=>{
  e.preventDefault();invalidateView();const token=viewGeneration;
  try{
   const value=await cache.reader.search({origin:'user',userText:'搜索知识库：'+query.value.trim(),courseId:current});
   if(!await valid(token,value.stamp))return;
   if(!value.results.length)el('p','本次有界搜索未找到匹配资料。',results);
   for(const r of value.results){const item=el('div',undefined,results),b=button(r.title,item);
    Object.assign(b.dataset,{entry:r.id,revision:r.revision,course:r.course_id,stamp:value.stamp});el('p',r.excerpt,item);el('small',`来源：${r.source_ref} · 未核实`,item);
   }
   message(`本次扫描 ${value.scanBytes} 字节，最多返回5段。`);
  }catch(e){if(live()&&token===viewGeneration)message(e.message);}
 });
 // Invalidate visible old content when another tab/cache instance replaces the snapshot.
 // The host can dispatch this event after any successful external apply.
 const changed=()=>{if(live())void loadLocal().catch(e=>message(e.message));};
 on(doc.defaultView,'gernze:knowledge-changed',changed);
 container.append(root);
 const ready=(async()=>{await loadLocal();if(!live())return;selected=new Set(catalog.courses.map(c=>c.id));drawChoices();})();
 return Object.freeze({ready,getCurrentCourseId:()=>current,
  destroy(){if(destroyed)return;destroyed=true;viewGeneration++;for(const remove of listeners)remove();sync.close();root.remove();current=null;onCourseChange(null);}
 });
}
