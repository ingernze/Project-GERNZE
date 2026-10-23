'use strict';
(async()=>{
  const origin=location.origin,embedded=parent!==window,inputs=new AbortController();
  const messages={pet:['嗯，在呢。','再摸一下也可以。','今天也辛苦啦。'],pester:['等、等一下，让我缓缓……'],sway:['我站稳啦。'],settle:['好啦，放稳啦。'],notice:['怎么啦？我在这里。']};
  let character=null,reactions=null,closed=false,visible=true;
  const send=data=>{if(embedded&&!closed)parent.postMessage(data,origin);};
  function dispose(){if(closed)return;closed=true;inputs.abort();reactions?.destroy();character?.destroy();character=null;}
  window.addEventListener('message',event=>{
    if(!embedded||event.source!==parent||event.origin!==origin||closed)return;
    switch(event.data?.type){
      case 'hecate:visibility':if(typeof event.data.visible==='boolean'){visible=event.data.visible;character?.setVisible(visible);}break;
      case 'hecate:blink':character?.blink();break;
      case 'hecate:reply':try{reactions?.receive(event.data.reply);}catch{}break;
      case 'hecate:breathing':if([1.3,1.6].includes(event.data.value))character?.setBreathingStrength(event.data.value);break;
      case 'hecate:pet':character?.respond('pet');break;
      case 'hecate:sway':character?.respond('sway');break;
      case 'hecate:dispose':dispose();break;
    }
  },{signal:inputs.signal});
  window.addEventListener('pagehide',dispose,{signal:inputs.signal});
  try{
    const response=await fetch('layers.json',{signal:inputs.signal});if(!response.ok)throw Error('图层清单未载入');
    const manifest=await response.json();if(closed)return;
    const instance=await HebaoCharacter.mount({
      container:document.getElementById('sample'),manifest,
      assets:Object.fromEntries(manifest.items.map(item=>[item.id,'layers/'+item.id+'.png'])),
      expressions:{happy:'layers/happy.png',annoyed:'layers/annoyed.png'},
      blinkAssets:{underlay:'layers/blink_cleanup_underlay.png',frontHair:'layers/hair_fixed_front_blink.png'},
      onState:state=>{send({type:'hecate:state',busy:state.interacting,status:state.status});reactions?.notifyState();},
      onMessage:key=>{reactions?.notifyLocalMessage(key);if(key!==null){const choices=messages[key];send({type:'hecate:say',text:choices[Math.floor(Math.random()*choices.length)]});}}
    });
    if(closed){instance.destroy();return;}
    character=instance;reactions=HebaoReactions.create({character,onBubble:text=>{if(text!==null)send({type:'hecate:say',text});}});character.setVisible(visible);send({type:'hecate:ready'});
  }catch(error){if(!closed){document.getElementById('status').textContent='人物没有准备好，请重新加载';send({type:'hecate:error'});console.error(error);}}
})();
