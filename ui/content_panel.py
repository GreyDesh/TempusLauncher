from PyQt6.QtCore import (
    Qt, pyqtSignal, QPropertyAnimation, QEasingCurve,
    QParallelAnimationGroup, QThread, pyqtSlot, QTimer, QUrl,
    QRunnable, QThreadPool, QObject, QRect, QSize, QPoint, QEvent, QBuffer, QIODevice
)
from PyQt6.QtGui import (
    QPixmap, QFont, QColor, QPainter, QLinearGradient,
    QPainterPath, QBrush, QPen, QFontMetrics, QFontDatabase, QImage
)

def _load_minecraft_font() -> str:
    import asset_pack
    from PyQt6.QtCore import QByteArray
    data = asset_pack.read("assets/MinecraftTen.ttf")
    if data:
        fid = QFontDatabase.addApplicationFontFromData(QByteArray(data))
    else:
        fid = -1
    families = QFontDatabase.applicationFontFamilies(fid)
    return families[0] if families else "Rubik"

_MINECRAFT_FONT = None
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QStackedWidget,
    QScrollArea, QFrame, QProgressBar, QSizePolicy, QGraphicsOpacityEffect, QPushButton,
    QLayout, QDialog, QPlainTextEdit
)
try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PyQt6.QtMultimediaWidgets import QVideoWidget
    _VIDEO_SUPPORTED = True
except ImportError:
    _VIDEO_SUPPORTED = False
from assets_cache import AssetCache
from downloader import is_installed, needs_update, install_mode
from config import ANIM_NORMAL, CACHE_DIR
from ui.glow_button import GlowButton, SecondaryButton, SplitGlowButton


class InstallWorker(QThread):
    progress = pyqtSignal(str, float)
    done = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, mode: dict, launcher_config: dict):
        super().__init__()
        self._mode = mode
        self._config = launcher_config

    def run(self):
        try:
            install_mode(self._mode, lambda msg, frac: self.progress.emit(msg, frac), self._config)
            self.done.emit()
        except Exception as e:
            self.error.emit(str(e))


