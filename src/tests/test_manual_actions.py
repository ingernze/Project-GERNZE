import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from manual_actions import load_manual_action

ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT/'assets'/'pixel'/'libao'/'actions'
idle_manifest=json.loads((ROOT/'assets'/'pixel'/'libao'/'idle'/'manifest.json').read_text(encoding='utf-8'))
IDLE=Image.open(ROOT/'assets'/'pixel'/'libao'/'idle'/idle_manifest['frames'][0]['file']).convert('RGBA')

class ManualAssetsTest(unittest.TestCase):
    def test_sleep_sequence_and_seams(self):
        data,frames,phases=load_manual_action(ASSETS,'sleep',IDLE,[64,127])
        self.assertEqual([len(phases[k]) for k in ('enter','loop','exit')],[8,8,8])
        self.assertEqual([sum(ms for _,ms in phases[k]) for k in ('enter','loop','exit')],[2400,4200,2420])
        self.assertEqual(data['trigger'],'manual_only')
        self.assertEqual(len(frames),24)
    def test_headpat_body_and_single_response(self):
        data,frames,phases=load_manual_action(ASSETS,'headpat',IDLE,[64,127])
        self.assertEqual(len(frames),9)
        self.assertEqual(sum(ms for _,ms in phases['play']),1160)
        self.assertEqual([ms for _,ms in phases['play'] if ms==0],[0,0])
        body=IDLE.crop((0,75,128,128)).tobytes()
        self.assertTrue(all(im.crop((0,75,128,128)).tobytes()==body for im in frames))
    def bad_manifest(self,modify):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            shutil.copytree(ASSETS/'sleep',root/'sleep')
            path=root/'sleep'/'manifest.json'
            data=json.loads(path.read_text(encoding='utf-8'));modify(data)
            path.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaises((ValueError,KeyError)):
                load_manual_action(root,'sleep',IDLE,[64,127])
    def test_reject_different_anchor(self):
        self.bad_manifest(lambda d:d.update(anchor=[64,126]))
    def test_reject_zero_loop_duration(self):
        self.bad_manifest(lambda d:d['phases']['loop'][0].update(duration_ms=0))
    def test_reject_path_escape(self):
        self.bad_manifest(lambda d:d['frames'][0].update(file='../outside.png'))
    def test_reject_corruption(self):
        self.bad_manifest(lambda d:d['frames'][0].update(sha256='0'*64))
    def test_reject_duplicate_frames(self):
        self.bad_manifest(lambda d:d['frames'].append(copy.deepcopy(d['frames'][0])))
    def test_missing_action(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileNotFoundError):
                load_manual_action(temp,'sleep',IDLE,[64,127])

if __name__=='__main__':unittest.main()
