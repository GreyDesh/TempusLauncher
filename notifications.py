"""Центр уведомлений лаунчера.

Держит: режим «Не беспокоить» (DND), состояние индикатора (точка на трее и на
кнопке друзей) и звук уведомления. UI (трей, кнопка, окно чата) подписывается на
`indicator_changed` и дёргает `notify_*`.

Логика точки-индикатора: красная (есть непрочитанные сообщения) > жёлтая (есть
входящие заявки в друзья) > нет. При DND точка ВСЁ РАВНО показывается — глушатся
только звук / всплывающее уведомление / авто-открытие чата.
"""
from PyQt6.QtCore import QObject, pyqtSignal

import auth_client


class _NotificationCenter(QObject):
    # "" | "yellow" | "red"
    indicator_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._has_requests = False
        self._has_messages = False
        self._player = None
        self._audio = None
        self._buf = None

    # ── DND ────────────────────────────────────────────────────────────────────

    def is_dnd(self) -> bool:
        return bool(auth_client._load_settings().get("dnd", False))

    def set_dnd(self, value: bool):
        auth_client._save_settings({"dnd": bool(value)})

    def should_disturb(self) -> bool:
        """Можно ли беспокоить (звук/тост/открытие). False при DND."""
        return not self.is_dnd()

    # ── Индикатор ───────────────────────────────────────────────────────────────

    def current_indicator(self) -> str:
        if self._has_messages:
            return "red"
        if self._has_requests:
            return "yellow"
        return ""

    def set_requests(self, has: bool):
        has = bool(has)
        if has != self._has_requests:
            self._has_requests = has
            self.indicator_changed.emit(self.current_indicator())

    def set_messages(self, has: bool):
        has = bool(has)
        if has != self._has_messages:
            self._has_messages = has
            self.indicator_changed.emit(self.current_indicator())

    # ── Звук ────────────────────────────────────────────────────────────────────

    def play_ping(self):
        """Проигрывает msg_ping.ogg (из data.dat). Тихо игнорирует любые сбои аудио."""
        try:
            from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
            from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
            import asset_pack
            data = asset_pack.read("assets/msg_ping.ogg")
            if not data:
                return
            self._buf = QBuffer()
            self._buf.setData(QByteArray(data))
            self._buf.open(QIODevice.OpenModeFlag.ReadOnly)
            self._audio = QAudioOutput()
            self._player = QMediaPlayer()
            self._player.setAudioOutput(self._audio)
            self._player.setSourceDevice(self._buf)
            self._player.play()
        except Exception:
            pass


def compose_dot(base_px, color: str):
    """Рисует цветную точку в правом-нижнем углу иконки. color: '' | 'yellow' | 'red'."""
    if not color:
        return base_px
    from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen
    from PyQt6.QtCore import Qt
    px = base_px.copy()  # type: QPixmap
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor("#ef4444") if color == "red" else QColor("#f5b301")
    d = max(8, px.width() // 3)
    x, y = px.width() - d, px.height() - d
    p.setPen(QPen(QColor(0, 0, 0, 160), 2))
    p.setBrush(c)
    p.drawEllipse(x, y, d - 1, d - 1)
    p.end()
    return px


_center: _NotificationCenter | None = None


def center() -> _NotificationCenter:
    global _center
    if _center is None:
        _center = _NotificationCenter()
    return _center
