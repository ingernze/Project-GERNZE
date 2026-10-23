import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from reading_action import load_reading_action

PROJECT=Path(__file__).resolve().parent.parent
ROOT=PROJECT/'assets/pixel/libao/reading'

class ReadingManifestChecks(unittest.TestCase):
    def setUp(self):
        self.idle=Image.open(PROJECT/'assets/pixel/libao/idle/frame_00.png').convert('RGBA')
    def test_loading_phase_contract(self):
        resource,frames,wait,duration=load_reading_action(ROOT,self.idle)
        self.assertEqual(len(frames),11)
        self.assertEqual(resource['hold_index'],6)
        self.assertEqual(sum(ms for _,ms in resource['phases']['enter']),740)
        self.assertEqual(sum(ms for _,ms in resource['phases']['exit']),740)
        self.assertEqual(resource['phases']['glance'],[(8,180),(9,450),(10,700),(9,120),(8,200)])
        self.assertEqual((wait,duration),([120000,300000],[120000,240000]))
    def invalid(self,change,expected):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'reading';shutil.copytree(ROOT,root)
            f=root/'manifest.json';data=json.loads(f.read_text(encoding='utf-8'));change(data)
            f.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaises(expected):load_reading_action(root,self.idle)
    def test_path_escape_rejected(self):
        self.invalid(lambda d:d['frames'][0].update(file='../outside.png'),ValueError)
    def test_zero_duration_rejected(self):
        self.invalid(lambda d:d['phases']['enter'][0].update(duration_ms=0),ValueError)
    def test_missing_phase_rejected(self):
        self.invalid(lambda d:d['phases'].pop('exit'),KeyError)
    def test_wrong_idle_endpoint_rejected(self):
        self.invalid(lambda d:d['phases']['exit'][-1].update(file='v05/04_read.png'),ValueError)
    def test_invalid_minute_range_rejected(self):
        self.invalid(lambda d:d.update(idle_wait_ms=[300000,120000]),ValueError)

if __name__=='__main__':unittest.main()
