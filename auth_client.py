import json
import requests
from config import SETTINGS_FILE, DEV_BYPASS_AUTH, DEV_USERNAME


def _verify():
    from config import SSL_VERIFY
    return SSL_VERIFY

# Кеш ролей Discord — заполняется при старте лаунчера
_discord_roles: set[str] = set()


def sync_discord_link() -> bool | None:
    """Сверяет локальную привязку Discord с авторитетным состоянием в БД сервера
    (`/api/link/discord/{uuid}` читает привязку прямо из таблицы players).

    - 200 linked=true  → сохраняем discord_id/username из БД.
    - 200 linked=false → БД ТОЧНО не знает привязки (напр. база была пересоздана) →
      стираем локальную привязку, чтобы лаунчер не врал «привязан».
    - иначе (сеть/500/исключение) → НЕ трогаем привязку (транзиентный сбой).

    Возвращает True/False = актуальное состояние привязки, None = не удалось проверить.
    """
    from config import SERVER_URL
    settings = _load_settings()
    uuid = settings.get("uuid", "")
    if not uuid:
        return None
    try:
        r = requests.get(f"{SERVER_URL}/api/link/discord/{uuid}", timeout=8, verify=_verify())
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except Exception:
        return None
    if data.get("linked"):
        _save_settings({
            "discord_id": str(data.get("discord_id", "")),
            "discord_username": data.get("discord_name", ""),
        })
        return True
    # Авторитетный ответ БД: привязки нет. Стираем локальную (если была).
    if settings.get("discord_id"):
        _save_settings({"discord_id": None, "discord_username": None})
    _discord_roles.clear()
    return False


def fetch_discord_roles() -> None:
    """Сверяет привязку с БД, затем загружает роли Discord и кеширует их в память."""
    global _discord_roles
    from config import SERVER_URL
    # Сначала авторитетная сверка привязки с БД (может стереть протухшую привязку).
    linked = sync_discord_link()
    if linked is False:
        _discord_roles.clear()
        return

    settings = _load_settings()
    uuid = settings.get("uuid", "")
    if not uuid or not settings.get("discord_id"):
        return
    try:
        r = requests.get(f"{SERVER_URL}/api/link/roles/{uuid}", timeout=8, verify=_verify())
        if r.status_code == 200:
            data = r.json()
            _discord_roles = set(data.get("roles", []))
            if data.get("reason") == "not_linked":
                # Роли не пришли по транзиентной причине (бот не в гильдии). discord_id
                # тут НЕ стираем — за авторитетный сброс отвечает sync_discord_link выше.
                _discord_roles.clear()
            elif data.get("discord_id"):
                _save_settings({"discord_id": data["discord_id"], "discord_username": data.get("discord_name", "")})
    except Exception:
        pass


def has_discord_role(role_id: str) -> bool:
    return str(role_id) in _discord_roles


def refresh_discord_roles() -> bool:
    """Перезапрашивает привязку/роли с сервера. Возвращает True, если набор ролей
    или сам факт привязки изменился (нужно перерисовать текущий режим)."""
    before_roles = set(_discord_roles)
    before_linked = bool(_load_settings().get("discord_id"))
    fetch_discord_roles()
    after_linked = bool(_load_settings().get("discord_id"))
    return _discord_roles != before_roles or after_linked != before_linked


_ENCRYPTED_FIELDS = {"token", "refresh_token"}


def _load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
        from dpapi import decrypt
        for field in _ENCRYPTED_FIELDS:
            if raw.get(field):
                raw[field] = decrypt(raw[field])
        return raw
    return {}


def _save_settings(data: dict):
    from dpapi import encrypt
    existing = _load_settings()
    existing.update(data)
    to_write = dict(existing)
    for field in _ENCRYPTED_FIELDS:
        if to_write.get(field):
            to_write[field] = encrypt(to_write[field])
    SETTINGS_FILE.write_text(json.dumps(to_write, ensure_ascii=False, indent=2), encoding="utf-8")


