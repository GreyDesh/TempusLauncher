import json
import re
import threading
import requests
from pathlib import Path
from config import LAUNCHER_JSON_URL, NEWS_JSON_URL, CACHE_DIR, CONNECT_JSON_URL
import config as _config

_LAUNCHER_CACHE = CACHE_DIR / "launcher.enc"
_META_CACHE     = CACHE_DIR / "meta.enc"
_NEWS_CACHE     = CACHE_DIR / "news.json"

# Локальные файлы-примеры (для тестирования без GitHub)
_LOCAL_LAUNCHER = Path(__file__).parent.parent / "launcher_example.json"
_LOCAL_META     = Path(__file__).parent.parent / "meta_example.json"
_LOCAL_NEWS     = Path(__file__).parent.parent / "news_example.json"

_FALLBACK_LAUNCHER = {
    "modes": [],
}
_FALLBACK_META = {
    "launcher": {"version": "1.0.0", "update_url": ""},
    "java": {},
}
_FALLBACK_NEWS: list = []


def _read_enc(path: Path) -> str | None:
    """Читает зашифрованный файл, возвращает строку или None."""
    if not path.exists():
        return None
    try:
        import dpapi
        return dpapi.decrypt(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_enc(path: Path, text: str):
    """Шифрует и записывает строку в файл."""
    try:
        import dpapi
        path.write_text(dpapi.encrypt(text), encoding="utf-8")
    except Exception:
        pass


def _get_verify():
    from config import SSL_VERIFY
    return SSL_VERIFY


def _fetch_text(url: str, timeout: int = 10) -> str | None:
    try:
        verify = _get_verify() if "github" not in url else True
        r = requests.get(url, timeout=timeout, verify=verify)
        r.raise_for_status()
        return r.text
    except Exception:
        return None


def _load_cached(path: Path, fallback, encrypted: bool = False):
    if path.exists():
        try:
            text = _read_enc(path) if encrypted else path.read_text(encoding="utf-8")
            if text:
                return json.loads(text)
        except Exception:
            pass
    return fallback


def _local_fallback(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def _fetch_json(url: str, cache_path: Path, local_path: Path, fallback: dict | list,
                placeholder="YOUR_USER", encrypted: bool = False):
    if placeholder not in url:
        text = _fetch_text(url)
    else:
        text = None
    if text is None:
        cached = _load_cached(cache_path, None, encrypted=encrypted)
        return cached if cached else _local_fallback(local_path, fallback)
    cached_text = (_read_enc(cache_path) or "") if encrypted else (
        cache_path.read_text(encoding="utf-8") if cache_path.exists() else "")
    if text != cached_text:
        if encrypted:
            _write_enc(cache_path, text)
        else:
            cache_path.write_text(text, encoding="utf-8")
    try:
        return json.loads(text)
    except Exception:
        return _local_fallback(local_path, fallback)


def fetch_connect_json():
    """Загружает connect.json с GitHub: адрес серверов, соцсети.
    server_url  — лаунчерный API (server_launcher, port 7531)
    site_url    — сайт/банк (server_main, port 443)
    """
    try:
        r = requests.get(CONNECT_JSON_URL, timeout=8, verify=True)
        data = r.json()
        url = data.get("server_url", "").rstrip("/")
        if url:
            _config.SERVER_URL = url
        site_url = data.get("site_url", "").rstrip("/")
        if site_url:
            _config.SITE_URL = site_url
        else:
            _config.SITE_URL = _config.SERVER_URL  # fallback: один сервер
        _config.SERVER_IP      = data.get("server_ip", _config.SERVER_IP)
        _config.SOCIAL         = data.get("social", {}) or {}
    except Exception:
        pass  # оставить значения по умолчанию из config.py
    _config.LAUNCHER_JSON_URL = f"{_config.SERVER_URL}/api/launcher/config"


def _launcher_config_url() -> str:
    """URL конфига с uuid — сервер по нему решает, какие hidden-режимы отдать.
    Используется И при первичной загрузке, И при SSE-проверке изменений (иначе
    сравнение шло бы против кэша с другим URL и рассинхронилось)."""
    url = _config.LAUNCHER_JSON_URL
    try:
        import auth_client
        _uuid = auth_client._load_settings().get("uuid", "")
        if _uuid:
            url = f"{url}{'&' if '?' in url else '?'}uuid={_uuid}"
    except Exception:
        pass
    return url


def fetch_launcher_config(on_progress=None) -> dict:
    if on_progress:
        on_progress("Загрузка конфигурации лаунчера...")
    launcher = _fetch_json(_launcher_config_url(), _LAUNCHER_CACHE, _LOCAL_LAUNCHER, _FALLBACK_LAUNCHER, encrypted=True)
    # Структура result сохранена; источники: java — вшит, social/фон/маскот — connect.json
    # Нужно убрать!
    result = dict(launcher)
    result["social"] = _config.SOCIAL
    result["java"]   = _config.JAVA
    result["_meta"]  = {"background_url": _config.BACKGROUND_URL,
                        "maskot_url": _config.MASKOT_URL}
    return result


def fetch_news(on_progress=None) -> list:
    if on_progress:
        on_progress("Загрузка новостей...")
    return _fetch_json(NEWS_JSON_URL, _NEWS_CACHE, _LOCAL_NEWS, _FALLBACK_NEWS)


# Кэш новостей режимов: в памяти (мгновенно в рамках сессии) + на диске (офлайн, мгновенный показ при следующем запуске). По файлу на режим.
# Нужно для для DEBUG START LOCAL LAUNCHER TEST
_MODE_NEWS_MEM: dict[str, list] = {}


def _mode_news_cache_path(mode_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", mode_id)
    return CACHE_DIR / f"news_{safe}.json"


def load_cached_mode_news(mode_id: str) -> list | None:
    """Кэш новостей режима (память → диск). None, если кэша ещё нет."""
    if not mode_id:
        return None
    if mode_id in _MODE_NEWS_MEM:
        return _MODE_NEWS_MEM[mode_id]
    p = _mode_news_cache_path(mode_id)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                _MODE_NEWS_MEM[mode_id] = data
                return data
        except Exception:
            pass
    return None


def fetch_mode_news(mode_id: str) -> list:
    """Новости конкретного режима с сервера (вкладка «Новости» в лаунчере).
    image приходит относительным (/static/...) — подставляем SERVER_URL.
    Успех → пишем кэш (память+диск). Ошибка → отдаём кэш (или пусто)."""
    if not mode_id:
        return []
    try:
        url = f"{_config.SERVER_URL}/api/launcher/modes/{mode_id}/news"
        r = requests.get(url, timeout=8, verify=_get_verify())
        r.raise_for_status()
        items = r.json().get("news", []) or []
    except Exception:
        cached = load_cached_mode_news(mode_id)
        return cached if cached is not None else []
    out = []
    for n in items:
        img = (n.get("image") or "").strip()
        if img.startswith("/"):
            img = f"{_config.SERVER_URL}{img}"
        out.append({**n, "image": img})
    _MODE_NEWS_MEM[mode_id] = out
    try:
        _mode_news_cache_path(mode_id).write_text(
            json.dumps(out, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return out


def ping_server(server_ip: str) -> str | None:
    try:
        from mcstatus import JavaServer
        host, _, port_str = server_ip.partition(":")
        port = int(port_str) if port_str else 25565
        server = JavaServer(host, port, timeout=3)
        status = server.status()
        return f"{status.players.online}/{status.players.max}"
    except Exception:
        return None


class ConfigWatcher:
    """Фоновый поток: SSE push от сервера + поллинг раз в час как fallback."""

    def __init__(self, on_launcher_update, on_news_update, on_friends_update=None,
                 on_media_update=None, on_roles_update=None,
                 on_message=None, on_message_read=None, on_connect=None,
                 on_mode_news_update=None, on_feed_update=None):
        self._on_launcher = on_launcher_update
        self._on_news = on_news_update
        self._on_friends = on_friends_update
        self._on_media = on_media_update
        self._on_roles = on_roles_update
        self._on_message = on_message
        self._on_message_read = on_message_read
        self._on_connect = on_connect
        # SSE 'news_updated' — новости режима
        self._on_mode_news = on_mode_news_update
        # SSE 'feed_updated' — посты-скриншоты
        self._on_feed = on_feed_update
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._sse_thread = threading.Thread(target=self._sse_run, daemon=True)
        import random
        self._jitter = random.randint(0, 300)

    def start(self):
        self._thread.start()
        self._sse_thread.start()

    def stop(self):
        self._stop.set()

    def _seconds_until_next_hour(self) -> float:
        from datetime import datetime
        now = datetime.now()
        seconds_past = now.minute * 60 + now.second
        return max(0, 3600 - seconds_past) + self._jitter

    def _run(self):
        # Первые 10 минут — проверяем каждую минуту (ловим быстрые изменения после запуска)
        for _ in range(10):
            if self._stop.wait(60):
                return
            self._check_launcher()
            self._check_news()
            self._check_media()
        # Дальше — раз в час + jitter
        while not self._stop.is_set():
            if self._stop.wait(3600 + self._jitter):
                return
            self._check_launcher()
            self._check_news()
            self._check_media()

    def _check_media(self):
        """Опрос медиа-манифеста: если картинки изменились — синхронит и зовёт callback."""
        try:
            import media_sync
            if media_sync.sync() and self._on_media:
                self._on_media()
        except Exception:
            pass

    def _check_launcher(self):
        import logging
        log = logging.getLogger("api.sse")
        launcher_text = _fetch_text(_launcher_config_url())
        log.info("[check] launcher fetched=%s", launcher_text is not None)
        changed = False
        if launcher_text:
            cached = _read_enc(_LAUNCHER_CACHE) or ""
            log.info("[check] launcher changed=%s (len new=%d cached=%d)", launcher_text != cached, len(launcher_text), len(cached))
            if launcher_text != cached:
                _write_enc(_LAUNCHER_CACHE, launcher_text)
                changed = True
        log.info("[check] overall changed=%s → calling on_launcher=%s", changed, changed)
        if changed:
            try:
                self._on_launcher(fetch_launcher_config())
            except Exception as e:
                log.error("[check] on_launcher error: %s", e)

    def _check_news(self):
        text = _fetch_text(NEWS_JSON_URL)
        if text is None:
            return
        cached = _NEWS_CACHE.read_text(encoding="utf-8") if _NEWS_CACHE.exists() else ""
        if text != cached:
            _NEWS_CACHE.write_text(text, encoding="utf-8")
            try:
                self._on_news(json.loads(text))
            except Exception:
                pass

    def _sse_run(self):
        """Подключается к SSE и при событии config_updated сразу обновляет конфиг."""
        import logging, time
        log = logging.getLogger("api.sse")
        # Ждём пока SERVER_URL заполнится из connect.json (теперь на главном хосте)
        self._stop.wait(5)
        while not self._stop.is_set():
            try:
                from config import SERVER_URL
                url = f"{SERVER_URL}/api/launcher/events"
                log.info("[SSE] Подключение к %s", url)
                import auth_client
                headers = auth_client.session_headers()
                with requests.get(url, stream=True, timeout=(10, 120), verify=_get_verify(), headers=headers) as r:
                    if r.status_code in (401, 422):
                        # 401 — сессия истекла (сервер перезапущен) (токены в озу памяти нет)
                        # 422 — токена вообще нет, нужно пересоздать сессию SSH
                        log.info("[SSE] %s — пересоздаю сессию", r.status_code)
                        if not auth_client.create_session():
                            log.warning("[SSE] create_session не удался (игрок не найден в БД?) — жду 15s")
                            self._stop.wait(15)
                        else:
                            self._stop.wait(2)
                        continue
                    r.raise_for_status()
                    log.info("[SSE] Соединение установлено")
                    # Ресинк после пере-подключения: пока не было связи (рестарт)
                    # Мы теряемся,пере-подключаемся конфиг/медиа/новости
                    # И внешние подписчики (друзья/непрочитанное).
                    self._check_media()
                    self._check_launcher()
                    self._check_news()
                    if self._on_connect:
                        try:
                            self._on_connect()
                        except Exception:
                            pass
                    for line in r.iter_lines(decode_unicode=True):
                        if self._stop.is_set():
                            return
                        if line.startswith("event:") and "config_updated" in line:
                            t = time.strftime("%H:%M:%S")
                            log.info("[SSE %s] Получено обновление конфига — применяю", t)
                            # Преднамеренная загрузка контента.
                            # Сначала докачиваем картинки, потом обновляем список режимов (новая сборка тянет свои медиа(Теперь на главном сервере)),
                            # Необходимо чтобы новый режим отрисовался с иконкой.
                            self._check_media()
                            self._check_launcher()
                            self._check_news()
                        elif line.startswith("event:") and "friends_updated" in line:
                            t = time.strftime("%H:%M:%S")
                            if self._on_friends:
                                try:
                                    self._on_friends()
                                except Exception:
                                    pass
                            log.info("[SSE %s] friends_updated", t)
                        elif line.startswith("event:") and "media_updated" in line:
                            t = time.strftime("%H:%M:%S")
                            log.info("[SSE %s] media_updated — синхронизирую картинки", t)
                            self._check_media()
                        elif line.startswith("event:") and "news_updated" in line:
                            t = time.strftime("%H:%M:%S")
                            log.info("[SSE %s] news_updated — обновляю ленту новостей", t)
                            if self._on_mode_news:
                                try:
                                    self._on_mode_news()
                                except Exception:
                                    pass
                        elif line.startswith("event:") and "feed_updated" in line:
                            t = time.strftime("%H:%M:%S")
                            log.info("[SSE %s] feed_updated — обновляю ленту скриншотов", t)
                            if self._on_feed:
                                try:
                                    self._on_feed()
                                except Exception:
                                    pass
                        elif line.startswith("event:") and "roles_updated" in line:
                            t = time.strftime("%H:%M:%S")
                            log.info("[SSE %s] roles_updated — перечитываю роли Discord", t)
                            if self._on_roles:
                                try:
                                    self._on_roles()
                                except Exception:
                                    pass
                            # Роль влияет и на видимость hidden-режимов (фильтр по роли дискорд)
                            self._check_launcher()
                        elif line.startswith("event:") and "message_read" in line:
                            # Проверяем до "message"
                            if self._on_message_read:
                                try:
                                    self._on_message_read()
                                except Exception:
                                    pass
                        elif line.startswith("event:") and "message" in line:
                            if self._on_message:
                                try:
                                    self._on_message()
                                except Exception:
                                    pass
            except Exception as e:
                log.warning("[SSE] Ошибка: %s — переподключение через 15s", e)
                self._stop.wait(15)
