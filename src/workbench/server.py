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

from hebao_modules.security import strict_json
from activity_timing import validate_preferences
from .bridge import Bridge, CONTRACTS, validate_call
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
CONTROL = {'modules.open': (set(), set()), 'behavior.get': (set(), set()), 'behavior.set': ({'settings'}, set()), 'arrival.claim': (set(), set()), 'session.close': (set(), set()), 'session.leave': (set(), set()),
           'voice.workbench_open': (set(), set()), 'voice.workbench_stop': (set(), set()),
           **{name: (set(), set()) for name in ('voice.available','voice.open','voice.fixed','voice.text','voice.api')}}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; "
       "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; "
       "object-src 'none'; frame-ancestors 'none'")


class WorkbenchServer(HTTPServer):
    def __init__(self, data_dir, *, voice_notify=None, entrance=None, behavior_call=None, modules=None, module_notify=None):
        self.behavior_call = behavior_call
        self.desktop_voice_available = voice_notify is not None
        self.voice_notify = voice_notify or (lambda event: None)
        self.entrance = entrance if entrance is not None else EntranceSession()
        self.bridge = Bridge(data_dir, modules=modules)
        self.module_notify = module_notify
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
        self.send_header('Content-Security-Policy', CSP)
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
            if command.startswith('behavior.'):
                if command=='behavior.set':validate_preferences(_params['settings'])
                if self.server.behavior_call is None:
                    if command=='behavior.set':raise ValueError('请从桌面赫宝打开工作台，再调整动作时间。')
                    result={'available':False}
                else:result=self.server.behavior_call(command,_params)
            elif command == 'modules.open':
                if self.server.module_notify is None: raise ValueError('请从桌面赫宝打开模块管理入口。')
                self.server.module_notify()
                result = {'queued': True}
            elif command == 'arrival.claim':
                self.server.active()
                result = {'play': self.server.entrance.claim()}
            elif command == 'voice.available':
                result = {'available': self.server.desktop_voice_available}
            elif command in ('voice.open','voice.fixed','voice.text','voice.api'):
                if not self.server.desktop_voice_available:
                    raise ValueError('请从桌面赫宝打开工作台，再使用声音模块。')
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
