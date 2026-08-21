import logging
import threading
import requests
from PyQt6.QtCore import (Qt, pyqtSignal, QTimer, QObject,
                           QPropertyAnimation, QEasingCurve, QRect, QPoint)
from PyQt6.QtGui import QFont, QPixmap, QPainter, QColor, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QLineEdit, QFrame
)
import auth_client
import config as _config


def _verify():
    import sys
    p = _config.SERVER_CERT
    if p.exists():
        return str(p)
    return True if getattr(sys, 'frozen', False) else __import__('certifi').where()

log = logging.getLogger("friends")

# Предзагруженные данные друзей со сплеша
_prefetch_cache: dict | None = None

# Лёгкий кэш uuid -> ник (для тостов/чата, когда панель ещё не открывали)
_names_cache: dict[str, str] = {}

def _update_names(data: dict):
    if not data:
        return
    names = []
    for key in ("friends", "incoming", "outgoing"):
        for r in (data.get(key) or []):
            u, n = r.get("uuid"), r.get("username")
            if u and n:
                _names_cache[u] = n
                names.append(n)
    if names:
        preload_heads(names)   # прогреваем головы, пока список ещё не открыли

def name_for(uuid: str) -> str | None:
    return _names_cache.get(uuid)

def set_prefetch_cache(data: dict):
    global _prefetch_cache
    _prefetch_cache = data
    _update_names(data)
DRAWER_W = 300


class _Loader(QObject):
    done = pyqtSignal(object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            result = self._fn()
            log.debug("[Loader] done, result type=%s", type(result).__name__)
            self.done.emit(result)
        except Exception as e:
            log.error("[Loader] exception: %s", e, exc_info=True)
            self.done.emit(None)


_HEAD_CACHE_TTL = 600  # секунд (10 минут)
_head_inflight: set[str] = set()   # ники, чьи головы сейчас качаются (без дублей)


def _refresh_head_async(username: str):
    """Фоново перекачивает голову в кеш (revalidate). Не блокирует UI."""
    if not username or username in _head_inflight:
        return
    _head_inflight.add(username)
    def _run():
        try:
            from config import CACHE_DIR
            r = requests.get(f"https://mc-heads.net/avatar/{username}/64", timeout=8)
            r.raise_for_status()
            (CACHE_DIR / f"head_{username}.png").write_bytes(r.content)
        except Exception:
            pass
        finally:
            _head_inflight.discard(username)
    threading.Thread(target=_run, daemon=True).start()


def _head_pixmap(username: str, size: int = 32) -> QPixmap | None:
    """Голова из кеша. Протухшую НЕ удаляем — показываем сразу (stale-while-revalidate),
    а свежую подтягиваем в фоне; на следующем показе будет актуальная."""
    import time
    from config import CACHE_DIR
    path = CACHE_DIR / f"head_{username}.png"
    if path.exists():
        if time.time() - path.stat().st_mtime >= _HEAD_CACHE_TTL:
            _refresh_head_async(username)
        px = QPixmap(str(path))
        if not px.isNull():
            return px.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    return None


def preload_heads(usernames):
    """Фоново прогревает кеш голов (после запуска / когда пришёл список друзей)."""
    def _run():
        from config import CACHE_DIR
        for u in usernames:
            if not u:
                continue
            path = CACHE_DIR / f"head_{u}.png"
            if path.exists():
                continue
            try:
                r = requests.get(f"https://mc-heads.net/avatar/{u}/64", timeout=8)
                r.raise_for_status()
                path.write_bytes(r.content)
            except Exception:
                pass
    threading.Thread(target=_run, daemon=True).start()


class _GlCornerMask(QWidget):
    """Закрашивает острые углы QOpenGLWidget цветом фона карточки."""
    _BG = QColor(12, 15, 22)

    def __init__(self, gl_w: int, card_h: int, radius: int, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(gl_w, card_h)
        self._r = radius

    def paintEvent(self, _):
        p = QPainter(self)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._BG)
        r = self._r
        h = self.height()

        # Верхний левый угол
        tl_rect = QPainterPath()
        tl_rect.addRect(0, 0, r, r)
        tl_arc = QPainterPath()
        tl_arc.moveTo(r, r)
        tl_arc.arcTo(0, 0, 2 * r, 2 * r, 90, 90)
        tl_arc.closeSubpath()
        p.drawPath(tl_rect.subtracted(tl_arc))

        # Нижний левый угол
        bl_rect = QPainterPath()
        bl_rect.addRect(0, h - r, r, r)
        bl_arc = QPainterPath()
        bl_arc.moveTo(r, h - r)
        bl_arc.arcTo(0, h - 2 * r, 2 * r, 2 * r, 180, 90)
        bl_arc.closeSubpath()
        p.drawPath(bl_rect.subtracted(bl_arc))


class _AvatarWrap(QWidget):
    hover_enter = pyqtSignal()
    hover_leave = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 36)
        self.setStyleSheet("background: transparent;")

    def enterEvent(self, e): self.hover_enter.emit()
    def leaveEvent(self, e): self.hover_leave.emit()


