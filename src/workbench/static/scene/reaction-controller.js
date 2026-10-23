'use strict';
(function(global) {
  // Only these presentation values can cross the chat/character boundary.
  function normalizeReply(value) {
    if(typeof value==='string')value={text:value};
    if(!value || typeof value.text!=='string' || !value.text.trim())throw new Error('回复缺少文字');
    return {
      text:value.text.trim().slice(0,4000),
      emotion:['normal','happy','annoyed'].includes(value.emotion)?value.emotion:'normal',
      action:value.action==='sway'?'sway':'none'
    };
  }
  function create({character,onBubble=()=>{},onStatus=()=>{},now=()=>performance.now()}) {
    let pending=null,bubbleTimer=null,lastMotion=-Infinity,applying=false,disposed=false;
    function clearBubble() {if(bubbleTimer!==null){clearTimeout(bubbleTimer);bubbleTimer=null;}}
    function flush() {
      if(disposed||applying||!pending)return;
      const state=character.getState();
      if(state.disposed||state.mode==='reference'||now()-pending.receivedAt>15000){pending=null;onStatus('text-only');return;}
      if(state.paused||state.visible===false||state.interacting){onStatus('queued');return;}
      const reply=pending.reply;pending=null;applying=true;
      try {
        character.setMood(reply.emotion,4);
        if(reply.action==='sway'&&now()-lastMotion>=10000){lastMotion=now();character.respond('sway');}
        clearBubble();onBubble(reply.text);onStatus('shown');
        bubbleTimer=setTimeout(()=>{bubbleTimer=null;if(!disposed)onBubble(null);},5000);
      }finally{applying=false;}
    }
    return Object.freeze({
      receive(value) {
        if(disposed)return null;
        const reply=normalizeReply(value);
        pending={reply,receivedAt:now()};flush();return reply;
      },
      notifyState:flush,
      notifyLocalMessage(key) {if(key!==null)clearBubble();},
      cancelPending() {pending=null;},
      destroy() {if(disposed)return;disposed=true;pending=null;clearBubble();}
    });
  }
  global.HebaoReactions=Object.freeze({create,normalizeReply});
})(window);
