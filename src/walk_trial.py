"""Manual four-direction walking. Candidate art is never modified in place."""
from bisect import bisect_right
import json
import time
from pathlib import Path

import win32api
import win32con
import win32gui
from PIL import Image, ImageTk
from style_resources import decode_atlas, make_photo

VECTORS = {'up': (0, -1), 'down': (0, 1), 'left': (-1, 0), 'right': (1, 0)}


def position_window(root, x, y):
    hwnd = win32gui.GetAncestor(root.winfo_id(), win32con.GA_ROOT)
    win32gui.SetWindowPos(hwnd, 0, round(x), round(y), 0, 0,
                         win32con.SWP_NOSIZE | win32con.SWP_NOZORDER |
                         win32con.SWP_NOACTIVATE)


def bounded_position(origin, direction, distance, work, size):
    dx, dy = VECTORS[direction]
    x, y = origin[0] + dx * distance, origin[1] + dy * distance
    left, top, right, bottom = work
    return (round(max(left, min(x, max(left, right-size[0])))),
            round(max(top, min(y, max(top, bottom-size[1])))))


def load_action(asset_dir, direction, target_canvas, target_anchor):
    asset_dir = Path(asset_dir).resolve()
    data = json.loads((asset_dir/'manifest.json').read_text(encoding='utf-8'))
    if data.get('renderer') != 'pixel' or data.get('action') != 'walk':
        raise ValueError('Unsupported walking resource manifest')
    if direction not in VECTORS:
        raise ValueError('Unknown walking direction')
    action = data['directions'][direction]
    canvas, anchor = action['canvas'], action['anchor']
    if (not isinstance(canvas, list) or len(canvas) != 2
            or not all(type(v) is int and 1 <= v <= 1024 for v in canvas)):
        raise ValueError('Invalid walking canvas')
    if (not isinstance(anchor, list) or len(anchor) != 2
            or not all(type(v) is int and 0 <= v < canvas[i] for i, v in enumerate(anchor))):
        raise ValueError('Invalid walking anchor')
    entries = action['frames']
    if not isinstance(entries, list) or not 1 <= len(entries) <= 120:
        raise ValueError('Invalid walking frame sequence')
    offset = (target_anchor[0]-anchor[0], target_anchor[1]-anchor[1])
    images, durations, boundaries = [], [], []
    for entry in entries:
        path = (asset_dir/entry['file']).resolve()
        if not path.is_relative_to(asset_dir):
            raise ValueError('Walking frame escapes resource folder')
        duration = entry['duration_ms']
        if type(duration) is not int or not 30 <= duration <= 10000:
            raise ValueError('Invalid walking frame duration')
        with Image.open(path) as source:
            if 'atlas_box' in entry:
                image=decode_atlas(source,entry,canvas)
            else:
                if source.size != tuple(canvas) or source.mode != 'RGBA':
                    raise ValueError('Wrong walking frame canvas or transparency format')
                image = source.copy()
        box = image.getchannel('A').getbbox()
        if box is None:
            raise ValueError('Empty walking frame')
        if (box[0]+offset[0] < 0 or box[1]+offset[1] < 0
                or box[2]+offset[0] > target_canvas[0]
                or box[3]+offset[1] > target_canvas[1]):
            raise ValueError('Anchor mapping would clip the walking frame')
        # One fixed translation per action, never individual frame recentering.
        display = Image.new('RGBA', tuple(target_canvas), (0, 0, 0, 0))
        display.paste(image, offset)
        images.append(display)
        durations.append(duration)
        boundaries.append(sum(durations))
    cycles = data['manual_trial']['cycles']
    speed = data['manual_trial']['speed_pixels_per_second']
    if type(cycles) is not int or not 1 <= cycles <= 10:
        raise ValueError('Invalid manual loop count')
    if type(speed) not in (int, float) or not 1 <= speed <= 200:
        raise ValueError('Invalid walking speed')
    return images, durations, boundaries, cycles, speed, action


