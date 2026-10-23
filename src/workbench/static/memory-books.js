/* Standalone, read-only monthly memory books. No data source is installed by default. */
(function(global){
  'use strict';
  const instances=new WeakMap();
  const pad=n=>String(n).padStart(2,'0');
  function monthParts(value){if(typeof value!=='string'||!/^\d{4}-\d{2}$/.test(value))throw Error('月份格式无效');const [y,m]=value.split('-').map(Number);if(y<1||m<1||m>12)throw Error('月份格式无效');return [y,m];}
  function daysInMonth(value){const [y,m]=monthParts(value);return [31,(y%4===0&&(y%100!==0||y%400===0))?29:28,31,30,31,30,31,31,30,31,30,31][m-1];}
  function dayParts(value){if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))throw Error('日期格式无效');const month=value.slice(0,7),[y,m]=monthParts(month),d=Number(value.slice(8));if(d<1||d>daysInMonth(month))throw Error('日期格式无效');return [y,m,d];}
  function adjacent(day,direction){const [year,month,date]=dayParts(day);let y=year,m=month,d=date+direction;if(d<1){if(--m<1){m=12;y--;}if(y<1)return null;d=daysInMonth(`${String(y).padStart(4,'0')}-${pad(m)}`);}else if(d>daysInMonth(day.slice(0,7))){d=1;if(++m>12){m=1;y++;}if(y>9999)return null;}return `${String(y).padStart(4,'0')}-${pad(m)}-${pad(d)}`;}
  function weekday(day){let [y,m,d]=dayParts(day);const offsets=[0,3,2,5,0,3,5,1,4,6,2,4];if(m<3)y--;return ['星期日','星期一','星期二','星期三','星期四','星期五','星期六'][(y+Math.floor(y/4)-Math.floor(y/100)+Math.floor(y/400)+offsets[m-1]+d)%7];}
  const monthLabel=m=>{const [y,n]=monthParts(m);return `${y}年${n}月`;};
  const monthName=m=>['一','二','三','四','五','六','七','八','九','十','十一','十二'][monthParts(m)[1]-1]+'月';
  const isCount=n=>Number.isSafeInteger(n)&&n>=0;
  function monthsData(value){if(!Array.isArray(value))throw Error('月份列表无效');const seen=new Set();return value.map(item=>{monthParts(item?.month);if(seen.has(item.month)||!isCount(item.dayCount)||item.dayCount>daysInMonth(item.month)||!isCount(item.entryCount))throw Error('月份列表无效');seen.add(item.month);return {month:item.month,dayCount:item.dayCount,entryCount:item.entryCount};}).sort((a,b)=>b.month.localeCompare(a.month));}
  function daysData(value,month){if(!Array.isArray(value))throw Error('日期列表无效');const seen=new Set();return value.map(item=>{dayParts(item?.day);if(item.day.slice(0,7)!==month||seen.has(item.day)||!isCount(item.entryCount)||typeof item.hasSummary!=='boolean'||typeof item.hasOriginal!=='boolean')throw Error('日期列表无效');seen.add(item.day);return {...item};}).sort((a,b)=>a.day.localeCompare(b.day));}
  function entriesData(value,day){if(!value||value.day!==day||!Array.isArray(value.entries))throw Error('日页数据无效');const seen=new Set(),result=[];for(const item of value.entries){if(!item||!['active','deleted','superseded'].includes(item.status))throw Error('记录状态无效');if(item.status!=='active')continue;if(typeof item.id!=='string'||!item.id||seen.has(item.id)||!['summary','memory','conversation'].includes(item.kind)||typeof item.text!=='string'||!Array.isArray(item.sourceRefs)||item.sourceRefs.some(r=>!r||typeof r.id!=='string'||typeof r.label!=='string'))throw Error('记录格式无效');seen.add(item.id);if(!item.text.trim())continue;result.push({...item,sourceRefs:item.sourceRefs.map(r=>({id:r.id,label:r.label}))});}return result;}
  function mount({container,source,timeZone='Asia/Shanghai',onClose=()=>{}}={}){
    if(!container||typeof container.appendChild!=='function')throw Error('需要书架容器');
    const mobileLayout=container.dataset.memoryLayout==='mobile';
    const goldLayout=container.dataset.memoryLayout==='gold',initiallyExpanded=mobileLayout||goldLayout;
    if(typeof timeZone!=='string')throw Error('时区无效');
    // Calendar IDs come from source. The timeZone is a label, never a date-conversion instruction.
    try{new Intl.DateTimeFormat('zh-CN',{timeZone});}catch{throw Error('时区无效');}
    const calendarParts=new Intl.DateTimeFormat('en',{timeZone,year:'numeric',month:'2-digit'}).formatToParts(new Date());
    const currentMonth=calendarParts.find(p=>p.type==='year').value+'-'+calendarParts.find(p=>p.type==='month').value;
    if(source&&['listMonths','listDays','loadDay'].some(k=>typeof source[k]!=='function'))throw Error('记忆来源接口不完整');
    instances.get(container)?.destroy();
    const dataSource=source||{listMonths:async()=>[],listDays:async()=>[],loadDay:async({day})=>({day,entries:[]})};
    const doc=container.ownerDocument||document,root=doc.createElement('section');root.className='mb-books';root.hidden=true;root.setAttribute('aria-label','记忆书架');root.setAttribute('role','region');container.appendChild(root);
    const events=new AbortController();let controller=null,generation=0,dead=false,visible=false,view='shelf',months=[],days=[],entries=[],selected=null,currentDay=null,loading=false,error='',direction=0,previousFocus=null;
    let expanded=initiallyExpanded,pose=0,spread=initiallyExpanded?1:0,bankFrame=null,bankEpoch=0,bankTarget=null,drag=null,suppressClickUntil=0,flight=null,dragFrame=null;
    const shownWidths=new Map(),readingPositions=new Map(),lastDayByMonth=new Map();
    let paintedDay=null,shelfScrollTop=0,bankVelocity=0,bankTimestamp=-Infinity;
    const clock=()=>global.performance?.now()??Date.now();
    const reduced=()=>global.matchMedia?.('(prefers-reduced-motion: reduce)').matches===true;
    const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
    function rememberPosition(){
      const body=root.querySelector('.mb-day-scroll');
      if(body&&paintedDay&&body.getAttribute('aria-busy')==='false')readingPositions.set(paintedDay,body.scrollTop||0);
      const shelf=root.querySelector('.mb-shelf-scroll');if(shelf&&root.querySelector('.mb-stage'))shelfScrollTop=shelf.scrollTop||0;
    }
    function putText(node,text){if(node.textContent!==text)node.textContent=text;}
    function element(tag,className,text){const e=doc.createElement(tag);if(className)e.className=className;if(text!==undefined)e.textContent=text;return e;}
    function button(text,action,className='mb-button',label=text){const b=element('button',className,text);b.type='button';b.dataset.action=action;b.setAttribute('aria-label',label);return b;}
    function invalidate(){generation++;controller?.abort();controller=null;}
    function begin(){invalidate();controller=new AbortController();loading=true;error='';entries=[];render();return {token:generation,signal:controller.signal};}
    const current=r=>!dead&&visible&&generation===r.token&&!r.signal.aborted;
    function findMonth(value){return months.find(m=>m.month===value);}
    const thicknessFor=pages=>pages>15?32:pages>5?22:14;
    const bookTone=month=>monthParts(month)[1]%2===0?'#5a718b':'#647b77';
    function updateMonthCounts(){const m=findMonth(selected);if(m){m.dayCount=days.length;m.entryCount=days.reduce((n,d)=>n+d.entryCount,0);}}
    function nextTarget(sign){
      const index=days.findIndex(d=>d.day===currentDay),local=days[index+sign];
      if(index>=0&&local)return {day:local.day};
      const neighbor=months[months.findIndex(m=>m.month===selected)-sign];
      return neighbor?{month:neighbor.month,edge:sign<0?'last':'first'}:null;
    }
    function turnPage(sign){const target=nextTarget(sign);if(!target)return;clearFlight();direction=sign;if(target.day)navigate(target.day,sign);else openMonth(target.month,null,target.edge);}

    function header(){
      const h=element('header','mb-header'),left=element('div','mb-heading');
      if(view==='reader')left.append(button('‹','shelf','mb-icon','返回书架'),element('div','mb-heading-copy',monthLabel(selected)));
      else{const sigil=element('span','mb-sigil','☾');sigil.setAttribute('aria-hidden','true');const copy=element('div','mb-heading-copy');copy.append(element('span','mb-eyebrow','莉宝 · 保存的日子'),element('h1','mb-title','记忆书架'));left.append(sigil,copy);}
      h.append(left);if(!mobileLayout)h.append(button('×','close','mb-icon','关闭记忆书架'));return h;
    }
    function status(message,kind='loading'){const box=element('div','mb-status mb-status-'+kind);if(kind==='loading'){const mark=element('span','mb-status-mark','☾');mark.setAttribute('aria-hidden','true');box.append(mark);}box.append(element('p','',message));if(kind==='error')box.append(button('重新载入','refresh','mb-secondary'));return box;}
    function coverFace(month){
      const cover=element('span','mb-cover');cover.dataset.jacket=pad(monthParts(month)[1]);
      const artwork=({10:'assets/cover-10.png',11:'assets/cover-11.png',12:'assets/cover-12.png'})[monthParts(month)[1]];
      if(artwork){
        const picture=element('img','mb-cover-art');picture.setAttribute('alt','');picture.setAttribute('aria-hidden','true');picture.setAttribute('draggable','false');
        picture.setAttribute('src',global.HebaoMemoryBookArtwork?.[pad(monthParts(month)[1])]||artwork);
        cover.append(picture);
      }
      cover.append(element('span','mb-cover-top',pad(monthParts(month)[1])),element('span','mb-cover-year',String(monthParts(month)[0])),element('span','mb-cover-name',monthName(month)),element('span','mb-cover-moon','☾'),element('span','mb-cover-rule'),element('span','mb-cover-bottom','莉宝'));
      return cover;
    }
    function renderShelf(){
      const content=element('div','mb-shelf-scroll');
      const intro=element('div','mb-intro');intro.append(element('p','mb-kicker','每月一本 · 每天一页'));if(!mobileLayout)intro.append(element('h2','','日子，都收在这里。'),element('p','mb-intro-note','展开书架，选一本想翻看的月册。'));content.append(intro);
      const stage=element('div','mb-stage');stage.setAttribute('aria-label','立体月册书架，展开后可左右滑动选月');content.append(stage);
      if(loading||error||!months.length){
        stage.classList.add('mb-stage-placeholder');stage.setAttribute('aria-label','记忆书架');
        stage.append(element('div','mb-rail'),status(loading?'正在取回记忆册…':error||'暂无记忆册，保存的对话会收在这里。',loading?'loading':error?'error':'empty'));
        return content;
      }
      stage.append(element('div','mb-rail'),element('span','mb-bank-caption',`${months.length} 本月册`));
      const bank=element('div','mb-bank');
      months.forEach((m,i)=>{
        const b=button('','select','mb-solid',`${monthLabel(m.month)}，${m.dayCount}页，${m.entryCount}条内容`);b.dataset.month=m.month;b.dataset.jacket=pad(monthParts(m.month)[1]);b.style.setProperty('--mb-thickness',thicknessFor(m.dayCount)+'px');b.style.setProperty('--mb-book-tone',bookTone(m.month));
        const spine=element('span','mb-spine');spine.append(element('span','mb-spine-number',String(monthParts(m.month)[0])),element('span','mb-spine-title',monthName(m.month)),element('span','mb-spine-dot',''));
        b.append(coverFace(m.month),element('span','mb-page-top'),spine);const shadow=element('span','mb-book-shadow');shadow.setAttribute('aria-hidden','true');bank.append(shadow,b);
      });stage.append(bank);
      const info=element('div','mb-selection');info.append(element('p','mb-current-month'),element('p','mb-current-count'));
      const navigation=element('div','mb-bank-nav');const prev=button('‹','book-prev','mb-icon','选择前一本月册'),next=button('›','book-next','mb-icon','选择后一本月册');navigation.append(prev,element('span','mb-bank-index'),next);info.append(navigation);content.append(info);
      content.append(element('p','mb-shelf-hint'));
      return content;
    }
    // All books derive their pose from this one selection position. No per-book clocks.
    function paintBank(){
      if(dead||!visible||view!=='shelf'||!months.length)return;
      const stage=root.querySelector('.mb-stage');if(!stage)return;
      const width=stage.clientWidth||container.clientWidth||340;
      const selectedIndex=clamp(Math.round(pose),0,months.length-1);
      selected=months[selectedIndex].month;
      root.dataset.expanded=String(expanded);
      const widths=months.map(m=>shownWidths.get(m.month)??thicknessFor(m.dayCount)),packed=[],lanes=[];let packedTotal=0,laneTotal=0;
      widths.forEach(w=>{packed.push(packedTotal);lanes.push(laneTotal);packedTotal+=w+10;laneTotal+=w+26;});
      const floor=Math.floor(pose),fraction=pose-floor;
      const origin=lanes[floor]+((lanes[Math.min(floor+1,lanes.length-1)]-lanes[floor])*fraction);
      const thickness=widths[floor]+((widths[Math.min(floor+1,widths.length-1)]-widths[floor])*fraction);
      const shadows=root.querySelectorAll('.mb-book-shadow');
      root.querySelectorAll('.mb-solid').forEach((book,i)=>{
        const distance=i-pose;
        const weight=Math.pow(Math.max(0,1-Math.abs(distance)),1.4)*spread;
        const closed=width/2-(packedTotal-10+88)/2+packed[i];
        const browsed=width/2+6-thickness+(lanes[i]-origin)-weight*50;
        const x=closed+(browsed-closed)*spread;
        const y=110+Math.abs(distance)*3-weight*66;
        book.style.transform=`translate3d(${x.toFixed(2)}px,${y.toFixed(2)}px,0)`;
        book.style.zIndex=String((goldLayout?Math.round(weight*100):0)+i+1);if(book.style.getPropertyValue('--mb-thickness')!==widths[i]+'px')book.style.setProperty('--mb-thickness',widths[i]+'px');book.style.setProperty('--mb-lift',weight.toFixed(3));
        const shadow=shadows[i];shadow.style.transform=`translate3d(${(x+weight*27).toFixed(2)}px,312px,0) scale(${((88+widths[i])/104*(1-weight*.15)).toFixed(3)},${(1+weight*.8).toFixed(3)})`;shadow.style.opacity=String(.27-weight*.12);
        const pressed=String(expanded&&i===selectedIndex);if(book.getAttribute('aria-pressed')!==pressed)book.setAttribute('aria-pressed',pressed);
      });
      root.querySelector('.mb-selection').style.opacity=String(1-Math.abs(pose-selectedIndex)*.35);
      const m=findMonth(selected);
      putText(root.querySelector('.mb-current-month'),expanded?monthLabel(selected):'收好的日子');
      putText(root.querySelector('.mb-current-count'),expanded?`${m.dayCount}页 · ${m.entryCount}条保存内容`:`${months.length}本月册，等你慢慢翻开`);
      putText(root.querySelector('.mb-bank-index'),`${String(selectedIndex+1).padStart(2,'0')} / ${String(months.length).padStart(2,'0')}`);
      root.querySelector('[data-action="book-prev"]').disabled=!expanded||selectedIndex===0;
      root.querySelector('[data-action="book-next"]').disabled=!expanded||selectedIndex===months.length-1;
      putText(root.querySelector('.mb-shelf-hint'),expanded?'左右滑动选月 · 点选中的书或下方按钮打开':'先展开书架，再选一本月册');
      const read=root.querySelector('[data-action="read"]'),expand=root.querySelector('[data-action="expand"]');
      if(read){read.hidden=!expanded;putText(read,`翻开${monthName(selected)}  ↗`);read.disabled=bankFrame!==null;}
      if(expand)expand.hidden=expanded;
    }
    function stopBank(){bankVelocity=0;bankTimestamp=-Infinity;bankEpoch++;if(bankFrame!==null)global.cancelAnimationFrame?.(bankFrame);if(dragFrame!==null)global.cancelAnimationFrame?.(dragFrame);dragFrame=null;bankFrame=null;bankTarget=null;drag=null;}
    function animateBank(target,targetSpread=1){
      const incoming=clock()-bankTimestamp<100?bankVelocity:0;
      clearFlight();stopBank();const epoch=bankEpoch;bankTarget=target;
      const fromWidths=months.map(m=>shownWidths.get(m.month)??thicknessFor(m.dayCount)),toWidths=months.map(m=>thicknessFor(m.dayCount));
      if(reduced()||!global.requestAnimationFrame){pose=target;spread=targetSpread;months.forEach((m,i)=>shownWidths.set(m.month,toWidths[i]));bankTarget=null;paintBank();return;}
      const start=clock(),fromPose=pose,fromSpread=spread,duration=fromSpread!==targetSpread?620:Math.abs(target-fromPose)<.001?240:360;
      const velocity=clamp(incoming,-Math.max(.001,Math.abs(target-fromPose)/duration*2),Math.max(.001,Math.abs(target-fromPose)/duration*2));let lastTime=start,lastPose=fromPose;
      function tick(now){
        if(dead||!visible||view!=='shelf'||epoch!==bankEpoch)return;
        const t=clamp((now-start)/duration,0,1),ease=(1-(1+8*t)*Math.exp(-8*t))/(1-9*Math.exp(-8));
        pose=clamp(fromPose+(target-fromPose)*ease+velocity*duration*t*(1-t)*(1-t),0,months.length-1);spread=fromSpread+(targetSpread-fromSpread)*ease;
        bankVelocity=now>lastTime?(pose-lastPose)/(now-lastTime):0;bankTimestamp=now;lastTime=now;lastPose=pose;
        months.forEach((m,i)=>shownWidths.set(m.month,fromWidths[i]+(toWidths[i]-fromWidths[i])*ease));
        if(t<1){bankFrame=global.requestAnimationFrame(tick);paintBank();}
        else{bankFrame=null;bankTarget=null;bankVelocity=0;pose=target;spread=targetSpread;paintBank();}
      }
      bankFrame=global.requestAnimationFrame(tick);paintBank();
    }
    function expandShelf(index=months.findIndex(m=>m.month===selected)){
      expanded=true;animateBank(clamp(index,0,months.length-1),1);
    }
    function stepBook(delta){if(!expanded)return;animateBank(clamp((bankTarget??Math.round(pose))+delta,0,months.length-1));}
    function clearFlight(){if(!flight)return;const old=flight;flight=null;old.animations.forEach(a=>a.cancel());old.node.remove();delete root.dataset.motion;}
    function flyCover(month,from,to,closing){
      clearFlight();if(mobileLayout||reduced()||!from||!to||!root.animate)return;
      const bounds=root.getBoundingClientRect(),node=element('div','mb-flight'),lid=coverFace(month);node.append(lid);node.style.width='140px';node.style.height='198px';node.style.setProperty('--mb-book-tone',bookTone(month));
      root.append(node);root.dataset.motion=closing?'closing':'opening';
      const flat=r=>`matrix(${r.width/140},0,0,${r.height/198},${r.left-bounds.left},${r.top-bounds.top})`;
      const projected=r=>`matrix(${r.width/140},${-33.6/140},0,${(r.height-33.6)/198},${r.left-bounds.left},${r.top-bounds.top+33.6})`;
      const fromTransform=closing?flat(from):projected(from),toTransform=closing?projected(to):flat(to);
      const frames=[{transform:fromTransform,opacity:1},{transform:toTransform,opacity:1,offset:.9},{transform:toTransform,opacity:0}];
      const options={duration:520,easing:'cubic-bezier(.2,.65,.22,1)',fill:'both'};
      const move=node.animate(frames,options),turn=lid.animate(closing?[{transform:'perspective(1000px) rotateY(-105deg)'},{transform:'perspective(1000px) rotateY(0deg)',offset:.55},{transform:'perspective(1000px) rotateY(0deg)'}]:[{transform:'perspective(1000px) rotateY(0deg)'},{transform:'perspective(1000px) rotateY(0deg)',offset:.4},{transform:'perspective(1000px) rotateY(-105deg)'}],options);
      flight={node,animations:[move,turn]};move.onfinish=()=>{if(flight?.node===node){node.remove();flight=null;delete root.dataset.motion;}};
    }
    function readBook(){
      if(!expanded||bankFrame!==null)return;
      const origin=root.querySelectorAll('.mb-solid')[months.findIndex(m=>m.month===selected)]?.querySelector('.mb-cover');
      const from=origin?.getBoundingClientRect?.();stopBank();direction=1;openMonth(selected);
      const to=root.querySelector('.mb-paper')?.getBoundingClientRect?.();flyCover(selected,from,to,false);
    }
    function entryCard(item){
      const card=element('article','mb-entry mb-entry-'+item.kind),head=element('div','mb-entry-head'),tag=element('span','mb-kind',({summary:'摘要',memory:'记忆',conversation:'聊天原文'})[item.kind]);head.append(tag);card.append(head,element('p','mb-entry-text',item.text));
      if(item.kind==='summary')card.append(element('p','mb-entry-note',entries.some(e=>e.kind==='conversation')?'这是整理后的摘要，已保存原文另列于本页。':'这是整理后的摘要，当前未提供聊天原文。'));
      if(item.sourceRefs.length){const refs=element('div','mb-sources');refs.append(element('span','','来源'));item.sourceRefs.forEach(ref=>refs.append(element('span','mb-source',ref.label)));card.append(refs);}
      return card;
    }
    function renderReader(){
      const paper=element('div','mb-paper'),head=element('div','mb-day-heading');
      const select=element('select','mb-date-select');select.setAttribute('aria-label','选择本月日期');
      for(const meta of days){const option=element('option','',`${monthParts(selected)[1]}月${Number(meta.day.slice(8))}日`);option.value=meta.day;option.selected=currentDay===meta.day;select.append(option);}select.disabled=!days.length;select.dataset.action='date';
      head.append(element('span','mb-paper-label','一日一页'),select,element('span','mb-weekday',currentDay?weekday(currentDay):''));paper.append(head);
      const body=element('div','mb-day-scroll');body.tabIndex=0;body.setAttribute('aria-label','当天保存的内容，可纵向滚动');body.setAttribute('aria-busy',String(loading));
      if(loading)body.append(status('正在翻到这一天…'));
      else if(error)body.append(status(error,'error'));
      else{const count=element('p','mb-entry-count',`${entries.length}条已保存内容`);body.append(count);entries.forEach(e=>body.append(entryCard(e)));body.append(element('p','mb-page-end','— 这一天的内容到这里 —'));}
      if(!loading&&!error&&direction){body.classList.add(direction<0?'mb-flip-back':'mb-flip-forward');body.addEventListener('animationend',()=>body.classList.remove('mb-flip-back','mb-flip-forward'),{once:true});}
      paper.append(body);
      const nav=element('nav','mb-day-nav');nav.setAttribute('aria-label','按已保存的日页翻页');
      const prev=button('‹ 上一页','prev','mb-page-button'),next=button('下一页 ›','next','mb-page-button');prev.disabled=!nextTarget(-1);next.disabled=!nextTarget(1);
      const center=element('div','mb-page-number');center.append(element('strong','',days.length?`${Math.max(1,days.findIndex(d=>d.day===currentDay)+1)} / ${days.length}`:'—'),element('span','',monthLabel(selected)));nav.append(prev,center,next);paper.append(nav);return paper;
    }
    function render(){
      if(dead||!visible)return;
      const focusAction=root.contains(doc.activeElement)?doc.activeElement.dataset.action:null;
      rememberPosition();stopBank();root.replaceChildren(header());root.dataset.view=view;
      if(view==='shelf'){
        root.append(renderShelf());
        if(!loading&&!error&&months.length){const foot=element('footer','mb-shelf-footer'),expand=button('展开书架  ↗','expand','mb-primary'),read=button('翻开月册','read','mb-primary');foot.append(expand,read);root.append(foot);}
      }else root.append(renderReader());
      paintedDay=view==='reader'?currentDay:null;
      if(view==='reader'&&!loading&&!error){const body=root.querySelector('.mb-day-scroll');body.scrollTop=readingPositions.get(currentDay)||0;}
      if(view==='shelf'&&!loading&&!error){const shelf=root.querySelector('.mb-shelf-scroll');if(shelf)shelf.scrollTop=shelfScrollTop;}
      const live=element('span','mb-live','');live.setAttribute('role','status');live.setAttribute('aria-live','polite');
      if(loading)live.textContent='载入中';
      else if(error)live.textContent=error;
      else if(view==='reader')live.textContent=`${monthLabel(selected)}${Number(currentDay.slice(8))}日，${entries.length}条保存内容`;
      else live.textContent=`${months.length}本记忆册`;
      root.append(live);
      if(view==='shelf'&&!loading&&!error&&months.length){
        months.forEach(m=>{if(!shownWidths.has(m.month))shownWidths.set(m.month,thicknessFor(m.dayCount));});
        pose=Math.max(0,months.findIndex(m=>m.month===selected));spread=expanded?1:0;paintBank();
        if(months.some(m=>Math.abs(shownWidths.get(m.month)-thicknessFor(m.dayCount))>.001))animateBank(pose,spread);
      }
      if(flight)root.append(flight.node);
      if(focusAction){const target=root.querySelector(`[data-action="${focusAction}"]`);if(target&&!target.disabled)target.focus({preventScroll:true});}
      if(mobileLayout)root.dispatchEvent(new CustomEvent('memory-books:view',{bubbles:true,detail:{view,monthLabel:selected?monthLabel(selected):''}}));
    }
    function failed(r){if(!current(r))return;loading=false;entries=[];error='内容暂时没有取回，可以重试。';direction=0;render();}
    function omitEmptyMonth(){
      months=months.filter(m=>m.month!==selected);selected=months[0]?.month||null;view='shelf';days=[];entries=[];currentDay=null;loading=false;direction=0;clearFlight();render();
    }
    async function dayWithin(r,day){
      if(!current(r))return;dayParts(day);currentDay=day;
      const index=days.findIndex(d=>d.day===day);if(index<0)return;
      const raw=await dataSource.loadDay({day,signal:r.signal});if(!current(r))return;
      const result=entriesData(raw,day);
      if(!result.length){
        days.splice(index,1);updateMonthCounts();
        if(!days.length){omitEmptyMonth();return;}
        currentDay=days[Math.min(index,days.length-1)].day;render();await dayWithin(r,currentDay);return;
      }
      days[index]={...days[index],entryCount:result.length};updateMonthCounts();lastDayByMonth.set(selected,day);entries=result;loading=false;error='';render();
    }
    async function openMonth(month,day=null,edge='remember'){
      monthParts(month);if(!findMonth(month)||dead||!visible)return;
      view='reader';selected=month;currentDay=null;days=[];const r=begin();
      try{const raw=await dataSource.listDays({month,signal:r.signal});if(!current(r))return;days=daysData(raw,month).filter(d=>d.entryCount>0);updateMonthCounts();
        if(!days.length){omitEmptyMonth();return;}
        const requested=day||(edge==='remember'?lastDayByMonth.get(month):null);const chosen=days.some(d=>d.day===requested)?requested:(edge==='first'?days[0].day:days[days.length-1].day);currentDay=chosen;render();await dayWithin(r,chosen);
      }catch{failed(r);}
    }
    async function navigate(day,sign=0){
      if(!days.some(d=>d.day===day)||dead||!visible)return;direction=sign;currentDay=day;const r=begin();try{await dayWithin(r,day);}catch{failed(r);}
    }
    async function refresh(){
      if(dead||!visible)return;const oldView=view,oldMonth=selected,oldDay=currentDay;const r=begin();
      try{const raw=await dataSource.listMonths({signal:r.signal});if(!current(r))return;months=monthsData(raw).filter(m=>m.dayCount>0&&m.entryCount>0);selected=findMonth(oldMonth)?oldMonth:mobileLayout&&findMonth(currentMonth)?currentMonth:months[0]?.month||null;
        if(oldView==='reader'&&findMonth(oldMonth)){
          view='reader';const rawDays=await dataSource.listDays({month:oldMonth,signal:r.signal});if(!current(r))return;days=daysData(rawDays,oldMonth).filter(d=>d.entryCount>0);updateMonthCounts();if(!days.length){omitEmptyMonth();return;}currentDay=days.some(d=>d.day===oldDay)?oldDay:days[days.length-1].day;render();await dayWithin(r,currentDay);
        }else{view='shelf';currentDay=null;entries=[];loading=false;direction=0;render();}
      }catch{failed(r);}
    }
    function backToShelf(){
      const month=selected,from=root.querySelector('.mb-paper')?.getBoundingClientRect?.();
      clearFlight();invalidate();view='shelf';entries=[];days=[];currentDay=null;loading=false;error='';direction=0;expanded=true;render();
      const origin=root.querySelectorAll('.mb-solid')[months.findIndex(m=>m.month===month)]?.querySelector('.mb-cover');flyCover(month,from,origin?.getBoundingClientRect?.(),true);
    }
    async function open(){if(dead)return;if(visible)return;previousFocus=doc.activeElement;visible=true;root.hidden=false;view='shelf';direction=0;await refresh();if(visible&&!dead)root.querySelector('button')?.focus({preventScroll:true});}
    function hide(notify){if(dead||!visible)return;rememberPosition();stopBank();clearFlight();invalidate();visible=false;loading=false;entries=[];days=[];root.hidden=true;root.replaceChildren();if(previousFocus?.isConnected)previousFocus.focus({preventScroll:true});if(notify)onClose();}
    function close(){hide(true);}
    function setVisible(value){return value?open():hide(false);}
    function destroy(){if(dead)return;stopBank();clearFlight();invalidate();dead=true;visible=false;entries=[];months=[];days=[];shownWidths.clear();readingPositions.clear();lastDayByMonth.clear();events.abort();root.remove();if(instances.get(container)===api)instances.delete(container);}
    root.addEventListener('click',e=>{
      const b=e.target.closest('[data-action]');if(!b||!root.contains(b)||b.disabled)return;
      const action=b.dataset.action;
      if(action==='close')close();else if(action==='shelf')backToShelf();
      else if(action==='expand')expandShelf();
      else if(action==='book-prev')stepBook(-1);else if(action==='book-next')stepBook(1);
      else if(action==='select'){
        if(clock()<suppressClickUntil)return;
        const index=months.findIndex(m=>m.month===b.dataset.month);
        if(!expanded)expandShelf(index);
        else if(Math.abs(pose-index)<.02&&bankFrame===null)readBook();
        else animateBank(index);
      }else if(action==='read')readBook();
      else if(action==='prev')turnPage(-1);
      else if(action==='next')turnPage(1);
      else if(action==='refresh'){clearFlight();refresh();}
    },{signal:events.signal});
    root.addEventListener('change',e=>{if(e.target.dataset.action==='date'){clearFlight();navigate(e.target.value,0);}},{signal:events.signal});
    root.addEventListener('keydown',e=>{
      if(e.key==='Escape'){e.stopPropagation();if(view==='reader')backToShelf();else close();}
      else if(view==='shelf'&&expanded&&['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();stepBook(e.key==='ArrowLeft'?-1:1);}
    },{signal:events.signal});
    root.addEventListener('pointerdown',e=>{
      if(!expanded||view!=='shelf'||loading||!months.length||e.button!==0||!e.target.closest('.mb-stage'))return;
      const startPose=pose;stopBank();drag={id:e.pointerId,x:e.clientX,y:e.clientY,pose:startPose,moved:false,lastX:e.clientX,lastTime:e.timeStamp,velocity:0};
    },{signal:events.signal});
    root.addEventListener('pointermove',e=>{
      if(!drag||drag.id!==e.pointerId)return;
      const dx=e.clientX-drag.x,dy=e.clientY-drag.y;
      if(!drag.moved){if(Math.abs(dy)>Math.abs(dx)&&Math.abs(dy)>8){drag=null;return;}if(Math.abs(dx)<8)return;drag.moved=true;e.target.closest('.mb-stage')?.setPointerCapture?.(e.pointerId);clearFlight();}
      const dt=e.timeStamp-drag.lastTime;if(dt>0)drag.velocity=(e.clientX-drag.lastX)/dt;
      drag.lastX=e.clientX;drag.lastTime=e.timeStamp;pose=clamp(drag.pose-dx/80,0,months.length-1);if(!mobileLayout)paintBank();else if(dragFrame===null)dragFrame=global.requestAnimationFrame(()=>{dragFrame=null;paintBank();});
    },{signal:events.signal});
    function releaseDrag(e){if(!drag||drag.id!==e.pointerId)return;const moved=drag.moved,velocity=drag.velocity;drag=null;if(moved){bankVelocity=-velocity/80;bankTimestamp=clock();suppressClickUntil=clock()+350;animateBank(clamp(Math.round(pose-(e.type==='pointercancel'?0:velocity*.13)),0,months.length-1));}else if(Math.abs(pose-Math.round(pose))>.001)animateBank(Math.round(pose));else paintBank();}
    root.addEventListener('pointerup',releaseDrag,{signal:events.signal});root.addEventListener('pointercancel',releaseDrag,{signal:events.signal});
    const resizeObserver=mobileLayout&&global.ResizeObserver?new ResizeObserver(()=>{if(!dead&&visible&&view==='shelf'&&dragFrame===null)dragFrame=global.requestAnimationFrame(()=>{dragFrame=null;paintBank();});}):null;
    resizeObserver?.observe(container);
    const motionPreference=global.matchMedia?.('(prefers-reduced-motion: reduce)');
    motionPreference?.addEventListener?.('change',()=>{if(reduced()){const target=bankTarget??Math.round(pose);stopBank();pose=target;spread=expanded?1:0;months.forEach(m=>shownWidths.set(m.month,thicknessFor(m.dayCount)));clearFlight();paintBank();}},{signal:events.signal});
    const api=Object.freeze({open,close,refresh,setVisible,destroy(){resizeObserver?.disconnect();destroy();}});instances.set(container,api);return api;
  }
  global.HebaoMemoryBooks=Object.freeze({mount});
})(window);
