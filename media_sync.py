
# Синхронизация картинок режимов.

# Сервер отдаёт манифест: per-file sha256 + бандл. Лаунчер сравнивает со своим
# состоянием и выбирает стратегию:
#  - кеша нет (новичок) или изменилось > половины -> качает bundle.zip целиком;
#  - изменилось мало -> качает точечно по одному;
#  - ничего не изменилось -> не качает.
# Целостность каждого файла и бандла проверяется по sha256.

import hashlib
import io
import json
import zipfile
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

import config as _config
from config import MEDIA_CACHE_DIR

_STATE = MEDIA_CACHE_DIR / "_state.json"     # {имя: sha256} — что уже скачано
_BUNDLE_THRESHOLD = 0.5                        # >половины изменилось -> брать бандл


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _file_sha(name: str) -> str:
    p = MEDIA_CACHE_DIR / name
    return _sha(p.read_bytes()) if p.exists() else ""


def _load_state() -> dict:
    try:
        return json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(st: dict):
    MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _STATE.write_text(json.dumps(st), encoding="utf-8")
    except Exception:
        pass


def sync(on_progress=None) -> bool:
    """Приводит локальные картинки в соответствие с манифестом сервера.
    Возвращает True, если что-то скачалось/изменилось (для живой перерисовки)."""
    MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    base = _config.SERVER_URL
    try:
        man = requests.get(f"{base}/api/launcher/media/manifest", timeout=10).json()
    except Exception:
        return False  # нет сети — работаем на том, что уже в кеше

    files = man.get("files", {})              # {имя: {"sha256": ...}}
    if not files:
        return False
    state = _load_state()
    changed = [n for n, meta in files.items()
               if state.get(n) != meta.get("sha256") or not (MEDIA_CACHE_DIR / n).exists()]
    if not changed:
        return False

    total = len(files)
    if not state or len(changed) > total * _BUNDLE_THRESHOLD:
        _download_bundle(base, man, on_progress)          # много/новичок -> бандл
    else:
        _download_individual(base, changed, files, on_progress)  # мало -> точечно

    # обновляем состояние только по реально скачанным с верным хешем
    st = _load_state()
    updated = False
    for n, meta in files.items():
        if _file_sha(n) == meta.get("sha256"):
            if st.get(n) != meta["sha256"]:
                updated = True
            st[n] = meta["sha256"]
    _save_state(st)
    return updated


def _download_bundle(base, man, on_progress):
    if on_progress:
        on_progress("Загрузка медиа...", 0.0)
    url = man.get("bundle", {}).get("url", "")
    if url.startswith("/"):
        url = base + url
    try:
        data = requests.get(url, timeout=90).content
    except Exception:
        return
    want = man.get("bundle", {}).get("sha256", "")
    if want and _sha(data) != want:
        return  # битый бандл — не распаковываем
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            z.extractall(MEDIA_CACHE_DIR)
    except Exception:
        return
    if on_progress:
        on_progress("Медиа загружено", 1.0)


def _download_individual(base, changed, files, on_progress):
    n_total = len(changed)

    def _one(name):
        try:
            data = requests.get(f"{base}/api/launcher/media/{name}", timeout=30).content
            if _sha(data) == files[name].get("sha256"):
                (MEDIA_CACHE_DIR / name).write_bytes(data)
        except Exception:
            pass

    done = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for _ in as_completed([pool.submit(_one, n) for n in changed]):
            done += 1
            if on_progress:
                on_progress(f"Обновление медиа {done}/{n_total}", done / n_total)
