from contextlib import closing
import concurrent.futures
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'update-publisher'))
from event_outbox import EventOutbox, EventError, AuthenticatedPeer, canonical
from event_routes import EventRoutes

A='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
B='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
NOW=2000000000000


def event(i=1, **changes):
    result={'event_id':str(uuid.UUID(int=i)), 'created_at':NOW,'expires_at':NOW+100000,
            'type':'task_completed','title':'任务完成','body':'合成报告已经准备好。','target':{'page':'messages'}}
    result.update(changes)
    return result


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'events.sqlite3';self.now=NOW
        self.box=EventOutbox(self.path,clock=lambda:self.now,max_per_peer=4)
        self.a=AuthenticatedPeer(A);self.b=AuthenticatedPeer(B)
    def tearDown(self):self.temp.cleanup()
    def push(self,i=1,peer=A,**changes):return self.box.enqueue({'peer_id':peer,'event':event(i,**changes)})
    def error(self,code,fn):
        with self.assertRaises(EventError) as caught:fn()
        self.assertEqual(caught.exception.code,code)
    def test_peer_isolation_and_cross_peer_ack(self):
        self.push();self.push(2,B)
        self.box.ack(self.b,[event()['event_id']])
        self.assertEqual([r['event']['event_id'] for r in self.box.fetch(self.a,0)['events']],[event()['event_id']])
        self.assertEqual([r['event']['event_id'] for r in self.box.fetch(self.b,0)['events']],[event(2)['event_id']])
        self.error('authentication_failed',lambda:self.box.fetch(A,0))
    def test_producer_retry_and_conflicting_reuse(self):
        self.assertEqual(self.push()['cursor'],1);self.assertEqual(self.push()['status'],'duplicate')
        self.error('event_conflict',lambda:self.push(body='别的内容'))
        self.box.ack(self.a,[event()['event_id']]);self.assertTrue(self.push()['acked'])
        with closing(sqlite3.connect(self.path)) as db, db:self.assertIsNone(db.execute('SELECT payload FROM events').fetchone()[0])
    def test_ack_retry_and_unknown_ids_are_safe(self):
        self.push();ids=[event()['event_id']]
        self.assertEqual(self.box.ack(self.a,ids),self.box.ack(self.a,ids))
        self.box.ack(self.a,[str(uuid.uuid4())]);self.assertEqual(self.box.fetch(self.a,0)['events'],[])
    def test_reopen_keeps_stream_monotonic_cursor_and_receipts(self):
        self.push();old=self.box.fetch(self.a,0)
        box=EventOutbox(self.path,clock=lambda:self.now,max_per_peer=4)
        self.assertEqual(box.fetch(self.a,0),old)
        self.assertEqual(box.enqueue({'peer_id':A,'event':event(2)})['cursor'],2)
        self.error('cursor_ahead',lambda:box.fetch(self.a,3))
        self.error('stream_reset',lambda:box.fetch(self.a,0,stream_id=str(uuid.uuid4())))
    def test_pagination_old_cursor_and_reordered_ack(self):
        for i in range(1,5):self.push(i)
        first=self.box.fetch(self.a,0,2);self.assertTrue(first['has_more']);self.assertEqual(first['next_cursor'],2)
        self.box.ack(self.a,[event(4)['event_id'],event(1)['event_id']])
        second=self.box.fetch(self.a,first['next_cursor'],2);self.assertEqual([r['cursor'] for r in second['events']],[3]);self.assertEqual(second['next_cursor'],4)
        self.assertEqual([r['cursor'] for r in self.box.fetch(self.a,0)['events']],[2,3])
    def test_nonprefix_expiry_reports_gap_without_skipping_live_older_row(self):
        self.push();self.push(2,expires_at=NOW+10);self.now+=11
        result=self.box.fetch(self.a,0)
        self.assertEqual(result['gap'],{'lost_through':2});self.assertEqual([r['cursor'] for r in result['events']],[1])
        self.assertEqual(result['next_cursor'],2)
    def test_queue_bound_expiry_and_ack_tombstone_retention(self):
        for i in range(1,5):self.push(i)
        self.error('queue_full',lambda:self.push(5));self.box.ack(self.a,[event()['event_id']])
        self.error('queue_full',lambda:self.push(5))  # Receipt retained for idempotency, not unbounded growth.
        self.now+=100001;self.assertEqual(self.push(5,created_at=self.now,expires_at=self.now+100)['cursor'],5)
        self.error('event_expired',lambda:self.push(1))
    def test_strict_target_text_types_and_limits(self):
        for change in ({'target':{'page':'study'}},{'target':{'page':'messages','url':'http://x'}},{'target':{'page':'messages','event_id':str(uuid.uuid4())}}, {'title':'x'*61},{'body':'x'*401},{'body':'bad\nline'},{'created_at':True},{'type':'run_command'},{'expires_at':NOW+604800001}):
            self.error('invalid_input',lambda c=change:self.push(**c))
        bad=event();bad['command']='exit';self.error('invalid_input',lambda:self.box.enqueue({'peer_id':A,'event':bad}))
    def test_dispatcher_rejects_identity_in_body_duplicates_and_floats(self):
        route=EventRoutes(self.box);body={'schema':1,'cursor':0,'limit':6,'stream_id':None}
        self.error('authentication_failed',lambda:route.dispatch('/v1/events/fetch',canonical(body),None))
        self.error('invalid_input',lambda:route.dispatch('/v1/events/fetch',b'{"schema":1,"schema":1}',self.a))
        self.error('invalid_input',lambda:route.dispatch('/v1/events/fetch',b'{"cursor":0.0}',self.a))
        body['pairingId']=B;self.error('invalid_input',lambda:route.dispatch('/v1/events/fetch',canonical(body),self.a))
        self.error('invalid_input',lambda:route.dispatch('/v1/events/fetch',b'x'*4097,self.a))
    def test_parallel_duplicate_enqueue_is_one_transaction(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:self.push(),range(8)))
        self.assertEqual(sum(x['status']=='enqueued' for x in results),1)
        self.assertEqual(len(self.box.fetch(self.a,0)['events']),1)
    def test_peer_limit_explicit_revocation_cleanup(self):
        box=EventOutbox(self.path,clock=lambda:self.now,max_peers=1)
        box.fetch(self.a,0);self.error('queue_full',lambda:box.fetch(self.b,0))
        box.drop_revoked_peer(self.a);self.assertEqual(box.fetch(self.b,0)['events'],[])
    def test_response_fits_frozen_pinned_http_16k_limit(self):
        box=EventOutbox(self.path,clock=lambda:self.now,max_per_peer=8)
        for i in range(1,7):box.enqueue({'peer_id':A,'event':event(i,title='星'*60,body='好'*400)})
        result=box.fetch(self.a,0,6);self.assertLessEqual(len(canonical(result)),16384)

if __name__=='__main__':unittest.main(verbosity=2)
