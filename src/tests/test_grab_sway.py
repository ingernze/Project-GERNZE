import json
import tempfile
import unittest
from pathlib import Path
from grab_sway import BodySpring,load_grab
ROOT=Path(__file__).resolve().parent.parent

class GrabMotionTests(unittest.TestCase):
    def setUp(self):
        self.data,self.images,self.angles=load_grab(ROOT/'assets/grab',[128,128])
    def simulate(self,sign):
        motion=BodySpring(self.data['physics']);motion.begin(0,0);samples=[]
        for i in range(1,100):
            now=i/30;x=sign*min(i,10)*24
            if i<=10:motion.move(x,now)
            motion.update(now);samples.append(motion.angle)
        return motion,samples
    def test_right_drag_lags_left_and_rebounds_right_while_held(self):
        motion,samples=self.simulate(1)
        self.assertLess(min(samples[:11]),-6)
        self.assertGreater(max(samples[11:]),2.5)
        self.assertTrue(motion.quiet())
    def test_left_drag_is_symmetric(self):
        _,right=self.simulate(1);_,left=self.simulate(-1)
        self.assertTrue(all(abs(a+b)<1e-8 for a,b in zip(right,left)))
    def test_static_hold_has_no_spontaneous_motion(self):
        motion=BodySpring(self.data['physics']);motion.begin(5,100);motion.update(101)
        self.assertEqual(motion.angle,0);self.assertTrue(motion.quiet())
    def test_original_pngs_have_shared_solid_anchor(self):
        self.assertEqual(len(self.images),3)
        self.assertEqual(set(self.angles.values()),{-14,0,14})
        for im in self.images.values():self.assertEqual(im.getchannel('A').getpixel((64,16)),255)
        self.assertEqual(self.data['watch'],'baked_in_original_png_no_separate_layer')
    def test_missing_or_corrupt_resources_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);data=json.loads((ROOT/'assets/grab/manifest.json').read_text(encoding='utf-8'))
            data['frames'][0]['file']='../left.png'
            (path/'manifest.json').write_text(json.dumps(data))
            with self.assertRaises(ValueError):load_grab(path,[128,128])
    def test_long_suspension_stops_motion(self):
        motion=BodySpring(self.data['physics']);motion.begin(0,0);motion.move(200,0.1);motion.update(20)
        self.assertTrue(motion.quiet())

if __name__=='__main__':unittest.main()
