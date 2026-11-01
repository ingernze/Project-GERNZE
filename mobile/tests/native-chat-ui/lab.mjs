import {cases} from './cases.mjs';
const frame=document.getElementById('preview'),result=document.getElementById('result'),run=document.getElementById('run'),select=document.getElementById('case');
for(const [id,label]of cases){const option=document.createElement('option');option.value=id;option.textContent=label;select.append(option);}
let queue=[],results=[],running=false;
const show=()=>{result.textContent=JSON.stringify({status:running?'running':results.some(r=>r.status==='failed')?'failed':'passed',results,realProviderCalls:0,realAndroid:false},null,2);};
function next(){if(!queue.length){running=false;run.disabled=false;document.getElementById('one').disabled=false;window.nativeUiResults={status:results.some(r=>r.status==='failed')?'failed':'passed',results,realProviderCalls:0,realAndroid:false};show();return;}const id=queue.shift();document.getElementById('now').textContent=cases.find(c=>c[0]===id)[1];frame.src='frame.html?case='+encodeURIComponent(id);}
function start(ids){if(running)return;queue=ids.slice();results=[];running=true;window.nativeUiResults=null;run.disabled=true;document.getElementById('one').disabled=true;show();next();}
run.onclick=()=>start(cases.map(c=>c[0]));document.getElementById('one').onclick=()=>start([select.value]);
window.addEventListener('message',e=>{if(e.source!==frame.contentWindow||e.data?.type!=='gernze-native-ui-result')return;results.push(e.data.result);show();next();});
document.getElementById('download').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(window.nativeUiResults||{status:'not-run',results},null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='native-ui-browser-results.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
