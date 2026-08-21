# Клиент чата — REST к серверу (session-токен).

# Все функции синхронные и блокирующие — вызывать из фоновых потоков, не из UI.
# Отправитель на сервере берётся из session-токена (нельзя писать от чужого имени).

#  Эндпоинты:
#  POST /api/messages            {to_uuid, body, kind, payload} -> сообщение
#  GET  /api/messages/{uuid}     ?before=<id>&limit=50          -> [msg, ...]  (старые сверху)
#  POST /api/messages/{uuid}/read                               -> {ok}
#  GET  /api/messages/unread                                    -> {uuid: count}

import requests


def _verify():
    import sys
    from config import SERVER_CERT
    if SERVER_CERT.exists():
        return str(SERVER_CERT)
    return True if getattr(sys, 'frozen', False) else __import__('certifi').where()


def send_message(to_uuid: str, body: str, kind: str = "text", payload: dict | None = None) -> dict | None:
    import config, auth_client
    try:
        r = requests.post(
            f"{config.SERVER_URL}/api/messages",
            json={"to_uuid": to_uuid, "body": body, "kind": kind, "payload": payload},
            headers=auth_client.session_headers(), timeout=8, verify=_verify(),
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def fetch_history(friend_uuid: str, before: int = 0, limit: int = 50) -> list[dict]:
    import config, auth_client
    try:
        params = {"limit": limit}
        if before:
            params["before"] = before
        r = requests.get(
            f"{config.SERVER_URL}/api/messages/{friend_uuid}",
            params=params, headers=auth_client.session_headers(), timeout=8, verify=_verify(),
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


def mark_read(friend_uuid: str) -> None:
    import config, auth_client
    try:
        requests.post(
            f"{config.SERVER_URL}/api/messages/{friend_uuid}/read",
            headers=auth_client.session_headers(), timeout=8, verify=_verify(),
        )
    except Exception:
        pass


def unread_counts() -> dict[str, int]:
    import config, auth_client
    try:
        r = requests.get(
            f"{config.SERVER_URL}/api/messages/unread",
            headers=auth_client.session_headers(), timeout=8, verify=_verify(),
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}
