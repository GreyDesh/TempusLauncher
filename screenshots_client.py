#Клиент публикации/ленты скриншотов (session-токен).

# Функции блокирующие — звать из фоновых потоков, не из UI.
# Автор на сервере берётся из session-токена.

#  Эндпоинты:
#  POST   /api/screenshots            multipart(file=jpeg, description) -> {id}
#  GET    /api/screenshots/feed       ?before=&limit=                   -> {posts:[...]}
#  DELETE /api/screenshots/{id}                                         -> {ok}

import requests


def _verify():
    from config import SSL_VERIFY
    return SSL_VERIFY


def publish(jpeg_bytes: bytes, description: str = "") -> dict | None:
    import config, auth_client
    try:
        r = requests.post(
            f"{config.SERVER_URL}/api/screenshots",
            files={"file": ("screenshot.jpg", jpeg_bytes, "image/jpeg")},
            data={"description": description or ""},
            headers=auth_client.session_headers(), timeout=30, verify=_verify(),
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def fetch_feed(before: int = 0, limit: int = 30) -> list[dict]:
    """Свои + друзей посты. image приходит относительным — подставляем SERVER_URL."""
    import config, auth_client
    try:
        params = {"limit": limit}
        if before:
            params["before"] = before
        r = requests.get(
            f"{config.SERVER_URL}/api/screenshots/feed",
            params=params, headers=auth_client.session_headers(), timeout=10, verify=_verify(),
        )
        if r.status_code != 200:
            return []
        posts = r.json().get("posts", []) or []
    except Exception:
        return []
    out = []
    for p in posts:
        img = (p.get("image") or "").strip()
        if img.startswith("/"):
            img = f"{config.SERVER_URL}{img}"
        out.append({**p, "image": img})
    return out


def delete_post(post_id: int) -> bool:
    import config, auth_client
    try:
        r = requests.delete(
            f"{config.SERVER_URL}/api/screenshots/{post_id}",
            headers=auth_client.session_headers(), timeout=10, verify=_verify(),
        )
        return r.status_code == 200
    except Exception:
        return False