class FriendHoverCard(QWidget):
    CARD_W = 310
    CARD_H = 185
    GL_W   = 90
    GAME_H = 86

    def __init__(self, friend: dict, modes: list, parent=None):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self.CARD_W, self.CARD_H)

        self._friend     = friend
        # Играет сейчас → текущий режим; иначе → последний сыгранный.
        self._playing    = bool(friend.get("mode_id"))
        mode_id          = friend.get("mode_id") or friend.get("last_mode") or ""
        modes_map        = {m["id"]: m for m in modes}
        self._mode_data  = modes_map.get(mode_id, {})
        self._banner_px: QPixmap | None = None
        self._logo_px:   QPixmap | None = None
        self._alpha      = 0.0
        self._target     = 0.0
        self._gl_shown   = False
        self._anim       = QTimer(self)
        self._anim.setInterval(16)
        self._anim.timeout.connect(self._tick)
        self._gl_delay   = QTimer(self)
        self._gl_delay.setSingleShot(True)
        self._gl_delay.setInterval(500)
        self._gl_delay.timeout.connect(self._show_gl)

        self.setWindowOpacity(0.0)
        self._build()
        self._load_assets()

    # Build

    def _build(self):
        from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Left: GL skin в контейнере фиксированного размера
        from PyQt6.QtWidgets import QVBoxLayout as _VL, QGraphicsOpacityEffect
        gl_container = QWidget()
        gl_container.setFixedSize(self.GL_W, self.CARD_H)
        gl_container.setStyleSheet("background: transparent;")
        _cl = _VL(gl_container)
        _cl.setContentsMargins(0, 0, 0, 0)
        self._gl = None
        self._gl_overlay = None
        try:
            from ui.player_gl_widget import PlayerGLWidget
            self._gl = PlayerGLWidget(gl_container)
            self._gl.setFixedSize(self.GL_W, self.CARD_H)
            username = self._friend.get("username", "")
            if username:
                QTimer.singleShot(0, lambda: self._gl.set_username(username, "classic", False))
            self._gl.hide()
            _cl.addWidget(self._gl)

            # Оверлей поверх GL — скрывает чёрный фон, плавно исчезает при появлении
            self._gl_overlay = QWidget(gl_container)
            self._gl_overlay.setFixedSize(self.GL_W, self.CARD_H)
            self._gl_overlay.setStyleSheet("background: #0c0f16;")
            self._gl_overlay.hide()
        except Exception:
            pass
        # Маска скруглённых углов поверх GL
        mask = _GlCornerMask(self.GL_W, self.CARD_H, 12, gl_container)
        mask.move(0, 0)
        mask.raise_()
        root.addWidget(gl_container)

        # ── Right: info labels (transparent bg — card drawn in paintEvent) ─
        right = QWidget()
        right.setStyleSheet("background: transparent;")
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(12, 12, 12, 0)
        rlay.setSpacing(2)

        online    = self._friend.get("online", False)
        mode_name = self._friend.get("mode")

        name_lbl = QLabel(self._friend.get("username", "Unknown"))
        name_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        name_lbl.setStyleSheet("color: #E6EDF3; background: transparent;")

        if online and mode_name:
            st_text, st_color = mode_name, "#4caf50"
        elif online:
            st_text, st_color = "В сети", "#5B8CFF"
        else:
            st_text, st_color = "Не в сети", "#555570"

        st_lbl = QLabel(st_text)
        st_lbl.setFont(QFont("Segoe UI", 9))
        st_lbl.setStyleSheet(f"color: {st_color}; background: transparent;")

        rlay.addWidget(name_lbl)
        rlay.addWidget(st_lbl)
        rlay.addStretch()
        root.addWidget(right, 1)

    # ── Assets ────────────────────────────────────────────────────────────────

    def _load_assets(self):
        if not self._mode_data:
            return
        from assets_cache import AssetCache

        def _set_banner(u, px):
            self._banner_px = px
            self.update()

        def _set_logo(u, px):
            self._logo_px = px
            self.update()

        banner_url = self._mode_data.get("banner_url", "")
        logo_url   = self._mode_data.get("logo_url", "")
        if banner_url:
            AssetCache.load(banner_url, _set_banner)
        if logo_url:
            AssetCache.load(logo_url, _set_logo)

    # ── Show / hide ───────────────────────────────────────────────────────────

    def show_card(self, global_pos: QPoint):
        self.move(global_pos)
        self._target = 1.0
        self._gl_shown = False
        self._gl_delay.stop()
        self.show()
        self.raise_()
        self._anim.start()

    def hide_card(self):
        self._target = 0.0
        self._gl_delay.stop()
        self._anim.start()

    def _show_gl(self):
        if self._gl and not self._gl_shown:
            self._gl_shown = True
            self._gl.show()
            try:
                self._gl.restart_intro()
            except Exception:
                pass
            if self._gl_overlay:
                from PyQt6.QtWidgets import QGraphicsOpacityEffect
                self._gl_overlay.show()
                self._gl_overlay.raise_()
                fx = QGraphicsOpacityEffect(self._gl_overlay)
                fx.setOpacity(1.0)
                self._gl_overlay.setGraphicsEffect(fx)
                self._gl_fade = QPropertyAnimation(fx, b"opacity")
                self._gl_fade.setDuration(350)
                self._gl_fade.setStartValue(1.0)
                self._gl_fade.setEndValue(0.0)
                self._gl_fade.setEasingCurve(QEasingCurve.Type.OutCubic)
                self._gl_fade.finished.connect(self._gl_overlay.hide)
                self._gl_fade.start()
                self._gl_fx = fx  # держим ссылку

    def _tick(self):
        self._alpha += (self._target - self._alpha) * 0.12
        if abs(self._alpha - self._target) < 0.015:
            self._alpha = self._target
            self._anim.stop()
            if self._alpha <= 0:
                self.hide()
                if self._gl:
                    self._gl.hide()
                if self._gl_overlay:
                    self._gl_overlay.hide()
                    self._gl_overlay.setGraphicsEffect(None)
                self._gl_shown = False
            elif not self._gl_shown:
                self._show_gl()
        self.setWindowOpacity(self._alpha)

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        GL_W   = self.GL_W
        GAME_H = self.GAME_H

        # Card background
        card_path = QPainterPath()
        card_path.addRoundedRect(0, 0, w, h, 12, 12)
        p.setClipPath(card_path)
        p.fillRect(0, 0, w, h, QColor(12, 15, 22, 252))
        p.setClipping(False)

        # Card border
        border_pen = QPen(QColor(255, 255, 255, 22))
        border_pen.setWidth(1)
        p.setPen(border_pen)
        p.drawPath(card_path)

        if not self._mode_data:
            return

        game_y = h - GAME_H
        game_x = GL_W
        game_w = w - GL_W

        # Separator
        p.setPen(QColor(255, 255, 255, 14))
        p.drawLine(game_x, game_y, w, game_y)

        # Banner background
        if self._banner_px and not self._banner_px.isNull():
            p.save()
            clip = QPainterPath()
            clip.addRect(game_x, game_y, game_w, GAME_H)
            p.setClipPath(clip.intersected(card_path))
            scaled = self._banner_px.scaled(
                game_w, GAME_H,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation)
            bx = game_x + (game_w - scaled.width()) // 2
            by = game_y + (GAME_H - scaled.height()) // 2
            p.setOpacity(0.45)
            p.drawPixmap(bx, by, scaled)
            p.restore()

        # Dark overlay
        p.setOpacity(0.6)
        p.fillRect(game_x, game_y, game_w, GAME_H, QColor(7, 9, 16, 210))
        p.setOpacity(1.0)

        # Logo
        LOGO = 38
        logo_x = game_x + 10
        logo_y = game_y + (GAME_H - LOGO) // 2
        if self._logo_px and not self._logo_px.isNull():
            sl = self._logo_px.scaled(LOGO, LOGO,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(logo_x + (LOGO - sl.width()) // 2,
                         logo_y + (LOGO - sl.height()) // 2, sl)

        text_x = logo_x + LOGO + 10
        text_w = game_w - LOGO - 28

        p.setPen(QColor(215, 225, 242))
        p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        p.drawText(text_x, game_y + 14, text_w, 22,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._mode_data.get("name", ""))

        secs = self._friend.get("last_seconds", 0) or 0
        try:
            import playtime as _pt
            pt_str = _pt.format_hours(secs) if secs else ""
        except Exception:
            pt_str = ""
        # Играет сейчас → «Играет · <время>», иначе → «Наиграно <время>»
        if pt_str:
            sub = (f"Играет · {pt_str}" if self._playing else f"Наиграно {pt_str}")
        else:
            sub = "Играет" if self._playing else "Нет данных"
        p.setPen(QColor(90, 105, 130))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(text_x, game_y + 44, text_w, 20,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            sub)


class FriendRow(QWidget):
    remove_requested  = pyqtSignal(str)        # uuid
    join_requested    = pyqtSignal(str, str)   # mode_id, server_ip
    message_requested = pyqtSignal(str, str)   # uuid, username — открыть чат

    def __init__(self, friend: dict, modes: list = None, parent=None):
        super().__init__(parent)
        self._uuid      = friend["uuid"]
        self._username  = friend.get("username") or "Unknown"
        self._online    = friend.get("online", False)
        self._mode      = friend.get("mode")
        self._mode_id   = friend.get("mode_id")
        self._server_ip = friend.get("server_ip")
        self._last_mode = friend.get("last_mode")
        self._last_seconds = friend.get("last_seconds", 0)
        self._modes     = modes or []
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(700)
        self._hover_timer.timeout.connect(self._show_hover_card)
        self.setFixedHeight(44)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.destroyed.connect(self._cleanup_hover)
        self._build()
        # Создаём карточку сразу — GL-виджет начинает грузить скин в фоне
        self._hover_card = FriendHoverCard(
            {"uuid": self._uuid, "username": self._username,
             "online": self._online, "mode": self._mode,
             "mode_id": self._mode_id,
             "last_mode": self._last_mode, "last_seconds": self._last_seconds},
            self._modes,
        )

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(8)

        # Аватар с цветной рамкой-индикатором
        avatar_wrap = _AvatarWrap()
        avatar_wrap.hover_enter.connect(self._on_avatar_enter)
        avatar_wrap.hover_leave.connect(self._on_avatar_leave)
        self._avatar = QLabel(avatar_wrap)
        self._avatar.setFixedSize(32, 32)
        self._avatar.move(2, 2)
        self._avatar.setStyleSheet("background: #1a1a2e; border-radius: 6px;")

        if self._online and self._mode:
            dot_color = "#4caf50"   # зелёный — играет
        elif self._online:
            dot_color = "#5B8CFF"   # синий — в сети
        else:
            dot_color = "#333355"   # серый — офлайн

        dot = QLabel(avatar_wrap)
        dot.setFixedSize(10, 10)
        dot.move(26, 26)
        dot.setStyleSheet(f"""
            background: {dot_color};
            border-radius: 5px;
            border: 2px solid #0a0d14;
        """)

        lay.addWidget(avatar_wrap)
        self._load_avatar()

        # Имя + статус
        info = QVBoxLayout()
        info.setSpacing(0)
        name = QLabel(self._username)
        name.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        name.setStyleSheet("color: #e0e0f0; background: transparent;")

        if self._online and self._mode:
            status_text  = self._mode
            status_color = "#4caf50"
        elif self._online:
            status_text  = "В сети"
            status_color = "#5B8CFF"
        else:
            status_text  = "Не в сети"
            status_color = "#555570"

        status = QLabel(status_text)
        status.setFont(QFont("Segoe UI", 8))
        status.setStyleSheet(f"color: {status_color}; background: transparent;")
        info.addWidget(name)
        info.addWidget(status)
        lay.addLayout(info, 1)

        # Бейдж непрочитанных (скрыт при 0)
        self._unread_lbl = QLabel("")
        self._unread_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._unread_lbl.setFixedHeight(18)
        self._unread_lbl.setMinimumWidth(18)
        self._unread_lbl.setStyleSheet("""
            background: #ef4444; color: #fff; border-radius: 9px;
            font-size: 10px; font-weight: 700; padding: 0 5px;
        """)
        self._unread_lbl.hide()
        lay.addWidget(self._unread_lbl)

        # Кнопка меню (три точки)
        from ui.assets import svg_icon as _svg
        self._menu_btn = QPushButton()
        self._menu_btn.setFixedSize(24, 24)
        self._menu_btn.setIcon(_svg("menu_dots_vertical.svg", "#aaaacc", 14))
        self._menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._menu_btn.setVisible(False)
        self._menu_btn.setStyleSheet("""
            QPushButton { background: rgba(255,255,255,0);
                border: none; border-radius: 4px; }
            QPushButton:hover { background: rgba(255,255,255,15); }
        """)
        self._menu_btn.clicked.connect(self._show_context_menu)
        lay.addWidget(self._menu_btn)

    def enterEvent(self, e):
        self._menu_btn.setVisible(True)
        self.setStyleSheet("background: rgba(100,140,255,18); border-radius: 8px;")

    def leaveEvent(self, e):
        self._menu_btn.setVisible(False)
        self.setStyleSheet("background: transparent;")
        self._hover_timer.stop()

    def _on_avatar_enter(self):
        self._hover_timer.start()

    def _on_avatar_leave(self):
        self._hover_timer.stop()
        if self._hover_card:
            self._hover_card.hide_card()

    def _show_hover_card(self):
        avatar_wrap = self.findChild(_AvatarWrap)
        if avatar_wrap:
            gp = avatar_wrap.mapToGlobal(QPoint(0, 0))
        else:
            gp = self.mapToGlobal(QPoint(0, 0))
        x = gp.x() - FriendHoverCard.CARD_W - 8
        y = gp.y() - FriendHoverCard.CARD_H // 2 + 18
        self._hover_card.show_card(QPoint(x, y))

    def _cleanup_hover(self):
        if self._hover_card:
            self._hover_card.deleteLater()
            self._hover_card = None

    def _show_context_menu(self):
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #12142a; border: 1px solid rgba(255,255,255,20);
                border-radius: 8px; padding: 4px; color: #e0e0f0; font-size: 12px; }
            QMenu::item { padding: 6px 16px; border-radius: 5px; }
            QMenu::item:selected { background: rgba(100,140,255,120); }
            QMenu::item:disabled { color: #444466; }
        """)
        act_message = menu.addAction("Сообщение")
        menu.addSeparator()

        act_launch = menu.addAction("Запустить игру")
        act_launch.setEnabled(bool(self._mode_id))

        can_join = bool(self._online and self._mode_id and self._server_ip)
        act_join = menu.addAction("Присоединиться к игре")
        act_join.setEnabled(can_join)

        menu.addSeparator()
        act_remove = menu.addAction("Удалить друга")

        action = menu.exec(self._menu_btn.mapToGlobal(
            self._menu_btn.rect().bottomLeft()))

        if action == act_message:
            self.message_requested.emit(self._uuid, self._username)
        elif action == act_launch and self._mode_id:
            self.join_requested.emit(self._mode_id, "")
        elif action == act_join:
            self.join_requested.emit(self._mode_id, self._server_ip)
        elif action == act_remove:
            self.remove_requested.emit(self._uuid)

    def mouseDoubleClickEvent(self, e):
        # Двойной клик по строке друга открывает чат (кнопка меню/аватар
        # обрабатываются своими виджетами и сюда не доходят).
        if e.button() == Qt.MouseButton.LeftButton:
            self.message_requested.emit(self._uuid, self._username)
        super().mouseDoubleClickEvent(e)

    def set_unread(self, count: int):
        """Показать/скрыть бейдж непрочитанных сообщений."""
        if count and count > 0:
            self._unread_lbl.setText("99+" if count > 99 else str(count))
            self._unread_lbl.show()
        else:
            self._unread_lbl.hide()

    def _load_avatar(self):
        px = _head_pixmap(self._username, 32)
        if px:
            self._avatar.setPixmap(px)
            return
        username = self._username

        def _do_load():
            from config import CACHE_DIR
            path = CACHE_DIR / f"head_{username}.png"
            if not path.exists():
                try:
                    r = requests.get(
                        f"https://mc-heads.net/avatar/{username}/64", timeout=6)
                    r.raise_for_status()
                    path.write_bytes(r.content)
                except Exception:
                    return None
            return _head_pixmap(username, 32)

        loader = _Loader(_do_load, self)
        loader.done.connect(self._on_avatar)
        loader.start()

    def _on_avatar(self, result):
        if isinstance(result, QPixmap) and not result.isNull():
            self._avatar.setPixmap(result)


class IncomingRow(QWidget):
    accepted = pyqtSignal(str)
    declined = pyqtSignal(str)

    def __init__(self, req: dict, parent=None):
        super().__init__(parent)
        self._uuid = req["uuid"]
        username = req.get("username") or "Unknown"
        self.setFixedHeight(44)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(8)

        # Аватар
        avatar = QLabel()
        avatar.setFixedSize(32, 32)
        avatar.setStyleSheet("background: #1a1a2e; border-radius: 6px;")
        lay.addWidget(avatar)
        px = _head_pixmap(username, 32)
        if px:
            avatar.setPixmap(px)
        else:
            def _fetch_av(u=username, av=avatar):
                from config import CACHE_DIR
                path = CACHE_DIR / f"head_{u}.png"
                if not path.exists():
                    try:
                        r = requests.get(f"https://mc-heads.net/avatar/{u}/64", timeout=6)
                        r.raise_for_status()
                        path.write_bytes(r.content)
                    except Exception:
                        return None
                return _head_pixmap(u, 32)
            ldr = _Loader(_fetch_av, self)
            ldr.done.connect(lambda px, av=avatar: av.setPixmap(px) if px else None)
            ldr.start()

        lbl = QLabel(username)
        lbl.setStyleSheet("color: #c0c0e0; font-size: 11px; background: transparent;")
        lay.addWidget(lbl, 1)

        from ui.assets import svg_icon as _svg
        ok = QPushButton()
        ok.setFixedSize(26, 26)
        ok.setIcon(_svg("plus.svg", "#ffffff", 14))
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.setStyleSheet("""
            QPushButton { background: rgba(76,175,80,150);
                border:none; border-radius:5px; }
            QPushButton:hover { background: rgba(76,175,80,220); }
        """)
        ok.clicked.connect(lambda: self.accepted.emit(self._uuid))

        no = QPushButton()
        no.setFixedSize(26, 26)
        no.setIcon(_svg("cross.svg", "#ffffff", 14))
        no.setCursor(Qt.CursorShape.PointingHandCursor)
        no.setStyleSheet("""
            QPushButton { background: rgba(255,80,80,100);
                border:none; border-radius:5px; }
            QPushButton:hover { background: rgba(255,80,80,200); }
        """)
        no.clicked.connect(lambda: self.declined.emit(self._uuid))

        lay.addWidget(ok)
        lay.addWidget(no)


class _OutgoingRow(QWidget):
    cancelled = pyqtSignal(str)  # uuid

    def __init__(self, req: dict, parent=None):
        super().__init__(parent)
        self._uuid = req["uuid"]
        username = req.get("username") or "Unknown"
        self.setFixedHeight(44)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(8)

        avatar = QLabel()
        avatar.setFixedSize(32, 32)
        avatar.setStyleSheet("background: #1a1a2e; border-radius: 6px;")
        lay.addWidget(avatar)
        px = _head_pixmap(username, 32)
        if px:
            avatar.setPixmap(px)
        else:
            def _fetch_av(u=username, av=avatar):
                from config import CACHE_DIR
                path = CACHE_DIR / f"head_{u}.png"
                if not path.exists():
                    try:
                        r = requests.get(f"https://mc-heads.net/avatar/{u}/64", timeout=6)
                        r.raise_for_status()
                        path.write_bytes(r.content)
                    except Exception:
                        return None
                return _head_pixmap(u, 32)
            ldr = _Loader(_fetch_av, self)
            ldr.done.connect(lambda px, av=avatar: av.setPixmap(px) if px else None)
            ldr.start()

        lbl = QLabel(username)
        lbl.setStyleSheet("color: #7888aa; font-size: 11px; background: transparent;")
        lay.addWidget(lbl, 1)

        cancel = QPushButton("Отменить")
        cancel.setFixedHeight(22)
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setStyleSheet("""
            QPushButton { background: rgba(255,80,80,80); color:#ccc;
                border:none; border-radius:4px; font-size:10px; padding: 0 8px; }
            QPushButton:hover { background: rgba(255,80,80,180); color:#fff; }
        """)
        cancel.clicked.connect(lambda: self.cancelled.emit(self._uuid))
        lay.addWidget(cancel)


class FriendsPanel(QWidget):
    join_game = pyqtSignal(str, str)  # mode_id, server_ip

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("FriendsPanel { background: #0a0d14; } QLabel { background: transparent; }")
        self._my_uuid: str = ""
        self._search_card = None
        self._modes: dict[str, str] = {}  # id -> name
        self._config_modes: list = []     # полный список режимов из конфига
        self._chats: dict = {}            # uuid -> ChatWindow (открытые окна переписки)
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._refresh)
        # Поллинг — лишь резервный (основное — SSE friends_updated + ресинк на реконнекте)
        self._poll_timer.setInterval(30_000)
        self._build()

    def showEvent(self, e):
        super().showEvent(e)
        # Если open_drawer уже инициализировал uuid — не запускаем refresh повторно
        if self._my_uuid:
            return
        try:
            settings = auth_client._load_settings()
            raw = settings.get("uuid", "")
            s = raw.replace("-", "")
            self._my_uuid = f"{s[:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:]}" if len(s) == 32 else raw
            has_discord = bool(settings.get("discord_id"))
            log.info("[showEvent] uuid=%s has_discord=%s", self._my_uuid, has_discord)
            self._no_discord_widget.setVisible(not has_discord)
            self._content_widget.setVisible(has_discord)
            if self._my_uuid and has_discord:
                self._refresh()
                self._poll_timer.start()
        except Exception as e:
            log.error("[showEvent] %s", e, exc_info=True)

    def hideEvent(self, e):
        super().hideEvent(e)
        self._poll_timer.stop()

    def set_modes(self, modes: list):
        self._modes = {m["id"]: m.get("name", m["id"]) for m in modes if "id" in m}
        self._config_modes = modes

    def _init_uuid(self):
        """Инициализирует _my_uuid из настроек (нужно для фонового обновления,
        когда панель ещё ни разу не открывали)."""
        raw = auth_client._load_settings().get("uuid", "")
        s = raw.replace("-", "")
        self._my_uuid = f"{s[:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:]}" if len(s) == 32 else raw

    def notify_friends_updated(self):
        """SSE friends_updated. Панель видна → полный рендер; скрыта → только индикатор
        (не создаём строки/GL-виджеты в скрытую панель — это и давало пустые заголовки)."""
        if not self._my_uuid:
            self._init_uuid()
        if not self._my_uuid:
            return
        if self.isVisible():
            self._refresh()
        else:
            self._refresh_indicator_only()

    def _refresh_indicator_only(self):
        """Лёгкое фоновое обновление жёлтой точки (входящие заявки) без рендера панели."""
        import threading
        def _run():
            for attempt in range(3):
                try:
                    r = requests.get(
                        f"{_config.SERVER_URL}/api/friends",
                        headers=auth_client.session_headers(), timeout=8, verify=_verify())
                    if r.status_code in (401, 422) and attempt < 2:
                        auth_client.create_session()
                        continue
                    r.raise_for_status()
                    data = r.json()
                    _update_names(data)
                    try:
                        import notifications
                        notifications.center().set_requests(bool(data.get("incoming")))
                    except Exception:
                        pass
                    return
                except Exception:
                    if attempt < 2:
                        import time as _t
                        _t.sleep(1)
                        continue
                    return
        threading.Thread(target=_run, daemon=True).start()

    def refresh_discord_state(self):
        """Вызывается после привязки/отвязки Discord."""
        settings = auth_client._load_settings()
        has_discord = bool(settings.get("discord_id"))
        self._no_discord_widget.setVisible(not has_discord)
        self._content_widget.setVisible(has_discord)
        if has_discord and self._my_uuid:
            self._refresh()
            self._poll_timer.start()

    # Build UI

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        # Заголовок
        title = QLabel("Друзья")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #e0e0f0;")
        lay.addWidget(title)

        # Заглушка — Discord не привязан
        self._no_discord_widget = QWidget()
        self._no_discord_widget.setStyleSheet("background: transparent;")
        no_dc_lay = QVBoxLayout(self._no_discord_widget)
        no_dc_lay.setContentsMargins(0, 20, 0, 0)
        no_dc_lay.setSpacing(12)

        mimi = QLabel()
        mimi.setAlignment(Qt.AlignmentFlag.AlignCenter)
        from pathlib import Path as _P
        mimi_path = str(_P(__file__).parent.parent / "assets" / "mimi_grand.png")
        mimi_px = QPixmap(mimi_path)
        if not mimi_px.isNull():
            mimi.setPixmap(mimi_px.scaledToWidth(120, Qt.TransformationMode.SmoothTransformation))
        no_dc_lay.addWidget(mimi)

        self._no_discord_lbl = QLabel(
            "Привяжите Discord в настройках\nаккаунта чтобы добавлять друзей"
        )
        self._no_discord_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_discord_lbl.setWordWrap(True)
        self._no_discord_lbl.setStyleSheet("color: #444466; font-size: 12px;")
        no_dc_lay.addWidget(self._no_discord_lbl)

        self._no_discord_widget.hide()
        lay.addWidget(self._no_discord_widget)

        # Основной контент (скрывается если нет Discord)
        self._content_widget = QWidget()
        self._content_widget.setStyleSheet("background: transparent;")
        content_lay = QVBoxLayout(self._content_widget)
        content_lay.setContentsMargins(0, 0, 0, 0)
        content_lay.setSpacing(10)
        lay.addWidget(self._content_widget, 1)

        search_row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Найти игрока...")
        self._search.setFixedHeight(32)
        self._search.setStyleSheet("""
            QLineEdit { background: rgba(255,255,255,8); color: #e0e0f0;
                border: 1px solid rgba(255,255,255,15); border-radius: 8px;
                padding: 0 10px; font-size: 12px; }
            QLineEdit:focus { border-color: rgba(100,140,255,150); }
        """)
        self._search.returnPressed.connect(self._do_search)
        # Очистка результата поиска, когда поле опустошили
        self._search.textChanged.connect(
            lambda t: self._clear_search() if not t.strip() else None)
        add_btn = QPushButton("Поиск")
        add_btn.setFixedHeight(32)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet("""
            QPushButton { background: rgba(100,140,255,160); color:#fff;
                border:none; border-radius:8px; font-weight:600;
                font-size:12px; padding: 0 12px; }
            QPushButton:hover { background: rgba(100,140,255,230); }
        """)
        add_btn.clicked.connect(self._do_search)
        search_row.addWidget(self._search, 1)
        search_row.addWidget(add_btn)
        content_lay.addLayout(search_row)

        # Результаты поиска (скрыты по умолчанию)
        self._search_result = QLabel("")
        self._search_result.setWordWrap(True)
        self._search_result.setStyleSheet("color: #8888aa; font-size: 11px;")
        self._search_result.hide()
        content_lay.addWidget(self._search_result)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: rgba(255,255,255,10); border:none; max-height:1px;")
        content_lay.addWidget(sep)

        # Входящие заявки
        self._incoming_lbl = QLabel("Входящие заявки")
        self._incoming_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._incoming_lbl.setStyleSheet("color: #f0a040;")
        self._incoming_lbl.hide()
        content_lay.addWidget(self._incoming_lbl)

        self._incoming_list = QWidget()
        self._incoming_list.setLayout(QVBoxLayout())
        self._incoming_list.layout().setContentsMargins(0, 0, 0, 0)
        self._incoming_list.layout().setSpacing(2)
        content_lay.addWidget(self._incoming_list)

        # Исходящие заявки
        self._outgoing_lbl = QLabel("Исходящие заявки")
        self._outgoing_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._outgoing_lbl.setStyleSheet("color: #7888aa;")
        self._outgoing_lbl.hide()
        content_lay.addWidget(self._outgoing_lbl)

        self._outgoing_list = QWidget()
        self._outgoing_list.setLayout(QVBoxLayout())
        self._outgoing_list.layout().setContentsMargins(0, 0, 0, 0)
        self._outgoing_list.layout().setSpacing(2)
        content_lay.addWidget(self._outgoing_list)

        friends_lbl = QLabel("Список друзей")
        friends_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        friends_lbl.setStyleSheet("color: #8888aa;")
        content_lay.addWidget(friends_lbl)

        # Скроллируемый список друзей
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { background: transparent; width: 4px; }
            QScrollBar::handle:vertical { background: #2a2a4a; border-radius: 2px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        self._friends_widget = QWidget()
        self._friends_widget.setStyleSheet("background: transparent;")
        self._friends_layout = QVBoxLayout(self._friends_widget)
        self._friends_layout.setContentsMargins(0, 0, 0, 0)
        self._friends_layout.setSpacing(2)
        self._friends_layout.addStretch()
        scroll.setWidget(self._friends_widget)
        self._friends_scroll = scroll
        content_lay.addWidget(scroll, 1)

        # Индикатор загрузки (пока данные друзей ещё не пришли — вместо «нет друзей»)
        self._loading_lbl = QLabel("Загрузка…")
        self._loading_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_lbl.setStyleSheet("color: #8888aa; font-size: 13px; background: transparent;")
        content_lay.addWidget(self._loading_lbl, 1)
        self._loading_lbl.hide()

        # Пустое состояние — по центру выдвижного окна: картинка + текст
        self._empty_widget = QWidget()
        self._empty_widget.setStyleSheet("background: transparent;")
        empty_lay = QVBoxLayout(self._empty_widget)
        empty_lay.setContentsMargins(0, 0, 0, 0)
        empty_lay.setSpacing(14)
        empty_lay.addStretch(1)

        empty_img = QLabel()
        empty_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        try:
            from ui.assets import mimi_grand
            px = mimi_grand()
            if not px.isNull():
                empty_img.setPixmap(px.scaledToWidth(
                    120, Qt.TransformationMode.SmoothTransformation))
        except Exception:
            pass
        empty_lay.addWidget(empty_img, alignment=Qt.AlignmentFlag.AlignCenter)

        self._empty_lbl = QLabel("У тебя нет друзей...\nДобавьте первого друга!")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet(
            "color: #8888aa; font-size: 13px; font-weight: 600; background: transparent;")
        empty_lay.addWidget(self._empty_lbl, alignment=Qt.AlignmentFlag.AlignCenter)

        empty_lay.addStretch(1)
        content_lay.addWidget(self._empty_widget, 1)

    # ── Data ─────────────────────────────────────────────────────────────────

    def _refresh(self):
        global _prefetch_cache
        if not self._my_uuid:
            return
        if _prefetch_cache is not None:
            log.info("[refresh] using prefetch cache")
            self._on_data(_prefetch_cache)
            _prefetch_cache = None
        # Если ещё ничего не отрисовано (данные не пришли) — показываем индикатор
        # загрузки вместо «нет друзей».
        if getattr(self, "_last_friends", None) is None:
            self._friends_scroll.hide()
            self._empty_widget.hide()
            self._loading_lbl.show()
        log.info("[refresh] fetching friends")
        def _fetch():
            # До 3 попыток: на 401/422 (сессия ещё не установилась после запуска)
            # пересоздаём сессию и повторяем — иначе список не грузился с первого раза.
            for attempt in range(3):
                try:
                    r = requests.get(
                        f"{_config.SERVER_URL}/api/friends",
                        headers=auth_client.session_headers(), timeout=8, verify=_verify())
                    log.info("[refresh] response status=%s (попытка %d)", r.status_code, attempt + 1)
                    if r.status_code in (401, 422) and attempt < 2:
                        auth_client.create_session()
                        continue
                    r.raise_for_status()
                    return r.json()
                except Exception as e:
                    log.error("[refresh] fetch error (попытка %d): %s", attempt + 1, e)
                    if attempt < 2:
                        import time as _t; _t.sleep(1)
                        continue
                    return None
            return None
        loader = _Loader(_fetch, self)
        loader.done.connect(self._on_data)
        loader.start()

    def _on_data(self, data):
        log.info("[on_data] data=%s", data)
        if not data:
            return
        self._loading_lbl.hide()   # данные пришли — снимаем индикатор загрузки
        _update_names(data)
        try:
            self._render_incoming(data.get("incoming", []))
            self._render_outgoing(data.get("outgoing", []))
            self._render_friends(data.get("friends", []))
        except Exception as e:
            log.error("[on_data] render error: %s", e, exc_info=True)

    def _render_incoming(self, incoming: list):
        log.info("[render_incoming] count=%d", len(incoming))
        if getattr(self, "_last_incoming", None) == incoming:
            return
        self._last_incoming = [dict(r) for r in incoming]
        # Жёлтая точка-индикатор: есть входящие заявки в друзья
        try:
            import notifications
            notifications.center().set_requests(bool(incoming))
        except Exception:
            pass
        lay = self._incoming_list.layout()
        while lay.count():
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._incoming_lbl.setVisible(bool(incoming))
        for req in incoming:
            log.debug("[render_incoming] req=%s", req)
            row = IncomingRow(req, self._incoming_list)
            row.accepted.connect(self._accept_request)
            row.declined.connect(self._decline_request)
            lay.addWidget(row)

    def _render_outgoing(self, outgoing: list):
        log.info("[render_outgoing] count=%d", len(outgoing))
        if getattr(self, "_last_outgoing", None) == outgoing:
            return
        self._last_outgoing = [dict(r) for r in outgoing]
        lay = self._outgoing_list.layout()
        while lay.count():
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._outgoing_lbl.setVisible(bool(outgoing))
        for req in outgoing:
            log.debug("[render_outgoing] req=%s", req)
            row = _OutgoingRow(req, self._outgoing_list)
            row.cancelled.connect(self._cancel_request)
            lay.addWidget(row)

    def _render_friends(self, friends: list):
        log.info("[render_friends] count=%d", len(friends))
        if getattr(self, "_last_friends", None) == friends:
            log.debug("[render_friends] data unchanged, skip")
            return
        self._last_friends = [dict(f) for f in friends]
        lay = self._friends_layout
        while lay.count():
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._empty_widget.setVisible(not friends)
        self._friends_scroll.setVisible(bool(friends))
        self._rows = {}   # uuid -> FriendRow (для бейджей непрочитанного)
        for f in friends:
            raw_mode_id = f.get("mode")
            mode_name = self._modes.get(raw_mode_id, raw_mode_id) if raw_mode_id else None
            f = dict(f, mode=mode_name, mode_id=raw_mode_id)
            log.debug("[render_friends] friend=%s", f)
            row = FriendRow(f, self._config_modes, self._friends_widget)
            row.remove_requested.connect(self._remove_friend)
            row.join_requested.connect(self._on_join_requested)
            row.message_requested.connect(self._open_chat)
            self._rows[f["uuid"]] = row
            lay.addWidget(row)
        lay.addStretch()
        # применяем известные счётчики непрочитанного к новым строкам
        for uuid, cnt in (getattr(self, "_unread_map", None) or {}).items():
            if uuid in self._rows:
                self._rows[uuid].set_unread(cnt)

    def set_unread_map(self, counts: dict):
        """Обновляет бейджи непрочитанного на строках друзей."""
        self._unread_map = dict(counts or {})
        for uuid, row in (getattr(self, "_rows", None) or {}).items():
            row.set_unread(self._unread_map.get(uuid, 0))

    def friend_name(self, uuid: str) -> str | None:
        return _names_cache.get(uuid)

    # Actions

    def _do_search(self):
        q = self._search.text().strip()
        if len(q) < 2:
            self._search_result.setText("Введите минимум 2 символа")
            self._search_result.show()
            return
        self._search_result.setText("Поиск...")
        self._search_result.show()

        def _fetch():
            try:
                r = requests.get(
                    f"{_config.SERVER_URL}/api/player/search",
                    params={"q": q}, headers=auth_client.session_headers(),
                    timeout=6, verify=_verify())
                r.raise_for_status()
                return r.json()
            except Exception:
                return None

        loader = _Loader(_fetch, self)
        loader.done.connect(self._on_search_result)
        loader.start()

    def _on_search_result(self, results):
        # Удалить старую карточку результата если была
        if hasattr(self, "_search_card") and self._search_card:
            self._search_card.deleteLater()
            self._search_card = None

        if results is None:
            self._search_result.setText("Ошибка поиска")
            self._search_result.show()
            return
        if not results:
            self._search_result.setText("Игрок не найден")
            self._search_result.show()
            return

        player = results[0]
        uuid = player["uuid"]
        name = player.get("username") or "Unknown"
        if uuid == self._my_uuid:
            self._search_result.setText("Это вы")
            self._search_result.show()
            return

        self._search_result.hide()

        # Карточка игрока
        card = QFrame()
        card.setStyleSheet("""
            QFrame { background: rgba(255,255,255,6);
                border: 1px solid rgba(255,255,255,14);
                border-radius: 10px; }
        """)
        card.setFixedHeight(52)
        card_lay = QHBoxLayout(card)
        card_lay.setContentsMargins(10, 6, 10, 6)
        card_lay.setSpacing(10)

        # Голова
        avatar = QLabel()
        avatar.setFixedSize(36, 36)
        avatar.setStyleSheet("background: #1a1a2e; border-radius: 6px; border: none;")
        card_lay.addWidget(avatar)

        def _load_avatar():
            px = _head_pixmap(name, 36)
            if px:
                avatar.setPixmap(px)
            else:
                def _fetch_av():
                    from config import CACHE_DIR
                    path = CACHE_DIR / f"head_{name}.png"
                    if not path.exists():
                        try:
                            import requests as _req
                            r = _req.get(f"https://mc-heads.net/avatar/{name}/64", timeout=6)
                            r.raise_for_status()
                            path.write_bytes(r.content)
                        except Exception:
                            return None
                    return _head_pixmap(name, 36)
                ldr = _Loader(_fetch_av, card)
                ldr.done.connect(lambda px: avatar.setPixmap(px) if px else None)
                ldr.start()

        _load_avatar()

        # Ник
        name_lbl = QLabel(name)
        name_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        name_lbl.setStyleSheet("color: #e0e0f0; background: transparent; border: none;")
        card_lay.addWidget(name_lbl, 1)

        # Что показывать справа зависит от текущей связи с игроком
        rel = self._relationship(uuid)
        if rel in ("friend", "outgoing"):
            # Уже друг / заявка уже отправлена — не даём отправить повторно
            status = QLabel("В друзьях" if rel == "friend" else "Заявка отправлена")
            status.setStyleSheet(
                "color: %s; background: transparent; border: none; font-size: 11px; font-weight: 600;"
                % ("#4caf50" if rel == "friend" else "#8888aa")
            )
            card_lay.addWidget(status)
        else:
            # rel == "incoming" (встречная — клик авто-примет) или None (новая заявка)
            from ui.assets import svg_icon as _svg
            add_btn = QPushButton()
            add_btn.setFixedSize(32, 32)
            add_btn.setIcon(_svg("plus_small.svg", "#ffffff", 16))
            add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            add_btn.setToolTip("Принять заявку" if rel == "incoming" else "Добавить в друзья")
            add_btn.setStyleSheet("""
                QPushButton { background: rgba(76,175,80,160);
                    border:none; border-radius:8px; }
                QPushButton:hover { background: rgba(76,175,80,230); }
                QPushButton:disabled { background: rgba(60,60,80,120); }
            """)

            def _send():
                add_btn.setEnabled(False)
                add_btn.setIcon(_svg("plus_small.svg", "#555555", 16))
                def _done(msg):
                    add_btn.setIcon(_svg("plus.svg", "#4caf50", 16))
                    self._search_result.setText(msg)
                    self._search_result.show()
                    # Заявка отправлена — карточка сама убирается через пару секунд
                    QTimer.singleShot(2000, self._clear_search)
                self._send_request(uuid, on_done=_done)

            add_btn.clicked.connect(_send)
            card_lay.addWidget(add_btn)

        self._search_card = card
        # Вставляем сразу после строки поиска (index 1 в content_lay)
        self._content_widget.layout().insertWidget(1, card)

    def _relationship(self, uuid: str) -> str | None:
        """Текущая связь с игроком по uuid: 'friend' | 'outgoing' | 'incoming' | None.
        Использует последние данные /api/friends (друзья, исходящие, входящие)."""
        for f in (getattr(self, "_last_friends", None) or []):
            if f.get("uuid") == uuid:
                return "friend"
        for r in (getattr(self, "_last_outgoing", None) or []):
            if r.get("uuid") == uuid:
                return "outgoing"
        for r in (getattr(self, "_last_incoming", None) or []):
            if r.get("uuid") == uuid:
                return "incoming"
        return None

    def _clear_search(self):
        """Убирает карточку результата поиска и текст-статус."""
        if getattr(self, "_search_card", None):
            self._search_card.deleteLater()
            self._search_card = None
        self._search_result.hide()
        self._search_result.clear()

    def _send_request(self, to_uuid: str, on_done=None):
        def _post():
            try:
                r = requests.post(
                    f"{_config.SERVER_URL}/api/friends/request",
                    params={"to_uuid": to_uuid},
                    headers=auth_client.session_headers(),
                    timeout=6, verify=_verify())
                return (r.status_code, r.json() if r.content else {})
            except Exception:
                return (None, {})

        def _on_result(result):
            code, body = result
            if code == 200:
                auto = body.get("auto_accepted")
                msg = "Вы теперь друзья ✓" if auto else "Заявка отправлена ✓"
            elif code == 409:
                msg = body.get("detail", "Заявка уже существует")
            elif code == 403:
                msg = body.get("detail", "Нет доступа")
            elif code == 404:
                msg = "Игрок не найден"
            else:
                msg = "Ошибка отправки"
            if on_done:
                on_done(msg)
            else:
                self._search_result.setText(msg)
                self._search_result.show()
            if code == 200:
                QTimer.singleShot(800, self._refresh)

        loader = _Loader(_post, self)
        loader.done.connect(_on_result)
        loader.start()

    def _accept_request(self, from_uuid: str):
        def _post():
            requests.post(
                f"{_config.SERVER_URL}/api/friends/accept",
                params={"from_uuid": from_uuid},
                headers=auth_client.session_headers(),
                timeout=6, verify=_verify())
        threading.Thread(target=_post, daemon=True).start()
        QTimer.singleShot(500, self._refresh)

    def _decline_request(self, from_uuid: str):
        def _del():
            requests.delete(
                f"{_config.SERVER_URL}/api/friends/remove",
                params={"other_uuid": from_uuid},
                headers=auth_client.session_headers(),
                timeout=6, verify=_verify())
        threading.Thread(target=_del, daemon=True).start()
        QTimer.singleShot(500, self._refresh)

    def _cancel_request(self, to_uuid: str):
        def _del():
            requests.delete(
                f"{_config.SERVER_URL}/api/friends/remove",
                params={"other_uuid": to_uuid},
                headers=auth_client.session_headers(),
                timeout=6, verify=_verify())
        threading.Thread(target=_del, daemon=True).start()
        QTimer.singleShot(500, self._refresh)

    def _on_join_requested(self, mode_id: str, server_ip: str):
        from PyQt6.QtWidgets import QMessageBox
        from downloader import _load_installed
        # Режим не существует в конфиге лаунчера
        if mode_id not in self._modes:
            QMessageBox.warning(
                self,
                "Неизвестная игра",
                f"Игрок играет в режим «{mode_id}», которого нет в вашем лаунчере.\n"
                "Обратитесь к администрации.",
                QMessageBox.StandardButton.Ok,
            )
            return
        # Режим есть но не установлен
        if mode_id not in _load_installed():
            mode_name = self._modes.get(mode_id, mode_id)
            reply = QMessageBox.question(
                self,
                "Сборка не установлена",
                f"У вас не установлена сборка «{mode_name}».\nУстановить сейчас?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.join_game.emit(mode_id, "")
        else:
            self.join_game.emit(mode_id, server_ip)

    def _remove_friend(self, other_uuid: str):
        def _del():
            requests.delete(
                f"{_config.SERVER_URL}/api/friends/remove",
                params={"other_uuid": other_uuid},
                headers=auth_client.session_headers(),
                timeout=6, verify=_verify())
        threading.Thread(target=_del, daemon=True).start()
        QTimer.singleShot(500, self._refresh)

    def _open_chat(self, uuid: str, username: str):
        """Открывает (или поднимает) окно переписки с другом."""
        win = self._chats.get(uuid)
        if win is not None:
            win.showNormal(); win.raise_(); win.activateWindow()
        else:
            from ui.chat_window import ChatWindow
            online = False
            for f in (getattr(self, "_last_friends", None) or []):
                if f.get("uuid") == uuid:
                    online = bool(f.get("online"))
                    break
            win = ChatWindow(uuid, username, online, self.window())
            win.closed.connect(lambda u: self._chats.pop(u, None))
            self._chats[uuid] = win
            win.show()
            win.raise_()
            win.activateWindow()
        # окно на открытии метит входящие прочитанными — обновим индикатор/бейджи
        w = self.window()
        fn = getattr(w, "refresh_chat_unread", None)
        if fn:
            QTimer.singleShot(1000, fn)

    def refresh_open_chats(self):
        """Перечитать историю во всех открытых окнах (по SSE message/read)."""
        for win in list(self._chats.values()):
            try:
                win.refresh()
            except Exception:
                pass


class FriendsDrawer(QWidget):
    """Выдвижная панель друзей — дочерний виджет поверх лаунчера."""
    join_game = pyqtSignal(str, str)  # mode_id, server_ip

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("FriendsDrawer { background-color: #0a0d14; border-left: 1px solid rgba(255,255,255,18); }")
        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._on_anim_done)
        self._closing = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._panel = FriendsPanel(self)
        self._panel.join_game.connect(self.join_game)
        lay.addWidget(self._panel)

    def set_modes(self, modes: list):
        self._panel.set_modes(modes)

    def notify_friends_updated(self):
        self._panel.notify_friends_updated()

    def refresh_discord_state(self):
        self._panel.refresh_discord_state()

    def refresh_open_chats(self):
        self._panel.refresh_open_chats()

    def set_unread_map(self, counts: dict):
        self._panel.set_unread_map(counts)

    def friend_name(self, uuid: str):
        return self._panel.friend_name(uuid)

    def open_chat(self, uuid: str, username: str):
        self._panel._open_chat(uuid, username)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(10, 13, 20))
        p.setPen(QColor(255, 255, 255, 18))
        p.drawLine(0, 0, 0, self.height())

    def open_drawer(self, top_h: int, win_w: int, win_h: int):
        self._closing = False
        # Инициализируем uuid ДО show() чтобы showEvent не запускал refresh
        settings = auth_client._load_settings()
        raw = settings.get("uuid", "")
        s = raw.replace("-", "")
        self._panel._my_uuid = f"{s[:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:]}" if len(s) == 32 else raw
        has_discord = bool(settings.get("discord_id"))
        self._panel._no_discord_widget.setVisible(not has_discord)
        self._panel._content_widget.setVisible(has_discord)

        h = win_h - top_h
        hidden = QRect(win_w, top_h, DRAWER_W, h)
        shown  = QRect(win_w - DRAWER_W, top_h, DRAWER_W, h)
        self.setGeometry(hidden)
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setStartValue(hidden)
        self._anim.setEndValue(shown)
        self._anim.start()

        if self._panel._my_uuid and has_discord:
            # НЕ чистим кэш: строки с прошлого открытия уже нарисованы → показываем
            # мгновенно, а _refresh в фоне обновит их ТОЛЬКО при изменении данных
            # (без «дудоса» и мигания). Фоновые обновления при закрытой панели —
            # только индикатор, поэтому пустых заголовков больше не будет.
            self._panel._refresh()
            self._panel._poll_timer.start()

    def close_drawer(self):
        self._closing = True
        r = self.geometry()
        win_w = self.parent().width() if self.parent() else r.right()
        off = QRect(win_w, r.y(), DRAWER_W, r.height())
        self._anim.stop()
        self._anim.setStartValue(r)
        self._anim.setEndValue(off)
        self._anim.start()
        self._panel._poll_timer.stop()

    def _on_anim_done(self):
        if self._closing:
            self.hide()

    def reposition(self, top_h: int, win_w: int, win_h: int):
        if self.isVisible() and not self._closing:
            self.setGeometry(win_w - DRAWER_W, top_h, DRAWER_W, win_h - top_h)
