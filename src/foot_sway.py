"""Finite idle-only foot sway; validated native art and a sparse timer."""
import math
import random
import sys
import time
from activity_timing import random_wait_seconds

def sequence(folder, cycles):
    from app import load_manifest
    if type(cycles) is not int or not 1 <= cycles <= 3:
        raise ValueError('摆腿轮数必须在1～3之间。')
    manifest, loop = load_manifest(folder)
    transition, enter = load_manifest(folder / 'transitions')
    for key in ('canvas', 'foot_anchor', 'source_canvas', 'source_foot_anchor'):
        if manifest[key] != transition[key]: raise ValueError('Transition anchor differs')
    if len(loop)!=18 or sum(ms for im,ms in loop)!=2500: raise ValueError('Invalid sway loop')
    steps = transition['frames'] + manifest['frames'] * cycles
    frames = enter + loop * cycles
    landing = len(frames)
    steps += [{**manifest['frames'][0], 'duration_ms':240}]
    frames += [(loop[0][0],240)]
    for index,ms in ((3,180),(2,180),(1,220),(0,240)):
        steps.append({**transition['frames'][index], 'duration_ms':ms})
        frames.append((enter[index][0],ms))
    return {**manifest,'loop':False,'frames':steps},frames,landing

def photos_for(frames,size,resampling):
    from style_resources import make_photo
    cache={};photos=[]
    for image,ms in frames:
        key=id(image)
        if key not in cache:cache[key]=make_photo(image,size,resampling)
        photos.append(cache[key])
    return photos

class FootSwaySchedule:
    def __init__(self,pet,*,clock=time.monotonic,rng=None):
        self.pet=pet;self.clock=clock;self.rng=rng or random.Random()
        self.job=None;self.due=None;self.failed=False
        self.suspended=any('self-test' in x or x=='--benchmark' for x in sys.argv)
    def resource_available(self):
        p=self.pet
        return p.character_style=='style2' and (p.style_asset_paths['idle']/'foot_sway/transitions/manifest.json').is_file()
    def available(self):
        p=self.pet
        return (not self.suspended and not self.failed and p.settings['activity_timing']['foot_sway_enabled']
                and not p.closing and p.visible and p.drag_start is None
                and not p.walk_trial.active and not p.manual_action.active and p.reading_index is None
                and not p.coast.motion.frame.active and p.character_style=='style2'
                and p.style2_motion=='rest' and self.resource_available())
    def schedule(self):
        if self.job is not None or not self.available():return
        now=self.clock()
        if self.due is None or self.due<=now:
            self.due=now+random_wait_seconds(self.pet.settings['activity_timing']['foot_sway_mean_min'],self.rng)
        expected=self.due
        self.job=self.pet.root.after(max(1,math.ceil((expected-now)*1000)),lambda:self._run(expected))
    def _run(self,expected):
        self.job=None;self.due=None
        if not self.available():return
        if self.clock()-expected>60:self.schedule();return
        if not self.pet.set_style2_motion('foot_sway',automatic=True):
            self.failed=True
            self.pet.record_manual_event('scheduled_foot_sway_unavailable_until_restart')
    def cancel_idle(self,*,reset_wait=False):
        if self.job is not None:self.pet.root.after_cancel(self.job)
        self.job=None
        # Every interruption starts a fresh idle wait; never catch up later.
        self.due=None
