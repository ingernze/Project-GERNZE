import copy
import json
import tempfile
import unittest
from pathlib import Path
from walk_trial import bounded_position, load_action

ROOT=Path(__file__).resolve().parent.parent/'assets/walk'

class WalkingResources(unittest.TestCase):
    def test_all_four_latest_actions(self):
        expected={'right':'right_rework_candidate_v05','left':'left_F06_patch_v02','up':'up_v05','down':'down_v05'}
        for d, version in expected.items():
            frames,durations,boundaries,cycles,speed,action=load_action(ROOT,d,(128,128),(64,127))
            self.assertEqual((len(frames),sum(durations),cycles),(8,1120,3))
            self.assertEqual(action['version'],version)
    def test_absolute_negative_monitor_bounds(self):
        self.assertEqual(bounded_position((-1800,50),'left',9999,(-1920,0,0,1080),(256,256)),(-1920,50))
        self.assertEqual(bounded_position((-1800,50),'right',9999,(-1920,0,0,1080),(256,256)),(-256,50))
    def test_vertical_movement_does_not_change_x(self):
        self.assertEqual(bounded_position((200,200),'up',100,(0,0,900,700),(256,256)),(200,100))
        self.assertEqual(bounded_position((200,200),'down',100,(0,0,900,700),(256,256)),(200,300))
    def invalid(self, mutate, expected):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            data=json.loads((ROOT/'manifest.json').read_text())
            mutate(data)
            (root/'manifest.json').write_text(json.dumps(data))
            with self.assertRaises(expected):
                load_action(root,'up',(128,128),(64,127))
    def test_path_escape_rejected(self):
        self.invalid(lambda d:d['directions']['up']['frames'][0].update(file='../outside.png'),ValueError)
    def test_bad_duration_rejected_before_image_open(self):
        self.invalid(lambda d:d['directions']['up']['frames'][0].update(duration_ms=0),ValueError)
    def test_missing_direction_rejected(self):
        self.invalid(lambda d:d['directions'].pop('up'),KeyError)
    def test_bad_anchor_rejected(self):
        self.invalid(lambda d:d['directions']['up'].update(anchor=[64,128]),ValueError)

if __name__=='__main__':unittest.main()
