import math
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtSignal, QTimer, pyqtProperty
from PyQt6.QtGui import (
    QPixmap, QFont, QPainter, QColor, QLinearGradient,
    QRadialGradient, QPainterPath, QPen, QBrush
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QApplication, QPushButton
)
from assets_cache import AssetCache
from ui.titlebar import TitleBar


class LoginWindow(QWidget):
    login_success = pyqtSignal(str)

    def __init__(self, launcher_config: dict):
        super().__init__()
        self._cfg = launcher_config
        self._bg_pixmap: QPixmap | None = None
        from config import LAUNCHER_NAME
        self._name = LAUNCHER_NAME

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(self._name)
        self.resize(900, 580)
        self._build_ui()
        self._load_assets()
        self._center()

    def _center(self):
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2,
                  (screen.height() - self.height()) // 2)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._titlebar = TitleBar(self, self._name, show_maximize=False)
        root.addWidget(self._titlebar)

        center = QWidget()
        center.setStyleSheet("background: transparent;")
        cv = QVBoxLayout(center)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self._build_card())
        row.addStretch()
        cv.addLayout(row)
        cv.addStretch()
        root.addWidget(center, 1)

    def _build_card(self) -> QWidget:
        card = QWidget()
        card.setFixedWidth(380)
        card.setStyleSheet("background: transparent;")

        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        glass = QFrame()
        glass.setStyleSheet("""
            QFrame {
                background: rgba(13,17,23,215);
                border-radius: 20px;
                border: 1px solid rgba(255,255,255,18);
            }
        """)
        gl = QVBoxLayout(glass)
        gl.setContentsMargins(36, 32, 36, 32)
        gl.setSpacing(0)

        # Маскот
        maskot_lbl = QLabel()
        maskot_lbl.setFixedSize(140, 140)
        maskot_lbl.setScaledContents(True)
        maskot_lbl.setStyleSheet("background: transparent; border: none;")
        maskot_url = (self._cfg.get("_meta", {}) or {}).get("maskot_url", "")
        if maskot_url:
            from assets_cache import AssetCache
            AssetCache.load(maskot_url, lambda url, px: maskot_lbl.setPixmap(px))
        gl.addWidget(maskot_lbl, alignment=Qt.AlignmentFlag.AlignCenter)
        gl.addSpacing(16)

        # Заголовок
        title = QLabel("Войдите в аккаунт")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title.setStyleSheet("color: #E6EDF3; background: transparent; border: none;")
        gl.addWidget(title)
        gl.addSpacing(6)

        sub = QLabel("Используйте лицензионный аккаунт Minecraft")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #6e7681; font-size: 12px; background: transparent; border: none;")
        gl.addWidget(sub)
        gl.addSpacing(28)

        # Кнопка Microsoft
        ms_btn = QPushButton("  Войти через Microsoft")
        ms_btn.setFixedHeight(48)
        ms_btn.setFont(QFont("Segoe UI", 13, QFont.Weight.DemiBold))
        ms_btn.setStyleSheet("""
            QPushButton {
                background: #1a73e8;
                color: #fff;
                border: none;
                border-radius: 12px;
                font-size: 14px;
                font-weight: 600;
                padding-left: 8px;
            }
            QPushButton:hover { background: #1557b0; }
            QPushButton:pressed { background: #0f3d82; }
            QPushButton:disabled { background: #1a3a60; color: #6e7681; }
        """)
        ms_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ms_btn.clicked.connect(self._do_ms_login)
        self._ms_btn = ms_btn
        gl.addWidget(ms_btn)
        gl.addSpacing(12)

        # Статус / ошибка
        self._status_lbl = QLabel("")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet("color: #F85149; font-size: 12px; background: transparent; border: none;")
        self._status_lbl.setFixedHeight(32)
        gl.addWidget(self._status_lbl)

        lay.addWidget(glass)
        return card

    # ── Фон ──────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()

        if self._bg_pixmap:
            p.drawPixmap(self.rect(), self._bg_pixmap.scaled(
                self.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            p.fillRect(self.rect(), QColor(14, 17, 23))

        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0, QColor(14, 17, 23, 200))
        grad.setColorAt(0.5, QColor(14, 17, 23, 160))
        grad.setColorAt(1, QColor(14, 17, 23, 210))
        p.fillRect(self.rect(), grad)

        cx, cy = w // 2, h // 2 + 40
        glow = QRadialGradient(cx, cy, 280)
        glow.setColorAt(0, QColor(88, 101, 242, 20))
        glow.setColorAt(1, QColor(88, 101, 242, 0))
        p.fillRect(self.rect(), glow)

    def _load_assets(self):
        url = (self._cfg.get("_meta") or {}).get("background_url", "")
        if not url:
            from config import LOGIN_BACKGROUND_URL
            url = LOGIN_BACKGROUND_URL
        if url:
            AssetCache.load(url, self._on_bg_loaded)

    def _on_bg_loaded(self, url: str, px: QPixmap):
        self._bg_pixmap = px
        self.update()

    # ── Microsoft Login ───────────────────────────────────────────────────────

    def _do_ms_login(self):
        from ui.ms_auth_dialog import MsAuthDialog
        import auth_client
        self._ms_btn.setEnabled(False)
        self._status_lbl.setStyleSheet("color: #8888aa; font-size: 12px; background: transparent; border: none;")
        self._status_lbl.setText("Открываю окно авторизации...")

        def _on_ms_success(profile: dict):
            auth_client._save_settings({
                "token":         profile["mc_token"],
                "refresh_token": profile.get("refresh_token", ""),  # implicit-флоу его не даёт; device-code — даёт
                "username":      profile["username"],
                "uuid":          profile["uuid"],
                "auth_type":     "microsoft",
                "skin_variant":  profile.get("skin_variant", "classic"),
            })
            self._ms_btn.setEnabled(True)
            self._status_lbl.setText("")
            # Подтянуть Discord из сервера по UUID (привязка делается в игре)
            self._fetch_discord(profile["uuid"], profile["username"])

        def _on_close():
            self._ms_btn.setEnabled(True)
            self._status_lbl.setText("")

        dlg = MsAuthDialog(None)
        dlg.login_success.connect(_on_ms_success)
        dlg.rejected.connect(_on_close)
        dlg.exec()

    def _fetch_discord(self, uuid: str, username: str):
        """Запрашивает discord_id с сервера по Minecraft UUID."""
        import threading, requests, config, auth_client

        def _run():
            try:
                import sys
                _verify = str(config.SERVER_CERT) if config.SERVER_CERT.exists() else (True if getattr(sys, 'frozen', False) else __import__('certifi').where())
                resp = requests.get(
                    f"{config.SERVER_URL}/api/link/discord/{uuid}",
                    timeout=6, verify=_verify,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("linked"):
                        auth_client._save_settings({
                            "discord_id":       data["discord_id"],
                            "discord_username":  data.get("discord_name", ""),
                        })
            except Exception:
                pass  # Сервер недоступен — войдём без Discord
            self.login_success.emit(username)  # PyQt6 сам очередит в главный поток

        threading.Thread(target=_run, daemon=True).start()
