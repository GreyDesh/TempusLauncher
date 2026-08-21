# Диалог входа через Device Code Flow — без WebEngine.

import threading
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt6.QtGui import QFont, QColor, QPainter, QLinearGradient
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QApplication
)


class _PollWorker(QThread):
    success  = pyqtSignal(dict)
    failed   = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, device_code: str, interval: int):
        super().__init__()
        self._device_code = device_code
        self._interval    = interval
        self._stop        = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        import ms_auth
        try:
            profile = ms_auth.device_code_poll(
                self._device_code, self._interval, self._stop,
                on_progress=lambda msg: self.progress.emit(msg)
            )
            self.success.emit(profile)
        except Exception as e:
            if not self._stop.is_set():
                self.failed.emit(str(e))


class DeviceCodeDialog(QDialog):
    login_success = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Вход через Microsoft")
        self.setWindowFlags(Qt.WindowType.Tool)
        # Высота — минимум (растёт под контент при масштабе Windows >100%).
        self.setFixedWidth(420)
        self.setMinimumHeight(300)
        self.setStyleSheet("QDialog { background: #0d0d18; }")
        self._worker: _PollWorker | None = None
        self._timer: QTimer | None = None
        self._seconds_left = 0
        self._build_ui()
        self._start()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 24)
        lay.setSpacing(12)

        title = QLabel("Вход через Microsoft")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #e8e8f0; background: transparent;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        hint = QLabel("Перейдите по адресу в браузере и введите код:")
        hint.setStyleSheet("color: #7D8590; font-size: 12px; background: transparent;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._url_lbl = QLabel("microsoft.com/devicelogin")
        self._url_lbl.setStyleSheet("color: #5B8CFF; font-size: 13px; font-weight: 600; background: transparent;")
        self._url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._url_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        def _open_url(_): __import__("webbrowser").open("https://microsoft.com/devicelogin")
        self._url_lbl.mousePressEvent = _open_url

        self._code_lbl = QLabel("...")
        self._code_lbl.setFont(QFont("Courier New", 28, QFont.Weight.Bold))
        self._code_lbl.setStyleSheet("color: #E6EDF3; letter-spacing: 6px; background: transparent;")
        self._code_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        copy_btn = QPushButton("Скопировать код")
        copy_btn.setFixedHeight(32)
        copy_btn.setStyleSheet("""
            QPushButton { background: rgba(91,140,255,30); color: #5B8CFF;
                border: 1px solid rgba(91,140,255,60); border-radius: 8px; font-size: 12px; }
            QPushButton:hover { background: rgba(91,140,255,60); }
        """)
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(self._code_lbl.text()))

        self._status = QLabel("Ожидание входа...")
        self._status.setStyleSheet("color: #7D8590; font-size: 11px; background: transparent;")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._bar = QProgressBar()
        self._bar.setRange(0, 900)
        self._bar.setFixedHeight(4)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet("""
            QProgressBar { background: rgba(255,255,255,10); border-radius: 2px; border: none; }
            QProgressBar::chunk { background: #5B8CFF; border-radius: 2px; }
        """)

        lay.addWidget(title)
        lay.addWidget(hint)
        lay.addSpacing(4)
        lay.addWidget(self._url_lbl)
        lay.addWidget(self._code_lbl)
        lay.addWidget(copy_btn)
        lay.addStretch()
        lay.addWidget(self._status)
        lay.addWidget(self._bar)

    def _start(self):
        self._status.setText("Получение кода...")
        try:
            import ms_auth
            data = ms_auth.device_code_start()
        except Exception as e:
            self._status.setStyleSheet("color: #F85149; font-size: 11px; background: transparent;")
            self._status.setText(f"Ошибка: {e}")
            return

        user_code = data.get("user_code", "")
        device_code = data.get("device_code", "")
        interval = data.get("interval", 5)
        self._seconds_left = data.get("expires_in", 900)
        verify_url = data.get("verification_uri") or data.get("verification_url") or "https://microsoft.com/devicelogin"

        self._verify_url = verify_url
        self._url_lbl.setText(verify_url.replace("https://", ""))
        def _open_url(_): __import__("webbrowser").open(verify_url)
        self._url_lbl.mousePressEvent = _open_url

        self._code_lbl.setText(user_code)
        self._bar.setMaximum(self._seconds_left)
        self._bar.setValue(self._seconds_left)
        self._status.setText("Ожидание входа...")

        # Таймер обратного отсчёта
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self._worker = _PollWorker(device_code, interval)
        self._worker.success.connect(self._on_success)
        self._worker.failed.connect(self._on_failed)
        self._worker.progress.connect(self._status.setText)
        self._worker.start()

    def _tick(self):
        self._seconds_left -= 1
        self._bar.setValue(self._seconds_left)
        if self._seconds_left <= 0:
            self._on_failed("Время истекло. Попробуйте снова.")

    def _on_success(self, profile: dict):
        if self._timer:
            self._timer.stop()
        self._status.setStyleSheet("color: #3FB950; font-size: 11px; background: transparent;")
        self._status.setText(f"Добро пожаловать, {profile['username']}!")
        self.login_success.emit(profile)
        QTimer.singleShot(800, self.accept)

    def _on_failed(self, msg: str):
        if self._timer:
            self._timer.stop()
        self._status.setStyleSheet("color: #F85149; font-size: 11px; background: transparent;")
        self._status.setText(f"Ошибка: {msg}")

    def closeEvent(self, e):
        if self._worker:
            self._worker.stop()
        if self._timer:
            self._timer.stop()
        super().closeEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor(18, 18, 35, 250))
        g.setColorAt(1, QColor(10, 10, 22, 250))
        p.setBrush(g)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(self.rect(), 12, 12)
