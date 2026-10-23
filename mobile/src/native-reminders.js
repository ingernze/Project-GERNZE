// Thin adapter over official Capacitor plugins; no background JavaScript loop.
import { Capacitor } from '@capacitor/core';
import { App } from '@capacitor/app';
import { LocalNotifications } from '@capacitor/local-notifications';

export function createRemindersHost({capacitor=Capacitor,app=App,notifications=LocalNotifications}={}) {
  const native=capacitor.isNativePlatform()&&capacitor.getPlatform()==='android';
  let callbacks={},initialized=false,active=true;
  const valid=id=>Number.isInteger(id)&&id>0&&id<=2147483647;
  const host={
    native,
    async init(options={}){
      callbacks=options;if(!native||initialized)return;initialized=true;
      await notifications.createChannel({id:'hecate-study',name:'学习提醒',description:'你自己安排的学习提醒',importance:4,visibility:0});
      await notifications.addListener('localNotificationReceived',event=>callbacks.received?.(event.id));
      await notifications.addListener('localNotificationActionPerformed',event=>callbacks.open?.(event.notification?.id));
      await app.addListener('appStateChange',event=>{active=event.isActive;callbacks.active?.(active)});
      await app.addListener('backButton',async()=>{if(!callbacks.back?.())await app.exitApp()});
    },
    async permission(request=false){
      if(!native)return false;let status=await notifications.checkPermissions();
      if(status.display!=='granted'&&request)status=await notifications.requestPermissions();
      return status.display==='granted';
    },
    async schedule(reminder,{requestPermission=false}={}){
      if(!native)return;if(!valid(reminder.nativeId))throw Error('提醒编号无效。');
      if(!Number.isFinite(reminder.at)||reminder.at<=Date.now())throw Error('请选择一个还没有到的时间。');
      if(!await host.permission(requestPermission))throw Error('手机通知权限未开启，提醒尚未保存。你仍可使用陪伴和学习页。');
      await notifications.schedule({notifications:[{id:reminder.nativeId,title:'莉宝 · 学习提醒',body:reminder.label,channelId:'hecate-study',smallIcon:'ic_stat_libao',isExactNotification:false,schedule:{at:new Date(reminder.at),allowWhileIdle:true},extra:{page:'study'},foreground:true}]});
    },
    async cancel(id){if(native&&valid(id))await notifications.cancel({notifications:[{id}]})},
    async reconcile(reminders){
      if(!native)return [];const delivered=await notifications.getDeliveredNotifications();
      const ids=new Set(delivered.notifications.map(n=>n.id));
      if(!await host.permission(false))return [...ids];
      const pending=await notifications.getPending();const scheduled=new Set(pending.notifications.map(n=>n.id));
      for(const r of reminders)if(r.enabled!==false&&!r.delivered&&!ids.has(r.nativeId)&&valid(r.nativeId)&&r.at>Date.now()&&!scheduled.has(r.nativeId))await host.schedule(r);
      return [...ids];
    },
    async test(){
      if(!native)throw Error('请在手机安装版中测试系统通知。');
      if(!await host.permission(true))throw Error('手机通知权限未开启。');
      await notifications.schedule({notifications:[{id:2147483646,title:'莉宝',body:'系统通知已经连上啦。',channelId:'hecate-study',isExactNotification:false,foreground:true}]});
    },
    get active(){return active}
  };
  return host;
}
