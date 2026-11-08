/* KB-02: human browsing only. No writer, model tool, or data source is installed. */
(function(global){
'use strict';
const instances=new WeakMap(),PAGE=30;
const labels={course:'课程资料',encounter:'见闻',interest:'兴趣',expression_research:'表达参考'};
const id=v=>typeof v==='string'&&v.length>0&&v.length<=200;
const text=v=>typeof v==='string';
const need=(v,message='知识库目录格式不符，请刷新后重试。')=>{if(!v)throw Error(message);};
const normalize=s=>s.normalize('NFKC').toLocaleLowerCase();
const match=(title,tokens)=>tokens.every(t=>normalize(title).includes(t));
const tokens=value=>normalize(value.trim()).split(/\s+/u).filter(Boolean);
function unique(rows,validate){
 const seen=new Map();for(const raw of rows){validate(raw);const prior=seen.get(raw.id);
  if(prior){need(JSON.stringify(prior)===JSON.stringify(raw),'同一目录ID出现冲突版本，请刷新。');continue;}
  seen.set(raw.id,raw);
 }return [...seen.values()];
}
function catalogData(raw){
 need(raw&&typeof raw==='object'&&typeof raw.available==='boolean');
 if(!raw.available)return {available:false,detail:text(raw.detail)?raw.detail:'尚未连接知识库。',courses:[],collections:[],entries:[]};
 need(raw.readOnly===true&&id(raw.library_id)&&Number.isSafeInteger(raw.revision)&&raw.revision>=0);
 need(['courses','collections','entries'].every(k=>Array.isArray(raw[k])));
 const courses=unique(raw.courses,c=>need(c&&id(c.id)&&text(c.name)));
 const collections=unique(raw.collections,c=>need(c&&id(c.id)&&id(c.revision)&&text(c.title)&&Object.hasOwn(labels,c.category)&&(c.course_id===null||c.course_id===undefined||id(c.course_id))));
 const entries=unique(raw.entries,e=>need(e&&id(e.id)&&id(e.revision)&&text(e.title)&&['knowledge_note','research_assessment'].includes(e.type)&&Object.hasOwn(labels,e.category)&&(e.collection_id===undefined||e.collection_id===null||id(e.collection_id))&&(e.course_id===undefined||e.course_id===null||id(e.course_id))));
 // Only the catalog whitelist is retained; a stray body is never rendered here.
 const fields=['id','revision','title','type','state','category','collection_id','course_id','origin','source_ref','body_hash','body_bytes','previous','related','related_revision','review_status','reply_use_granted','readable'];
 return {available:true,library_id:raw.library_id,revision:raw.revision,courses:courses.map(c=>({id:c.id,name:c.name})),collections:collections.map(c=>({id:c.id,revision:c.revision,title:c.title,category:c.category,course_id:c.course_id})),entries:entries.map(e=>Object.fromEntries(fields.filter(k=>Object.hasOwn(e,k)).map(k=>[k,e[k]])))};
}
function mount(container,{call}={}){
 need(container&&typeof container.appendChild==='function','需要知识书架容器。');need(typeof call==='function','需要只读RPC接口。');
 instances.get(container)?.destroy();
 const doc=container.ownerDocument,root=doc.createElement('section');root.className='kb-books';root.setAttribute('aria-label','项目知识库只读书架');
 const events=new AbortController();let dead=false,catalog=null,catalogEpoch=0,viewEpoch=0,catalogController=null,readController=null;
 let category='all',courseId='',query='',page=0,groups=[],opened=null,entryPage=0;
 const h=(tag,cls,value)=>{const n=doc.createElement(tag);if(cls)n.className=cls;if(value!==undefined)n.textContent=value;return n;};
 const button=(label,action)=>{const b=h('button','scene-button kb-button',label);b.type='button';b.dataset.action=action;return b;};
 const header=h('header','kb-heading'),heading=h('div','kb-heading-copy');heading.append(h('p','kb-eyebrow','莉宝 · 工作模式整理'),h('h2','','项目知识库'));
 const refreshButton=button('刷新目录','refresh');header.append(heading,refreshButton);
 const hint=h('p','kb-hint','只读浏览 · 点开才读正文 · 资料保留来源，保存不代表已经核实。');
 const toolbar=h('div','kb-toolbar'),categoryLabel=h('label','','资料分类 '),categorySelect=h('select');categorySelect.setAttribute('aria-label','资料分类');
 for(const [value,label] of [['all','全部资料'],...Object.entries(labels)]){const option=h('option','',label);option.value=value;categorySelect.append(option);}categoryLabel.append(categorySelect);
 const courseLabel=h('label','','课程 '),courseSelect=h('select');courseSelect.setAttribute('aria-label','课程选择');courseLabel.append(courseSelect);
 const searchLabel=h('label','kb-title-search','目录标题 '),search=h('input');search.type='search';search.maxLength=120;search.placeholder='搜索专题或条目标题';search.setAttribute('aria-label','搜索目录标题');searchLabel.append(search);toolbar.append(categoryLabel,courseLabel,searchLabel);
 const status=h('p','kb-status');status.setAttribute('role','status');
 const shelf=h('div','kb-shelf');shelf.setAttribute('aria-label','专题书架');
 const pager=h('nav','kb-pager');pager.setAttribute('aria-label','专题分页');const prev=button('上一批专题','prev'),pageInfo=h('span'),next=button('下一批专题','next');pager.append(prev,pageInfo,next);
 const reader=h('article','kb-reader');reader.hidden=true;reader.setAttribute('aria-label','知识库正文');reader.setAttribute('aria-live','polite');
 root.append(header,hint,toolbar,status,shelf,pager,reader);container.append(root);
 const live=()=>!dead&&root.parentNode===container;
 function invalidateRead(){viewEpoch++;readController?.abort();readController=null;reader.hidden=true;reader.replaceChildren();for(const b of shelf.querySelectorAll('[data-action=read]'))b.removeAttribute('aria-current');}
 function courseName(c){return catalog?.courses.find(v=>v.id===c)?.name||(c?'课程未登记':'课程未标明');}
 const categoryName=g=>labels[g.category]+(g.category==='course'?' · '+courseName(g.course_id):'');
 const visibleItem=e=>(category==='all'||e.category===category)&&(!courseId||(e.category==='course'&&e.course_id===courseId));
 function buildGroups(){
  groups=[];if(!catalog?.available)return;
  const collectionsById=new Map(catalog.collections.map(c=>[c.id,c])),members=new Map(catalog.collections.map(c=>[c.id,[]])),orphans=new Map();
  for(const e of catalog.entries){
   if(!visibleItem(e))continue;
   const c=collectionsById.get(e.collection_id);
   if(c&&c.category===e.category&&(c.category!=='course'||c.course_id===e.course_id)){members.get(c.id).push(e);continue;}
   if(!orphans.has(e.category))orphans.set(e.category,[]);orphans.get(e.category).push(e);
  }
  const terms=tokens(query);
  for(const c of catalog.collections){
   if(!visibleItem(c))continue;
   const items=members.get(c.id),titleMatch=match(c.title,terms),found=titleMatch?items:items.filter(e=>match(e.title,terms));
   if(terms.length&&!titleMatch&&!found.length)continue;
   groups.push({...c,key:'collection:'+c.id,items:found,total:items.length});
  }
  for(const [cat,items] of orphans){
   const title='未归专题 / 参考登记',found=match(title,terms)?items:items.filter(e=>match(e.title,terms));
   if(!found.length)continue;groups.push({key:'ungrouped:'+cat,title,category:cat,course_id:courseId||null,items:found,total:items.length});
  }
  const compare=(a,b)=>a.title.localeCompare(b.title,'zh-CN',{numeric:true})||a.key.localeCompare(b.key);
  groups.sort((a,b)=>Object.keys(labels).indexOf(a.category)-Object.keys(labels).indexOf(b.category)||compare(a,b));
 }
 function readable(e){
  if(e.state!==undefined&&e.state!=='active')return false;
  return e.readable!==false&&(e.type==='research_assessment'||e.state==='active');
 }
 function itemState(e){
  if(e.state==='withdrawn')return '已撤回 · 不读取正文';
  if(e.type==='research_assessment')return e.readable===false?'参考登记 · 暂不可读':'参考登记 · 正文可能尚未接入';
  if(e.state!=='active')return '状态非活动或未知 · 不读取正文';
  return e.readable===false?'来源变化或暂不可读 · 请刷新':'未核实 · 可读性由读取时核对';
 }
 function fillBook(details,g){
  details.querySelector('.kb-book-content')?.remove();if(!details.open)return;
  const content=h('div','kb-book-content'),summary=h('p','kb-entry-count');
  const count=g.items.length;entryPage=Math.max(0,Math.min(entryPage,Math.max(0,Math.ceil(count/PAGE)-1)));
  summary.textContent=count?'本次匹配 '+count+' 份 · 第 '+(entryPage+1)+' / '+Math.ceil(count/PAGE)+' 批':'本专题暂无条目。';
  content.append(summary);const list=h('div','kb-entries');
  for(const e of g.items.slice(entryPage*PAGE,(entryPage+1)*PAGE)){
   const row=h('div','kb-entry'),b=button(e.title||'无标题条目','read');b.dataset.id=e.id;b.dataset.revision=e.revision;b.disabled=!readable(e);
   row.append(b,h('p','kb-entry-meta',itemState(e)));
   if(e.category==='course')row.append(h('small','kb-entry-meta',courseName(e.course_id)));list.append(row);
  }
  content.append(list);
  if(count>PAGE){const nav=h('nav','kb-pager');nav.setAttribute('aria-label','条目分页');const back=button('上一批条目','entry-prev'),forward=button('下一批条目','entry-next');back.disabled=entryPage===0;forward.disabled=(entryPage+1)*PAGE>=count;nav.append(back,forward);content.append(nav);}
  details.append(content);
 }
 function drawShelf(){
  shelf.replaceChildren();
  const pages=Math.ceil(groups.length/PAGE);page=Math.max(0,Math.min(page,Math.max(0,pages-1)));
  if(catalog?.available&&!groups.length)shelf.append(h('p','kb-empty',query?'没有匹配的标题。':catalog.entries.length||catalog.collections.length?'当前分类或课程暂无资料。':'知识库还没有资料。'));
  for(const g of groups.slice(page*PAGE,(page+1)*PAGE)){
   // Local adaptation of memory-books.js topicFolder: same card, cover and palette.
   const details=h('details','desktop-memory-card research-card panel kb-book');details.dataset.bookKey=g.key;
   const summary=h('summary','kb-book-summary'),cover=h('span','kb-cover'),img=h('img');img.src='assets/cover-10.png';img.alt='';img.width=44;img.height=62;img.draggable=false;cover.setAttribute('aria-hidden','true');cover.append(img);
   const copy=h('span','kb-book-copy');copy.append(h('strong','kb-book-title',g.title),h('span','kb-book-meta',categoryName(g)),h('span','kb-book-meta',g.items.length+'份 · 展开目录'));
   summary.append(cover,copy);details.append(summary);shelf.append(details);
   if(opened===g.key){details.open=true;fillBook(details,g);}
  }
  pager.hidden=groups.length<=PAGE;prev.disabled=page===0;next.disabled=page+1>=pages;pageInfo.textContent=pages?'第 '+(page+1)+' / '+pages+' 批':'';
  if(catalog?.available)status.textContent='目录版本 '+catalog.revision+' · '+groups.length+' 本专题（含未归专题入口） · 仅搜索标题，不读正文。';
 }
 function redraw(){invalidateRead();opened=null;entryPage=0;page=0;buildGroups();drawShelf();}
 function sourceRows(metadata){
  const rows=[['ID',metadata.id],['修订',metadata.revision],['来源',metadata.source_ref||'未提供来源说明'],['整理来源',metadata.origin||'既有参考登记'],['核实状态','未核实（不作为已审记忆）']];
  if(metadata.body_hash)rows.push(['正文哈希',metadata.body_hash]);
  if(metadata.related)rows.push(['关联来源',metadata.related],['关联修订',metadata.related_revision||'未提供']);
  const dl=h('dl','kb-provenance');for(const [label,value] of rows)dl.append(h('dt','',label),h('dd','',String(value)));return dl;
 }
 async function openEntry(ident,revision){
  const e=catalog?.entries.find(e=>e.id===ident&&e.revision===revision);if(!e||!readable(e))return;
  invalidateRead();const token=viewEpoch,epoch=catalogEpoch,controller=new AbortController();readController=controller;
  const current=()=>live()&&token===viewEpoch&&epoch===catalogEpoch&&!controller.signal.aborted;
  reader.hidden=false;reader.append(button('关闭正文','close-read'),h('h3','',e.title),h('p','kb-status','正在核对并读取所选修订…'));reader.setAttribute('aria-busy','true');
  for(const b of shelf.querySelectorAll('[data-action=read]'))if(b.dataset.id===ident)b.setAttribute('aria-current','true');
  try{
   const value=await call('chat.knowledge.read',{ident,revision},controller.signal);if(!current())return;
   const m=value?.metadata;need(m&&m.id===ident&&m.revision===revision&&m.type===e.type&&m.category===e.category,'返回资料与所选修订不一致，请刷新目录。');
   if(e.type==='knowledge_note')need(value.readOnly===true&&typeof value.body==='string'&&m.state==='active'&&m.readable!==false&&m.course_id===e.course_id,'资料已变化或不可读，请刷新目录。');
   else need(value.body===null,'参考登记返回格式不符，请刷新目录。');
   reader.replaceChildren(button('关闭正文','close-read'),h('h3','',m.title||e.title),sourceRows(m));
   if(value.body===null)reader.append(h('p','kb-notice',text(value.detail)?value.detail:'本项仅为参考登记，正文尚未接入。'));
   else reader.append(h('pre','kb-body',value.body));
  }catch(error){if(current())reader.replaceChildren(button('关闭正文','close-read'),h('h3','',e.title),h('p','kb-notice','所选资料或修订已变化，或暂未能读取。请刷新目录后重新选择；没有自动改读其他版本。'));}
  finally{if(current())reader.setAttribute('aria-busy','false');}
 }
 async function refresh(){
  if(dead)return;catalogController?.abort();catalogController=new AbortController();const controller=catalogController,epoch=++catalogEpoch;
  invalidateRead();catalog=null;groups=[];opened=null;page=entryPage=0;shelf.replaceChildren();pager.hidden=true;status.textContent='正在读取知识库目录…';root.setAttribute('aria-busy','true');
  const current=()=>live()&&epoch===catalogEpoch&&!controller.signal.aborted;
  try{
   const value=await call('chat.knowledge.catalog',{},controller.signal);if(!current())return;
   catalog=catalogData(value);courseSelect.replaceChildren();const all=h('option','','全部课程');all.value='';courseSelect.append(all);
   for(const c of catalog.courses){const option=h('option','',c.name);option.value=c.id;courseSelect.append(option);}
   if(!catalog.courses.some(c=>c.id===courseId))courseId='';courseSelect.value=courseId;
   buildGroups();drawShelf();if(!catalog.available)status.textContent=catalog.detail;
  }catch(error){if(current()){catalog=null;status.textContent='知识库目录暂未读取，请点击“刷新目录”重试。';}}
  finally{if(current())root.setAttribute('aria-busy','false');}
 }
 root.addEventListener('input',event=>{if(event.target===search){query=search.value;redraw();}},{signal:events.signal});
 root.addEventListener('change',event=>{
  if(event.target===categorySelect){category=categorySelect.value;courseId='';courseSelect.value='';redraw();}
  if(event.target===courseSelect){courseId=courseSelect.value;if(courseId){category='course';categorySelect.value='course';}redraw();}
 },{signal:events.signal});
 root.addEventListener('error',event=>{if(event.target.matches?.('.kb-cover img'))event.target.hidden=true;},{capture:true,signal:events.signal});
 root.addEventListener('toggle',event=>{
  const details=event.target;if(!live()||!shelf.contains(details)||!details.matches('.kb-book'))return;
  const g=groups.find(g=>g.key===details.dataset.bookKey);if(!g)return;
  if(details.open){
   if(opened!==g.key){invalidateRead();opened=g.key;entryPage=0;}
   for(const other of shelf.querySelectorAll('details[open]'))if(other!==details)other.open=false;
   fillBook(details,g);
  }else{details.querySelector('.kb-book-content')?.remove();if(opened===g.key){invalidateRead();opened=null;entryPage=0;}}
 },{capture:true,signal:events.signal});
 root.addEventListener('click',event=>{
  const b=event.target.closest('button[data-action]');if(!b||!root.contains(b)||b.disabled||dead)return;
  const action=b.dataset.action;
  if(action==='refresh'){void refresh();return;}
  if(action==='read'){void openEntry(b.dataset.id,b.dataset.revision);return;}
  if(action==='close-read'){invalidateRead();return;}
  if(action==='prev'||action==='next'){invalidateRead();opened=null;page+=action==='next'?1:-1;drawShelf();return;}
  if(action==='entry-prev'||action==='entry-next'){
   const details=b.closest('.kb-book'),g=groups.find(g=>g.key===details.dataset.bookKey);if(!g)return;
   invalidateRead();entryPage+=action==='entry-next'?1:-1;fillBook(details,g);
  }
 },{signal:events.signal});
 function destroy(){if(dead)return;dead=true;catalogEpoch++;invalidateRead();catalogController?.abort();events.abort();root.remove();if(instances.get(container)===api)instances.delete(container);catalog=null;groups=[];}
 const api=Object.freeze({ready:refresh(),refresh,destroy});instances.set(container,api);return api;
}
global.GernzeKnowledgeBooks=Object.freeze({mount});
})(window);
