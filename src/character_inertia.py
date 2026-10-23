"""Dependency-free release inertia; coordinates/velocities are px and px/s.

Own implementation based on published inertia behaviour, not copied JS code.
No threads, global hooks, periodic idle tasks, gravity, or asset changes.
"""
from collections import deque
from dataclasses import dataclass
import math
import time


@dataclass(frozen=True)
class InertiaConfig:
    sample_window: float = 0.12
    stale_after: float = 0.08
    minimum_sample_time: float = 0.02
    launch_speed: float = 45.0
    stop_speed: float = 10.0
    resistance: float = 6.0
    max_speed: float = 2200.0
    max_distance: float = 500.0
    max_duration: float = 1.2
    tick_ms: int = 16

    def __post_init__(self):
        for name, value in vars(self).items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.stop_speed >= self.launch_speed:
            raise ValueError("stop_speed must be below launch_speed")
        if self.minimum_sample_time > self.sample_window:
            raise ValueError("minimum_sample_time exceeds sample_window")
        if not isinstance(self.tick_ms, int):
            raise ValueError("tick_ms must be an integer")


@dataclass(frozen=True)
class Bounds:
    """Inclusive limits for the WINDOW TOP LEFT, not screen right/bottom."""
    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self):
        if not all(math.isfinite(v) for v in vars(self).values()):
            raise ValueError("bounds must be finite")
        if self.left > self.right or self.top > self.bottom:
            raise ValueError("empty bounds; account for window dimensions")

    def clamp(self, x, y):
        return min(self.right, max(self.left, x)), min(self.bottom, max(self.top, y))


@dataclass(frozen=True)
class Frame:
    x: float
    y: float
    vx: float
    vy: float
    active: bool


class ReleaseVelocity:
    def __init__(self, config=None):
        self.config = config or InertiaConfig()
        self.samples = deque()
        self.last_movement = None

    def reset(self, x, y, now):
        self.samples.clear()
        self.last_movement = None
        self.add(x, y, now)

    def add(self, x, y, now):
        if not all(math.isfinite(v) for v in (x, y, now)):
            raise ValueError("sample must be finite")
        if self.samples:
            old_t, old_x, old_y = self.samples[-1]
            if now < old_t:
                return  # Ignore out-of-order events; never divide by negative time.
            if x != old_x or y != old_y:
                self.last_movement = now
            if now == old_t:
                self.samples[-1] = (now, x, y)
                return
        self.samples.append((now, x, y))
        cutoff = now - self.config.sample_window
        while len(self.samples) > 2 and self.samples[1][0] < cutoff:
            self.samples.popleft()

    def release(self, x, y, now):
        self.add(x, y, now)  # Include release time, including a stationary pause.
        c = self.config
        if self.last_movement is None or now - self.last_movement >= c.stale_after:
            return 0.0, 0.0
        points = [p for p in self.samples if now - c.sample_window <= p[0] <= now]
        if len(points) < 2 or points[-1][0] - points[0][0] < c.minimum_sample_time:
            return 0.0, 0.0
        # Recent-window least squares avoids estimating from the entire drag.
        # Subtract a local origin to keep large monotonic timestamps accurate.
        base = points[0][0]
        ts = [p[0] - base for p in points]
        mean_t = sum(ts) / len(ts)
        denominator = sum((t - mean_t) ** 2 for t in ts)
        if denominator <= 0:
            return 0.0, 0.0
        return tuple(sum((t - mean_t) * p[axis] for t, p in zip(ts, points))
                     / denominator for axis in (1, 2))


