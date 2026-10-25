from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QPen, QPainterPath
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QStackedWidget, QFrame, QApplication
)


class WinControlBtn(QWidget):
    # Кнопка управления окном — кастомный виджет, не подпадает под глобальный QSS QPushButton.
    clicked = pyqtSignal()

    def __init__(self, text: str, fg: QColor, hover_bg: QColor, parent=None):
        super().__init__(parent)
        self._text = text
        self._fg = fg
        self._hover_bg = hover_bg
        self._hover = False
        self.setFixedSize(32, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, e): self._hover = True; self.update()
    def leaveEvent(self, e): self._hover = False; self.update()
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        bg = self._hover_bg if self._hover else QColor(28, 33, 40)
        p.setBrush(bg)
        p.setPen(QPen(QColor(48, 54, 61), 1))
        p.drawRoundedRect(1, 1, w - 2, h - 2, 6, 6)
        p.setPen(QColor(255, 255, 255) if self._hover else self._fg)
        p.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        p.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter, self._text)
from config import WINDOW_WIDTH, WINDOW_HEIGHT, ANIM_SLOW, JSON_POLL_INTERVAL_MS, BASE_DIR
from ui.styles import DARK_GLASS_QSS
from ui.sidebar import Sidebar
from ui.content_panel import ContentPanel
from ui.social_tab import SocialTab
from ui.settings_dialog import SettingsDialog
from ui.log_dialog import LogDialog
from ui.account_dialog import AccountDialog
from ui.titlebar import TitleBar
from assets_cache import AssetCache
import api