class WalkTrial:
    def __init__(self, pet, asset_dir):
        self.pet, self.asset_dir = pet, Path(asset_dir)
        self.active = False
        self.automatic = False
        self.job = None
        self.frames, self.photos = [], {}
        self.index = 0
        self.direction = 'right'
        self.moving = True
        self.canvas = tuple(pet.manifest['canvas'])
        self.anchor = tuple(pet.manifest['foot_anchor'])

    def start(self, direction='right', moving=True, *, automatic=False, cycles=None, speed=None):
        if self.pet.closing or self.pet.drag_start is not None:
            return False
        loaded = load_action(self.asset_dir, direction, self.canvas, self.anchor)
        if cycles is not None and (type(cycles) is not int or not 1 <= cycles <= 10):
            raise ValueError('Invalid walking loop override')
        if speed is not None and (type(speed) not in (int,float) or not 1 <= speed <= 200):
            raise ValueError('Invalid walking speed override')
        self.pet.show()
        self.pet._reset_idle(preserve_reading_wait=automatic)
        self.frames, self.durations, self.boundaries, self.cycles, self.speed, self.action = loaded
        self.automatic = automatic
        if cycles is not None:self.cycles=cycles
        if speed is not None:self.speed=speed
        self.direction, self.moving = direction, moving
        self.photos = {}
        self.index = 0
        self.duration = self.durations[0]
        self.remaining = len(self.frames)*self.cycles
        self.loop_ms = self.boundaries[-1]
        self.total_ms = self.loop_ms*self.cycles
        self.pet.root.update_idletasks()
        self.origin = (self.pet.root.winfo_x(), self.pet.root.winfo_y())
        width, height = self.canvas[0]*self.pet.scale, self.canvas[1]*self.pet.scale
        monitor = win32api.MonitorFromPoint(
            (self.origin[0]+width//2, self.origin[1]+height//2), 2)
        self.work = win32api.GetMonitorInfo(monitor)['Work']
        self.active = True
        self.started = time.monotonic()
        self.display()
        if moving:
            self._move(0)
        self._schedule()
        return True

    def display(self):
        scale = self.pet.scale
        if scale not in self.photos:
            size = (self.canvas[0]*scale, self.canvas[1]*scale)
            self.photos[scale] = [
                make_photo(im,size,getattr(self.pet,'style_resampling',Image.Resampling.NEAREST))
                for im in self.frames]
        self.pet.label.configure(image=self.photos[scale][self.index])

    def _move(self, elapsed_ms):
        size = (self.canvas[0]*self.pet.scale, self.canvas[1]*self.pet.scale)
        distance = self.speed*self.pet.scale*elapsed_ms/1000
        x, y = bounded_position(self.origin, self.direction, distance, self.work, size)
        # Win32 absolute coordinates also work on monitors left/above the primary one.
        position_window(self.pet.root, x, y)

    def _schedule(self):
        elapsed = max(0, (time.monotonic()-self.started)*1000)
        phase = elapsed % self.loop_ms
        delay = max(1, self.boundaries[self.index]-phase)
        if self.moving:
            delay = min(33, delay)
        self.job = self.pet.root.after(max(1, round(delay)), self.step)

    def step(self):
        self.job = None
        if not self.active:
            return
        if not self.pet.visible or self.pet.closing:
            self.cancel()
            return
        # A held press pauses the walk; dragging replaces it with idle.
        if self.pet.drag_start is not None:
            self.stop()
            return
        elapsed = max(0, (time.monotonic()-self.started)*1000)
        if self.moving:
            self._move(min(elapsed, self.total_ms))
        if elapsed >= self.total_ms:
            self.stop()
            return
        phase = elapsed % self.loop_ms
        index = bisect_right(self.boundaries, phase)
        self.remaining = (self.cycles-int(elapsed//self.loop_ms))*len(self.frames)-index
        if index != self.index:
            self.index = index
            self.display()
        self._schedule()

    def stop(self):
        self.pet._reset_idle(preserve_reading_wait=self.automatic)
        self.pet._remember_position()
        self.pet._schedule_next_frame()
        self.pet._schedule_reading()

    def cancel(self):
        if self.job is not None:
            self.pet.root.after_cancel(self.job)
        self.job = None
        self.active = False
        self.automatic = False
