"""Плейтайм — серверный подсчёт как в Steam.
Лаунчер только сообщает старт/пинг/стоп, сервер считает время сам."""
import threading
import requests
import logging
from datetime import datetime, timezone

log = logging.getLogger("playtime")

# Кеш с сервера (только для отображения в UI)
_cache: dict = {}

# Текущая активная сессия
_session_id: str | None = None
_session_mode_id: str | None = None
_ping_timer: threading.Timer | None = None
_PING_INTERVAL = 5 * 60  # 5 минут


def _get_discord_id() -> str | None:
    import auth_client
    return auth_client._load_settings().get("discord_id")


def _verify():
    import sys
    from config import SERVER_CERT
    if SERVER_CERT.exists():
        return str(SERVER_CERT)
    return True if getattr(sys, 'frozen', False) else __import__('certifi').where()


def start_session(mode_id: str):
    """Вызывается когда Minecraft запустился. Сервер фиксирует время старта."""
    discord_id = _get_discord_id()
    if not discord_id:
        return
    threading.Thread(target=_do_start, args=(mode_id, discord_id), daemon=True).start()


def _do_start(mode_id: str, discord_id: str):
    global _session_id, _session_mode_id
    try:
        import config
        r = requests.post(
            f"{config.SERVER_URL}/api/playtime/start",
            json={"discord_id": discord_id, "mode_id": mode_id},
            timeout=8, verify=_verify(),
        )
        if r.status_code == 200:
            _session_id = r.json().get("session_id")
            _session_mode_id = mode_id
            log.info(f"Сессия начата: {_session_id} mode={mode_id}")
            # Сразу помечаем «играл сегодня» в локальном кеше для UI
            entry = _cache.get(mode_id, {"seconds": 0, "last_played": None})
            entry["last_played"] = datetime.now(timezone.utc).isoformat()
            _cache[mode_id] = entry
            _schedule_ping()
        else:
            log.warning(f"start_session: {r.status_code} {r.text}")
    except Exception as e:
        log.error(f"start_session error: {e}")


def _schedule_ping():
    global _ping_timer
    _cancel_ping()
    _ping_timer = threading.Timer(_PING_INTERVAL, _do_ping)
    _ping_timer.daemon = True
    _ping_timer.start()


def _cancel_ping():
    global _ping_timer
    if _ping_timer:
        _ping_timer.cancel()
        _ping_timer = None


def _do_ping():
    if not _session_id:
        return
    try:
        import config
        r = requests.post(
            f"{config.SERVER_URL}/api/playtime/ping/{_session_id}",
            timeout=8, verify=_verify(),
        )
        log.info(f"Пинг сессии {_session_id}: {r.status_code}")
    except Exception as e:
        log.error(f"ping error: {e}")
    finally:
        if _session_id:
            _schedule_ping()


def stop_session():
    """Вызывается когда Minecraft закрылся. Сервер считает итоговое время."""
    global _session_id, _session_mode_id
    _cancel_ping()
    if not _session_id:
        return
    sid = _session_id
    mid = _session_mode_id
    _session_id = None
    _session_mode_id = None
    threading.Thread(target=_do_stop, args=(sid, mid), daemon=True).start()


def _do_stop(session_id: str, mode_id: str | None):
    try:
        import config
        r = requests.post(
            f"{config.SERVER_URL}/api/playtime/stop/{session_id}",
            timeout=8, verify=_verify(),
        )
        if r.status_code == 200:
            data = r.json()
            seconds = data.get("seconds", 0)
            log.info(f"Сессия завершена: {session_id}, засчитано {seconds:.0f} сек")
            # Обновляем локальный кеш для UI
            if mode_id:
                entry = _cache.get(mode_id, {"seconds": 0, "last_played": None})
                entry["seconds"] = entry.get("seconds", 0) + seconds
                entry["last_played"] = datetime.now(timezone.utc).isoformat()
                _cache[mode_id] = entry
        else:
            log.warning(f"stop_session: {r.status_code} {r.text}")
    except Exception as e:
        log.error(f"stop_session error: {e}")


def get(mode_id: str) -> dict:
    return _cache.get(mode_id, {"seconds": 0, "last_played": None})


def fetch_from_server() -> bool:
    """Загружает плейтайм с сервера в кеш для отображения в UI."""
    global _cache
    try:
        import config
        discord_id = _get_discord_id()
        if not discord_id:
            return True
        r = requests.get(
            f"{config.SERVER_URL}/api/playtime/{discord_id}",
            timeout=8, verify=_verify(),
        )
        if r.status_code == 200:
            _cache = r.json()
            return True
    except Exception:
        pass
    return False


def format_hours(seconds: float) -> str:
    h = int(seconds // 3600)
    if h == 0:
        m = int(seconds // 60)
        return f"{m} мин" if m > 0 else "< 1 мин"
    return f"{h} ч"


def format_last_played(iso: str | None) -> str:
    if not iso:
        return "Никогда"
    try:
        dt = datetime.fromisoformat(iso).astimezone()
        now = datetime.now(dt.tzinfo)
        days = (now - dt).days
        if days == 0:
            return "Сегодня"
        if days == 1:
            return "Вчера"
        if days < 7:
            return f"{days} дн. назад"
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return "—"
