import json,unittest
from unittest.mock import patch
from types import SimpleNamespace
from tests.test_scene_voice import VoiceTests,Backend
from scene_voice import SceneVoice,fixed_voice_rows
import app

class BindingTests(VoiceTests):
    def test_override_and_disable_survive_reload(self):
        overrides={'drag':['held','welcome'],'wake_evening':[]}
        self.v.apply_bindings(overrides)
        fresh=SceneVoice(self.root,backend=Backend(),bindings=json.loads(json.dumps(overrides)))
        self.assertEqual(fresh.events['drag'],['held','welcome'])
        self.assertEqual(fresh.events['wake_evening'],[])
        self.assertEqual(fresh.events['reading_start'],['read'])
        self.assertEqual(fresh.events['held'],[])
    def test_invalid_choices_leave_runtime_unchanged(self):
        original=dict(self.v.events)
        for invalid in [[],{'unknown':[]},{'drag':['missing']},{'drag':'welcome'},{'drag':['welcome','welcome']},{'drag':[[]]}]:
            with self.assertRaises(ValueError):self.v.apply_bindings(invalid)
            self.assertEqual(self.v.events,original)
    def test_bad_saved_scene_ignored_independently(self):
        fresh=SceneVoice(self.root,backend=Backend(),bindings={'drag':['missing'],'sleep':[]})
        self.assertEqual(fresh.events['drag'],['drag'])
        self.assertEqual(fresh.events['sleep'],[])
        self.assertEqual(fresh.binding_overrides,{'sleep':[]})
    def test_explicit_held_selection_and_restore(self):
        self.v.apply_bindings({'drag':['held']})
        self.assertTrue(self.v.emit('drag'));self.assertEqual(self.v.current,'held')
        self.v.apply_bindings({});self.assertEqual(self.v.events['drag'],['drag'])
        self.assertEqual(self.v.events['held'],[])
    def test_selected_group_used_for_random_choice(self):
        calls=[]
        self.v.apply_bindings({'drag':['welcome','held']})
        self.v.choose=lambda ids:(calls.append(list(ids)),ids[-1])[1]
        self.assertTrue(self.v.emit('drag'));self.assertEqual(self.v.current,'held')
        self.assertEqual(calls,[['welcome','held']])
    def test_save_failure_keeps_previous_settings_and_runtime(self):
        old={'voice_volume_percent':30,'other_user_choice':42,'scene_voice_bindings':{}}
        pet=SimpleNamespace(closing=False,voice=self.v,settings=old,voice_controls=None)
        with patch.object(app,'save_settings',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):app.HecatePet.save_voice_bindings(pet,{'drag':[]})
        self.assertIs(pet.settings,old);self.assertEqual(self.v.events['drag'],['drag'])
    def test_save_preserves_unrelated_settings(self):
        pet=SimpleNamespace(closing=False,voice=self.v,settings={'voice_volume_percent':30,'other_user_choice':42},voice_controls=None)
        with patch.object(app,'save_settings') as saved,patch.object(app,'log'):
            app.HecatePet.save_voice_bindings(pet,{'drag':[]})
        self.assertEqual(saved.call_args.args[0]['other_user_choice'],42)
        self.assertEqual(pet.settings['voice_volume_percent'],30)
        self.assertEqual(self.v.events['drag'],[])
if __name__=='__main__':unittest.main()
