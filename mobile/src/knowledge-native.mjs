import {registerPlugin} from '@capacitor/core';
import {createKnowledgeCache,knowledgeUUID} from './knowledge-cache.mjs';
import {createKnowledgeSync} from './knowledge-sync.mjs';
import {mountKnowledgePanel} from './knowledge-panel.mjs';
const native=registerPlugin('HebaoUpdateTransport');
// App owns the cache; each visible panel owns one fresh sync. No chat reference.
export function createKnowledgeHost({transport=native,storage=globalThis.localStorage,window:win=globalThis.window,document:doc=globalThis.document,cache=createKnowledgeCache()}={}){
 let closed=false,active=true;const views=new Set(),listeners=[];
 const pair=()=>{try{const id=JSON.parse(storage.getItem('hebao.updates.v1')||'{}')?.pair?.pairingId;return knowledgeUUID(id)?id:null;}catch{return null;}};
 const eligible=()=>!closed&&active&&!doc.hidden;
 const on=(target,type,fn)=>{target.addEventListener(type,fn);listeners.push(()=>target.removeEventListener(type,fn));};
 const reset=()=>{for(const view of [...views])view.reset();};
 on(win,'hebao:app-active',e=>{active=e.detail!==false;reset();});
 on(doc,'visibilitychange',reset);
 on(win,'hebao:pairing-changed',reset);
 on(win,'hebao:page-change',e=>{if(e.detail?.page!=='dialogue')for(const view of [...views])view.destroy();});
 on(win,'pagehide',()=>{void destroy();});
 function mount(container){
  if(closed)throw Error('课程书架已关闭。');
  let panel=null,dead=false,generation=0,ready=Promise.resolve();
  const live=()=>!dead&&eligible()&&container.isConnected;
  function stop(){generation++;panel?.destroy();panel=null;container.replaceChildren();}
  function resetPanel(){
   if(dead)return;stop();
   if(!live()){const p=doc.createElement('p');p.className='hint';p.textContent='课程资料已暂停，回到前台后可继续。';container.append(p);return;}
   const token=generation,sync=createKnowledgeSync({transport,cache,getPairingId:pair,isEligible:live,window:win,document:doc});
   try{
    panel=mountKnowledgePanel({container,cache,sync});
    ready=panel.ready.catch(()=>{if(!dead&&token===generation){const p=doc.createElement('p');p.className='hint';p.textContent='本地课程暂未读取，请关闭课程资料后重新打开。';container.append(p);}});
   }catch(error){sync.close();throw error;}
  }
  const view=Object.freeze({get ready(){return ready;},reset:resetPanel,destroy(){if(dead)return;dead=true;stop();views.delete(view);}});
  views.add(view);resetPanel();return view;
 }
 async function destroy(){if(closed)return;closed=true;for(const view of [...views])view.destroy();for(const remove of listeners)remove();await cache.close();}
 return Object.freeze({mount,destroy});
}
