"""Optional loopback server with a random per-launch capability and finite API.

The accept loop blocks on sockets. A one-shot leave deadline reclaims the
server after normal page closure, and a reloaded authenticated page cancels it.
No recurring timer, telemetry, shell operation or model provider is installed.
"""
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import re
import selectors
import socket
import threading
import time

from libao_modules.security import strict_json
from activity_timing import validate_preferences
from .bridge import Bridge, CONTRACTS, validate_call
from .companion_chat import CompanionChat
from .companion_memory import CompanionMemory
from .memory_archive import MemoryArchive
from .owner_memory import owner_memory
from .summary_wiring import adapter_for_chat
from .desktop_memory_review import DesktopMemoryReview
from .entrance import EntranceSession

STATIC = Path(__file__).resolve().parent / 'static'
MAX_BODY = 600_000
ASSETS = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/index.html': ('index.html', 'text/html; charset=utf-8'),
    '/style.css': ('style.css', 'text/css; charset=utf-8'),
    '/mark.svg': ('mark.svg', 'image/svg+xml'),
    '/arrival.css': ('arrival.css', 'text/css; charset=utf-8'),
    '/arrival_v23.webm': ('arrival_v23.webm', 'video/webm'),
    **{'/' + name: (name, 'text/javascript; charset=utf-8') for name in
       ('theme.js', 'layout.js', 'runtime.js', 'frame.js', 'example.js', 'modules.js', 'app.js', 'arrival.js', 'arrival_bootstrap.js')},
}
# Only bundled scene assets are served. No directory or arbitrary-file endpoint.
ASSETS.update({
    '/scene-chat.js': ('scene-chat.js', 'text/javascript; charset=utf-8'),
    '/scene-memory.js': ('scene-memory.js', 'text/javascript; charset=utf-8'),
    '/chat-adapter.js': ('chat-adapter.js', 'text/javascript; charset=utf-8'),
    '/scene/reaction-controller.js': ('scene/reaction-controller.js', 'text/javascript; charset=utf-8'),
    '/scene.js': ('scene.js', 'text/javascript; charset=utf-8'),
    '/scene/action.json': ('scene/action.json', 'application/json; charset=utf-8'),
    '/scene/B01.png': ('scene/B01.png', 'image/png'),
    '/scene/B04.png': ('scene/B04.png', 'image/png'),
    '/scene/closed.png': ('scene/closed.png', 'image/png'),
    '/scene/config.js': ('scene/config.js', 'text/javascript; charset=utf-8'),
    '/scene/eye-white-v2.png': ('scene/eye-white-v2.png', 'image/png'),
    '/scene/F01.png': ('scene/F01.png', 'image/png'),
    '/scene/F02.png': ('scene/F02.png', 'image/png'),
    '/scene/F03.png': ('scene/F03.png', 'image/png'),
    '/scene/F04.png': ('scene/F04.png', 'image/png'),
    '/scene/F05.png': ('scene/F05.png', 'image/png'),
    '/scene/F06.png': ('scene/F06.png', 'image/png'),
    '/scene/F07.png': ('scene/F07.png', 'image/png'),
    '/scene/F08.png': ('scene/F08.png', 'image/png'),
    '/scene/F09.png': ('scene/F09.png', 'image/png'),
    '/scene/F10.png': ('scene/F10.png', 'image/png'),
    '/scene/half.png': ('scene/half.png', 'image/png'),
    '/scene/original.png': ('scene/original.png', 'image/png'),
    '/scene/pixi.js': ('scene/pixi.js', 'text/javascript; charset=utf-8'),
    '/scene/portrait.css': ('scene/portrait.css', 'text/css; charset=utf-8'),
    '/scene/portrait.html': ('scene/portrait.html', 'text/html; charset=utf-8'),
    '/scene/portrait.js': ('scene/portrait.js', 'text/javascript; charset=utf-8'),
    '/scene/character.js': ('scene/character.js', 'text/javascript; charset=utf-8'),
    '/scene/layers.json': ('scene/layers.json', 'application/json; charset=utf-8'),
    '/scene/layers/cape_rear.png': ('scene/layers/cape_rear.png', 'image/png'),
    '/scene/layers/leg_left.png': ('scene/layers/leg_left.png', 'image/png'),
    '/scene/layers/leg_right.png': ('scene/layers/leg_right.png', 'image/png'),
    '/scene/layers/boot_left.png': ('scene/layers/boot_left.png', 'image/png'),
    '/scene/layers/boot_right.png': ('scene/layers/boot_right.png', 'image/png'),
    '/scene/layers/neck_rear_hair_backing.png': ('scene/layers/neck_rear_hair_backing.png', 'image/png'),
    '/scene/layers/neck_hidden.png': ('scene/layers/neck_hidden.png', 'image/png'),
    '/scene/layers/hat_hidden_brim.png': ('scene/layers/hat_hidden_brim.png', 'image/png'),
    '/scene/layers/body_connection_underlay.png': ('scene/layers/body_connection_underlay.png', 'image/png'),
    '/scene/layers/sleeve_left.png': ('scene/layers/sleeve_left.png', 'image/png'),
    '/scene/layers/sleeve_right.png': ('scene/layers/sleeve_right.png', 'image/png'),
    '/scene/layers/skirt_cast_shadow.png': ('scene/layers/skirt_cast_shadow.png', 'image/png'),
    '/scene/layers/skirt.png': ('scene/layers/skirt.png', 'image/png'),
    '/scene/layers/torso.png': ('scene/layers/torso.png', 'image/png'),
    '/scene/layers/ruffle.png': ('scene/layers/ruffle.png', 'image/png'),
    '/scene/layers/ribbon.png': ('scene/layers/ribbon.png', 'image/png'),
    '/scene/layers/collar_front.png': ('scene/layers/collar_front.png', 'image/png'),
    '/scene/layers/chain.png': ('scene/layers/chain.png', 'image/png'),
    '/scene/layers/watch.png': ('scene/layers/watch.png', 'image/png'),
    '/scene/layers/bag.png': ('scene/layers/bag.png', 'image/png'),
    '/scene/layers/hand_left.png': ('scene/layers/hand_left.png', 'image/png'),
    '/scene/layers/hand_right.png': ('scene/layers/hand_right.png', 'image/png'),
    '/scene/layers/hair_hat_shadow.png': ('scene/layers/hair_hat_shadow.png', 'image/png'),
    '/scene/layers/hair_hidden_roots.png': ('scene/layers/hair_hidden_roots.png', 'image/png'),
    '/scene/layers/face_visible.png': ('scene/layers/face_visible.png', 'image/png'),
    '/scene/layers/ear_left.png': ('scene/layers/ear_left.png', 'image/png'),
    '/scene/layers/hair_04.png': ('scene/layers/hair_04.png', 'image/png'),
    '/scene/layers/hair_05.png': ('scene/layers/hair_05.png', 'image/png'),
    '/scene/layers/ear_right.png': ('scene/layers/ear_right.png', 'image/png'),
    '/scene/layers/hair_face_shadow.png': ('scene/layers/hair_face_shadow.png', 'image/png'),
    '/scene/layers/eye_left_white.png': ('scene/layers/eye_left_white.png', 'image/png'),
    '/scene/layers/eye_left_iris.png': ('scene/layers/eye_left_iris.png', 'image/png'),
    '/scene/layers/eye_left_lashes.png': ('scene/layers/eye_left_lashes.png', 'image/png'),
    '/scene/layers/eye_right_white.png': ('scene/layers/eye_right_white.png', 'image/png'),
    '/scene/layers/eye_right_iris.png': ('scene/layers/eye_right_iris.png', 'image/png'),
    '/scene/layers/eye_right_lashes.png': ('scene/layers/eye_right_lashes.png', 'image/png'),
    '/scene/layers/hair_fixed_front.png': ('scene/layers/hair_fixed_front.png', 'image/png'),
    '/scene/layers/hair_01.png': ('scene/layers/hair_01.png', 'image/png'),
    '/scene/layers/hair_02.png': ('scene/layers/hair_02.png', 'image/png'),
    '/scene/layers/hair_03.png': ('scene/layers/hair_03.png', 'image/png'),
    '/scene/layers/brow_left.png': ('scene/layers/brow_left.png', 'image/png'),
    '/scene/layers/brow_right.png': ('scene/layers/brow_right.png', 'image/png'),
    '/scene/layers/nose.png': ('scene/layers/nose.png', 'image/png'),
    '/scene/layers/mouth_closed.png': ('scene/layers/mouth_closed.png', 'image/png'),
    '/scene/layers/hat_base.png': ('scene/layers/hat_base.png', 'image/png'),
    '/scene/layers/eye_left_half.png': ('scene/layers/eye_left_half.png', 'image/png'),
    '/scene/layers/eye_left_closed.png': ('scene/layers/eye_left_closed.png', 'image/png'),
    '/scene/layers/eye_right_half.png': ('scene/layers/eye_right_half.png', 'image/png'),
    '/scene/layers/eye_right_closed.png': ('scene/layers/eye_right_closed.png', 'image/png'),
    '/scene/layers/wrist_left_hidden.png': ('scene/layers/wrist_left_hidden.png', 'image/png'),
    '/scene/layers/neck_front_connection.png': ('scene/layers/neck_front_connection.png', 'image/png'),
    '/scene/layers/wrist_right_hidden.png': ('scene/layers/wrist_right_hidden.png', 'image/png'),
    '/scene/layers/watch_cast_shadow.png': ('scene/layers/watch_cast_shadow.png', 'image/png'),
    '/scene/layers/happy.png': ('scene/layers/happy.png', 'image/png'),
    '/scene/layers/annoyed.png': ('scene/layers/annoyed.png', 'image/png'),
    '/scene/layers/blink_cleanup_underlay.png': ('scene/layers/blink_cleanup_underlay.png', 'image/png'),
    '/scene/layers/hair_fixed_front_blink.png': ('scene/layers/hair_fixed_front_blink.png', 'image/png'),
    '/scene/T01.png': ('scene/T01.png', 'image/png'),
    '/scene/T02.png': ('scene/T02.png', 'image/png'),
    '/scene/underlayer.png': ('scene/underlayer.png', 'image/png'),
    '/scene/unsafe-eval.js': ('scene/unsafe-eval.js', 'text/javascript; charset=utf-8'),
    '/scene/window-dusk.png': ('scene/window-dusk.png', 'image/png'),
})

