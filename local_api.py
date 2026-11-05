import json
import logging
import re
import socket
import threading

log = logging.getLogger("local_api")

# По умолчанию пробуем 19580, если занят — ОС выделит динамический свободный порт.
DEFAULT_PORT = 19580
_current_port = DEFAULT_PORT

_event_handlers: dict[str, list] = {}  # event_name -> [callback]
_server_sock: socket.socket | None = None
_server_thread: threading.Thread | None = None
_stop_event = threading.Event()


def on_event(event_name: str):
    """Декоратор для регистрации обработчика события (например 'CONNECT', 'DISCONNECT')."""
    def decorator(fn):
        _event_handlers.setdefault(event_name.upper(), []).append(fn)
        return fn
    return decorator


def register_handler(event_name: str, fn):
    _event_handlers.setdefault(event_name.upper(), []).append(fn)


def unregister_handler(event_name: str, fn):
    handlers = _event_handlers.get(event_name.upper(), [])
    if fn in handlers:
        handlers.remove(fn)


def _dispatch(event_name: str, data: dict):
    for handler in _event_handlers.get(event_name.upper(), []):
        try:
            handler(data)
        except Exception as e:
            log.error("[local_api] handler error for %s: %s", event_name, e, exc_info=True)


def get_port() -> int:
    """Возвращает фактический порт, на котором слушает local_api."""
    return _current_port


def _parse_payload(raw_text: str):
    """Парсит как чистую строку JSON, так и HTTP POST запрос."""
    text = raw_text.strip()
    if not text:
        return

    # Если пришёл HTTP запрос
    if text.startswith("POST ") or text.startswith("GET "):
        # На GET / ping можно не диспатчить события
        if text.startswith("GET "):
            return
        # Для POST ищем тело после двойного перевода строки
        parts = re.split(r"\r?\n\r?\n", text, maxsplit=1)
        if len(parts) > 1:
            text = parts[1].strip()

    # Парсим JSON
    # В одном сообщении может быть несколько строк JSON
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if isinstance(data, dict):
                # Поддерживаем и "event", и старый "type"
                ev = data.get("event") or data.get("type", "")
                if ev:
                    log.info("[local_api] event=%s data=%s", ev, data)
                    _dispatch(str(ev), data)
        except Exception as e:
            log.warning("[local_api] failed to parse payload line: %r (%s)", line, e)


def _client_handler(conn: socket.socket):
    try:
        conn.settimeout(2.0)
        buf = bytearray()
        while not _stop_event.is_set():
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf.extend(chunk)
            # Если получили завершение строки или конец HTTP заголовков/тела
            if b"\n" in chunk or len(buf) > 16384:
                break

        raw_text = buf.decode("utf-8", errors="replace")
        _parse_payload(raw_text)

        # Отправляем подтверждение (совместимо с raw socket и HTTP клиентами)
        try:
            if raw_text.startswith("POST ") or raw_text.startswith("GET "):
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"ok\":true}")
            else:
                conn.sendall(b"{\"ok\":true}\n")
        except Exception:
            pass
    except Exception as e:
        log.debug("[local_api] client error: %s", e)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _server_loop(sock: socket.socket):
    while not _stop_event.is_set():
        try:
            conn, _ = sock.accept()
            t = threading.Thread(target=_client_handler, args=(conn,), daemon=True)
            t.start()
        except (socket.timeout, BlockingIOError):
            continue
        except Exception:
            break


def start() -> int:
    """Запускает TCP сервер на 127.0.0.1. Возвращает номер порта."""
    global _server_sock, _server_thread, _current_port
    if _server_sock is not None:
        return _current_port

    _stop_event.clear()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    port = DEFAULT_PORT
    try:
        sock.bind(("127.0.0.1", port))
    except Exception:
        # Если порт 19580 занят — просим ОС выделить любой свободный
        try:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        except Exception as e:
            log.error("[local_api] failed to bind 127.0.0.1: %s", e)
            sock.close()
            return 0

    sock.listen(16)
    sock.settimeout(1.0)
    _current_port = port
    _server_sock = sock

    _server_thread = threading.Thread(target=_server_loop, args=(sock,), daemon=True)
    _server_thread.start()
    log.info("[local_api] listening on 127.0.0.1:%d", _current_port)
    return _current_port


def stop():
    global _server_sock, _server_thread
    _stop_event.set()
    if _server_sock:
        try:
            _server_sock.close()
        except Exception:
            pass
        _server_sock = None
    _server_thread = None
