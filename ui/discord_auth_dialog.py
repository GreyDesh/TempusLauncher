"""Диалог привязки Discord через лаунчерный OAuth-поток."""
from PyQt6.QtCore import Qt, pyqtSignal, QUrl, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar
from PyQt6.QtWebEngineWidgets import QWebEngineView


class DiscordAuthDialog(QDialog):
    login_success = pyqtSignal(str, str, str)  # username, discord_id, login_token

    def __init__(self, server_url: str, parent=None, profile=None):
        super().__init__(parent)
        self._server_url = server_url.rstrip("/")
        self._profile = profile
        self.setWindowTitle("Привязка Discord")
        self.setWindowFlags(Qt.WindowType.Tool)
        self.resize(520, 680)
        self.setStyleSheet("QDialog { background: #0d0d18; }")
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        header = QLabel("  Привязка Discord аккаунта")
        header.setFixedHeight(42)
        header.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        header.setStyleSheet("color: #e8e8f0; background: #1a1a2e; padding-left: 8px;")
        lay.addWidget(header)

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        self._bar.setFixedHeight(3)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet("""
            QProgressBar { background: #1a1a2e; border: none; }
            QProgressBar::chunk { background: #5865F2; }
        """)
        lay.addWidget(self._bar)

        self._view = QWebEngineView()
        if self._profile:
            from PyQt6.QtWebEngineCore import QWebEnginePage
            self._view.setPage(QWebEnginePage(self._profile, self._view))
        self._view.loadFinished.connect(lambda _: self._bar.hide())
        self._view.urlChanged.connect(self._on_url_changed)
        lay.addWidget(self._view, 1)

        self._status = QLabel("Войдите в Discord в браузере выше...")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setFixedHeight(32)
        self._status.setStyleSheet("color: #4A5260; font-size: 11px; background: #0d0d18;")
        lay.addWidget(self._status)

        import auth_client, urllib.parse
        s = auth_client._load_settings()
        params = urllib.parse.urlencode({
            "uuid":     s.get("uuid", ""),
            "username": s.get("username", ""),
        })
        self._view.setUrl(QUrl(f"{self._server_url}/auth/discord/launcher?{params}"))

    def _on_url_changed(self, url: QUrl):
        s = url.toString()
        if "/auth/launcher-done" not in s:
            return

        discord_id  = self._param(url, "discord_id")
        username    = self._param(url, "username")
        login_token = self._param(url, "login_token")
        print(f"[discord_dlg] done: discord_id={discord_id!r} token={login_token!r}")

        if not discord_id:
            return

        self._view.urlChanged.disconnect(self._on_url_changed)
        self._bar.setRange(0, 1)
        self._bar.setValue(1)
        self._bar.show()
        self._status.setText(f"✓ Discord привязан: {username}")

        QTimer.singleShot(600, lambda: (
            self.login_success.emit(username, discord_id, login_token),
            self.accept()
        ))

    @staticmethod
    def _param(url: QUrl, name: str) -> str:
        from PyQt6.QtCore import QUrlQuery
        return QUrlQuery(url).queryItemValue(name)