# Explicit production bookshelf assets; no directory browsing or arbitrary paths.
ASSETS.update({
    '/memory-books.js': ('memory-books.js', 'text/javascript; charset=utf-8'),
    '/memory-books.css': ('memory-books.css', 'text/css; charset=utf-8'),
    '/alignment.css': ('alignment.css', 'text/css; charset=utf-8'),
    '/assets/study-soft-classic.png': ('assets/study-soft-classic.png', 'image/png'),
    **{'/assets/cover-'+str(m)+'.png': ('assets/cover-'+str(m)+'.png', 'image/png') for m in (10,11,12)},
    **{'/assets/flowers/'+str(m).zfill(2)+'.svg': ('assets/flowers/'+str(m).zfill(2)+'.svg','image/svg+xml') for m in range(1,13)},
})


# Approved desktop UI resources; exact paths, no arbitrary-file serving.
ASSETS.update({
    '/scene-gold.css': ('scene-gold.css', 'text/css; charset=utf-8'),
    '/scene-jelly.js': ('scene-jelly.js', 'text/javascript; charset=utf-8'),
    '/vendor/brand-jelly.js': ('vendor/brand-jelly.js', 'text/javascript; charset=utf-8'),
    '/vendor/matter-0.20.0.min.js': ('vendor/matter-0.20.0.min.js', 'text/javascript; charset=utf-8'),
    '/assets/jelly/libao-desktop.png': ('assets/jelly/libao-desktop.png', 'image/png'),
    '/assets/jelly/chibi-idle.png': ('assets/jelly/chibi-idle.png', 'image/png'),
    '/assets/gold/shelf-board.svg': ('assets/gold/shelf-board.svg', 'image/svg+xml'),
    '/assets/gold/shelf-frame.svg': ('assets/gold/shelf-frame.svg', 'image/svg+xml'),
    '/assets/gold/shelf-teacups.png': ('assets/gold/shelf-teacups.png', 'image/png'),
})

