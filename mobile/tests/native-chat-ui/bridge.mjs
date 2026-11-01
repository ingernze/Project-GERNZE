// Contract-shaped test double. It never owns a key or performs HTTP.
export class NativeChatDouble {
  constructor({onRequest=()=>{},cancelMode='drain',cancelDelay=20}={}){
    this.events=[];this.tasks=new Map();this.active=null;this.onRequest=onRequest;this.cancelMode=cancelMode;this.cancelDelay=cancelDelay;this.maxActive=0;
    this.config={enabled:true,configured:true,keyPresent:true,endpoint:'https://synthetic.invalid/chat/completions',model:'synthetic-only',balanceSupported:false};
  }
  log(type,data={}){this.events.push({type,at:performance.now(),...data});}
  error(message,code){return Object.assign(Error(message),{code});}
  async getConfig(){this.log('getConfig');return {...this.config};}
  async configure(value){if(this.active)throw this.error('上一轮尚未结束。','busy');this.config={...this.config,...value};delete this.config.key;return this.getConfig();}
  async deleteKey(){if(this.active)this.cancel({id:this.active.id});this.config={...this.config,enabled:false,configured:false,keyPresent:false};return this.getConfig();}
  request(args){
    const {id,purpose='chat',messages}=args;
    const supplied=Object.hasOwn(args,'maxTokens'),maxTokens=supplied?args.maxTokens:(purpose==='summary'?500:700);
    if(supplied&&(!Number.isSafeInteger(maxTokens)||!(purpose==='summary'?[500]:[700,1800]).includes(maxTokens)))return Promise.reject(this.error('无效预算','invalid_request'));
    if(!['chat','summary'].includes(purpose)||typeof id!=='string'||!/^[A-Za-z0-9_-]{1,100}$/.test(id))return Promise.reject(this.error('无效请求','invalid_request'));
    if(this.active){this.log('busy',{id,purpose,activeId:this.active.id});return Promise.reject(this.error('上一轮尚未结束。','busy'));}
    const inputBytes=new TextEncoder().encode(JSON.stringify(messages)).length;
    if(!Array.isArray(messages)||messages.length<2||messages.length>1000||inputBytes>65536||messages.at(-1)?.role!=='user'||messages.some((m,i)=>Object.keys(m).sort().join()!=='content,role'||m.role!==(i===0?'system':i%2?'user':'assistant')||typeof m.content!=='string'||!m.content))return Promise.reject(this.error('无效消息','invalid_request'));
    const task={id,purpose,messages,inputBytes,maxTokens,cancelled:false,settled:false,queued:false};
    const promise=new Promise((resolve,reject)=>Object.assign(task,{resolve,reject}));this.tasks.set(id,task);this.active=task;this.maxActive=Math.max(this.maxActive,1);
    this.log('request',{id,purpose,inputBytes,maxTokens:task.maxTokens});
    task.deadline=setTimeout(()=>{if(task.settled||task.queued)return;task.cancelled=true;this.log('native-deadline',{id,purpose});if(this.cancelMode==='drain')setTimeout(()=>this.finish(id),this.cancelDelay);},purpose==='summary'?16000:65000);
    this.onRequest(task,this);return promise;
  }
  reply(task){return {data:{choices:[{message:{content:JSON.stringify(task.purpose==='summary'?{text:'合成摘要：只是第三层候选。'}:{text:'合成回复 '+task.id,emotion:'normal',action:'none',core:{overwrite:true},approved:[{body:'恶意批准字段'}]})},finish_reason:'stop'}]}};}
  finish(id){const task=this.tasks.get(id);if(!task||task.settled)return;task.settled=true;clearTimeout(task.deadline);if(this.active===task)this.active=null;
    if(task.cancelled){this.log('rejected-cancelled',{id});task.reject(this.error('已停止等待本轮回复。','cancelled'));}
    else {this.log('resolve',{id,purpose:task.purpose});task.resolve(this.reply(task));}
  }
  // Native may already have called resolve and released its slot before WebView receives the delivery.
  queueDelivery(id){const task=this.tasks.get(id);if(!task||task.settled)return;task.queued=true;clearTimeout(task.deadline);if(this.active===task)this.active=null;this.log('queued-delivery',{id});}
  deliverQueued(id){const task=this.tasks.get(id);if(!task?.queued||task.settled)return;task.settled=true;clearTimeout(task.deadline);this.log('late-delivery',{id,purpose:task.purpose});task.resolve(this.reply(task));}
  async cancel({id}){this.log('cancel',{id,matched:this.active?.id===id});const task=this.active;if(task?.id===id){task.cancelled=true;if(this.cancelMode==='drain')setTimeout(()=>this.finish(id),this.cancelDelay);}return {cancelled:true};}
  async dispose(){for(const task of this.tasks.values()){if(task.queued)this.deliverQueued(task.id);else if(!task.settled){task.cancelled=true;this.finish(task.id);}}}
}
