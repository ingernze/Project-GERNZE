import math
import unittest
from hebao_inertia import Bounds, CoastController, InertiaConfig, InertiaMotion, ReleaseVelocity

AREA = Bounds(-10000, -10000, 10000, 10000)


class VelocityTests(unittest.TestCase):
    def sampler(self):
        s = ReleaseVelocity()
        s.reset(0, 0, 1000)
        for i in range(1, 7):
            s.add(i * 20, i * -10, 1000 + i * 0.02)
        return s

    def test_fast_flick_has_direction_and_speed(self):
        vx, vy = self.sampler().release(120, -60, 1000.12)
        self.assertAlmostEqual(vx, 1000, places=6)
        self.assertAlmostEqual(vy, -500, places=6)

    def test_stationary_pause_erases_old_throw(self):
        self.assertEqual(self.sampler().release(120, -60, 1000.3), (0, 0))

    def test_press_and_release_without_motion(self):
        s = ReleaseVelocity()
        s.reset(5, 5, 0)
        self.assertEqual(s.release(5, 5, 0.2), (0, 0))

    def test_duplicate_timestamps_do_not_create_infinite_velocity(self):
        s = ReleaseVelocity()
        s.reset(0, 0, 0)
        s.add(100, 0, 0)
        self.assertEqual(s.release(100, 0, 0), (0, 0))

    def test_too_short_sample_is_not_a_throw(self):
        s = ReleaseVelocity()
        s.reset(0, 0, 0)
        self.assertEqual(s.release(100, 0, 0.005), (0, 0))

    def test_recent_reversal_overrides_old_direction(self):
        s = ReleaseVelocity()
        s.reset(0, 0, 0)
        s.add(1000, 0, 1)
        for i in range(1, 11):
            s.add(1000 - 20 * i, 0, 1 + i * 0.02)
        vx, _ = s.release(800, 0, 1.2)
        self.assertLess(vx, -900)

    def test_out_of_order_event_does_not_corrupt_history(self):
        s = self.sampler()
        s.add(99999, 99999, 999)
        vx, vy = s.release(120, -60, 1000.12)
        self.assertAlmostEqual(vx, 1000, places=6)
        self.assertAlmostEqual(vy, -500, places=6)


class MotionTests(unittest.TestCase):
    def motion(self, velocity=(1000, -500), bounds=AREA, position=(0, 0)):
        m = InertiaMotion()
        m.start(position, velocity, 0, bounds)
        return m

    def test_release_preserves_position_and_velocity(self):
        m = self.motion(position=(200, 300))
        self.assertEqual(m.frame, m.update(0))
        self.assertEqual((m.frame.x, m.frame.y), (200, 300))
        self.assertEqual((m.frame.vx, m.frame.vy), (1000, -500))

    def test_30_and_144_hz_agree_at_same_wall_time(self):
        a, b = self.motion(), self.motion()
        for i in range(1, 16):
            a.update(i / 30)
        for i in range(1, 73):
            b.update(i / 144)
        self.assertAlmostEqual(a.frame.x, b.frame.x, places=9)
        self.assertAlmostEqual(a.frame.y, b.frame.y, places=9)

    def test_motion_decays_and_does_not_return_to_origin(self):
        m = self.motion()
        early = m.update(0.1)
        late = m.update(0.3)
        end = m.update(5)
        self.assertGreater(late.x, early.x)
        self.assertLess(abs(late.vx), abs(early.vx))
        self.assertFalse(end.active)
        self.assertGreater(end.x, late.x)
        self.assertEqual(end, m.update(10))

    def test_small_speed_stays_still(self):
        m = self.motion((20, 10))
        self.assertFalse(m.frame.active)
        self.assertEqual((m.update(1).x, m.frame.y), (0, 0))

    def test_diagonal_distance_and_speed_are_capped(self):
        m = self.motion((100000, 100000))
        self.assertLessEqual(math.hypot(m.frame.vx, m.frame.vy), 2200 + 1e-6)
        f = m.update(5)
        self.assertLessEqual(math.hypot(f.x, f.y), 500)

    def test_wall_stops_one_axis_and_keeps_other_sliding(self):
        m = self.motion((1000, 500), Bounds(0, 0, 30, 1000), (10, 10))
        f = m.update(0.1)
        self.assertEqual(f.x, 30)
        self.assertEqual(f.vx, 0)
        self.assertGreater(f.vy, 0)
        self.assertTrue(f.active)

    def test_corner_stops_both_axes(self):
        m = self.motion((1000, 1000), Bounds(0, 0, 30, 30), (10, 10))
        f = m.update(0.1)
        self.assertEqual((f.x, f.y, f.vx, f.vy), (30, 30, 0, 0))
        self.assertFalse(f.active)

    def test_outward_throw_at_edge_does_not_launch(self):
        m = self.motion((-500, 0), Bounds(0, 0, 500, 500))
        self.assertFalse(m.frame.active)

    def test_negative_screen_positions_are_preserved(self):
        m = self.motion((-600, -200), Bounds(-1920, -400, -220, 700), (-500, 0))
        f = m.update(0.2)
        self.assertLess(f.x, -500)
        self.assertLess(f.y, 0)

    def test_delayed_callback_finishes_without_overshoot(self):
        m = self.motion((900, 0), Bounds(0, 0, 100, 100))
        f = m.update(30)
        self.assertFalse(f.active)
        self.assertLessEqual(f.x, 100)

    def test_nonmonotonic_update_does_not_move_backwards(self):
        m = self.motion((900, 0))
        f = m.update(0.2)
        self.assertEqual(f, m.update(0.1))

    def test_cancel_freezes_current_position(self):
        m = self.motion()
        f = m.update(0.2)
        m.cancel()
        stop = m.update(0.5)
        self.assertEqual((stop.x, stop.y), (f.x, f.y))
        self.assertFalse(stop.active)