class BgLayer(QWidget):
    # Слой заднего фона: размытие + прозрачность через QPainter.setOpacity.
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._px: QPixmap | None = None
        self._alpha: float = 0.0  # 0.0 — скрыт, 1.0 — полностью виден

    def set_opacity(self, v: float):
        self._alpha = v
        self.update()

    def get_opacity(self) -> float:
        return self._alpha

    def set_pixmap_smooth(self, px: QPixmap):
        self._px = px
        self.update()

    def paintEvent(self, e):
        if not self._px or self._alpha <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setOpacity(self._alpha)
        # Размытие через масштаб вниз/вверх (нет QGraphicsBlurEffect чтобы избежать конфликтов)
        w, h = self.width(), self.height()
        small = self._px.scaled(w // 4, h // 4,
                                Qt.AspectRatioMode.IgnoreAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
        blurred = small.scaled(w, h,
                               Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        p.drawPixmap(0, 0, blurred)


class MainWindow(QMainWindow):
    _game_running_signal = pyqtSignal(bool, str)   # (running, mode_id)
    _roles_loaded_signal = pyqtSignal()
    _config_updated_signal = pyqtSignal(dict)
    _status_signal = pyqtSignal(str, str)  # text, color
    _media_refresh_signal = pyqtSignal()   # картинки обновились -> перерисовать
    _chat_msg_signal = pyqtSignal()        # SSE: пришло сообщение
    _chat_read_signal = pyqtSignal()       # SSE: наши сообщения прочитаны
    _chat_unread_signal = pyqtSignal(dict, bool)  # (counts, notify)
    _toast_signal = pyqtSignal(str, str, str, str)  # (title, body, head_path, sender_uuid)
    _sse_connected_signal = pyqtSignal()   # SSE (пере)подключился -> ресинк
    _news_reload_signal = pyqtSignal()     # SSE 'news_updated' -> перезагрузить ленту
    _feed_reload_signal = pyqtSignal()     # SSE 'feed_updated' -> перезагрузить посты-скриншоты
    _friends_update_signal = pyqtSignal()  # SSE 'friends_updated' -> маршалинг в UI-поток

    def __init__(self, config: dict, news: list, username: str):
        super().__init__()
        self._config = config
        self._news = news
        self._username = username
        self._chat_unread: dict = {}
        self._current_mode: dict | None = None
        self._modes_map = {m["id"]: m.get("name", m["id"]) for m in config.get("modes", []) if "id" in m}

        from config import LAUNCHER_NAME
        name = LAUNCHER_NAME
        self.setWindowTitle(name)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setStyleSheet(DARK_GLASS_QSS)
        self._center()
        self._build_ui(name)
        self._config_updated_signal.connect(self._apply_config_update)
        self._media_refresh_signal.connect(self._refresh_media_images)
        self._chat_msg_signal.connect(self._handle_chat_message)
        self._chat_read_signal.connect(self._handle_chat_read)
        self._chat_unread_signal.connect(self._apply_chat_unread)
        self._toast_signal.connect(self._show_toast)
        self._sse_connected_signal.connect(self._on_sse_connected)
        self._start_watcher()
        QTimer.singleShot(1500, self.refresh_chat_unread)   # непрочитанное на старте
        QTimer.singleShot(2500, self._preload_chats)        # прогрев кэша переписок
        # Создаём диалог аккаунта заранее чтобы OpenGL-контекст
        # инициализировался до первого показа (без мигания)
        self._account_dlg = AccountDialog(username, self, getattr(self, "_web_profile", None))
        self._account_dlg.logout_requested.connect(self._on_logout)
        self._account_dlg.discord_linked.connect(self._on_discord_linked)

    def _visible_modes(self) -> list:
        return [m for m in self._config.get("modes", []) if m.get("visible", True)]

    def _center(self):
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - WINDOW_WIDTH) // 2, (screen.height() - WINDOW_HEIGHT) // 2)

    # Build UI

    def _build_ui(self, name: str):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Задний фон (два слоя для crossfade) — всегда под UI
        self._bg_a = BgLayer(central)
        self._bg_b = BgLayer(central)
        self._bg_a.lower()
        self._bg_b.lower()

        self._bg_a.set_opacity(0.35)
        self._bg_b.set_opacity(0.0)
        self._active_bg = "a"

        # Верхняя панель
        top_bar = QWidget()
        top_bar.setObjectName("topBar")
        top_bar.setFixedHeight(56)
        top_bar.setStyleSheet("""
            QWidget#topBar {
                background: rgba(13,17,23,230);
                border-bottom: 1px solid rgba(255,255,255,8);
            }
        """)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(16, 0, 10, 0)
        top_layout.setSpacing(0)

        # Слева: логотип + название
        logo_widget = QWidget()
        logo_widget.setStyleSheet("background: transparent;")
        logo_lay = QHBoxLayout(logo_widget)
        logo_lay.setContentsMargins(0, 0, 20, 0)
        logo_lay.setSpacing(10)

        self._logo_lbl = QLabel()
        self._logo_lbl.setFixedSize(32, 32)
        self._logo_lbl.setStyleSheet("background: transparent; border: none;")
        self._logo_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        from ui.assets import launcher_logo
        self._logo_lbl.setPixmap(launcher_logo().scaled(
            32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self._easter_egg_used = False
        self._logo_lbl.mousePressEvent = lambda e: self._on_logo_click()

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("color: #E6EDF3; font-size: 14px; font-weight: 700; background: transparent; border: none;")

        logo_lay.addWidget(self._logo_lbl)
        logo_lay.addWidget(name_lbl)
        top_layout.addWidget(logo_widget)

        # Разделитель
        div = QFrame()
        div.setFrameShape(QFrame.Shape.VLine)
        div.setStyleSheet("background: rgba(255,255,255,10); border: none; max-width: 1px; margin: 10px 16px 10px 44px;")
        top_layout.addWidget(div)

        # Центр: табы + соцсети
        tabs_widget = QWidget()
        tabs_widget.setStyleSheet("background: transparent;")
        tabs_layout = QHBoxLayout(tabs_widget)
        tabs_layout.setContentsMargins(0, 0, 0, 0)
        tabs_layout.setSpacing(2)

        from ui.assets import svg_icon as _svg
        from PyQt6.QtCore import QSize as _QSize
        self._tab_btns: dict[str, QPushButton] = {}
        for key, label, icon in [("main", "Главная", "home.svg")]:  # ("web", "Сайт", "globe.svg") — временно скрыто
            btn = QPushButton(f"  {label}")
            btn.setProperty("class", "tab")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            try:
                btn.setIcon(_svg(icon, "#E6EDF3", 16))
                btn.setIconSize(_QSize(16, 16))
            except Exception:
                pass
            btn.clicked.connect(lambda checked, k=key: self._switch_tab(k))
            tabs_layout.addWidget(btn)
            self._tab_btns[key] = btn

        # Hover-меню на кнопке "Сайт" (кнопка временно скрыта — код сохранён)
        if "web" in self._tab_btns:
            _web_btn = self._tab_btns["web"]
            _web_btn.setProperty("_has_site_menu", True)

            from PyQt6.QtWidgets import QMenu
            from PyQt6.QtGui import QAction
            _site_menu = QMenu(self)
            _site_menu.setStyleSheet("""
                QMenu {
                    background: rgba(13,17,23,240);
                    border: 1px solid rgba(255,255,255,12);
                    border-radius: 8px;
                    padding: 4px;
                    color: #c8c8e0;
                    font-size: 12px;
                }
                QMenu::item {
                    padding: 7px 20px 7px 12px;
                    border-radius: 6px;
                }
                QMenu::item:selected { background: rgba(255,255,255,10); }
                QMenu::separator { height: 1px; background: rgba(255,255,255,8); margin: 3px 8px; }
            """)
            for _lbl, _url, _ico in [
                ("Карта",    "https://hyligans.ru/map",       "map_marker.svg"),
                ("Вики",     "https://hyligans.ru/wiki",      "info.svg"),
                ("Гильдии",  "https://hyligans.ru/guilds",    "users_alt.svg"),
                ("Курьерка", "https://hyligans.ru/delivery",  "truck.svg"),
                ("Банк",     "https://hyligans.ru/dashboard", "bank.svg"),
            ]:
                act = QAction(_lbl, _site_menu)
                try:
                    act.setIcon(_svg(_ico, "#8888aa", 16))
                except Exception:
                    pass
                act.triggered.connect(lambda checked, u=_url: self._open_in_browser(u))
                _site_menu.addAction(act)

            def _show_site_menu():
                pos = _web_btn.mapToGlobal(_web_btn.rect().bottomLeft())
                _site_menu.popup(pos)

            _web_btn.clicked.disconnect()
            _web_btn.clicked.connect(_show_site_menu)

        # Соцсети
        import webbrowser
        from PyQt6.QtGui import QIcon
        social = self._config.get("social", {})
        tg_url = social.get("telegram", "")
        dc_url = social.get("discord", "")
        from ui.assets import svg_icon as _svg_ic
        from PyQt6.QtCore import QSize as _SZ

        def _social_btn(label, url, color, hover_c, svg_name):
            btn = QPushButton(f"  {label}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            try:
                btn.setIcon(_svg_ic(svg_name, color, 16))
                btn.setIconSize(_SZ(16, 16))
            except Exception:
                pass
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {color};
                    border: none; padding: 6px 12px;
                    font-size: 12px; font-weight: 500;
                    border-radius: 6px;
                }}
                QPushButton:hover {{ color: {hover_c}; background: rgba(255,255,255,8); }}
            """)
            btn.clicked.connect(lambda: webbrowser.open(url))
            return btn

        if tg_url:
            tabs_layout.addSpacing(8)
            tabs_layout.addWidget(_social_btn("Telegram", tg_url, "#2AABEE", "#60ccff", "telegram.svg"))
        if dc_url:
            tabs_layout.addWidget(_social_btn("Discord", dc_url, "#5865F2", "#7983f5", "discord.svg"))

        top_layout.addWidget(tabs_widget)
        top_layout.addStretch()

        # Справа: аккаунт + управление окном
        from ui.player_widget import PlayerHeadLabel

        acc_widget = QWidget()
        acc_widget.setStyleSheet("""
            QWidget {
                background: rgba(255,255,255,8);
                border: 1px solid rgba(255,255,255,12);
                border-radius: 8px;
            }
            QWidget:hover { background: rgba(63,185,80,15); border: 1px solid rgba(63,185,80,40); }
        """)
        acc_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        acc_layout = QHBoxLayout(acc_widget)
        acc_layout.setContentsMargins(6, 4, 8, 4)
        acc_layout.setSpacing(6)

        self._head_label = PlayerHeadLabel(self._username, 28)
        acc_layout.addWidget(self._head_label)

        acc_text = QWidget()
        acc_text.setStyleSheet("background: transparent; border: none;")
        acc_text_lay = QVBoxLayout(acc_text)
        acc_text_lay.setContentsMargins(0, 0, 0, 0)
        acc_text_lay.setSpacing(1)
        self._acc_name_lbl = QLabel(self._username)
        self._acc_name_lbl.setStyleSheet("color: #E6EDF3; font-size: 12px; font-weight: 700; background: transparent; border: none;")
        # Строка статуса: цветная точка + подпись (ручной статус, как в Discord)
        from ui.account_menu import status_color, status_label
        import auth_client as _ac
        self._status = _ac._load_settings().get("status", "online")
        # DND согласован со статусом при старте
        try:
            import notifications
            notifications.center().set_dnd(self._status == "dnd")
        except Exception:
            pass
        status_row = QWidget(); status_row.setStyleSheet("background: transparent; border: none;")
        sr_lay = QHBoxLayout(status_row); sr_lay.setContentsMargins(0, 0, 0, 0); sr_lay.setSpacing(5)
        from ui.account_menu import _Dot
        self._status_dot = _Dot(status_color(self._status), 8)
        sr_lay.addWidget(self._status_dot)
        self._acc_status_lbl = QLabel(status_label(self._status))
        self._acc_status_lbl.setStyleSheet(
            f"color: {status_color(self._status)}; font-size: 10px; background: transparent; border: none;")
        sr_lay.addWidget(self._acc_status_lbl)
        acc_text_lay.addWidget(self._acc_name_lbl)
        acc_text_lay.addWidget(status_row)
        acc_layout.addWidget(acc_text)

        chevron = QLabel("▾")
        chevron.setStyleSheet("color: #4A5260; font-size: 12px; background: transparent; border: none;")
        acc_layout.addWidget(chevron)
        acc_widget.mousePressEvent = lambda e: self._toggle_account_menu()
        self._account_btn = acc_widget
        self._acc_menu = None

        top_layout.addWidget(acc_widget)
        top_layout.addSpacing(6)

        # Кнопка друзей
        from ui.assets import svg_icon as _svg_friends
        self._friends_btn = QPushButton()
        self._friends_btn.setFixedSize(36, 36)
        self._friends_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._friends_btn.setCheckable(True)
        try:
            self._friends_btn.setIcon(_svg_friends("users_alt.svg", "#8888aa", 18))
            from PyQt6.QtCore import QSize as _QSZ
            self._friends_btn.setIconSize(_QSZ(18, 18))
        except Exception:
            self._friends_btn.setText("👥")
        self._friends_btn.setStyleSheet("""
            QPushButton {
                background: transparent; border: none; border-radius: 8px;
            }
            QPushButton:hover { background: rgba(255,255,255,10); }
            QPushButton:checked { background: rgba(100,140,255,30);
                border: 1px solid rgba(100,140,255,60); }
        """)
        self._friends_btn.toggled.connect(self._toggle_friends_drawer)
        # Точка-индикатор уведомлений (жёлтая=заявка, красная=сообщение)
        self._friends_dot = QLabel(self._friends_btn)
        self._friends_dot.setFixedSize(9, 9)
        self._friends_dot.move(25, 3)
        self._friends_dot.hide()
        import notifications
        notifications.center().indicator_changed.connect(self._on_indicator_changed)
        QTimer.singleShot(0, lambda: self._on_indicator_changed(
            notifications.center().current_indicator()))
        top_layout.addWidget(self._friends_btn)
        top_layout.addSpacing(4)

        # Кнопки управления окном (кастомный виджет — не подпадает под QSS QPushButton)
        self._min_btn = WinControlBtn("─", QColor(139, 148, 158), QColor(48, 54, 61))
        self._min_btn.clicked.connect(self.showMinimized)

        self._close_btn = WinControlBtn("✕", QColor(248, 81, 73), QColor(218, 54, 51))
        self._close_btn.clicked.connect(self.close)

        top_layout.addWidget(self._min_btn)
        top_layout.addWidget(self._close_btn)

        # Drag через топ-бар
        top_bar.mousePressEvent = self._tb_press
        top_bar.mouseMoveEvent = self._tb_move
        top_bar.mouseReleaseEvent = lambda e: setattr(self, "_drag_pos", None)
        self._drag_pos = None

        # Контент
        self._stack = QStackedWidget()

        # Главная — sidebar + content в скруглённой карточке
        main_tab = QWidget()
        main_tab.setStyleSheet("background: transparent;")
        main_outer = QVBoxLayout(main_tab)
        main_outer.setContentsMargins(0, 0, 0, 0)
        main_outer.setSpacing(0)

        game_card = QWidget()
        game_card.setObjectName("gameCard")
        game_card.setStyleSheet("QWidget#gameCard { background: rgba(10,13,18,220); }")
        game_card_h = QHBoxLayout(game_card)
        game_card_h.setContentsMargins(0, 0, 0, 0)
        game_card_h.setSpacing(0)

        modes = self._visible_modes()
        self._sidebar = Sidebar(modes)
        self._sidebar.mode_selected.connect(self._on_mode_selected)
        self._sidebar.all_modes_clicked.connect(self._on_all_modes)
        self._sidebar.downloads_clicked.connect(self._toggle_download_bar)
        self._sidebar.update_clicked.connect(self._restart_for_update)
        self._content = ContentPanel()
        self._content.set_launcher_config(self._config)
        self._content.play_requested.connect(self._on_play)
        self._content.settings_requested.connect(self._open_settings)
        self._current_mode: dict = {}
        self._running_mode_id: str = ""   # id режима с запущенной игрой
        self._launching_mode_id: str = ""  # id режима в фазе "Запуск игры..." (окно ещё не поднялось)
        self._running_proc = None         # Popen запущенной игры (для проверки живости)
        self._game_running_signal.connect(self._on_game_running)
        self._roles_loaded_signal.connect(self._on_roles_loaded)
        self._status_signal.connect(self._update_acc_status)
        # Heartbeat: раз в 20с шлём на сервер актуальный статус (играю/онлайн) и правим метку.
        # Сервер снимает онлайн, если пульса не было >60с (см. friends.sweep_offline).
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(20_000)
        self._heartbeat_timer.timeout.connect(self._heartbeat)
        self._heartbeat_timer.start()
        self._content.log_requested.connect(self._show_log_error)
        self._content.mode_thumb_selected.connect(self._on_mode_selected)
        self._content.discord_link_requested.connect(self._open_discord_link)

        _sep = QFrame()
        _sep.setFrameShape(QFrame.Shape.VLine)
        _sep.setFixedWidth(1)
        _sep.setStyleSheet("background: rgba(255,255,255,12); border: none;")

        game_card_h.addWidget(self._sidebar)
        game_card_h.addWidget(_sep)
        game_card_h.addWidget(self._content, 1)
        main_outer.addWidget(game_card)

        # Встроенный браузер
        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView
            from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
            from PyQt6.QtCore import QUrl
            from config import SITE_URL
            # Именованный профиль — cookies сохраняются на диск между запусками
            self._web_profile = QWebEngineProfile("launcher", self)
            self._web_view = QWebEngineView()
            self._web_view.setPage(QWebEnginePage(self._web_profile, self._web_view))

            # Автологин если Discord привязан
            import auth_client as _ac
            _s = _ac._load_settings()
            _uuid = _s.get("uuid", "")
            _dc   = _s.get("discord_id", "")
            if _uuid and _dc:
                import urllib.parse as _up
                _params = _up.urlencode({"uuid": _uuid, "discord_id": _dc})
                self._web_view.setUrl(QUrl(f"{SITE_URL}/auth/auto-login?{_params}"))
            else:
                self._web_view.setUrl(QUrl(SITE_URL + "/"))

            web_widget = self._web_view
        except ImportError:
            web_widget = QLabel("PyQt6-WebEngine не установлен.\npip install PyQt6-WebEngine")
            web_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            web_widget.setStyleSheet("color: #7D8590; font-size: 14px;")
            self._web_view = None

        self._stack.addWidget(main_tab)   # index 0
        self._stack.addWidget(web_widget) # index 1

        root.addWidget(top_bar)
        root.addWidget(self._stack, 1)

        # Плашка загрузок
        from ui.download_bar import DownloadBar
        self._download_bar = DownloadBar(self)
        self._download_bar.hide()
        self._download_bar.raise_()

        # Drawer друзей (поверх всего, справа)
        from ui.friends_panel import FriendsDrawer
        self._friends_drawer = FriendsDrawer(self)
        self._friends_drawer.hide()
        self._friends_drawer.set_modes(self._config.get("modes", []))
        self._friends_drawer.join_game.connect(self._on_join_game)

        # Диалоги
        self._settings_dialog = SettingsDialog(self)
        self._settings_dialog.verify_requested.connect(self._content.start_verify)
        self._log_dialog = LogDialog(self)

        # Начальная вкладка — Главная, показать все режимы
        self._switch_tab("main")
        self._sidebar.select_all()
        QTimer.singleShot(0, lambda: self._content.show_all_modes(modes))

    # Window controls

    def _tb_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _tb_move(self, event):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    # Tab switching

    def _open_in_browser(self, url: str):
        web_view = getattr(self, "_web_view", None)
        if web_view is not None:
            from PyQt6.QtCore import QUrl
            web_view.setUrl(QUrl(url))
            self._switch_tab("web")
        else:
            import webbrowser
            webbrowser.open(url)

    def _switch_tab(self, key: str):
        idx = {"main": 0, "web": 1}.get(key, 0)
        self._stack.setCurrentIndex(idx)
        for k, btn in self._tab_btns.items():
            active = k == key
            btn.setProperty("active", "true" if active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # Mode selection

    def _on_all_modes(self):
        modes = self._visible_modes()
        self._content.show_all_modes(modes)
        self._switch_tab("main")
        bg_url = (self._config.get("_meta") or {}).get("background_url", "")
        if bg_url:
            self._update_background({"background_blur_url": bg_url})

    def _on_roles_loaded(self):
        if self._current_mode:
            self._content.show_mode(self._current_mode)

    def _on_mode_selected(self, mode: dict):
        mid = mode.get("id")
        # Тот же режим уже показан в контенте — не переоткрываем (без повторной анимации
        # затемнения и без мигающего пере-рендера при закликивании). Всё равно возвращаемся
        # на вкладку и подсвечиваем карточку — на случай, если ушли на другую вкладку.
        already_shown = self._content.current_mode_id() == mid
        self._current_mode = mode
        if not already_shown:
            self._content.show_mode(mode)
            self._update_background(mode)
        if self._running_mode_id and self._running_mode_id == mid:
            self._content.set_game_running(True, mid)
        elif self._launching_mode_id and self._launching_mode_id == mid:
            self._content.set_game_launching(mid)
        self._switch_tab("main")
        self._sidebar.highlight_mode(mode)

    def _update_background(self, mode: dict):
        url = mode.get("background_blur_url") or mode.get("background_url", "")
        if not url:
            return
        AssetCache.load(url, self._on_bg_loaded)

    def _on_bg_loaded(self, url: str, px: QPixmap):
        scaled = px.scaled(self.size(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        if self._active_bg == "a":
            self._bg_b.set_pixmap_smooth(scaled)
            self._crossfade(self._bg_b, self._bg_a)
            self._active_bg = "b"
        else:
            self._bg_a.set_pixmap_smooth(scaled)
            self._crossfade(self._bg_a, self._bg_b)
            self._active_bg = "a"

    def _crossfade(self, show_layer: BgLayer, hide_layer: BgLayer):
        show_layer.setGeometry(0, 0, self.width(), self.height())
        show_layer.lower()
        # Анимируем _alpha напрямую на BgLayer через QTimer (без QPropertyAnimation и QObject-target)
        if hasattr(self, "_bg_timer") and self._bg_timer.isActive():
            self._bg_timer.stop()
        steps = 20
        duration_ms = ANIM_SLOW
        interval = duration_ms // steps
        step_ref = [0]
        start_show = show_layer.get_opacity()
        start_hide = hide_layer.get_opacity()
        target_show = 0.35
        target_hide = 0.0

        def _tick():
            t = step_ref[0] / steps
            ease = t * t * (3 - 2 * t)  # smoothstep
            show_layer.set_opacity(start_show + (target_show - start_show) * ease)
            hide_layer.set_opacity(start_hide + (target_hide - start_hide) * ease)
            step_ref[0] += 1
            if step_ref[0] > steps:
                self._bg_timer.stop()
                show_layer.set_opacity(target_show)
                hide_layer.set_opacity(target_hide)

        self._bg_timer = QTimer(self)
        self._bg_timer.setInterval(interval)
        self._bg_timer.timeout.connect(_tick)
        self._bg_timer.start()

    # Actions

    def changeEvent(self, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.ActivationChange:
            if self.isActiveWindow():
                self._content.refresh_playtime()
                self._content.resume_video()
            else:
                self._content.pause_video()
        super().changeEvent(event)

    def _on_join_game(self, mode_id: str, server_ip: str):
        # Запуск игры из панели друзей с опциональным подключением к серверу.
        from downloader import is_installed
        from PyQt6.QtWidgets import QMessageBox
        modes = self._config.get("modes", [])
        mode = next((m for m in modes if m.get("id") == mode_id), None)
        # Режима нет в конфиге = он скрыт для этого игрока (hidden) и не отдан сервером
        if not mode:
            QMessageBox.warning(self, "Нет доступа",
                                "У вас нет доступа к этому режиму — он скрыт.")
            return
        # Режим виден, но заблокирован по Discord-роли для игры
        role_id = mode.get("required_discord_role", "")
        if role_id:
            import auth_client
            if not auth_client.has_discord_role(role_id):
                role_name = mode.get("required_discord_role_name", "")
                QMessageBox.warning(
                    self, "Нужна роль",
                    "Для этого режима нужна роль"
                    + (f" «{role_name}»" if role_name else "") + " в Discord.")
                return
        if not is_installed(mode):
            self._on_mode_selected(mode)
            self._content.start_install()
            return
        if server_ip:
            host, _, port = server_ip.rpartition(":")
            mode = dict(mode, _join_server=host or server_ip, _join_port=port or "25565")
        self._on_play(mode)

    def _on_game_running(self, running: bool, mode_id: str):
        # Игра поднялась/закрылась — фаза "Запуск..." для этого режима завершена.
        if self._launching_mode_id == mode_id:
            self._launching_mode_id = ""
        self._content.set_game_running(running, mode_id)

    def _on_play(self, mode: dict):
        import launcher as mc_launcher
        if getattr(self, "_running_mode_id", "") == mode.get("id", ""):
            if mode.get("_join_server"):
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self, "Игра уже запущена",
                    "Вы не можете присоединиться — игра уже запущена."
                )
            return
        # Сразу показываем "Запуск игры..." и меняем статус (только у кнопки ЭТОГО режима)
        self._launching_mode_id = mode.get("id", "")
        self._content.set_game_launching(self._launching_mode_id)
        # Статус "Играет" НЕ ставим оптимистично — только когда игра реально запустилась
        # (см. _watch_game). Пока показываем нейтральный "Запуск…".
        self._status_signal.emit("Запуск…", "#FFB454")
        # launch_mode блокирует UI-поток (рефреш токена — сетевые запросы на секунды),
        # поэтому принудительно прогоняем очередь, чтобы "Запуск игры..." успело отрисоваться.
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QEventLoop
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        try:
            proc = mc_launcher.launch_mode(mode, self._username)
        except Exception as e:
            self._launching_mode_id = ""
            self._content.set_game_running(False, mode.get("id", ""))
            self._status_signal.emit("В сети", "#5B8CFF")
            self._show_log_error(str(e))
            return
        self._running_proc = proc

        def _kill_game():
            from PyQt6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self, "Завершить игру",
                "Вы точно хотите завершить Minecraft?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                proc.terminate()

        self._content.connect_kill(lambda: _kill_game())

        log_dialog = LogDialog(self)
        log_dialog.set_title(f"Minecraft — {mode.get('name', '')}")

        import threading, time, playtime as pt
        _start_time = time.time()
        _window_found = [False]
        _log_lines: list[str] = []

        def _drain_stdout():
            # Только сливает stdout в список — никаких Qt-вызовов из потока.
            for line in proc.stdout:
                _log_lines.append(line.rstrip())

        threading.Thread(target=_drain_stdout, daemon=True).start()

        def _notify_online(is_online: bool):
            # При запуске игры передаём mode_id, при выходе сбрасываем на "просто онлайн"
            mode_id = mode.get("id") if is_online else None
            self._set_online(is_online=True, mode_id=mode_id) if is_online else self._set_online(True, None)

        def _watch_game():
            time.sleep(10)
            if proc.poll() is not None:
                # Игра не поднялась (краш/мгновенное закрытие) — возвращаем статус и уведомляем сервер
                self._running_mode_id = ""
                self._running_proc = None
                self._game_running_signal.emit(False, mode.get("id", ""))
                QTimer.singleShot(0, _poll_timer.stop)
                threading.Thread(target=_notify_online, args=(False,), daemon=True).start()
                return
            _window_found[0] = True
            self._running_mode_id = mode.get("id", "")
            self._game_running_signal.emit(True, mode.get("id", ""))
            threading.Thread(target=_notify_online, args=(True,), daemon=True).start()
            # Сообщаем серверу что игра началась
            pt.start_session(mode.get("id", ""))
            QTimer.singleShot(0, self._content.refresh_playtime)
            proc.wait()
            self._running_mode_id = ""
            self._running_proc = None
            self._game_running_signal.emit(False, mode.get("id", ""))
            QTimer.singleShot(0, _poll_timer.stop)
            threading.Thread(target=_notify_online, args=(False,), daemon=True).start()
            # Сообщаем серверу что игра закончилась — он считает время сам
            pt.stop_session()

        threading.Thread(target=_watch_game, daemon=True).start()

        # Таймер только для чтения лога и периодической синхронизации плейтайма
        _poll_timer = QTimer(self)
        _poll_timer.setInterval(1000)
        _last_ui_refresh = [0.0]
        _UI_REFRESH_INTERVAL = 60  # секунд

        def _check_proc():
            # Перекидываем накопленные строки лога в диалог (в главном потоке)
            while _log_lines:
                log_dialog.append_log(_log_lines.pop(0))

            now = time.time()

            # Обновление табло НАИГРАНО — каждую минуту, только если окно активно
            if (_window_found[0]
                    and self.isActiveWindow()
                    and now - _last_ui_refresh[0] >= _UI_REFRESH_INTERVAL):
                _last_ui_refresh[0] = now
                mode_id = mode.get("id", "")
                elapsed = now - _start_time
                entry = pt.get(mode_id)
                import copy
                tmp = copy.copy(entry)
                tmp["seconds"] = entry.get("seconds", 0) + elapsed
                pt._cache[mode_id] = tmp
                self._content.refresh_playtime()
                pt._cache[mode_id] = entry  # восстанавливаем — реальное время придёт после stop

            # (статус-heartbeat вынесен в общий _heartbeat_timer, 20с)

        _poll_timer.timeout.connect(_check_proc)
        _poll_timer.start()

        from config import SETTINGS_FILE
        import json
        try:
            settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8")) if SETTINGS_FILE.exists() else {}
        except Exception:
            settings = {}
        if settings.get("show_logs"):
            log_dialog.show()

    def _toggle_download_bar(self):
        if self._download_bar.isVisible():
            self._download_bar.hide()
        else:
            btn_pos = self._sidebar.downloads_btn_pos_in(self)
            self._download_bar.set_anchor(btn_pos)
            self._download_bar.show()
            self._download_bar.raise_()

    def _open_settings(self, mode: dict = {}):
        self._settings_dialog.set_mode(mode, self._config)
        if self._settings_dialog.exec() and self._settings_dialog.delete_requested:
            # Обновить кнопку играть после удаления
            self._content.refresh_current_view()

    def _open_discord_link(self):
        from ui.discord_auth_dialog import DiscordAuthDialog
        import config
        dlg = DiscordAuthDialog(config.SITE_URL, self, getattr(self, "_web_profile", None))
        def _on_linked(dc_username, discord_id, login_token):
            import auth_client
            auth_client._save_settings({"discord_id": discord_id, "discord_username": dc_username})
            # роли + перерисовка режима теперь внутри _on_discord_linked (общая точка)
            self._on_discord_linked(login_token)
        dlg.login_success.connect(_on_linked)
        dlg.exec()

    def _refresh_current_mode(self):
        if self._current_mode:
            self._content.show_mode(self._current_mode)

    def _open_account(self):
        self._account_dlg.show()
        self._account_dlg.raise_()

    def _on_discord_linked(self, login_token: str):
        # После привязки Discord — обновляем роли, гейт режима и логиним web view.
        self._friends_drawer.refresh_discord_state()
        # Единая точка обновления состояния привязки для ОБОИХ путей (аккаунт-вкладка и карточка режима):
        # тянем роли с сервера и перерисовываем текущий режим, чтобы гейт "привяжите Discord" исчез.
        import auth_client, threading

        def _load_and_refresh():
            auth_client.fetch_discord_roles()
            # Сигнал потокобезопасно маршалит перерисовку текущего режима в UI-поток.
            # (Раньше был QMetaObject.invokeMethod по имени незарегистрированного слота —
            # молча не срабатывал, из-за чего экран «Привяжите Discord» оставался.)
            self._roles_loaded_signal.emit()
        threading.Thread(target=_load_and_refresh, daemon=True).start()
        print(f"[discord_linked] token={login_token!r} web_view={self._web_view is not None}")
        if not self._web_view:
            return
        from PyQt6.QtCore import QUrl
        from config import SITE_URL

        def _navigate():
            if login_token:
                # Токен → сервер ставит session cookie
                url = f"{SITE_URL}/auth/launcher-login?token={login_token}"
            else:
                # Fallback: session cookie уже в профиле — просто идём на главную
                url = f"{SITE_URL}/"
            print(f"[discord_linked] navigating to {url}")
            self._web_view.setUrl(QUrl(url))

        QTimer.singleShot(300, _navigate)

    def _on_logo_click(self):
        if self._easter_egg_used:
            return
        self._easter_egg_used = True

        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel
        from PyQt6.QtGui import QPixmap
        from PyQt6.QtCore import QTimer
        import asset_pack

        dlg = QDialog(self)
        dlg.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        dlg.setModal(False)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)

        img_lbl = QLabel()
        owl_data = asset_pack.read("assets/owl.png")
        if owl_data:
            px = QPixmap()
            px.loadFromData(owl_data)
            img_lbl.setPixmap(px)
        img_lbl.setStyleSheet("border-radius: 12px;")
        lay.addWidget(img_lbl)
        dlg.adjustSize()

        # По центру главного окна
        geo = self.geometry()
        dlg.move(
            geo.x() + (geo.width() - dlg.width()) // 2,
            geo.y() + (geo.height() - dlg.height()) // 2,
        )
        dlg.show()

        try:
            from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
            from PyQt6.QtCore import QUrl
            import tempfile, os

            sound_data = asset_pack.read("assets/scream.mp3")
            if sound_data:
                tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                tmp.write(sound_data)
                tmp.flush()
                tmp.close()
                self._egg_player = QMediaPlayer(self)
                self._egg_audio = QAudioOutput(self)
                self._egg_player.setAudioOutput(self._egg_audio)
                self._egg_audio.setVolume(1.0)
                self._egg_player.setSource(QUrl.fromLocalFile(tmp.name))
                self._egg_player.play()
                def _cleanup(p=self._egg_player, f=tmp.name):
                    p.stop()
                    QTimer.singleShot(300, lambda: os.unlink(f) if os.path.exists(f) else None)
                QTimer.singleShot(7000, _cleanup)
        except Exception:
            pass
        QTimer.singleShot(7000, dlg.close)

    def _on_logout(self):
        import auth_client
        auth_client.logout()
        self.close()
        from ui.login_window import LoginWindow
        self._login_win = LoginWindow(self._config)
        self._login_win.login_success.connect(self._on_relogin)
        self._login_win.show()

    def _on_relogin(self, username: str):
        self._username = username
        self._acc_name_lbl.setText(username)
        self._head_label.set_username(username)
        self._login_win.close()
        self.show()

    def _show_log_error(self, text: str):
        self._log_dialog.set_title("Ошибка")
        self._log_dialog.append_log(text)
        self._log_dialog.show_error("Произошла ошибка. Отправьте этот лог администрации.")
        self._log_dialog.show()

    # ── Local API (мод ↔ лаунчер) ────────────────────────────────────────────

    # ── JSON hot-reload ───────────────────────────────────────────────────────

    def _start_watcher(self):
        self._watcher = api.ConfigWatcher(
            on_launcher_update=self._on_config_updated,
            on_news_update=self._on_news_updated,
            on_friends_update=lambda: self._friends_update_signal.emit(),
            on_media_update=self._on_media_update,
            on_roles_update=self._on_roles_update,
            on_message=lambda: self._chat_msg_signal.emit(),
            on_message_read=lambda: self._chat_read_signal.emit(),
            on_connect=lambda: self._sse_connected_signal.emit(),
            on_mode_news_update=lambda: self._news_reload_signal.emit(),
            on_feed_update=lambda: self._feed_reload_signal.emit(),
        )
        self._news_reload_signal.connect(self._content.reload_news)
        self._feed_reload_signal.connect(self._content.reload_feed)
        self._friends_update_signal.connect(self._friends_drawer.notify_friends_updated)
        self._watcher.start()

        # Слой 2: периодический рефреш ролей Discord (страховка, если живой SSE-пуш
        # не дошёл). Раз в 3 мин перечитывает роли; при изменении перерисовывает режим.
        self._roles_timer = QTimer(self)
        self._roles_timer.timeout.connect(self._poll_roles)
        self._roles_timer.setInterval(180_000)  # 3 минуты
        self._roles_timer.start()

        # Периодический опрос манифеста на обновление app (баннер «доступно обновление»)
        self._update_shown_ver = ""
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._check_app_update)
        self._update_timer.setInterval(120_000)  # каждые 2 минуты
        self._update_timer.start()
        QTimer.singleShot(5000, self._check_app_update)  # первый чек вскоре после старта

    def _heartbeat(self):
        """Пульс раз в 20с. Проверяет, жив ли процесс игры; шлёт статус и правит метку по факту."""
        proc = self._running_proc
        alive = proc is not None and proc.poll() is None
        if not alive and self._running_mode_id:
            # Игра закрылась/умерла, но состояние не сбросилось — чиним
            _closed_id = self._running_mode_id
            self._running_mode_id = ""
            self._running_proc = None
            self._game_running_signal.emit(False, _closed_id)
        mode_id = self._running_mode_id or None
        # _set_online пошлёт пульс на сервер и обновит метку ("Играет"/"В сети")
        import threading
        threading.Thread(target=self._set_online, args=(True, mode_id), daemon=True).start()

    def _set_online(self, is_online: bool = True, mode_id: str | None = None):
        """Обновляет mode_id на сервере. Онлайн-статус управляется SSE-соединением."""
        import requests as _req, auth_client, config as _cfg
        try:
            verify = _cfg.SSL_VERIFY
            headers = auth_client.session_headers()
            if not headers:
                return
            params = {"status": getattr(self, "_status", "online")}
            if mode_id:
                params["mode"] = mode_id
            _req.post(f"{_cfg.SERVER_URL}/api/player/online",
                      params=params, headers=headers, timeout=4, verify=verify)
        except Exception:
            pass
        if mode_id:
            self._status_signal.emit("Играет", "#4caf50")
        else:
            self._status_signal.emit("В сети", "#5B8CFF")

    def _update_acc_status(self, text: str, color: str):
        # text/color — игровое состояние. Когда «В сети» (не в игре) — показываем
        # РУЧНОЙ статус (в сети/не активен/не беспокоить/не в сети). Точка = ручной.
        if text == "В сети":
            from ui.account_menu import status_color, status_label
            text, color = status_label(self._status), status_color(self._status)
        self._acc_status_lbl.setText(text)
        self._acc_status_lbl.setStyleSheet(
            f"color: {color}; font-size: 10px; background: transparent; border: none;")

    def _toggle_account_menu(self):
        from ui.account_menu import AccountMenu
        if self._acc_menu is not None and self._acc_menu.isVisible():
            self._acc_menu.close(); return
        import auth_client
        linked = bool(auth_client._load_settings().get("discord_id"))
        self._acc_menu = AccountMenu(
            self._username, self._status,
            on_skin=self._open_account,
            on_status=self._set_my_status,
            on_logout=self._on_logout,
            discord_linked=linked,
            on_link_discord=self._open_discord_link,
            parent=self,
        )
        self._acc_menu.show_under(self._account_btn)

    def _set_my_status(self, status: str):
        from ui.account_menu import status_color, status_label
        self._status = status
        import auth_client
        auth_client._save_settings({"status": status})
        # «Не беспокоить» = включить DND (глушит звук/попапы уведомлений)
        try:
            import notifications
            notifications.center().set_dnd(status == "dnd")
        except Exception:
            pass
        self._status_dot.set_color(status_color(status))
        # если не в игре — сразу обновить подпись
        if not self._running_mode_id:
            self._acc_status_lbl.setText(status_label(status))
            self._acc_status_lbl.setStyleSheet(
                f"color: {status_color(status)}; font-size: 10px; background: transparent; border: none;")
        # немедленный heartbeat со статусом (друзья увидят)
        import threading
        threading.Thread(target=self._set_online, args=(True, self._running_mode_id or None),
                         daemon=True).start()

    def _on_config_updated(self, new_config: dict):
        self._config_updated_signal.emit(new_config)

    # Чат: SSE-события и непрочитанное
    def _handle_chat_message(self):
        # SSE 'message': обновляем открытые окна и пересчитываем непрочитанное с уведомлением.
        self._friends_drawer.refresh_open_chats()
        self._fetch_unread_async(notify=True)

    def _handle_chat_read(self):
        # SSE 'message_read': наши сообщения прочитаны — перерисовываем галочки.
        self._friends_drawer.refresh_open_chats()

    def _on_sse_connected(self):
        # SSE (пере)подключился — досинхронизируем то, что могли пропустить при обрыве.
        self.refresh_chat_unread()
        self._friends_drawer.notify_friends_updated()
        self._friends_drawer.refresh_open_chats()

    def refresh_chat_unread(self):
        # Пересчитать непрочитанное без уведомления (старт / после открытия чата).
        self._fetch_unread_async(notify=False)

    def _preload_chats(self):
        # Прогрев кэша всех переписок после запуска — чтобы окна открывались мгновенно.
        try:
            from ui.chat_window import preload_all
            preload_all()
        except Exception:
            pass

    def _fetch_unread_async(self, notify: bool):
        import threading, chat_client
        def _run():
            counts = chat_client.unread_counts()
            self._chat_unread_signal.emit(counts, notify)
        threading.Thread(target=_run, daemon=True).start()

    def _apply_chat_unread(self, counts: dict, notify: bool):
        increased = [u for u, c in counts.items() if c > self._chat_unread.get(u, 0)]
        self._chat_unread = dict(counts)
        total = sum(counts.values()) if counts else 0
        try:
            import notifications
            notifications.center().set_messages(total > 0)
        except Exception:
            pass
        self._friends_drawer.set_unread_map(counts)
        if notify:
            for sender in increased:
                self._notify_new_message(sender)

    def _notify_new_message(self, sender_uuid: str):
        import notifications
        nc = notifications.center()
        if not nc.should_disturb():
            return  # DND: только точка/бейджи (уже выставлены)
        if sender_uuid in self._friends_drawer._panel._chats:
            return  # чат уже открыт — не беспокоим повторно
        nc.play_ping()
        name = self._friends_drawer.friend_name(sender_uuid) or "Друг"
        self._friends_drawer.open_chat(sender_uuid, name)
        # Мигание иконки приложения в панели задач (пока окно не активируют)
        try:
            from PyQt6.QtWidgets import QApplication
            QApplication.alert(self, 0)
        except Exception:
            pass
        # Тост с головой: в фоне гарантируем кеш головы (первый раз её ещё нет),
        # затем показываем в UI-потоке через сигнал.
        import threading
        def _run():
            head_path = ""
            try:
                from config import CACHE_DIR
                p = CACHE_DIR / f"head_{name}.png"
                if not p.exists() and name != "Друг":
                    import requests
                    r = requests.get(f"https://mc-heads.net/avatar/{name}/64", timeout=6)
                    r.raise_for_status()
                    p.write_bytes(r.content)
                if p.exists():
                    head_path = str(p)
            except Exception:
                pass
            self._toast_signal.emit(name, "Новое сообщение", head_path, sender_uuid)
        threading.Thread(target=_run, daemon=True).start()

    def _show_toast(self, title: str, body: str, head_path: str, sender_uuid: str):
        # Кастомный тост-виджет (без системного звука Windows; свой звук уже сыграли).
        # Клик по тосту — поднять окно чата с этим другом.
        from ui.toast import show_toast
        show_toast(title, body, head_path,
                   on_click=lambda u=sender_uuid, n=title: self._friends_drawer.open_chat(u, n))

    def _on_media_update(self):
        # вызывается из потока ConfigWatcher после media_sync — маршалим в Qt-поток
        self._media_refresh_signal.emit()

    def _on_roles_update(self):
        # SSE 'roles_updated' (поток ConfigWatcher): перечитываем роли и перерисовываем режим
        import auth_client
        try:
            auth_client.refresh_discord_roles()
        except Exception:
            pass
        self._roles_loaded_signal.emit()

    def _poll_roles(self):
        # Периодическая страховка: рефреш ролей в фоне, перерисовка только если изменились
        import threading, auth_client
        def _run():
            try:
                if auth_client.refresh_discord_roles():
                    self._roles_loaded_signal.emit()
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    def _refresh_media_images(self):
        # картинки уже пере-скачаны media_sync — перерисовываем с ними (как при config update)
        self._sidebar.update_modes(self._visible_modes())
        if self._current_mode:
            self._content.show_mode(self._current_mode)

    def _apply_config_update(self, new_config: dict):
        import logging
        self._config = new_config
        self._content.set_launcher_config(new_config)
        modes = self._visible_modes()
        logging.getLogger("api.sse").info("[config] visible modes: %s", [m["id"] for m in modes])
        self._sidebar.update_modes(modes)
        self._friends_drawer.set_modes(new_config.get("modes", []))
        # Обновить текущий открытый режим если он изменился
        if self._current_mode:
            updated = next((m for m in modes if m["id"] == self._current_mode["id"]), None)
            if updated:
                self._current_mode = updated
                self._content.show_mode(updated)
        # Проверка обновления лаунчера (новая схема)
        self._check_app_update()

    def _check_app_update(self):
        #Сверяет app.version из манифеста со своей версией (state.json в папке установки, которую пишет updater) — показывает баннер обновления.
        try:
            import sys, json, requests
            from pathlib import Path
            from config import SERVER_URL
            if not hasattr(self, "_update_shown_ver"):
                self._update_shown_ver = ""
            state_f = Path(sys.executable).parent / "state.json"
            if not state_f.exists():
                return  # dev или старая схема — своей версии нет
            running = json.loads(state_f.read_text(encoding="utf-8")).get("app_ver", "")
            latest = (requests.get(f"{SERVER_URL}/api/launcher/manifest", timeout=6)
                      .json().get("app") or {}).get("version", "")
            if running and latest and latest != running and latest != self._update_shown_ver:
                self._update_shown_ver = latest
                self._sidebar.show_update_banner(latest)
        except Exception:
            pass

    def _restart_for_update(self):
        # Баннер Updater, при нажатии закроет лаунчер (mutex освободится) и запустит updater, который скачет новую версию и стартанет лаунчер. Затем закрываем текущий экземпляр.
        import sys, subprocess
        from pathlib import Path
        root = Path(sys.executable).parent           # папка установки (base)
        pyw = root / "pythonw.exe"
        # Релонч под брендированным именем (копия подписанного pythonw.exe), если есть.
        brand = root / "TempusLauncher.exe"
        launch_exe = brand if brand.exists() else pyw
        if (root / "updater.pyc").exists() and pyw.exists():
            r = root.as_posix()                       # forward slashes — безопасно в коде
            le = launch_exe.as_posix()
            waiter = (
                "import ctypes, time, subprocess\n"
                "k = ctypes.windll.kernel32\n"
                "end = time.time() + 15\n"
                "while time.time() < end:\n"
                "    h = k.OpenMutexW(0x100000, False, 'TempusLauncher_AppMutex')\n"
                "    if not h:\n"
                "        break\n"
                "    k.CloseHandle(h)\n"
                "    time.sleep(0.3)\n"
                f"subprocess.Popen([r'{le}', 'updater.pyc'], cwd='{r}')\n"
            )
            try:
                subprocess.Popen([str(pyw), "-c", waiter], cwd=str(root),
                                 close_fds=True, creationflags=0x00000008)  # DETACHED_PROCESS
            except Exception:
                pass
        # чистый выход — освобождает mutex, чтобы ожидатель продолжил
        try:
            self._watcher.stop()
        except Exception:
            pass
        tray = getattr(self, "_tray_icon", None)
        if tray:
            tray.hide()
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().quit()

    def _on_news_updated(self, new_news: list):
        self._news = new_news

    def _toggle_friends_drawer(self, checked: bool):
        TOP_H = 56
        if checked:
            self._friends_drawer.open_drawer(TOP_H, self.width(), self.height())
        else:
            self._friends_drawer.close_drawer()

    def _on_indicator_changed(self, color: str):
        """Обновляет точку-индикатор на кнопке друзей ('' | 'yellow' | 'red')."""
        if not color:
            self._friends_dot.hide()
            return
        c = "#ef4444" if color == "red" else "#f5b301"
        self._friends_dot.setStyleSheet(
            f"background: {c}; border-radius: 4px; border: 1px solid #0a0d14;")
        self._friends_dot.show()
        self._friends_dot.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for layer in (self._bg_a, self._bg_b):
            layer.setGeometry(0, 0, self.width(), self.height())
            layer.lower()
        if hasattr(self, "_download_bar") and self._download_bar.isVisible():
            btn_pos = self._sidebar.downloads_btn_pos_in(self)
            self._download_bar.set_anchor(btn_pos)
            self._download_bar.raise_()
        if hasattr(self, "_friends_drawer") and self._friends_drawer.isVisible():
            self._friends_drawer.reposition(56, self.width(), self.height())

    def closeEvent(self, event):
        from PyQt6.QtWidgets import QSystemTrayIcon
        tray = getattr(self, "_tray_icon", None)
        if tray and tray.isVisible() and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
        else:
            self._watcher.stop()
            super().closeEvent(event)
