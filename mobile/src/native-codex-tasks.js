import {Capacitor,registerPlugin} from '@capacitor/core';
import {LocalNotifications} from '@capacitor/local-notifications';
import {createCodexTasks} from './codex-tasks.mjs';
import {createEventReceiver} from './device-events/event-receiver.mjs';
import {createEventNotifications} from './device-events/event-notifications.mjs';
import {createIndexedEventStorage} from './device-events/event-storage.mjs';
const native=registerPlugin('HebaoUpdateTransport');

export function mountCodexTasks(){
  const home=document.getElementById('home');
  if(!home||!Capacitor.isNativePlatform()||document.getElementById('codexTasksToggle'))return;
  const wrap=document.createElement('aside');wrap.className='codex-tasks-widget';wrap.hidden=true;
  const button=document.createElement('button');button.type='button';button.id='codexTasksToggle';button.setAttribute('aria-pressed','false');
  const status=document.createElement('span');status.setAttribute('role','status');status.className='codex-tasks-status';
  wrap.append(button,status);home.append(wrap);
  const style=document.createElement('style');style.textContent=`
    .codex-tasks-widget{position:absolute;right:18px;bottom:18px;z-index:8;text-align:right;max-width:210px}
    .codex-tasks-widget[hidden]{display:none!important}
    #codexTasksToggle{border:1px solid #b7a47b;border-radius:18px;background:#19344be8;color:#f5edd9;padding:10px 14px;font:inherit;font-size:13px;touch-action:manipulation}
    #codexTasksToggle[aria-pressed=true]{background:#f3ead5;color:#29455d}
    .codex-tasks-status{display:block;font-size:11px;color:#f5edd9;text-shadow:0 1px 3px #102133;margin-top:5px}
  `;document.head.append(style);
  const pair=()=>{try{return JSON.parse(localStorage.getItem('hebao.updates.v1')||'{}').pair?.pairingId||null;}catch{return null;}};
  let boundPair=pair(),timer=null,alive=true;
  const call=(method,request)=>{const pairingId=pair();if(!pairingId||pairingId!==boundPair)throw Error('请重新确认配对电脑');return native[method]({pairingId,...request});};
  const transport={info:()=>call('codexInfo'),subscribe:(enabled,expectedRevision,renew=false)=>call('codexSubscription',{request:{enabled,expectedRevision,renew}})};
  const unpack=answer=>{const {serverId,...data}=answer;return data;};
  const storage=createIndexedEventStorage({name:'gernze-codex-events-v1'});
  let controller,receiver,notificationEnabled=false;
  const notifications=createEventNotifications({notifications:LocalNotifications,capacitor:Capacitor,isActive:()=>!document.hidden,
    getEnabled:()=>notificationEnabled&&controller?.state.enabled===true,setEnabled:async value=>{notificationEnabled=value;},scope:()=>boundPair,
    resolveTarget:(id,expected)=>receiver.notificationTarget(id,expected),onOpen:target=>document.getElementById(target.page==='companion'?'activityBack':'openActivity')?.click()});
  receiver=createEventReceiver({pairingId:boundPair,foreground:false,storage,notify:notifications,transport:{
    async fetch({cursor,stream_id}){return unpack(await call('codexEvents',{request:{cursor,streamId:stream_id}}));},
    async ack({event_ids}){return unpack(await call('codexAck',{request:{eventIds:event_ids}}));}
  }});
  controller=createCodexTasks({transport,notifier:{async permission(){return (await notifications.enableFromUserClick()).allowed;}},receiver,onChange:state=>{
    wrap.hidden=!state.available;button.textContent=state.enabled?'Codex 提醒 · 开':'Codex 提醒 · 关';
    button.setAttribute('aria-pressed',String(state.enabled));button.disabled=state.busy&&!state.enabled;status.textContent=state.message;
    if(!state.enabled&&timer){clearInterval(timer);timer=null;}
    if(state.enabled&&!timer)timer=setInterval(()=>{if(!document.hidden)void controller.tick();},15000);
  }});
  button.onclick=()=>void controller.toggle();
  const resume=()=>{if(!alive)return;if(document.hidden){void controller.pause();return;}const next=pair();if(next!==boundPair){controller.disconnect();boundPair=next;receiver.setPairing(next);}void controller.refresh();};
  const visible=event=>{if(event.detail===true||event.detail?.visible===true)resume();};
  const offline=()=>controller.disconnect();
  document.addEventListener('visibilitychange',resume);window.addEventListener('online',resume);window.addEventListener('offline',offline);window.addEventListener('hebao:portrait-visible',visible);
  const app=event=>{if(event.detail===false)void controller.pause();else resume();};window.addEventListener('hebao:app-active',app);
  void notifications.init();void controller.refresh();
  window.addEventListener('pagehide',()=>{alive=false;controller.destroy();clearInterval(timer);void notifications.destroy();void storage.close();document.removeEventListener('visibilitychange',resume);window.removeEventListener('online',resume);window.removeEventListener('offline',offline);window.removeEventListener('hebao:portrait-visible',visible);window.removeEventListener('hebao:app-active',app);wrap.remove();style.remove();},{once:true});
  return controller;
}
