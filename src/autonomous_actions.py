"""Sparse autonomous action timers. No queue polling or background animation."""
import json
import math
import random
import sys
import time
from pathlib import Path
import win32api
from activity_timing import SleepSchedule
from foot_sway import FootSwaySchedule


def _range(value, minimum, maximum, label):
    if (not isinstance(value,list) or len(value)!=2
            or any(type(v) is not int for v in value)
            or not minimum<=value[0]<=value[1]<=maximum):
        raise ValueError('Invalid '+label)
    return value


def load_behavior(path, walk_dir):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    walk=data['random_walk'];sleep=data['random_sleep'];selector=data['selector']
    validate_selector(selector)
    for item in (walk,sleep):
        if type(item['enabled']) is not bool:raise ValueError('Invalid behavior enabled flag')
    _range(walk['idle_wait_ms'],100,3600000,'walk wait')
    _range(walk['cycles'],1,10,'walk cycles')
    _range(sleep['wait_ms'],100,86400000,'sleep wait')
    _range(sleep['duration_ms'],100,3600000,'sleep duration')
    speed=walk['speed_pixels_per_second'];margin=walk['edge_margin_pixels']
    if type(speed) not in (int,float) or not 1<=speed<=200:raise ValueError('Invalid random walking speed')
    if type(margin) is not int or not 0<=margin<=100:raise ValueError('Invalid edge margin')
    manifest=json.loads((Path(walk_dir)/'manifest.json').read_text(encoding='utf-8'))
    loop_ms={}
    for direction in ('up','down','left','right'):
        action=manifest.get('directions',{}).get(direction)
        if action is None:continue
        times=[f['duration_ms'] for f in action['frames']]
        if not times or any(type(ms) is not int or not 30<=ms<=10000 for ms in times):
            raise ValueError('Invalid random walking frame duration')
        loop_ms[direction]=sum(times)
    return data,loop_ms


def validate_selector(selector):
    if type(selector['enabled']) is not bool:raise ValueError('Invalid selector switch')
    _range(selector['idle_wait_ms'],100,3600000,'selector wait')
    levels=selector['levels'];ids=set();actions=set()
    if not isinstance(levels,list) or not levels:raise ValueError('No action levels')
    for level in levels:
        identifier=level['id'];members=level['actions']
        if type(identifier) is not int or identifier<1 or identifier in ids:raise ValueError('Invalid level ID')
        if not isinstance(members,list) or not members or any(not isinstance(a,str) or not a for a in members):raise ValueError('Invalid level actions')
        if len(set(members))!=len(members) or actions.intersection(members):raise ValueError('Duplicate automatic action')
        ids.add(identifier);actions.update(members)
    for context in ('idle','busy'):
        policy=selector['contexts'][context]
        if type(policy['enabled']) is not bool:raise ValueError('Invalid context switch')
        weights=policy['level_weights']
        if weights is None and not policy['enabled']:continue
        if not isinstance(weights,dict) or set(weights)!={str(i) for i in ids}:raise ValueError('Missing level weight')
        if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in weights.values()):raise ValueError('Invalid level weight')
        if policy['enabled'] and sum(weights.values())<=0:raise ValueError('All level weights are zero')


def eligible_trips(origin,size,work,scale,walk,loop_ms):
    x,y=origin;left,top,right,bottom=work;margin=walk['edge_margin_pixels']*scale
    room={'left':x-left-margin,'right':right-size[0]-x-margin,
          'up':y-top-margin,'down':bottom-size[1]-y-margin}
    choices={}
    for direction,ms in loop_ms.items():
        stride=walk['speed_pixels_per_second']*scale*ms/1000
        maximum=min(walk['cycles'][1],math.floor(max(0,room[direction])/stride))
        if maximum>=walk['cycles'][0]:choices[direction]=maximum
    return choices


def choose_trip(origin,size,work,scale,walk,loop_ms,rng=random):
    choices=eligible_trips(origin,size,work,scale,walk,loop_ms)
    if not choices:return None
    direction=rng.choice(list(choices))
    return direction,rng.randint(walk['cycles'][0],choices[direction])


def choose_action(selector,eligible,context='idle',rng=random):
    """First draw an eligible category, then draw one of that category's actions.

    Level IDs identify categories, not priority or probability. Missing, disabled,
    cooling-down and blocked actions are removed before either draw.
    """
    policy=selector['contexts'].get(context)
    if not policy or not policy['enabled']:return None
    levels=[];members=[];weights=[]
    for level in selector['levels']:
        available=[name for name in level['actions'] if name in eligible]
        weight=policy['level_weights'].get(str(level['id']),0)
        if available and weight>0:
            levels.append(level);members.append(available);weights.append(weight)
    if not levels:return None
    index=rng.choices(range(len(levels)),weights=weights,k=1)[0]
    return levels[index]['id'],rng.choice(members[index])


