# Официальные плащи Mojang: список владеемых, скачивание текстур, активация.

# Работает только для лицензионных аккаунтов (есть токен). Функции блокирующие — звать из фоновых потоков, не из UI.
# Хотя пиратки нет в планах, но пиратка может иметь ввиду обход Mojang, Xbox, Microsoft Аккаунты.

import requests
from pathlib import Path
from config import CACHE_DIR

_PROFILE = "https://api.minecraftservices.com/minecraft/profile"
_ACTIVE = "https://api.minecraftservices.com/minecraft/profile/capes/active"


def _verify():
    from config import SSL_VERIFY
    return SSL_VERIFY


def fetch_owned_capes(token: str) -> list[dict]:
    """[{id, state, url, alias}] — плащи аккаунта. Пусто при ошибке/офлайне."""
    if not token:
        return []
    try:
        r = requests.get(_PROFILE, headers={"Authorization": f"Bearer {token}"},
                         timeout=10, verify=_verify())
        if r.status_code != 200:
            return []
        return r.json().get("capes", []) or []
    except Exception:
        return []


def cape_texture(cape: dict) -> str | None:
    """Скачивает текстуру плаща в CACHE_DIR/cape_<id>.png, возвращает путь."""
    cid, url = cape.get("id"), cape.get("url")
    if not cid or not url:
        return None
    p = CACHE_DIR / f"cape_{cid}.png"
    if not p.exists():
        try:
            r = requests.get(url, timeout=15, verify=_verify())
            r.raise_for_status()
            p.write_bytes(r.content)
        except Exception:
            return None
    return str(p)


def set_active_cape(token: str, cape_id: str | None) -> bool:
    """Активирует плащ на аккаунте (в игре) или снимает (cape_id=None)."""
    if not token:
        return False
    try:
        if cape_id:
            r = requests.put(_ACTIVE, headers={"Authorization": f"Bearer {token}"},
                             json={"capeId": cape_id}, timeout=10, verify=_verify())
        else:
            r = requests.delete(_ACTIVE, headers={"Authorization": f"Bearer {token}"},
                                timeout=10, verify=_verify())
        return r.status_code in (200, 204)
    except Exception:
        return False
