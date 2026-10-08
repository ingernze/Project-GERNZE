import unittest,tempfile,sys,json,hashlib,zipfile,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from optional_modules import OptionalModules,safe_name
from workbench.bridge import Bridge
class Packages(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.resources=self.root/'host';self.resources.mkdir();self.data=self.root/'data'
        payload={'cet6':{'python/hebao_modules/placeholder.txt':b'learning'},'fixed_voice':{'voice/manifest.json':b'{}'},'voice_engine':{'catalog.json':b'{"defaults":{}}','voice_backend.py':b'# code'}}
        catalog={'schema_version':1,'modules':{}}
        self.packages={}
        for identity,files in payload.items():
            catalog['modules'][identity]={'version':'v1','bytes':sum(map(len,files.values())),'files':{n:{'size':len(b),'sha256':hashlib.sha256(b).hexdigest()} for n,b in files.items()}}
            zpath=self.root/(identity+'.zip');self.packages[identity]=zpath
            with zipfile.ZipFile(zpath,'w') as z:
                z.writestr('module.json',json.dumps({'schema_version':1,'id':identity,'version':'v1'}))
                for n,b in files.items():z.writestr('payload/'+n,b)
        (self.resources/'module_catalog.json').write_text(json.dumps(catalog))
        self.manager=OptionalModules(self.resources,self.data,install_root=self.root/'installed')
    def tearDown(self):self.tmp.cleanup()
    def modified(self,identity,transform):
        p=self.root/'invalid.zip'
        with zipfile.ZipFile(self.packages[identity]) as source,zipfile.ZipFile(p,'w') as target:
            items={n:source.read(n) for n in source.namelist()};transform(items)
            for n,b in items.items():target.writestr(n,b)
        return p
    def test_empty_host_denies_learning_and_keeps_records(self):
        bridge=Bridge(self.data,modules=self.manager)
        bridge.memory.add(kind='project_log',title='personal',body='keep me',decision='candidate',source='user',memory_confirmed=False)
        self.assertEqual(bridge.call({'command':'state.summary','params':{}})['lessons'],[])
        with self.assertRaises(ValueError):bridge.call({'command':'daily.workspace','params':{}})
        self.assertEqual(len(bridge.memory.records()),1)
    def test_install_remove_reinstall(self):
        for key,p in self.packages.items():
            self.assertFalse(self.manager.installed(key));self.manager.install(p);self.assertTrue(self.manager.installed(key));self.manager.uninstall(key);self.assertFalse(self.manager.installed(key));self.manager.install(p);self.assertTrue(self.manager.installed(key))
    def test_voice_user_files_retained_and_restored(self):
        self.manager.install(self.packages['voice_engine']);folder=self.manager.folder('voice_engine')
        for name in ('models/user.pth','references/user.wav','state/settings.json'):
            p=folder/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'personal')
        (folder/'catalog.json').write_bytes(b'{"custom":true}')
        self.manager.uninstall('voice_engine');self.assertFalse(folder.exists())
        self.manager.install(self.packages['voice_engine'])
        self.assertEqual((folder/'models/user.pth').read_bytes(),b'personal');self.assertEqual((folder/'catalog.json').read_bytes(),b'{"custom":true}')
    def test_tampered_same_size_cannot_replace_existing(self):
        self.manager.install(self.packages['fixed_voice']);original=self.manager.folder('fixed_voice')/'voice/manifest.json'
        bad=self.modified('fixed_voice',lambda items:items.update({'payload/voice/manifest.json':b'[]'}))
        with self.assertRaises(ValueError):self.manager.install(bad)
        self.assertEqual(original.read_bytes(),b'{}');self.assertTrue(self.manager.installed('fixed_voice'))
    def test_extra_file_rejected(self):
        bad=self.modified('cet6',lambda d:d.update({'payload/code.py':b'unknown'}))
        with self.assertRaises(ValueError):self.manager.install(bad)
    def test_traversal_rejected(self):
        bad=self.modified('cet6',lambda d:d.update({'payload/../../outside':b'bad'}))
        with self.assertRaises(ValueError):self.manager.install(bad)
        self.assertFalse((self.root/'outside').exists())
    def test_case_collision_rejected(self):
        bad=self.modified('fixed_voice',lambda d:d.update({'Payload/VOICE/manifest.json':b'{}'}))
        with self.assertRaises(ValueError):self.manager.install(bad)
    def test_wrong_version_rejected(self):
        bad=self.modified('cet6',lambda d:d.update({'module.json':b'{"schema_version":1,"id":"cet6","version":"v2"}'}))
        with self.assertRaises(ValueError):self.manager.install(bad)
    def test_modified_code_preserved_but_not_restored(self):
        self.manager.install(self.packages['voice_engine']);folder=self.manager.folder('voice_engine');(folder/'voice_backend.py').write_bytes(b'changed')
        self.manager.uninstall('voice_engine');self.manager.install(self.packages['voice_engine'])
        self.assertEqual((folder/'voice_backend.py').read_bytes(),b'# code');self.assertEqual((self.manager.retained/'voice_engine/voice_backend.py').read_bytes(),b'changed')
    def test_reserved_windows_paths(self):
        for name in ('CON.txt','a/../b','a\\b','C:/bad','a./b','a/NUL','a//b'):
            with self.subTest(name=name),self.assertRaises(ValueError):safe_name(name)
    def test_legacy_mode_does_not_remove_resources(self):
        (self.resources/'module_catalog.json').unlink();legacy=OptionalModules(self.resources,self.data)
        self.assertTrue(legacy.installed('cet6'))
        with self.assertRaises(ValueError):legacy.uninstall('cet6')
if __name__=='__main__':unittest.main(verbosity=2)
