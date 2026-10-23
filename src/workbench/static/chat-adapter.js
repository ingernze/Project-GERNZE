'use strict';
(function(global) {
  // Providers implement requestReply({text,signal}) and return {text,emotion,action}.
  // API credentials and provider-specific HTTP handling belong in a local backend.
  function create({requestReply,onReply,onStatus=()=>{}}) {
    if(typeof requestReply!=='function')throw new Error('未配置聊天接口');
    let active=null,sequence=0,disposed=false;
    return Object.freeze({
      async send(input) {
        if(disposed)return;
        if(typeof input!=='string'||!input.trim())return;
        const text=input.trim().slice(0,1000),id=++sequence;
        active?.abort();active=new AbortController();const signal=active.signal;
        onStatus('loading');
        try {
          const reply=await requestReply({text,signal});
          if(disposed||signal.aborted||id!==sequence)return;
          onReply(reply);onStatus('ready');
        }catch(error){
          if(disposed||signal.aborted||id!==sequence)return;
          onStatus('error',error);
        }finally{if(id===sequence)active=null;}
      },
      cancel(){if(disposed)return;++sequence;active?.abort();active=null;},
      destroy(){if(disposed)return;disposed=true;++sequence;active?.abort();active=null;}
    });
  }
  global.HebaoChat=Object.freeze({create});
})(window);
