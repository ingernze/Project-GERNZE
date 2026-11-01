"""Independent phone-summary review using temporary databases and fake provider."""
import copy,json,sqlite3,threading,types,unittest
from unittest.mock import patch
import phone_research_summaries_test as fixtures
from workbench.desktop_memory_review import DesktopMemoryReview
from workbench.conversation_store import stamp
from workbench.memory_archive import MemoryArchive,day_of
from workbench.research_review import packet
from workbench.research_summaries import reference


class Adapter:
    limits=types.SimpleNamespace(context_window=65536,margin=512,io_timeout=2)
    def __init__(self):self.calls=[];self.callback=None;self.edit=None;self.action='supported'
    def count(self,messages):return len(json.dumps(messages,ensure_ascii=False).encode())+128
    def complete(self,messages,maximum,control,report,**kwargs):
        control.check();self.calls.append({'messages':copy.deepcopy(messages),'maximum':maximum});decisions=[]
        for entry in json.loads(messages[1]['content'])['entries']:
            value={'id':entry['id'],'revision':entry['revision'],'action':self.action,'evidence':
                   [next(s['id'] for s in entry['sources'] if s['kind'] in ('user','research'))] if self.action=='supported' else [],
                   'reason':'仅核对所附输入，不批准用户事实'}
            if self.edit:self.edit(value,entry)
            decisions.append(value)
        if self.callback:self.callback()
        return json.dumps({'decisions':decisions},ensure_ascii=False)


