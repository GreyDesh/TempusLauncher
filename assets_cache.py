import hashlib
import requests
from pathlib import Path
from PyQt6.QtCore import QRunnable, QThreadPool, pyqtSignal, QObject
from PyQt6.QtGui import QPixmap
from config import CACHE_DIR, BASE_DIR


def _is_local(url: str) -> bool:
    return not url.startswith("http://") and not url.startswith("https://")


def _resolve_local(url: str) -> Path:
    # картинки режимов: media_cache/<имя> -> локально скачанный media_sync файл
    if url.startswith("media_cache/"):
        from config import MEDIA_CACHE_DIR
        return MEDIA_CACHE_DIR / url[len("media_cache/"):]
    p = Path(url)
    if p.is_absolute():
        return p
    candidates = [BASE_DIR / url, BASE_DIR.parent / url, Path(url)]
    for c in candidates:
        if c.exists():
            return c
    return BASE_DIR.parent / url


def _url_to_path(url: str) -> Path:
    name = hashlib.md5(url.encode()).hexdigest()
    ext = url.split("?")[0].rsplit(".", 1)[-1]
    if ext not in ("png", "jpg", "jpeg", "webp", "gif"):
        ext = "png"
    return CACHE_DIR / f"{name}.{ext}"


def get_cached_path(url: str) -> Path | None:
    if not url:
        return None
    if _is_local(url):
        p = _resolve_local(url)
        return p if p.exists() else None
    p = _url_to_path(url)
    return p if p.exists() else None


class _PixmapSignals(QObject):
    done   = pyqtSignal(str, QPixmap)
    failed = pyqtSignal(str)


class PixmapLoader(QRunnable):
    def __init__(self, url: str, signals: _PixmapSignals):
        super().__init__()
        self.url = url
        self.signals = signals

    def run(self):
        if _is_local(self.url):
            path = _resolve_local(self.url)
        else:
            path = _url_to_path(self.url)
            if not path.exists():
                try:
                    r = requests.get(self.url, timeout=15)
                    r.raise_for_status()
                    path.write_bytes(r.content)
                except Exception:
                    self.signals.failed.emit(self.url)
                    return
        px = QPixmap(str(path))
        if px.isNull():
            self.signals.failed.emit(self.url)
        else:
            self.signals.done.emit(self.url, px)


class AssetCache:
    _pool = QThreadPool.globalInstance()

    @classmethod
    def load(cls, url: str, on_done, on_failed=None):
        if not url:
            return
        if _is_local(url):
            path = _resolve_local(url)
            px = QPixmap(str(path))
            if not px.isNull():
                on_done(url, px)
            elif on_failed:
                on_failed(url)
            return
        path = _url_to_path(url)
        if path.exists():
            px = QPixmap(str(path))
            if not px.isNull():
                on_done(url, px)
                return
        signals = _PixmapSignals()
        signals.done.connect(on_done)
        if on_failed:
            signals.failed.connect(on_failed)
        cls._pool.start(PixmapLoader(url, signals))

    @classmethod
    def preload_all(cls, urls: list[str], on_progress=None, on_all_done=None):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        urls = [u for u in urls if u]
        total = len(urls)

        def _download_one(url):
            path = _url_to_path(url)
            if not path.exists():
                try:
                    r = requests.get(url, timeout=15)
                    r.raise_for_status()
                    path.write_bytes(r.content)
                except Exception:
                    pass

        done = 0
        if total:
            with ThreadPoolExecutor(max_workers=8) as pool:
                for _ in as_completed([pool.submit(_download_one, u) for u in urls]):
                    done += 1
                    if on_progress:
                        on_progress(f"Загрузка ресурсов... {done}/{total}", done / total)
        if on_all_done:
            on_all_done()
