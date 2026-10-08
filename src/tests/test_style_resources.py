import unittest
from pathlib import Path
from PIL import Image
from style_resources import style_paths,decode_atlas
from walk_trial import load_action
import app
P=Path(__file__).resolve().parents[1]
class StyleResourcesTests(unittest.TestCase):
    def test_styles_use_separate_roots_and_no_missing_action_fallback(self):
        paths=style_paths(P,'style2')
        self.assertIsNone(paths['reading']);self.assertEqual(paths['grab'],paths['idle']/'grab')
        from manual_actions import load_manual_action
        manifest,frames=app.load_manifest(paths['idle'])
        data,images,phases=load_manual_action(paths['actions'],'sleep',frames[0][0],manifest['foot_anchor'])
        self.assertEqual(data['renderer'],'native_manual')
        self.assertEqual([len(phases[k]) for k in ('enter','loop','exit')],[20,24,19])
        self.assertEqual([sum(ms for _,ms in phases[k]) for k in ('enter','loop','exit')],[3360,2880,3120])
        self.assertEqual(images[phases['exit'][-1][0]].tobytes(),frames[0][0].tobytes())
        self.assertFalse((paths['actions']/'headpat/manifest.json').exists())
        self.assertNotEqual(paths['walk'],style_paths(P,'original')['walk'])
        with self.assertRaises(ValueError):style_paths(P,'unknown')
    def test_native_two_motion_sequences_keep_source_resolution_and_timing(self):
        base=style_paths(P,'style2')['idle']
        for folder,count,unique,ms in ((base,16,16,2000),(base/'foot_sway',18,10,2500)):
            manifest,frames=app.load_manifest(folder)
            self.assertEqual(len(frames),count)
            self.assertEqual(len({id(im) for im,duration in frames}),unique)
            self.assertEqual(sum(duration for im,duration in frames),ms)
            self.assertEqual(manifest['source_canvas'],[1254,1254])
            self.assertTrue(all(im.size==(1254,1254) and im.mode=='RGBA' for im,duration in frames))
        manifest,frames=app.load_manifest(base/'foot_sway')
        self.assertEqual([v['file'] for v in manifest['frames']],
            [f'F{i:02d}.png' for i in list(range(10,0,-1))+list(range(2,10))])
        self.assertEqual(manifest['source_foot_anchor'],[668,1227])
    def test_new_style_does_not_use_previous_style_walk_art(self):
        import json
        paths=style_paths(P,'style2')
        self.assertEqual(json.loads((paths['walk']/'manifest.json').read_text(encoding='utf-8'))['directions'],{})
        manifest,frames=app.load_manifest(paths['idle'])
        for direction in ('up','down','left','right'):
            with self.assertRaises(KeyError):load_action(paths['walk'],direction,manifest['canvas'],manifest['foot_anchor'])
    def test_invalid_and_empty_atlas_cells_rejected(self):
        source=Image.new('RGBA',(32,32),(0,0,0,0))
        for box in ([0,0,33,32],[-1,0,12,12],[2,2,2,9],[0,0,10,10]):
            with self.assertRaises(ValueError):decode_atlas(source,{'atlas_box':box},[128,128])
    def test_original_idle_and_actions_remain_loadable(self):
        from reading_action import load_reading_action
        from manual_actions import load_manual_action
        paths=style_paths(P,'original');manifest,frames=app.load_manifest(paths['idle'])
        self.assertTrue(load_reading_action(paths['reading'],frames[0][0])[1])
        for name in ('headpat','sleep'):
            self.assertTrue(load_manual_action(paths['actions'],name,frames[0][0],manifest['foot_anchor'])[1])

class ArtPreferenceTests(unittest.TestCase):
    def test_default_order_and_saved_choice(self):
        import tempfile,json
        from unittest.mock import patch
        from style_resources import STYLE_NAMES
        self.assertEqual(list(STYLE_NAMES),['style2','original'])
        with tempfile.TemporaryDirectory() as tmp:
            settings=Path(tmp)/'settings.json'
            with patch.object(app,'SETTINGS',settings):
                self.assertEqual(app.load_settings()['character_style'],'style2')
                settings.write_text(json.dumps({'character_style':'unknown'}),encoding='utf8')
                self.assertEqual(app.load_settings()['character_style'],'style2')
                settings.write_text(json.dumps({'character_style':'original'}),encoding='utf8')
                self.assertEqual(app.load_settings()['character_style'],'original')
