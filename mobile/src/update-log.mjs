const bytes=s=>new TextEncoder().encode(s).length;
export function validateUpdateLog(v){
 const line=(s,n)=>typeof s==='string'&&s.trim().length>0&&s.length<=n&&!/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(s);
 const date=typeof v?.date==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(v.date)?new Date(v.date):null;
 if(!v||Object.keys(v).sort().join()!=='changes,date,knownIssues,schema,status,versionCode,versionName'||v.schema!==1||!line(v.versionName,50)||!Number.isSafeInteger(v.versionCode)||v.versionCode<1||!line(v.status,100)||!date||!Number.isFinite(+date)||date.toISOString().slice(0,10)!==v.date||bytes(JSON.stringify(v))>8192||!['changes','knownIssues'].every(k=>Array.isArray(v[k])&&v[k].length<=8&&v[k].every(s=>line(s,400))))throw Error('随包日志格式无效，请反馈此构建。');
 return v;
}
export function mountUpdateLog({container,fetcher=(...a)=>fetch(...a)}){
 const details=document.createElement('details'),summary=document.createElement('summary'),body=document.createElement('div');summary.textContent='本次更新日志';body.className='hint';body.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;max-width:100%';details.append(summary,body);container.append(details);
 let generation=0,closed=false,key=null;
 async function update(installed){
  if(closed)return;
  const next=JSON.stringify([installed?.versionName??null,installed?.versionCode??null]);if(next===key)return;key=next;const ticket=++generation;body.replaceChildren();
  const p=text=>{const e=document.createElement('p');e.textContent=text;body.append(e);};
  if(!installed||typeof installed.versionName!=='string'||!Number.isSafeInteger(installed.versionCode)||installed.versionCode<1){p('尚未取得实际安装版本，不能确认本次日志。');return;}
  p('实际安装：'+installed.versionName+' / 构建 '+installed.versionCode);
  try{
   const r=await fetcher('update-log.json',{cache:'no-store'});if(!r.ok)throw Error('随包日志缺失或暂未读取。');
   const text=await r.text();if(bytes(text)>8192)throw Error('随包日志超过大小上限。');const log=validateUpdateLog(JSON.parse(text));if(closed||ticket!==generation)return;
   if(log.versionName!==installed.versionName||log.versionCode!==installed.versionCode){p('日志版本与实际安装不符（日志 '+log.versionName+' / '+log.versionCode+'），未作为本次改动展示。');return;}
   p(log.date+' · '+log.status);p('本次改动：\n'+log.changes.map(x=>'• '+x).join('\n'));p('已知问题：\n'+log.knownIssues.map(x=>'• '+x).join('\n'));
  }catch(e){if(!closed&&ticket===generation)p(e instanceof SyntaxError?'随包日志格式无效。':e.message||'随包日志未读取。');}
 }
 return {update,destroy(){closed=true;generation++;details.remove();}};
}
