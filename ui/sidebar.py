import math
import threading
from PyQt6.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve, pyqtProperty, QTimer
from PyQt6.QtGui import (
    QPainter, QColor, QFont, QPixmap, QLinearGradient,
    QRadialGradient, QPainterPath, QBrush, QPen
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel, QFrame
)
from assets_cache import AssetCache
from api import ping_server
from config import SIDEBAR_WIDTH
from download_manager import DownloadManager, DownloadTask


class ModeCard(QWidget):
    clicked = pyqtSignal(dict)

    def __init__(self, mode: dict, parent=None):
        super().__init__(parent)
        self._mode = mode
        self._selected = False
        self._hover_prog = 0.0
        self._logo_px: QPixmap | None = None
        self._online: str | None = None

        self.setFixedHeight(90)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContentsMargins(8, 4, 8, 4)

        self._anim = QPropertyAnimation(self, b"hoverProg")
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._load_logo()
        self._load_online()
        # Периодически обновляем онлайн (раньше пинговали один раз при создании
        # карточки → «0/60» висело часами). Только для режимов с server_ip.
        if self._mode.get("server_ip"):
            self._online_timer = QTimer(self)
            self._online_timer.timeout.connect(self._load_online)
            self._online_timer.setInterval(45_000)   # раз в 45 сек
            self._online_timer.start()

    def get_hover_prog(self): return self._hover_prog
    def set_hover_prog(self, v):
        self._hover_prog = v
        self.update()
    hoverProg = pyqtProperty(float, get_hover_prog, set_hover_prog)

    def set_selected(self, v: bool):
        self._selected = v
        self.update()

    def _load_logo(self):
        url = self._mode.get("logo_url", "")
        if url:
            AssetCache.load(url, self._on_logo)

    def _on_logo(self, url: str, px: QPixmap):
        self._logo_px = px.scaled(60, 60,
                                  Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
        self.update()

    def _load_online(self):
        ip = self._mode.get("server_ip", "")
        if not ip:
            return
        def _ping():
            result = ping_server(ip)
            if result:
                self._online = result
                self.update()
        threading.Thread(target=_ping, daemon=True).start()

    def update_mode(self, mode: dict):
        self._mode = mode
        self._online = None
        self._connector_px = None
        self._load_logo()
        self._load_online()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        hp = self._hover_prog

        # Скруглённый прямоугольник карточки
        pad = 4
        card_rect_x, card_rect_y = pad, pad
        card_rect_w, card_rect_h = w - pad * 2, h - pad * 2

        path = QPainterPath()
        path.addRoundedRect(card_rect_x, card_rect_y, card_rect_w, card_rect_h, 10, 10)

        # Фон карточки
        if self._selected:
            bg = QColor(63, 185, 80, 18)
        elif hp > 0:
            bg = QColor(28, 33, 40, int(220 * hp))
        else:
            bg = QColor(0, 0, 0, 0)

        p.setBrush(bg)

        # Рамка
        if self._selected:
            p.setPen(QPen(QColor(63, 185, 80, 200), 1.5))
        elif hp > 0:
            p.setPen(QPen(QColor(255, 255, 255, int(15 * hp)), 1))
        else:
            p.setPen(Qt.PenStyle.NoPen)

        p.drawPath(path)

        # Glow при selected
        if self._selected:
            glow = QRadialGradient(card_rect_x + 30, card_rect_y + card_rect_h / 2, 60)
            glow.setColorAt(0, QColor(63, 185, 80, 20))
            glow.setColorAt(1, QColor(63, 185, 80, 0))
            p.setClipPath(path)
            p.setBrush(glow)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRect(card_rect_x, card_rect_y, card_rect_w, card_rect_h)
            p.setClipping(False)

        # Иконка (60×60) слева
        icon_x = card_rect_x + 10
        icon_y = (h - 60) // 2
        if self._logo_px:
            icon_path = QPainterPath()
            icon_path.addRoundedRect(icon_x, icon_y, 60, 60, 10, 10)
            p.setClipPath(icon_path)
            p.drawPixmap(icon_x, icon_y, self._logo_px)
            p.setClipping(False)
        else:
            p.setBrush(QColor(37, 43, 51))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(icon_x, icon_y, 60, 60, 10, 10)
            p.setPen(QColor(80, 90, 110))
            p.setFont(QFont("Rubik", 18, QFont.Weight.Bold))
            p.drawText(icon_x, icon_y, 60, 60, Qt.AlignmentFlag.AlignCenter,
                       self._mode.get("name", "?")[:1].upper())


        # Текст
        text_x = icon_x + 60 + 12
        text_w = w - text_x - pad - 8

        # Название
        p.setPen(QColor(230, 237, 243) if self._selected or hp > 0.3 else QColor(180, 190, 205))
        p.setFont(QFont("Rubik", 12, QFont.Weight.Bold))
        name = self._mode.get("name", "")
        p.drawText(text_x, card_rect_y + 8, text_w, 20,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)

        # Жанр
        p.setPen(QColor(125, 133, 144))
        p.setFont(QFont("Rubik", 10))
        genre = self._mode.get("genre", "")
        p.drawText(text_x, card_rect_y + 28, text_w, 16,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, genre)

        # Онлайн
        if self._online:
            p.setPen(QColor(63, 185, 80))
            p.setFont(QFont("Rubik", 10))
            p.drawText(text_x, card_rect_y + 44, text_w, 16,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       f"● {self._online}")
        elif self._mode.get("server_ip", ""):
            p.setPen(QColor(80, 90, 100))
            p.setFont(QFont("Rubik", 10))
            p.drawText(text_x, card_rect_y + 44, text_w, 16,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       "● offline")

        # Событие под онлайном
        from mode_event import get_event_text
        event_text = get_event_text(self._mode)
        if event_text:
            p.setPen(QColor(148, 163, 184))
            ev_font = QFont("Rubik", 10)
            p.setFont(ev_font)
            elided = p.fontMetrics().elidedText(event_text, Qt.TextElideMode.ElideRight, text_w)
            p.drawText(text_x, card_rect_y + 60, text_w, 16,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       elided)

    def enterEvent(self, event):
        self._anim.stop()
        self._anim.setStartValue(self._hover_prog)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def leaveEvent(self, event):
        self._anim.stop()
        self._anim.setStartValue(self._hover_prog)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._mode)


