import concurrent.futures
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from workbench.entrance import EntranceSession
from workbench_host import WorkbenchHost


class EntranceSessionChecks(unittest.TestCase):
    def test_concurrent_claims_allow_only_one_page(self):
        gate = EntranceSession()
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            self.assertEqual(sum(pool.map(lambda _: gate.claim(), range(48))), 1)

    def call(self, server, *, authorized=True, params=None):
        c = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=4)
        headers = {'Content-Type': 'application/json'}
        if authorized:
            headers['Authorization'] = 'Bearer ' + server.token
        try:
            c.request('POST', '/api/call', json.dumps({'command':'arrival.claim','params':params or {}}), headers)
            r = c.getresponse()
            return r.status, json.loads(r.read())
        finally:
            c.close()

    def test_reopen_same_desktop_skips_new_desktop_resets(self):
        with tempfile.TemporaryDirectory(prefix='hebao-entrance-') as folder:
            hosts = []
            try:
                host = WorkbenchHost(folder, Path(__file__).resolve().parents[1], lambda *a, **k:None)
                hosts.append(host)
                s = host.open(launch_browser=False)
                self.assertEqual(self.call(s), (200, {'result':{'play':True}}))
                self.assertEqual(self.call(s), (200, {'result':{'play':False}}))
                host.close_service()
                reopened = host.open(launch_browser=False)
                self.assertIsNot(reopened, s)
                self.assertEqual(self.call(reopened), (200, {'result':{'play':False}}))
                host.close()
                fresh = WorkbenchHost(folder, Path(__file__).resolve().parents[1], lambda *a, **k:None)
                hosts.append(fresh)
                self.assertEqual(self.call(fresh.open(launch_browser=False)), (200, {'result':{'play':True}}))
            finally:
                for host in hosts: host.close()

    def test_unauthorized_and_invalid_requests_do_not_consume_entrance(self):
        with tempfile.TemporaryDirectory(prefix='hebao-entrance-') as folder:
            host = WorkbenchHost(folder, Path(__file__).resolve().parents[1], lambda *a, **k:None)
            try:
                s = host.open(launch_browser=False)
                self.assertEqual(self.call(s, authorized=False)[0], 403)
                self.assertEqual(self.call(s, params={'reset':True})[0], 400)
                self.assertEqual(self.call(s)[1], {'result':{'play':True}})
            finally: host.close()

    def test_reload_claim_cancels_page_leave_deadline(self):
        with tempfile.TemporaryDirectory(prefix='hebao-entrance-') as folder:
            host = WorkbenchHost(folder, Path(__file__).resolve().parents[1], lambda *a, **k:None)
            try:
                s = host.open(launch_browser=False)
                self.call(s)
                s.leave()
                self.assertIsNotNone(s.leave_timer)
                self.assertFalse(self.call(s)[1]['result']['play'])
                self.assertIsNone(s.leave_timer)
            finally: host.close()
