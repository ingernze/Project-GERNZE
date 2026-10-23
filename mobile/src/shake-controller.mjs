export function createShakeController({plugin,onShake,onStatus=()=>{},clock=()=>performance.now()}) {
  let desired=false,attached=false,disposed=false,active=null,handle=null,queue=Promise.resolve(),lastShake=-Infinity;
  const sync=()=>{
    queue=queue.catch(()=>{}).then(async()=>{
      if(!attached&&!disposed)return;
      const enabled=desired&&!disposed&&attached;
      if(active===enabled)return;
      try{
        const result=await plugin.setEnabled({enabled});
        active=Boolean(result.active);
        if(!disposed)onStatus(result);
      }catch(error){active=null;if(!disposed)onStatus({available:false,active:false,error});}
    });
    return queue;
  };
  return {
    async init(){
      const listener=await plugin.addListener('shake',()=>{
        if(disposed||!desired||!active||clock()-lastShake<3500)return;
        lastShake=clock();onShake();
      });
      if(disposed){await listener.remove();return;}
      handle=listener;attached=true;await sync();
    },
    setActive(value){desired=Boolean(value);return sync();},
    async destroy(){disposed=true;desired=false;await sync();await handle?.remove();handle=null;attached=false;}
  };
}
