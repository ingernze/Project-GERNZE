import copy
from datetime import datetime,timedelta
import json
import random
from types import SimpleNamespace as NS
import unittest

from activity_timing import DEFAULTS,validate_preferences,stored_preferences,in_sleep_window,next_window_boundary,random_wait_seconds,SleepSchedule,DesktopSettingsRequest

class Preferences(unittest.TestCase):
    def test_defaults_and_cross_midnight(self):
        p=validate_preferences(DEFAULTS)
        for h,m,expected in ((21,59,False),(22,0,True),(0,0,True),(7,59,True),(8,0,False),(12,0,False)):
            self.assertEqual(in_sleep_window(datetime(2026,10,7,h,m),p),expected)
        self.assertEqual(next_window_boundary(datetime(2026,10,7,22),p),datetime(2026,10,8,8))
    def test_non_crossing_window(self):
        p={**DEFAULTS,'sleep_window_start':'12:15','sleep_window_end':'15:30'}
        self.assertTrue(in_sleep_window(datetime(2026,10,7,12,15),p))
        self.assertFalse(in_sleep_window(datetime(2026,10,7,15,30),p))
        self.assertEqual(next_window_boundary(datetime(2026,10,7,16),p),datetime(2026,10,8,12,15))
    def test_invalid_input_cannot_mutate_preferences(self):
        for key,value in (('blink_min_s',True),('blink_min_s',0),('sleep_min_s',601),('sleep_window_start','24:00'),('sleep_window_end','22:00'),('sleep_day_mean_min',float('nan')),('sleep_enabled',1),('shell','run')):
            p={**DEFAULTS,key:value}
            with self.assertRaises(ValueError):validate_preferences(p)
        self.assertEqual(stored_preferences({'sleep_min_s':0}),DEFAULTS)
        self.assertEqual(stored_preferences(None),DEFAULTS)
        self.assertEqual(stored_preferences({'sleep_enabled':False})['sleep_enabled'],False)
    def test_distribution_is_random_with_selected_mean(self):
        for minutes in (10,120):
            rng=random.Random(18);waits=[random_wait_seconds(minutes,rng) for _ in range(20000)]
            self.assertTrue(all(x>=30 for x in waits))
            self.assertGreater(len(set(waits)),100)
            self.assertAlmostEqual(sum(waits)/len(waits)/(minutes*60),1,delta=.035)
    def test_expired_desktop_request_never_saves_later(self):
        request=DesktopSettingsRequest('behavior.set',{'settings':dict(DEFAULTS)})
        with self.assertRaises(OSError):request.wait(0)
        calls=[];request.execute(NS(apply_activity_settings=lambda v:calls.append(v)))
        self.assertEqual(calls,[])

class Root:
    def __init__(self):self.jobs={};self.seq=0
    def after(self,ms,fn):self.seq+=1;self.jobs[self.seq]=(ms,fn);return self.seq
    def after_cancel(self,job):self.jobs.pop(job,None)
    def fire(self,job):self.jobs.pop(job)[1]()

class MeanRandom:
    def expovariate(self,rate):return 1/rate
    def randint(self,a,b):return a

