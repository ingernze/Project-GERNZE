// Foreground-only receiver. Opening/reconnecting NEVER restores an enabled state.
export function createCodexTasks({transport,notifier,receiver,onChange=()=>{}}) {
  let available=false,enabled=false,busy=false,revision=0,epoch=0,closed=false;
  let message='连接热点后可开启';
  const state=()=>({available,enabled,busy,message});
  const paint=()=>{if(!closed)onChange(state());};
  function off(text,hide=false){epoch++;enabled=false;receiver.setForeground(false);message=text;if(hide)available=false;paint();}
  async function refresh(){
    if(closed||busy||enabled)return;
    busy=true;paint();
    try{
      const info=await transport.info();
      if(closed)return;
      available=info.available===true;revision=info.revision;
      if(available&&info.enabled){const result=await transport.subscribe(false,revision);revision=result.revision;}
      message=available?'Codex 提醒已关闭':'未启用 Codex 插件';
    }catch{available=false;message='热点未连通';}
    finally{busy=false;paint();}
  }
  async function disable(text='Codex 提醒已关闭'){
    off(text);
    // A late enable response is reconciled by enable() before it exits.
    if(busy||closed)return;
    busy=true;paint();
    try{const result=await transport.subscribe(false,revision);revision=result.revision;}
    catch{available=false;message='已关闭，电脑状态将在失联后过期';}
    finally{busy=false;paint();}
  }
  async function toggle(){
    if(closed)return;
    if(enabled){await disable();return;}
    if(busy||!available)return;
    busy=true;const generation=++epoch;paint();
    try{
      if(!await notifier.permission())throw Error('请先允许莉宝发送通知');
      if(closed||generation!==epoch)return;
      const info=await transport.info();revision=info.revision;
      if(info.available!==true)throw Error('电脑未启用 Codex 插件');
      const result=await transport.subscribe(true,revision);revision=result.revision;
      if(closed||generation!==epoch){await transport.subscribe(false,revision).catch(()=>{});return;}
      if(result.enabled!==true)throw Error('电脑尚未确认开启');
      enabled=true;receiver.setForeground(true);message='Codex 提醒已开启';
    }catch(error){off(error.message||'热点未连通，提醒已关闭');}
    finally{busy=false;paint();}
  }
  async function tick(){
    if(closed||busy||!enabled)return;
    busy=true;const generation=epoch;
    try{
      const lease=await transport.subscribe(true,revision,true);revision=lease.revision;
      if(closed||generation!==epoch||!enabled){await transport.subscribe(false,revision).catch(()=>{});return;}
      await receiver.checkOnce();
    }catch(error){if(generation===epoch)off(error.message||'热点连接已断开，提醒已关闭',true);}
    finally{
      busy=false;
      if(generation!==epoch&&!enabled&&!closed)await transport.subscribe(false,revision).catch(()=>{});
      paint();
    }
  }
  return {get state(){return state();},refresh,toggle,tick,
    disconnect(){off('热点连接已断开，提醒已关闭',true);},
    async pause(){await disable('已暂停，回到前台后需手动开启');},
    destroy(){off('已关闭');closed=true;void receiver.destroy();}
  };
}
