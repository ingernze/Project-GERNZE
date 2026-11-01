"""Real file transactions and paired service, synthetic sources/provider only."""
import json
from pathlib import Path
import sqlite3
import socket
import ssl
import hashlib
import sys
import threading
import types
import unittest
import uuid
from unittest.mock import patch

import research_summaries_test as fixtures
from workbench.desktop_memory_review import DesktopMemoryReview
from workbench.layer_sync import LayerSync, empty
from workbench.conversation_store import ConversationStore, stamp
from workbench.research_catalog import ResearchAccess
from workbench.research_context import ResearchJournal
from workbench.research_summaries import reference
ORIGINAL_CONNECT=socket.socket.connect


class Adapter:
    limits=types.SimpleNamespace(context_window=65536, margin=512, io_timeout=2)
    def __init__(self):self.calls=[];self.callback=None;self.edit=None;self.action='supported'
    def count(self,messages):return len(json.dumps(messages,ensure_ascii=False).encode())+128
    def complete(self,messages,maximum,control,report,**kwargs):
        self.calls.append({'messages':messages,'maximum':maximum});control.check()
        decisions=[]
        for entry in json.loads(messages[1]['content'])['entries']:
            if 'key' in entry:
                value={'key':entry['key'],'revision':entry['revision'],'action':'defer','text':'','evidence':[],'reason':'合成保留待审'}
            else:
                value={'id':entry['id'],'revision':entry['revision'],'action':self.action,
                       'evidence':[next(s['id'] for s in entry['sources'] if s['kind']=='research')] if self.action=='supported' else [],'reason':'仅核对所附输入，不批准用户事实'}
            if self.edit:self.edit(value,entry)
            decisions.append(value)
        if self.callback:self.callback()
        return json.dumps({'decisions':decisions},ensure_ascii=False)


