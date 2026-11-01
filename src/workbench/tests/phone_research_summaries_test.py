"""Synthetic phone raw -> bounded desktop summary -> negotiated cache."""
import copy,json,sqlite3,threading,unittest,uuid
from unittest.mock import patch
from workbench.context_manager import ContextManager
from workbench.phone_research_archive import USE_FORMAT_V2,FORMAT
from workbench.phone_research_summaries import verify
from workbench.research_catalog import ResearchAccess
from workbench.research_summaries import reference
from workbench.layer_sync import empty
from workbench.memory_archive import MemoryArchive,day_of
from workbench.conversation_store import stamp
import phone_research_archive_test as fixtures

class Worker:
    def __init__(self):self.calls=[];self.callback=None;self.text='PHONE_DELTA_SUMMARY'
    def __call__(self,request,**kwargs):
        self.calls.append(request)
        if self.callback:self.callback()
        return {'text':self.text,'source_turn_ids':request['source_turn_ids']}

class PhoneSummaryTests(unittest.TestCase):
    packets=[]
    def setUp(self):
        self.h=fixtures.CurrentSourceTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.store=self.h.h.store;self.chat=self.h.h.chat;self.archive=self.h.archive;self.worker=Worker()
        self.manager=ContextManager(summarizer=self.worker,keep_recent=6,batch_size=3,min_batch=3,summary_timeout=1,summary_output_limit=500)
    def seed(self,n=12,long=False):
        rows=[]
        for i in range(n):
            text='Q'*1100 if long else 'PHONE_Q'+str(i)
            r=fixtures.receipt(self.h.server,self.h.sync.scope,self.h.sid,text,source=copy.deepcopy(self.h.src))
            rows.append(fixtures.turn(i,r,text))
        b=copy.deepcopy(self.h.b);b['turns']=rows;self.archive.exchange(self.h.device,b)
        with self.archive.connection(True) as db:db.execute("UPDATE pr_receipts SET received_at='2000-01-01T00:00:00Z'")
    def run_summary(self):
        with self.h.h.scope(study=False):return self.manager.summarize(self.store,self.store.session_id)
    def rows(self):
        with self.store.read_connection() as db:return [dict(r) for r in db.execute('SELECT * FROM rc_phone_summary_meta')]
    def export(self,v2=True):
        value=self.h.sync.exchange({'snapshot':empty(self.h.sync.scope),'capabilities':['gernze-research-cache-v2' if v2 else 'gernze-research-cache-v1']})['research'];self.packets.append(value);return value
    def reject_root(self):
        src=self.h.src
        with self.store.connection() as db:db.execute('INSERT OR REPLACE INTO rc_summary_reviews VALUES (?,?,?,?,?,?)',(src['id'],src['revision'],src['body_hash'],'reject','synthetic',stamp()))
    def test_worker_commits_phone_delta_sources_and_coverage_together(self):
        self.seed();self.assertEqual(self.run_summary(),'committed');self.assertEqual(len(self.worker.calls),1)
        request=self.worker.calls[0];self.assertEqual(len(request['new_block']),3);self.assertEqual(request['existing_summaries'],[]);self.assertTrue(all(t['origin']=='external_ai' for t in request['new_block']))
        self.assertNotIn('PHONE_Q6',json.dumps(request));meta=self.rows()[0]
        self.assertEqual(len(json.loads(meta['phone_refs'])),3);self.assertEqual(json.loads(meta['parents'])[0]['id'],self.h.src['id'])
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM rc_phone_summary_coverage').fetchone()[0],3)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lm_working').fetchone()[0],0);self.assertEqual(db.execute('SELECT COUNT(*) FROM lm_approved').fetchone()[0],0)
    def test_budget_gate_reads_no_phone_body(self):
        self.seed(long=True);queries=[];original=sqlite3.connect
        def trace(*a,**kw):db=original(*a,**kw);db.set_trace_callback(queries.append);return db
        with patch('sqlite3.connect',trace):self.assertEqual(self.run_summary(),'input_too_large')
        self.assertEqual(self.worker.calls,[]);self.assertFalse(any(q.startswith('SELECT payload FROM phone_raw.pr_bodies') for q in queries))
    def test_rejected_root_is_filtered_before_body(self):
        self.seed();self.reject_root();self.store.trace=None;queries=[];original=sqlite3.connect
        def trace(*a,**kw):db=original(*a,**kw);db.set_trace_callback(queries.append);return db
        with patch('sqlite3.connect',trace):self.assertEqual(self.run_summary(),'not_due')
        self.assertEqual(self.worker.calls,[]);self.assertFalse(any(q.startswith('SELECT payload FROM phone_raw.pr_bodies') for q in queries))
    def test_failure_rolls_back_summary_body_and_coverage(self):
        self.seed()
        with self.store.connection() as db:db.execute("CREATE TRIGGER fail_phone BEFORE INSERT ON rc_phone_summary_coverage BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        self.assertEqual(self.run_summary(),'storage_failed')
        with self.store.read_connection() as db:
            for table in ['rc_phone_summary_meta','rc_phone_summary_bodies','rc_phone_summary_coverage']:self.assertEqual(db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0)
        self.assertEqual(len(self.archive.metadata()),12)
    def test_reject_during_worker_discards_entire_result(self):
        self.seed();self.worker.callback=self.reject_root;self.assertIn(self.run_summary(),('storage_failed','stale'));self.assertEqual(self.rows(),[])
    def test_epoch_change_during_worker_discards_result(self):
        self.seed();self.worker.callback=lambda:self.store.retire_context('synthetic');self.assertEqual(self.run_summary(),'stale');self.assertEqual(self.rows(),[])
    def test_provider_wait_holds_neither_journal_nor_archive_writer(self):
        self.seed();ok=[]
        def change():
            with self.store.connection() as db:db.execute("INSERT OR REPLACE INTO rc_meta VALUES ('synthetic_probe','1')")
            with self.archive.connection(True) as db:db.execute('UPDATE pr_schema SET version=2')
            ok.append(True)
        self.worker.callback=change;self.assertEqual(self.run_summary(),'committed');self.assertEqual(ok,[True])
    def test_attachment_denies_archive_writes_during_journal_commit(self):
        from workbench.phone_research_summaries import attach
        self.seed()
        with self.store.connection() as db:
            attach(db,self.store.path)
            with self.assertRaises(sqlite3.DatabaseError):db.execute('UPDATE phone_raw.pr_schema SET version=9')
            db.execute("INSERT OR REPLACE INTO rc_meta VALUES ('synthetic_local','1')")
        with self.archive.connection() as db:self.assertEqual(db.execute('SELECT version FROM pr_schema').fetchone()[0],2)
    def test_cancel_during_worker_never_commits(self):
        self.seed();self.worker.callback=self.manager.cancel;self.assertEqual(self.run_summary(),'cancelled');self.assertEqual(self.rows(),[])
    def test_failed_attempt_does_not_immediately_rebill(self):
        self.seed();self.worker.callback=lambda:(_ for _ in ()).throw(ValueError('synthetic'));self.assertEqual(self.run_summary(),'failed');self.worker.callback=None
        self.assertEqual(self.run_summary(),'not_due');self.assertEqual(len(self.worker.calls),1)
    def test_disabled_and_not_due_keep_existing_api_budget(self):
        self.seed();self.chat.layers.configure({'summaryEnabled':False,'summaryDays':1,'reviewDays':None});self.assertEqual(self.run_summary(),'disabled');self.assertEqual(self.worker.calls,[])
    def test_unknown_legacy_receipts_are_not_reconstructed(self):
        self.seed()
        with self.archive.connection(True) as db:db.execute('DROP TABLE pr_receipts');db.execute('UPDATE pr_schema SET version=1')
        self.assertEqual(self.run_summary(),'not_due');self.assertEqual(self.worker.calls,[]);self.assertEqual(len(self.archive.metadata()),12)
    def test_v2_cache_preserves_phone_refs_v1_reads_no_new_body(self):
        self.seed();self.assertEqual(self.run_summary(),'committed');v2=self.export();derived=next(r for r in v2['records'] if r['phone_refs'])
        self.assertEqual(v2['format'],'gernze-research-cache-v2');self.assertEqual(len(derived['phone_refs']),3);self.assertEqual(derived['body'],self.worker.text);self.assertEqual(derived['review']['status'],'pending')
        self.h.h.events.clear();v1=self.export(False);self.assertEqual(v1['format'],'gernze-research-cache-v1');self.assertTrue(all('phone_refs' not in r for r in v1['records']));self.assertFalse(any('SELECT body FROM rc_phone_summary_bodies' in q for q in self.h.h.events))
    def test_retraction_removes_derived_cache_without_loading_new_body(self):
        self.seed();self.run_summary();self.reject_root();self.h.h.events.clear();packet=self.export();self.assertEqual(packet['records'],[]);self.assertFalse(any('SELECT body FROM rc_phone_summary_bodies' in q for q in self.h.h.events))
    def test_v2_receipt_roundtrips_and_changed_root_invalidates_it(self):
        self.seed();self.run_summary();derived=next(r for r in self.export()['records'] if r['phone_refs']);src={k:v for k,v in derived.items() if k!='body'}
        r=fixtures.receipt(self.h.server,self.h.sync.scope,'derived',source=src);r['format']=USE_FORMAT_V2
        b=copy.deepcopy(self.h.b);b['sessionId']='derived';b['turns']=[fixtures.turn(0,r)];self.archive.exchange(self.h.device,b)
        self.assertEqual(self.archive.source_status(r),'current');self.reject_root();self.assertEqual(self.archive.source_status(r),'changed');self.assertEqual(self.archive.raw(self.h.device,'derived',0)['research'],r)
    def test_second_generation_not_automatically_compressed_again(self):
        self.seed();self.run_summary();derived=next(r for r in self.export()['records'] if r['phone_refs']);src={k:v for k,v in derived.items() if k!='body'};b=copy.deepcopy(self.h.b);b['sessionId']='derived'
        b['turns']=[]
        for i in range(12):
            r=fixtures.receipt(self.h.server,self.h.sync.scope,'derived',source=copy.deepcopy(src));r['format']=USE_FORMAT_V2;b['turns'].append(fixtures.turn(i,r))
        self.archive.exchange(self.h.device,b)
        with self.archive.connection(True) as db:db.execute("UPDATE pr_receipts SET received_at='2000-01-01T00:00:00Z'")
        self.assertEqual(self.run_summary(),'not_due');self.assertEqual(len(self.worker.calls),1)
    def test_own_verdict_or_raw_hash_change_prevents_replay(self):
        self.seed();self.run_summary();meta=self.rows()[0]
        with self.archive.connection(True) as db:db.execute("UPDATE pr_meta SET content_hash=? WHERE seq=0",('a'*64,))
        with self.store.read_connection() as db:
            with self.assertRaises(ValueError):verify(self.store,db,reference(meta),ResearchAccess())
        self.assertFalse(any(r['phone_refs'] for r in self.export()['records']))
    def test_ordinary_readonly_directory_never_opens_new_summary_body(self):
        self.seed();self.run_summary();self.h.h.events.clear();archive=MemoryArchive(self.chat);archive.months();archive.days(day_of(stamp())[:7]);archive.status()
        self.assertFalse(any('SELECT body FROM rc_phone_summary_bodies' in q for q in self.h.h.events))
        self.assertTrue(any('PHONE_DELTA_SUMMARY' in e['text'] for e in archive.day(day_of(stamp()))['entries']))
    def test_adapter_request_uses_existing_output_protocol(self):
        from workbench.summary_adapter import validate_request
        self.seed();self.run_summary();request,ids=validate_request(self.worker.calls[0]);self.assertEqual(tuple(request['source_turn_ids']),ids);self.assertEqual(request['max_output_units'],500)

if __name__=='__main__':unittest.main(verbosity=2)
