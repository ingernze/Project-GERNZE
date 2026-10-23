/* Desktop adapter. Supplied GernzeJelly handles brand taps; Matter.js handles soft bodies.
 * Sources and licenses: vendor/SOURCES.md. No character-renderer or application RPC changes. */
(function(root){
'use strict';
const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
const rim=[[-1,-1],[0,-1],[1,-1],[1,0],[1,1],[0,1],[-1,1],[-1,0]];
function bindBrand(button,scope){
  const image=button.querySelector('img');if(!image||!root.GernzeJelly||typeof image.animate!=='function')return;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  const jelly=root.GernzeJelly.create(image,{squash:[.16,.16],stretch:[.104,.104],down:1,lift:5,duration:500});
  let timer=null,active=true;
  const allowed=()=>!scope.closed&&!document.hidden&&!reduced.matches&&active;
  function stop(){clearTimeout(timer);timer=null;jelly.stop();}
  function schedule(){clearTimeout(timer);if(allowed())timer=setTimeout(()=>{if(allowed())jelly.pulse({tap:false,strength:.375,time:660});schedule();},9000+Math.random()*5000);}
  const refresh=()=>{stop();schedule();};
  scope.listen(button,'click',()=>{if(allowed())jelly.pulse();schedule();});
  scope.listen(document,'visibilitychange',refresh);scope.listen(reduced,'change',refresh);
  scope.listen(window,'hebao:app-active',e=>{active=e.detail===true;refresh();});
  scope.own(stop);schedule();
}
function createSoftPet(M,world,x,y,r){
  const group=M.Body.nextGroup(true),settings={collisionFilter:{group,category:1,mask:0xffffffff},restitution:.62,friction:.35,frictionAir:.025,density:.0015,slop:.02};
  const center=M.Bodies.circle(x,y,r*.48,settings);
  const points=rim.map(([u,v])=>M.Bodies.circle(x+u*r,y+v*r,5.5,settings));
  const constraints=[];
  const connect=(a,b,stiffness)=>constraints.push(M.Constraint.create({bodyA:a,bodyB:b,length:M.Vector.magnitude(M.Vector.sub(a.position,b.position)),stiffness,damping:.11}));
  points.forEach((p,i)=>{connect(center,p,.28);connect(p,points[(i+1)%8],.72);});
  for(let i=0;i<4;i++)connect(points[i],points[i+4],.19);
  const composite=M.Composite.create({label:'Gernze soft pet'});M.Composite.add(composite,[center,...points,...constraints]);M.Composite.add(world,composite);
  return {center,points,constraints,composite,r,handle:null};
}
function bounds(M,world,width,height,obstacle){
  const floor=height*.955,thick=80;
  const bodies=[M.Bodies.rectangle(width/2,floor+thick/2,width+160,thick,{isStatic:true}),M.Bodies.rectangle(-thick/2,height/2,thick,height*3,{isStatic:true}),M.Bodies.rectangle(width+thick/2,height/2,thick,height*3,{isStatic:true}),M.Bodies.rectangle(width/2,-thick/2,width+160,thick,{isStatic:true})];
  if(obstacle&&obstacle.width>1&&obstacle.height>1)bodies.push(M.Bodies.rectangle(obstacle.x+obstacle.width/2,obstacle.y+obstacle.height/2,obstacle.width,obstacle.height,{isStatic:true,chamfer:{radius:[Math.min(obstacle.width*.025,obstacle.height*.025),Math.min(obstacle.width*.025,obstacle.height*.025),1,1]}}));
  M.Composite.add(world,bodies);return bodies;
}
function triangle(ctx,img,source,target){
  const [p,q,r]=source,[a,b,c]=target;
  const det=p.x*(q.y-r.y)+q.x*(r.y-p.y)+r.x*(p.y-q.y);if(Math.abs(det)<1e-8)return;
  const solve=key=>[(a[key]*(q.y-r.y)+b[key]*(r.y-p.y)+c[key]*(p.y-q.y))/det,(a[key]*(r.x-q.x)+b[key]*(p.x-r.x)+c[key]*(q.x-p.x))/det,(a[key]*(q.x*r.y-r.x*q.y)+b[key]*(r.x*p.y-p.x*r.y)+c[key]*(p.x*q.y-q.x*p.y))/det];
  const x=solve('x'),y=solve('y'),cx=(a.x+b.x+c.x)/3,cy=(a.y+b.y+c.y)/3;
  const expanded=target.map(v=>{const d=Math.hypot(v.x-cx,v.y-cy)||1;return {x:v.x+(v.x-cx)*.45/d,y:v.y+(v.y-cy)*.45/d};});
  ctx.save();ctx.beginPath();ctx.moveTo(expanded[0].x,expanded[0].y);ctx.lineTo(expanded[1].x,expanded[1].y);ctx.lineTo(expanded[2].x,expanded[2].y);ctx.closePath();ctx.clip();ctx.transform(x[0],y[0],x[1],y[1],x[2],y[2]);ctx.drawImage(img,0,0);ctx.restore();
}
function drawPet(ctx,img,pet,floor){
  const p=pet.center.position,r=pet.r,alt=clamp((floor-p.y)/250,0,1);
  ctx.save();ctx.fillStyle='rgba(4,11,25,'+(.22*(1-alt*.7))+')';ctx.beginPath();ctx.ellipse(p.x,floor+1,r*(.9-alt*.45),r*.13,0,0,Math.PI*2);ctx.fill();ctx.restore();
  if(!img||('complete' in img&&!img.complete)||!(img.naturalWidth||img.width))return;
  const w=img.naturalWidth||img.width,h=img.naturalHeight||img.height,source=rim.map(([u,v])=>({x:(u+1)*w/2,y:(v+1)*h/2}));
  for(let i=0;i<8;i++)triangle(ctx,img,[{x:w/2,y:h/2},source[i],source[(i+1)%8]],[p,pet.points[i].position,pet.points[(i+1)%8].position]);
}
function mount(room,{scope,obstacle}={}){
  const M=root.Matter;if(!M)throw Error('物理引擎未载入');
  const canvas=document.createElement('canvas');canvas.className='scene-jelly-canvas';canvas.setAttribute('aria-hidden','true');room.append(canvas);
  const toolbar=document.createElement('div');toolbar.className='scene-jelly-tools';
  const spawnButton=document.createElement('button'),clearButton=document.createElement('button');spawnButton.className=clearButton.className='scene-button';spawnButton.type=clearButton.type='button';spawnButton.textContent='＋ 果冻小莉宝';clearButton.textContent='收回';clearButton.hidden=true;toolbar.append(spawnButton,clearButton);room.append(toolbar);
  let texture=null;const image=new Image();image.src=root.GernzeJellyArtwork?.pet||'assets/jelly/chibi-idle.png';
  const ctx=canvas.getContext('2d'),engine=M.Engine.create({positionIterations:8,velocityIterations:8,constraintIterations:8,enableSleeping:true});engine.gravity.y=1.25;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');let active=true,closed=false,width=1,height=1,walls=[],pets=[],frame=null,last=0,accumulator=0,drag=null,sequence=0;
  const MAX=50,STEP=1000/120;
  const dialogue=room.querySelector('.desktop-dialogue'),stage=room.closest('.desktop-scene-stage');
  let holdDelay=null,holdRepeat=null,holdPointer=null,suppressHeldClick=false,chatWall=null,chatRect=null;
  spawnButton.title='点击添加一只，长按快速连续添加，最多50只';
  function stopHold(){clearTimeout(holdDelay);clearInterval(holdRepeat);holdDelay=holdRepeat=null;const id=holdPointer;holdPointer=null;if(id!==null){try{if(spawnButton.hasPointerCapture?.(id))spawnButton.releasePointerCapture(id);}catch{}}}
  function allowed(){return !closed&&!document.hidden&&active&&!reduced.matches;}
  function count(){spawnButton.disabled=pets.length>=MAX;spawnButton.textContent=pets.length>=MAX?'已放满 '+MAX+' 只':'＋ 果冻小莉宝'+(pets.length?' · '+pets.length:'');clearButton.hidden=!pets.length;if(pets.length>=MAX)stopHold();}
  function wake(pet){for(const b of M.Composite.allBodies(pet.composite))M.Sleeping.set(b,false);}
  function release(){if(!drag)return;const d=drag;drag=null;M.Composite.remove(engine.world,d.constraint);try{if(d.handle.hasPointerCapture?.(d.id))d.handle.releasePointerCapture(d.id);}catch{}d.handle.classList.remove('is-dragging');}
  function remove(pet){if(drag?.pet===pet)release();M.Composite.remove(engine.world,pet.composite,true);pet.handle.remove();pets=pets.filter(p=>p!==pet);count();render();}
  function clear(){pause();for(const pet of [...pets])remove(pet);render();}
  function position(event){const box=room.getBoundingClientRect(),r=drag?.pet.r||40;return {x:clamp(event.clientX-box.left,r+8,width-r-8),y:clamp(event.clientY-box.top,r+8,height*.955-r-8)};}
  function spawn(){
    if(closed||pets.length>=MAX)return;
    const r=clamp(width*.045,29,47),x=clamp(width*(.57+Math.random()*.3),r+15,width-r-15),y=reduced.matches?height*.955-r-9:Math.max(r+12,height*.12);
    const pet=createSoftPet(M,engine.world,x,y,r),handle=document.createElement('button');pet.handle=handle;handle.type='button';handle.className='scene-jelly-handle';handle.setAttribute('aria-label','拖动果冻小莉宝 '+(++sequence));handle.title='拖动或轻点；Delete 收回';room.append(handle);pets.push(pet);
    M.Body.setVelocity(pet.center,{x:(Math.random()-.5)*3,y:0});
    handle.addEventListener('pointerdown',event=>{
      if(event.button!==0)return;event.preventDefault();release();wake(pet);handle.setPointerCapture?.(event.pointerId);
      const target=position(event),constraint=M.Constraint.create({pointA:target,bodyB:pet.center,pointB:{x:0,y:0},length:0,stiffness:.13,damping:.12});M.Composite.add(engine.world,constraint);
      drag={pet,constraint,handle,id:event.pointerId,start:target,moved:false};handle.classList.add('is-dragging');
    });
    handle.addEventListener('pointermove',event=>{
      if(drag?.handle!==handle||drag.id!==event.pointerId)return;const target=position(event);drag.moved ||= Math.hypot(target.x-drag.start.x,target.y-drag.start.y)>5;
      drag.constraint.pointA=target;wake(pet);
      if(reduced.matches){const d=M.Vector.sub(target,pet.center.position);M.Composite.translate(pet.composite,d);render();}
    });
    const finish=event=>{if(drag?.handle!==handle||drag.id!==event.pointerId)return;const tap=!drag.moved;release();if(tap&&!reduced.matches){wake(pet);for(const p of pet.points)M.Body.applyForce(p,p.position,{x:0,y:-.00065});}};
    handle.addEventListener('pointerup',finish);for(const name of ['pointercancel','lostpointercapture'])handle.addEventListener(name,()=>{if(drag?.handle===handle)release();});
    handle.addEventListener('keydown',event=>{if(['Delete','Backspace'].includes(event.key)){event.preventDefault();remove(pet);}else if(['ArrowLeft','ArrowRight','ArrowUp',' ','Enter'].includes(event.key)){event.preventDefault();wake(pet);M.Body.applyForce(pet.center,pet.center.position,{x:event.key==='ArrowLeft'?-.005:event.key==='ArrowRight'?.005:0,y:event.key==='ArrowLeft'||event.key==='ArrowRight'?-.002:-.018});}});
    count();render();schedule();
  }
  function render(){
    if(closed)return;const dpr=Math.min(devicePixelRatio||1,2);ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);
    for(const pet of pets){drawPet(ctx,texture||image,pet,height*.955);const pts=pet.points.map(p=>p.position),left=Math.min(...pts.map(p=>p.x))-7,top=Math.min(...pts.map(p=>p.y))-7,right=Math.max(...pts.map(p=>p.x))+7,bottom=Math.max(...pts.map(p=>p.y))+7;
      Object.assign(pet.handle.style,{left:left+'px',top:top+'px',width:(right-left)+'px',height:(bottom-top)+'px'});
    }
  }
  function syncDialogueCollision(open=Boolean(dialogue&&!dialogue.hidden)){
    if(closed)return;
    const box=room.getBoundingClientRect(),r=open&&dialogue?.getBoundingClientRect();
    const x=r?clamp(r.left-box.left,0,width):0,y=r?clamp(r.top-box.top,0,height):0;
    const next=r?{x,y,width:clamp(r.right-box.left,0,width)-x,height:clamp(r.bottom-box.top,0,height)-y}:null;
    if(!next||next.width<2||next.height<2){if(chatWall)M.Composite.remove(engine.world,chatWall);chatWall=chatRect=null;for(const pet of pets)wake(pet);return;}
    if(chatRect&&['x','y','width','height'].every(k=>Math.abs(chatRect[k]-next[k])<.5))return;
    release();if(chatWall)M.Composite.remove(engine.world,chatWall);chatRect=next;
    chatWall=M.Bodies.rectangle(next.x+next.width/2,next.y+next.height/2,next.width,next.height,{label:'Conversation collision surface',isStatic:true,restitution:.35,chamfer:{radius:Math.min(12,next.width/4,next.height/4)}});M.Composite.add(engine.world,chatWall);
    for(const pet of pets){
      const points=[pet.center,...pet.points],xs=points.map(p=>p.position.x),ys=points.map(p=>p.position.y);
      if(Math.max(...xs)+6<=next.x||Math.min(...xs)-6>=next.x+next.width||Math.max(...ys)+6<=next.y||Math.min(...ys)-6>=next.y+next.height)continue;
      const p=pet.center.position,pad=pet.r+15,targets=[];
      if(next.x+next.width+pad<=width-pad)targets.push({x:next.x+next.width+pad,y:clamp(p.y,pad,height*.955-pad)});
      if(next.y-pad>=pad)targets.push({x:clamp(p.x,pad,width-pad),y:next.y-pad});
      if(next.x-pad>=pad)targets.push({x:next.x-pad,y:clamp(p.y,pad,height*.955-pad)});
      targets.sort((a,b)=>Math.hypot(a.x-p.x,a.y-p.y)-Math.hypot(b.x-p.x,b.y-p.y));
      if(targets.length){M.Composite.translate(pet.composite,M.Vector.sub(targets[0],p));for(const b of points){M.Body.setVelocity(b,{x:0,y:0});M.Body.setAngularVelocity(b,0);}}
      wake(pet);
    }
    render();schedule();
  }
  function resize(){
    release();const before={width,height},box=room.getBoundingClientRect();width=Math.max(1,box.width);height=Math.max(1,box.height);const dpr=Math.min(devicePixelRatio||1,2);canvas.width=Math.ceil(width*dpr);canvas.height=Math.ceil(height*dpr);
    for(const w of walls)M.Composite.remove(engine.world,w);
    const r=obstacle?.getBoundingClientRect(),o=r&&r.width&&r.height?{x:r.left-box.left+r.width*.08,y:r.top-box.top+r.height*.05,width:r.width*.84,height:r.height*.885}:null;
    walls=bounds(M,engine.world,width,height,o);
    for(const pet of pets){const target={x:clamp(pet.center.position.x/before.width*width,pet.r+12,width-pet.r-12),y:clamp(pet.center.position.y/before.height*height,pet.r+12,height*.955-pet.r-12)};M.Composite.translate(pet.composite,M.Vector.sub(target,pet.center.position));wake(pet);}syncDialogueCollision();render();
  }
  function tick(time){frame=null;if(!allowed()||!pets.length){last=0;accumulator=0;return;}const elapsed=last?Math.min(time-last,50):STEP;last=time;accumulator+=elapsed;
    for(let steps=0;accumulator>=STEP&&steps<6;steps++){M.Engine.update(engine,STEP);accumulator-=STEP;}render();schedule();
  }
  function schedule(){if(frame===null&&allowed()&&pets.length)frame=requestAnimationFrame(tick);}
  function pause(){stopHold();if(frame!==null)cancelAnimationFrame(frame);frame=null;last=0;accumulator=0;release();}
  function refresh(){pause();render();schedule();}
  const resizeObserver=new ResizeObserver(resize);resizeObserver.observe(room);
  const dialogueSize=new ResizeObserver(()=>syncDialogueCollision());if(dialogue)dialogueSize.observe(dialogue);
  const dialogueVisibility=new MutationObserver(()=>syncDialogueCollision());if(dialogue)dialogueVisibility.observe(dialogue,{attributes:true,attributeFilter:['hidden']});
  if(stage)scope.listen(stage,'gernze:conversation-visibility',e=>syncDialogueCollision(e.detail.open));
  scope.listen(spawnButton,'pointerdown',event=>{
    if(event.button!==0||spawnButton.disabled||closed)return;stopHold();suppressHeldClick=false;holdPointer=event.pointerId;spawnButton.setPointerCapture?.(event.pointerId);
    holdDelay=setTimeout(()=>{holdDelay=null;if(holdPointer===null||closed||document.hidden||!active)return;suppressHeldClick=true;spawn();if(holdPointer!==null)holdRepeat=setInterval(()=>{if(closed||document.hidden||!active||pets.length>=MAX){stopHold();return;}spawn();},75);},320);
  });
  scope.listen(spawnButton,'click',event=>{if(suppressHeldClick&&event.detail!==0){suppressHeldClick=false;return;}suppressHeldClick=false;spawn();});
  for(const name of ['pointerup','pointercancel','lostpointercapture','pointerleave'])scope.listen(spawnButton,name,stopHold);
  scope.listen(document,'pointerup',stopHold);scope.listen(document,'pointercancel',stopHold);scope.listen(window,'blur',stopHold);
  scope.listen(spawnButton,'contextmenu',event=>event.preventDefault());
  scope.listen(clearButton,'click',clear);scope.listen(document,'visibilitychange',refresh);scope.listen(reduced,'change',refresh);
  scope.listen(window,'hebao:app-active',e=>{active=e.detail===true;refresh();});
  image.onload=()=>{if(closed)return;texture=document.createElement('canvas');const scale=Math.min(1,256/Math.max(image.naturalWidth,image.naturalHeight));texture.width=Math.max(1,Math.round(image.naturalWidth*scale));texture.height=Math.max(1,Math.round(image.naturalHeight*scale));texture.getContext('2d').drawImage(image,0,0,texture.width,texture.height);render();};image.onerror=()=>{spawnButton.disabled=true;spawnButton.textContent='小莉宝素材未加载';};
  const controller=Object.freeze({spawn,clear,state:()=>({count:pets.length,bodyCount:M.Composite.allBodies(engine.world).length,running:frame!==null,dragging:!!drag,width,height}),engine});
  room.GernzeJellyPhysics=controller;
  scope.own(()=>{closed=true;pause();resizeObserver.disconnect();dialogueSize.disconnect();dialogueVisibility.disconnect();clear();M.Composite.clear(engine.world,false);M.Engine.clear(engine);chatWall=chatRect=null;image.onload=image.onerror=null;texture=null;canvas.width=canvas.height=1;canvas.remove();toolbar.remove();if(room.GernzeJellyPhysics===controller)delete room.GernzeJellyPhysics;});
  resize();return controller;
}
root.GernzeSceneJelly=Object.freeze({mount,bindBrand,createSoftPet,bounds,drawPet});
})(window);
