"""Synthetic credential routing and metadata persistence; never uses Windows credentials."""
from pathlib import Path
import json,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from workbench.companion_chat import CompanionChat,DEFAULTS

class Keys:
    def __init__(self):self.values={}
    def get(self,k):return self.values.get(k,'')
    def set(self,k,v):self.values[k]=v
    def delete(self,k):self.values.pop(k,None)

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'chat.json';self.keys=Keys()
        self.config={'enabled':True,'endpoint':'https://synthetic.invalid/chat/completions','model':'synthetic'}
        self.path.write_text(json.dumps(self.config),encoding='utf-8')
        self.chat=CompanionChat(self.path,keys=self.keys)
        self.legacy=self.chat._target(self.config);self.keys.set(self.legacy,'synthetic-first-key')
    def test_legacy_key_is_visible_as_saved_without_rewriting_credential(self):
        listing=self.chat.list_connections()
        self.assertEqual(listing['saved_count'],1);self.assertEqual(listing['active_id'],'default')
        self.assertEqual(self.chat.config()['key_present'],True)
        self.assertEqual(self.chat._target(self.config),self.legacy)
        self.assertNotIn('synthetic-first-key',json.dumps(listing))
    def test_same_endpoint_can_keep_two_independent_keys_and_switch_after_reopen(self):
        added=self.chat.save_connection('备用服务',{**self.config,'key':'synthetic-second-key'})
        ident=added['config']['connection_id'];self.assertNotEqual(ident,'default')
        self.assertEqual(self.chat.keys.get(self.chat._target(self.config)),'synthetic-second-key')
        self.assertEqual(added['list']['saved_count'],2)
        self.chat.select_connection('default');self.assertEqual(self.chat.keys.get(self.chat._target(self.config)),'synthetic-first-key')
        reopened=CompanionChat(self.path,keys=self.keys)
        self.assertEqual(reopened.config()['connection_id'],'default')
        reopened.select_connection(ident);self.assertEqual(reopened.keys.get(reopened._target(self.config)),'synthetic-second-key')
        saved=self.path.read_text();self.assertNotIn('synthetic-first-key',saved);self.assertNotIn('synthetic-second-key',saved)
        self.assertNotIn('synthetic-second-key',json.dumps(added))
    def test_remove_only_the_selected_secret_and_never_silently_enable_fallback(self):
        added=self.chat.save_connection('第二份',{**self.config,'key':'synthetic-second-key'})
        ident=added['config']['connection_id'];target=self.chat._target(self.config)
        result=self.chat.remove_connection(ident)
        self.assertNotIn(target,self.keys.values);self.assertEqual(self.keys.get(self.legacy),'synthetic-first-key')
        self.assertEqual(result['list']['saved_count'],1);self.assertFalse(result['config']['enabled'])
    def test_edit_without_key_keeps_saved_secret_and_friendly_name(self):
        result=self.chat.save_connection('新名称',self.config,'default')
        self.assertEqual(result['config']['connection_name'],'新名称');self.assertEqual(self.keys.get(self.legacy),'synthetic-first-key')
    def test_unfinished_new_connection_does_not_become_a_list_item(self):
        with self.assertRaises(ValueError):self.chat.save_connection('未填密钥',self.config)
        self.assertEqual(len(self.chat.list_connections()['connections']),1)
    def test_active_request_prevents_switch_save_or_remove(self):
        self.chat.sending.acquire()
        try:
            for action in [lambda:self.chat.select_connection('default'),lambda:self.chat.save_connection('新',self.config),lambda:self.chat.remove_connection('default')]:
                with self.assertRaises(ValueError):action()
        finally:self.chat.sending.release()
    def test_secret_or_unknown_fields_are_rejected_in_metadata(self):
        with self.assertRaises(ValueError):self.chat.configure({**self.config,'extra':'invalid'})
        doc=self.chat._connections();doc['connections'][0]['settings']['key']='synthetic-should-not-be-on-disk'
        self.path.write_text(json.dumps(doc))
        with self.assertRaises(ValueError):self.chat.list_connections()

    def test_failed_metadata_save_rolls_back_the_new_secret(self):
        original=self.path.read_bytes();keys=dict(self.keys.values)
        def fail(doc):raise OSError('synthetic-write-failure')
        self.chat._write_connections=fail
        with self.assertRaises(OSError):self.chat.save_connection('新增',{**self.config,'key':'synthetic-second-key'})
        self.assertEqual(self.path.read_bytes(),original);self.assertEqual(self.keys.values,keys)

    def test_failed_remove_restores_secret_and_list(self):
        added=self.chat.save_connection('新增',{**self.config,'key':'synthetic-second-key'})
        original=self.path.read_bytes();keys=dict(self.keys.values)
        def fail(doc):raise OSError('synthetic-write-failure')
        self.chat._write_connections=fail
        with self.assertRaises(OSError):self.chat.remove_connection(added['config']['connection_id'])
        self.assertEqual(self.path.read_bytes(),original);self.assertEqual(self.keys.values,keys)

if __name__=='__main__':unittest.main(verbosity=2)
