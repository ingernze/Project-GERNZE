import {createChatJournal} from '../src/chat-journal.mjs';
export async function runNative(packets){
 const checks=[],check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);},sleep=ms=>new Promise(r=>setTimeout(r,ms));
 const until=async fn=>{for(let i=0;i<200;i++){if(await fn())return;await sleep(10);}throw Error('synthetic native UI timeout');};
 const savedFetch=window.fetch.bind(window),core={schemaVersion:1,entries:[]},sent=[];
 const sample=packets.find(p=>p.records.some(r=>r.restriction==='general')&&p.records.some(r=>r.restriction==='study'));
 const name='hebao-chat-journal-v1',journal=createChatJournal({name});
 await journal.researchCache.apply(sample,{serverId:sample.serverId,scope_id:sample.scope_id});await journal.setting('summaryEnabled',false);await journal.setting('layerSyncEnabled',false);
 localStorage.clear();
 document.body.innerHTML='<style>body{margin:0;padding:0;background:#1d3348}.shell{height:852px;width:100%;display:flex;flex-direction:column}#dialogue{height:100%;min-height:0}[hidden]{display:none!important}.panel{padding:12px}button{font:inherit}.hint{font-size:12px}</style><div id="settings" hidden></div><div class="shell"><div id="dialogue"></div></div>';
 for(const file of ['dialogue-page.css','memory-books.css','theme-soft.css']){const link=document.createElement('link');link.rel='stylesheet';link.href='/www/'+file;document.head.append(link);}
 await import('/www/dialogue-page.js');await import('/www/memory-books.js');
 window.fetch=async input=>{if(String(input)==='chat-persona.txt')return new Response('合成联调人设。');if(String(input)==='chat-core-memory.json')return new Response(JSON.stringify(core));throw Error('No real fetch allowed: '+input);};
 window.__bridge={getConfig:async()=>({enabled:true,configured:true,keyPresent:true,endpoint:'https://synthetic.invalid/v1/chat/completions',model:'synthetic'}),request:async p=>{sent.push(p);return {data:{choices:[{finish_reason:'stop',message:{content:JSON.stringify({text:'合成研究答复'})}}]}};},cancel:async()=>{}};
 window.HebaoDialogueController=window.HebaoDialoguePage.mount({container:document.getElementById('dialogue'),portraitSrc:'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>',sceneSrc:'',artSceneSrc:''});
 window.HebaoDialogueController.setVisible(true);
 await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='/native-test.js';script.onload=resolve;script.onerror=reject;document.head.append(script);});
 window.Stage8Chat.mountChat();await until(()=>document.querySelector('.hebao-dialogue')?.dataset.chatReady==='true');
 check(sent.length===0,'actual native adapter mounts without a provider request');
 const clickText=text=>{const b=[...document.querySelectorAll('button')].find(b=>b.textContent===text&&!b.closest('[hidden]'));if(!b)throw Error('button missing '+text);b.click();};
 async function pick(){document.querySelector('.dl-books').click();await until(()=>[...document.querySelectorAll('button')].some(b=>b.textContent==='研究资料'&&!b.closest('[hidden]')));clickText('研究资料');await until(()=>[...document.querySelectorAll('button')].some(b=>b.textContent==='用于下一次提问'&&!b.closest('[hidden]')));clickText('用于下一次提问');await until(()=>!window.HebaoDialogueController.getSnapshot().memoryOpen);}
 await pick();check([...document.querySelectorAll('.dl-compose [role="status"]')].some(n=>!n.hidden&&n.textContent.includes('仅用于下一次提问')),'bookshelf selection returns to chat and shows one-use notice');
 clickText('取消取用');check(document.querySelector('.dl-compose [role="status"]').hidden,'visible remove button clears selection');
 await pick();window.dispatchEvent(new CustomEvent('hebao:app-active',{detail:false}));check(document.querySelector('.dl-compose [role="status"]').hidden,'background event clears pending selection');
 await pick();window.dispatchEvent(new CustomEvent('hebao:page-change',{detail:{page:'home'}}));check(document.querySelector('.dl-compose [role="status"]').hidden,'leaving dialogue clears pending selection');
 await pick();document.getElementById('chatNewSession').click();await sleep(50);check(document.querySelector('.dl-compose [role="status"]').hidden,'new session button clears pending selection');
 await pick();const input=document.querySelector('.dl-compose textarea');input.value='合成UI问题';input.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('.dl-compose').requestSubmit();await until(()=>sent.length===1&&!window.HebaoDialogueController.getSnapshot().pending);
 check(sent[0].messages[0].content.includes('本轮明确选择的低信任研究摘要')&&document.querySelector('.dl-compose [role="status"]').hidden,'actual composer uses selected summary once then clears notice');
 check((await journal.context(window.HebaoDialogueController.getSnapshot().id)).session.researchRanges.length===1,'actual native adapter persists separate research raw');
 document.querySelector('.dl-books').click();await until(()=>[...document.querySelectorAll('button')].some(b=>b.textContent==='研究资料'));clickText('研究资料');
 check(document.documentElement.scrollWidth<=innerWidth,'393px actual bookshelf and research tabs fit viewport');
 // Keep this view for a screenshot. Teardown is explicit after screenshot in runner.
 window.__finishNative=async()=>{window.dispatchEvent(new Event('pagehide'));window.HebaoDialogueController.destroy();await journal.close();window.fetch=savedFetch;};
 return checks;
}