# Exact aliases to existing local sleep frames; no duplicate PNG payloads.
_SLEEP_ROOT = Path(__file__).resolve().parents[1] / 'assets/styles/style2/actions/sleep'
ASSETS.update({
    '/scene-actions.js': ('scene-actions.js', 'text/javascript; charset=utf-8'),
    '/scene/sleep.json': ('scene/sleep.json', 'application/json; charset=utf-8'),
    '/scene/sleep/00.png': (_SLEEP_ROOT / '01_入睡PNG/00_V7静息.png', 'image/png'),
    '/scene/sleep/01.png': (_SLEEP_ROOT / '01_入睡PNG/01_抬手.png', 'image/png'),
    '/scene/sleep/02.png': (_SLEEP_ROOT / '01_入睡PNG/02_扶帽檐.png', 'image/png'),
    '/scene/sleep/03.png': (_SLEEP_ROOT / '01_入睡PNG/03_帽子提离.png', 'image/png'),
    '/scene/sleep/04.png': (_SLEEP_ROOT / '01_入睡PNG/04_摘帽经过脸前.png', 'image/png'),
    '/scene/sleep/05.png': (_SLEEP_ROOT / '01_入睡PNG/05_站立抱帽.png', 'image/png'),
    '/scene/sleep/06.png': (_SLEEP_ROOT / '01_入睡PNG/06_轻屈膝.png', 'image/png'),
    '/scene/sleep/07.png': (_SLEEP_ROOT / '01_入睡PNG/07_继续屈膝.png', 'image/png'),
    '/scene/sleep/08.png': (_SLEEP_ROOT / '01_入睡PNG/08_深屈膝.png', 'image/png'),
    '/scene/sleep/09.png': (_SLEEP_ROOT / '01_入睡PNG/09_落座前.png', 'image/png'),
    '/scene/sleep/10.png': (_SLEEP_ROOT / '01_入睡PNG/10_落座前_披风接地.png', 'image/png'),
    '/scene/sleep/11.png': (_SLEEP_ROOT / '01_入睡PNG/11_刚落座_靴口修正.png', 'image/png'),
    '/scene/sleep/12.png': (_SLEEP_ROOT / '01_入睡PNG/12_收腿起步_脚踝修正.png', 'image/png'),
    '/scene/sleep/13.png': (_SLEEP_ROOT / '01_入睡PNG/13_收腿中段_新增.png', 'image/png'),
    '/scene/sleep/14.png': (_SLEEP_ROOT / '01_入睡PNG/14_收腿后半_靴口修正.png', 'image/png'),
    '/scene/sleep/15.png': (_SLEEP_ROOT / '01_入睡PNG/15_换握抱帽.png', 'image/png'),
    '/scene/sleep/16.png': (_SLEEP_ROOT / '01_入睡PNG/16_换握中段.png', 'image/png'),
    '/scene/sleep/17.png': (_SLEEP_ROOT / '01_入睡PNG/17_坐稳清醒.png', 'image/png'),
    '/scene/sleep/18.png': (_SLEEP_ROOT / '01_入睡PNG/18_渐合眼.png', 'image/png'),
    '/scene/sleep/19.png': (_SLEEP_ROOT / '01_入睡PNG/19_闭眼睡稳.png', 'image/png'),
    '/scene/sleep/20.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/00_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/21.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/01_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/22.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/02_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/23.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/03_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/24.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/04_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/25.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/05_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/26.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/06_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/27.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/07_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/28.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/08_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/29.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/09_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/30.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/10_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/31.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/11_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/32.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/12_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/33.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/13_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/34.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/14_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/35.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/15_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/36.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/16_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/37.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/17_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/38.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/18_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/39.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/19_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/40.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/20_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/41.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/21_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/42.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/22_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/43.png': (_SLEEP_ROOT / '02_睡眠微呼吸PNG/23_睡眠呼吸.png', 'image/png'),
    '/scene/sleep/44.png': (_SLEEP_ROOT / '03_醒来PNG/00_闭眼静息.png', 'image/png'),
    '/scene/sleep/45.png': (_SLEEP_ROOT / '03_醒来PNG/01_渐睁眼.png', 'image/png'),
    '/scene/sleep/46.png': (_SLEEP_ROOT / '03_醒来PNG/02_坐稳清醒.png', 'image/png'),
    '/scene/sleep/47.png': (_SLEEP_ROOT / '03_醒来PNG/03_从膝前抬帽.png', 'image/png'),
    '/scene/sleep/48.png': (_SLEEP_ROOT / '03_醒来PNG/04_抬帽经过脸前.png', 'image/png'),
    '/scene/sleep/49.png': (_SLEEP_ROOT / '03_醒来PNG/05_抬帽经过视线.png', 'image/png'),
    '/scene/sleep/50.png': (_SLEEP_ROOT / '03_醒来PNG/06_帽子对准头顶.png', 'image/png'),
    '/scene/sleep/51.png': (_SLEEP_ROOT / '03_醒来PNG/07_坐姿戴好帽子.png', 'image/png'),
    '/scene/sleep/52.png': (_SLEEP_ROOT / '03_醒来PNG/08_双腿收回中段.png', 'image/png'),
    '/scene/sleep/53.png': (_SLEEP_ROOT / '03_醒来PNG/09_双脚收至身前.png', 'image/png'),
    '/scene/sleep/54.png': (_SLEEP_ROOT / '03_醒来PNG/10_移重离地.png', 'image/png'),
    '/scene/sleep/55.png': (_SLEEP_ROOT / '03_醒来PNG/11_低蹲上升.png', 'image/png'),
    '/scene/sleep/56.png': (_SLEEP_ROOT / '03_醒来PNG/12_扶膝伸膝.png', 'image/png'),
    '/scene/sleep/57.png': (_SLEEP_ROOT / '03_醒来PNG/13_半站仍扶膝.png', 'image/png'),
    '/scene/sleep/58.png': (_SLEEP_ROOT / '03_醒来PNG/14_松手离膝.png', 'image/png'),
    '/scene/sleep/59.png': (_SLEEP_ROOT / '03_醒来PNG/15_手向腰间回收.png', 'image/png'),
    '/scene/sleep/60.png': (_SLEEP_ROOT / '03_醒来PNG/16_接近站直.png', 'image/png'),
    '/scene/sleep/61.png': (_SLEEP_ROOT / '03_醒来PNG/17_站直前轻屈膝.png', 'image/png'),
    '/scene/sleep/62.png': (_SLEEP_ROOT / '03_醒来PNG/18_返回原始V7.png', 'image/png'),
    '/scene/sleep/wake-04a.png': (_SLEEP_ROOT / '03_醒来PNG/04a_帽子经过脸前补帧.png', 'image/png'),
    '/scene/sleep/wake-05a.png': (_SLEEP_ROOT / '03_醒来PNG/05a_抬帽中间姿势.png', 'image/png'),
    '/scene/sleep/wake-05b.png': (_SLEEP_ROOT / '03_醒来PNG/05b_帽子靠近头顶补帧.png', 'image/png'),
    '/scene/sleep/wake-10a.png': (_SLEEP_ROOT / '03_醒来PNG/10a_承重起身中间姿势.png', 'image/png'),
})
CONTROL = {'mobile_updates.open': (set(),set()), 'chat.memory.list': (set(),set()), 'chat.config.get': (set(),set()), 'chat.config.set': ({'settings'},set()), 'chat.key.delete': (set(),set()), 'chat.reply': ({'text'},set()), 'chat.cancel': (set(),set()), 'modules.open': (set(), set()), 'behavior.get': (set(), set()), 'behavior.set': ({'settings'}, set()), 'arrival.claim': (set(), set()), 'session.close': (set(), set()), 'session.leave': (set(), set()),
           'voice.workbench_open': (set(), set()), 'voice.workbench_stop': (set(), set()),
           **{name: (set(),set()) for name in ('voice.scene_sleep','voice.scene_wake','voice.scene_stop')},
           **{name: (set(), set()) for name in ('voice.available','voice.open','voice.fixed','voice.text','voice.api')}}