class InertiaMotion:
    def __init__(self, config=None):
        self.config = config or InertiaConfig()
        self.frame = Frame(0, 0, 0, 0, False)

    def start(self, position, velocity, now, bounds):
        if not all(math.isfinite(v) for v in (*position, *velocity, now)):
            raise ValueError("position, velocity and time must be finite")
        self.bounds = bounds
        self.origin = bounds.clamp(*position)
        vx, vy = velocity
        x, y = self.origin
        if (x <= bounds.left and vx < 0) or (x >= bounds.right and vx > 0):
            vx = 0.0
        if (y <= bounds.top and vy < 0) or (y >= bounds.bottom and vy > 0):
            vy = 0.0
        speed = math.hypot(vx, vy)
        cap = min(self.config.max_speed,
                  self.config.resistance * self.config.max_distance)
        if speed > cap:
            vx, vy = vx * cap / speed, vy * cap / speed
            speed = cap
        self.initial_velocity = (vx, vy)
        self.started = self.last_time = now
        if speed < self.config.launch_speed:
            self.duration = 0.0
            self.frame = Frame(x, y, 0, 0, False)
        else:
            self.duration = min(self.config.max_duration,
                                math.log(speed / self.config.stop_speed)
                                / self.config.resistance)
            self.frame = Frame(x, y, vx, vy, True)
        return self.frame

    def update(self, now):
        if not self.frame.active:
            return self.frame
        if not math.isfinite(now):
            raise ValueError("time must be finite")
        self.last_time = max(self.last_time, now)
        elapsed = min(self.duration, self.last_time - self.started)
        decay = math.exp(-self.config.resistance * elapsed)
        distance_factor = -math.expm1(-self.config.resistance * elapsed) / self.config.resistance
        vx, vy = self.initial_velocity
        raw_x = self.origin[0] + vx * distance_factor
        raw_y = self.origin[1] + vy * distance_factor
        x, y = self.bounds.clamp(raw_x, raw_y)
        vx, vy = vx * decay, vy * decay
        if raw_x <= self.bounds.left or raw_x >= self.bounds.right:
            vx = 0.0
        if raw_y <= self.bounds.top or raw_y >= self.bounds.bottom:
            vy = 0.0
        active = elapsed < self.duration and math.hypot(vx, vy) > self.config.stop_speed
        self.frame = Frame(x, y, vx if active else 0.0, vy if active else 0.0, active)
        return self.frame

    def cancel(self):
        self.frame = Frame(self.frame.x, self.frame.y, 0, 0, False)


class CoastController:
    """Tk-compatible scheduler adapter. Call every method on the Tk main thread.

    scheduler: object with after(ms, callback) and after_cancel(id).
    place(x, y): move your actual pet window in SCREEN coordinates.
    state_changed: dragging/coasting/idle; keep existing pose handling here.
    settled(x, y): persist final position once, after stopping (not each tick).
    begin/move/release receive pointer positions and actual window positions.
    Cancel BEFORE tray hide, resize/reposition, switching actions or destruction.
    """
    def __init__(self, scheduler, place, state_changed=None, settled=None,
                 config=None, clock=time.perf_counter):
        self.config = config or InertiaConfig()
        self.scheduler, self.place, self.clock = scheduler, place, clock
        self.state_changed = state_changed or (lambda state: None)
        self.settled = settled or (lambda x, y: None)
        self.velocity = ReleaseVelocity(self.config)
        self.motion = InertiaMotion(self.config)
        self.pending = None
        self.generation = 0
        self.dragging = self.closed = False
        self.state = "idle"
        self.position = (0.0, 0.0)

    def _state(self, state):
        if self.state != state:
            self.state = state
            self.state_changed(state)

    def begin(self, pointer, position):
        if self.closed:
            return
        self.cancel(notify=False)
        self.position = position
        self.velocity.reset(*pointer, self.clock())
        self.dragging = True
        self._state("dragging")

    def move(self, pointer, position):
        if self.dragging and not self.closed:
            self.position = position
            self.velocity.add(*pointer, self.clock())

    def release(self, pointer, position, bounds):
        if not self.dragging or self.closed:
            return
        self.dragging = False
        now = self.clock()
        velocity = self.velocity.release(*pointer, now)
        frame = self.motion.start(position, velocity, now, bounds)
        generation = self.generation
        self.position = (frame.x, frame.y)
        self.place(*self.position)
        if generation != self.generation or self.closed:
            return
        if frame.active:
            self._state("coasting")
            # A pose callback may hide/close/regrab synchronously.
            if (generation == self.generation and self.motion.frame.active
                    and not self.closed and not self.dragging):
                self._schedule()
        else:
            self._finish()

    def _schedule(self):
        if self.pending is None:
            generation = self.generation
            self.pending = self.scheduler.after(self.config.tick_ms,
                                                lambda: self._tick(generation))

    def _tick(self, generation):
        if generation != self.generation or self.closed:
            return
        self.pending = None
        frame = self.motion.update(self.clock())
        self.position = (frame.x, frame.y)
        self.place(*self.position)
        # Guard callbacks which change state while placement is being applied.
        if generation != self.generation or self.closed:
            return
        if frame.active:
            self._schedule()
        else:
            self._finish()

    def _finish(self):
        generation = self.generation
        self._state("idle")
        if generation == self.generation and not self.closed:
            self.settled(*self.position)

    def cancel(self, notify=True):
        was_active = self.dragging or self.motion.frame.active
        self.generation += 1
        if self.pending is not None:
            self.scheduler.after_cancel(self.pending)
            self.pending = None
        self.dragging = False
        self.motion.cancel()
        if notify and was_active:
            self._finish()

    def close(self):
        self.cancel(notify=False)
        self.closed = True
