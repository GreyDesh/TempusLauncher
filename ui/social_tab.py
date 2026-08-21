import webbrowser
import math
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPainter, QColor, QPainterPath, QBrush, QPen
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
)


class TelegramIcon(QWidget):
    def __init__(self, size=48, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._size = size

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self._size
        # Синий круг
        p.setBrush(QBrush(QColor("#2AABEE")))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(0, 0, s, s)
        # Белый бумажный самолётик
        p.setBrush(QBrush(QColor("#ffffff")))
        path = QPainterPath()
        cx, cy = s * 0.5, s * 0.5
        # Упрощённый самолётик
        path.moveTo(s * 0.18, s * 0.5)
        path.lineTo(s * 0.82, s * 0.3)
        path.lineTo(s * 0.55, s * 0.72)
        path.lineTo(s * 0.45, s * 0.58)
        path.closeSubpath()
        p.drawPath(path)
        # Хвост
        path2 = QPainterPath()
        path2.moveTo(s * 0.45, s * 0.58)
        path2.lineTo(s * 0.55, s * 0.72)
        path2.lineTo(s * 0.42, s * 0.76)
        path2.closeSubpath()
        p.drawPath(path2)


class DiscordIcon(QWidget):
    def __init__(self, size=48, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._size = size

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self._size
        # Фиолетовый круг
        p.setBrush(QBrush(QColor("#5865F2")))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(0, 0, s, s)
        # Белый контроллер-логотип Discord (упрощённый)
        p.setBrush(QBrush(QColor("#ffffff")))
        # Тело
        path = QPainterPath()
        path.moveTo(s * 0.28, s * 0.38)
        path.quadTo(s * 0.5, s * 0.28, s * 0.72, s * 0.38)
        path.lineTo(s * 0.76, s * 0.62)
        path.quadTo(s * 0.62, s * 0.76, s * 0.5, s * 0.72)
        path.quadTo(s * 0.38, s * 0.76, s * 0.24, s * 0.62)
        path.closeSubpath()
        p.drawPath(path)
        # Глаза (тёмные круги)
        p.setBrush(QBrush(QColor("#5865F2")))
        eye_r = s * 0.085
        p.drawEllipse(int(s*0.36 - eye_r), int(s*0.48 - eye_r), int(eye_r*2), int(eye_r*2))
        p.drawEllipse(int(s*0.64 - eye_r), int(s*0.48 - eye_r), int(eye_r*2), int(eye_r*2))


class SocialCard(QFrame):
    def __init__(self, name: str, url: str, color: str, icon_widget: QWidget, parent=None):
        super().__init__(parent)
        self.setFixedSize(180, 200)
        self.setStyleSheet(f"""
            QFrame {{
                background: rgba(255,255,255,7);
                border-radius: 16px;
                border: 1px solid {color}44;
            }}
            QFrame:hover {{ background: rgba(255,255,255,13); border: 1px solid {color}88; }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_widget.setParent(self)

        name_lbl = QLabel(name)
        name_lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {color}; background: transparent; border: none;")
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        btn = QPushButton("Открыть")
        btn.setFixedHeight(34)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {color}33;
                color: {color};
                border: 1px solid {color}66;
                border-radius: 8px;
                font-weight: 600; font-size: 12px;
            }}
            QPushButton:hover {{ background: {color}66; color: #fff; }}
        """)
        btn.clicked.connect(lambda: webbrowser.open(url))

        lay.addWidget(icon_widget, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(name_lbl)
        lay.addWidget(btn)


class SocialTab(QWidget):
    def __init__(self, social: dict, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(0)

        title = QLabel("Социальные сети")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff; margin-bottom: 16px;")
        root.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(16)

        tg = social.get("telegram", "")
        dc = social.get("discord", "")

        if tg:
            row.addWidget(SocialCard("Telegram", tg, "#2AABEE", TelegramIcon(52)))
        if dc:
            row.addWidget(SocialCard("Discord", dc, "#5865F2", DiscordIcon(52)))

        if not tg and not dc:
            lbl = QLabel("Социальные сети не настроены")
            lbl.setStyleSheet("color: #5a5a8a; font-size: 14px;")
            row.addWidget(lbl)

        row.addStretch()
        root.addLayout(row)
        root.addStretch()
