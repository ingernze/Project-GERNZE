import copy
import json
import random
import tempfile
import unittest
from pathlib import Path
from autonomous_actions import choose_trip,load_behavior,choose_action

ROOT=Path(__file__).resolve().parent.parent

class AutonomousBoundaries(unittest.TestCase):
    def setUp(self):
        self.config,self.loops=load_behavior(ROOT/'behavior_config.json',ROOT/'assets/walk')
        self.walk=self.config['random_walk']
    def test_production_timing_and_art_loop(self):
        self.assertEqual(self.walk['idle_wait_ms'],[20000,45000])
        self.assertEqual(self.walk['cycles'],[1,3])
        self.assertEqual(set(self.loops.values()),{1120})
        self.assertEqual(self.config['random_sleep']['duration_ms'],[120000,240000])
    def test_all_directions_reachable_without_leaving_work_area(self):
        seen=set()
        for seed in range(100):
            direction,cycles=choose_trip((700,350),(256,256),(0,0,1920,1080),2,self.walk,self.loops,random.Random(seed))
            seen.add(direction)
            self.assertTrue(1<=cycles<=3)
        self.assertEqual(seen,{'left','right','up','down'})
    def test_corner_never_walks_outward(self):
        for seed in range(30):
            direction,cycles=choose_trip((0,0),(256,256),(0,0,1920,1080),2,self.walk,self.loops,random.Random(seed))
            self.assertIn(direction,('right','down'))
    def test_negative_monitor_coordinates(self):
        for seed in range(30):
            direction,_=choose_trip((-1920,-1080),(256,256),(-1920,-1080,0,0),2,self.walk,self.loops,random.Random(seed))
            self.assertIn(direction,('right','down'))
    def test_short_distance_limits_cycle_count(self):
        # Only right has 70 pixels of spare distance: one 53.76-pixel loop fits.
        for seed in range(30):
            self.assertEqual(choose_trip((0,0),(256,256),(0,0,342,256),2,self.walk,self.loops,random.Random(seed)),('right',1))
    def test_no_space_means_stay_idle(self):
        self.assertIsNone(choose_trip((0,0),(256,256),(0,0,256,256),2,self.walk,self.loops))
    def test_missing_direction_is_not_selected(self):
        for seed in range(10):
            self.assertEqual(choose_trip((200,200),(256,256),(0,0,1000,800),2,self.walk,{'up':1120},random.Random(seed))[0],'up')
    def test_invalid_configuration_rejected(self):
        for key,value in [('idle_wait_ms',[0,45]),('cycles',[3,1]),('speed_pixels_per_second',float('nan')),('enabled','yes')]:
            config=copy.deepcopy(self.config);config['random_walk'][key]=value
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'behavior.json';path.write_text(json.dumps(config))
                with self.assertRaises(ValueError):load_behavior(path,ROOT/'assets/walk')

class LevelSelection(unittest.TestCase):
    def setUp(self):
        self.config,_=load_behavior(ROOT/'behavior_config.json',ROOT/'assets/walk')
        self.selector=self.config['selector']
        self.actions={a for level in self.selector['levels'] for a in level['actions']}
    def test_all_levels_and_actions_reachable(self):
        result=[choose_action(self.selector,self.actions,rng=random.Random(seed)) for seed in range(1200)]
        self.assertEqual({level for level,action in result},{1,2,3})
        self.assertEqual({action for level,action in result},self.actions)
        counts={level:sum(i==level for i,a in result) for level in (1,2,3)}
        # Four walking directions must not make walking four times as likely as reading.
        self.assertTrue(all(320<value<480 for value in counts.values()),counts)
    def test_category_draw_precedes_specific_action_draw(self):
        class RecordingRandom:
            def choices(self,values,weights,k):
                self.weights=weights;return [0]
            def choice(self,members):
                self.members=members;return members[-1]
        rng=RecordingRandom();level,action=choose_action(self.selector,self.actions,rng=rng)
        self.assertEqual(rng.weights,[1,1,1])
        self.assertEqual(len(rng.members),4)
        self.assertEqual((level,action),(1,'walk_right'))
    def test_busy_context_pending_not_drawn(self):
        self.assertIsNone(choose_action(self.selector,self.actions,'busy'))
        self.assertIsNone(self.selector['contexts']['busy']['level_weights'])
        self.assertEqual(self.selector['probability_status'],'temporary_preview_pending_user_decision')
    def test_only_eligible_actions_are_drawn(self):
        for seed in range(50):
            self.assertEqual(choose_action(self.selector,{'walk_left'},rng=random.Random(seed)),(1,'walk_left'))
        self.assertIsNone(choose_action(self.selector,set()))
    def test_zero_weight_disables_level_not_reassigns_id(self):
        self.selector['contexts']['idle']['level_weights']={'1':0,'2':1,'3':0}
        for seed in range(10):self.assertEqual(choose_action(self.selector,self.actions,rng=random.Random(seed)),(2,'reading'))
    def test_level_id_is_not_weight(self):
        self.selector['levels'][0]['id']=99
        self.selector['contexts']['idle']['level_weights']={'99':1,'2':0,'3':0}
        self.assertEqual(choose_action(self.selector,{'walk_up'}),(99,'walk_up'))
    def test_invalid_weights_and_duplicate_levels_rejected(self):
        for change in ('negative','nan','duplicate','missing','allzero'):
            config=copy.deepcopy(self.config);selector=config['selector']
            if change=='duplicate':selector['levels'][1]['id']=1
            else:
                weights=selector['contexts']['idle']['level_weights']
                if change=='negative':weights['1']=-1
                if change=='nan':weights['1']=float('nan')
                if change=='missing':del weights['1']
                if change=='allzero':weights.update({'1':0,'2':0,'3':0})
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'behavior.json';path.write_text(json.dumps(config))
                with self.assertRaises(ValueError):load_behavior(path,ROOT/'assets/walk')

if __name__=='__main__':unittest.main()
