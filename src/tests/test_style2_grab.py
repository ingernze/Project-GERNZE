import unittest,json,hashlib,tempfile,shutil
from pathlib import Path
from grab_sway import load_grab,select_native_pose,BodySpring
P=Path(__file__).resolve().parents[1]/'assets/styles/style2/grab'
class NativeGrabTests(unittest.TestCase):
    def test_23_distinct_intact_sources_and_per_pose_anchors(self):
        m,images,angles=load_grab(P,[128,128])
        self.assertEqual(len(images),23)
        self.assertEqual(len(set(e['source_sha256'] for e in m['poses'])),23)
        self.assertTrue(all(im.size==(1254,1254) for im in images.values()))
        self.assertEqual(m['physics']['max_angle'],35)
        self.assertEqual(angles['CENTER'],0)
        self.assertTrue(all(im.getpixel(tuple(e['grab_xy']))[3]>0 for e in m['poses'] for name,im in images.items() if name==e['pose']))
    def test_outbound_excludes_return_variants_and_uses_end_bridges(self):
        m,_,_=load_grab(P,[128,128])
        for e in m['poses']:
            if e['pose'].endswith('_RETURN'):continue
            a=e['normalized_swing_proxy']*35
            v=-1 if a<0 else 1
            self.assertEqual(select_native_pose(m,a,v),e['pose'])
    def test_left_return_uses_variant_own_coordinate(self):
        m,_,_=load_grab(P,[128,128])
        for e in m['poses']:
            if e['pose'].endswith('_RETURN'):
                self.assertEqual(select_native_pose(m,e['normalized_swing_proxy']*35,1),e['pose'])
        self.assertEqual(select_native_pose(m,0,100),'CENTER')
    def test_hysteresis_does_not_hold_wrong_side_at_reversal(self):
        m,_,_=load_grab(P,[128,128])
        self.assertEqual(select_native_pose(m,35,100,'L_END'),'R_END')
        self.assertEqual(select_native_pose(m,-35,-100,'R_END'),'L_END')
    def test_spring_lag_and_decay_no_idle_oscillation(self):
        m,_,_=load_grab(P,[128,128]);spring=BodySpring(m['physics']);spring.begin(0,1)
        for i in range(1,11):spring.move(i*24,1+i*.033)
        spring.update(1.363);self.assertLess(spring.angle,-6)
        samples=[]
        for i in range(1,161):spring.update(1.363+i*.025);samples.append(spring.angle)
        self.assertGreater(max(samples),1)
        self.assertLessEqual(max(map(abs,samples)),35)
        self.assertTrue(spring.quiet())
    def test_bad_native_path_and_hash_rejected(self):
        m=json.loads((P/'manifest.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as d:
            q=Path(d);shutil.copytree(P/'png',q/'png')
            for value in ('../escape.png','png/L_END.png'):
                broken=json.loads(json.dumps(m));broken['poses'][0]['source_path']=value;broken['poses'][0]['source_sha256']='0'*64
                (q/'manifest.json').write_text(json.dumps(broken),encoding='utf-8')
                with self.assertRaises(ValueError):load_grab(q,[128,128])
