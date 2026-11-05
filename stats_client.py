import logging
import uuid
import requests
import config
import auth_client

log = logging.getLogger("stats_client")
_stats_session_id: str | None = None
_cached_client_id: str | None = None


def get_client_id() -> str:
    global _cached_client_id
    if _cached_client_id:
        return _cached_client_id
    settings = auth_client._load_settings()
    cid = settings.get("uuid") or settings.get("stats_client_id")
    if not cid:
        cid = str(uuid.uuid4())
        settings["stats_client_id"] = cid
        auth_client._save_settings(settings)
    _cached_client_id = cid
    return cid


def send_stats_ping(mode_id: str | None = None):
    global _stats_session_id
    try:
        cid = get_client_id()
        settings = auth_client._load_settings()
        user_tag = settings.get("username") or settings.get("discord_id")

        payload = {
            "client_id": cid,
            "user_tag": user_tag,
            "mode_id": mode_id,
            "session_id": _stats_session_id if mode_id else None
        }

        resp = requests.post(
            f"{config.SERVER_URL}/api/stats/ping",
            json=payload,
            timeout=4,
            verify=config.SSL_VERIFY
        )
        if resp.status_code == 200:
            data = resp.json()
            if mode_id:
                _stats_session_id = data.get("session_id")
            else:
                _stats_session_id = None
    except Exception as e:
        log.debug("stats ping failed: %s", e)


def stop_mode_session():
    global _stats_session_id
    if not _stats_session_id:
        return
    try:
        sid = _stats_session_id
        _stats_session_id = None
        requests.post(
            f"{config.SERVER_URL}/api/stats/session/stop",
            json={"session_id": sid},
            timeout=3,
            verify=config.SSL_VERIFY
        )
    except Exception as e:
        log.debug("stats stop session failed: %s", e)
