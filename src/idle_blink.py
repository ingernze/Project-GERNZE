"""Optional blink on a single breathing cycle; normal idle stays eyes-open."""
import random,time
from style_resources import make_photo

class BlinkLottery:
    def __init__(self,clock=time.monotonic,rng=None):
        self.clock=clock;self.rng=rng or random.Random();self.interval=(3,5);self.reset()
    def configure(self,minimum,maximum):
        self.interval=(minimum,maximum);self.reset()
    def reset(self):
        # Blink art shares a fixed phase of the 2s breathing loop. Two loops
        # between starts keeps breathing continuous and falls within 3-5s.
        import math
        # Match the already approved breathing art, without retiming frames.
        low=math.ceil(self.interval[0]/2);high=math.floor(self.interval[1]/2)
        if low<=high:
            cycles=max(low,min(high,round(self.rng.uniform(*self.interval)/2)))
        else:
            cycles=max(1,round(sum(self.interval)/4))
        self.due=self.clock()+max(1,cycles)*2
    def draw(self):
        if self.clock()<self.due:return False
        self.reset()
        return True

class IdleBlink:
    def __init__(self,pet):
        self.pet=pet;self.lottery=BlinkLottery();self.active=False
        prefs=pet.settings['activity_timing'];self.lottery.configure(prefs['blink_min_s'],prefs['blink_max_s'])
        self.blink_frames=[];self.blink_manifest=None;self.blink_photos={}
        self.base_frames=None;self.base_manifest=None;self.base_photos=None
        self.bind()
    def bind(self):
        import app
        self.active=False;self.lottery.reset()
        self.base_frames=self.pet.frames;self.base_manifest=self.pet.manifest;self.base_photos=self.pet.photos
        if self.pet.character_style!='style2' or self.pet.style2_motion!='rest':return
        if self.blink_manifest is None:
            try:
                m,frames=app.load_manifest(self.pet.style_asset_paths['idle']/'blink')
                if m.get('motion')!='rest_blink' or m['canvas']!=self.base_manifest['canvas'] or m['source_canvas']!=self.base_manifest['source_canvas'] or m['foot_anchor']!=self.base_manifest['foot_anchor'] or m['source_foot_anchor']!=self.base_manifest['source_foot_anchor'] or sum(ms for im,ms in frames)!=2000:
                    raise ValueError('Blink must share original canvas, anchors and breathing duration')
                base={e['file']:im for e,(im,ms) in zip(self.base_manifest['frames'],self.base_frames)}
                # Reuse unchanged native art rather than keep duplicate full-size bitmaps.
                self.blink_frames=[(base[e['source']] if e.get('eye_state')=='open' else im,ms) for e,(im,ms) in zip(m['frames'],frames)]
                self.blink_manifest=m
            except (OSError,ValueError,KeyError,TypeError,AssertionError) as exc:
                app.log('idle_blink_unavailable',reason=str(exc))
    def eligible(self):
        p=self.pet
        return (p.settings['activity_timing']['blink_enabled'] and p.character_style=='style2' and p.style2_motion=='rest' and p.visible and not p.closing and p.drag_start is None and p.reading_index is None and not p.manual_action.active and not p.walk_trial.active and not p.coast.motion.frame.active and self.blink_manifest is not None)
    def on_cycle_boundary(self):
        import app
        if self.active:
            self.cancel(reset_wait=False);app.log('idle_blink_finished');return
        if not self.eligible() or not self.lottery.draw():return
        p=self.pet
        if p.scale not in self.blink_photos:
            self.blink_photos[p.scale]=[make_photo(im,(128*p.scale,128*p.scale),p.style_resampling) for im,ms in self.blink_frames]
        self.base_frames=p.frames;self.base_manifest=p.manifest;self.base_photos=p.photos
        p.frames=self.blink_frames;p.manifest=self.blink_manifest;p.photos=self.blink_photos;p.frame_index=0
        self.active=True;app.log('idle_blink_started',steps=len(p.frames),visible_blink_ms=250)
    def cancel(self, *, reset_wait=True):
        p=self.pet
        if self.active:
            entry=self.blink_manifest['frames'][p.frame_index]
            source=entry.get('source','F00.png')
            index=next((i for i,e in enumerate(self.base_manifest['frames']) if e['file']==source),0)
            p.frames=self.base_frames;p.manifest=self.base_manifest;p.photos=self.base_photos;p.frame_index=index
            p._prepare_photos();p.label.configure(image=p.photos[p.scale][index])
        self.active=False
        if reset_wait:self.lottery.reset()