class AutonomousActions:
    def __init__(self,pet,config_path,walk_dir):
        self.pet=pet;self.job=None;self.wake_job=None;self.sleep_due_at=None;self.sleep_armed=False
        self.disabled_actions=set()
        self.suspended=any('self-test' in flag or flag=='--benchmark' for flag in sys.argv)
        if '--random-actions-self-test' in sys.argv:self.suspended=False
        try:self.config,self.loop_ms=load_behavior(config_path,walk_dir)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.config={'selector':{'enabled':False},'random_walk':{'enabled':False},'random_reading':{'enabled':False},'random_sleep':{'enabled':False}};self.loop_ms={}
            pet.record_manual_event('autonomous_unavailable',reason=str(exc))

        # Sleep now has an independent daytime/nighttime schedule.
        self.config['random_sleep']['enabled']=False
        self.sleep=SleepSchedule(pet)
        self.sway=FootSwaySchedule(pet)

    def enabled(self):
        return not self.suspended and self.config['selector']['enabled']

    def available(self):
        pet=self.pet
        return (self.enabled() and not pet.closing and pet.visible and pet.drag_start is None
                and not pet.walk_trial.active and not pet.manual_action.active and pet.reading_index is None
                and not pet.coast.motion.frame.active
                and (pet.character_style!='style2' or pet.style2_motion=='rest'))

    def schedule(self):
        self.sleep.schedule()
        self.sway.schedule()
        if self.job is not None or not self.available():return
        now=time.monotonic();pet=self.pet
        if self.config['random_reading']['enabled'] and pet.reading_frames and pet.reading_due_at is None:
            pet.reading_due_at=now+random.randint(*pet.reading_wait)/1000
        sleep=self.config['random_sleep']
        if sleep['enabled'] and self.sleep_due_at is None:
            self.sleep_due_at=now+random.randint(*sleep['wait_ms'])/1000
        if not any(self.config[key]['enabled'] for key in ('random_walk','random_reading','random_sleep')):return
        wait=random.randint(*self.config['selector']['idle_wait_ms'])
        self.job=pet.root.after(wait,self._run)

    def eligible(self,now):
        pet=self.pet;root=pet.root;root.update_idletasks();trips={};actions=set()
        if self.config['random_walk']['enabled']:
            canvas=pet.manifest['canvas'];scale=pet.scale
            size=(canvas[0]*scale,canvas[1]*scale);origin=(root.winfo_x(),root.winfo_y())
            monitor=win32api.MonitorFromPoint((origin[0]+size[0]//2,origin[1]+size[1]//2),2)
            work=win32api.GetMonitorInfo(monitor)['Work']
            trips=eligible_trips(origin,size,work,scale,self.config['random_walk'],self.loop_ms)
            actions.update('walk_'+d for d in trips)
        if self.config['random_reading']['enabled'] and pet.reading_frames and pet.reading_due_at is not None and now>=pet.reading_due_at:
            actions.add('reading')
        if self.config['random_sleep']['enabled'] and self.sleep_due_at is not None and now>=self.sleep_due_at:
            if (pet.manual_action.asset_dir/'sleep'/'manifest.json').is_file():actions.add('sleep')
        return actions-self.disabled_actions,trips

    def _run(self):
        self.job=None
        if not self.available():return
        eligible,trips=self.eligible(time.monotonic())
        selected=choose_action(self.config['selector'],eligible)
        if selected:
            level,action=selected
            self.pet.record_manual_event('random_action_selected',level=level,action=action,context='idle',probability_status=self.config['selector']['probability_status'])
            if action=='reading':
                self.pet.reading_due_at=None
                started=self.pet.start_reading()
            elif action=='sleep':
                self.sleep_due_at=None
                started=self.pet.start_manual_action('sleep',automatic=True)
            elif action.startswith('walk_') and action[5:] in trips:
                direction=action[5:];walk=self.config['random_walk']
                cycles=random.randint(walk['cycles'][0],trips[direction])
                started=self.pet.start_walk(direction,automatic=True,cycles=cycles,speed=walk['speed_pixels_per_second'])
            else:started=False
            if not started:
                self.disabled_actions.add(action)
                self.pet.record_manual_event('random_action_skipped',level=level,action=action,reason='unavailable_until_restart')
        self.schedule()

    def sleep_holding(self):
        self.sleep.sleep_holding()

    def _wake(self):
        self.wake_job=None;action=self.pet.manual_action
        if self.pet.visible and not self.pet.closing and action.active and action.automatic:action.wake(automatic=True)

    def cancel_idle(self):
        self.sleep.cancel_idle()
        self.sway.cancel_idle()
        if self.job is not None:self.pet.root.after_cancel(self.job)
        self.job=None

    def cancel_wake(self):
        self.sleep.cancel_wake()
        if self.wake_job is not None:self.pet.root.after_cancel(self.wake_job)
        self.wake_job=None

    def cancel(self,*,reset_wait=False):
        self.sleep.cancel(reset_wait=reset_wait)
        self.sway.cancel_idle(reset_wait=reset_wait)
        self.cancel_idle();self.cancel_wake();self.sleep_armed=False
        if reset_wait:self.sleep_due_at=None
