# Диалог привязки Discord: открывает OAuth во внешнем браузере (где юзер
# уже залогинен в Discord) и опрашивает сервер — не привязался ли аккаунт.

import urllib.parse
import requests

from PyQt6.QtCore import Qt, QUrl, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QDesktopServices
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QProgressBar,
)

import config as _config


class DiscordAuthDialog(QDialog):
    login_success = pyqtSignal(str, str, str)  # username, discord_id, login_token

    def __init__(self, server_url: str, parent=None, profile=None):
        super().__init__(parent)
        self._server_url = server_url.rstrip("/")
        self.setWindowTitle("Привязка Discord")
        self.setWindowFlags(Qt.WindowType.Tool)
        self.resize(420, 240)
        self.setStyleSheet("QDialog { background: #0d0d18; }")

        import auth_client
        self._settings = auth_client._load_settings()
        self._uuid = self._settings.get("uuid", "")

        self._build_ui()
        self._open_browser()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(2000)

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(14)

        title = QLabel("Привязка Discord")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #e8e8f0;")
        lay.addWidget(title)

        info = QLabel(
            "Открыт браузер со страницей Discord. Войдите и подтвердите "
            "привязку — лаунчер сам закроет это окно."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #a0a0b0; font-size: 12px;")
        lay.addWidget(info)

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        self._bar.setFixedHeight(3)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet(
            "QProgressBar { background: #1a1a2e; border: none; }"
            "QProgressBar::chunk { background: #5865F2; }"
        )
        lay.addWidget(self._bar)

        self._status = QLabel("Ожидание подтверждения...")
        self._status.setStyleSheet("color: #4A5260; font-size: 11px;")
        lay.addWidget(self._status)

        again = QPushButton("Открыть страницу заново")
        again.setCursor(Qt.CursorShape.PointingHandCursor)
        again.setStyleSheet(
            "QPushButton { background: #1a1a2e; color: #e8e8f0; border: none;"
            " padding: 8px; border-radius: 4px; }"
            "QPushButton:hover { background: #26263d; }"
        )
        again.clicked.connect(self._open_browser)
        lay.addWidget(again)

    def _open_browser(self):
        params = urllib.parse.urlencode({
            "uuid":     self._uuid,
            "username": self._settings.get("username", ""),
        })
        QDesktopServices.openUrl(QUrl(f"{self._server_url}/auth/discord/launcher?{params}"))

    def _poll(self):
        if not self._uuid:
            return
        try:
            r = requests.get(
                f"{_config.SERVER_URL}/api/link/discord/{self._uuid}",
                timeout=5, verify=_config.SSL_VERIFY,
            )
            data = r.json()
        except Exception:
            return
        if not data.get("linked"):
            return
        self._timer.stop()
        self._bar.setRange(0, 1)
        self._bar.setValue(1)
        self._status.setText(f"✓ Discord привязан: {data.get('discord_name', '')}")
        QTimer.singleShot(500, lambda: (
            self.login_success.emit(
                data.get("discord_name", ""), str(data.get("discord_id", "")), ""
            ),
            self.accept(),
        ))
