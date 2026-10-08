import unittest
from idle_blink import BlinkLottery
class Rng:
    def __init__(self,interval=2):self.interval=interval
    def uniform(self,a,b):return self.interval
    def random(self):raise AssertionError('No probability draw is allowed')
class BlinkLotteryTests(unittest.TestCase):
    def test_every_due_interval_triggers_blink(self):
        now=[0];schedule=BlinkLottery(lambda:now[0],Rng(2))
        self.assertFalse(schedule.draw())
        now[0]=4;self.assertTrue(schedule.draw());self.assertEqual(schedule.due,8)
        self.assertFalse(schedule.draw())
        now[0]=8;self.assertTrue(schedule.draw());self.assertEqual(schedule.due,12)
    def test_breathing_aligned_interval_is_within_3_to_5_seconds(self):
        now=[0];schedule=BlinkLottery(lambda:now[0],Rng(3))
        self.assertTrue(3<=schedule.due<=5)
        now[0]=3.99;self.assertFalse(schedule.draw())
        now[0]=4;self.assertTrue(schedule.draw());self.assertEqual(schedule.due,8)
    def test_interruption_restarts_wait(self):
        now=[0];schedule=BlinkLottery(lambda:now[0],Rng(2))
        now[0]=3;schedule.reset();self.assertEqual(schedule.due,7)
        now[0]=6;self.assertFalse(schedule.draw())