CONTROL.update({
    'chat.layers.auto_review.status': (set(),set()),
    'chat.layers.auto_review.configure': ({'enabled'},set()),
    'chat.layers.auto_review.run': (set(),set()),
    'chat.reply': ({'text'},{'request_id'}), 'chat.cancel': (set(),{'request_id'}),
    'chat.history': (set(),{'limit','before'}),
    'chat.books.months': (set(),set()), 'chat.books.days': ({'month'},set()),
    'chat.books.day': ({'day'},set()), 'chat.books.status': (set(),set()),
    'chat.books.undated': (set(),set()), 'chat.layers.get': (set(),set()),
    'chat.layers.settings': ({'settings'},set()), 'chat.layers.decide': ({'decisions'},set()),
    'chat.layers.correct': ({'key','revision','text'},set()),
    'chat.layers.withdraw': ({'key','revision'},set()),
    'chat.layers.phone_source': ({'key','revision'},set()),
    'chat.layers.conflicts': (set(),set()),
    'chat.layers.resolve_conflict': ({'id','revision','fingerprint','delete'},set()),
})
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; "
       "connect-src 'self'; frame-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; "
       "object-src 'none'; frame-ancestors 'none'")


class WorkbenchServer(HTTPServer):
    def __init__(self, data_dir, *, voice_notify=None, entrance=None, behavior_call=None, modules=None, module_notify=None):
        self.behavior_call = behavior_call
        self.desktop_voice_available = voice_notify is not None
        self.voice_notify = voice_notify or (lambda event: None)
        self.entrance = entrance if entrance is not None else EntranceSession()
        self.bridge = Bridge(data_dir, modules=modules)
        self.module_notify = module_notify
        self.memories = owner_memory(Path(data_dir) / "workbench" / "companion-memory.sqlite3",workbench=True)
        self.chat = CompanionChat(Path(data_dir) / "workbench" / "chat.json", memories=self.memories)
        self.archive = MemoryArchive(self.chat,legacy=self.memories)
        self.chat.context.summarizer=adapter_for_chat(self.chat)
        self.chat.context.timeout=18.0
        self.chat.context.summary_interval_days=7
        self.token = secrets.token_urlsafe(32)
        self.closing = False
        self.lock = threading.Lock()
        self.request_lock = threading.Lock()
        self.request_workers = {}
        self.api_lock = threading.Lock()
        self.leave_timer = None
        self.wake_read, self.wake_write = socket.socketpair()
        try:
            super().__init__(('127.0.0.1', 0), Handler)
        except BaseException:
            self.wake_read.close()
            self.wake_write.close()
            raise
        self.authority = '127.0.0.1:' + str(self.server_port)
        self.origin = 'http://' + self.authority
        self.memory_reviewer = DesktopMemoryReview(self.chat)
        self.memory_reviewer.start()

    @property
    def launch_url(self):
        return self.origin + '/#session=' + self.token

    def active(self):
        with self.lock:
            if self.leave_timer:
                self.leave_timer.cancel()
                self.leave_timer = None

    def leave(self):
        with self.lock:
            if self.leave_timer:
                self.leave_timer.cancel()
            timer = threading.Timer(5.0, self._leave_expired)
            timer.daemon = True
            self.leave_timer = timer
            timer.start()

    def _leave_expired(self):
        with self.lock:
            # A canceled older callback must not close a newly active page.
            if self.leave_timer is not threading.current_thread():
                return
            self.leave_timer = None
            self._stop_locked()

    def _stop_locked(self):
        if self.closing:
            return
        self.closing = True
        self.memory_reviewer.stop()
        try:
            self.wake_write.send(b'x')
        except OSError:
            # Teardown may already have closed the wake socket.
            pass

    def stop(self):
        with self.lock:
            self._stop_locked()
        with self.request_lock:
            requests = list(self.request_workers.values())
        for request in requests:
            try:
                request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def process_request(self, request, address):
        # A browser may pause reading a video while other panels need the API.
        # Finite, request-owned workers avoid blocking those panels; no polling.
        with self.request_lock:
            if self.closing or len(self.request_workers) >= 16:
                self.shutdown_request(request)
                return
            worker = threading.Thread(target=self._serve_request,
                                      args=(request, address),
                                      name='hebao-workbench-request', daemon=True)
            self.request_workers[worker] = request
            worker.start()

    def _serve_request(self, request, address):
        try:
            self.finish_request(request, address)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
            pass
        except Exception:
            if not self.closing:
                self.handle_error(request, address)
        finally:
            self.shutdown_request(request)
            with self.request_lock:
                self.request_workers.pop(threading.current_thread(), None)

    def serve(self):
        with selectors.DefaultSelector() as selector:
            selector.register(self.socket, selectors.EVENT_READ, 'request')
            selector.register(self.wake_read, selectors.EVENT_READ, 'stop')
            while not self.closing:
                for key, _mask in selector.select():
                    if key.data == 'stop' or self.closing:
                        return
                    self._handle_request_noblock()

    def server_close(self):
        self.active()
        self.stop()
        super().server_close()
        with self.request_lock:
            workers = list(self.request_workers)
        deadline = time.monotonic() + 8
        for worker in workers:
            if worker is not threading.current_thread():
                worker.join(max(0, deadline - time.monotonic()))
        self.wake_read.close()
        self.wake_write.close()


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def setup(self):
        super().setup()
        self.connection.settimeout(8)

    def log_message(self, _format, *_args):
        # Do not log credentials, imported text or request paths.
        pass

    def response_headers(self, code, length, content_type, extra=None):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        policy = CSP.replace("frame-ancestors 'none'", "frame-ancestors 'self'") if self.path == '/scene/portrait.html' else CSP
        self.send_header('Content-Security-Policy', policy)
        self.send_header('Connection', 'close')
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def respond(self, code, body, content_type='application/json; charset=utf-8'):
        self.response_headers(code, len(body), content_type)
        if self.command == 'HEAD':
            return
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # A departing UI may abort after an explicitly requested write.
            pass

    def json_response(self, code, value):
        self.respond(code, json.dumps(value, ensure_ascii=False).encode())

    def check_site(self):
        hosts = self.headers.get_all('Host', [])
        if hosts != [self.server.authority]:
            self.json_response(403, {'error': '本地地址不匹配'})
            return False
        origin = self.headers.get('Origin')
        if origin is not None and origin != self.server.origin:
            self.json_response(403, {'error': '只接受同源的工作台请求'})
            return False
        if self.headers.get('Sec-Fetch-Site') in ('cross-site', 'same-site'):
            self.json_response(403, {'error': '只接受同源的工作台请求'})
            return False
        return True

    def do_GET(self):
        if not self.check_site():
            return
        asset = ASSETS.get(self.path)
        if asset is None:
            self.json_response(404, {'error': '资源不存在'})
            return
        path = STATIC / asset[0]
        if not path.is_file():
            self.json_response(404, {'error': '资源不存在'})
            return
        if asset[1] == 'video/webm':
            self.media_response(path, asset[1])
            return
        body = path.read_bytes()
        if asset[0] == 'index.html':
            theme = self.server.bridge.appearance_theme()
            body = body.replace(b'data-theme="dark"', ('data-theme="' + theme + '"').encode('ascii'), 1)
        self.respond(200, body, asset[1])

    def do_HEAD(self):
        self.do_GET()

    def media_response(self, path, content_type):
        # Only whitelist media paths reach this method. Support browser seeking
        # without loading the entire video in memory or changing API access.
        with path.open('rb') as stream:
            size = path.stat().st_size
            start, end, code = 0, size - 1, 200
            extra = {'Accept-Ranges': 'bytes'}
            ranges = self.headers.get_all('Range', [])
            if ranges:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', ranges[0]) if len(ranges) == 1 else None
                try:
                    if not match or not any(match.groups()):
                        raise ValueError
                    left, right = match.groups()
                    if left:
                        start = int(left)
                        end = min(int(right), size - 1) if right else size - 1
                        if start >= size or end < start:
                            raise ValueError
                    else:
                        count = int(right)
                        if count <= 0:
                            raise ValueError
                        start = max(0, size - count)
                    code = 206
                    extra['Content-Range'] = f'bytes {start}-{end}/{size}'
                except (ValueError, OverflowError):
                    self.response_headers(416, 0, content_type, {'Content-Range': f'bytes */{size}'})
                    return
            length = end - start + 1
            self.response_headers(code, length, content_type, extra)
            if self.command == 'HEAD':
                return
            stream.seek(start)
            try:
                while length:
                    chunk = stream.read(min(length, 65536))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    length -= len(chunk)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
                # Skipping or closing the animation may cancel the transfer.
                pass

    def do_POST(self):
        if not self.check_site():
            return
        if self.path != '/api/call':
            self.json_response(404, {'error': '接口不存在'})
            return
        supplied = self.headers.get_all('Authorization', [])
        expected = 'Bearer ' + self.server.token
        if len(supplied) != 1 or not supplied[0].isascii() or not hmac.compare_digest(supplied[0], expected):
            self.json_response(403, {'error': '本地会话无效，请重新打开工作台'})
            return
        if self.headers.get_content_type() != 'application/json' or self.headers.get('Transfer-Encoding'):
            self.json_response(415, {'error': '仅接受定长 JSON 数据'})
            return
        lengths = self.headers.get_all('Content-Length', [])
        try:
            if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
                raise ValueError('需要有效的请求长度')
            length = int(lengths[0])
            if not 0 < length <= MAX_BODY:
                self.json_response(413, {'error': '请求过大或为空'})
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError('请求数据不完整')
            value = strict_json(raw.decode('utf-8'), max_bytes=MAX_BODY)
            command, _params = validate_call(value, {**CONTRACTS, **CONTROL})
            if command == 'chat.memory.list': result = self.server.archive.legacy_notes()
            elif command == 'chat.history': result = self.server.archive.history(**_params)
            elif command == 'chat.books.months': result = self.server.archive.months()
            elif command == 'chat.books.days': result = self.server.archive.days(_params['month'])
            elif command == 'chat.books.day': result = self.server.archive.day(_params['day'])
            elif command == 'chat.books.status': result = self.server.archive.status()
            elif command == 'chat.books.undated': result = self.server.archive.undated()
            elif command == 'chat.layers.get': result = self.server.chat.layers.snapshot()
            elif command == 'chat.layers.auto_review.status': result = self.server.memory_reviewer.status()
            elif command == 'chat.layers.auto_review.configure': result = self.server.memory_reviewer.configure(_params['enabled'])
            elif command == 'chat.layers.auto_review.run': result = self.server.memory_reviewer.request()
            elif command == 'chat.layers.phone_source': result = self.server.chat.layers.phone_source(**_params)
            elif command == 'chat.layers.conflicts':
                from .layer_sync import LayerSync
                try:result=LayerSync.local(self.server.chat).conflicts()
                except ValueError as error:
                    if str(error)!='还没有分层同步记录。':raise
                    result={'conflicts':[],'fingerprint':None}
            elif command == 'chat.layers.resolve_conflict':
                from .layer_sync import LayerSync
                with self.server.chat.guard:
                    self.server.chat.cancel();result=LayerSync.local(self.server.chat).decide(_params)
            elif command == 'chat.layers.decide': result = self.server.chat.review_layers(_params['decisions'])
            elif command == 'chat.layers.correct': result = self.server.chat.change_approved(**_params)
            elif command == 'chat.layers.withdraw': result = self.server.chat.change_approved(**_params,withdraw=True)
            elif command == 'chat.layers.settings':
                with self.server.chat.guard:
                    self.server.chat.cancel()
                    result = self.server.chat.layers.configure(_params['settings'])
            elif command == 'chat.config.get': result = self.server.chat.config()
            elif command == 'chat.config.set': result = self.server.chat.configure(_params['settings'])
            elif command == 'chat.key.delete': result = self.server.chat.delete_key()
            elif command == 'chat.reply': result = self.server.chat.reply_request(**_params)
            elif command == 'chat.cancel': result = self.server.chat.cancel(**_params)
            elif command.startswith('behavior.'):
                if command=='behavior.set':validate_preferences(_params['settings'])
                if self.server.behavior_call is None:
                    if command=='behavior.set':raise ValueError('请从桌面莉宝打开工作台，再调整动作时间。')
                    result={'available':False}
                else:result=self.server.behavior_call(command,_params)
            elif command == 'mobile_updates.open':
                from mobile_update_launcher import open_publisher
                result = open_publisher(self.server.bridge.appearance_path.parent.parent)
            elif command == 'modules.open':
                if self.server.module_notify is None: raise ValueError('请从桌面莉宝打开模块管理入口。')
                self.server.module_notify()
                result = {'queued': True}
            elif command == 'arrival.claim':
                self.server.active()
                result = {'play': self.server.entrance.claim()}
            elif command == 'voice.available':
                result = {'available': self.server.desktop_voice_available}
            elif command in ('voice.open','voice.fixed','voice.text','voice.api'):
                if not self.server.desktop_voice_available:
                    raise ValueError('请从桌面莉宝打开工作台，再使用声音模块。')
                self.server.voice_notify(command.split('.',1)[1])
                result = {'queued': True}
            elif command.startswith('voice.'):
                self.server.voice_notify(command.split('.',1)[1])
                result = {'queued': True}
            elif command == 'session.close':
                self.server.voice_notify('workbench_stop')
                result = {'closed': True}
            elif command == 'session.leave':
                self.server.voice_notify('workbench_stop')
                result = {'closing_after_seconds': 5}
                self.server.leave()
            else:
                self.server.active()
                with self.server.api_lock:
                    result = self.server.bridge.call(value)
            self.json_response(200, {'result': result})
            if command == 'session.close':
                self.server.stop()
        except (ValueError, TypeError, KeyError, UnicodeError) as error:
            self.json_response(400, {'error': str(error)})
        except OSError:
            self.json_response(503, {'error': '本地数据暂时不可用，未完成此次操作'})
        except Exception:
            self.json_response(500, {'error': '本地处理没有完成，请保留原始材料后重试'})

    def do_OPTIONS(self):
        # No CORS grant and no cross-origin preflight capability.
        self.json_response(403, {'error': '不接受跨站请求'})