class ResearchReviewTransferTests(unittest.TestCase):
    captures=[]
    packets=[]
    def setUp(self):
        self.h=fixtures.ResearchSummaryTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.chat=self.h.chat;self.store=self.chat.store;self.events=self.h.events
        self.h.source,self.h.entry=self.h.fixture.seed(course=False,text='GENERAL_material')
        self.h.worker.text='GENERAL_summary';self.h.seed_turns(study=False)
        self.assertEqual(self.h.summarize(study=False),'committed')
        self.adapter=Adapter();self.reviewer=DesktopMemoryReview(self.chat,adapter=self.adapter)
        self.server=str(uuid.uuid4());self.sync=LayerSync(self.chat,self.server)
        self.scope=self.sync.scope
    def tearDown(self):
        self.captures.append({'case':self.id(),'sql':self.events[:],'requests':self.adapter.calls})
    def rows(self):
        with self.store.read_connection() as db:return [dict(r) for r in db.execute('SELECT * FROM rc_summary_reviews')]
    def exchange(self,cap=True):
        result=self.sync.exchange({'snapshot':empty(self.scope),**({'capabilities':['gernze-research-cache-v1']} if cap else {})})
        if 'research' in result:self.packets.append(result['research'])
        return result
    def course_summary(self):
        self.h.source,self.h.entry=self.h.fixture.seed(course=True,text='COURSE_SECRET_material')
        self.h.worker.text='COURSE_SECRET_summary';self.h.seed_turns(study=True)
        self.assertEqual(self.h.summarize(study=True),'committed')
        return self.h.summary_rows()[-1]
    def test_supported_review_is_separate_from_user_facts_and_one_call(self):
        result=self.reviewer.run(force=True)
        self.assertEqual((result['status'],result['kind'],result['userFactsWritten']),('completed','research',0))
        self.assertEqual(self.rows()[0]['status'],'supported');self.assertEqual(len(self.adapter.calls),1)
        self.assertEqual(self.adapter.calls[0]['maximum'],8192)
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lm_approved').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lm_working').fetchone()[0],0)
        self.assertIn('研究摘要核对完成',self.reviewer.status()['progress']['message'])
    def test_reject_blocks_context_and_snapshot_without_loading_summary_again(self):
        self.adapter.action='reject';self.assertEqual(self.reviewer.run(force=True)['status'],'completed');self.events.clear()
        with self.h.scope(study=False):self.assertEqual(self.store.research_summaries.metadata(self.store.session_id),[])
        self.assertEqual(self.exchange()['research']['records'],[])
        self.assertFalse(any(q.startswith('SELECT body FROM rc_summary_bodies') for q in self.events))
    def test_defer_is_low_trust_and_not_a_user_fact(self):
        self.adapter.action='defer';self.reviewer.run(force=True)
        value=self.exchange()['research']['records'][0]
        self.assertEqual(value['review']['status'],'defer');self.assertEqual(value['trust'],'research_summary')
    def test_model_cannot_write_approval_or_permissions(self):
        self.adapter.edit=lambda d,e:d.update(action='approve',study=True)
        self.assertEqual(self.reviewer.run(force=True)['status'],'failed');self.assertEqual(self.rows(),[])
    def test_supported_cannot_cite_only_assistant(self):
        self.adapter.edit=lambda d,e:d.update(evidence=[next(s['id'] for s in e['sources'] if s['kind']=='assistant')])
        self.assertEqual(self.reviewer.run(force=True)['status'],'failed');self.assertEqual(self.rows(),[])
    def test_source_revision_changed_during_model_discards_receipt(self):
        self.adapter.callback=lambda:self.store.catalog.change_source(*self.h.source,source_text='revised')
        self.assertEqual(self.reviewer.run(force=True)['status'],'failed');self.assertEqual(self.rows(),[])
    def test_raw_retirement_during_model_discards_receipt(self):
        self.adapter.callback=lambda:self.store.retire_context('synthetic_retraction')
        self.assertEqual(self.reviewer.run(force=True)['status'],'failed');self.assertEqual(self.rows(),[])
    def test_model_wait_holds_neither_chat_guard_nor_writer_lock(self):
        errors=[]
        def callback():
            def change():
                try:self.reviewer.configure(False)
                except Exception as e:errors.append(str(e))
            thread=threading.Thread(target=change,daemon=True);thread.start();thread.join(2)
            self.assertFalse(thread.is_alive(),'provider held chat.guard or writer lock')
        self.adapter.callback=callback
        self.assertEqual(self.reviewer.run(force=True)['status'],'failed');self.assertEqual(self.rows(),[]);self.assertEqual(errors,[])
    def test_review_batch_and_its_log_rollback_together(self):
        self.h.seed_turns(n=3,study=False)
        with self.store.connection() as db:db.execute("UPDATE rc_summary_attempt SET clock='2000-01-01T00:00:00Z'")
        self.assertEqual(self.h.summarize(study=False),'committed')
        second=self.h.summary_rows()[1]['id']
        with self.store.connection() as db:db.execute("CREATE TRIGGER fail_research_receipt BEFORE INSERT ON rc_summary_reviews WHEN NEW.summary_id='"+second+"' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        self.assertEqual(self.reviewer.run(force=True)['status'],'failed');self.assertEqual(self.rows(),[])
        self.assertFalse(any(r.get('kind')=='research' for r in self.reviewer.status()['recent']))
    def test_automatic_review_filters_course_before_any_body(self):
        self.course_summary()
        self.reviewer.run(force=True) # the general one only
        self.events.clear();calls=len(self.adapter.calls)
        self.assertEqual(self.reviewer.run(force=True)['status'],'no_pending')
        self.assertEqual(len(self.adapter.calls),calls)
        self.assertFalse(any(q.startswith('SELECT body FROM rc_summary_bodies') or q.startswith('SELECT id,role,content,allowed') for q in self.events))
    def test_legacy_and_research_alternate_without_two_paid_calls(self):
        sid=str(uuid.uuid4())
        with self.store.connection() as db:db.execute('INSERT INTO lc_sessions VALUES (?,?,0)',(sid,stamp()))
        for i in range(4):
            rid=str(uuid.uuid4());self.store.begin_turn(sid,'我的昵称是合成甲。',rid)
            ConversationStore.complete(self.store,rid,{'text':'合成回答','emotion':'normal','action':'none'},self.store.epoch(),[])
        view=self.store.summary_view(sid,keep_recent=1,batch=3)
        self.assertTrue(self.store.commit_summary(sid,view,view['new_turns'],'我的昵称是合成甲。'))
        first=self.reviewer.run(force=True);self.assertEqual(first['status'],'completed');self.assertNotIn('kind',first)
        second=self.reviewer.run(force=True);self.assertEqual(second.get('kind'),'research');self.assertEqual(len(self.adapter.calls),2)
    def test_cancel_during_model_never_commits(self):
        self.adapter.callback=self.reviewer.cancel.set
        self.reviewer.run(force=True);self.assertEqual(self.rows(),[])
    def test_disabled_and_periodic_not_due_do_not_call(self):
        self.reviewer.configure(False);self.assertEqual(self.reviewer.run(force=True)['status'],'disabled')
        self.reviewer.configure(True);self.assertEqual(self.reviewer.run()['status'],'not_due');self.assertEqual(self.adapter.calls,[])
    def test_old_stage6_reader_refuses_new_verdict_schema(self):
        class OldReader(ResearchJournal):SUPPORTED_VERSIONS=(0,1,2,3)
        with self.assertRaises(ValueError):OldReader(self.store.path)
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],4)
            self.assertEqual(db.execute("SELECT value FROM rc_meta WHERE key='summary_schema'").fetchone()[0],'2')
    def test_explicit_upgrade_retains_v3_summary_and_originals(self):
        original=self.h.summary_rows()[0]
        with self.store.connection() as db:
            db.execute('DROP TABLE rc_summary_reviews');db.execute("UPDATE rc_meta SET value='1' WHERE key='summary_schema'");db.execute('PRAGMA user_version=3')
        upgraded=ResearchJournal(self.store.path)
        with upgraded.read_connection() as db:
            row=db.execute('SELECT id,revision,body_hash FROM rc_summary_meta WHERE id=?',(original['id'],)).fetchone()
            self.assertEqual(dict(row),reference(original));self.assertEqual(db.execute('SELECT COUNT(*) FROM lc_messages').fetchone()[0],14)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lm_approved').fetchone()[0],0)
    def test_parent_rejection_blocks_descendants_before_body(self):
        self.h.seed_turns(n=3,study=False)
        with self.store.connection() as db:db.execute("UPDATE rc_summary_attempt SET clock='2000-01-01T00:00:00Z'")
        self.assertEqual(self.h.summarize(study=False),'committed')
        self.chat.context=self.h.manager;self.h.seed_turns(n=5,study=False)
        with self.store.connection() as db:db.execute("UPDATE rc_summary_attempt SET clock='2000-01-01T00:00:00Z'")
        self.assertEqual(self.h.summarize(study=False),'committed')
        child=self.h.summary_rows()[-1];parents=json.loads(child['parents']);self.assertTrue(parents)
        parent=parents[0]
        with self.store.connection() as db:db.execute('INSERT INTO rc_summary_reviews VALUES (?,?,?,?,?,?)',(parent['id'],parent['revision'],parent['body_hash'],'reject','合成来源否决',stamp()))
        self.events.clear()
        with self.h.scope(study=False):
            with self.assertRaisesRegex(ValueError,'summary_review_rejected_or_changed'):self.store.research_summaries.read(reference(child))
        self.assertFalse(any(q.startswith('SELECT body FROM rc_summary_bodies') for q in self.events))
    def test_review_reject_during_actual_chat_invalidates_whole_answer(self):
        self.chat.context=self.h.manager;ref=reference(self.h.summary_rows()[0])
        def reject():
            with self.store.connection() as db:db.execute('INSERT INTO rc_summary_reviews VALUES (?,?,?,?,?,?)',(ref['id'],ref['revision'],ref['body_hash'],'reject','合成否决',stamp()))
        self.h.http.callback=reject
        rid=self.h.fixture.bind(self.h.entry,access=ResearchAccess())
        with self.assertRaises(ValueError):self.chat.reply_request('继续这项合成研究',request_id=rid)
        self.assertIn('GENERAL_summary',json.dumps(self.h.http.requests[-1]))
        with self.store.read_connection() as db:
            self.assertNotEqual(db.execute('SELECT status FROM lc_turns WHERE id=?',(rid,)).fetchone()[0],'complete')
            self.assertIsNone(db.execute('SELECT 1 FROM rc_exposures WHERE turn_id=?',(rid,)).fetchone())
    def test_review_reject_blocks_actual_cached_answer_without_model_retry(self):
        self.chat.context=self.h.manager;ref=reference(self.h.summary_rows()[0])
        rid=self.h.fixture.bind(self.h.entry,access=ResearchAccess());self.chat.reply_request('继续这项合成研究',request_id=rid)
        count=len(self.h.http.requests)
        with self.store.connection() as db:db.execute('INSERT INTO rc_summary_reviews VALUES (?,?,?,?,?,?)',(ref['id'],ref['revision'],ref['body_hash'],'reject','合成否决',stamp()))
        self.h.fixture.bind(self.h.entry,access=ResearchAccess(),rid=rid)
        with self.assertRaises(ValueError):self.chat.reply_request('继续这项合成研究',request_id=rid)
        self.assertEqual(len(self.h.http.requests),count)
    def test_no_negotiation_does_not_send_or_read_research_body(self):
        self.events.clear();result=self.exchange(False);self.assertNotIn('research',result)
        self.assertFalse(any(q.startswith('SELECT body FROM rc_summary_bodies') for q in self.events))
    def test_complete_snapshot_keeps_provenance_but_course_body_stays_on_desktop(self):
        course=self.course_summary();self.events.clear();result=self.exchange()['research']
        self.assertEqual(len(result['records']),2)
        general=next(r for r in result['records'] if r['restriction']=='general');restricted=next(r for r in result['records'] if r['restriction']=='study')
        self.assertEqual(general['body'],'GENERAL_summary');self.assertIsNone(restricted['body'])
        self.assertTrue(restricted['sources']);self.assertTrue(restricted['raw_refs']);self.assertEqual(restricted['courses'],[self.h.fixture.course])
        self.assertNotIn('COURSE_SECRET',json.dumps(result));self.assertNotIn('GENERAL_RESEARCH_answer',json.dumps(result))
        self.assertFalse(any(q.startswith('SELECT body FROM rc_summary_bodies') and course['id'] in q for q in self.events))
    def test_source_retraction_clears_whole_old_item_in_next_snapshot(self):
        first=self.exchange()['research'];self.assertEqual(len(first['records']),1)
        self.store.catalog.change_source(*self.h.source,state='withdrawn')
        second=self.exchange()['research'];self.assertGreater(second['sequence'],first['sequence']);self.assertEqual(second['records'],[])
    def test_publisher_attachment_and_restart_keep_owner_and_sequence(self):
        from layer_service import LayerService
        owner=self.store.owner;service=LayerService(self.store.path,self.server);service.layers.core_loader=lambda:{'schemaVersion':1,'entries':[]}
        self.assertEqual(service.info()['researchCache'],'gernze-research-cache-v1')
        one=service.exchange({'snapshot':empty(self.scope),'capabilities':['gernze-research-cache-v1']})['research']
        service=LayerService(self.store.path,self.server);service.layers.core_loader=lambda:{'schemaVersion':1,'entries':[]}
        two=service.exchange({'snapshot':empty(self.scope),'capabilities':['gernze-research-cache-v1']})['research']
        self.assertGreater(two['sequence'],one['sequence'])
        with self.store.read_connection() as db:self.assertEqual(self.store._get(db,'owner'),owner)
    def test_bad_capability_rejected_before_write(self):
        with self.assertRaisesRegex(ValueError,'unsupported_layer_capabilities'):self.sync.exchange({'snapshot':empty(self.scope),'capabilities':['unrecognized']})
        with self.store.read_connection() as db:self.assertIsNone(db.execute("SELECT value FROM rc_meta WHERE key='phone_cache_sequence'").fetchone())
    def test_corrupted_body_rolls_back_export_sequence(self):
        first=self.exchange()['research']
        with self.store.connection() as db:db.execute("UPDATE rc_summary_bodies SET body='CORRUPTED'")
        with self.assertRaisesRegex(ValueError,'research_cache_integrity'):self.exchange()
        with self.store.read_connection() as db:self.assertEqual(int(db.execute("SELECT value FROM rc_meta WHERE key='phone_cache_sequence'").fetchone()[0]),first['sequence'])
    def test_overflow_fails_instead_of_sending_partial_snapshot(self):
        first=self.exchange()['research'];original=self.h.summary_rows()[0]
        with self.store.connection() as db:
            for i in range(128):
                copy=dict(original);copy['id']=str(uuid.uuid4());copy['version']=i+2
                db.execute('INSERT INTO rc_summary_meta VALUES ('+','.join('?'*len(copy))+')',tuple(copy.values()))
        with self.assertRaisesRegex(ValueError,'research_cache_limit'):self.exchange()
        with self.store.read_connection() as db:self.assertEqual(int(db.execute("SELECT value FROM rc_meta WHERE key='phone_cache_sequence'").fetchone()[0]),first['sequence'])
    def test_real_paired_tls_requires_auth_and_negotiates_cache(self):
        from publisher import Publisher
        root=self.h.fixture.root;apk=root/'synthetic.apk';apk.write_bytes(b'NOT_AN_INSTALLABLE_APK');data=apk.read_bytes()
        manifest={'schemaVersion':1,'artifactId':str(uuid.uuid4()),'packageName':'com.hecate.companion','versionCode':1,'versionName':'synthetic','size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'signerCertificateSha256':['a'*64],'minSdkVersion':24}
        def local_connect(sock,address):
            if address[0]!='127.0.0.1':raise AssertionError('external network prohibited')
            return ORIGINAL_CONNECT(sock,address)
        with patch('socket.socket.connect',local_connect),patch('publisher.private_host',lambda v:v):
            publisher=Publisher(root/'publisher',apk,manifest,'127.0.0.1',memory_path=root/'companion-memory.sqlite3').start()
            try:
                context=ssl.create_default_context(cadata=ssl.DER_cert_to_PEM_cert(publisher.der))
                def request(path,body=None,auth=None):
                    payload=json.dumps(body).encode() if body is not None else b'';method='POST' if body is not None else 'GET'
                    headers=f'{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{publisher.port}\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n'
                    if auth:headers+='Authorization: Bearer '+auth['token']+'\r\nX-Hebao-Pairing: '+auth['pairingId']+'\r\n'
                    with socket.create_connection(('127.0.0.1',publisher.port),timeout=3) as sock:
                        with context.wrap_socket(sock,server_hostname='hebao.local') as tls:
                            tls.sendall((headers+'\r\n').encode()+payload);answer=b''
                            while block:=tls.recv(65536):answer+=block
                    head,value=answer.split(b'\r\n\r\n',1);return int(head.split()[1]),json.loads(value)
                self.assertEqual(request('/v1/layers/info')[0],401)
                invitation=publisher.issue_invitation();status,auth=request('/v1/pair',{'serverId':invitation['serverId'],'deviceId':str(uuid.uuid4()),'pairingSecret':invitation['pairingSecret']});self.assertEqual(status,200)
                status,info=request('/v1/layers/info',auth=auth);self.assertEqual(status,200);self.assertEqual(info['researchCache'],'gernze-research-cache-v1')
                status,result=request('/v1/layers/exchange',{'snapshot':empty(info['scope_id']),'capabilities':['gernze-research-cache-v1']},auth);self.assertEqual(status,200)
                self.assertEqual(result['research']['records'][0]['body'],'GENERAL_summary');self.assertEqual(result['serverId'],invitation['serverId'])
            finally:publisher.close()


if __name__=='__main__':unittest.main()
