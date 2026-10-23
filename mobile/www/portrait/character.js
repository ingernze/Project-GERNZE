'use strict';
(function(global) {
async function mount(options) {
  const { canvas: suppliedView, container: host, manifest, assets = {}, expressions = {}, blinkAssets = {}, onState = () => {}, onMessage = () => {} } = options;
  if (!host || !manifest?.items?.length) throw new Error('角色需要容器和图层清单');
  const view=suppliedView || document.createElement('canvas');
  if(!suppliedView){view.tabIndex=0;view.setAttribute('aria-label','莉宝互动人物');host.appendChild(view);}
  let disposed = false, observer = null, lastState = '', message = null, visible = true;
  const inputs = new AbortController(), ownedTextures = new Set();
  const listen = (target, event, callback) => target.addEventListener(event, callback, {signal: inputs.signal});
  function textureFromCanvas(canvas) {
    const texture = PIXI.Texture.from(canvas); ownedTextures.add(texture); return texture;
  }
  const app = new PIXI.Application({ view, width: 800, height: 900, backgroundAlpha: 0, antialias: true, resolution: Math.min(devicePixelRatio || 1, options.resolution || 1.5, 2048 / Math.max(innerWidth, innerHeight)), autoDensity: true });
  app.ticker.maxFPS = options.fps === 24 ? 24 : 30;
  const actor = new PIXI.Container();
  app.stage.addChild(actor);
  view.style.touchAction='none';view.style.userSelect='none';
  const sprites = new Map(), pieces = [], eyes = {};
  let time = 0, previous = performance.now(), mode = 'animated', paused = false, zoom = false, amplitude = 1;
  let reaction = null, blinkStart = -100, slowBlink = false, nextBlink = 3.2, eyeTest = false;
  let bubbleUntil = 0, tapTimes = [], pointer = null, drag = { x: 0, y: 0 }, dragTarget = { x: 0, y: 0 }, dragging = false;
  function cancelGrab(reset=false) {
    const held=pointer;pointer=null;dragging=false;dragTarget={x:0,y:0};
    if(reset)drag={x:0,y:0};
    if(held&&view.hasPointerCapture(held.id))view.releasePointerCapture(held.id);
  }
  let previousBodyAngle = null, hairFollow = 0, watchFollow = 0;
  let mood = 'normal', pendingMood = null, moodUntil = Infinity;
  let breathingStrength=1.6,breathingTarget=1.6;
  const expressionViews = new Map();
  let blinkUnderlay=null, blinkHairTextures=null;
  function requestMood(value, duration = Infinity) {
    pendingMood = value; moodUntil = duration === Infinity ? Infinity : time + duration;
    eyeTest = false; blinkStart = time; slowBlink = false;
    paused = false;
  }
  const headIds = new Set(['neck_hidden','neck_rear_hair_backing','hat_hidden_brim','hair_hat_shadow','hair_hidden_roots','face_visible','ear_left','ear_right','hair_04','hair_05','hair_face_shadow','hair_fixed_front','hair_01','hair_02','hair_03','brow_left','brow_right','nose','mouth_closed','hat_base','neck_front_connection']);
  const leftArm = new Set(['sleeve_left','hand_left','wrist_left_hidden']);
  const rightArm = new Set(['sleeve_right','hand_right','wrist_right_hidden']);
  const staticIds = new Set(['leg_left','leg_right','boot_left','boot_right']);
  const breathingCloth = new Set(['cape_rear','body_connection_underlay','torso','ruffle','ribbon','collar_front','skirt']);
  function breathOffset(x,y) {
    const smooth=t=>{t=Math.max(0,Math.min(1,t));return t*t*(3-2*t);};
    // One continuous chest field: fade out at the neck and waist, leaving the
    // face and legs unchanged. Overlapping clothes use the same source space.
    const weight=smooth((y-350)/120)*smooth((650-y)/180);
    return [Math.max(-180,Math.min(180,x-650))*.012*weight,-2.8*weight];
  }
  const anchors = { hair_04: [553,285], hair_05: [731,283], hair_01:[631,205],hair_02:[573,202],hair_03:[704,211],watch:[628,584],watch_cast_shadow:[628,584],chain:[649,552] };
  function groupFor(id) {
    if (id.startsWith('eye_')) return 'head';
    if (headIds.has(id)) return 'head';
    if (leftArm.has(id)) return 'left-arm';
    if (rightArm.has(id)) return 'right-arm';
    if (id === 'watch' || id === 'watch_cast_shadow') return 'watch';
    if (staticIds.has(id)) return 'legs';
    return 'body';
  }
  function loadImage(src) { return new Promise((resolve,reject) => { const img = new Image(); img.onload=()=>resolve(img); img.onerror=()=>reject(new Error('素材未载入：'+src)); img.src=src; }); }
  function setMode(value) {
    mode=value; paused=false; reaction=null; eyeTest=false; dragging=false;pointer=null;dragTarget={x:0,y:0};drag={x:0,y:0};
    mood='normal';pendingMood=null;moodUntil=Infinity;
    hideMessage(); publish();
  }
  function hideMessage() { if(message !== null) {message=null;onMessage(null);} }
  function say(key,duration=3) {message=key;onMessage(key);bubbleUntil=time+duration;}
  function getState() {
    const active=mode==='animated',age=time-blinkStart;
    const status=disposed?'disposed':!active?'reference':dragging?'drag':reaction?.type==='pet'?'pet':reaction?.type==='pester'?'pester':reaction?.type==='sway'||reaction?.type==='settle'?'sway':eyeTest||(age>=0&&age<.28)?'blink':'idle';
    return {mode,paused,zoom,amplitude,breathingStrength:breathingTarget,mood:pendingMood ?? (active?mood:'normal'),status,disposed,visible,interacting:Boolean(pointer)||dragging||reaction!==null,grab:{active:Boolean(pointer),dragging,x:drag.x,y:drag.y}};
  }
  function publish() {
    const state=getState(),key=JSON.stringify(state);
    if(key!==lastState){lastState=key;onState(state);}
  }
  function destroy() {
    if(disposed)return;
    disposed=true;observer?.disconnect();inputs.abort();
    if(pointer && view.hasPointerCapture(pointer.id))view.releasePointerCapture(pointer.id);
    pointer=null;app.stop();app.destroy(true,{children:true,texture:false,baseTexture:false});
    for(const texture of ownedTextures)texture.destroy(true);
    ownedTextures.clear();hideMessage();publish();
  }
  function respond(type) {
    if(disposed)return;
    if(!['pet','sway','blink'].includes(type))throw new Error('不支持的角色反应：'+type);
    if(mode!=='animated')setMode('animated');
    paused=false;
    const now=time;
    if(type==='pet') {
      tapTimes=tapTimes.filter(t=>now-t<4);tapTimes.push(now);
      const annoyed=tapTimes.length>=4;
      eyeTest=false;reaction={type:annoyed?'pester':'pet',start:now,duration:annoyed?2.2:4.2};
      requestMood(annoyed?'annoyed':'happy',annoyed?3:4.2);
      blinkStart=now;slowBlink=false;nextBlink=now+3+Math.random()*2;
      say(annoyed?'pester':'pet');
    } else if(type==='sway') { reaction={type:'sway',start:now,duration:3};say('sway',2.6); }
    else if(type==='blink') { eyeTest=!eyeTest;reaction=null;hideMessage(); }
    publish();
  }
  try {
    const items=[...manifest.items].sort((a,b)=>a.order-b.order);
    // Keep the original draw order, with each closed-eye replacement below the bangs.
    for(const item of items) {
      if(item.id.endsWith('_opening'))continue;
      const img=await loadImage(assets[item.id] || 'assets/'+item.id+'.png');
      const [l,t,r,b]=item.bounds;
      const canvas=document.createElement('canvas');canvas.width=r-l;canvas.height=b-t;
      canvas.getContext('2d').drawImage(img,l,t,r-l,b-t,0,0,r-l,b-t);
      const texture=textureFromCanvas(canvas),deforms=breathingCloth.has(item.id);
      const sprite=deforms?new PIXI.SimplePlane(texture,13,Math.max(5,Math.ceil((b-t)/22)+1)):new PIXI.Sprite(texture);
      let breathing=null;
      if(deforms){
        const buffer=sprite.geometry.getBuffer('aVertexPosition'),base=new Float32Array(buffer.data),offsets=new Float32Array(base.length);
        for(let i=0;i<base.length;i+=2){const d=breathOffset(l+base[i],t+base[i+1]);offsets[i]=d[0];offsets[i+1]=d[1];}
        breathing={buffer,base,offsets};
      }
      const pivot=new PIXI.Container();pivot.addChild(sprite);
      const group=groupFor(item.id);
      let anchor=anchors[item.id] || (group==='head'?[651,390]:group==='left-arm'?[508,503]:group==='right-arm'?[745,494]:group==='legs'?[638,805]:[638,718]);
      sprite.position.set(l-anchor[0],t-anchor[1]);pivot.position.set(...anchor);
      sprite.visible=item.visible;
      pivot.zIndex=item.order;
      const m=item.id.match(/^eye_(left|right)_(half|closed)$/);
      if(m) {const lash=items.find(x=>x.id==='eye_'+m[1]+'_lashes');pivot.zIndex=lash.order+.1+(m[2]==='closed'?.01:0);}
      actor.addChild(pivot);sprites.set(item.id,sprite);pieces.push({id:item.id,pivot,anchor,group,breathing});
    }
    actor.sortableChildren=true;actor.sortChildren();
    // Preserve the current expression alignment at [535,251,735,431] and original
    // face alpha, front hair and hat as the silhouette; no extra vertical offset.
    for (const expression of ['happy','annoyed']) {
      const img = await loadImage(expressions[expression] || `expression-study/${expression}-candidate.png`);
      const pivot = new PIXI.Container(), clipped = new PIXI.Container();
      const canvas=document.createElement('canvas');canvas.width=600;canvas.height=540;
      canvas.getContext('2d').drawImage(img,0,0,600,540);
      const picture = new PIXI.Sprite(textureFromCanvas(canvas));
      picture.position.set(535-651,251-390); picture.width=200;picture.height=180;
      const faceMask = new PIXI.Sprite(sprites.get('face_visible').texture);
      faceMask.position.copyFrom(sprites.get('face_visible').position);
      const blinkMask = new PIXI.Graphics();
      clipped.addChild(picture,blinkMask);picture.mask=blinkMask;
      pivot.addChild(clipped,faceMask);clipped.mask=faceMask;
      pivot.position.set(651,390);pivot.zIndex=30.5;pivot.visible=false;
      actor.addChild(pivot);pieces.push({id:`expression_${expression}`,pivot,anchor:[651,390],group:'head'});
      expressionViews.set(expression,{pivot,blinkMask,lastBlink:null});
    }
    // Eye cleanup is already clipped in source space. Do not reintroduce the
    // pinholes in the original face alpha by masking this underlay with it.
    if(blinkAssets.underlay && blinkAssets.frontHair) {
      async function croppedTexture(url, bounds) {
        const img=await loadImage(url),[l,t,r,b]=bounds;
        const canvas=document.createElement('canvas');canvas.width=r-l;canvas.height=b-t;
        canvas.getContext('2d').drawImage(img,l,t,r-l,b-t,0,0,r-l,b-t);
        return textureFromCanvas(canvas);
      }
      const texture=await croppedTexture(blinkAssets.underlay,[554,260,705,352]);
      blinkUnderlay=new PIXI.Container();const skin=new PIXI.Sprite(texture);
      skin.position.set(554-651,260-390);blinkUnderlay.addChild(skin);
      blinkUnderlay.position.set(651,390);blinkUnderlay.zIndex=30.45;blinkUnderlay.visible=false;
      actor.addChild(blinkUnderlay);pieces.push({id:'blink_cleanup_underlay',pivot:blinkUnderlay,anchor:[651,390],group:'head'});
      const hair=sprites.get('hair_fixed_front');
      const bounds=items.find(item=>item.id==='hair_fixed_front').bounds;
      blinkHairTextures={open:hair.texture,blink:await croppedTexture(blinkAssets.frontHair,bounds)};
    }
    actor.sortChildren();
    for(const side of ['left','right'])eyes[side]={open:['white','iris','lashes'].map(k=>sprites.get(`eye_${side}_${k}`)),half:sprites.get(`eye_${side}_half`),closed:sprites.get(`eye_${side}_closed`)};
    function fit(){
      const box=host.getBoundingClientRect();if(box.width<=0||box.height<=0)return;
      app.renderer.resize(box.width,box.height);
      if(options.layout){const p=options.layout(box.width,box.height);actor.scale.set(p.scale);actor.pivot.set(0,0);actor.position.set(p.x,p.y);return;}
      const k=Math.min(box.width*.89/1150,box.height*.94/1220)*(zoom?1.78:1);
      actor.scale.set(k);actor.pivot.set(646,zoom?320:635);actor.position.set(box.width*.5,box.height*(zoom?.48:.50));
    }
    observer=new ResizeObserver(fit);observer.observe(host);fit();
    function local(e){const box=view.getBoundingClientRect();return actor.toLocal(new PIXI.Point((e.clientX-box.left)*app.screen.width/box.width,(e.clientY-box.top)*app.screen.height/box.height));}
    listen(view,'pointerdown',e=>{if(e.button!==0||e.isPrimary===false||pointer||paused||!visible)return;if(mode!=='animated')setMode('animated');const point=local(e);if(point.x<95||point.x>1210||point.y<10||point.y>1240)return;pointer={id:e.pointerId,x:e.clientX,y:e.clientY,point};view.setPointerCapture(e.pointerId);});
    listen(view,'pointermove',e=>{if(!pointer||pointer.id!==e.pointerId)return;const dx=e.clientX-pointer.x,dy=e.clientY-pointer.y;if(Math.hypot(dx,dy)>6){dragging=true;reaction=null;dragTarget.x=Math.max(-150,Math.min(150,dx/actor.scale.x));dragTarget.y=Math.max(-110,Math.min(110,dy/actor.scale.y));hideMessage();}});
    function release(e,cancel=false){if(!pointer||pointer.id!==e.pointerId)return;const wasDrag=dragging,point=pointer.point;pointer=null;dragging=false;dragTarget={x:0,y:0};if(view.hasPointerCapture(e.pointerId))view.releasePointerCapture(e.pointerId);if(cancel)return;if(wasDrag){reaction={type:'settle',start:time,duration:1.8};say('settle',2.4);}else if(point.y<465)respond('pet');else{reaction={type:'notice',start:time,duration:1.8};say('notice',2.5);}}
    listen(view,'pointerup',e=>release(e));listen(view,'pointercancel',e=>release(e,true));listen(view,'lostpointercapture',e=>release(e,true));
    listen(view,'keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();respond('pet');}});
    function syncVisibility(){previous=performance.now();if(document.hidden||!visible){cancelGrab(true);app.stop();}else app.start();}
    listen(document,'visibilitychange',syncVisibility);
    app.ticker.add(()=>{
      const now=performance.now(),dt=Math.min((now-previous)/1000,.07);previous=now;
      if(paused)return;time+=dt;
      const active=mode==='animated';
      if(active&&time>nextBlink&&!reaction&&!dragging){blinkStart=time;slowBlink=false;nextBlink=time+3+Math.random()*2;}
      let blink=0;const age=time-blinkStart,duration=slowBlink?1.7:.28;
      if(active&&age>=0&&age<duration) {const p=age/duration;blink=p<.25?p/.25:p<.58?1:(1-p)/.42;}
      let pet=0,sway=0,notice=0,pester=0;
      if(active&&reaction){const age=time-reaction.start,p=Math.min(1,age/reaction.duration),envelope=Math.sin(Math.PI*p);if(p>=1)reaction=null;else if(reaction.type==='pet')pet=envelope;else if(reaction.type==='sway')sway=Math.sin(p*Math.PI*2)*envelope;else if(reaction.type==='settle')sway=Math.sin(p*Math.PI*2)*envelope*.2;else if(reaction.type==='notice')notice=envelope;else pester=envelope;}
      if(eyeTest)blink=1;
      if(active && time > moodUntil && pendingMood === null) requestMood('normal');
      if(pendingMood !== null && blink >= .72) {mood=pendingMood;pendingMood=null;}
      const faceExpression=active?mood:'normal', blinking=blink>=.28;
      if(blinkUnderlay) {
        const cleaned=active&&blinking;
        blinkUnderlay.visible=cleaned;
        const hair=sprites.get('hair_fixed_front'),texture=cleaned?blinkHairTextures.blink:blinkHairTextures.open;
        if(hair.texture!==texture)hair.texture=texture;
      }
      for(const [value,view] of expressionViews) {
        view.pivot.visible=faceExpression===value;
        if(view.lastBlink!==blinking) {
          const g=view.blinkMask;g.clear().beginFill(0xffffff).drawRect(535-651,251-390,200,180);
          if(blinking) {
            g.beginHole().drawPolygon([554-651,294-390,612-651,290-390,619-651,349-390,554-651,351-390]).endHole();
            g.beginHole().drawPolygon([629-651,266-390,699-651,260-390,704-651,325-390,632-651,331-390]).endHole();
          }
          g.endFill();view.lastBlink=blinking;
        }
      }
      for(const id of ['brow_left','brow_right','nose','mouth_closed'])sprites.get(id).visible=faceExpression==='normal';
      for(const side of ['left','right']){const eye=eyes[side];const state=!active||blink<.28?'open':blink<.72?'half':'closed';for(const s of eye.open)s.visible=state==='open';eye.half.visible=state==='half';eye.closed.visible=state==='closed';}
      if(faceExpression!=='normal'&&!blinking)for(const side of ['left','right'])for(const s of eyes[side].open)s.visible=false;
      const ease=1-Math.exp(-dt*(dragging?18:9));drag.x+=(dragTarget.x-drag.x)*ease;drag.y+=(dragTarget.y-drag.y)*ease;
      const a=active?amplitude:0,body=(Math.sin(time*.9)*.0026+sway*.018)*a,tilt=drag.x*.0004;
      // All upper-body pieces share one transform around the waist. Different
      // source pivots must also move through it, or the joints pull apart.
      const bodyVelocity=previousBodyAngle===null?0:(body-previousBodyAngle)/Math.max(dt,.001);
      previousBodyAngle=active?body:null;
      const clamp=(v,limit)=>Math.max(-limit,Math.min(limit,v));
      hairFollow=active?hairFollow+(clamp(-bodyVelocity*.1,.006)-hairFollow)*(1-Math.exp(-dt/ .16)):0;
      watchFollow=active?watchFollow+(clamp(-bodyVelocity*.18,.012)-watchFollow)*(1-Math.exp(-dt/ .22)):0;
      const bodyCos=Math.cos(body),bodySin=Math.sin(body);
      const headTilt=active?-pet*.012+notice*.005:0,headCos=Math.cos(headTilt),headSin=Math.sin(headTilt);
      breathingStrength+=(breathingTarget-breathingStrength)*(1-Math.exp(-dt*5));
      const breath=active?(1-Math.cos(time*Math.PI*2/4.8))*.5*a*breathingStrength:0;
      actor.rotation=tilt;
      for(const piece of pieces){const {id,pivot,anchor,group,breathing}=piece;let rot=0,x=anchor[0],y=anchor[1];
        if(breathing){
          const {buffer,base,offsets}=breathing;
          for(let i=0;i<base.length;i++)buffer.data[i]=base[i]+offsets[i]*breath;
          buffer.update();
        }
        if(active&&group!=='legs'){
          // Each sleeve, wrist and hand stays rigid and follows its shoulder.
          // Keep head/hat still instead of lifting the whole character.
          const shoulder=group==='left-arm'||group==='watch'||id==='chain'?[508,503]:group==='right-arm'||id==='bag'?[745,494]:null;
          if(shoulder){const d=breathOffset(...shoulder);x+=d[0]*breath;y+=d[1]*breath;}
          if(group==='head'){
            const hx=x-651,hy=y-390;
            x=651+hx*headCos-hy*headSin;
            y=390+hx*headSin+hy*headCos+pet*.8;
            rot+=headTilt;
            if(id==='hair_04'||id==='hair_05')rot+=hairFollow;
          }
          if(group==='watch')rot+=watchFollow;
          const bx=x-638,by=y-760;
          x=638+bx*bodyCos-by*bodySin;
          y=760+bx*bodySin+by*bodyCos;
          rot+=body;
        }
        pivot.rotation=rot;pivot.position.set(x+drag.x,y+drag.y);
      }
      if(time>bubbleUntil)hideMessage();
      publish();
    });
    syncVisibility();
    publish();
    return Object.freeze({
      getState,
      setBreathingStrength(value) {if(![1.3,1.6].includes(value))throw new Error("无效呼吸档位");breathingTarget=value;publish();},
      respond,
      blink() {if(disposed)return;eyeTest=false;blinkStart=time;slowBlink=false;nextBlink=time+3+Math.random()*2;publish();},
      setVisible(value) {if(disposed)return;visible=Boolean(value);syncVisibility();publish();},
      setMood(value, duration=Infinity) {
        if(disposed)return;
        if(!['normal','happy','annoyed'].includes(value))throw new Error('不支持的表情：'+value);
        if(duration!==Infinity && (!Number.isFinite(duration)||duration<=0))throw new Error('表情时长必须大于零');
        if(mode!=='animated')setMode('animated');
        reaction=null;requestMood(value,duration);hideMessage();publish();
      },
      setMode(value) {
        if(disposed)return;
        if(!['animated','reference'].includes(value))throw new Error('不支持的展示模式：'+value);
        if(pointer && view.hasPointerCapture(pointer.id))view.releasePointerCapture(pointer.id);
        setMode(value);
      },
      setZoom(value) {if(disposed)return;zoom=Boolean(value);fit();publish();},
      setAmplitude(value) {
        if(disposed)return;
        if(!Number.isFinite(value)||value<0||value>2)throw new Error('活动幅度须在0至2之间');
        amplitude=value;publish();
      },
      setPaused(value) {if(disposed)return;paused=Boolean(value);if(paused)cancelGrab(true);publish();},
      destroy
    });
  } catch(error) {destroy();throw error;}
}
global.HebaoCharacter=Object.freeze({mount});
})(window);