class _VideoGradientOverlay(QWidget):
    """Прозрачный виджет поверх видео — рисует градиент как у HeroBanner."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        p = QPainter(self)
        grad = QLinearGradient(0, h * 0.35, 0, h)
        grad.setColorAt(0.0, QColor(10, 13, 18, 0))
        grad.setColorAt(0.6, QColor(10, 13, 18, 160))
        grad.setColorAt(1.0, QColor(10, 13, 18, 255))
        p.fillRect(0, 0, w, h, grad)
        for x0, x1 in ((0, w * 0.25), (w, w * 0.75)):
            sg = QLinearGradient(x0, 0, x1, 0)
            sg.setColorAt(0, QColor(10, 13, 18, 120))
            sg.setColorAt(1, QColor(10, 13, 18, 0))
            p.fillRect(0, 0, w, h, sg)


# ── Banner container (баннер + видео) ────────────────────────────────────────

class _BadgeTooltip(QWidget):
    def __init__(self, text: str, parent=None):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._text = text
        self._alpha = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._target = 0.0
        self.hide()

    def show_tip(self):
        self._target = 1.0
        self.show()
        self.raise_()
        self._timer.start()

    def hide_tip(self):
        self._target = 0.0
        self._timer.start()

    def _tick(self):
        speed = 0.1
        self._alpha += (self._target - self._alpha) * speed
        if abs(self._alpha - self._target) < 0.01:
            self._alpha = self._target
            self._timer.stop()
            if self._alpha <= 0:
                self.hide()
        self.update()

    def paintEvent(self, _):
        if self._alpha <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self._alpha)
        w, h = self.width(), self.height()
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, 6, 6)
        p.fillPath(path, QColor(18, 22, 30, 230))
        pen = QPen(QColor(255, 255, 255, 30))
        pen.setWidth(1)
        p.setPen(pen)
        p.drawPath(path)
        p.setPen(QColor(200, 210, 225))
        p.setFont(QFont("Segoe UI", 10))
        p.drawText(self.rect().adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter, self._text)


class _Badge(QLabel):
    _BADGE_SIZE = 36
    _ICON_SIZE  = 20

    def __init__(self, svg: str, color: str, tooltip_text: str, fallback: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(self._BADGE_SIZE, self._BADGE_SIZE)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "background: rgba(0,0,0,150); border-radius: 8px;"
            "border: 1px solid rgba(255,255,255,25);"
        )
        try:
            from ui.assets import svg_icon as _svg
            self.setPixmap(_svg(svg, color, self._ICON_SIZE).pixmap(self._ICON_SIZE, self._ICON_SIZE))
        except Exception:
            self.setText(fallback or "●")

        self._tip = _BadgeTooltip(tooltip_text, parent)
        self._tip.hide()
        self._update_tip_size(tooltip_text)

    def _update_tip_size(self, text: str):
        fm = QFontMetrics(QFont("Segoe UI", 10))
        lines = text.split("\n")
        tw = max(fm.horizontalAdvance(l) for l in lines)
        th = fm.height() * len(lines)
        self._tip.setFixedSize(tw + 24, th + 14)

    def _reposition_tip(self):
        tip_w = self._tip.width()
        tip_h = self._tip.height()
        global_center = self.mapToGlobal(self.rect().center())
        x = global_center.x() - tip_w // 2
        y = global_center.y() + self.height() // 2 + 6
        self._tip.move(x, y)

    def enterEvent(self, e):
        self._reposition_tip()
        self._tip.show_tip()

    def leaveEvent(self, e):
        self._tip.hide_tip()


class BannerContainer(QWidget):
    """Баннер с поддержкой видео через QVideoSink — кадры рисуются в paintEvent."""

    def __init__(self, mode_id: str, parent=None):
        super().__init__(parent)
        self._mode_id = mode_id
        self._video_path: str | None = None
        self._player = None
        self._current_frame: QPixmap | None = None
        self._video_alpha: float = 0.0   # 0 = только баннер, 1 = только видео
        self._fade_timer: QTimer | None = None
        self._video_enabled = self._load_pref()
        self._banner = HeroBanner(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Кнопка — обычный Qt виджет, всегда поверх т.к. paintEvent не перекрывает
        self._toggle_btn = QPushButton("▶", self)
        self._toggle_btn.setFixedSize(44, 28)
        self._toggle_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0,0,0,160); color: #fff;
                border: 1px solid rgba(255,255,255,60);
                border-radius: 6px; font-size: 13px;
                font-family: 'Segoe UI'; font-weight: 700;
                padding: 0 6px;
            }
            QPushButton:hover { background: rgba(0,0,0,230); }
        """)
        self._title_px: QPixmap | None = None
        self._name: str = ""
        self._badges: list = []
        self._toggle_btn.hide()
        self._toggle_btn.clicked.connect(self._on_toggle)

    def add_badge(self, svg: str, color: str, size: int, tooltip: str, fallback: str = ""):
        badge = _Badge(svg, color, tooltip, fallback, self)
        self._badges.append(badge)
        badge.show()
        badge.raise_()
        self._reposition_badges()

    def set_connector(self, show: bool):
        if show:
            self.add_badge(
                "network_cloud_computer.svg", "#7BAEFF", 20,
                "В этом режиме можно легко подключатся\nи играть со своими друзьям на сервер.",
                "🌐",
            )

    def set_mod_protection(self, strict: bool):
        if strict:
            self.add_badge(
                "lock.svg", "#7BAEFF", 20,
                "Любое изменение игровых файлов модов невозможно.",
                "🔒",
            )

    def set_hidden(self, hidden: bool):
        if hidden:
            self.add_badge(
                "incognito.svg", "#7BAEFF", 20,
                "Скрытый режим — виден только по роли Discord.",
                "🕵️",
            )

    def set_required_role(self, role_id: str, role_name: str = ""):
        if role_id:
            tip = (f"Для игры нужна роль «{role_name}» на нашем Discord-сервере."
                   if role_name else "Для игры нужна особая роль на нашем Discord-сервере.")
            self.add_badge("membership_vip.svg", "#7BAEFF", 20, tip, "🎫")

    def _reposition_badges(self):
        x = self.width() - 36 - 10
        y = 10
        for badge in self._badges:
            badge.move(x, y)
            badge.raise_()
            x -= 36 + 6

    def resizeEvent(self, e):
        self._banner.resize(self.size())
        self._toggle_btn.move(
            self.width() - self._toggle_btn.width() - 10,
            self.height() - self._toggle_btn.height() - 10,
        )
        self._toggle_btn.raise_()
        self._reposition_badges()

    def banner(self) -> "HeroBanner":
        return self._banner

    def set_title_logo(self, px: QPixmap | None):
        self._title_px = px
        self._banner.set_title_logo(px)
        self.update()

    def set_mode_name(self, name: str):
        self._name = name
        self.update()

    def paintEvent(self, _):
        if self._video_alpha <= 0 or self._current_frame is None:
            return  # баннер рисует себя сам
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setOpacity(self._video_alpha)
        # Масштаб с сохранением пропорций, заполняем весь виджет
        scaled = self._current_frame.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                             Qt.TransformationMode.SmoothTransformation)
        x = (w - scaled.width()) // 2
        y = (h - scaled.height()) // 2
        p.drawPixmap(x, y, scaled)
        p.setOpacity(self._video_alpha)
        # Градиент снизу как у баннера
        grad = QLinearGradient(0, h * 0.35, 0, h)
        grad.setColorAt(0.0, QColor(10, 13, 18, 0))
        grad.setColorAt(0.6, QColor(10, 13, 18, 160))
        grad.setColorAt(1.0, QColor(10, 13, 18, 255))
        p.setOpacity(1.0)
        p.fillRect(0, 0, w, h, grad)
        for x0, x1 in ((0, w * 0.25), (w, w * 0.75)):
            sg = QLinearGradient(x0, 0, x1, 0)
            sg.setColorAt(0, QColor(10, 13, 18, 120))
            sg.setColorAt(1, QColor(10, 13, 18, 0))
            p.fillRect(0, 0, w, h, sg)
        if self._title_px and not self._title_px.isNull():
            logo_h = 208
            logo_px = self._title_px.scaledToHeight(logo_h, Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(12, h - logo_h + 20, logo_px)
        elif self._name:
            p.setFont(QFont("Rubik", 56, QFont.Weight.Bold))
            p.setPen(QColor(230, 237, 243))
            p.drawText(24, h - 22, self._name)

    def _set_alpha(self, alpha: float):
        self._video_alpha = alpha
        if alpha >= 0.99:
            self._banner.setVisible(False)
        elif alpha <= 0:
            self._banner.setGraphicsEffect(None)
            self._banner.setVisible(True)
        else:
            self._banner.setVisible(True)
            fx = self._banner.graphicsEffect()
            if not isinstance(fx, QGraphicsOpacityEffect):
                fx = QGraphicsOpacityEffect(self._banner)
                self._banner.setGraphicsEffect(fx)
            fx.setOpacity(max(0.0, 1.0 - alpha))
        self.update()

    def _animate_alpha(self, target: float, duration: int, on_done=None):
        if self._fade_timer:
            self._fade_timer.stop()
        start = self._video_alpha
        steps = max(1, duration // 16)
        step = [0]

        def _tick():
            step[0] += 1
            t = step[0] / steps
            self._set_alpha(start + (target - start) * t)
            if step[0] >= steps:
                self._fade_timer.stop()
                self._set_alpha(target)
                if on_done:
                    on_done()

        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(16)
        self._fade_timer.timeout.connect(_tick)
        self._fade_timer.start()

    def start_video(self, video_url: str):
        if not _VIDEO_SUPPORTED or not video_url:
            return
        import hashlib, threading
        ext = video_url.split("?")[0].rsplit(".", 1)[-1]
        if ext not in ("mp4", "webm", "mov"):
            ext = "mp4"
        cache_path = CACHE_DIR / f"{hashlib.md5(video_url.encode()).hexdigest()}.{ext}"
        self._video_path = str(cache_path)
        if cache_path.exists():
            QTimer.singleShot(3000, self._activate_video)
        else:
            threading.Thread(target=self._download_video, args=(video_url, cache_path), daemon=True).start()

    def _download_video(self, url: str, path):
        try:
            import requests
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(url, stream=True, timeout=120, headers=headers, allow_redirects=True)
            r.raise_for_status()
            ct = r.headers.get("content-type", "")
            if "text/html" in ct or "application/json" in ct:
                return
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
            QTimer.singleShot(0, self._activate_video)
        except Exception:
            pass

    def _activate_video(self):
        if not self._video_path or not _VIDEO_SUPPORTED:
            return
        self._toggle_btn.setText("■" if self._video_enabled else "▶")
        self._toggle_btn.show()
        self._toggle_btn.raise_()
        if self._video_enabled:
            self._play_video()

    def _play_video(self):
        if not _VIDEO_SUPPORTED or not self._video_path:
            return
        self._fade_started = False
        if not self._player:
            from PyQt6.QtMultimedia import QVideoSink, QVideoFrame
            self._sink = QVideoSink(self)
            self._player = QMediaPlayer(self)
            self._audio = QAudioOutput(self)
            self._audio.setVolume(0)
            self._player.setAudioOutput(self._audio)
            self._player.setVideoSink(self._sink)
            self._sink.videoFrameChanged.connect(self._on_frame)
            self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.setSource(QUrl.fromLocalFile(self._video_path))
        self._player.play()

    def _on_frame(self, frame):
        img = frame.toImage()
        if not img.isNull():
            self._current_frame = QPixmap.fromImage(img)
            self.update()
            if not getattr(self, '_fade_started', False):
                self._fade_started = True
                self._animate_alpha(1.0, 600)

    def _on_media_status(self, status):
        if _VIDEO_SUPPORTED and status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._player.setPosition(0)
            self._player.play()

    def _on_toggle(self):
        self._video_enabled = not self._video_enabled
        self._save_pref(self._video_enabled)
        self._toggle_btn.setText("■" if self._video_enabled else "▶")
        if self._video_enabled:
            self._play_video()
        else:
            def _after():
                if self._player:
                    self._player.stop()
                self._current_frame = None
                self._banner.setGraphicsEffect(None)
                self._banner.setVisible(True)
            self._animate_alpha(0.0, 500, on_done=_after)

    def pause(self):
        if not self._player:
            return
        from PyQt6.QtMultimedia import QMediaPlayer as _QMP
        if self._player.playbackState() == _QMP.PlaybackState.PlayingState:
            self._player.pause()

    def resume(self):
        if not self._player or not self._video_enabled or not self._video_path:
            return
        from PyQt6.QtMultimedia import QMediaPlayer as _QMP
        if self._player.playbackState() == _QMP.PlaybackState.PausedState:
            self._player.play()

    def stop(self):
        if self._player:
            self._animate_alpha(0.0, 300, on_done=lambda: self._player.stop() if self._player else None)

    def _pref_key(self):
        return "video_enabled"

    def _load_pref(self) -> bool:
        try:
            import json
            from config import SETTINGS_FILE
            d = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            return d.get(self._pref_key(), True)
        except Exception:
            return True

    def _save_pref(self, val: bool):
        try:
            import json
            from config import SETTINGS_FILE
            d = json.loads(SETTINGS_FILE.read_text(encoding="utf-8")) if SETTINGS_FILE.exists() else {}
            d[self._pref_key()] = val
            SETTINGS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


# ── Hero banner ───────────────────────────────────────────────────────────────

class HeroBanner(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._px: QPixmap | None = None
        self._title_px: QPixmap | None = None
        self._name: str = ""
        self._version: str = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_image(self, px: QPixmap):
        self._px = px
        self.update()

    def set_title_logo(self, px: QPixmap | None):
        self._title_px = px
        self.update()

    def set_mode_info(self, name: str, version: str):
        self._name = name
        self._version = version
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        bg = QColor(10, 13, 18)

        p.fillRect(0, 0, w, h, bg)

        if self._px:
            # Масштабируем по высоте, сохраняем пропорции
            scaled = self._px.scaledToHeight(h, Qt.TransformationMode.SmoothTransformation)
            # Если по ширине не хватает — масштабируем по ширине
            if scaled.width() < w:
                scaled = self._px.scaledToWidth(w, Qt.TransformationMode.SmoothTransformation)
            # Центрируем
            x = (w - scaled.width()) // 2
            y = (h - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)

        # Градиент снизу — плавное растворение в фон
        grad = QLinearGradient(0, h * 0.35, 0, h)
        grad.setColorAt(0.0, QColor(10, 13, 18, 0))
        grad.setColorAt(0.6, QColor(10, 13, 18, 160))
        grad.setColorAt(1.0, QColor(10, 13, 18, 255))
        p.fillRect(0, 0, w, h, grad)

        # Лёгкий градиент по бокам
        for x0, x1 in ((0, w * 0.25), (w, w * 0.75)):
            sg = QLinearGradient(x0, 0, x1, 0)
            sg.setColorAt(0, QColor(10, 13, 18, 120))
            sg.setColorAt(1, QColor(10, 13, 18, 0))
            p.fillRect(0, 0, w, h, sg)

        # Название режима (логотип или текст)
        if self._title_px and not self._title_px.isNull():
            logo_h = 208
            logo_px = self._title_px.scaledToHeight(logo_h, Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(12, h - logo_h + 20, logo_px)
        elif self._name:
            global _MINECRAFT_FONT
            if _MINECRAFT_FONT is None:
                _MINECRAFT_FONT = _load_minecraft_font()
            p.setFont(QFont("Rubik", 56, QFont.Weight.Bold))
            p.setPen(QColor(230, 237, 243))
            p.drawText(24, h - 22, self._name)



# ── StatBlock — колонка статистики ────────────────────────────────────────────

class StatBlock(QWidget):
    def __init__(self, icon: str, label: str, value: str, color: str = "#E6EDF3", svg: str = "", url: str = "", parent=None):
        super().__init__(parent)
        self._icon = icon
        self._label = label
        self._value = value
        self._color = QColor(color)
        self._url = url
        self._hover = False
        self._svg_px = None
        if svg:
            try:
                from ui.assets import svg_icon as _svg
                self._svg_px = _svg(svg, color, 14).pixmap(14, 14)
            except Exception:
                pass
        self.setMinimumWidth(80)
        if url:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, e):
        if self._url:
            self._hover = True
            self.update()

    def leaveEvent(self, e):
        if self._url:
            self._hover = False
            self.update()

    def mousePressEvent(self, e):
        if self._url and e.button() == Qt.MouseButton.LeftButton:
            import webbrowser
            webbrowser.open(self._url)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Иконка + лейбл в одну строку
        if self._svg_px and not self._svg_px.isNull():
            icon_w = 18
            p.drawPixmap(0, 3, self._svg_px)
        else:
            icon_font = QFont("Segoe UI Emoji", 11)
            p.setFont(icon_font)
            fm_icon = p.fontMetrics()
            icon_w = fm_icon.horizontalAdvance(self._icon) + 4
            p.setPen(QColor(125, 133, 144))
            p.drawText(0, 0, icon_w, 20, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._icon)

        p.setFont(QFont("Rubik", 10))
        p.setPen(QColor(74, 82, 96))
        p.drawText(icon_w, 0, w - icon_w, 20, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)

        # Значение
        value_color = QColor(200, 210, 220) if not self._hover else QColor(230, 237, 243)
        p.setFont(QFont("Rubik", 13, QFont.Weight.Bold))
        p.setPen(value_color)
        p.drawText(0, 22, w, 20, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._value)

        # Подчёркивание при hover (цвет акцента блока)
        if self._hover:
            fm = p.fontMetrics()
            text_w = min(fm.horizontalAdvance(self._value), w)
            p.setPen(self._color.lighter(130) if self._url else value_color)
            p.drawLine(0, 40, text_w, 40)

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(100, 44)


# ── RoleBlockedView ───────────────────────────────────────────────────────────

class RoleBlockedView(QWidget):
    """Экран 'нет доступа' — картинка фоном справа, текст слева."""
    link_discord_requested = pyqtSignal()
    recheck_requested = pyqtSignal()

    def __init__(self, mode: dict, reason: str, launcher_config: dict = None, parent=None):
        super().__init__(parent)
        self._mode = mode
        self._launcher_config = launcher_config or {}
        self._px = QPixmap()
        self._logo_px = QPixmap()
        from ui.assets import not_discord, not_role_pig
        self._px = not_discord() if reason == "not_linked" else not_role_pig()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._build_ui(reason)
        # Загружаем логотип режима
        logo_url = mode.get("logo_url", "")
        if logo_url:
            AssetCache.load(logo_url, self._on_logo)

    def _on_logo(self, _url: str, px: QPixmap):
        self._logo_px = px
        if self._logo_lbl and not px.isNull():
            self._logo_lbl.setPixmap(px.scaledToHeight(80, Qt.TransformationMode.SmoothTransformation))

    def _build_ui(self, reason: str):
        root = QVBoxLayout(self)
        root.setContentsMargins(52, 48, 0, 40)
        root.setSpacing(0)

        s = "background: transparent;"

        # ── Логотип + название режима ─────────────────────────────────────────
        name_row = QHBoxLayout()
        name_row.setSpacing(14)
        name_row.setContentsMargins(0, 0, 0, 0)

        # ВАЖНО: логотип создаём СРАЗУ с родителем (self) и НЕ вызываем show() до
        # добавления в layout — иначе parentless-виджет на миг всплывает отдельным
        # top-level окном по центру экрана (мелькающее «маленькое окно»).
        logo_url = self._mode.get("logo_url", "")
        self._logo_lbl = QLabel(self)
        self._logo_lbl.setFixedSize(80, 80)
        self._logo_lbl.setScaledContents(True)
        self._logo_lbl.setStyleSheet(s)

        name_lbl = QLabel(self._mode.get("name", ""))
        name_lbl.setStyleSheet(f"color: #E6EDF3; font-size: 48px; font-weight: 800; font-family: 'Segoe UI'; {s}")
        name_lbl.setWordWrap(False)

        name_row.addWidget(self._logo_lbl)
        name_row.addWidget(name_lbl)
        name_row.addStretch()
        self._logo_lbl.setVisible(bool(logo_url))

        root.addLayout(name_row)
        root.addSpacing(36)

        if reason == "not_linked":
            title_txt = "Привяжите Discord"
            desc_txt  = (
                "Этот режим доступен только участникам\n"
                "нашего Discord-сервера.\n\n"
                "Чтобы получить доступ привяжите\n"
                "Discord к аккаунту Minecraft."
            )
            dc_url = ""
        else:
            title_txt = "Нет необходимой роли"
            role_name = self._mode.get("required_discord_role_name", "участника")
            desc_txt  = (
                f"Для игры в этом режиме необходима\n"
                f"роль «{role_name}» на нашем Discord-сервере.\n\n"
                "Вступите в Discord-сервер сообщества\n"
                "и получите роль участника."
            )
            dc_url = self._launcher_config.get("social", {}).get("discord", "")

        # Заголовок с замком
        lock_row = QHBoxLayout()
        lock_row.setSpacing(10)
        lock_row.setContentsMargins(0, 0, 0, 0)
        lock_icon = QLabel("🔒")
        lock_icon.setStyleSheet(f"font-size: 26px; {s}")
        title_lbl = QLabel(title_txt)
        title_lbl.setStyleSheet(f"color: #E6EDF3; font-size: 28px; font-weight: 800; font-family: 'Segoe UI'; {s}")
        lock_row.addWidget(lock_icon)
        lock_row.addWidget(title_lbl)
        lock_row.addStretch()
        root.addLayout(lock_row)
        root.addSpacing(18)

        desc_lbl = QLabel(desc_txt)
        desc_lbl.setStyleSheet(f"color: #b0b8c4; font-size: 16px; line-height: 1.6; {s}")
        desc_lbl.setWordWrap(True)
        root.addWidget(desc_lbl)
        root.addSpacing(28)

        from PyQt6.QtGui import QIcon
        from PyQt6.QtCore import QSize
        from ui.assets import svg_icon as _svg_a
        _dc_qicon = _svg_a("discord.svg", "#ffffff", 20)
        if dc_url:
            dc_btn = QPushButton(" Discord сервер")
            dc_btn.setFixedSize(220, 44)
            dc_btn.setStyleSheet("""
                QPushButton {
                    background: #5865F2; color: #fff; border: none;
                    border-radius: 10px; font-size: 14px; font-weight: 700;
                }
                QPushButton:hover { background: #7983f5; }
            """)
            dc_btn.setIcon(_dc_qicon)
            dc_btn.setIconSize(QSize(20, 20))
            dc_btn.clicked.connect(lambda: __import__('webbrowser').open(dc_url))
            root.addWidget(dc_btn)
        elif reason == "not_linked":
            link_btn = QPushButton(" Привязать Discord")
            link_btn.setFixedSize(220, 44)
            link_btn.setStyleSheet("""
                QPushButton {
                    background: #5865F2; color: #fff; border: none;
                    border-radius: 10px; font-size: 14px; font-weight: 700;
                }
                QPushButton:hover { background: #7983f5; }
            """)
            link_btn.setIcon(_dc_qicon)
            link_btn.setIconSize(QSize(20, 20))
            link_btn.clicked.connect(self.link_discord_requested)
            root.addWidget(link_btn)

        # Кнопка «проверить снова» — для случая, когда роль уже получена в Discord,
        # но лаунчер ещё держит старый кеш (живой пуш мог не дойти).
        if reason == "no_role":
            root.addSpacing(10)
            self._recheck_btn = QPushButton("Обновить")
            self._recheck_btn.setFixedSize(160, 40)
            self._recheck_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._recheck_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(255,255,255,20); color: #E6EDF3; border: 1px solid rgba(255,255,255,40);
                    border-radius: 10px; font-size: 13px; font-weight: 600;
                }
                QPushButton:hover { background: rgba(255,255,255,36); }
                QPushButton:disabled { color: #8892a0; border-color: rgba(255,255,255,20); }
            """)
            self._recheck_btn.clicked.connect(self._on_recheck_clicked)
            root.addWidget(self._recheck_btn)

        root.addStretch()

    def _on_recheck_clicked(self):
        btn = getattr(self, "_recheck_btn", None)
        if btn is not None:
            btn.setEnabled(False)
            btn.setText("Проверяю…")
        self.recheck_requested.emit()

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if not self._px.isNull():
            scaled = self._px.scaledToHeight(h, Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(w - scaled.width(), 0, scaled)
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0.0,  QColor(10, 13, 18, 255))
        grad.setColorAt(0.45, QColor(10, 13, 18, 220))
        grad.setColorAt(0.72, QColor(10, 13, 18, 80))
        grad.setColorAt(1.0,  QColor(10, 13, 18, 0))
        p.fillRect(0, 0, w, h, grad)


# ── Новости режима ────────────────────────────────────────────────────────────

_RU_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
              "августа", "сентября", "октября", "ноября", "декабря"]


def _format_news_date(published_at: str) -> str:
    """'2026-08-19 ..' → '19 августа'; прошлые годы → '19 августа 2025'."""
    s = (published_at or "").strip()
    if not s:
        return ""
    try:
        from datetime import datetime
        d = int(s[8:10]); m = int(s[5:7]); y = int(s[0:4])
        out = f"{d} {_RU_MONTHS[m - 1]}"
        if y != datetime.now().year:
            out += f" {y}"
        return out
    except Exception:
        return s[:16].replace("T", " ")


class _NewsThumb(QLabel):
    """Прямоугольная миниатюра фикс-размера (кроп по центру, скруглённая)."""
    def __init__(self, w: int, h: int, parent=None):
        super().__init__(parent)
        self._w, self._h = w, h
        self.setFixedSize(w, h)
        self.setStyleSheet("background: rgba(255,255,255,5); border-radius: 8px;")

    def set_source(self, px: QPixmap):
        scaled = px.scaled(self._w, self._h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
        x = max(0, (scaled.width() - self._w) // 2)
        y = max(0, (scaled.height() - self._h) // 2)
        rounded = QPixmap(self._w, self._h)
        rounded.fill(Qt.GlobalColor.transparent)
        p = QPainter(rounded)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self._w, self._h, 8, 8)
        p.setClipPath(path)
        p.drawPixmap(0, 0, scaled.copy(x, y, self._w, self._h))
        p.end()
        self.setPixmap(rounded)


class NewsCard(QFrame):
    """Новость — «величественная», но компактная: миниатюра слева + метка
    «НОВОСТЬ», крупный заголовок, описание; акцентная зелёная рамка/фон.
    Клик открывает полный текст в оверлее-ридере."""
    open_requested = pyqtSignal(dict)
    _THUMB_W, _THUMB_H = 200, 112   # 16:9

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self._data = data
        self.setObjectName("newsHero")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "#newsHero { background: rgba(51,193,90,12); border: 1px solid rgba(51,193,90,55);"
            " border-radius: 12px; }"
            " #newsHero:hover { background: rgba(51,193,90,20); border-color: rgba(51,193,90,90); }")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 12, 16, 12)
        row.setSpacing(14)

        self._img_url = (data.get("image") or "").strip()
        if self._img_url:
            self._img = _NewsThumb(self._THUMB_W, self._THUMB_H)
            row.addWidget(self._img, 0, Qt.AlignmentFlag.AlignTop)
            from assets_cache import AssetCache
            AssetCache.load(self._img_url, self._on_img)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        chip = QLabel("НОВОСТЬ")
        chip.setStyleSheet(
            "color: #0B140E; background: #33C15A; border-radius: 5px; padding: 2px 9px;"
            " font-size: 10px; font-weight: 800; letter-spacing: 1.2px;")
        top.addWidget(chip)
        top.addStretch()
        date = QLabel(_format_news_date(data.get("published_at", "")))
        date.setStyleSheet("color: #8B93A7; font-size: 12px; font-weight: 600; background: transparent;")
        top.addWidget(date)
        col.addLayout(top)

        title = QLabel(data.get("title", ""))
        title.setWordWrap(True)
        title.setStyleSheet("color: #FFFFFF; font-size: 18px; font-weight: 800; background: transparent;")
        col.addWidget(title)

        body_text = (data.get("body", "") or "").strip()
        if body_text:
            body = QLabel(body_text)
            body.setWordWrap(True)
            body.setStyleSheet("color: #9AA4B2; font-size: 13px; background: transparent;")
            col.addWidget(body)
        col.addStretch()
        row.addLayout(col, 1)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.open_requested.emit(self._data)
        super().mousePressEvent(e)

    def _on_img(self, url: str, px: QPixmap):
        if url == self._img_url:
            self._img.set_source(px)


class NewsReader(QWidget):
    """Оверлей-ридер новости поверх окна лаунчера (без новых окон): картинка,
    заголовок, полный текст со скроллом. Закрытие ✕ / Esc / клик по фону."""
    def __init__(self, data: dict, parent):
        super().__init__(parent)
        from ui.assets import svg_icon
        self._img_url = (data.get("image") or "").strip()
        self._src = None
        self.setStyleSheet("background: transparent;")
        self.setGeometry(parent.rect())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        parent.installEventFilter(self)

        self._panel = QFrame(self)
        self._panel.setObjectName("newsReader")
        self._panel.setStyleSheet(
            "#newsReader { background: #12161C; border: 1px solid rgba(51,193,90,70);"
            " border-radius: 14px; }")
        pl = QVBoxLayout(self._panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)

        scroll = QScrollArea(self._panel)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(0)

        self._img = None
        if self._img_url:
            self._img = QLabel()
            self._img.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._img.setStyleSheet("background: rgba(255,255,255,4);")
            il.addWidget(self._img)   # загрузку запустим в конце __init__ (см. ниже)

        content = QVBoxLayout()
        content.setContentsMargins(22, 16, 22, 22)
        content.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(8)
        chip = QLabel("НОВОСТЬ")
        chip.setStyleSheet(
            "color: #0B140E; background: #33C15A; border-radius: 5px; padding: 2px 9px;"
            " font-size: 10px; font-weight: 800; letter-spacing: 1.2px;")
        top.addWidget(chip)
        top.addStretch()
        date = QLabel(_format_news_date(data.get("published_at", "")))
        date.setStyleSheet("color: #8B93A7; font-size: 12px; font-weight: 600; background: transparent;")
        top.addWidget(date)
        content.addLayout(top)
        self._title = QLabel(data.get("title", ""))
        self._title.setWordWrap(True)
        self._title.setStyleSheet("color: #FFFFFF; font-size: 22px; font-weight: 800; background: transparent;")
        content.addWidget(self._title)
        self._body = QLabel((data.get("body", "") or "").strip())
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._body.setStyleSheet("color: #C2CAD6; font-size: 14px; line-height: 1.5; background: transparent;")
        content.addWidget(self._body)
        il.addLayout(content)
        il.addStretch()
        scroll.setWidget(inner)
        pl.addWidget(scroll)

        self._btn_close = QPushButton(self)
        self._btn_close.setIcon(svg_icon("cross.svg", "#E6EDF3", 16))
        self._btn_close.setFixedSize(36, 36)
        self._btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_close.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,20); border: 1px solid rgba(255,255,255,30);"
            " border-radius: 18px; }"
            " QPushButton:hover { background: rgba(255,255,255,38); }")
        self._btn_close.clicked.connect(self.close)
        self._relayout()
        # Картинку грузим ТОЛЬКО теперь — колбэк из кэша синхронный, а _relayout
        # обращается к self._title/_body, которые должны быть уже созданы.
        if self._img_url:
            from assets_cache import AssetCache
            AssetCache.load(self._img_url, self._on_img)

    def _on_img(self, url: str, px: QPixmap):
        if url != self._img_url:
            return
        self._src = px
        self._render_img()
        self._relayout()   # теперь известна высота картинки → подгоняем панель

    def _render_img(self):
        if not self._src:
            return
        cw = max(1, self._panel.width())
        scaled = self._src.scaledToWidth(cw, Qt.TransformationMode.SmoothTransformation)
        max_h = 300
        if scaled.height() > max_h:   # не даём картинке быть слишком высокой
            y = (scaled.height() - max_h) // 2
            scaled = scaled.copy(0, y, cw, max_h)
        # скругляем верхние углы под панель
        h = scaled.height()
        rounded = QPixmap(cw, h)
        rounded.fill(Qt.GlobalColor.transparent)
        p = QPainter(rounded)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = 14
        path = QPainterPath()
        path.moveTo(0, h)
        path.lineTo(0, r)
        path.quadTo(0, 0, r, 0)
        path.lineTo(cw - r, 0)
        path.quadTo(cw, 0, cw, r)
        path.lineTo(cw, h)
        path.closeSubpath()
        p.setClipPath(path)
        p.drawPixmap(0, 0, scaled)
        p.end()
        self._img.setFixedHeight(h)
        self._img.setPixmap(rounded)

    def _relayout(self):
        w, h = self.width(), self.height()
        pw = min(680, w - 80)
        # Высота панели по КОНТЕНТУ (со скроллом, если длиннее доступного) —
        # иначе панель тянется на весь экран и её нижняя рамка «висит» полосой.
        textw = pw - 44
        need = 16 + 22 + 10   # верх контента + строка метки + отступ
        need += self._title.heightForWidth(textw)
        bt = self._body.text().strip()
        if bt:
            need += 10 + self._body.heightForWidth(textw)
        need += 22   # нижний отступ контента
        if self._img is not None:
            need += self._img.height() if self._src else int(pw * 9 / 16)
        ph = max(160, min(h - 80, need))
        px, py = (w - pw) // 2, (h - ph) // 2
        self._panel.setGeometry(px, py, pw, ph)
        self._btn_close.move(px + pw - 46, py + 10)
        self._btn_close.raise_()
        self._render_img()

    def resizeEvent(self, e):
        self._relayout()
        super().resizeEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 200))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e):
        if not self._panel.geometry().contains(e.pos()):
            self.close()

    def eventFilter(self, obj, ev):
        if obj is self.parent() and ev.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
        return super().eventFilter(obj, ev)

    def closeEvent(self, e):
        par = self.parent()
        if par:
            par.removeEventFilter(self)
        super().closeEvent(e)
        self.deleteLater()


# ── Скриншоты режима ──────────────────────────────────────────────────────────

class FlowLayout(QLayout):
    """Адаптивная сетка: плитки равной ширины заполняют строку ЦЕЛИКОМ (без
    пустоты справа), высота 16:9. Кол-во колонок подбирается по ширине."""
    def __init__(self, parent=None, spacing=10, min_tile=200):
        super().__init__(parent)
        self._items = []
        self._space = spacing
        self._min = min_tile
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        return QSize(self._min, self._min * 9 // 16)

    def _grid(self, width):
        cols = max(1, (width + self._space) // (self._min + self._space))
        tile_w = (width - self._space * (cols - 1)) // cols
        return cols, max(1, tile_w)

    def _do_layout(self, rect, test_only):
        n = len(self._items)
        if n == 0:
            return 0
        cols, tw = self._grid(rect.width())
        th = tw * 9 // 16
        for i, item in enumerate(self._items):
            if not test_only:
                x = rect.x() + (i % cols) * (tw + self._space)
                y = rect.y() + (i // cols) * (th + self._space)
                item.setGeometry(QRect(x, y, tw, th))
        rows = (n + cols - 1) // cols
        return rows * th + (rows - 1) * self._space


class _ShotSignals(QObject):
    done = pyqtSignal(str, QImage)


class _ShotLoader(QRunnable):
    """Декодирует картинку и уменьшает до ~640px в фоне (QImage потокобезопасен).
    Кроп/скругление под текущий размер плитки — уже в UI-потоке."""
    _pool = QThreadPool.globalInstance()

    def __init__(self, path: str, signals: _ShotSignals):
        super().__init__()
        self._path, self._sig = path, signals

    def run(self):
        img = QImage(self._path)
        if img.isNull():
            return
        if img.width() > 640:
            img = img.scaledToWidth(640, Qt.TransformationMode.SmoothTransformation)
        self._sig.done.emit(self._path, img)


class ShotTile(QLabel):
    """Адаптивная плитка скриншота 16:9 (скруглённые углы), грузится в фоне.
    Размер задаёт раскладка (FlowLayout); при наведении — кнопка публикации."""
    clicked = pyqtSignal(str)
    publish_requested = pyqtSignal(str)

    def __init__(self, path: str, can_publish: bool = True, parent=None):
        super().__init__(parent)
        from ui.assets import svg_icon
        self._path = path
        self._src = None
        self.setMinimumSize(1, 1)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background: rgba(255,255,255,5); border-radius: 8px;")
        self._sig = _ShotSignals()
        self._sig.done.connect(self._on_img)
        _ShotLoader._pool.start(_ShotLoader(path, self._sig))

        # Кнопка публикации — только если игрок может публиковать (привязан Discord).
        # Без QGraphicsOpacityEffect (в PyQt6 он «съедает» иконку на QPushButton).
        # «Еле заметность» — через слабую тёмную подложку; значок всегда виден.
        self._pub_btn = None
        if can_publish:
            self._pub_btn = QPushButton(self)
            self._pub_btn.setIcon(svg_icon("download.svg", "#FFFFFF", 15))
            self._pub_btn.setFixedSize(26, 26)
            self._pub_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._pub_btn.setToolTip("Опубликовать")
            self._pub_btn.setStyleSheet(
                "QPushButton { background: rgba(0,0,0,90); border: 1px solid rgba(255,255,255,25);"
                " border-radius: 13px; }"
                " QPushButton:hover { background: rgba(51,193,90,210); border-color: #33C15A; }")
            self._pub_btn.hide()
            self._pub_btn.clicked.connect(lambda: self.publish_requested.emit(self._path))

    def enterEvent(self, e):
        if self._pub_btn is not None:
            self._pub_btn.show()
            self._pub_btn.raise_()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self._pub_btn is not None:
            self._pub_btn.hide()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._path)
        super().mousePressEvent(e)

    def resizeEvent(self, e):
        self._render()
        if self._pub_btn is not None:
            self._pub_btn.move(self.width() - 32, self.height() - 32)
        super().resizeEvent(e)

    def _on_img(self, path: str, img: QImage):
        if path != self._path:
            return
        self._src = QPixmap.fromImage(img)
        self._render()

    def _render(self):
        w, h = self.width(), self.height()
        if not self._src or w <= 0 or h <= 0:
            return
        scaled = self._src.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation)
        x = max(0, (scaled.width() - w) // 2)
        y = max(0, (scaled.height() - h) // 2)
        rounded = QPixmap(w, h)
        rounded.fill(Qt.GlobalColor.transparent)
        p = QPainter(rounded)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path_ = QPainterPath()
        path_.addRoundedRect(0, 0, w, h, 8, 8)
        p.setClipPath(path_)
        p.drawPixmap(0, 0, scaled.copy(x, y, w, h))
        p.end()
        self.setPixmap(rounded)


class _FullSignals(QObject):
    done = pyqtSignal(str, QImage)


class _FullLoader(QRunnable):
    """Полное изображение грузим в фоне (QImage потокобезопасен)."""
    _pool = QThreadPool.globalInstance()

    def __init__(self, path: str, signals: _FullSignals):
        super().__init__()
        self._path, self._sig = path, signals

    def run(self):
        img = QImage(self._path)
        if not img.isNull():
            self._sig.done.emit(self._path, img)


class ScreenshotViewer(QWidget):
    """Полноэкранный просмотр поверх окна лаунчера: листание ‹/› (и стрелками),
    счётчик, описание снизу, опц. публикация, закрытие по ✕ / Esc / клику по фону.
    items — список {"src": путь_или_URL, "desc": описание}."""
    publish_requested = pyqtSignal(str)   # src текущего кадра
    _BTN = ("QPushButton { background: rgba(255,255,255,20);"
            " border: 1px solid rgba(255,255,255,30); border-radius: 20px; }"
            " QPushButton:hover { background: rgba(255,255,255,38); }")

    def __init__(self, items: list, index: int, parent, allow_publish: bool = True):
        super().__init__(parent)
        from ui.assets import svg_icon
        # нормализуем: список строк → список {src, desc}
        self._items = [({"src": it, "desc": ""} if isinstance(it, str) else it) for it in items]
        self._index = index
        self._pixmap = None
        self._cur_src = None
        self.setStyleSheet("background: transparent;")
        self.setGeometry(parent.rect())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        parent.installEventFilter(self)   # следим за ресайзом окна

        self._img = QLabel(self)
        self._img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img.setStyleSheet("background: transparent; color: #7D8590; font-size: 13px;")

        self._btn_close = QPushButton(self)
        self._btn_close.setIcon(svg_icon("cross.svg", "#E6EDF3", 18))
        self._btn_close.setFixedSize(40, 40)
        self._btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_close.setStyleSheet(self._BTN)
        self._btn_close.clicked.connect(self.close)

        # Публикация текущего кадра (только для локальных скриншотов) — заметная
        # кнопка с текстом, чтобы легко попадать (не крошечная иконка в углу).
        self._btn_pub = QPushButton("  Опубликовать", self)
        self._btn_pub.setIcon(svg_icon("download.svg", "#0B140E", 16))
        self._btn_pub.setFixedHeight(42)
        self._btn_pub.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_pub.setStyleSheet(
            "QPushButton { background: #33C15A; color: #0B140E; border: none; border-radius: 21px;"
            " padding: 0 20px; font-size: 13px; font-weight: 700; }"
            " QPushButton:hover { background: #46D46E; }")
        self._btn_pub.clicked.connect(lambda: self.publish_requested.emit(self._cur_src or ""))
        self._btn_pub.setVisible(allow_publish)
        self._btn_pub.adjustSize()
        self._btn_pub.setFixedHeight(42)
        self._allow_publish = allow_publish

        self._btn_prev = QPushButton(self)
        self._btn_next = QPushButton(self)
        self._btn_prev.setIcon(svg_icon("angle_left.svg", "#E6EDF3", 20))
        self._btn_next.setIcon(svg_icon("angle_right.svg", "#E6EDF3", 20))
        for b, d in ((self._btn_prev, -1), (self._btn_next, 1)):
            b.setFixedSize(44, 44)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(self._BTN)
            b.clicked.connect(lambda _=False, dd=d: self._go(dd))

        # Описание снизу (для постов ленты)
        self._desc = QLabel("", self)
        self._desc.setWordWrap(True)
        self._desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._desc.setStyleSheet(
            "color: #E6EDF3; font-size: 13px; background: rgba(0,0,0,120);"
            " border-radius: 8px; padding: 8px 14px;")
        self._desc.setVisible(False)

        self._counter = QLabel("", self)
        self._counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._counter.setStyleSheet(
            "color: #C9D1D9; font-size: 12px; font-weight: 600; background: transparent;")

        self._sig = _FullSignals()
        self._sig.done.connect(self._on_full)
        self._load_current()
        self._relayout()

    def _load_current(self):
        item = self._items[self._index]
        src, desc = item.get("src", ""), (item.get("desc") or "").strip()
        self._cur_src = src
        self._pixmap = None
        self._img.setPixmap(QPixmap())
        self._img.setText("Загрузка…")
        self._counter.setText(f"{self._index + 1} / {len(self._items)}")
        multi = len(self._items) > 1
        self._btn_prev.setVisible(multi)
        self._btn_next.setVisible(multi)
        self._desc.setText(desc)
        self._desc.setVisible(bool(desc))
        self._relayout_desc()
        if src.startswith("http://") or src.startswith("https://"):
            from assets_cache import AssetCache
            AssetCache.load(src, self._on_remote)   # скачает+закеширует, отдаст QPixmap в UI
        else:
            _FullLoader._pool.start(_FullLoader(src, self._sig))

    def _on_full(self, path: str, img: QImage):
        if path != self._cur_src:
            return
        self._pixmap = QPixmap.fromImage(img)
        self._rescale()

    def _on_remote(self, url: str, px: QPixmap):
        if url != self._cur_src:
            return
        self._pixmap = px
        self._rescale()

    def _go(self, delta: int):
        n = len(self._items)
        if n:
            self._index = (self._index + delta) % n
            self._load_current()

    def _rescale(self):
        if not self._pixmap:
            return
        max_w = max(1, self.width() - 160)
        max_h = max(1, self.height() - 130)
        self._img.setText("")
        self._img.setPixmap(self._pixmap.scaled(
            max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def _relayout_desc(self):
        w, h = self.width(), self.height()
        if self._desc.isVisible():
            self._desc.setFixedWidth(min(int(w * 0.7), 900))
            self._desc.adjustSize()
            dw = self._desc.width()
            self._desc.move((w - dw) // 2, h - self._desc.height() - 44)

    def _relayout(self):
        w, h = self.width(), self.height()
        self._img.setGeometry(0, 0, w, h)
        self._btn_close.move(w - 56, 16)
        self._btn_prev.move(16, h // 2 - 22)
        self._btn_next.move(w - 60, h // 2 - 22)
        self._btn_pub.move(w - self._btn_pub.width() - 24, h - 58)   # нижний-правый
        self._counter.setGeometry(0, h - 40, w, 22)
        self._relayout_desc()
        for c in (self._btn_close, self._btn_prev, self._btn_next, self._btn_pub,
                  self._counter, self._desc):
            c.raise_()
        self._rescale()

    def resizeEvent(self, e):
        self._relayout()
        super().resizeEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 224))

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self.close()
        elif k == Qt.Key.Key_Left:
            self._go(-1)
        elif k == Qt.Key.Key_Right:
            self._go(1)
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e):
        # клик по тёмному фону (вне картинки и описания) закрывает
        if self._desc.isVisible() and self._desc.geometry().contains(e.pos()):
            return
        pm = self._img.pixmap()
        if pm and not pm.isNull():
            iw, ih = pm.width(), pm.height()
            rect = QRect((self.width() - iw) // 2, (self.height() - ih) // 2, iw, ih)
            if rect.contains(e.pos()):
                return
        self.close()

    def eventFilter(self, obj, ev):
        if obj is self.parent() and ev.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
        return super().eventFilter(obj, ev)

    def closeEvent(self, e):
        par = self.parent()
        if par:
            par.removeEventFilter(self)
        super().closeEvent(e)
        self.deleteLater()


def compress_to_jpeg(path: str, max_dim: int = 1920, quality: int = 85) -> bytes:
    """Читает скриншот, ужимает до max_dim по большей стороне и кодирует в JPEG."""
    img = QImage(path)
    if img.isNull():
        return b""
    if max(img.width(), img.height()) > max_dim:
        img = img.scaled(max_dim, max_dim, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "JPEG", quality)
    data = bytes(buf.data())
    buf.close()
    return data


class PublishShotDialog(QDialog):
    """Диалог публикации скриншота: превью + описание + «Опубликовать».
    Сжатие в JPEG и отправка идут в фоне (из потока — только через сигнал)."""
    published = pyqtSignal()
    _result = pyqtSignal(bool, str)   # (ok, error) из фонового потока

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self._path = path
        self.setWindowTitle("Опубликовать скриншот")
        self.setMinimumWidth(400)
        self.setStyleSheet(
            "QDialog { background: #12161C; }"
            " QLabel { color: #C9D1D9; background: transparent; }"
            " QPlainTextEdit { background: rgba(255,255,255,8); color: #E6EDF3;"
            "   border: 1px solid rgba(255,255,255,20); border-radius: 8px; padding: 6px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(12)

        prev = QLabel()
        prev.setFixedSize(364, 205)   # 16:9
        prev.setStyleSheet("background: rgba(255,255,255,6); border-radius: 8px;")
        prev.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img = QImage(path)
        if not img.isNull():
            px = QPixmap.fromImage(img).scaled(
                364, 205, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation)
            x = max(0, (px.width() - 364) // 2)
            y = max(0, (px.height() - 205) // 2)
            rounded = QPixmap(364, 205)
            rounded.fill(Qt.GlobalColor.transparent)
            p = QPainter(rounded)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pth = QPainterPath()
            pth.addRoundedRect(0, 0, 364, 205, 8, 8)
            p.setClipPath(pth)
            p.drawPixmap(0, 0, px.copy(x, y, 364, 205))
            p.end()
            prev.setPixmap(rounded)
        lay.addWidget(prev, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._desc = QPlainTextEdit()
        self._desc.setPlaceholderText("Описание (необязательно)")
        self._desc.setFixedHeight(80)
        lay.addWidget(self._desc)

        self._err = QLabel("")
        self._err.setStyleSheet("color: #F85149; font-size: 12px; background: transparent;")
        self._err.setVisible(False)
        lay.addWidget(self._err)

        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Отмена")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        self._pub = QPushButton("Опубликовать")
        self._pub.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pub.setStyleSheet(
            "QPushButton { background: rgba(51,193,90,20); color: #33C15A;"
            " border: 1px solid rgba(51,193,90,90); border-radius: 8px; padding: 6px 16px; }"
            " QPushButton:hover { background: rgba(51,193,90,40); color: #fff; }")
        self._pub.clicked.connect(self._do_publish)
        row.addWidget(cancel)
        row.addWidget(self._pub)
        lay.addLayout(row)

        self._result.connect(self._on_result)

    def _do_publish(self):
        self._pub.setEnabled(False)
        self._pub.setText("Публикация…")
        self._err.setVisible(False)
        import threading
        path, desc = self._path, self._desc.toPlainText().strip()

        def _run():
            data = compress_to_jpeg(path)
            if not data:
                self._result.emit(False, "Не удалось прочитать изображение")
                return
            import screenshots_client
            res = screenshots_client.publish(data, desc)
            if res and res.get("success"):
                self._result.emit(True, "")
            else:
                self._result.emit(False, "Ошибка публикации. Проверьте связь с сервером.")
        threading.Thread(target=_run, daemon=True).start()

    def _on_result(self, ok: bool, err: str):
        if ok:
            self.published.emit()
            self.accept()
        else:
            self._pub.setEnabled(True)
            self._pub.setText("Опубликовать")
            self._err.setText(err)
            self._err.setVisible(True)


class FeedThumb(QLabel):
    """Адаптивная миниатюра поста ленты (удалённый URL, 16:9, скруглённая).
    Клик отдаёт свой индекс в группе."""
    clicked = pyqtSignal(int)

    def __init__(self, url: str, index: int, parent=None):
        super().__init__(parent)
        self._url, self._index, self._src = url, index, None
        self.setMinimumSize(1, 1)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background: rgba(255,255,255,5); border-radius: 8px;")
        from assets_cache import AssetCache
        AssetCache.load(url, self._on_img)

    def _on_img(self, url: str, px: QPixmap):
        if url == self._url:
            self._src = px
            self._render()

    def resizeEvent(self, e):
        self._render()
        super().resizeEvent(e)

    def _render(self):
        w, h = self.width(), self.height()
        if not self._src or w <= 0 or h <= 0:
            return
        scaled = self._src.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation)
        x = max(0, (scaled.width() - w) // 2)
        y = max(0, (scaled.height() - h) // 2)
        rounded = QPixmap(w, h)
        rounded.fill(Qt.GlobalColor.transparent)
        p = QPainter(rounded)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pth = QPainterPath()
        pth.addRoundedRect(0, 0, w, h, 8, 8)
        p.setClipPath(pth)
        p.drawPixmap(0, 0, scaled.copy(x, y, w, h))
        p.end()
        self.setPixmap(rounded)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._index)
        super().mousePressEvent(e)


class FeedGroupCard(QFrame):
    """Карточка ленты «Главная»: посты одного автора за день.
    1 фото → миниатюра слева + описание справа; несколько → сетка миниатюр
    (без описаний). Клик по фото открывает полноэкранный просмотр группы."""
    open_requested = pyqtSignal(list, int)   # (items[{src,desc}], index)

    _THUMB_W, _THUMB_H = 200, 112

    def __init__(self, group: dict, parent=None):
        super().__init__(parent)
        self._posts = group["posts"]
        self.setObjectName("feedCard")
        self.setStyleSheet(
            "#feedCard { background: rgba(255,255,255,7); border: 1px solid rgba(255,255,255,15);"
            " border-radius: 10px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Шапка: голова + ник + дата (один раз на группу)
        head_row = QHBoxLayout()
        head_row.setContentsMargins(12, 10, 12, 8)
        head_row.setSpacing(8)
        self._head_url = f"https://mc-heads.net/avatar/{group.get('author_uuid','')}/28"
        self._head = QLabel()
        self._head.setFixedSize(28, 28)
        self._head.setStyleSheet("background: rgba(255,255,255,8); border-radius: 6px;")
        from assets_cache import AssetCache
        AssetCache.load(self._head_url, self._on_head)
        head_row.addWidget(self._head)
        name = QLabel(group.get("author_name", "Игрок") + ("  (вы)" if group.get("mine") else ""))
        name.setStyleSheet("color: #E6EDF3; font-size: 13px; font-weight: 700; background: transparent;")
        head_row.addWidget(name)
        head_row.addStretch()
        cnt = len(self._posts)
        date_text = _format_news_date(group.get("date", ""))
        if cnt > 1:
            date_text += f"  ·  {cnt} фото"
        date = QLabel(date_text)
        date.setStyleSheet("color: #8B93A7; font-size: 12px; font-weight: 600; background: transparent;")
        head_row.addWidget(date)
        lay.addLayout(head_row)

        if cnt == 1:
            # Одно фото: миниатюра слева + описание справа
            row = QHBoxLayout()
            row.setContentsMargins(12, 0, 14, 12)
            row.setSpacing(14)
            thumb = FeedThumb(self._posts[0]["image"], 0)
            thumb.setFixedSize(self._THUMB_W, self._THUMB_H)
            thumb.clicked.connect(self._open)
            row.addWidget(thumb, 0, Qt.AlignmentFlag.AlignTop)
            desc = (self._posts[0].get("description") or "").strip()
            d = QLabel(desc or "")
            d.setWordWrap(True)
            d.setStyleSheet("color: #7D8590; font-size: 13px; background: transparent;")
            d.setAlignment(Qt.AlignmentFlag.AlignTop)
            row.addWidget(d, 1)
            lay.addLayout(row)
        else:
            # Несколько фото: сетка миниатюр без описаний
            grid_w = QWidget()
            grid_w.setStyleSheet("background: transparent;")
            flow = FlowLayout(spacing=8, min_tile=150)
            grid_w.setLayout(flow)
            for i, p in enumerate(self._posts):
                t = FeedThumb(p["image"], i)
                t.clicked.connect(self._open)
                flow.addWidget(t)
            wrap = QVBoxLayout()
            wrap.setContentsMargins(12, 0, 14, 12)
            wrap.addWidget(grid_w)
            lay.addLayout(wrap)

    def _items(self) -> list:
        return [{"src": p["image"], "desc": (p.get("description") or "")} for p in self._posts]

    def _open(self, index: int):
        self.open_requested.emit(self._items(), index)

    def _on_head(self, url: str, px: QPixmap):
        if url != self._head_url:
            return
        rounded = QPixmap(28, 28)
        rounded.fill(Qt.GlobalColor.transparent)
        p = QPainter(rounded)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pth = QPainterPath()
        pth.addRoundedRect(0, 0, 28, 28, 6, 6)
        p.setClipPath(pth)
        p.drawPixmap(0, 0, px.scaled(28, 28, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                     Qt.TransformationMode.SmoothTransformation))
        p.end()
        self._head.setPixmap(rounded)


# ── ModeView ──────────────────────────────────────────────────────────────────

class ModeView(QWidget):
    play_requested = pyqtSignal(dict)
    settings_requested = pyqtSignal(dict)
    log_requested = pyqtSignal(str)
    _news_loaded = pyqtSignal(list)   # маршалинг новостей из фонового потока в UI
    _feed_loaded = pyqtSignal(list)   # маршалинг постов-скриншотов (лента «Главная»)
    def __init__(self, mode: dict, launcher_config: dict = None, parent=None):
        super().__init__(parent)
        self._mode = mode
        self._launcher_config = launcher_config or {}
        self._install_worker: InstallWorker | None = None
        self._build_ui()
        self._load_assets()

    def _build_ui(self):
        from config import SIDEBAR_WIDTH
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Баннер сверху на всю ширину ───────────────────────────────────────
        self._banner_container = BannerContainer(self._mode.get("id", ""))
        self._banner_container.setFixedHeight(300)
        self._banner = self._banner_container.banner()
        # version_label — чисто визуальная подпись версии (fallback на minecraft_version
        # для старых режимов). Техническая версия для установки живёт в modpack.
        ver_str = self._mode.get("version_label") or self._mode.get("minecraft_version", "")
        self._banner.set_mode_info(self._mode.get("name", ""), ver_str)
        self._banner_container.set_mode_name(self._mode.get("name", ""))
        self._banner_container.set_connector(self._mode.get("connector", False))
        _mp = self._mode.get("modpack", {}) or {}
        self._banner_container.set_mod_protection(_mp.get("mod_protection") == "strict")
        self._banner_container.set_hidden(self._mode.get("hidden", False))
        self._banner_container.set_required_role(
            self._mode.get("required_discord_role", ""),
            self._mode.get("required_discord_role_name", ""),
        )
        root.addWidget(self._banner_container)

        # ── Под баннером: 3 колонки ───────────────────────────────────────────
        bottom = QWidget()
        bottom.setStyleSheet("background: transparent;")
        bottom_row = QHBoxLayout(bottom)
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(0)

        def _vline():
            f = QFrame()
            f.setFrameShape(QFrame.Shape.VLine)
            f.setStyleSheet("background: rgba(255,255,255,8); border: none; max-width: 1px;")
            f.setFixedWidth(1)
            return f

        # ── Центр: кнопка + описание ──────────────────────────────────────────
        center = QWidget()
        center.setStyleSheet("background: transparent;")
        center_lay = QVBoxLayout(center)
        center_lay.setContentsMargins(24, 12, 24, 16)
        center_lay.setSpacing(8)

        btns_top = QHBoxLayout()
        btns_top.setSpacing(14)
        btns_top.setContentsMargins(0, 0, 0, 0)

        self._play_btn = SplitGlowButton("  Играть", "#3FB950")
        self._play_btn.setFixedWidth(210)
        self._play_btn.clicked.connect(self._on_play_or_install)
        self._play_btn.settings_clicked.connect(lambda: self.settings_requested.emit(self._mode))

        self._maintenance_lbl = QLabel()
        self._maintenance_lbl.setStyleSheet("color: #9CA3AF; font-size: 12px; background: transparent;")
        self._maintenance_lbl.setVisible(False)

        self._size_widget = QWidget()
        self._size_widget.setStyleSheet("background: transparent;")
        _sw_lay = QVBoxLayout(self._size_widget)
        _sw_lay.setContentsMargins(0, 0, 0, 0)
        _sw_lay.setSpacing(1)
        _sw_top = QLabel("ВЕС")
        _sw_top.setStyleSheet("color: #4A5260; font-size: 9px; font-weight: 700; letter-spacing: 1px; background: transparent;")
        self._size_lbl = QLabel("")
        self._size_lbl.setStyleSheet("color: #E6EDF3; font-size: 13px; font-weight: 700; background: transparent;")
        _sw_lay.addWidget(_sw_top)
        _sw_lay.addWidget(self._size_lbl)
        self._size_widget.setVisible(False)

        import playtime as pt
        import auth_client
        mode_id = self._mode.get("id", "")
        pt_data = pt.get(mode_id)
        discord_id = auth_client._load_settings().get("discord_id")

        def _stat_lbl(top: str, val: str) -> QWidget:
            w = QWidget(); w.setStyleSheet("background: transparent;")
            l = QVBoxLayout(w); l.setContentsMargins(0, 0, 0, 0); l.setSpacing(1)
            t = QLabel(top)
            t.setStyleSheet("color: #4A5260; font-size: 9px; font-weight: 700; letter-spacing: 1px; background: transparent;")
            v = QLabel(val)
            v.setStyleSheet("color: #E6EDF3; font-size: 13px; font-weight: 700; background: transparent;")
            l.addWidget(t); l.addWidget(v)
            return w

        btns_top.addWidget(self._play_btn)
        btns_top.addSpacing(12)
        btns_top.addWidget(self._size_widget)

        self._pt_hours_lbl = None
        self._pt_last_lbl = None
        if not discord_id:
            hint_w = QWidget()
            hint_w.setStyleSheet("background: transparent;")
            hint_lay = QHBoxLayout(hint_w)
            hint_lay.setContentsMargins(0, 0, 0, 0)
            hint_lay.setSpacing(8)
            dc_icon = QLabel()
            dc_icon.setStyleSheet("background: transparent;")
            dc_icon.setFixedSize(40, 40)
            dc_icon.setScaledContents(True)
            from ui.assets import mimi_grand
            dc_icon.setPixmap(mimi_grand())
            txt = QLabel("Чтобы сохранить время прогресса\nпривяжите Discord к аккаунту")
            txt.setStyleSheet("color: #4A5260; font-size: 11px; line-height: 1.4; background: transparent;")
            txt.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            hint_lay.addWidget(dc_icon)
            hint_lay.addWidget(txt)
            btns_top.addWidget(hint_w)
        elif pt_data.get("seconds", 0) > 0:
            pt_w1 = _stat_lbl("НАИГРАНО", pt.format_hours(pt_data["seconds"]))
            pt_w2 = _stat_lbl("ПОСЛЕДНИЙ ВХОД", pt.format_last_played(pt_data.get("last_played")))
            self._pt_hours_lbl = pt_w1.layout().itemAt(1).widget()
            self._pt_last_lbl  = pt_w2.layout().itemAt(1).widget()
            btns_top.addWidget(pt_w1, alignment=Qt.AlignmentFlag.AlignVCenter)
            btns_top.addSpacing(12)
            btns_top.addWidget(pt_w2, alignment=Qt.AlignmentFlag.AlignVCenter)

        btns_top.addStretch()
        # Кнопочный ряд (Играть + наиграно + последний вход) — в рамке-прямоугольнике.
        top_frame = QFrame()
        top_frame.setObjectName("topActions")
        top_frame.setStyleSheet(
            "#topActions { background: rgba(255,255,255,7);"
            " border: 1px solid rgba(255,255,255,20); border-radius: 10px; }")
        tf_lay = QVBoxLayout(top_frame)
        tf_lay.setContentsMargins(14, 10, 14, 10)
        tf_lay.setSpacing(8)
        tf_lay.addLayout(btns_top)
        if self._maintenance_lbl.isVisible():
            tf_lay.addWidget(self._maintenance_lbl)

        self._progress_frame = QWidget()
        self._progress_frame.hide()
        pf = QVBoxLayout(self._progress_frame)
        pf.setContentsMargins(0, 0, 0, 0)
        pf.setSpacing(4)
        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet("color: #7D8590; font-size: 11px; background: transparent;")
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setRange(0, 1000)
        pf.addWidget(self._progress_label)
        pf.addWidget(self._progress_bar)
        tf_lay.addWidget(self._progress_frame)
        center_lay.addWidget(top_frame)
        center_lay.addSpacing(6)   # воздух между карточкой кнопки и табами

        # Блок табов + контента (верхней полоски нет — рамка выше уже отделяет).
        info_block = QVBoxLayout()
        info_block.setContentsMargins(0, 0, 0, 0)
        info_block.setSpacing(0)   # таб-бар стоит вплотную на базовой линии

        # Наиграно ≥1 мин в этом режиме — от этого зависит вкладка «Скриншоты»
        # (без игры скриншотов не будет) и стартовая вкладка.
        try:
            import playtime as _pt0
            self._played = (_pt0.get(self._mode.get("id", "")).get("seconds", 0) or 0) >= 60
        except Exception:
            self._played = False

        # ── Вкладки: Главная | Новости | Скриншоты | Описание ──────────────────
        tabs_row = QHBoxLayout()
        tabs_row.setContentsMargins(0, 0, 0, 0)
        tabs_row.setSpacing(6)
        self._tab_main = QPushButton("ГЛАВНАЯ")
        self._tab_news = QPushButton("НОВОСТИ")
        self._tab_shots = QPushButton("СКРИНШОТЫ")
        self._tab_desc = QPushButton("ОПИСАНИЕ")
        for b in (self._tab_main, self._tab_news, self._tab_shots, self._tab_desc):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFlat(True)
        self._user_switched_tab = False
        self._tab_main.clicked.connect(lambda: self._on_tab_click("main"))
        self._tab_news.clicked.connect(lambda: self._on_tab_click("news"))
        self._tab_shots.clicked.connect(lambda: self._on_tab_click("shots"))
        self._tab_desc.clicked.connect(lambda: self._on_tab_click("desc"))
        tabs_row.addWidget(self._tab_main)
        tabs_row.addWidget(self._tab_news)
        tabs_row.addWidget(self._tab_shots)
        tabs_row.addWidget(self._tab_desc)
        tabs_row.addStretch()
        info_block.addLayout(tabs_row)
        # ВАЖНО: setVisible на _tab_shots делаем НЕ здесь — info_block ещё не на
        # виджете (попадёт на center лишь в center_lay.addLayout ниже), кнопка пока
        # parentless и setVisible(True) всплыл бы отдельным окном. См. ниже, после
        # center_lay.addLayout(info_block).

        # Полоска под табами — отделяет кнопки-вкладки от содержимого
        _under_tabs_sep = QFrame()
        _under_tabs_sep.setFrameShape(QFrame.Shape.HLine)
        _under_tabs_sep.setFixedHeight(1)
        _under_tabs_sep.setStyleSheet("background: rgba(255,255,255,12); border: none;")
        info_block.addWidget(_under_tabs_sep)
        info_block.addSpacing(14)   # воздух между табами и содержимым

        # Страница «Описание»
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        desc_w = QWidget()
        desc_w.setStyleSheet("background: transparent;")
        desc_l = QVBoxLayout(desc_w)
        desc_l.setContentsMargins(0, 2, 24, 8)
        # description_full поддерживает HTML: <b>жирный</b>, <i>курсив</i>, <br> перенос,
        # отступы (&nbsp; или <blockquote>/<ul><li>), цвета, ссылки. Может приходить готовым
        # HTML (сервер вклеивает из modes/<id>.description.md|html) или plain-текстом из JSON.
        _raw_desc = self._mode.get("description_full", "") or ""
        # plain-текст → переносы в <br>; готовый HTML (с тегами) оставляем как есть,
        # иначе \n между блочными тегами дал бы лишние пустые строки.
        _desc_html = _raw_desc if ("<" in _raw_desc and ">" in _raw_desc) else _raw_desc.replace("\n", "<br>")
        self._desc_full = QLabel(_desc_html)
        self._desc_full.setTextFormat(Qt.TextFormat.RichText)
        self._desc_full.setWordWrap(True)
        self._desc_full.setOpenExternalLinks(True)
        self._desc_full.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._desc_full.setStyleSheet("color: #7D8590; font-size: 13px; background: transparent;")
        desc_l.addWidget(self._desc_full)
        desc_l.addStretch()
        scroll.setWidget(desc_w)
        self._desc_scroll = scroll
        info_block.addWidget(self._desc_scroll, 1)

        # Страница «Главная» — лента: новости + (позже) посты со скриншотами
        # друзей и свои. Пока = новости.
        self._main_page, self._main_lay, self._main_empty = self._make_feed_page("Загрузка…")
        info_block.addWidget(self._main_page, 1)

        # Страница «Новости» — только новости
        self._news_page, self._news_lay, self._news_empty = self._make_feed_page("Загрузка…")
        info_block.addWidget(self._news_page, 1)
        self._news_items = []
        self._feed_posts = []
        self._news_loaded.connect(self._render_news)
        self._feed_loaded.connect(self._on_feed_loaded)

        # Страница «Скриншоты» — сетка миниатюр из папки режима (грузится лениво)
        shots_scroll = QScrollArea()
        shots_scroll.setWidgetResizable(True)
        shots_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        shots_w = QWidget()
        shots_w.setStyleSheet("background: transparent;")
        outer_shots = QVBoxLayout(shots_w)
        outer_shots.setContentsMargins(0, 2, 24, 8)
        outer_shots.setSpacing(0)
        self._shots_flow = FlowLayout(spacing=10, min_tile=200)
        outer_shots.addLayout(self._shots_flow)
        self._shots_empty = QLabel("Пусто")
        self._shots_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._shots_empty.setStyleSheet("color: #555570; font-size: 13px; background: transparent;")
        outer_shots.addWidget(self._shots_empty)
        outer_shots.addStretch()
        shots_scroll.setWidget(shots_w)
        self._shots_page = shots_scroll
        self._shots_loaded = False   # ленивая загрузка при первом показе вкладки
        info_block.addWidget(self._shots_page, 1)

        center_lay.addLayout(info_block, 1)
        # Теперь табы встроены в center (есть родитель) — можно скрывать кнопку
        # «Скриншоты» без всплытия отдельным окном.
        self._tab_shots.setVisible(self._played)   # видна только если наиграно ≥1мин

        # Стартовая вкладка: «Главная» открывается, если есть новости (по кэшу, чтобы
        # решить синхронно — без мелькания) И наиграно ≥1мин; иначе «Описание».
        import api as _api
        _cached_news = _api.load_cached_mode_news(self._mode.get("id", ""))
        _has_cached_news = bool(_cached_news)
        self._switch_info_tab("main" if (self._played and _has_cached_news) else "desc")
        # Грузим новости только теперь — когда вкладки уже встроены в иерархию.
        # (setVisible на ещё не-родительском виджете всплыл бы отдельным окном.)
        self._load_news()
        self._load_feed_posts()   # посты-скриншоты в ленту «Главная»

        bottom_row.addWidget(center, 1)
        bottom_row.addWidget(_vline())

        # ── Правая колонка: статистика (той же ширины) ────────────────────────
        right = QWidget()
        right.setFixedWidth(SIDEBAR_WIDTH)
        right.setStyleSheet("background: transparent;")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(16, 12, 16, 16)
        right_lay.setSpacing(4)

        ver_label = self._mode.get("version_label") or self._mode.get("minecraft_version", "—")
        # Единая система цвета иконок: акцентный зелёный = обычная инфа,
        # красный = ограничение (нужна роль). Убирает «радугу» без смысла.
        _ACCENT = "#33C15A"
        stats_data = [
            ("👤", "Разработчик", self._mode.get("developer", "—"), _ACCENT, "crown.svg", self._mode.get("developer_url", "")),
            ("🎮", "Жанр", self._mode.get("genre", "—"), _ACCENT, "gamepad.svg", ""),
            ("⚡", "Версия", ver_label, _ACCENT, "bolt.svg", ""),
        ]
        role_name = self._mode.get("required_discord_role_name")
        if role_name:
            stats_data.append(("🎫", "Необходимая роль", role_name, _ACCENT, "ticket.svg", ""))
        from mode_event import get_event_parts
        ev_label, ev_value = get_event_parts(self._mode)
        if ev_label:
            stats_data.append(("🕐", ev_label, ev_value, _ACCENT, "clock.svg", ""))
        for icon, label, value, color, svg, url in stats_data:
            right_lay.addWidget(StatBlock(icon, label, value, color, svg, url))

        right_lay.addStretch()

        bottom_row.addWidget(right)
        root.addWidget(bottom, 1)
        self._update_play_btn()
        # Если загрузка уже идёт — подключиться к ней
        from download_manager import DownloadManager, DownloadTask
        existing = DownloadManager.instance().get(self._mode.get("id", ""))
        if existing and existing.state in (DownloadTask.RUNNING, DownloadTask.QUEUED):
            self._bind_task(existing)

    def refresh_playtime(self):
        if not self._pt_hours_lbl or not self._pt_last_lbl:
            return
        import playtime as pt
        pt_data = pt.get(self._mode.get("id", ""))
        self._pt_hours_lbl.setText(pt.format_hours(pt_data["seconds"]) if pt_data.get("seconds", 0) > 0 else "—")
        self._pt_last_lbl.setText(pt.format_last_played(pt_data.get("last_played")))
        # После игры мог измениться наигранный порог и появиться новые скриншоты.
        self._played = (pt_data.get("seconds", 0) or 0) >= 60
        if hasattr(self, "_tab_shots"):
            self._tab_shots.setVisible(self._played)
            if self._played:
                if self._shots_page.isVisible():
                    self._load_shots()          # вкладка открыта — обновляем сразу
                else:
                    self._shots_loaded = False  # иначе пересканируем при следующем открытии

    @staticmethod
    def _info_tab_style(active: bool) -> str:
        # Активная вкладка: яркий жирный текст + лёгкая подложка (скруглённый верх)
        # + зелёное подчёркивание (в тон кнопке «Играть») на базовой линии.
        if active:
            return ("QPushButton { color: #FFFFFF; font-size: 10px; font-weight: 800;"
                    " letter-spacing: 1.2px; background: rgba(255,255,255,13);"
                    " border: none; border-bottom: 2px solid #33C15A;"
                    " border-top-left-radius: 6px; border-top-right-radius: 6px;"
                    " padding: 4px 12px 7px 12px; }")
        return ("QPushButton { color: #5A6270; font-size: 10px; font-weight: 700;"
                " letter-spacing: 1.2px; background: transparent; border: none;"
                " border-bottom: 2px solid transparent;"
                " border-top-left-radius: 6px; border-top-right-radius: 6px;"
                " padding: 4px 12px 7px 12px; }"
                " QPushButton:hover { color: #8899aa; background: rgba(255,255,255,6); }")

    def _on_tab_click(self, which: str):
        """Клик пользователя по вкладке — запоминаем, чтобы авто-логика (пустые
        новости → описание) больше не перебивала выбор."""
        self._user_switched_tab = True
        self._switch_info_tab(which)

    def _switch_info_tab(self, which: str):
        """Переключение Главная / Новости / Скриншоты / Описание."""
        is_main = which == "main"
        is_news = which == "news"
        is_shots = which == "shots"
        is_desc = which == "desc"
        self._main_page.setVisible(is_main)
        self._news_page.setVisible(is_news)
        self._shots_page.setVisible(is_shots)
        self._desc_scroll.setVisible(is_desc)
        self._tab_main.setStyleSheet(self._info_tab_style(is_main))
        self._tab_news.setStyleSheet(self._info_tab_style(is_news))
        self._tab_shots.setStyleSheet(self._info_tab_style(is_shots))
        self._tab_desc.setStyleSheet(self._info_tab_style(is_desc))
        if is_shots and not self._shots_loaded:
            self._shots_loaded = True
            self._load_shots()

    def _update_play_btn(self):
        if self._mode.get("maintenance"):
            self._play_btn.set_icon_svg("wrench.svg")
            self._play_btn.setText("  Тех. работы")
            self._play_btn._color = QColor("#6B7280")
            self._play_btn.setEnabled(False)
            self._play_btn.update()
            return
        self._play_btn.setEnabled(True)
        if not is_installed(self._mode):
            self._play_btn.set_icon_svg("download.svg")
            self._play_btn.setText("  Скачать")
            self._play_btn._color = QColor("#00B8D9")
            self._play_btn.update()
            size_mb = self._mode.get("modpack", {}).get("size_mb") or self._mode.get("size_mb")
            if size_mb:
                self._size_lbl.setText(f"{size_mb} МБ")
                self._size_widget.setVisible(True)
            else:
                self._size_widget.setVisible(False)
        elif needs_update(self._mode):
            self._play_btn.set_icon_svg("download.svg")
            self._play_btn.setText("  Обновить")
            self._play_btn._color = QColor("#F59E0B")
            self._play_btn.update()
            self._size_widget.setVisible(False)
        else:
            self._play_btn.set_icon_svg("play.svg")
            self._play_btn.setText("  Играть")
            self._play_btn._color = QColor("#3FB950")
            self._play_btn.update()
            self._size_widget.setVisible(False)


    def set_game_launching(self):
        """Промежуточное состояние — процесс запущен, окно ещё не появилось."""
        self._play_btn.set_running(False)
        self._play_btn.setEnabled(False)
        self._play_btn.setText("  Запуск игры...")
        self._play_btn._color = QColor("#F59E0B")
        self._play_btn.update()

    def set_game_running(self, running: bool):
        if running:
            self._play_btn.set_icon_svg("gamepad.svg")
            self._play_btn.setText("  Игра запущена")
            self._play_btn._color = QColor("#6E40C9")
            self._play_btn.setEnabled(True)
            self._play_btn.set_running(True)
            self._play_btn.update()
        else:
            self._play_btn.set_running(False)
            self._play_btn.setEnabled(True)
            self._update_play_btn()

    def _load_assets(self):
        banner_url = self._mode.get("banner_url") or self._mode.get("background_url", "")
        if banner_url:
            AssetCache.load(banner_url, lambda u, px: self._banner.set_image(px))
        title_logo_url = self._mode.get("title_logo_url", "")
        if title_logo_url:
            AssetCache.load(title_logo_url, lambda u, px: self._banner_container.set_title_logo(px))
        video_url = self._mode.get("video_url", "")
        if video_url:
            self._banner_container.start_video(video_url)
    def _load_news(self):
        """Показывает кэш мгновенно (если есть), затем обновляет с сервера в фоне."""
        import threading, api
        mode_id = self._mode.get("id", "")
        cached = api.load_cached_mode_news(mode_id)
        self._news_had_cache = cached is not None
        if cached is not None:
            self._render_news(cached, auto_switch=False)   # кэш — рисуем тихо, без смены вкладки
        def _run():
            items = api.fetch_mode_news(mode_id)
            self._news_loaded.emit(items)
        threading.Thread(target=_run, daemon=True).start()

    def _make_feed_page(self, placeholder: str):
        """Страница-лента (QScrollArea + VBox с плейсхолдером и stretch).
        Возвращает (scroll_area, layout, empty_label)."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 2, 24, 8)
        lay.setSpacing(12)
        empty = QLabel(placeholder)
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setStyleSheet("color: #555570; font-size: 13px; background: transparent;")
        lay.addWidget(empty)
        lay.addStretch()
        scroll.setWidget(w)
        return scroll, lay, empty

    def _fill_feed(self, layout, empty_label, items):
        # удаляем старые карточки (empty_label и финальный stretch не трогаем)
        for i in reversed(range(layout.count())):
            w = layout.itemAt(i).widget()
            if isinstance(w, NewsCard):
                layout.takeAt(i)
                w.deleteLater()
        empty_label.setText("Пусто")
        empty_label.setVisible(not items)
        for n in items:
            card = NewsCard(n)
            card.open_requested.connect(self._open_news_reader)
            layout.insertWidget(layout.count() - 1, card)

    def _open_news_reader(self, data: dict):
        self._news_reader = NewsReader(data, self.window())
        self._news_reader.show()
        self._news_reader.setFocus()

    def _render_news(self, items: list, auto_switch: bool = True):
        self._has_news = bool(items)
        self._news_items = items
        self._fill_feed(self._news_lay, self._news_empty, items)   # вкладка «Новости»
        self._render_main()                                        # «Главная» = новости + посты
        # Пусто (ни новостей, ни постов) и ПЕРВАЯ загрузка (кэша не было) → «Описание».
        if (not items and not self._feed_posts and auto_switch and not self._user_switched_tab
                and not getattr(self, "_news_had_cache", False)):
            self._switch_info_tab("desc")

    def _load_feed_posts(self):
        """Тянет посты-скриншоты (свои + друзей) в фоне для ленты «Главная»."""
        import threading, screenshots_client
        def _run():
            posts = screenshots_client.fetch_feed()
            self._feed_loaded.emit(posts)
        threading.Thread(target=_run, daemon=True).start()

    def _on_feed_loaded(self, posts: list):
        self._feed_posts = posts
        self._render_main()

    def _render_main(self):
        """Лента «Главная»: новости + посты-скриншоты (группами автор+день),
        свежие сверху по дате."""
        lay = self._main_lay
        for i in reversed(range(lay.count())):
            w = lay.itemAt(i).widget()
            if isinstance(w, (NewsCard, FeedGroupCard)):
                lay.takeAt(i)
                w.deleteLater()
        # Группируем посты по автору+дню (посты приходят свежие сверху → ts = первая дата).
        groups, order = {}, []
        for p in self._feed_posts:
            key = ((p.get("author_uuid") or ""), (p.get("created_at") or "")[:10])
            g = groups.get(key)
            if g is None:
                g = {"author_uuid": p.get("author_uuid", ""),
                     "author_name": p.get("author_name", "Игрок"),
                     "mine": p.get("mine", False),
                     "date": p.get("created_at", ""),
                     "ts": p.get("created_at", ""),
                     "posts": []}
                groups[key] = g
                order.append(key)
            g["posts"].append(p)
        entries = [((n.get("published_at") or ""), "news", n) for n in self._news_items]
        entries += [(groups[k]["ts"], "group", groups[k]) for k in order]
        entries.sort(key=lambda e: e[0], reverse=True)
        self._main_empty.setText("Пусто")
        self._main_empty.setVisible(not entries)
        for _, kind, data in entries:
            if kind == "news":
                card = NewsCard(data)
                card.open_requested.connect(self._open_news_reader)
            else:
                card = FeedGroupCard(data)
                card.open_requested.connect(self._open_feed_viewer)
            lay.insertWidget(lay.count() - 1, card)

    def _open_feed_viewer(self, items: list, index: int):
        self._viewer = ScreenshotViewer(items, index, self.window(), allow_publish=False)
        self._viewer.show()
        self._viewer.setFocus()

    # ── Скриншоты ─────────────────────────────────────────────────────────────

    def _can_publish(self) -> bool:
        """Публиковать можно только с привязанным Discord."""
        try:
            import auth_client
            return bool(auth_client._load_settings().get("discord_id"))
        except Exception:
            return False

    def _shots_dir(self):
        from config import MINECRAFT_DIR
        return MINECRAFT_DIR / self._mode.get("id", "") / "screenshots"

    def _scan_shots(self) -> list:
        d = self._shots_dir()
        if not d.is_dir():
            return []
        exts = (".png", ".jpg", ".jpeg", ".webp")
        files = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in exts]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)   # новые сверху
        return files

    def _load_shots(self):
        """Пересобирает сетку миниатюр из папки скриншотов режима."""
        # чистим текущие плитки
        while self._shots_flow.count():
            it = self._shots_flow.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        files = self._scan_shots()
        self._shot_files = [str(p) for p in files]
        self._shots_empty.setVisible(not files)
        can_pub = self._can_publish()
        for path in self._shot_files:
            tile = ShotTile(path, can_publish=can_pub)
            tile.clicked.connect(self._open_shot_viewer)
            tile.publish_requested.connect(self._open_publish_dialog)
            self._shots_flow.addWidget(tile)

    def _open_shot_viewer(self, path: str):
        files = getattr(self, "_shot_files", [])
        if not files:
            return
        try:
            idx = files.index(path)
        except ValueError:
            idx = 0
        items = [{"src": f, "desc": ""} for f in files]
        self._viewer = ScreenshotViewer(items, idx, self.window(), allow_publish=self._can_publish())
        self._viewer.publish_requested.connect(self._open_publish_dialog)
        self._viewer.show()
        self._viewer.setFocus()

    def _open_publish_dialog(self, path: str):
        if not path:
            return
        dlg = PublishShotDialog(path, self.window())
        dlg.published.connect(self._load_feed_posts)   # опубликовали → обновить ленту
        dlg.exec()

    def _on_play_or_install(self):
        from download_manager import DownloadManager, DownloadTask
        existing = DownloadManager.instance().get(self._mode["id"])
        if existing and existing.state in (DownloadTask.RUNNING, DownloadTask.QUEUED):
            self._bind_task(existing)
            return
        if not is_installed(self._mode) or needs_update(self._mode):
            self._start_install()
        else:
            self.play_requested.emit(self._mode)

    def _start_install(self):
        from download_manager import DownloadManager, DownloadTask
        dm = DownloadManager.instance()
        task = dm.enqueue(self._mode, self._launcher_config)
        self._bind_task(task)

    def start_verify(self, mode: dict):
        """Проверка целостности файлов сборки — через общий менеджер загрузок
        (видна во вкладке «Загрузки», блокирует «Играть»)."""
        from download_manager import DownloadManager, DownloadTask
        dm = DownloadManager.instance()
        task = dm.get(mode["id"])
        if not (task and task.state in (DownloadTask.QUEUED, DownloadTask.RUNNING)):
            task = dm.enqueue(mode, self._launcher_config,
                              title=f"{mode.get('name', mode['id'])} · проверка", kind="verify")
        self._bind_task(task)

    def _bind_task(self, task):
        from download_manager import DownloadTask, DownloadManager
        is_verify = getattr(task, "kind", "install") == "verify"
        self._play_btn.setEnabled(False)
        self._play_btn.set_icon_svg("refresh.svg" if is_verify else "download.svg")
        self._play_btn.setText("  Проверка..." if is_verify else "  Загрузка...")
        self._play_btn._color = QColor("#FFB454" if is_verify else "#00B8D9")
        self._play_btn.update()
        self._progress_frame.show()

        task.progress.connect(self._on_install_progress)
        task.done.connect(self._on_install_done)
        task.error.connect(self._on_install_error)

        def _on_removed(mode_id: str):
            if mode_id == self._mode.get("id"):
                self._on_install_cancelled()
        DownloadManager.instance().task_removed.connect(_on_removed)

        if task.state == DownloadTask.DONE:
            self._on_install_done()
        elif task.state == DownloadTask.ERROR:
            self._on_install_error(task.error_msg)
        elif task.state in (DownloadTask.RUNNING, DownloadTask.QUEUED):
            self._on_install_progress(task.msg, task.frac)

    @pyqtSlot(str, float)
    def _on_install_progress(self, msg: str, frac: float):
        self._progress_label.setText(msg)
        self._progress_bar.setValue(int(frac * 1000))

    @pyqtSlot()
    def _on_install_done(self):
        self._progress_frame.hide()
        self._play_btn.setEnabled(True)
        self._update_play_btn()

    @pyqtSlot(str)
    def _on_install_error(self, err: str):
        self._progress_frame.hide()
        self._play_btn.setEnabled(True)
        self.log_requested.emit(err)

    def _on_install_cancelled(self):
        self._progress_frame.hide()
        self._play_btn.setEnabled(True)
        self._update_play_btn()


# ── ModeThumb — эскиз режима в сетке ─────────────────────────────────────────

class ModeThumb(QWidget):
    clicked = pyqtSignal(dict)

    def __init__(self, mode: dict, parent=None):
        super().__init__(parent)
        self._mode = mode
        self._banner_px: QPixmap | None = None
        self._hover = False
        self.setFixedHeight(150)
        self.setMinimumWidth(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        url = mode.get("banner_url") or mode.get("background_blur_url", "")
        if url:
            AssetCache.load(url, self._on_banner)

    def _on_banner(self, url: str, px: QPixmap):
        self._banner_px = px
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, 12, 12)
        p.setClipPath(path)

        if self._banner_px:
            scaled = self._banner_px.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(0, 0, scaled)
        else:
            p.fillRect(0, 0, w, h, QColor(22, 27, 34))

        # Затемнение снизу
        grad = QLinearGradient(0, h * 0.4, 0, h)
        grad.setColorAt(0, QColor(10, 13, 18, 0))
        grad.setColorAt(1, QColor(10, 13, 18, 210))
        p.fillRect(0, 0, w, h, grad)

        # Hover overlay
        if self._hover:
            p.fillRect(0, 0, w, h, QColor(255, 255, 255, 15))

        p.setClipping(False)

        # Название
        p.setFont(QFont("Rubik", 12, QFont.Weight.Bold))
        p.setPen(QColor(230, 237, 243))
        p.drawText(12, h - 42, w - 24, 20,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._mode.get("name", ""))

        # Жанр / событие
        from mode_event import get_event_text
        event_text = get_event_text(self._mode)
        sub_text = event_text if event_text else self._mode.get("genre", "")
        sub_color = QColor(148, 163, 184) if event_text else QColor(125, 133, 144)
        p.setFont(QFont("Rubik", 10))
        p.setPen(sub_color)
        p.drawText(12, h - 24, w - 24, 14,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   sub_text)

    def enterEvent(self, e): self._hover = True; self.update()
    def leaveEvent(self, e): self._hover = False; self.update()
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._mode)


