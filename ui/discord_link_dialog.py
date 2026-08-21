"""Необязательный диалог предложения привязать Discord после входа через Microsoft."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout


class DiscordLinkDialog(QDialog):
    link_accepted = pyqtSignal()
    link_skipped = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Привязать Discord")
        self.setWindowFlags(Qt.WindowType.Tool)
        # Высота — минимум (растёт под контент при масштабе Windows >100%).
        self.setFixedWidth(380)
        self.setMinimumHeight(240)
        self.setStyleSheet("QDialog { background: #0d0d18; }")
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 28, 28, 24)
        lay.setSpacing(12)

        icon = QLabel("🔗")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 36px; background: transparent;")
        lay.addWidget(icon)

        title = QLabel("Привязать аккаунт Discord?")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #e8e8f0; background: transparent;")
        lay.addWidget(title)

        desc = QLabel(
            "Это позволит автоматически входить на сайт сервера\n"
            "и использовать функции Discord-бота. Можно сделать\n"
            "это позже в настройках профиля."
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("color: #6e7681; font-size: 12px; background: transparent;")
        lay.addWidget(desc)

        lay.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        skip_btn = QPushButton("Пропустить")
        skip_btn.setFixedHeight(40)
        skip_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,8);
                color: #8888aa; border: 1px solid rgba(255,255,255,12);
                border-radius: 10px; font-size: 13px;
            }
            QPushButton:hover { background: rgba(255,255,255,14); color: #e8e8f0; }
        """)
        skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        skip_btn.clicked.connect(self._on_skip)

        link_btn = QPushButton("  Привязать Discord")
        link_btn.setFixedHeight(40)
        link_btn.setStyleSheet("""
            QPushButton {
                background: #5865F2; color: #fff;
                border: none; border-radius: 10px;
                font-size: 13px; font-weight: 600;
            }
            QPushButton:hover { background: #4752c4; }
        """)
        link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        link_btn.clicked.connect(self._on_link)

        btn_row.addWidget(skip_btn)
        btn_row.addWidget(link_btn)
        lay.addLayout(btn_row)

    def _on_skip(self):
        self.link_skipped.emit()
        self.accept()

    def _on_link(self):
        self.link_accepted.emit()
        self.accept()
