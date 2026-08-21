# Microsoft OAuth для Minecraft.
import threading
import time
import urllib.parse
import requests

_CLIENT_ID   = "00000000402b5328"
_REDIRECT    = "https://login.live.com/oauth20_desktop.srf"
_SCOPE       = "service::user.auth.xboxlive.com::MBI_SSL"

# Device Code Flow (публичный client_id Minecraft Launcher)
_DEVICE_CLIENT_ID = "40fd4978-5a64-430d-9766-fcf9054a3719"
_DEVICE_SCOPE     = "XboxLive.signin offline_access"
_DEVICE_CODE_URL  = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
_DEVICE_TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"

# Authorization code flow (легаси MSA-клиент 00000000402b5328).
# В отличие от implicit (response_type=token) даёт refresh_token, и — в отличие от
# device-code клиента 40fd4978 — проходит login_with_xbox без 403. Проверено вживую.
# Я ебал кодить с нуля - 3 недели.
_TOKEN_URL   = "https://login.live.com/oauth20_token.srf"
_AUTH_URL    = (
    "https://login.live.com/oauth20_authorize.srf"
    f"?client_id={_CLIENT_ID}"
    "&response_type=code"
    f"&redirect_uri={urllib.parse.quote(_REDIRECT, safe='')}"
    f"&scope={urllib.parse.quote(_SCOPE, safe='')}"
    "&prompt=login"
    "&locale=ru"
)
_XBL_URL     = "https://user.auth.xboxlive.com/user/authenticate"
_XSTS_URL    = "https://xsts.auth.xboxlive.com/xsts/authorize"
_MC_URL      = "https://api.minecraftservices.com/authentication/login_with_xbox"
_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"


def get_auth_url() -> str:
    return _AUTH_URL



def _xbl(ms_token: str) -> tuple[str, str]:
    import logging
    log = logging.getLogger("ms_auth")
    r = requests.post(_XBL_URL, json={
        "Properties": {
            "AuthMethod": "RPS",
            "SiteName":   "user.auth.xboxlive.com",
            "RpsTicket":  ms_token,
        },
        "RelyingParty": "http://auth.xboxlive.com",
        "TokenType":    "JWT",
    }, headers={"Content-Type": "application/json", "Accept": "application/json"}, timeout=15)
    log.debug("_xbl: status=%s body=%s", r.status_code, r.text[:400])
    r.raise_for_status()
    d = r.json()
    return d["Token"], d["DisplayClaims"]["xui"][0]["uhs"]


def _xsts(xbl_token: str) -> str:
    import logging
    log = logging.getLogger("ms_auth")
    r = requests.post(_XSTS_URL, json={
        "Properties": {
            "SandboxId":  "RETAIL",
            "UserTokens": [xbl_token],
        },
        "RelyingParty": "rp://api.minecraftservices.com/",
        "TokenType":    "JWT",
    }, headers={"Accept": "application/json"}, timeout=15)
    log.debug("_xsts: status=%s body=%s", r.status_code, r.text[:400])
    r.raise_for_status()
    return r.json()["Token"]


def _mc_token(xsts_token: str, user_hash: str) -> str:
    import logging
    log = logging.getLogger("ms_auth")
    r = requests.post(_MC_URL, json={
        "identityToken": f"XBL3.0 x={user_hash};{xsts_token}",
    }, timeout=15)
    log.debug("_mc_token: status=%s body=%s", r.status_code, r.text[:400])
    r.raise_for_status()
    return r.json()["access_token"]


def _profile(mc_token: str) -> dict:
    r = requests.get(_PROFILE_URL, headers={
        "Authorization": f"Bearer {mc_token}",
    }, timeout=15)
    r.raise_for_status()
    return r.json()


def device_code_start() -> dict:
    """Запрашивает device code. Возвращает {user_code, device_code, verification_uri, expires_in, interval}."""
    import logging
    log = logging.getLogger("ms_auth")
    log.debug("device_code_start: POST %s client_id=%s scope=%s", _DEVICE_CODE_URL, _DEVICE_CLIENT_ID, _DEVICE_SCOPE)
    r = requests.post(_DEVICE_CODE_URL, data={
        "client_id": _DEVICE_CLIENT_ID,
        "scope":     _DEVICE_SCOPE,
    }, timeout=15)
    log.debug("device_code_start: status=%s body=%s", r.status_code, r.text[:800])
    r.raise_for_status()
    return r.json()