class FakeScheduler:
    def __init__(self):
        self.now, self.next_id = 0.0, 0
        self.tasks = {}
        self.max_pending = 0

    def after(self, ms, callback):
        self.next_id += 1
        self.tasks[self.next_id] = (self.now + ms / 1000, callback)
        self.max_pending = max(self.max_pending, len(self.tasks))
        return self.next_id

    def after_cancel(self, task):
        self.tasks.pop(task, None)

    def drain(self):
        count = 0
        while self.tasks:
            key = min(self.tasks, key=lambda k: self.tasks[k][0])
            self.now, callback = self.tasks.pop(key)
            callback()
            count += 1
            if count > 200:
                raise AssertionError("timer failed to stop")


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = FakeScheduler()
        self.places, self.states, self.settlements = [], [], []
        self.c = CoastController(self.scheduler, lambda x, y: self.places.append((x, y)),
                                 self.states.append,
                                 lambda x, y: self.settlements.append((x, y)),
                                 clock=lambda: self.scheduler.now)

    def flick(self):
        self.c.begin((0, 0), (10, 10))
        for i in range(1, 6):
            self.scheduler.now = i * 0.02
            self.c.move((i * 20, 0), (10 + i * 20, 10))
        self.c.release((100, 0), (110, 10), AREA)

    def test_idle_and_dragging_do_not_schedule_timers(self):
        self.assertEqual(self.scheduler.tasks, {})
        self.c.begin((0, 0), (10, 10))
        self.scheduler.now = 0.05
        self.c.move((10, 0), (20, 10))
        self.assertEqual(self.scheduler.tasks, {})

    def test_slide_then_idle_and_save_once_with_no_residual_task(self):
        self.flick()
        self.assertEqual(self.c.state, "coasting")
        self.scheduler.drain()
        self.assertEqual(self.states, ["dragging", "coasting", "idle"])
        self.assertEqual(len(self.settlements), 1)
        self.assertEqual(self.scheduler.tasks, {})
        self.assertEqual(self.scheduler.max_pending, 1)
        self.assertGreater(self.settlements[0][0], 110)

    def test_stationary_release_returns_idle_without_timer(self):
        self.c.begin((0, 0), (10, 10))
        self.scheduler.now = 0.1
        self.c.release((0, 0), (10, 10), AREA)
        self.assertEqual(self.states, ["dragging", "idle"])
        self.assertEqual(self.scheduler.tasks, {})

    def test_regrab_invalidates_even_an_already_queued_callback(self):
        self.flick()
        old_callback = next(iter(self.scheduler.tasks.values()))[1]
        self.c.begin((200, 0), (210, 10))
        before = list(self.places)
        old_callback()
        self.assertEqual(self.places, before)
        self.assertEqual(self.c.state, "dragging")
        self.assertEqual(self.scheduler.tasks, {})

    def test_hide_cancel_cleans_timer_and_persists_once(self):
        self.flick()
        self.c.cancel()
        self.c.cancel()
        self.assertEqual(self.scheduler.tasks, {})
        self.assertEqual(self.c.state, "idle")
        self.assertEqual(len(self.settlements), 1)

    def test_close_leaves_no_callback_or_future_launch(self):
        self.flick()
        stale = next(iter(self.scheduler.tasks.values()))[1]
        self.c.close()
        stale()
        self.c.begin((0, 0), (0, 0))
        self.c.release((100, 0), (100, 0), AREA)
        self.assertEqual(self.scheduler.tasks, {})
        self.assertEqual(self.settlements, [])

    def test_repeated_release_does_not_start_a_second_timer(self):
        self.flick()
        pending = dict(self.scheduler.tasks)
        self.c.release((100, 0), (110, 10), AREA)
        self.assertEqual(pending, self.scheduler.tasks)

    def test_close_inside_place_callback_is_respected(self):
        self.c.place = lambda x, y: self.c.close()
        self.flick()
        self.assertEqual(self.scheduler.tasks, {})
        self.assertNotIn("coasting", self.states)


class ConfigTests(unittest.TestCase):
    def test_invalid_settings_are_rejected(self):
        for kwargs in ({"resistance": 0}, {"max_speed": float("inf")},
                       {"stop_speed": 100}, {"tick_ms": 1.5}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                InertiaConfig(**kwargs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
