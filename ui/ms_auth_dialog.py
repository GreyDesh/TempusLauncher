# Диалог авторизации Microsoft — authorization code flow (даёт refresh_token).

from PyQt6.QtCore import Qt, pyqtSignal, QUrl, QTimer, QThread
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar
from PyQt6.QtWebEngineWidgets import QWebEngineView


class _CompleteWorker(QThread):
    success = pyqtSignal(dict)
    failed  = pyqtSignal(str)

    def __init__(self, code: str):
        super().__init__()
        self._code = code

    def run(self):
        import ms_auth
        try:
            profile = ms_auth.exchange_code(self._code)
            self.success.emit(profile)
        except Exception as e:
            self.failed.emit(str(e))


class MsAuthDialog(QDialog):
    login_success = pyqtSignal(dict)

    _REDIRECT_HOST = "login.live.com"
    _REDIRECT_PATH = "/oauth20_desktop.srf"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Вход через Microsoft")
        self.setWindowFlags(Qt.WindowType.Tool)
        self.resize(480, 620)
        self.setStyleSheet("QDialog { background: #0d0d18; }")
        self._done = False
        self._worker: _CompleteWorker | None = None
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        header = QLabel("  Войдите через Microsoft")
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
            QProgressBar::chunk { background: #1a73e8; }
        """)
        lay.addWidget(self._bar)

        from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
        profile = QWebEngineProfile("ms_auth", self)
        profile.setHttpUserAgent(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = QWebEnginePage(profile, self)
        self._view = QWebEngineView()
        self._view.setPage(page)
        self._view.urlChanged.connect(self._on_url_changed)
        self._view.loadFinished.connect(self._on_load_finished)
        lay.addWidget(self._view, 1)

        self._status = QLabel("Войдите в аккаунт Microsoft в браузере выше")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setFixedHeight(32)
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #4A5260; font-size: 11px; background: #0d0d18;")
        lay.addWidget(self._status)

        import ms_auth
        self._view.setUrl(QUrl(ms_auth.get_auth_url()))

    def _on_url_changed(self, url: QUrl):
        if self._done:
            return
        if url.host() == self._REDIRECT_HOST and url.path() == self._REDIRECT_PATH:
            # code приходит в query (?code=...) и живёт пару секунд, после чего страница
            # сама уходит на ?removed=true. Поэтому читаем код СИНХРОННО из самого URL,
            # без JS и без задержки — иначе успеет смениться на removed=true (гонка).
            from PyQt6.QtCore import QUrlQuery
            q = QUrlQuery(url)
            code = q.queryItemValue("code", QUrl.ComponentFormattingOption.FullyDecoded)
            if code:
                self._done = True
                self._view.setUrl(QUrl("about:blank"))
                self._on_token(code)
                return
            err = (q.queryItemValue("error_description") or q.queryItemValue("error"))
            if err:
                self._set_error(err.replace("+", " "))

    def _on_load_finished(self, ok: bool):
        if not self._done:
            self._bar.hide()
        url = self._view.url()
        if url.host() == self._REDIRECT_HOST and url.path() == self._REDIRECT_PATH:
            self._read_token_from_hash()

    def _read_token_from_hash(self):
        if self._done:
            return
        self._view.page().runJavaScript(
            "window.location.hash || window.location.search",
            self._parse_token
        )

    def _parse_token(self, fragment: str):
        if self._done or not fragment:
            return
        # Убираем ведущий # или ?
        raw = fragment.lstrip("#").lstrip("?")
        params = {}
        for part in raw.split("&"):
            if "=" in part:
                k, _, v = part.partition("=")
                params[k] = v

        import urllib.parse
        code = params.get("code")
        if code:
            self._done = True
            self._view.setUrl(QUrl("about:blank"))
            self._on_token(urllib.parse.unquote(code))
            return

        error = params.get("error_description", params.get("error", ""))
        if error:
            self._set_error(error.replace("+", " "))

    def _on_token(self, code: str):
        self._bar.setRange(0, 0)
        self._bar.show()
        self._status.setStyleSheet("color: #8888aa; font-size: 11px; background: #0d0d18;")
        self._status.setText("Получение профиля Minecraft...")
        self._view.setEnabled(False)

        self._worker = _CompleteWorker(code)
        self._worker.success.connect(self._on_success)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_success(self, profile: dict):
        self._bar.hide()
        self._status.setStyleSheet("color: #3FB950; font-size: 11px; background: #0d0d18;")
        self._status.setText(f"Добро пожаловать, {profile['username']}!")
        self.login_success.emit(profile)
        QTimer.singleShot(600, self.accept)

    def _on_failed(self, msg: str):
        self._bar.hide()
        self._done = False
        self._set_error(msg)
        self._view.setEnabled(True)

    def _set_error(self, msg: str):
        self._status.setStyleSheet("color: #F85149; font-size: 11px; background: #0d0d18;")
        self._status.setText(f"Ошибка: {msg}")
