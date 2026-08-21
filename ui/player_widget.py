import threading
import requests
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QPainter, QColor, QPixmap, QPainterPath
from PyQt6.QtWidgets import QLabel
from config import CACHE_DIR


class _HeadLoader(QObject):
    loaded = pyqtSignal(QPixmap)

    def __init__(self, username: str, size: int, parent=None):
        super().__init__(parent)
        self._username = username
        self._size = size

    def start(self):
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        import base64, json as _json
        path = CACHE_DIR / f"head_{self._username}.png"
        try:
            uuid_r = requests.get(
                f"https://api.mojang.com/users/profiles/minecraft/{self._username}", timeout=8)
            uuid_r.raise_for_status()
            uuid = uuid_r.json()["id"]
            prof_r = requests.get(
                f"https://sessionserver.mojang.com/session/minecraft/profile/{uuid}", timeout=8)
            prof_r.raise_for_status()
            props = prof_r.json().get("properties", [])
            tex_prop = next((p for p in props if p["name"] == "textures"), None)
            if tex_prop:
                tex_data = _json.loads(base64.b64decode(tex_prop["value"]))
                skin_url = tex_data.get("textures", {}).get("SKIN", {}).get("url")
                if skin_url:
                    skin_r = requests.get(skin_url, timeout=10)
                    skin_r.raise_for_status()
                    from PyQt6.QtGui import QImage, QPainter as _P
                    import io
                    img = QImage()
                    img.loadFromData(skin_r.content)
                    img = img.convertToFormat(QImage.Format.Format_ARGB32)
                    # Первый слой: 8,8 (основа головы)
                    base = img.copy(8, 8, 8, 8).scaled(
                        64, 64, Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation)
                    # Второй слой: 40,8 (шлем/шапка, с прозрачностью)
                    overlay = img.copy(40, 8, 8, 8).scaled(
                        64, 64, Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation)
                    # Рисуем оба слоя
                    head_px = QPixmap.fromImage(base)
                    painter = _P(head_px)
                    painter.setCompositionMode(_P.CompositionMode.CompositionMode_SourceOver)
                    painter.drawImage(0, 0, overlay)
                    painter.end()
                    head_px.save(str(path), "PNG")
        except Exception:
            if not path.exists():
                return
        px = QPixmap(str(path))
        if not px.isNull():
            self.loaded.emit(px.scaled(
                self._size, self._size,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))


class PlayerHeadLabel(QLabel):
    # Иконка головы игрока в кнопке аккаунта.
    def __init__(self, username: str, size: int = 24, parent=None):
        super().__init__(parent)
        self._size = size
        self._px: QPixmap | None = None
        self.setFixedSize(size, size)
        self._loader: _HeadLoader | None = None
        if username:
            self._load(username)

    def set_username(self, username: str):
        # Кэш НЕ удаляем — показываем последнюю известную голову сразу, а _HeadLoader
        # всё равно перекачает актуальный скин из Mojang и перезапишет файл.
        self._load(username)

    def _load(self, username: str):
        # Мгновенно показываем голову из кеша (если есть), затем обновляем из Mojang.
        path = CACHE_DIR / f"head_{username}.png"
        if path.exists():
            px = QPixmap(str(path))
            if not px.isNull():
                self._on_loaded(px.scaled(
                    self._size, self._size,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
        self._loader = _HeadLoader(username, self._size, self)
        self._loader.loaded.connect(self._on_loaded)
        self._loader.start()

    def _on_loaded(self, px: QPixmap):
        self._px = px
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self._size
        if self._px:
            path = QPainterPath()
            path.addRoundedRect(0, 0, s, s, 4, 4)
            p.setClipPath(path)
            p.drawPixmap(0, 0, self._px)
        else:
            p.setBrush(QColor(60, 60, 80))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(0, 0, s, s, 4, 4)
            p.setPen(QColor(150, 150, 180))
            p.drawText(0, 0, s, s, Qt.AlignmentFlag.AlignCenter, "?")
