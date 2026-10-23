import {registerPlugin} from '@capacitor/core';
import {createWeeklySync,validateExchange} from './memory-sync-core.mjs';
const native=registerPlugin('HebaoUpdateTransport');
export async function mountMemorySync({container,journal,beforeChange,afterChange}){
  const section=document.createElement('section');section.className='panel';section.innerHTML='<h3>电脑与手机记忆互通</h3><label><input type="checkbox" id="weeklyMemory" checked> 每周同步一次主动保存的记忆</label><p class="hint">两端在同一热点，电脑更新窗口保持开启。到期后在莉宝前台尝试；错过会补试。只同步主动记忆，不传密钥、聊天全文或自动摘要。</p><button type="button" id="syncMemoryNow">现在同步</button><p class="hint" id="syncMemoryStatus" role="status"></p><div id="syncMemoryConflicts"></div>';container.append(section);
  const $=id=>section.querySelector('#'+id);let alive=true,appActive=true;
  const getPair=()=>{try{return JSON.parse(localStorage.getItem('hebao.updates.v1')||'{}').pair||null;}catch{return null;}};
  const eligible=()=>alive&&appActive&&!document.hidden&&!window.HebaoDialogueController?.getSnapshot().pending;
  const transport={memoryInfo:pairingId=>native.memoryInfo({pairingId}),memoryExchange:async(pairingId,snapshot)=>native.memoryExchange({pairingId,snapshot})};
  const coordinator=createWeeklySync({journal,transport,getPair,eligible,beforeChange,afterChange,onStatus:text=>$('syncMemoryStatus').textContent=text});
  $('weeklyMemory').checked=(await journal.setting('syncEnabled'))!==false;
  $('weeklyMemory').onchange=async()=>{try{await journal.setting('syncEnabled',$('weeklyMemory').checked);$('syncMemoryStatus').textContent=$('weeklyMemory').checked?'每周同步已开启，到期且前台连通时尝试。':'每周同步已暂停。';}catch(e){$('syncMemoryStatus').textContent=e.message;}};
  async function showConflicts(){
    const report=await journal.setting('syncReport'),box=$('syncMemoryConflicts');if(!alive)return;box.replaceChildren();
    if(!report?.conflicts?.length&&!report?.limits?.length)return;
    const binding=await journal.setting('syncBinding');if(!binding)return;
    const state=await journal.exportExchange(binding.scope_id);
    for(const conflict of report.conflicts||[]){
      const item=document.createElement('article'),title=document.createElement('p');title.textContent='这条记忆两边改动不同，暂不用于聊天。';item.append(title);
      const options=state.records.filter(r=>r.id===conflict.id&&!r.deleted);
      for(const record of options){const p=document.createElement('p'),button=document.createElement('button');p.textContent=record.title+'：'+record.body;button.type='button';button.textContent='采用这份';button.onclick=()=>decide(record,false);item.append(p,button);}
      const remove=document.createElement('button');remove.type='button';remove.textContent='确认忘记这条';remove.onclick=()=>decide({id:conflict.id},true);item.append(remove);box.append(item);
    }
    if(report.limits?.length){
      const p=document.createElement('p');p.textContent='合并后超过记忆数量或聊天六条限制，内容已保留但暂不用于聊天。请取消部分用于聊天，或明确忘记不需要的条目。';box.append(p);
      const shown=new Set();for(const record of state.records.filter(r=>!r.deleted)){
        if(shown.has(record.id))continue;shown.add(record.id);const row=document.createElement('article'),text=document.createElement('p'),off=document.createElement('button'),remove=document.createElement('button');text.textContent=record.title+'：'+record.body;off.type=remove.type='button';off.textContent='保留，但不用于聊天';off.onclick=()=>decide({...record,chat_enabled:false},false);remove.textContent='忘记这条';remove.onclick=()=>decide(record,true);row.append(text,off,remove);box.append(row);
      }
    }
    async function decide(record,remove){
      if(!eligible())return;const pair=getPair();if(!pair)return;section.querySelectorAll('button').forEach(b=>b.disabled=true);let detached=false;
      try{
        const before=await journal.exportExchange(binding.scope_id),note=remove?null:Object.fromEntries(['title','body','kind','event_date','chat_enabled','important'].map(k=>[k,record[k]]));
        const result=await validateExchange(await native.memoryDecide({pairingId:pair.pairingId,decision:{id:record.id,fingerprint:report.fingerprint,note,delete:remove}}),binding,before);
        if(!eligible())throw Error('稍后在前台接回结果。');beforeChange();detached=true;await journal.applyExchange(result,before.epoch,binding);await afterChange();detached=false;await showConflicts();$('syncMemoryStatus').textContent='选择已保存。';
      }catch(e){$('syncMemoryStatus').textContent=e.message||'选择未完成，重新同步后再试。';}finally{if(detached)await afterChange();section.querySelectorAll('button').forEach(b=>b.disabled=false);}
    }
  }
  async function tick(force=false){if(await coordinator.run(force))await showConflicts();}
  $('syncMemoryNow').onclick=()=>void tick(true);
  const resume=()=>{if(!document.hidden)void tick();},app=e=>{appActive=e.detail!==false;if(appActive)void tick();};
  document.addEventListener('visibilitychange',resume);window.addEventListener('online',resume);window.addEventListener('hebao:app-active',app);
  const timer=setInterval(()=>void tick(),60000);await showConflicts();void tick();
  return {destroy(){alive=false;coordinator.destroy();clearInterval(timer);document.removeEventListener('visibilitychange',resume);window.removeEventListener('online',resume);window.removeEventListener('hebao:app-active',app);section.remove();}};
}
