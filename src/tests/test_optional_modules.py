import unittest,tempfile,sys,json,hashlib,zipfile,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from optional_modules import OptionalModules,safe_name
from workbench.bridge import Bridge
class Packages(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.resources=self.root/'host';self.resources.mkdir();self.data=self.root/'data'
        payload={'cet6':{'python/libao_modules/placeholder.txt':b'learning'},'voice_engine':{'catalog.json':b'{"defaults":{}}','voice_backend.py':b'# code'}}
        catalog={'schema_version':1,'modules':{}}
        self.packages={}
        for identity,files in payload.items():
            catalog['modules'][identity]={'version':'v1','bytes':sum(map(len,files.values())),'files':{n:{'size':len(b),'sha256':hashlib.sha256(b).hexdigest()} for n,b in files.items()}}
            zpath=self.root/(identity+'.zip');self.packages[identity]=zpath
            with zipfile.ZipFile(zpath,'w') as z:
                z.writestr('module.json',json.dumps({'schema_version':1,'id':identity,'version':'v1'}))
                for n,b in files.items():z.writestr('payload/'+n,b)
        (self.resources/'module_catalog.json').write_text(json.dumps(catalog))
        core=self.resources/'assets/voice';core.mkdir(parents=True);(core/'manifest.json').write_text('{}')
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
        self.manager.install(self.packages['voice_engine']);original=self.manager.folder('voice_engine')/'voice_backend.py'
        bad=self.modified('voice_engine',lambda items:items.update({'payload/voice_backend.py':b'# evil'}))
        with self.assertRaises(ValueError):self.manager.install(bad)
        self.assertEqual(original.read_bytes(),b'# code');self.assertTrue(self.manager.installed('voice_engine'))
    def test_extra_file_rejected(self):
        bad=self.modified('cet6',lambda d:d.update({'payload/code.py':b'unknown'}))
        with self.assertRaises(ValueError):self.manager.install(bad)
    def test_traversal_rejected(self):
        bad=self.modified('cet6',lambda d:d.update({'payload/../../outside':b'bad'}))
        with self.assertRaises(ValueError):self.manager.install(bad)
        self.assertFalse((self.root/'outside').exists())
    def test_case_collision_rejected(self):
        bad=self.modified('voice_engine',lambda d:d.update({'Payload/VOICE_BACKEND.py':b'# code'}))
        with self.assertRaises(ValueError):self.manager.install(bad)
    def test_wrong_version_rejected(self):
        bad=self.modified('cet6',lambda d:d.update({'module.json':b'{"schema_version":1,"id":"cet6","version":"v2"}'}))
        with self.assertRaises(ValueError):self.manager.install(bad)
    def test_modified_code_preserved_but_not_restored(self):
        self.manager.install(self.packages['voice_engine']);folder=self.manager.folder('voice_engine');(folder/'voice_backend.py').write_bytes(b'changed')
        self.manager.uninstall('voice_engine');self.manager.install(self.packages['voice_engine'])
        self.assertEqual((folder/'voice_backend.py').read_bytes(),b'# code');self.assertEqual((self.manager.retained/'voice_engine/voice_backend.py').read_bytes(),b'changed')
    def test_core_recordings_survive_voice_module_removal(self):
        fixed=self.manager.fixed_home();before=(fixed/'manifest.json').read_bytes()
        self.manager.install(self.packages['voice_engine']);self.manager.uninstall('voice_engine')
        self.assertTrue(self.manager.installed('fixed_voice'))
        self.assertEqual(self.manager.fixed_home(),fixed)
        self.assertEqual((fixed/'manifest.json').read_bytes(),before)
        self.assertEqual({item['id'] for item in self.manager.snapshot()['items']},{'cet6','voice_engine'})
        with self.assertRaises(ValueError):self.manager.uninstall('fixed_voice')
        self.assertEqual((fixed/'manifest.json').read_bytes(),before)
        summary=Bridge(self.data,modules=self.manager).call({'command':'state.summary','params':{}})
        self.assertNotIn('fixed_voice',summary['optional_modules'])
        self.assertTrue(summary['core_features']['fixed_voice'])
    def test_old_catalog_reads_legacy_fixed_recordings_without_moving_them(self):
        path=self.resources/'module_catalog.json';catalog=json.loads(path.read_text())
        catalog['modules']['fixed_voice']={'version':'old','bytes':2,'files':{}}
        path.write_text(json.dumps(catalog))
        manager=OptionalModules(self.resources,self.data,install_root=self.root/'installed')
        legacy=manager.folder('fixed_voice');(legacy/'voice').mkdir(parents=True)
        (legacy/'voice/manifest.json').write_text('{}')
        (legacy/'.installed.json').write_text(json.dumps({'id':'fixed_voice','version':'old','catalog_hash':manager.catalog_hash('fixed_voice')}))
        self.assertEqual(manager.fixed_home(),self.resources/'assets/voice')
        (self.resources/'assets/voice/manifest.json').unlink()
        self.assertEqual(manager.fixed_home(),legacy/'voice')
        self.assertTrue(manager.installed('fixed_voice'))
        with self.assertRaises(ValueError):manager.uninstall('fixed_voice')
        self.assertTrue((legacy/'voice/manifest.json').is_file())
        (legacy/'.installed.json').unlink()
        self.assertFalse(manager.installed('fixed_voice'))
    def test_reserved_windows_paths(self):
        for name in ('CON.txt','a/../b','a\\b','C:/bad','a./b','a/NUL','a//b'):
            with self.subTest(name=name),self.assertRaises(ValueError):safe_name(name)
    def test_legacy_mode_does_not_remove_resources(self):
        (self.resources/'module_catalog.json').unlink();legacy=OptionalModules(self.resources,self.data)
        self.assertTrue(legacy.installed('cet6'))
        with self.assertRaises(ValueError):legacy.uninstall('cet6')


class StudyImportCompatibility(unittest.TestCase):
    def check_layout(self,namespace,variant='normal'):
        import subprocess
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);resources=root/'resources';resources.mkdir();folder=root/'installed/cet6';folder.mkdir(parents=True)
            entries={}
            namespaces=('libao_modules','hebao_modules') if variant=='ambiguous' else (namespace,)
            for ns in namespaces:
                for leaf in ('daily_study.py','handoff.py','prompts.py'):
                    data=(Path(__file__).resolve().parents[1]/'libao_modules'/leaf).read_bytes()
                    name='python/'+ns+'/'+leaf;dest=folder/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
                    entries[name]={'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
            if variant=='incomplete':del entries['python/'+namespace+'/prompts.py']
            catalog={'schema_version':1,'modules':{'cet6':{'version':'v1','files':entries},'voice_engine':{'version':'v1','available':False,'files':{}}}}
            (resources/'module_catalog.json').write_text(json.dumps(catalog),encoding='utf-8')
            manager=OptionalModules(resources,root/'data',install_root=root/'installed')
            (folder/'.installed.json').write_text(json.dumps({'id':'cet6','version':'v1','catalog_hash':manager.catalog_hash('cet6')}),encoding='utf-8')
            if variant=='tampered':(folder/'python'/namespace/'daily_study.py').write_text('raise AssertionError("unverified code")',encoding='utf-8')
            if variant=='unlisted':
                other=folder/'python/libao_modules';other.mkdir(parents=True)
                for leaf in ('daily_study.py','handoff.py','prompts.py'):(other/leaf).write_text('raise AssertionError("unlisted code")',encoding='utf-8')
            # A fresh interpreter and empty package path prevent the source tree or
            # earlier tests from hiding a broken external/frozen-module import.
            script="""
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import libao_modules,libao_modules.registry
from optional_modules import OptionalModules
from workbench.bridge import Bridge
root=Path(sys.argv[2]);ns=sys.argv[3];variant=sys.argv[4]
libao_modules.__path__=[]
manager=OptionalModules(root/'resources',root/'data',install_root=root/'installed')
assert manager.installed('cet6')
bridge=Bridge(root/'data',modules=manager)
if variant in ('tampered','ambiguous','incomplete'):
 try:bridge.call({'command':'daily.workspace','params':{}})
 except ValueError:pass
 else:raise AssertionError('Invalid package accepted')
 assert libao_modules.__path__==[]
else:
 result=bridge.call({'command':'daily.workspace','params':{}})
 assert isinstance(result,dict) and 'history' in result
 for name in ('daily_study','handoff','prompts'):
  actual=Path(sys.modules['libao_modules.'+name].__file__).resolve()
  assert actual==root/'installed/cet6/python'/ns/(name+'.py'),actual
 print(json.dumps({'workspaceLoaded':True,'namespace':ns,'unlistedIgnored':variant=='unlisted'}))
"""
            result=subprocess.run([sys.executable,'-B','-X','utf8','-c',script,str(Path(__file__).resolve().parents[1]),str(root),namespace,variant],capture_output=True,text=True,encoding='utf-8',timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
    def test_current_package_loads_actual_workspace(self):self.check_layout('libao_modules')
    def test_legacy_package_loads_actual_workspace(self):self.check_layout('hebao_modules')
    def test_tampered_legacy_package_rejected(self):self.check_layout('hebao_modules','tampered')
    def test_ambiguous_verified_namespaces_rejected(self):self.check_layout('hebao_modules','ambiguous')
    def test_unlisted_new_namespace_cannot_shadow_legacy(self):self.check_layout('hebao_modules','unlisted')
    def test_incomplete_registered_namespace_rejected(self):self.check_layout('hebao_modules','incomplete')

if __name__=='__main__':unittest.main(verbosity=2)
