
# Локальный HTTP сервер для общения мода с лаунчером.
# Слушает на localhost:25560, принимает события от Minecraft мода.
# Нужно доделать!

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

log = logging.getLogger("local_api")
PORT = 19580

_event_handlers: dict[str, list] = {}  # type -> [callback]


def on_event(event_type: str):
    """Декоратор для регистрации обработчика события."""
    def decorator(fn):
        _event_handlers.setdefault(event_type, []).append(fn)
        return fn
    return decorator


def _dispatch(event_type: str, data: dict):
    for handler in _event_handlers.get(event_type, []):
        try:
            handler(data)
        except Exception as e:
            log.error("[local_api] handler error for %s: %s", event_type, e)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # отключаем стандартный лог

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body) if body else {}
            event_type = data.get("type", "")
            log.info("[local_api] event=%s data=%s", event_type, data)
            _dispatch(event_type, data)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        except Exception as e:
            log.error("[local_api] error: %s", e)
            self.send_response(500)
            self.end_headers()

    def do_GET(self):
        """Пинг — мод может проверить что лаунчер запущен."""
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"launcher":true}')


_server: HTTPServer | None = None


def start():
    global _server
    try:
        _server = HTTPServer(("127.0.0.1", PORT), _Handler)
        t = threading.Thread(target=_server.serve_forever, daemon=True)
        t.start()
        log.info("[local_api] listening on localhost:%d", PORT)
    except Exception as e:
        log.error("[local_api] failed to start: %s", e)


def stop():
    global _server
    if _server:
        _server.shutdown()
        _server = None
