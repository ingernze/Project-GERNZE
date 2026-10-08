"""Offline checks for balance transitions; no Windows credentials or API calls."""
from __future__ import annotations

from decimal import Decimal
import threading
import time
import unittest

from hebao_quota.models import Balance, Snapshot
from hebao_quota.service import QuotaService
from quota_card import CardState, present


def sample(total="48.50"):
    return Snapshot("deepseek", "offline-test", "offline-test", time.time(),
                    balances=(Balance("CNY", Decimal(total), Decimal("40.00"),
                                      Decimal("8.50")),), available=True)


def wait_for(predicate, seconds=1.5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


class ImmediateProvider:
    def __init__(self):
        self.calls = 0
        self.lock = threading.Lock()

    def fetch(self, _cancel):
        with self.lock:
            self.calls += 1
            number = self.calls
        return sample(str(number))

    def close(self):
        pass


class BlockingProvider:
    def __init__(self):
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()

    def fetch(self, _cancel):
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            self.release.wait(1.0)
        return sample(str(self.calls))

    def close(self):
        self.release.set()


class FrontendTransitions(unittest.TestCase):
    def test_card_never_invents_zero_and_marks_failed_result_stale(self):
        blank = present(CardState())
        self.assertIsNone(blank["main"])
        self.assertEqual(blank["short"], "未保存密钥")
        old = present(CardState(key_present=True, enabled=True, snapshot=sample(),
                                error="网络连接失败"))
        self.assertIn("旧余额", old["short"])
        self.assertEqual(old["main"][1], "48.50")

    def test_show_resumes_auto_after_interval_and_hidden_cancels(self):
        provider = ImmediateProvider()
        svc = QuotaService({"deepseek":provider}, interval_s=.13,
                           manual_cooldown_s=.05)
        try:
            svc.configure(enabled=False, visible=True, active="deepseek")
            self.assertEqual(provider.calls, 0)
            svc.configure(enabled=True, visible=True, active="deepseek")
            self.assertTrue(wait_for(lambda: provider.calls == 1))
            self.assertTrue(wait_for(lambda: not svc.read_state().busy))
            self.assertFalse(svc.refresh(force=True))  # five-minute rule, scaled
            svc.configure(enabled=True, visible=False, active="deepseek")
            self.assertIsNone(svc.read_state().next_auto_remaining)
            svc.configure(enabled=True, visible=True, active="deepseek")
            self.assertIsNotNone(svc.read_state().next_auto_remaining)
            self.assertTrue(wait_for(lambda: provider.calls >= 2))
            svc.configure(enabled=True, visible=False, active="deepseek")
            stopped_at = provider.calls
            time.sleep(.18)
            self.assertEqual(provider.calls, stopped_at)
        finally:
            svc.close()

    def test_account_change_while_disabled_resets_previous_cooldown(self):
        provider = ImmediateProvider()
        svc = QuotaService({"deepseek": provider}, interval_s=900,
                           manual_cooldown_s=300)
        try:
            svc.configure(enabled=True, visible=True, active="deepseek")
            self.assertTrue(wait_for(lambda: provider.calls == 1))
            self.assertTrue(wait_for(lambda: not svc.read_state().busy))
            svc.configure(enabled=False, visible=True, active=None)
            svc.invalidate("deepseek")
            self.assertEqual(svc.read_state().manual_cooldown_remaining, 0)
            self.assertEqual(provider.calls, 1)
            svc.configure(enabled=True, visible=True, active="deepseek")
            self.assertTrue(wait_for(lambda: provider.calls == 2))
        finally:
            svc.close()

    def test_account_change_discards_inflight_old_balance(self):
        provider = BlockingProvider()
        svc = QuotaService({"deepseek":provider}, interval_s=5,
                           manual_cooldown_s=5)
        try:
            svc.configure(enabled=True, visible=True, active="deepseek")
            self.assertTrue(provider.started.wait(.6))
            svc.invalidate()  # user saved a different key; old worker is stale
            provider.release.set()
            self.assertTrue(wait_for(lambda: provider.calls == 2))
            self.assertTrue(wait_for(lambda: not svc.read_state().busy))
            results,_ = svc.drain()
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].snapshot.balances[0].total, Decimal("2"))
        finally:
            svc.close()


if __name__ == "__main__":
    unittest.main()
