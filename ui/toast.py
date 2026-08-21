"""Кастомный тост-уведомление в правом нижнем углу экрана.

Это обычный виджет, а не системное уведомление Windows — поэтому НЕ проигрывается
системный звук (свой звук играем отдельно). Плавное появление/исчезновение,
клик открывает чат, несколько тостов стопкой вверх, авто-закрытие через 5с.
"""
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QApplication,
)

_MARGIN = 16
_GAP = 10
_active: list["Toast"] = []


def _reposition():
    screen = QApplication.primaryScreen().availableGeometry()
    x = screen.right() - _MARGIN
    y = screen.bottom() - _MARGIN
    for t in reversed(_active):
        y -= t.height()
        t.move(x - t.width(), y)
        y -= _GAP


class Toast(QWidget):
    W = 320
    H = 72

    def __init__(self, title: str, body: str, icon_path: str = "", on_click=None):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._on_click = on_click
        self._closing = False
        self._anim = None
        self._build(title, body, icon_path)

        _active.append(self)
        _reposition()
        self.setWindowOpacity(0.0)
        self.show()
        self._fade(0.0, 1.0)                     # плавное появление
        QTimer.singleShot(5000, self._start_close)

    def _build(self, title: str, body: str, icon_path: str):
        wrap = QWidget(self)
        wrap.setGeometry(0, 0, self.W, self.H)
        wrap.setObjectName("toastCard")
        wrap.setStyleSheet(
            "#toastCard { background: #12142a;"
            " border: 1px solid rgba(255,255,255,25); border-radius: 12px; }")
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)

        av = QLabel()
        av.setFixedSize(40, 40)
        av.setStyleSheet("background: #1a1a2e; border-radius: 8px; border: none;")
        if icon_path:
            px = QPixmap(icon_path)
            if not px.isNull():
                av.setPixmap(px.scaled(40, 40, Qt.AspectRatioMode.IgnoreAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation))
        lay.addWidget(av)

        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet("color: #e6edf3; font-size: 13px; font-weight: 700;"
                        " background: transparent; border: none;")
        b = QLabel(body)
        b.setStyleSheet("color: #aab; font-size: 12px; background: transparent; border: none;")
        col.addWidget(t)
        col.addWidget(b)
        lay.addLayout(col, 1)

    def _fade(self, start: float, end: float, on_done=None):
        self._anim = QPropertyAnimation(self, b"windowOpacity")
        self._anim.setDuration(250)
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        if on_done:
            self._anim.finished.connect(on_done)
        self._anim.start()

    def _start_close(self):
        if self._closing:
            return
        self._closing = True
        self._fade(self.windowOpacity(), 0.0, on_done=self.close)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._on_click:
            try:
                self._on_click()
            except Exception:
                pass
        self._start_close()

    def closeEvent(self, e):
        if self in _active:
            _active.remove(self)
        _reposition()
        super().closeEvent(e)


def show_toast(title: str, body: str, icon_path: str = "", on_click=None):
    Toast(title, body, icon_path, on_click)
