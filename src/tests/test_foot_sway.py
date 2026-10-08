import unittest,random
from pathlib import Path
from types import SimpleNamespace as NS
from foot_sway import sequence,FootSwaySchedule
from activity_timing import DEFAULTS,validate_preferences,stored_preferences
from tests.test_activity_timing import Root,MeanRandom

class FootSwayTests(unittest.TestCase):
    def test_complete_cycles_once_only_transitions_and_landing(self):
        folder=Path(__file__).resolve().parents[1]/'assets/styles/style2/foot_sway'
        for cycles in (1,2,3):
            m,frames,landing=sequence(folder,cycles);files=[f['file'] for f in m['frames']]
            self.assertEqual(files[:4],['B01.png','T01.png','T02.png','B04.png'])
            self.assertEqual(files[-4:],['B04.png','T02.png','T01.png','B01.png'])
            self.assertEqual(files.count('F01.png'),cycles)
            self.assertEqual(files[landing],'F10.png')
            self.assertEqual(len(frames),18*cycles+9)
            self.assertEqual(sum(ms for im,ms in frames),1760+2500*cycles)
            self.assertEqual(len({id(im) for im,ms in frames}),14)
            self.assertFalse(m['loop'])
        for value in (0,4,True):
            with self.assertRaises(ValueError):sequence(folder,value)
    def test_settings_migration_and_invalid_ranges(self):
        self.assertEqual(stored_preferences({'blink_min_s':7,'blink_max_s':9})['blink_min_s'],7)
        for patch in ({'foot_sway_min_cycles':3,'foot_sway_max_cycles':2},{'foot_sway_max_cycles':4},{'foot_sway_mean_min':0},{'foot_sway_enabled':1}):
            with self.assertRaises(ValueError):validate_preferences({**DEFAULTS,**patch})
    def test_only_idle_can_trigger_and_no_missed_events(self):
        now=[0];root=Root();calls=[]
        pet=NS(settings={'activity_timing':dict(DEFAULTS)},root=root,closing=False,visible=True,drag_start=None,
            walk_trial=NS(active=False),manual_action=NS(active=False),reading_index=None,
            coast=NS(motion=NS(frame=NS(active=False))),character_style='style2',style2_motion='rest',
            style_asset_paths={'idle':Path(__file__).resolve().parents[1]/'assets/styles/style2'},
            set_style2_motion=lambda *a,**k:calls.append((a,k)) or True)
        auto=FootSwaySchedule(pet,clock=lambda:now[0],rng=MeanRandom());auto.suspended=False
        for target,key,value in ((pet,'visible',False),(pet,'drag_start',(0,0)),(pet,'reading_index',0),(pet,'style2_motion','foot_sway'),(pet.walk_trial,'active',True),(pet.manual_action,'active',True),(pet.coast.motion.frame,'active',True),(pet,'character_style','original')):
            old=getattr(target,key);setattr(target,key,value);auto.schedule();self.assertIsNone(auto.job);setattr(target,key,old)
        auto.schedule();job=auto.job;auto.schedule();self.assertEqual(auto.job,job)
        self.assertEqual(root.jobs[job][0],1200000)
        now[0]=1300;root.fire(job);self.assertEqual(calls,[]);self.assertIsNotNone(auto.job)
        auto.cancel_idle();self.assertEqual(root.jobs,{})
        auto.schedule();job=auto.job;now[0]+=1200;root.fire(job)
        self.assertEqual(calls,[(('foot_sway',),{'automatic':True})])
