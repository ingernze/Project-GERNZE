import unittest,tempfile,wave,array,hashlib
from pathlib import Path
from scene_voice import volume_wav,validate_volume

class VolumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.source=self.root/'original.wav';self.samples=[-32768,-30001,-3,-1,0,1,3,30001,32767]
        with wave.open(str(self.source),'wb') as w:w.setparams((1,2,32000,0,'NONE',''));w.writeframes(array.array('h',self.samples).tobytes())
        self.before=hashlib.sha256(self.source.read_bytes()).hexdigest()
    def read(self,f):
        with wave.open(str(f),'rb') as w:return w.getparams(),list(array.array('h',w.readframes(w.getnframes())))
    def test_50_halves_signed_samples_and_preserves_original(self):
        f=volume_wav(self.source,self.root/'cache',50);params,values=self.read(f)
        self.assertEqual(values,[round(x/2) for x in self.samples]);self.assertEqual(params,self.read(self.source)[0])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),self.before)
    def test_30_preserves_audio_and_scales_signed_samples(self):
        f=volume_wav(self.source,self.root/'cache',30);params,values=self.read(f)
        self.assertEqual(values,[round(x*.3) for x in self.samples]);self.assertEqual(params,self.read(self.source)[0])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),self.before)
    def test_100_plays_original_without_cache(self):
        self.assertEqual(volume_wav(self.source,self.root/'cache',100),self.source);self.assertFalse((self.root/'cache').exists())
    def test_0_silences_samples(self):self.assertEqual(self.read(volume_wav(self.source,self.root/'cache',0))[1],[0]*len(self.samples))
    def test_cache_reuse_and_gain_separation(self):
        a=volume_wav(self.source,self.root/'cache',50);stamp=a.stat().st_mtime_ns
        self.assertEqual(a,volume_wav(self.source,self.root/'cache',50));self.assertEqual(a.stat().st_mtime_ns,stamp)
        self.assertNotEqual(a,volume_wav(self.source,self.root/'cache',25));self.assertFalse(a.with_suffix('.tmp').exists())
    def test_invalid_gain_rejected(self):
        for n in [-1,101,True,None,'50',50.5]:
            with self.assertRaises(ValueError):validate_volume(n)
    def test_unsupported_audio_rejected(self):
        with wave.open(str(self.source),'wb') as w:w.setparams((1,1,32000,0,'NONE',''));w.writeframes(b'abc')
        with self.assertRaises(ValueError):volume_wav(self.source,self.root/'cache',50)