def verify_token() -> str | None:
    """Проверяет сохранённый MS токен через Minecraft API. Discord — дополнительная привязка, не primary auth."""
    if DEV_BYPASS_AUTH:
        return DEV_USERNAME
    settings = _load_settings()
    auth_type = settings.get("auth_type")
    token = settings.get("token")
    if not token:
        return None

    if auth_type == "microsoft":
        # Проверяем MC токен через official API
        try:
            r = requests.get(
                "https://api.minecraftservices.com/minecraft/profile",
                headers={"Authorization": f"Bearer {token}"},
                timeout=8,
            )
            if r.status_code == 200:
                data = r.json()
                username = data.get("name", settings.get("username"))
                if username and username != settings.get("username"):
                    _save_settings({"username": username})
                return username
            if r.status_code in (401, 403):
                # Токен истёк — пробуем refresh
                refresh_token = settings.get("refresh_token")
                if refresh_token:
                    try:
                        import ms_auth
                        profile = ms_auth.refresh_auth(refresh_token)
                        _save_settings({
                            "token":         profile["mc_token"],
                            "refresh_token": profile["refresh_token"],
                            "username":      profile["username"],
                            "uuid":          profile["uuid"],
                            "skin_variant":  profile.get("skin_variant", "classic"),
                        })
                        return profile["username"]
                    except Exception:
                        pass
        except Exception:
            pass
        # Если нет сети — вернуть сохранённый ник (оффлайн режим)
        saved = settings.get("username")
        if saved:
            return saved
        return None

    return None


def refresh_for_launch() -> None:
    """Best-effort обновление Minecraft-токена перед запуском игры.

    Если есть refresh_token — обновляем mc_token (свежий ~24ч токен снижает шанс, что
    лицензионный сервер посчитает сессию невалидной). Если refresh_token нет (текущий
    вход через implicit web-флоу его не выдаёт) или обновление не удалось — НЕ блокируем
    запуск: играем с текущим mc_token. Блокировать вход в игру из-за этого нельзя.
    """
    if DEV_BYPASS_AUTH:
        return
    settings = _load_settings()
    if settings.get("auth_type") != "microsoft":
        return
    import logging
    log = logging.getLogger("auth")
    refresh_token = settings.get("refresh_token")
    if not refresh_token:
        log.info("[launch] нет refresh_token — запуск с текущим mc_token без обновления")
        return
    try:
        import ms_auth
        profile = ms_auth.refresh_auth(refresh_token)
    except Exception as e:
        log.warning("[launch] обновление токена не удалось (%s) — запуск с текущим mc_token", e)
        return
    _save_settings({
        "token":         profile["mc_token"],
        "refresh_token": profile["refresh_token"],
        "username":      profile["username"],
        "uuid":          profile["uuid"],
        "skin_variant":  profile.get("skin_variant", "classic"),
    })
    log.info("[launch] token refreshed for %s", profile["username"])


def get_saved_username() -> str | None:
    return _load_settings().get("username")


def create_session() -> str | None:
    """Создаёт сессионный токен на сервере. Возвращает токен или None."""
    import logging
    log = logging.getLogger("api.sse")
    from config import SERVER_URL, SERVER_CERT
    settings = _load_settings()
    uuid = settings.get("uuid", "")
    if not uuid:
        log.warning("[session] no uuid, skipping")
        return None
    try:
        verify = _verify()
        log.info("[session] POST /api/auth/session uuid=%s", uuid)
        r = requests.post(
            f"{SERVER_URL}/api/auth/session",
            json={"uuid": uuid},
            timeout=8, verify=verify,
        )
        log.info("[session] response status=%s body=%s", r.status_code, r.text[:200])
        if r.status_code == 200:
            token = r.json().get("session_token")
            _save_settings({"session_token": token})
            log.info("[session] token saved")
            return token
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        log.warning("[session] сервер недоступен (таймаут/сеть): %s", e)   # ожидаемо, без traceback
    except Exception as e:
        log.error("[session] error: %s", e, exc_info=True)
    return None


def get_session_token() -> str | None:
    return _load_settings().get("session_token")


def session_headers() -> dict:
    """Возвращает заголовок X-Session-Token для запросов к серверу."""
    token = get_session_token()
    return {"X-Session-Token": token} if token else {}


def logout():
    _save_settings({"token": None, "refresh_token": None, "username": None,
                    "auth_type": None, "session_token": None})