class AllModesBtn(QWidget):
    """Кнопка 'Все режимы' в сайдбаре."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected = False
        self._hover = False
        self.setFixedHeight(40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_selected(self, v: bool):
        self._selected = v
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pad = 4
        path = QPainterPath()
        path.addRoundedRect(pad, 2, w - pad * 2, h - 4, 8, 8)

        if self._selected:
            p.setBrush(QColor(63, 185, 80, 22))
            p.setPen(QPen(QColor(63, 185, 80, 180), 1.5))
        elif self._hover:
            p.setBrush(QColor(28, 33, 40, 180))
            p.setPen(QPen(QColor(255, 255, 255, 15), 1))
        else:
            p.setBrush(QColor(0, 0, 0, 0))
            p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)

        color = "#E6EDF3" if self._selected else "#A0AAB9"
        p.setPen(QColor(color))
        p.setFont(QFont("Rubik", 11, QFont.Weight.Bold if self._selected else QFont.Weight.Normal))
        try:
            from ui.assets import svg_icon as _svg
            ico = _svg("apps.svg", color, 16).pixmap(16, 16)
            p.drawPixmap(14, (h - 16) // 2, ico)
        except Exception:
            pass
        p.drawText(36, 0, w - 36, h, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "Все режимы")

    def enterEvent(self, e): self._hover = True; self.update()
    def leaveEvent(self, e): self._hover = False; self.update()
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class _UpdateBanner(QWidget):
    """Кликабельная строка обновления в стиле DownloadsBtn."""
    clicked = pyqtSignal()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = False
        self._version = ""
        self._pulse = 0.0          # 0.0 .. 1.0 яркость пульса
        self._pulse_dir = 1
        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

    def set_version(self, v: str):
        self._version = v
        self.update()

    def start_pulse(self):
        self._pulse = 0.0
        self._pulse_dir = 1
        self._timer.start()

    def _tick(self):
        self._pulse += 0.04 * self._pulse_dir
        if self._pulse >= 1.0:
            self._pulse = 1.0
            self._pulse_dir = -1
        elif self._pulse <= 0.0:
            self._pulse = 0.0
            self._pulse_dir = 1
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _):
        from PyQt6.QtGui import QPainter, QPainterPath, QPen, QColor, QFont
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pad = 4

        # Фон
        path = QPainterPath()
        path.addRoundedRect(pad, 2, w - pad * 2, h - 4, 8, 8)
        alpha = int(30 + self._pulse * 25)
        p.setBrush(QColor(91, 140, 255, alpha if not self._hover else alpha + 40))
        border_alpha = int(50 + self._pulse * 60)
        p.setPen(QPen(QColor(91, 140, 255, border_alpha), 1))
        p.drawPath(path)

        # Иконка
        try:
            from ui.assets import svg_icon as _svg
            ico = _svg("refresh.svg", "#5B8CFF", 14).pixmap(14, 14)
            p.drawPixmap(14, (h - 14) // 2, ico)
        except Exception:
            pass

        # Текст
        label = f"Обновление {self._version}" if self._version else "Доступно обновление"
        p.setPen(QColor(91, 140, 255))
        p.setFont(QFont("Segoe UI", 10))
        p.drawText(36, 0, w - 40, h,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)


class DownloadsBtn(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = False
        self._count = 0
        self._has_error = False
        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        dm = DownloadManager.instance()
        dm.task_added.connect(self._refresh)
        dm.task_updated.connect(self._refresh)
        dm.task_removed.connect(lambda _: self._refresh())

    def _refresh(self, *_):
        tasks = DownloadManager.instance().tasks
        active = [t for t in tasks if t.state in (DownloadTask.RUNNING, DownloadTask.QUEUED)]
        self._count = len(active)
        self._has_error = any(t.state == DownloadTask.ERROR for t in tasks)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pad = 4
        path = QPainterPath()
        path.addRoundedRect(pad, 2, w - pad * 2, h - 4, 8, 8)
        if self._hover:
            p.setBrush(QColor(28, 33, 40, 180))
            p.setPen(QPen(QColor(255, 255, 255, 15), 1))
        else:
            p.setBrush(QColor(0, 0, 0, 0))
            p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)

        hex_color = "#ff5c5c" if self._has_error else "#5B8CFF"
        p.setPen(QColor(hex_color))
        p.setFont(QFont("Segoe UI", 10))
        try:
            from ui.assets import svg_icon as _svg
            ico_name = "cross.svg" if self._has_error else "download.svg"
            ico = _svg(ico_name, hex_color, 16).pixmap(16, 16)
            p.drawPixmap(14, (h - 16) // 2, ico)
        except Exception:
            pass
        count_str = f"  ({self._count})" if self._count else ""
        p.drawText(36, 0, w - 40, h, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, f"Загрузки{count_str}")

    def enterEvent(self, e): self._hover = True; self.update()
    def leaveEvent(self, e): self._hover = False; self.update()
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class _SectionHeader(QWidget):
    """Заголовок секции в сайдбаре: разделительная полоска + название категории."""
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 4)
        lay.setSpacing(6)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background: rgba(255,255,255,10); border: none; max-height: 1px;")
        lbl = QLabel(text.upper())
        lbl.setStyleSheet("color: #8888aa; font-size: 10px; font-weight: 700; "
                          "letter-spacing: 1px; background: transparent; border: none;")
        lay.addWidget(line)
        lay.addWidget(lbl)


class Sidebar(QWidget):
    mode_selected = pyqtSignal(dict)
    all_modes_clicked = pyqtSignal()
    downloads_clicked = pyqtSignal()
    update_clicked = pyqtSignal()      # клик по баннеру обновления -> перезапуск

    def __init__(self, modes: list, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(SIDEBAR_WIDTH)
        self._cards: list[ModeCard] = []
        self._current_id: str | None = None
        self._all_btn: AllModesBtn | None = None
        self._build_ui(modes)

    def _build_ui(self, modes: list):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 0)
        root.setSpacing(0)


        # Кнопка "Все режимы"
        self._all_btn = AllModesBtn()
        self._all_btn.clicked.connect(self._on_all_clicked)
        root.addWidget(self._all_btn)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch()

        scroll.setWidget(self._list_widget)
        root.addWidget(scroll, 1)

        self._populate_list(modes)

        if self._cards:
            self._select_card(self._cards[0])

        # ── Нижняя часть сайдбара ─────────────────────────────────────────────
        bottom = QWidget()
        bottom.setStyleSheet("background: transparent;")
        bottom_lay = QVBoxLayout(bottom)
        bottom_lay.setContentsMargins(8, 6, 8, 8)
        bottom_lay.setSpacing(6)

        # Разделитель
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: rgba(255,255,255,8); border: none; max-height: 1px;")
        bottom_lay.addWidget(sep)

        self._update_banner = _UpdateBanner()
        self._update_banner.hide()
        self._update_banner.clicked.connect(self.update_clicked)
        bottom_lay.addWidget(self._update_banner)

        self._downloads_btn = DownloadsBtn()
        self._downloads_btn.clicked.connect(self.downloads_clicked)
        bottom_lay.addWidget(self._downloads_btn)

        root.addWidget(bottom)

    def _add_card(self, mode: dict):
        card = ModeCard(mode)
        card.clicked.connect(lambda m: self._select_card_by_mode(m))
        self._list_layout.insertWidget(self._list_layout.count() - 1, card)
        self._cards.append(card)

    @staticmethod
    def _category(mode: dict) -> str:
        return (mode.get("category") or "minigame").lower()

    def _add_header(self, text: str):
        header = _SectionHeader(text)
        self._list_layout.insertWidget(self._list_layout.count() - 1, header)

    def _populate_list(self, modes: list):
        """Строит список: сначала серверы, потом разделитель+«Мини игры», потом мини-игры."""
        while self._list_layout.count() > 1:          # чистим всё, кроме хвостового stretch
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._cards = []
        servers   = [m for m in modes if self._category(m) == "server"]
        minigames = [m for m in modes if self._category(m) != "server"]
        if servers:
            self._add_header("Сервер")
            for m in servers:
                self._add_card(m)
        if minigames:
            self._add_header("Мини игры")
            for m in minigames:
                self._add_card(m)

    def _select_card_by_mode(self, mode: dict):
        card = next((c for c in self._cards if c._mode.get("id") == mode.get("id")), None)
        if card:
            self._select_card(card)

    def downloads_btn_pos_in(self, target: QWidget) -> "QPoint":
        """Возвращает позицию левого верхнего угла кнопки загрузок в системе координат target."""
        from PyQt6.QtCore import QPoint
        return self._downloads_btn.mapTo(target, QPoint(0, 0))

    def highlight_mode(self, mode: dict):
        """Визуально выделить карточку без эмита сигнала."""
        if self._all_btn:
            self._all_btn.set_selected(False)
        for c in self._cards:
            c.set_selected(c._mode.get("id") == mode.get("id"))
        self._current_id = mode.get("id")

    def _on_all_clicked(self):
        for c in self._cards:
            c.set_selected(False)
        self._current_id = None
        if self._all_btn:
            self._all_btn.set_selected(True)
        self.all_modes_clicked.emit()

    def select_all(self):
        self._on_all_clicked()

    def _select_card(self, card: ModeCard):
        if self._all_btn:
            self._all_btn.set_selected(False)
        for c in self._cards:
            c.set_selected(False)
        card.set_selected(True)
        self._current_id = card._mode.get("id")
        self.mode_selected.emit(card._mode)

    def update_modes(self, modes: list):
        prev_id = self._current_id
        new_ids = {m.get("id") for m in modes}
        # полная пересборка с группировкой (перезагружает и картинки карточек)
        self._populate_list(modes)
        if prev_id and prev_id in new_ids:
            # восстановить визуальный выбор без переключения контента
            self._current_id = prev_id
            for c in self._cards:
                c.set_selected(c._mode.get("id") == prev_id)
        elif prev_id is None:
            pass  # был выбран «Все режимы» — оставляем как есть
        elif self._cards:
            self._select_card(self._cards[0])  # выбранный режим исчез — берём первый

    def show_update_banner(self, version: str):
        self._update_banner.set_version(version)
        self._update_banner.show()
        self._update_banner.start_pulse()
