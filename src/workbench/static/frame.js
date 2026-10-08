/* Hebao workbench shell: owned navigation, page seat and contextual detail seat. */
(function (root) {
"use strict";
const {limits,bound,resolveLayout}=root.HebaoLayout;
function node(tag, cls) {const el=document.createElement(tag);el.className=cls;return el;}
class Frame {
  constructor(container) {
    this.scope=new root.HebaoRuntime.Scope();
    this.preferences={collapsed:false,mobileExpanded:false,navWidth:limits.nav,detailWidth:limits.detail,detailOpen:false};
    this.width=container.clientWidth;this.pending=null;this.gesture=null;
    this.root=node('div','workbench-shell');this.left=node('aside','navigation-seat');
    this.main=node('main','workspace-seat');this.right=node('aside','detail-seat');
    this.overlay=node('div','message-seat');this.shade=node('button','navigation-shade');
    this.shade.type='button';this.shade.setAttribute('aria-label','收起导航');
    this.right.setAttribute('aria-label','提示与详情');
    this.navGrip=this.addGrip('nav');this.detailGrip=this.addGrip('detail');
    this.root.append(this.left,this.main,this.right,this.overlay,this.shade,this.navGrip,this.detailGrip);
    container.append(this.root);
    this.scope.listen(this.shade,'click',()=>{this.preferences.mobileExpanded=false;this.paint();});
    this.scope.listen(this.root,'keydown',event=>{
      if(event.key==='Escape'&&this.preferences.mobileExpanded){
        event.preventDefault();this.preferences.mobileExpanded=false;this.paint();
        this.left.querySelector('.nav-toggle')?.focus();
      }
    });
    this.observer=new ResizeObserver(()=>this.requestPaint());this.observer.observe(container);
    this.scope.own(()=>this.observer.disconnect());
    this.scope.own(()=>this.finishGesture());
    this.scope.own(()=>{if(this.pending!==null)cancelAnimationFrame(this.pending);});
    this.paint();
  }
  requestPaint() {
    if(this.pending!==null||this.scope.closed)return;
    this.pending=requestAnimationFrame(()=>{this.pending=null;this.width=this.root.clientWidth;this.paint();});
  }
  addGrip(kind) {
    const grip=node('div','width-grip');grip.dataset.kind=kind;grip.tabIndex=0;
    grip.setAttribute('role','separator');grip.setAttribute('aria-orientation','vertical');
    grip.setAttribute('aria-label',kind==='nav'?'调整导航宽度':'调整详情宽度');
    const write=(value)=> {
      if(kind==='nav')this.preferences.navWidth=bound(value,limits.navMin,limits.navMax);
      else this.preferences.detailWidth=bound(value,limits.detailMin,limits.detailMax);
    };
    this.scope.listen(grip,'pointerdown',event=>{
      if(event.button!==0||this.gesture)return;
      event.preventDefault();grip.setPointerCapture(event.pointerId);
      this.gesture={grip,id:event.pointerId,start:event.clientX,width:kind==='nav'?this.preferences.navWidth:this.preferences.detailWidth,kind};
      this.root.classList.add('is-resizing');
    });
    const move=event=> {
      const current=this.gesture;
      if(!current||current.grip!==grip||event.pointerId!==current.id)return false;
      write(current.width+(event.clientX-current.start)*(kind==='nav'?1:-1));return true;
    };
    this.scope.listen(grip,'pointermove',event=>{if(move(event))this.requestPaint();});
    this.scope.listen(grip,'pointerup',event=>{if(move(event)){this.paint();this.finishGesture();}});
    for(const name of ['lostpointercapture','pointercancel'])this.scope.listen(grip,name,event=>{
      if(this.gesture?.id===event.pointerId)this.finishGesture();
    });
    this.scope.listen(grip,'keydown',event=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
      event.preventDefault();const value=kind==='nav'?this.preferences.navWidth:this.preferences.detailWidth;
      if(event.key==='Home')write(kind==='nav'?limits.navMin:limits.detailMin);
      else if(event.key==='End')write(kind==='nav'?limits.navMax:limits.detailMax);
      else write(value+(event.key==='ArrowRight'?12:-12)*(kind==='nav'?1:-1));
      this.paint();
    });
    return grip;
  }
  finishGesture() {
    const current=this.gesture;this.gesture=null;this.root.classList.remove('is-resizing');
    if(current&&current.grip.hasPointerCapture(current.id))current.grip.releasePointerCapture(current.id);
  }
  toggleSidebar() {
    if(this.width<limits.compactAt)this.preferences.mobileExpanded=!this.preferences.mobileExpanded;
    else this.preferences.collapsed=!this.preferences.collapsed;
    this.paint();
  }
  details(content) {
    this.preferences.detailOpen=true;this.preferences.mobileExpanded=false;this.right.replaceChildren(content);this.paint();
  }
  closeDetails() {this.preferences.detailOpen=false;this.right.replaceChildren();this.paint();}
  paint() {
    const view=resolveLayout(this.width,this.preferences);
    this.root.style.setProperty('--navigation-track',view.navTrack+'px');
    this.root.style.setProperty('--detail-track',view.detailTrack+'px');
    this.root.style.setProperty('--floating-navigation-width',view.nav+'px');
    this.root.style.setProperty('--navigation-width',(view.floating?view.nav:view.navTrack)+'px');
    this.root.style.setProperty('--detail-width',view.detailWidth+'px');
    this.left.classList.toggle('is-floating',view.floating);
    this.right.classList.toggle('is-overlay',view.overlay);this.right.hidden=!this.preferences.detailOpen;
    this.shade.classList.toggle('is-visible',view.floating);
    this.shade.tabIndex=view.floating?0:-1;
    this.shade.setAttribute('aria-hidden',String(!view.floating));
    this.navGrip.hidden=view.collapsed||view.small;this.navGrip.style.left=view.navTrack+'px';
    this.detailGrip.hidden=!view.detailTrack;this.detailGrip.style.left=(this.width-view.detailTrack)+'px';
    this.navGrip.setAttribute('aria-valuenow',String(view.nav));this.detailGrip.setAttribute('aria-valuenow',String(view.detailWidth));
    if(this.onLayout)this.onLayout(view.collapsed,view);
  }
  update() {this.paint();}
  dispose() {this.scope.dispose();this.root.remove();}
}
root.HebaoFrame=Frame;
})(window);