class AllModesView(QWidget):
    mode_selected = pyqtSignal(dict)

    def __init__(self, modes: list, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 20, 48, 20)
        root.setSpacing(16)

        header = QLabel("ВСЕ РЕЖИМЫ")
        header.setStyleSheet("color: #4A5260; font-size: 10px; font-weight: 700; "
                             "letter-spacing: 1.5px; background: transparent;")
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        grid_w = QWidget()
        grid_w.setStyleSheet("background: transparent;")
        from PyQt6.QtWidgets import QGridLayout
        grid = QGridLayout(grid_w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)

        cols = 3
        for col in range(cols):
            grid.setColumnStretch(col, 1)

        for i, mode in enumerate(modes):
            thumb = ModeThumb(mode)
            thumb.clicked.connect(self.mode_selected)
            grid.addWidget(thumb, i // cols, i % cols)

        grid.setRowStretch(grid.rowCount(), 1)
        scroll.setWidget(grid_w)
        root.addWidget(scroll, 1)


# ── ContentPanel (анимированный контейнер) ────────────────────────────────────

class ContentPanel(QWidget):
    play_requested = pyqtSignal(dict)
    settings_requested = pyqtSignal(dict)
    log_requested = pyqtSignal(str)
    mode_thumb_selected = pyqtSignal(dict)
    discord_link_requested = pyqtSignal()
    _recheck_done = pyqtSignal(dict)  # маршалинг результата перепроверки роли в UI-поток

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current: QWidget | None = None
        self._anim_grp = None
        self._launcher_config: dict = {}
        self._recheck_done.connect(self._on_recheck_done)

    def _recheck_role(self, mode: dict):
        """Живая перепроверка роли по кнопке на экране блокировки (в фоне)."""
        import threading, auth_client
        def _run():
            try:
                auth_client.refresh_discord_roles()
            except Exception:
                pass
            self._recheck_done.emit(mode)
        threading.Thread(target=_run, daemon=True).start()

    def _on_recheck_done(self, mode: dict):
        # Роли обновлены — перерисовываем режим (если роль появилась, откроется ModeView;
        # если всё ещё нет — снова экран блокировки с активной кнопкой).
        if isinstance(self._current, RoleBlockedView):
            self.show_mode(mode)

    def set_launcher_config(self, config: dict):
        self._launcher_config = config

    def refresh_playtime(self):
        if isinstance(self._current, ModeView):
            self._current.refresh_playtime()

    def current_mode_id(self) -> str | None:
        """id режима, показанного сейчас (ModeView или экран блокировки), иначе None."""
        v = self._current
        if isinstance(v, (ModeView, RoleBlockedView)):
            return v._mode.get("id")
        return None

    def show_all_modes(self, modes: list):
        new_view = AllModesView(modes, self)
        new_view.mode_selected.connect(self.mode_thumb_selected)
        self._switch_to(new_view)

    def refresh_current_view(self):
        if isinstance(self._current, ModeView):
            self._current._update_play_btn()

    def reload_news(self):
        """SSE 'news_updated' — перечитать ленту новостей открытого режима."""
        if isinstance(self._current, ModeView):
            self._current._load_news()

    def reload_feed(self):
        """SSE 'feed_updated' — перечитать посты-скриншоты ленты «Главная»."""
        if isinstance(self._current, ModeView):
            self._current._load_feed_posts()

    def show_mode(self, mode: dict):
        role_id = mode.get("required_discord_role", "")
        if role_id:
            import auth_client
            discord_id = auth_client._load_settings().get("discord_id", "")
            if not discord_id:
                v = RoleBlockedView(mode, "not_linked", self._launcher_config, self)
                v.link_discord_requested.connect(self.discord_link_requested)
                self._switch_to(v)
                return
            if not auth_client.has_discord_role(role_id):
                v = RoleBlockedView(mode, "no_role", self._launcher_config, self)
                v.recheck_requested.connect(lambda m=mode: self._recheck_role(m))
                self._switch_to(v)
                return

        new_view = ModeView(mode, self._launcher_config, self)
        new_view.play_requested.connect(self.play_requested)
        new_view.settings_requested.connect(self.settings_requested)
        new_view.log_requested.connect(self.log_requested)
        self._switch_to(new_view)

    def _switch_to(self, new_view: QWidget):
        old = self._current
        new_view.resize(self.size())
        new_view.move(0, 0)

        # Показываем с opacity=0, чтобы Qt посчитал layout до анимации
        fx_in = QGraphicsOpacityEffect(new_view)
        fx_in.setOpacity(0.0)
        new_view.setGraphicsEffect(fx_in)
        new_view.show()

        self._current = new_view

        from PyQt6.QtCore import QTimer
        def _start_anim():
            grp = QParallelAnimationGroup(self)

            fade_in = QPropertyAnimation(fx_in, b"opacity")
            fade_in.setDuration(450)
            fade_in.setStartValue(0.0)
            fade_in.setEndValue(1.0)
            fade_in.setEasingCurve(QEasingCurve.Type.InOutCubic)
            grp.addAnimation(fade_in)

            if old:
                fx_out = QGraphicsOpacityEffect(old)
                old.setGraphicsEffect(fx_out)
                fade_out = QPropertyAnimation(fx_out, b"opacity")
                fade_out.setDuration(300)
                fade_out.setStartValue(1.0)
                fade_out.setEndValue(0.0)
                fade_out.setEasingCurve(QEasingCurve.Type.OutCubic)
                grp.addAnimation(fade_out)
                def _cleanup_old(w=old):
                    if isinstance(w, ModeView):
                        w._banner_container.stop()
                    w.deleteLater()
                grp.finished.connect(_cleanup_old)

            grp.start()
            self._anim_grp = grp

        QTimer.singleShot(0, _start_anim)

    def pause_video(self):
        if isinstance(self._current, ModeView):
            self._current._banner_container.pause()

    def resume_video(self):
        if isinstance(self._current, ModeView):
            self._current._banner_container.resume()

    def set_game_launching(self, mode_id: str = None):
        # Меняем кнопку ТОЛЬКО если показан именно запускаемый режим (иначе запуск
        # одного режима менял бы кнопку у другого, открытого в окне).
        if isinstance(self._current, ModeView) and (
                mode_id is None or self._current._mode.get("id") == mode_id):
            self._current.set_game_launching()

    def set_game_running(self, running: bool, mode_id: str = None):
        if isinstance(self._current, ModeView) and (
                mode_id is None or self._current._mode.get("id") == mode_id):
            self._current.set_game_running(running)

    def start_install(self):
        if isinstance(self._current, ModeView):
            self._current._start_install()

    def start_verify(self, mode: dict):
        if isinstance(self._current, ModeView):
            self._current.start_verify(mode)

    def connect_kill(self, callback):
        if isinstance(self._current, ModeView):
            try:
                self._current._play_btn.kill_requested.disconnect()
            except Exception:
                pass
            self._current._play_btn.kill_requested.connect(callback)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current:
            self._current.resize(self.size())
            self._current.move(0, 0)