def device_code_poll(device_code: str, interval: int, stop_event, on_progress=None) -> dict:
    """Опрашивает токен до получения или отмены. Возвращает profile dict."""
    import logging
    log = logging.getLogger("ms_auth")
    while not stop_event.is_set():
        stop_event.wait(interval)
        if stop_event.is_set():
            raise Exception("Отменено")
        r = requests.post(_DEVICE_TOKEN_URL, data={
            "client_id":   _DEVICE_CLIENT_ID,
            "grant_type":  "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device_code,
        }, timeout=15)
        data = r.json()
        log.debug("device_code_poll: status=%s body=%s", r.status_code, str(data)[:300])
        error = data.get("error", "")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error:
            raise Exception(data.get("error_description", error))
        # Получили токен — XBL через OAuth2 (префикс d=)
        access_token = data["access_token"]
        if on_progress:
            on_progress("Получение Xbox токена...")
        refresh_token = data.get("refresh_token", "")
        if on_progress:
            on_progress("Получение Xbox токена...")
        xbl_token, user_hash = _xbl("d=" + access_token)
        if on_progress:
            on_progress("Получение Minecraft токена...")
        xsts_token = _xsts(xbl_token)
        mc_token   = _mc_token(xsts_token, user_hash)
        profile = _build_profile(mc_token, access_token)
        profile["refresh_token"] = refresh_token
        return profile
    raise Exception("Отменено")


def _fmt_uuid(raw: str) -> str:
    """Добавляет дефисы в UUID если их нет: 32 hex → 8-4-4-4-12."""
    s = raw.replace("-", "")
    if len(s) == 32:
        return f"{s[:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:]}"
    return raw


def _build_profile(mc_token: str, ms_token: str) -> dict:
    r = requests.get(_PROFILE_URL, headers={"Authorization": f"Bearer {mc_token}"}, timeout=15)
    r.raise_for_status()
    profile = r.json()
    skin_variant = "classic"
    for skin in profile.get("skins", []):
        if skin.get("state") == "ACTIVE":
            if skin.get("variant", "").upper() == "SLIM":
                skin_variant = "slim"
            break
    return {
        "username":     profile["name"],
        "uuid":         _fmt_uuid(profile["id"]),
        "mc_token":     mc_token,
        "ms_token":     ms_token,
        "skin_variant": skin_variant,
    }


def exchange_code(code: str) -> dict:
    """Обменивает authorization code на токены (легаси MSA endpoint).
    Даёт access_token + refresh_token → Xbox-цепочка → profile с refresh_token."""
    import logging
    log = logging.getLogger("ms_auth")
    r = requests.post(_TOKEN_URL, data={
        "client_id":    _CLIENT_ID,
        "code":         code,
        "grant_type":   "authorization_code",
        "redirect_uri": _REDIRECT,
        "scope":        _SCOPE,
    }, timeout=20)
    log.debug("exchange_code: status=%s", r.status_code)
    r.raise_for_status()
    data = r.json()
    access_token = data["access_token"]
    refresh      = data.get("refresh_token", "")
    xbl_token, user_hash = _xbl(access_token)   # легаси MSA-токен — без префикса "d="
    xsts_token = _xsts(xbl_token)
    mc_token   = _mc_token(xsts_token, user_hash)
    profile = _build_profile(mc_token, access_token)
    profile["refresh_token"] = refresh
    return profile


def refresh_auth(refresh_token: str) -> dict:
    """Обновляет сессию через refresh_token (легаси MSA endpoint). Возвращает profile dict."""
    import logging
    log = logging.getLogger("ms_auth")
    r = requests.post(_TOKEN_URL, data={
        "client_id":     _CLIENT_ID,
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token,
        "scope":         _SCOPE,
    }, timeout=20)
    log.debug("refresh_auth: status=%s", r.status_code)
    r.raise_for_status()
    data = r.json()
    access_token = data["access_token"]
    new_refresh  = data.get("refresh_token", refresh_token)
    xbl_token, user_hash = _xbl(access_token)
    xsts_token = _xsts(xbl_token)
    mc_token   = _mc_token(xsts_token, user_hash)
    profile = _build_profile(mc_token, access_token)
    profile["refresh_token"] = new_refresh
    return profile


def complete_auth(ms_access_token: str) -> dict:
    """Устаревший implicit-путь (без refresh_token). Оставлен для совместимости."""
    xbl_token, user_hash = _xbl(ms_access_token)
    xsts_token = _xsts(xbl_token)
    mc_token   = _mc_token(xsts_token, user_hash)
    return _build_profile(mc_token, ms_access_token)