class PhoneResearchReviewTests(unittest.TestCase):
    packets=[]
    def setUp(self):
        self.h=fixtures.PhoneSummaryTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.h.seed();self.assertEqual(self.h.run_summary(),'committed')
        self.chat=self.h.chat;self.store=self.h.store;self.archive=self.h.archive
        self.meta=self.h.rows()[0];self.parent=self.h.h.src
        self.verdict(self.parent,'supported')
        self.adapter=Adapter();self.reviewer=DesktopMemoryReview(self.chat,adapter=self.adapter)
    def verdict(self,ref,status):
        with self.store.connection() as db:db.execute('INSERT OR REPLACE INTO rc_summary_reviews VALUES (?,?,?,?,?,?)',
            (ref['id'],ref['revision'],ref['body_hash'],status,'合成核对',stamp()))
    def rows(self):
        with self.store.read_connection() as db:return [dict(r) for r in db.execute('SELECT * FROM rc_summary_reviews WHERE summary_id=?',(self.meta['id'],))]
    def export(self,label):
        result=self.h.export();self.packets.append({'case':label,'snapshot':result});return result
    def test_phone_supported_is_not_fact_and_uses_only_selected_originals(self):
        result=self.reviewer.run(force=True)
        self.assertEqual((result['status'],result['kind'],result['userFactsWritten']),('completed','research',0))
        self.assertEqual(result['researchTypes'],{'desktop':0,'phone':1});self.assertEqual(self.rows()[0]['status'],'supported')
        self.assertEqual(len(self.adapter.calls),1);self.assertEqual(self.adapter.calls[0]['maximum'],8192)
        entry=json.loads(self.adapter.calls[0]['messages'][1]['content'])['entries'][0]
        self.assertEqual(entry['sourceType'],'phone_summary');self.assertEqual(len(entry['sources']),6)
        self.assertEqual([s['text'] for s in entry['sources'] if s['kind']=='user'],['PHONE_Q0','PHONE_Q1','PHONE_Q2'])
        self.assertTrue(all(s['trust']=='host_attested_raw' for s in entry['sources']))
        self.assertNotIn('PHONE_Q3',json.dumps(entry));self.assertNotIn('GENERAL_material',json.dumps(entry))
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lm_approved').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lm_working').fetchone()[0],0)
        record=next(r for r in self.export('supported')['records'] if r['phone_refs'])
        self.assertEqual(record['review']['status'],'supported');self.assertEqual(record['trust'],'research_summary')
    def test_defer_remains_low_trust_and_archive_directory_stays_body_free(self):
        self.adapter.action='defer';self.assertEqual(self.reviewer.run(force=True)['status'],'completed')
        record=next(r for r in self.export('defer')['records'] if r['phone_refs'])
        self.assertEqual(record['review']['status'],'defer');self.assertEqual(record['body'],self.h.worker.text)
        self.h.h.h.events.clear();archive=MemoryArchive(self.chat);archive.months();archive.days(day_of(stamp())[:7]);archive.status()
        self.assertFalse(any('SELECT body FROM rc_phone_summary_bodies' in q for q in self.h.h.h.events))
        self.assertTrue(any('保留待核对，不是用户事实' in r['text'] for r in archive.day(day_of(stamp()))['entries']))
    def test_supported_archive_label_reports_input_match(self):
        self.reviewer.run(force=True)
        self.assertTrue(any('与所附输入相符，不是用户事实' in r['text'] for r in MemoryArchive(self.chat).day(day_of(stamp()))['entries']))
    def test_reject_removes_cache_before_body_without_deleting_raw(self):
        before=self.export('before_reject');derived=next(r for r in before['records'] if r['phone_refs'])
        from phone_research_archive_test import receipt
        from workbench.phone_research_archive import USE_FORMAT_V2
        use=receipt(self.h.h.server,self.h.h.sync.scope,'synthetic-derived',source={k:v for k,v in derived.items() if k!='body'})
        use['format']=USE_FORMAT_V2
        self.assertEqual(self.archive.source_status(use),'current')
        raw=self.archive.raw(self.h.h.device,self.h.h.sid,0)
        self.adapter.action='reject';self.assertEqual(self.reviewer.run(force=True)['status'],'completed')
        self.h.h.h.events.clear();after=self.export('rejected')
        self.assertFalse(any(r['id']==derived['id'] for r in after['records']))
        self.assertFalse(any('SELECT body FROM rc_phone_summary_bodies' in q for q in self.h.h.h.events))
        self.assertEqual(self.archive.raw(self.h.h.device,self.h.h.sid,0),raw)
        self.assertEqual(self.archive.source_status(use),'changed')
    def test_supported_cannot_use_assistant_evidence(self):
        self.adapter.edit=lambda d,e:d.update(evidence=[next(s['id'] for s in e['sources'] if s['kind']=='assistant')])
        self.assertEqual(self.reviewer.run(force=True)['status'],'failed');self.assertEqual(self.rows(),[])
    def test_invalid_model_shapes_cannot_write_or_grant(self):
        for change in [dict(action='approve'),dict(evidence='not-a-list'),dict(study=True),dict(revision='wrong'),dict(id='unknown')]:
            with self.subTest(change=change):
                self.adapter.edit=lambda d,e:d.update(change)
                self.assertEqual(self.reviewer.run(force=True)['status'],'failed');self.assertEqual(self.rows(),[])
    def test_raw_hash_change_during_model_discards_verdict(self):
        def change():
            with self.archive.connection(True) as db:db.execute("UPDATE pr_meta SET content_hash=? WHERE seq=0",('b'*64,))
        self.adapter.callback=change
        self.assertEqual(self.reviewer.run(force=True)['status'],'failed');self.assertEqual(self.rows(),[])
    def test_raw_body_change_during_model_discards_verdict(self):
        def change():
            with self.archive.connection(True) as db:db.execute("UPDATE pr_bodies SET payload='{}' WHERE seq=0")
        self.adapter.callback=change
        self.assertEqual(self.reviewer.run(force=True)['status'],'failed');self.assertEqual(self.rows(),[])
    def test_parent_reject_during_model_discards_verdict(self):
        self.adapter.callback=lambda:self.verdict(self.parent,'reject')
        self.assertEqual(self.reviewer.run(force=True)['status'],'failed');self.assertEqual(self.rows(),[])
    def test_epoch_change_during_model_discards_verdict(self):
        self.adapter.callback=lambda:self.store.retire_context('synthetic')
        self.assertEqual(self.reviewer.run(force=True)['status'],'failed');self.assertEqual(self.rows(),[])
    def test_cancel_never_commits(self):
        self.adapter.callback=self.reviewer.cancel.set
        self.reviewer.run(force=True);self.assertEqual(self.rows(),[])
    def test_provider_holds_no_chat_guard_or_database_writer(self):
        errors=[]
        def callback():
            def write():
                try:
                    with self.store.connection() as db:db.execute("INSERT OR REPLACE INTO rc_meta VALUES ('synthetic_probe','1')")
                    with self.archive.connection(True) as db:db.execute('UPDATE pr_schema SET version=2')
                    self.reviewer.configure(False)
                except Exception as e:errors.append(type(e).__name__)
            thread=threading.Thread(target=write,daemon=True);thread.start();thread.join(2)
            self.assertFalse(thread.is_alive(),'provider held a lock')
        self.adapter.callback=callback
        self.assertEqual(self.reviewer.run(force=True)['status'],'failed');self.assertEqual(self.rows(),[]);self.assertEqual(errors,[])
    def test_completion_audit_failure_rolls_back_verdict(self):
        with self.store.connection() as db:db.execute("CREATE TRIGGER fail_completion BEFORE INSERT ON lmar_runs WHEN json_extract(NEW.payload,'$.status')='completed' BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        self.assertEqual(self.reviewer.run(force=True)['status'],'failed');self.assertEqual(self.rows(),[])
        self.assertFalse(any(r.get('status')=='completed' for r in self.reviewer.status()['recent']))
    def test_oversized_metadata_skips_phone_body_and_provider(self):
        with self.archive.connection(True) as db:db.execute('UPDATE pr_receipts SET message_bytes=17000 WHERE seq=0')
        queries=[];original=sqlite3.connect
        def trace(*a,**kw):db=original(*a,**kw);db.set_trace_callback(queries.append);return db
        with patch('sqlite3.connect',trace):self.assertEqual(self.reviewer.run(force=True)['status'],'no_pending')
        self.assertEqual(self.adapter.calls,[]);self.assertFalse(any('SELECT payload FROM phone_raw.pr_bodies' in q for q in queries))
    def test_invalid_parent_skips_before_phone_body(self):
        self.verdict(self.parent,'reject');queries=[];original=sqlite3.connect
        def trace(*a,**kw):db=original(*a,**kw);db.set_trace_callback(queries.append);return db
        with patch('sqlite3.connect',trace):self.assertEqual(self.reviewer.run(force=True)['status'],'no_pending')
        self.assertEqual(self.adapter.calls,[]);self.assertFalse(any('SELECT payload FROM phone_raw.pr_bodies' in q for q in queries))
    def test_deferred_desktop_and_phone_alternate_first_place_in_shared_batch(self):
        self.verdict(self.parent,'defer');self.adapter.action='defer'
        first=self.reviewer.run(force=True);second=self.reviewer.run(force=True)
        self.assertEqual(first['status'],'completed');self.assertEqual(second['status'],'completed');self.assertEqual(len(self.adapter.calls),2)
        entries=[json.loads(c['messages'][1]['content'])['entries'] for c in self.adapter.calls]
        self.assertEqual(entries[0][0]['id'],self.meta['id']);self.assertEqual(entries[1][0]['id'],self.parent['id'])
        self.assertTrue(all(len(e)==2 for e in entries))
    def test_disabled_and_not_due_use_no_provider(self):
        self.reviewer.configure(False);self.assertEqual(self.reviewer.run(force=True)['status'],'disabled')
        self.reviewer.configure(True);self.assertEqual(self.reviewer.run()['status'],'not_due');self.assertEqual(self.adapter.calls,[])

if __name__=='__main__':unittest.main(verbosity=2)