class Schedule(unittest.TestCase):
    def setUp(self):
        from pathlib import Path
        self.mono=[0.0];self.wall=[datetime(2026,10,7,12)];self.root=Root();self.events=[];self.wakes=[]
        self.pet=NS(settings={'activity_timing':dict(DEFAULTS)},root=self.root,closing=False,visible=True,drag_start=None,
                    walk_trial=NS(active=False),manual_action=NS(active=False,automatic=False,finish_requested=False,asset_dir=Path(__file__).resolve().parents[1]/'assets/styles/style2/actions',wake=lambda **k:self.wakes.append(k)),
                    reading_index=None,coast=NS(motion=NS(frame=NS(active=False))),character_style='style2',style2_motion='rest',
                    record_manual_event=lambda *a,**k:self.events.append((a,k)))
        self.pet.start_manual_action=self.start
        self.auto=SleepSchedule(self.pet,clock=lambda:self.mono[0],local_now=lambda:self.wall[0],rng=MeanRandom());self.auto.suspended=False
    def start(self,name,automatic):
        self.pet.manual_action.active=True;self.pet.manual_action.automatic=automatic;self.auto.cancel();return True
    def advance(self,s):self.mono[0]+=s;self.wall[0]+=timedelta(seconds=s)
    def test_day_night_wait_and_one_timer(self):
        self.auto.schedule();job=self.auto.job
        self.assertEqual(self.root.jobs[job][0],7200000)
        self.auto.schedule();self.assertEqual(self.auto.job,job);self.assertEqual(len(self.root.jobs),1)
        self.auto.cancel(reset_wait=True);self.wall[0]=datetime(2026,10,7,23)
        self.auto.schedule();self.assertEqual(self.root.jobs[self.auto.job][0],600000)
    def test_boundary_replaces_old_frequency(self):
        self.wall[0]=datetime(2026,10,7,21,59);self.auto.schedule();job=self.auto.job
        self.assertEqual(self.root.jobs[job][0],60000)
        self.advance(60);self.root.fire(job)
        self.assertFalse(self.pet.manual_action.active)
        self.assertEqual(self.root.jobs[self.auto.job][0],600000)
    def test_duration_starts_only_in_loop_and_wakes_naturally(self):
        self.auto.schedule();job=self.auto.job;self.advance(7200);self.root.fire(job)
        self.assertTrue(self.pet.manual_action.active);self.assertIsNone(self.auto.wake_job)
        self.auto.sleep_holding();wake=self.auto.wake_job
        self.assertEqual(self.root.jobs[wake][0],30000)
        self.auto.sleep_holding();self.assertEqual(self.auto.wake_job,wake)
        self.root.fire(wake);self.assertEqual(self.wakes,[{'automatic':True}])
    def test_hide_or_cancel_removes_all_jobs(self):
        self.auto.schedule();self.auto.cancel(reset_wait=True)
        self.assertEqual(self.root.jobs,{})
        self.pet.manual_action.automatic=True;self.auto.sleep_holding();self.auto.cancel(reset_wait=True)
        self.assertEqual(self.root.jobs,{});self.assertIsNone(self.auto.due);self.assertFalse(self.auto.armed)
    def test_busy_foot_and_disabled_never_schedule(self):
        for target,key,value in ((self.pet,'drag_start',(0,0)),(self.pet,'visible',False),(self.pet,'reading_index',0),(self.pet,'style2_motion','foot_sway'),(self.pet.walk_trial,'active',True),(self.pet.coast.motion.frame,'active',True)):
            old=getattr(target,key);setattr(target,key,value);self.auto.schedule();self.assertIsNone(self.auto.job);setattr(target,key,old)
        self.pet.settings['activity_timing']['sleep_enabled']=False;self.auto.schedule();self.assertIsNone(self.auto.job)
    def test_resume_does_not_catch_up(self):
        self.auto.schedule();job=self.auto.job;self.advance(7400);self.root.fire(job)
        self.assertFalse(self.pet.manual_action.active);self.assertIsNotNone(self.auto.job)
    def test_clock_change_rearms_without_sleep(self):
        self.auto.schedule();job=self.auto.job;self.advance(7200);self.wall[0]+=timedelta(hours=2);self.root.fire(job)
        self.assertFalse(self.pet.manual_action.active);self.assertIsNotNone(self.auto.job)
    def test_changing_future_options_keeps_current_wake(self):
        self.pet.manual_action.active=True;self.pet.manual_action.automatic=True;self.auto.sleep_holding();job=self.auto.wake_job
        self.pet.settings['activity_timing']['sleep_enabled']=False;self.auto.cancel_idle(reset_wait=True);self.auto.schedule()
        self.assertEqual(self.auto.wake_job,job);self.root.fire(job);self.assertTrue(self.wakes)

class HttpRoutes(unittest.TestCase):
    def test_finite_authenticated_settings_routes(self):
        import http.client,tempfile,threading
        from workbench.server import WorkbenchServer
        with tempfile.TemporaryDirectory() as folder:
            calls=[]
            def callback(c,p):calls.append((c,p));return {'available':True}
            s=WorkbenchServer(folder,behavior_call=callback);worker=threading.Thread(target=s.serve,daemon=True);worker.start()
            def call(c,p,auth=True,origin=None):
                conn=http.client.HTTPConnection('127.0.0.1',s.server_port,timeout=3)
                headers={'Content-Type':'application/json','Origin':origin or s.origin}
                if auth:headers['Authorization']='Bearer '+s.token
                try:
                    conn.request('POST','/api/call',json.dumps({'command':c,'params':p}),headers)
                    r=conn.getresponse();body=json.loads(r.read());return r.status,body
                finally:conn.close()
            try:
                self.assertEqual(call('behavior.get',{})[0],200)
                self.assertEqual(call('behavior.set',{'settings':dict(DEFAULTS)})[0],200)
                count=len(calls)
                self.assertEqual(call('behavior.set',{'settings':{**DEFAULTS,'sleep_min_s':0}})[0],400)
                self.assertEqual(call('behavior.get',{},auth=False)[0],403)
                self.assertEqual(call('behavior.get',{},origin='https://example.invalid')[0],403)
                self.assertEqual(call('behavior.run',{})[0],400)
                self.assertEqual(len(calls),count)
            finally:s.stop();worker.join(9);s.server_close()

if __name__=='__main__':unittest.main()
