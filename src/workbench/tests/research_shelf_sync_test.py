"""Synthetic files/SQLite only; publication atomicity, revisions and host gates."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from workbench.research_catalog import ResearchAccess, ResearchError, packed
from workbench.research_import import FORMAT, ResearchImporter
from workbench.research_shelf_sync import Publication, ResearchShelfSync, sha


def ident():return str(uuid.uuid4())


class ShelfSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.profile=self.root/'profile';self.profile.mkdir()
        self.source=self.root/'publication';self.source.mkdir();self.profile_id=ident();self.namespace=ident();self.course=ident()
        self.path=self.profile/'catalog.sqlite3';self.writer=ResearchImporter(self.path)
        self.sync=ResearchShelfSync(self.profile,self.profile_id,self.path)
        self.config={'format':'gernze-bookshelf-receipt-v1','automaticSync':True,'namespace':self.namespace,'profileId':self.profile_id,
                     'sourceKind':'saved_reports_not_original_webpages','source':str(self.source),'courseMapping':{'math':{'suggested_uuid':self.course}}}
        self.save_config();self.a=self.item('one');self.b=self.item('two')

    def dump(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        return sha(path.read_bytes())

    def save_config(self):self.dump(self.profile/'bookshelf-receipt.json',self.config)

    def item(self,text,**kwargs):
        value={'id':ident()+'/part-001','revision':ident(),'previous':None,'title':'合成资料','body':text,'source_text':text,
               'source_ref':'synthetic://report#chars=0:'+str(len(text)),'review_status':'partial','review_scope':'合成证据；未运行真实模型。'}
        value.update(kwargs);return value

    def revise(self,item,text):return self.item(text,id=item['id'],previous=item['revision'])

    def publish(self,items,category='encounter',keys=None):
        keys=keys or [];specs=[];exports=[];logical=[]
        for number,item in enumerate(items):
            name='导入候选/packet-'+str(number)+'.json';packet={'format':FORMAT,'namespace':self.namespace,'items':[item]}
            digest=self.dump(self.source/name,packet);lid=item['id'].split('/')[0]
            stable={k:v for k,v in item.items() if k not in ('revision','previous')}
            history='修订历史/导入项/'+str(uuid.uuid5(uuid.UUID(self.namespace),item['id']))+'/'+item['revision']+'.json'
            self.dump(self.source/history,packet)
            specs.append({'packet':name,'sha256':digest,'category':category,'course_keys':keys,'source_kind':'companion','item_count':1})
            exports.append({'id':item['id'],'item_id':lid,'revision':item['revision'],'previous':item['previous'],'packet':name,
                            'category':category,'course_keys':keys,'content_hash':sha(packed(stable).encode()),'history':history,
                            'part':1,'char_start':0,'char_end_exclusive':len(item['body'])})
            logical.append({'id':lid,'body':item['body'],'source':{'char_start_in_decoded_file':0},'category':category,'course_keys':keys,'importable':True,'lifecycle':'active'})
        self.mapping={'format':'libao-reading-shelf-host-map-v1','namespace':self.namespace,'authoritative_packet_list_only':True,'packets':specs}
        self.index={'format':'libao-reading-shelf-v1','namespace':self.namespace,'items':logical,'exports':exports}
        self.flush()

    def flush(self):
        self.index.update(item_count=len(self.index['items']),import_item_count=len(self.index['exports']))
        self.dump(self.source/'分类索引.json',self.index);self.dump(self.source/'宿主映射清单.json',self.mapping)

    def rows(self):
        with self.writer.catalog.connection() as db:
            return [dict(r) for r in db.execute('SELECT * FROM rc_import_items ORDER BY external_id')]

    def test_opt_in_and_profile_binding(self):
        self.config['automaticSync']=False;self.save_config()
        with patch.object(Publication,'read',side_effect=AssertionError('must not read source')):
            self.assertEqual(self.sync.refresh(),{'state':'disabled'})
        self.assertFalse(self.path.exists())
        self.config.update(automaticSync=True,profileId=ident());self.save_config()
        self.assertEqual(self.sync.refresh()['state'],'waiting');self.assertFalse(self.path.exists())

    def test_add_idempotent_reopen_and_no_l2_schema(self):
        self.publish([self.a]);self.assertEqual(self.sync.refresh()['result']['created'],1)
        self.assertEqual(self.sync.refresh()['state'],'current')
        reopened=ResearchShelfSync(self.profile,self.profile_id,self.path)
        self.assertEqual(reopened.refresh()['result']['unchanged'],1)
        self.publish([self.a,self.b]);result=self.sync.refresh()['result']
        self.assertEqual((result['created'],result['unchanged']),(1,1))
        with self.writer.catalog.connection() as db:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse({'lm_approved','lm_working','lc_messages'}&tables)

    def test_last_packet_failure_keeps_entire_previous_library(self):
        self.publish([self.a]);self.sync.refresh();before=self.rows()
        a2=self.revise(self.a,'revision two');self.publish([a2,self.b]);self.mapping['packets'][-1]['sha256']='0'*64;self.flush()
        self.assertEqual(self.sync.refresh()['state'],'waiting');self.assertEqual(self.rows(),before)

    def test_source_change_during_transaction_rolls_back_every_item(self):
        self.publish([self.a]);self.sync.refresh();before=self.rows();self.publish([self.revise(self.a,'changed'),self.b])
        original=Publication.check_current
        def change(publication):
            (self.source/'分类索引.json').write_text('{}',encoding='utf-8');original(publication)
        with patch.object(Publication,'check_current',change):self.assertEqual(self.sync.refresh()['state'],'waiting')
        self.assertEqual(self.rows(),before)

    def test_late_importer_conflict_rolls_back_earlier_valid_item(self):
        self.publish([self.a,self.b]);self.sync.refresh();before=self.rows()
        # Same external revision with changed bytes is detected inside writer,
        # after a valid first update has already run in the same transaction.
        bad=deepcopy(self.b);bad['body']=bad['source_text']='illegal revision reuse'
        self.publish([self.revise(self.a,'valid edit'),bad])
        self.assertEqual(self.sync.refresh()['state'],'waiting');self.assertEqual(self.rows(),before)

    def test_missed_history_catches_up_without_losing_original(self):
        self.publish([self.a]);self.sync.refresh();a2=self.revise(self.a,'second');self.publish([a2]);a3=self.revise(a2,'third');self.publish([a3])
        result=self.sync.refresh()['result'];self.assertEqual(result['updated'],2);self.assertEqual(self.rows()[0]['external_revision'],a3['revision'])
        with self.writer.catalog.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM rc_source_payloads').fetchone()[0],3)

    def test_missing_or_cyclic_history_does_not_guess(self):
        self.publish([self.a]);self.sync.refresh();before=self.rows()
        next_item=self.revise(self.a,'next');next_item['previous']=ident();self.publish([next_item])
        self.assertEqual(self.sync.refresh()['state'],'waiting');self.assertEqual(self.rows(),before)
        next_item['previous']=next_item['revision'];self.publish([next_item]);self.assertEqual(self.sync.refresh()['state'],'waiting');self.assertEqual(self.rows(),before)

    def test_old_publication_cannot_restore_old_text(self):
        self.publish([self.a]);self.sync.refresh();a2=self.revise(self.a,'new');self.publish([a2]);self.sync.refresh();before=self.rows()
        self.publish([self.a]);self.assertEqual(self.sync.refresh()['state'],'waiting');self.assertEqual(self.rows(),before)
        self.publish([a2]);self.assertEqual(self.sync.refresh()['state'],'current')

    def test_local_withdrawal_is_retained_while_other_books_arrive(self):
        self.publish([self.a]);self.sync.refresh();row=self.rows()[0]
        self.writer.catalog.change_source(row['source_id'],row['source_revision'],state='withdrawn')
        self.publish([self.a,self.b]);result=self.sync.refresh()['result'];self.assertEqual((result['created'],result['retainedLocal']),(1,1))
        with self.writer.catalog.connection() as db:self.assertEqual(db.execute('SELECT state FROM rc_sources WHERE id=?',(row['source_id'],)).fetchone()[0],'withdrawn')

    def test_removed_source_becomes_unavailable_keeps_history_and_no_revival(self):
        self.publish([self.a,self.b]);self.sync.refresh();before=self.rows()
        self.publish([self.b]);self.assertEqual(self.sync.refresh()['result']['retired'],1)
        old=next(r for r in before if r['external_id']==self.a['id'])
        with self.assertRaises(ResearchError):self.writer.catalog.read_selected([(old['entry_id'],old['entry_revision'])])
        with self.writer.catalog.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM rc_source_payloads').fetchone()[0],2)
        self.publish([self.a,self.b]);self.assertEqual(self.sync.refresh()['result']['retainedLocal'],1)
        with self.assertRaises(ResearchError):self.writer.catalog.read_selected([(old['entry_id'],old['entry_revision'])])

    def test_scope_is_pinned_and_course_not_readable_by_ordinary_chat(self):
        self.publish([self.a],category='course',keys=['math']);self.assertEqual(self.sync.refresh()['result']['created'],1);row=self.rows()[0]
        with self.assertRaises(ResearchError):self.writer.catalog.read_selected([(row['entry_id'],row['entry_revision'])],access=ResearchAccess())
        self.assertEqual(len(self.writer.catalog.read_selected([(row['entry_id'],row['entry_revision'])],access=ResearchAccess('study',(self.course,)))),1)
        before=self.rows();self.publish([self.a],category='encounter');self.assertEqual(self.sync.refresh()['state'],'waiting');self.assertEqual(self.rows(),before)
        self.publish([self.a],category='course',keys=['unapproved']);self.assertEqual(self.sync.refresh()['state'],'waiting');self.assertEqual(self.rows(),before)

    def test_duplicate_keys_traversal_and_reconstruction_are_rejected(self):
        self.publish([self.a]);self.sync.refresh();before=self.rows()
        self.mapping['packets'][0]['packet']='导入候选/../../outside.json';self.flush();self.assertEqual(self.sync.refresh()['state'],'waiting')
        self.publish([self.a]);self.index['items'][0]['body']='missing tail';self.flush();self.assertEqual(self.sync.refresh()['state'],'waiting')
        (self.source/'分类索引.json').write_text('{"items":[],"items":[]}',encoding='utf-8')
        self.assertEqual(self.sync.refresh()['state'],'waiting');self.assertEqual(self.rows(),before)

    def test_namespace_is_not_allowed_to_adopt_another_database(self):
        self.publish([self.a]);self.index['namespace']=ident();self.flush();self.assertEqual(self.sync.refresh()['state'],'waiting');self.assertFalse(self.path.exists())

    def test_complete_empty_publication(self):
        self.publish([self.a]);self.sync.refresh();self.publish([])
        self.assertEqual(self.sync.refresh()['result']['retired'],1)
        self.assertEqual(len(self.rows()),1)

    def test_independently_changed_entry_is_not_retired(self):
        self.publish([self.a]);self.sync.refresh();row=self.rows()[0]
        with self.writer.catalog.connection(write=True) as db:db.execute('UPDATE rc_entries SET revision=? WHERE id=?',(ident(),row['entry_id']))
        self.publish([]);result=self.sync.refresh()['result'];self.assertEqual((result['retired'],result['retainedLocal']),(0,1))
        with self.writer.catalog.connection() as db:self.assertEqual(db.execute('SELECT state FROM rc_sources').fetchone()[0],'active')

    def test_linked_publication_is_refused(self):
        self.publish([self.a])
        with patch.object(Path,'is_symlink',return_value=True):self.assertEqual(self.sync.refresh()['state'],'waiting')
        self.assertFalse(self.path.exists())

    def test_shared_course_keys_use_set_identity_preserving_all_grants(self):
        other=ident();self.config['courseMapping']['other']={'suggested_uuid':other};self.save_config()
        self.publish([self.a],category='course',keys=['math','other'])
        self.index['exports'][0]['course_keys']=['other','math'];self.index['items'][0]['course_keys']=['other','math'];self.flush()
        self.assertEqual(self.sync.refresh()['result']['created'],1);row=self.rows()[0]
        self.assertEqual(json.loads(row['courses']),sorted([self.course,other]))
        with self.assertRaises(ResearchError):self.writer.catalog.read_selected([(row['entry_id'],row['entry_revision'])],access=ResearchAccess('study',(self.course,)))

    def test_shorter_revision_retires_removed_tail_fragment(self):
        tail=self.item('tail',id=self.a['id'].replace('part-001','part-002'))
        self.publish([self.a,tail]);self.index['items']=self.index['items'][:1];self.index['items'][0]['body']=self.a['body']+tail['body']
        self.index['exports'][1].update(part=2,char_start=len(self.a['body']),char_end_exclusive=len(self.a['body'])+len(tail['body']));self.flush()
        self.assertEqual(self.sync.refresh()['result']['created'],2);old=next(r for r in self.rows() if r['external_id']==tail['id'])
        self.publish([self.revise(self.a,'shortened')]);result=self.sync.refresh()['result'];self.assertEqual((result['updated'],result['retired']),(1,1))
        with self.assertRaises(ResearchError):self.writer.catalog.read_selected([(old['entry_id'],old['entry_revision'])])

    def test_oversized_history_waits_without_partial_replay(self):
        self.publish([self.a]);self.sync.refresh();before=self.rows();item=self.a
        for n in range(34):item=self.revise(item,str(n));self.publish([item])
        self.assertEqual(self.sync.refresh()['state'],'waiting');self.assertEqual(self.rows(),before)

    def test_declared_totals_cannot_silently_omit_items(self):
        self.publish([self.a,self.b]);self.sync.refresh();before=self.rows()
        self.index['items']=[];self.index['exports']=[];self.mapping['packets']=[]
        self.dump(self.source/'分类索引.json',self.index);self.dump(self.source/'宿主映射清单.json',self.mapping)
        self.assertEqual(self.sync.refresh()['state'],'waiting');self.assertEqual(self.rows(),before)


class ShelfSyncHostTests(unittest.TestCase):
    def setUp(self):
        from workbench import companion_chat as cc
        from workbench.encounter_composition import create_desktop_chat
        from workbench.memory_layers import MemoryLayers
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.profile=self.root/'research'
        class Keys:
            def get(self,*a):return ''
            def set(self,*a):raise AssertionError('credential writes prohibited')
            def delete(self,*a):raise AssertionError('credential deletion prohibited')
        class HTTP:
            requests=[]
            def open(self,*a,**k):raise AssertionError('real model calls prohibited')
        self.keys=Keys();self.http=HTTP()
        def chat(path,**kwargs):return create_desktop_chat(path,opener=self.http,**kwargs)
        for item in (patch.object(cc,'system_prompt',return_value='合成人设'),patch.object(cc,'MemoryLayers',side_effect=lambda store:MemoryLayers(store,core_loader=lambda:{'schemaVersion':1,'entries':[]})),patch('workbench.server.create_desktop_chat',side_effect=chat)):
            item.start();self.addCleanup(item.stop)

    def open(self,**kwargs):
        import research_preview
        return research_preview.preview_server(self.profile,keys_backend=self.keys,**kwargs)

    def test_real_host_startup_and_bookshelf_open_updates_only_preview(self):
        import http.client,threading
        import research_preview as preview
        from workbench.server import WorkbenchServer
        fixture=ShelfSyncTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.publish([fixture.a]);path,profile_id=preview.prepare_profile(self.profile)
        fixture.config['profileId']=profile_id;fixture.dump(path/'bookshelf-receipt.json',fixture.config)
        with self.open() as server:
            self.assertEqual(server.research_shelf_sync.last_success['result']['created'],1)
            thread=threading.Thread(target=server.serve,daemon=True);thread.start()
            def call(params=None):
                connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                connection.request('POST','/api/call',json.dumps({'command':'chat.research.groups','params':params or {}}),{'Authorization':'Bearer '+server.token,'Content-Type':'application/json'})
                response=connection.getresponse();status=response.status;value=json.loads(response.read());connection.close();return status,value
            try:
                fixture.publish([fixture.a,fixture.b]);status,value=call();self.assertEqual(status,200)
                self.assertEqual(value['result']['shelfSync']['result']['created'],1)
                self.assertEqual(next(g['count'] for g in value['result']['groups'] if g['id']=='encounter'),2)
                fixture.mapping['packets'][-1]['sha256']='0'*64;fixture.flush();status,value=call()
                self.assertEqual(value['result']['shelfSync']['state'],'waiting')
                self.assertEqual(next(g['count'] for g in value['result']['groups'] if g['id']=='encounter'),2)
                self.assertEqual(call({'source':str(fixture.source)})[0],400)
                with server.chat.store.read_connection() as db:
                    self.assertTrue(all(db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]==0 for t in ('lm_approved','lm_working','lc_messages')))
                self.assertEqual(self.http.requests,[])
            finally:server.stop();thread.join(6);self.assertFalse(thread.is_alive())
        with patch.object(ResearchShelfSync,'refresh',side_effect=AssertionError('ordinary host must not import')):
            normal=WorkbenchServer(self.root/'normal',chat_keys=self.keys)
            try:self.assertFalse(hasattr(normal,'research_shelf_sync'))
            finally:normal.stop();normal.server_close()


if __name__=='__main__':unittest.main()
