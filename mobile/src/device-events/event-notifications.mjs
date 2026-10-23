import {event,integer,uuid,requireValue} from './event-contract.mjs';
// Capacitor LocalNotifications 8.3.1 APIs from the supplied definitions. Inject existing plugin.
// No permission request during receipt; no interval, alarm schedule, voice or character action.
export function createEventNotifications({notifications,capacitor,isActive,getEnabled,setEnabled,reservedIds=()=>[],scope=()=>null,resolveTarget,onOpen}){
  const native=capacitor.isNativePlatform()&&capacitor.getPlatform()==='android';
  let dead=false,channel=false,listener=null,initializing=null;
  const ready=()=>!dead&&native&&isActive()&&getEnabled();
  const validId=id=>Number.isInteger(id)&&id>0&&id<=2147483647;
  async function init(){
    if(!native||dead)return;if(listener)return;
    return initializing??=(async()=>{const h=await notifications.addListener('localNotificationActionPerformed',async action=>{
      if(!ready()||action?.notification?.extra?.source!=='hecate-events')return;
      const id=action.notification.id;if(!validId(id))return;
      try{const binding=scope(),extra=action.notification.extra;uuid(extra.peer_id);uuid(extra.event_id);const destination=await resolveTarget(id,{peer_id:extra.peer_id,event_id:extra.event_id});if(binding!==scope()||!ready()||!destination||!['companion','messages'].includes(destination.page))return;onOpen(destination);}catch{/* stale/unknown IDs do not navigate */}
    });if(dead)await h.remove();else listener=h;})().finally(()=>{initializing=null;});
  }
  async function permission(){if(!ready())return false;const p=await notifications.checkPermissions();return ready()&&p.display==='granted';}
  async function enableFromUserClick(){
    if(dead||!native||!isActive())return {allowed:false};
    let p=await notifications.checkPermissions();if(dead||!isActive())return {allowed:false};
    if(p.display!=='granted')p=await notifications.requestPermissions();
    if(dead||!isActive())return {allowed:false};const allowed=p.display==='granted';await setEnabled(allowed);return {allowed};
  }
  async function occupiedIds(){
    const pending=await notifications.getPending(),delivered=await notifications.getDeliveredNotifications();
    const reserved=await reservedIds();requireValue(Array.isArray(reserved),'notification_failed');
    const ids=[...reserved,...pending.notifications.map(n=>n.id),...delivered.notifications.map(n=>n.id)];ids.forEach(id=>integer(id,1,2147483647));return ids;
  }
  async function lookup(id){integer(id,1,2147483647);const p=await notifications.getPending(),d=await notifications.getDeliveredNotifications();return [...p.notifications,...d.notifications].some(n=>n.id===id)?'present':'absent';}
  async function removeOwn(id){
    // Only the reserved ID of this attempt, never cancelAll/removeAll/listener removal for other modules.
    try{await notifications.cancel({notifications:[{id}]});}catch{}
    try{await notifications.removeDeliveredNotificationsById({ids:[id]});}catch{}
  }
  async function submit(message,guard){
    integer(message.id,1,2147483647);event(message.event);
    const valid=()=>ready()&&guard()&&message.event.expires_at>Date.now();
    if(!valid())return {status:'cancelled'};
    try{
      if(!await permission())return {status:valid()?'denied':'cancelled'};
      if(!valid())return {status:'cancelled'};
      if(!channel){await notifications.createChannel({id:'hecate-events',name:'电脑消息',description:'已配对电脑发来的任务与文件消息',importance:3,visibility:0});if(!valid())return {status:'cancelled'};channel=true;}
      // 8.3.1 schedule can request permission itself: recheck after channel awaits.
      // JS cannot atomically bind an OS permission check to a later native bridge call.
      if(!await permission())return {status:valid()?'denied':'cancelled'};
      // Final generation/foreground guard immediately before the native request.
      if(!valid())return {status:'cancelled'};
    }catch{return {status:valid()?'failed':'cancelled'};}
    try{
      await notifications.schedule({notifications:[{id:message.id,title:message.event.title,body:message.event.body,channelId:'hecate-events',smallIcon:'ic_stat_libao',isExactNotification:false,foreground:true,autoCancel:true,extra:{source:'hecate-events',peer_id:message.peer_id,event_id:message.event.event_id}}]});
      if(!valid()){await removeOwn(message.id);return {status:'cancelled'};}
      return {status:'submitted'}; // Plugin accepted submission, NOT proof of visibility or reading.
    }catch{
      if(!valid()){await removeOwn(message.id);return {status:'cancelled'};}
      return {status:'unknown'}; // Native may have posted before the bridge rejected; do not auto-repeat.
    }
  }
  async function destroy(){dead=true;if(listener){await listener.remove();listener=null;}}
  return Object.freeze({init,permission,enableFromUserClick,occupiedIds,lookup,submit,destroy});
}
