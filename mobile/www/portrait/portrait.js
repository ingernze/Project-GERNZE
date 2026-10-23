'use strict';
(async()=>{
  const inputs=new AbortController(),origin=location.origin;
  const quality=new URLSearchParams(location.search);
  let character=null,closed=false,visible=true,strength=1.6;
  const lines={pet:['嗯，在呢。','再摸一下也可以。','今天也辛苦啦。'],pester:['等、等一下，让我缓缓……'],sway:['我站稳啦。'],settle:['好啦，放稳啦。'],notice:['怎么啦？我在这里。']};
  const send=value=>{if(!closed&&parent!==window)parent.postMessage(value,origin);};
  const layout=(w,h)=>{const scale=Math.max(.01,Math.min((w-12)/760,(h-244)/1206));return {scale,x:w/2-640*scale,y:h-180-1227*scale+Math.min(44,h*.048)};};
  function metrics(){send({type:'hecate:metrics',data:{engine:'PixiJS 6.5.10',character:character?.getState(),fpsLimit:quality.get('fps')==='24'?24:30,resolutionLimit:Number(quality.get('dpr'))||1.5,realPhoneTest:false}});}
  function dispose(){if(closed)return;closed=true;inputs.abort();character?.destroy();character=null;}
  window.addEventListener('pagehide',dispose,{once:true});
  window.addEventListener('message',event=>{
    if(event.source!==parent||event.origin!==origin||closed)return;
    switch(event.data?.type){
      case 'hecate:visibility':if(typeof event.data.visible==='boolean'){visible=event.data.visible;character?.setVisible(visible);}break;
      case 'hecate:breathing':if([1.3,1.6].includes(event.data.value)){strength=event.data.value;character?.setBreathingStrength(strength);}break;
      case 'hecate:blink':character?.blink();break;
      case 'hecate:shake':{
        const state=character?.getState();
        if(visible&&!document.hidden&&state&&!state.interacting&&state.mode==='animated'&&state.mood==='normal')character.respond('sway');
        break;
      }
      case 'hecate:metrics':metrics();break;
      case 'hecate:dispose':dispose();break;
    }
  },{signal:inputs.signal});
  try{
    const resources=await HebaoResources.load('resource-map.json',{signal:inputs.signal});
    if(closed)return;
    const instance=await HebaoCharacter.mount({container:document.getElementById('sample'),manifest:resources.manifest,
      assets:resources.assets,expressions:resources.expressions,blinkAssets:resources.blinkAssets,layout,
      fps:Number(quality.get('fps')),resolution:Number(quality.get('dpr'))||1.5,
      onMessage:key=>{if(key&&lines[key])send({type:'hecate:say',text:lines[key][Math.floor(Math.random()*lines[key].length)]});}
    });
    if(closed){instance.destroy();return;}character=instance;character.setVisible(visible);character.setBreathingStrength(strength);
    send({type:'hecate:ready'});metrics();
  }catch(error){if(!closed){send({type:'hecate:error',message:error.message});console.error(error);}}
})();
