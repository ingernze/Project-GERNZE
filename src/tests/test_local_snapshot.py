"""Safety and stale-data behavior using synthetic records only."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from hebao_quota.local_snapshot import read_local_history, history_view

NOW = 1791005200

def record(stamp="2026-10-03T05:25:26Z", used=36, reset=1791019327):
    return {"type":"event_msg","timestamp":stamp,"payload":{"type":"token_count",
            "rate_limits":{"limit_id":"codex","primary":{"used_percent":used,
            "window_minutes":300,"resets_at":reset},"secondary":{
            "used_percent":6,"window_minutes":10080,"resets_at":1791606127}}}}

class LocalSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)/"sessions"
        self.root.mkdir()
    def tearDown(self): self.temp.cleanup()
    def write(self,name,items):
        path=self.root/name
        path.write_text("\n".join(json.dumps(x) for x in items)+"\n",encoding="utf-8")
        return path
    def test_real_structure_never_claims_current_account_even_with_metadata(self):
        self.write("rollout-a.jsonl",[{"type":"session_meta","payload":{
            "creator_account_id":"synthetic-account"}},record()])
        result=read_local_history(self.root,now=NOW)
        view=history_view(result,now=NOW)
        self.assertFalse(result.current_account_verified)
        self.assertEqual(view["current"],"未知")
        self.assertEqual(view["rows"][0],("5 小时","当时剩余 64%"))
    def test_selects_event_time_instead_of_file_modification_or_body_text(self):
        newest=self.write("rollout-a.jsonl",[record()])
        old=self.write("rollout-b.jsonl",[record(stamp="2026-10-03T04:00:00Z",used=1)])
        os.utime(old,(NOW+500,NOW+500))
        self.write("rollout-c.jsonl",[{"type":"response_item","payload":record()}])
        self.assertEqual(read_local_history(self.root,now=NOW).windows[0].used_percent,36)
    def test_missing_invalid_windows_and_future_records_do_not_invent_zero(self):
        broken=record(used=True);broken["payload"]["rate_limits"]["secondary"]=None
        self.write("rollout-a.jsonl",[broken,record(stamp="2030-10-03T05:25:26Z")])
        self.assertIsNone(read_local_history(self.root,now=NOW))
        self.assertEqual(history_view(None)["current"],"未知")
    def test_expired_window_is_unknown_not_reset_to_full(self):
        self.write("rollout-a.jsonl",[record(reset=NOW-1)])
        view=history_view(read_local_history(self.root,now=NOW),now=NOW)
        self.assertEqual(view["rows"][0],("5 小时","已过期"))
        self.assertEqual(view["current"],"未知")
    def test_old_snapshot_is_explicitly_stale(self):
        self.write("rollout-a.jsonl",[record()])
        view=history_view(read_local_history(self.root,now=NOW),now=NOW+2000)
        self.assertEqual(view["status"],"旧记录 · 非实时")
    def test_does_not_read_credentials_or_unrelated_files(self):
        self.write("auth.json",[record()])
        self.write("notes.jsonl",[record()])
        self.assertIsNone(read_local_history(self.root,now=NOW))
    def test_partial_record_and_cancellation_are_safe(self):
        path=self.write("rollout-a.jsonl",[record()])
        with path.open("a") as stream: stream.write('{"type":"event_msg"')
        self.assertIsNotNone(read_local_history(self.root,now=NOW))
        cancel=threading.Event();cancel.set()
        self.assertIsNone(read_local_history(self.root,now=NOW,cancel=cancel))

if __name__=="__main__": unittest.main()

