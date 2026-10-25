#Выпадающее меню аккаунта (как в Discord): выезжает с анимацией под кнопкой.
#Кнопки: Скин, Статус (4 варианта), Выйти. Статус синхронизируется с друзьями.

from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QGraphicsOpacityEffect,
)

# status -> (цвет точки, подпись)
STATUS_META = {
    "online":    ("#3fb950", "В сети"),
    "idle":      ("#d29922", "Не активен"),
    "dnd":       ("#f85149", "Не беспокоить"),
    "invisible": ("#747f8d", "Не в сети"),
}
STATUS_ORDER = ["online", "idle", "dnd", "invisible"]


def status_color(status: str) -> str:
    return STATUS_META.get(status, STATUS_META["online"])[0]


def status_label(status: str) -> str:
    return STATUS_META.get(status, STATUS_META["online"])[1]


class _Dot(QLabel):
    def __init__(self, color: str, d: int = 10, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._d = d
        self.setFixedSize(d, d)

    def set_color(self, color: str):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(self._color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(0, 0, self._d, self._d)


class _Row(QPushButton):
    """Строка меню: иконка-точка / SVG (опц.) + текст."""
    def __init__(self, text: str, dot_color: str | None = None, icon: str | None = None,
                 danger: bool = False, icon_color: str | None = None, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(34)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(10)
        col = "#f85149" if danger else "#dbe2f0"
        if dot_color is not None:
            lay.addWidget(_Dot(dot_color))
        elif icon is not None:
            from ui.assets import svg_icon
            ic = QLabel()
            ic.setFixedSize(16, 16)
            ic.setPixmap(svg_icon(icon, icon_color or col, 16).pixmap(16, 16))
            ic.setStyleSheet("background: transparent; border: none;")
            lay.addWidget(ic)
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {col}; font-size: 13px; background: transparent; border: none;")
        lay.addWidget(lbl)
        lay.addStretch()
        self.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 7px; text-align: left; }"
            " QPushButton:hover { background: rgba(255,255,255,10); }")


class AccountMenu(QWidget):
    """Popup-меню под кнопкой аккаунта. Автозакрытие при клике вне (флаг Popup)."""
    def __init__(self, username: str, current_status: str,
                 on_skin, on_status, on_logout,
                 discord_linked: bool = False, on_link_discord=None, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._on_status = on_status
        self._status_dots = {}

        self._panel = QFrame(self)
        self._panel.setObjectName("accMenu")
        self._panel.setStyleSheet(
            "#accMenu { background: #171b26; border: 1px solid rgba(255,255,255,18);"
            " border-radius: 12px; }")
        lay = QVBoxLayout(self._panel)
        lay.setContentsMargins(8, 10, 8, 10)
        lay.setSpacing(2)

        # Шапка: ник + текущий статус
        head = QVBoxLayout()
        head.setContentsMargins(12, 0, 12, 4)
        head.setSpacing(1)
        name = QLabel(username)
        name.setStyleSheet("color: #fff; font-size: 14px; font-weight: 800; background: transparent; border: none;")
        head.addWidget(name)
        self._cur_lbl = QLabel(status_label(current_status))
        self._cur_lbl.setStyleSheet(
            f"color: {status_color(current_status)}; font-size: 11px; background: transparent; border: none;")
        head.addWidget(self._cur_lbl)
        lay.addLayout(head)
        lay.addWidget(self._sep())

        skin = _Row("Поменять скин", icon="clothes_hanger.svg")
        skin.clicked.connect(lambda: self._act(on_skin))
        lay.addWidget(skin)

        # Привязать Discord — только если ещё НЕ привязан
        if not discord_linked:
            dc = _Row("Привязать Discord", icon="discord.svg", icon_color="#5865F2")
            dc.clicked.connect(lambda: self._act(on_link_discord))
            lay.addWidget(dc)

        lay.addWidget(self._sep())
        st_cap = QLabel("Статус")
        st_cap.setStyleSheet("color: #6b7284; font-size: 10px; font-weight: 700; letter-spacing: 1px;"
                             " padding: 4px 12px 2px; background: transparent; border: none;")
        lay.addWidget(st_cap)
        for st in STATUS_ORDER:
            color, label = STATUS_META[st]
            row = _Row(label, dot_color=color)
            row.clicked.connect(lambda _=False, s=st: self._choose_status(s))
            lay.addWidget(row)

        lay.addWidget(self._sep())
        out = _Row("Выйти из аккаунта", icon="door_open.svg", danger=True)
        out.clicked.connect(lambda: self._act(on_logout))
        lay.addWidget(out)

        self._panel.setFixedWidth(236)   # чтобы подписи статусов/«Выйти» не обрезались
        self._panel.adjustSize()
        self.resize(self._panel.size())

    @staticmethod
    def _sep() -> QFrame:
        f = QFrame()
        f.setFixedHeight(1)
        f.setStyleSheet("background: rgba(255,255,255,10); border: none;")
        return f

    def _act(self, fn):
        self.close()
        if fn:
            QTimer.singleShot(0, fn)

    def _choose_status(self, status: str):
        self._cur_lbl.setText(status_label(status))
        self._cur_lbl.setStyleSheet(
            f"color: {status_color(status)}; font-size: 11px; background: transparent; border: none;")
        if self._on_status:
            self._on_status(status)
        QTimer.singleShot(120, self.close)

    def show_under(self, anchor: QWidget):
        """Показывает меню под якорной кнопкой с анимацией выезда+появления."""
        gp = anchor.mapToGlobal(anchor.rect().bottomRight())
        w, h = self.width(), self.height()
        x = gp.x() - w
        y = gp.y() + 6
        self._panel.move(0, 0)
        self.setGeometry(x, y, w, h)
        # fade
        eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(eff)
        self._fade = QPropertyAnimation(eff, b"opacity", self)
        self._fade.setDuration(160); self._fade.setStartValue(0.0); self._fade.setEndValue(1.0)
        # slide (панель выезжает сверху вниз)
        self._slide = QPropertyAnimation(self._panel, b"geometry", self)
        self._slide.setDuration(190)
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide.setStartValue(QRect(0, -12, w, h))
        self._slide.setEndValue(QRect(0, 0, w, h))
        self.show()
        self._fade.start()
        self._slide.start()
