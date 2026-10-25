import os
import shutil
from pathlib import Path
from PyQt6.QtCore import pyqtSignal, Qt, QSize, QMimeData, QTimer, QObject
from PyQt6.QtGui import QFont, QPixmap, QPainter, QColor, QPen, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QFileDialog, QMessageBox, QRadioButton, QButtonGroup,
    QScrollArea, QWidget, QGridLayout, QSizePolicy
)
from ui.player_gl_widget import PlayerGLWidget
import auth_client

import json
_SKINS_DIR = Path.home() / "AppData" / "Local" / ".grandlauncher" / "skins"
_VARIANTS_FILE = _SKINS_DIR / "_variants.json"


def _ensure_skins_dir():
    _SKINS_DIR.mkdir(parents=True, exist_ok=True)


# ── Тип модели по каждому скину (classic/slim) — хранится рядом со скинами ──────
def _load_variants() -> dict:
    try:
        return json.loads(_VARIANTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_variant(name: str, variant: str):
    d = _load_variants()
    d[name] = variant
    try:
        _VARIANTS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def variant_of(path: str) -> str:
    """Тип модели для скина (по имени файла). Неизвестный → classic."""
    return _load_variants().get(Path(path).name, "classic")


# ── Группы скинов (пользовательские) — порядок групп + их скины по имени файла ──
_GROUPS_FILE = _SKINS_DIR / "_groups.json"
_SKIN_MIME = "application/x-tempus-skin"


def _load_groups() -> list:
    try:
        d = json.loads(_GROUPS_FILE.read_text(encoding="utf-8"))
        return [{"name": g.get("name", ""), "skins": list(g.get("skins", []))}
                for g in d.get("groups", []) if g.get("name")]
    except Exception:
        return []


def _save_groups(groups: list):
    try:
        _GROUPS_FILE.write_text(
            json.dumps({"groups": groups}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ── Плащ по каждому скину (Mojang cape id или "none") ──────────────────────────
_CAPES_FILE = _SKINS_DIR / "_capes.json"


def _load_capes() -> dict:
    try:
        return json.loads(_CAPES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cape(name: str, cape_id: str):
    d = _load_capes()
    d[name] = cape_id or "none"
    try:
        _CAPES_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def cape_of(path: str) -> str:
    """cape_id для скина, или 'none'."""
    return _load_capes().get(Path(path).name, "none")


class SkinVariantDialog(QDialog):
    """Пикер типа модели при импорте скина: две живые модельки (steve/wide и
    alex/slim) крутят animation.dance.arm с новым скином — игрок выбирает тип."""
    def __init__(self, skin_path: str, parent=None, web_profile=None):
        super().__init__(parent)
        self.chosen: str | None = None
        self.setWindowTitle("Тип модели скина")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog | Qt.WindowType.Tool)
        # Светлее окна «Аккаунт», чтобы пикер чётко отделялся поверх него
        self.setStyleSheet("QDialog { background: #181c2b; border: 1px solid rgba(255,255,255,34); }")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        from ui.titlebar import TitleBar
        root.addWidget(TitleBar(self, "Какой это тип модели?", show_maximize=False, show_minimize=False))

        body = QVBoxLayout()
        body.setContentsMargins(20, 12, 20, 18)
        body.setSpacing(12)
        hint = QLabel("Выберите тип модели для этого скина")
        hint.setStyleSheet("color: #9aa4b8; font-size: 12px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(16)
        for model, variant, label in (("steve", "classic", "Классический"), ("alex", "slim", "Slim")):
            col = QVBoxLayout()
            col.setSpacing(8)
            # Градиент-карточка под моделью (как у миниатюр), чтобы не сливалась с фоном
            card = QFrame()
            card.setFixedSize(190, 250)
            card.setStyleSheet(
                "QFrame { border: 1px solid rgba(255,255,255,22); border-radius: 14px;"
                " background: qlineargradient(x1:0,y1:0, x2:0,y2:1,"
                " stop:0 rgba(78,86,108,255), stop:1 rgba(32,36,48,255)); }")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(5, 5, 5, 5)
            gl = PlayerGLWidget(model, card, web_profile, transparent=True)
            gl.setFixedSize(180, 240)
            gl.set_skin(skin_path)
            gl.set_animation("animation.dance.arm")
            cl.addWidget(gl, alignment=Qt.AlignmentFlag.AlignCenter)
            col.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)
            btn = QPushButton(label)
            btn.setFixedHeight(38)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton { background: rgba(100,140,255,130); color:#fff; border:none;"
                " border-radius:8px; font-size:13px; font-weight:600; }"
                " QPushButton:hover { background: rgba(100,140,255,210); }")
            btn.clicked.connect(lambda _=False, v=variant: self._choose(v))
            col.addWidget(btn)
            row.addLayout(col)
        body.addLayout(row)

        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(30)
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,10); color:#aab; border:none; border-radius:8px; font-size:12px; }"
            " QPushButton:hover { background: rgba(255,255,255,20); color:#fff; }")
        cancel.clicked.connect(self.reject)
        body.addWidget(cancel)
        root.addLayout(body)

    def _choose(self, variant: str):
        self.chosen = variant
        self.accept()


class CapeTile(QFrame):
    """Плитка выбора плаща: рендер (Стив+плащ) на градиенте + подпись, кликабельна."""
    clicked = pyqtSignal(object)   # cape_id (None = без плаща)
    _W, _H = 128, 158

    def __init__(self, cape_id, label: str, parent=None):
        super().__init__(parent)
        self._cape_id = cape_id
        self._selected = False
        self.setFixedSize(self._W, self._H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("capeTile")
        self._apply_style()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        self._img = QLabel()
        self._img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img.setStyleSheet("background: transparent; border: none;")
        lay.addWidget(self._img, 1)
        cap = QLabel(label)
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cap.setWordWrap(True)
        cap.setStyleSheet("color: #c0c6d4; font-size: 10px; background: transparent; border: none;")
        lay.addWidget(cap)

    _STYLE_BASE = ("#capeTile { border: 1px solid rgba(255,255,255,22); border-radius: 10px;"
                   " background: qlineargradient(x1:0,y1:0, x2:0,y2:1,"
                   " stop:0 rgba(78,86,108,255), stop:1 rgba(32,36,48,255)); }")
    _STYLE_SEL = ("#capeTile { border: 1px solid rgba(120,150,255,170); border-radius: 10px;"
                  " background: qlineargradient(x1:0,y1:0, x2:0,y2:1,"
                  " stop:0 rgba(92,100,124,255), stop:1 rgba(40,45,60,255)); }")

    def _apply_style(self):
        self.setStyleSheet(self._STYLE_SEL if self._selected else self._STYLE_BASE)

    def set_selected(self, v: bool):
        self._selected = v
        self._apply_style()

    def set_image(self, px):
        if px and not px.isNull():
            self._img.setPixmap(px.scaled(self._W - 16, self._H - 32,
                                          Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._cape_id)


class CapePickerDialog(QDialog):
    """Выбор плаща для скина: слева живой превью (скин игрока + плащ, cape.idle→loop),
    справа плитки владеемых плащей + «Без плаща»."""
    def __init__(self, skin_path, variant, current_cape_id, capes, tex_map,
                 photographer, parent=None, web_profile=None):
        super().__init__(parent)
        self.chosen = current_cape_id or "none"
        self._tex_map = tex_map                       # {cape_id: local_texture_path}
        self._tiles = []
        self.setWindowTitle("Выбор плаща")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog | Qt.WindowType.Tool)
        self.setStyleSheet("QDialog { background: #181c2b; border: 1px solid rgba(255,255,255,34); }")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        from ui.titlebar import TitleBar
        root.addWidget(TitleBar(self, "Выберите плащ", show_maximize=False, show_minimize=False))

        body = QHBoxLayout()
        body.setContentsMargins(16, 12, 16, 16)
        body.setSpacing(16)

        # Левая колонка — живой превью скина игрока с плащом
        left_card = QFrame()
        left_card.setFixedSize(210, 260)
        left_card.setStyleSheet(
            "QFrame { border: 1px solid rgba(255,255,255,22); border-radius: 14px;"
            " background: qlineargradient(x1:0,y1:0, x2:0,y2:1,"
            " stop:0 rgba(78,86,108,255), stop:1 rgba(32,36,48,255)); }")
        lc = QVBoxLayout(left_card)
        lc.setContentsMargins(6, 6, 6, 6)
        model = "alex" if variant == "slim" else "steve"
        self._left = PlayerGLWidget(model, left_card, web_profile, transparent=True)
        self._left.setFixedSize(198, 248)
        if skin_path:
            self._left.set_skin(skin_path)
        self._left.set_cape(self._tex_for(self.chosen))
        self._left.set_animation("animation.cape.idle", loop=False, nxt="animation.cape.loop")
        lc.addWidget(self._left, alignment=Qt.AlignmentFlag.AlignCenter)
        body.addWidget(left_card, 0, Qt.AlignmentFlag.AlignTop)

        # Правая колонка — плитки плащей (скролл)
        right = QVBoxLayout()
        right.setSpacing(8)
        hint = QLabel("Плащи вашего аккаунта")
        hint.setStyleSheet("color: #9aa4b8; font-size: 12px;")
        right.addWidget(hint)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(460)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }"
                             " QScrollBar:vertical { background: #181c2b; width: 6px; }"
                             " QScrollBar::handle:vertical { background: #33405f; border-radius: 3px; }")
        host = QWidget(); host.setStyleSheet("background: transparent;")
        grid = QGridLayout(host)
        grid.setSpacing(8)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        entries = [(None, "Без плаща")] + [(c.get("id"), c.get("alias") or "Плащ") for c in capes]
        cols = 3
        for i, (cid, label) in enumerate(entries):
            tile = CapeTile(cid, label)
            tile.set_selected((cid or "none") == self.chosen)
            tile.clicked.connect(self._select)
            grid.addWidget(tile, i // cols, i % cols)
            self._tiles.append(tile)
            if photographer:
                photographer.request_cape(
                    cid, self._tex_map.get(cid),
                    lambda px, t=tile: t.set_image(px))
        scroll.setWidget(host)
        right.addWidget(scroll, 1)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(34); cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,10); color:#aab; border:none;"
            " border-radius:8px; padding:0 16px; font-size:12px; }"
            " QPushButton:hover { background: rgba(255,255,255,20); color:#fff; }")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Сохранить")
        save.setFixedHeight(34); save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.setStyleSheet(
            "QPushButton { background: rgba(100,140,255,150); color:#fff; border:none;"
            " border-radius:8px; padding:0 18px; font-size:13px; font-weight:600; }"
            " QPushButton:hover { background: rgba(100,140,255,220); }")
        save.clicked.connect(self.accept)
        btns.addWidget(cancel); btns.addWidget(save)
        right.addLayout(btns)
        body.addLayout(right, 1)
        root.addLayout(body)

    def _tex_for(self, cape_id):
        if not cape_id or cape_id == "none":
            return None
        return self._tex_map.get(cape_id)

    def _select(self, cape_id):
        self.chosen = cape_id or "none"
        self._left.set_cape(self._tex_for(self.chosen))
        for t in self._tiles:
            t.set_selected((t._cape_id or "none") == self.chosen)


class SkinThumbnail(QLabel):
    clicked = pyqtSignal(str)              # path
    change_type_requested = pyqtSignal(str)
    change_cape_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    _SIZE = 108   # плитка ~2x от прежних 56

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path
        self._selected = False
        self.setFixedSize(self._SIZE, self._SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setScaledContents(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Шестерёнка в правом верхнем углу — при наведении на плитку
        from ui.assets import svg_icon
        self._gear = QPushButton(self)
        self._gear.setIcon(svg_icon("settings.svg", "#FFFFFF", 14))
        self._gear.setFixedSize(24, 24)
        self._gear.setCursor(Qt.CursorShape.PointingHandCursor)
        self._gear.setStyleSheet(
            "QPushButton { background: rgba(0,0,0,120); border: 1px solid rgba(255,255,255,25);"
            " border-radius: 12px; }"
            " QPushButton:hover { background: rgba(100,140,255,210); border-color: #6c8cff; }")
        self._gear.move(self._SIZE - 28, 4)
        self._gear.hide()
        self._gear.clicked.connect(self._open_menu)
        self._menu_open = False
        self._press_pos = None
        self._dragging = False
        # Мягкий градиент-«кнопка» под моделью, чтобы бюст не сливался с панелью.
        self.setStyleSheet(
            "SkinThumbnail { border: 1px solid rgba(255,255,255,22); border-radius: 12px;"
            " background: qlineargradient(x1:0,y1:0, x2:0,y2:1,"
            " stop:0 rgba(78,86,108,255), stop:1 rgba(32,36,48,255)); }"
            " SkinThumbnail:hover { border-color: rgba(120,150,255,90);"
            " background: qlineargradient(x1:0,y1:0, x2:0,y2:1,"
            " stop:0 rgba(92,100,124,255), stop:1 rgba(40,45,60,255)); }")
        self._load_pixmap()

    def _load_pixmap(self):
        # Плоская текстура — как быстрый фолбэк, пока не приедет 3D-рендер бюста.
        px = QPixmap(self.path)
        if not px.isNull():
            self.setPixmap(px.scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.FastTransformation))

    def apply_render(self, px):
        """Ставит 3D-рендер бюста (портрет, прозрачный фон) поверх градиента."""
        if px is None or px.isNull():
            return
        s = self._SIZE - 6
        self.setPixmap(px.scaled(s, s, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation))

    def set_selected(self, val: bool):
        self._selected = val
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._selected:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(100, 140, 255), 2)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(1, 1, self.width() - 2, self.height() - 2, 12, 12)

    def enterEvent(self, e):
        self._gear.show()
        self._gear.raise_()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if not self._menu_open:      # пока открыто контекстное меню — шестерёнку не прячем
            self._gear.hide()
        super().leaveEvent(e)

    def _open_menu(self):
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #12142a; border: 1px solid rgba(255,255,255,20);
                border-radius: 8px; padding: 4px; color: #e0e0f0; font-size: 12px; }
            QMenu::item { padding: 6px 16px; border-radius: 5px; }
            QMenu::item:selected { background: rgba(100,140,255,120); }
        """)
        act_type = menu.addAction("Поменять тип")
        act_cape = menu.addAction("Поменять плащ")
        act_del = menu.addAction("Удалить")
        self._menu_open = True
        self._gear.show()
        self._gear.raise_()
        act = menu.exec(self._gear.mapToGlobal(self._gear.rect().bottomLeft()))
        self._menu_open = False
        if not self.underMouse():    # меню закрылось, курсор ушёл — прячем
            self._gear.hide()
        if act == act_type:
            self.change_type_requested.emit(self.path)
        elif act == act_cape:
            self.change_cape_requested.emit(self.path)
        elif act == act_del:
            self.delete_requested.emit(self.path)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_pos = e.position().toPoint()
            self._dragging = False

    def mouseMoveEvent(self, e):
        if self._press_pos is None or not (e.buttons() & Qt.MouseButton.LeftButton):
            return
        from PyQt6.QtWidgets import QApplication
        if (e.position().toPoint() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            return
        # Старт перетаскивания скина (в группу)
        from PyQt6.QtGui import QDrag
        from PyQt6.QtCore import QMimeData
        self._dragging = True
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_SKIN_MIME, Path(self.path).name.encode("utf-8"))
        drag.setMimeData(mime)
        pm = self.pixmap()
        if pm and not pm.isNull():
            drag.setPixmap(pm.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation))
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self._dragging \
                and self._press_pos is not None:
            self.clicked.emit(self.path)   # обычный клик (без перетаскивания)
        self._press_pos = None
        self._dragging = False


class GroupSection(QFrame):
    """Секция группы (или «Без группы»): заголовок + сетка скинов. Принимает
    брошенный скин (drag) → перемещает его в эту группу."""
    skin_dropped = pyqtSignal(str, object)   # filename, group_name (None = без группы)
    rename_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self._name = name                    # None → «Без группы»
        self.setObjectName("groupSection")
        self.setAcceptDrops(True)
        self._base_style = ("#groupSection { border: 1px solid transparent; border-radius: 10px; }")
        self._hot_style = ("#groupSection { border: 1px dashed rgba(120,150,255,160);"
                           " border-radius: 10px; background: rgba(100,140,255,18); }")
        self.setStyleSheet(self._base_style)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        hdr = QHBoxLayout()
        hdr.setSpacing(6)
        title = QLabel(name if name else "Без группы")
        title.setStyleSheet("color: #aab0c4; font-size: 12px; font-weight: 700;")
        hdr.addWidget(title)
        hdr.addStretch()
        if name:   # у пользовательских групп — меню (переименовать/удалить)
            from ui.assets import svg_icon
            gear = QPushButton()
            gear.setIcon(svg_icon("settings.svg", "#9aa4b8", 13))
            gear.setFixedSize(22, 22)
            gear.setCursor(Qt.CursorShape.PointingHandCursor)
            gear.setStyleSheet(
                "QPushButton { background: transparent; border: none; border-radius: 11px; }"
                " QPushButton:hover { background: rgba(255,255,255,20); }")
            gear.clicked.connect(self._group_menu)
            hdr.addWidget(gear)
        lay.addLayout(hdr)

        self._grid = QGridLayout()
        self._grid.setSpacing(8)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        lay.addLayout(self._grid)
        self._n = 0

    def add_thumb(self, thumb, cols=5):
        self._grid.addWidget(thumb, self._n // cols, self._n % cols)
        self._n += 1

    def _group_menu(self):
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #12142a; border: 1px solid rgba(255,255,255,20);
                border-radius: 8px; padding: 4px; color: #e0e0f0; font-size: 12px; }
            QMenu::item { padding: 6px 16px; border-radius: 5px; }
            QMenu::item:selected { background: rgba(100,140,255,120); }
        """)
        a_ren = menu.addAction("Переименовать")
        a_del = menu.addAction("Удалить группу")
        act = menu.exec(self.cursor().pos())
        if act == a_ren:
            self.rename_requested.emit(self._name)
        elif act == a_del:
            self.delete_requested.emit(self._name)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(_SKIN_MIME):
            e.acceptProposedAction()
            self.setStyleSheet(self._hot_style)

    def dragLeaveEvent(self, e):
        self.setStyleSheet(self._base_style)

    def dropEvent(self, e):
        self.setStyleSheet(self._base_style)
        if e.mimeData().hasFormat(_SKIN_MIME):
            fname = bytes(e.mimeData().data(_SKIN_MIME)).decode("utf-8")
            e.acceptProposedAction()
            self.skin_dropped.emit(fname, self._name)


class NewGroupDropZone(QFrame):
    """Пустая зона снизу: бросок скина сюда создаёт новую группу с этим скином."""
    skin_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFixedHeight(46)
        self._base = "QFrame { border: 1px dashed rgba(255,255,255,26); border-radius: 10px; }"
        self._hot = ("QFrame { border: 1px dashed rgba(120,150,255,180); border-radius: 10px;"
                     " background: rgba(100,140,255,20); }")
        self.setStyleSheet(self._base)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("＋ Перетащите скин сюда, чтобы создать новую группу")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color: #6b7288; font-size: 11px; background: transparent; border: none;")
        lay.addWidget(lbl)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(_SKIN_MIME):
            e.acceptProposedAction()
            self.setStyleSheet(self._hot)

    def dragLeaveEvent(self, e):
        self.setStyleSheet(self._base)

    def dropEvent(self, e):
        self.setStyleSheet(self._base)
        if e.mimeData().hasFormat(_SKIN_MIME):
            fname = bytes(e.mimeData().data(_SKIN_MIME)).decode("utf-8")
            e.acceptProposedAction()
            self.skin_dropped.emit(fname)


class ToggleSwitch(QWidget):
    """Маленький переключатель (вкл/выкл)."""
    toggled = pyqtSignal(bool)

    def __init__(self, on: bool = False, parent=None):
        super().__init__(parent)
        self._on = on
        self.setFixedSize(40, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._on

    def setChecked(self, value: bool):
        self._on = bool(value)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._on = not self._on
            self.update()
            self.toggled.emit(self._on)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QColor("#5865F2") if self._on else QColor(60, 60, 82)
        p.setBrush(track)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, self.width(), self.height(), 11, 11)
        p.setBrush(QColor("#ffffff"))
        d = self.height() - 6
        x = self.width() - d - 3 if self._on else 3
        p.drawEllipse(x, 3, d, d)


class AccountDialog(QDialog):
    logout_requested = pyqtSignal()
    discord_linked = pyqtSignal(str)
    _skin_done = pyqtSignal(str)   # variant
    _skin_fail = pyqtSignal(str)   # error message
    _capes_loaded = pyqtSignal(list, dict)   # owned capes + {id: tex_path}

    def __init__(self, username: str, parent=None, web_profile=None):
        super().__init__(parent)
        self._web_profile = web_profile
        self._username = username
        self._selected_skin_path: str | None = None
        self._thumbnails: list[SkinThumbnail] = []
        _ensure_skins_dir()

        self.setWindowTitle("Скины")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog | Qt.WindowType.Tool)
        # Ширину фиксируем, высоту — только минимум: при масштабе Windows >100% контент
        # выше 520px, и жёсткий setFixedSize резал нижнюю кнопку «Выйти из аккаунта».
        # Теперь окно растёт под содержимое на любом DPI.
        self.setFixedWidth(877)
        self.setMinimumHeight(520)
        # Светлее основного окна лаунчера, чтобы не сливаться (но темнее пикера типа)
        self.setStyleSheet("QDialog { background: #121520; border: 1px solid rgba(255,255,255,22); }")
        self.setAcceptDrops(True)
        self._skin_done.connect(self._on_skin_uploaded)
        self._skin_fail.connect(self._on_skin_error)
        self._owned_capes: list = []
        self._cape_tex_map: dict = {}
        self._capes_loaded.connect(self._on_capes_loaded)
        # «Фотограф» скинов — рендерит бюст-миниатюры (офскрин), кэш по sha1.
        try:
            from ui.skin_photo import SkinPhotographer
            self._photographer = SkinPhotographer(self)
            _photog = self._photographer   # захват, чтобы не трогать умирающий self
            self.destroyed.connect(lambda *_: _photog.close())
        except Exception:
            self._photographer = None
        self._build_ui(username)

    def _render_thumbs(self):
        """Рендер бюста для всех миниатюр типом КАЖДОГО скина (лениво, из кэша)."""
        if not self._photographer:
            return
        for t in self._thumbnails:
            self._photographer.request(
                t.path, variant_of(t.path),
                lambda px, th=t: self._apply_thumb_render(th, px))

    def _apply_thumb_render(self, thumb, px):
        try:
            if thumb in self._thumbnails:
                thumb.apply_render(px)
        except RuntimeError:
            pass  # миниатюра уже удалена

    # ── Плащи (официальные Mojang) ─────────────────────────────────────────────
    def _load_owned_capes(self):
        import threading
        token = auth_client._load_settings().get("token", "")
        if not token:
            return
        def _run():
            import cape_client
            capes = cape_client.fetch_owned_capes(token)
            texmap = {}
            for c in capes:
                tp = cape_client.cape_texture(c)
                if tp:
                    texmap[c.get("id")] = tp
            self._capes_loaded.emit(capes, texmap)
        threading.Thread(target=_run, daemon=True).start()

    def _on_capes_loaded(self, capes, texmap):
        self._owned_capes = capes
        self._cape_tex_map = texmap
        cur = self._selected_skin_path or auth_client._load_settings().get("applied_skin_path", "")
        if cur:
            self._model.set_cape(self._preview_cape_for(cur))

    def _preview_cape_for(self, skin_path):
        cid = cape_of(skin_path)
        return self._cape_tex_map.get(cid) if cid and cid != "none" else None

    def _teardown_picker(self, dlg):
        """Синхронно уничтожает GL-виджеты пикера и сам диалог ДО возврата, чтобы
        быстрый повторный open не наложился на ещё живой/рушащийся GL-контекст
        (перекрытие общих контекстов при AA_ShareOpenGLContexts → сегфолт драйвера)."""
        from PyQt6.QtCore import QCoreApplication, QEvent
        # Гасим ещё не отрисованные задания фотографа — их плитки уже уничтожаются.
        try:
            self._photographer._queue.clear()
            self._photographer._busy = False
        except Exception:
            pass
        try:
            for gl in dlg.findChildren(PlayerGLWidget):
                gl.setParent(None)
                gl.deleteLater()
        except Exception:
            pass
        dlg.setParent(None)
        dlg.deleteLater()
        # Форсируем отложенные удаления СЕЙЧАС → контексты уничтожаются до re-open.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()

    def _open_cape_picker(self, skin_path: str):
        if getattr(self, "_picker_busy", False):
            return                              # уже открыт/закрывается — гасим дребезг
        self._picker_busy = True
        variant = variant_of(skin_path)
        dlg = CapePickerDialog(skin_path, variant, cape_of(skin_path),
                               self._owned_capes, self._cape_tex_map,
                               self._photographer, self, self._web_profile)
        try:
            if dlg.exec() == QDialog.DialogCode.Accepted:
                _save_cape(Path(skin_path).name, dlg.chosen)
                if self._selected_skin_path == skin_path:
                    self._model.set_cape(self._preview_cape_for(skin_path))
        finally:
            self._teardown_picker(dlg)
            self._picker_busy = False

    def showEvent(self, e):
        super().showEvent(e)
        settings = auth_client._load_settings()
        force = bool(settings.get("token"))
        # Большой превью — типом применённого скина (или classic)
        applied = settings.get("applied_skin_path", "")
        variant = variant_of(applied) if applied else settings.get("skin_variant", "classic")
        # Сбрасываем выделение миниатюры и кнопку
        self._selected_skin_path = None
        for t in self._thumbnails:
            t.set_selected(False)
        self._apply_btn.setEnabled(False)
        self._apply_btn.setText("Применить скин")
        self._model.restart_intro()
        self._model.set_username(self._username, variant, force_refresh=force)
        # Плащ на большом превью (по применённому скину) + фоновый фетч владеемых плащей
        self._model.set_cape(self._preview_cape_for(applied) if applied else None)
        self._load_owned_capes()
        # Секция Discord: сразу перестраиваем по локальным настройкам (если игрок
        # привязался через карточку режима, пока окно было закрыто — кнопка исчезнет),
        # затем асинхронно сверяем с БД сервера (если привязка пропала — кнопка вернётся).
        self._refresh_discord_section()
        self._sync_discord()

    # ── Drag & drop ─────────────────────────────────────────────────────────

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            urls = e.mimeData().urls()
            if urls and urls[0].toLocalFile().lower().endswith(".png"):
                e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        path = e.mimeData().urls()[0].toLocalFile()
        self._import_skin(path)

    # ── Build UI ─────────────────────────────────────────────────────────────

    def _build_ui(self, username: str):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        from ui.titlebar import TitleBar
        tb = TitleBar(self, f"Скины  ·  {username}", show_maximize=False, show_minimize=False)
        tb.setFixedWidth(877)
        root.addWidget(tb)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        root.addLayout(body)

        body.addWidget(self._build_left(username))

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: rgba(255,255,255,12);")
        body.addWidget(sep)

        body.addWidget(self._build_right())

    def _build_left(self, username: str) -> QWidget:
        w = QWidget()
        w.setFixedWidth(260)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 12, 16, 16)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 3D model — тип берём у применённого скина (тумблер убран: тип задаётся
        # при импорте пикером и хранится по каждому скину)
        settings = auth_client._load_settings()
        applied = settings.get("applied_skin_path", "")
        skin_variant = variant_of(applied) if applied else settings.get("skin_variant", "classic")
        model_type = "alex" if skin_variant == "slim" else "steve"
        # Градиент-карточка за моделью (как у миниатюр/пикера), прозрачный GL сверху
        model_card = QFrame()
        model_card.setFixedSize(196, 236)
        model_card.setStyleSheet(
            "QFrame { border: 1px solid rgba(255,255,255,22); border-radius: 14px;"
            " background: qlineargradient(x1:0,y1:0, x2:0,y2:1,"
            " stop:0 rgba(78,86,108,255), stop:1 rgba(32,36,48,255)); }")
        mc = QVBoxLayout(model_card)
        mc.setContentsMargins(6, 6, 6, 6)
        self._model = PlayerGLWidget(model_type, model_card, self._web_profile, transparent=True)
        self._model.setFixedSize(180, 220)
        self._model.set_username(username, skin_variant)
        mc.addWidget(self._model, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(model_card, alignment=Qt.AlignmentFlag.AlignCenter)

        # Кнопка применить
        self._apply_btn = QPushButton("Применить скин")
        self._apply_btn.setFixedHeight(36)
        self._apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_btn.setEnabled(False)
        self._apply_btn.setStyleSheet("""
            QPushButton {
                background: rgba(100,140,255,150);
                color: #fff; border: none; border-radius: 8px;
                font-weight: 600; font-size: 12px;
            }
            QPushButton:hover { background: rgba(100,140,255,220); }
            QPushButton:disabled { background: rgba(60,60,90,120); color: #555; }
        """)
        self._apply_btn.clicked.connect(self._apply_skin)
        lay.addWidget(self._apply_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: rgba(255,255,255,12);")
        lay.addWidget(sep)

        # Discord
        self._discord_widget = self._build_discord_section()
        lay.addWidget(self._discord_widget)

        # «Не беспокоить» и «Выйти» перенесены в меню аккаунта (статус + выход).
        lay.addStretch()

        return w

    def _build_right(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(616)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        hdr = QHBoxLayout()
        title = QLabel("Скины")
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        title.setStyleSheet("color: #c8c8e0;")
        add_btn = QPushButton("+ Добавить")
        add_btn.setFixedHeight(26)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet("""
            QPushButton {
                background: rgba(100,140,255,130); color:#fff;
                border:none; border-radius:6px; font-size:11px; font-weight:600;
                padding: 0 10px;
            }
            QPushButton:hover { background: rgba(100,140,255,200); }
        """)
        add_btn.clicked.connect(self._open_file_dialog)
        group_btn = QPushButton("+ Группа")
        group_btn.setFixedHeight(26)
        group_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        group_btn.setStyleSheet("""
            QPushButton { background: rgba(255,255,255,14); color:#c8c8e0;
                border:none; border-radius:6px; font-size:11px; font-weight:600; padding: 0 10px; }
            QPushButton:hover { background: rgba(255,255,255,26); color:#fff; }
        """)
        group_btn.clicked.connect(self._add_group)
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(group_btn)
        hdr.addWidget(add_btn)
        lay.addLayout(hdr)

        # Drop hint
        self._drop_hint = QLabel("Перетащите PNG 64×64 сюда\nили нажмите «+ Добавить»")
        self._drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_hint.setStyleSheet("""
            color: #3a3a5a; font-size: 11px;
            border: 1px dashed #2a2a4a; border-radius: 8px;
            padding: 12px;
        """)
        lay.addWidget(self._drop_hint)

        # Scroll area with skin grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { background: #0d0d18; width: 6px; }
            QScrollBar::handle:vertical { background: #2a2a4a; border-radius: 3px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        self._sections_host = QWidget()
        self._sections_host.setStyleSheet("background: transparent;")
        self._sections_lay = QVBoxLayout(self._sections_host)
        self._sections_lay.setSpacing(6)
        self._sections_lay.setContentsMargins(0, 0, 0, 0)
        self._sections_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._sections_host)
        lay.addWidget(scroll)

        self._reload_skins()
        return w

    # ── Skins panel ──────────────────────────────────────────────────────────

    def _reload_skins(self):
        # чистим старые секции и миниатюры
        while self._sections_lay.count():
            it = self._sections_lay.takeAt(0)
            wgt = it.widget()
            if wgt:
                wgt.deleteLater()
        self._thumbnails.clear()

        by_name = {p.name: p for p in sorted(_SKINS_DIR.glob("*.png"))}
        self._drop_hint.setVisible(len(by_name) == 0)

        groups = _load_groups()
        grouped = set()

        def make_thumb(path: str) -> SkinThumbnail:
            th = SkinThumbnail(path)
            th.clicked.connect(self._on_skin_clicked)
            th.change_type_requested.connect(self._on_change_type)
            th.change_cape_requested.connect(self._open_cape_picker)
            th.delete_requested.connect(self._on_delete_skin)
            self._thumbnails.append(th)
            return th

        def make_section(name):
            sec = GroupSection(name, self._sections_host)
            sec.skin_dropped.connect(self._move_skin)
            sec.rename_requested.connect(self._rename_group)
            sec.delete_requested.connect(self._delete_group)
            self._sections_lay.addWidget(sec)
            return sec

        # Пользовательские группы (в своём порядке)
        for g in groups:
            sec = make_section(g["name"])
            for fname in g["skins"]:
                p = by_name.get(fname)
                if p:
                    grouped.add(fname)
                    sec.add_thumb(make_thumb(str(p)))

        # «Без группы» — всё, что не в группах (показываем всегда, это drop-таргет)
        rest = make_section(None)
        for fname, p in by_name.items():
            if fname not in grouped:
                rest.add_thumb(make_thumb(str(p)))

        # Зона снизу: бросок скина → создать новую группу
        zone = NewGroupDropZone(self._sections_host)
        zone.skin_dropped.connect(self._create_group_with_skin)
        self._sections_lay.addWidget(zone)

        self._render_thumbs()   # заменить плоские текстуры 3D-рендером бюста

    def _create_group_with_skin(self, fname: str):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Новая группа", "Название группы:")
        name = (name or "").strip()
        if not ok or not name:
            return
        groups = _load_groups()
        if any(g["name"] == name for g in groups):
            QMessageBox.information(self, "Группа", "Такая группа уже есть.")
            return
        for g in groups:
            if fname in g["skins"]:
                g["skins"].remove(fname)
        groups.append({"name": name, "skins": [fname]})
        _save_groups(groups)
        self._reload_skins()

    # ── Группы ────────────────────────────────────────────────────────────────
    def _add_group(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Новая группа", "Название группы:")
        name = (name or "").strip()
        if not ok or not name:
            return
        groups = _load_groups()
        if any(g["name"] == name for g in groups):
            QMessageBox.information(self, "Группа", "Такая группа уже есть.")
            return
        groups.append({"name": name, "skins": []})
        _save_groups(groups)
        self._reload_skins()

    def _rename_group(self, name: str):
        from PyQt6.QtWidgets import QInputDialog
        new, ok = QInputDialog.getText(self, "Переименовать группу", "Название:", text=name)
        new = (new or "").strip()
        if not ok or not new or new == name:
            return
        groups = _load_groups()
        if any(g["name"] == new for g in groups):
            QMessageBox.information(self, "Группа", "Такая группа уже есть.")
            return
        for g in groups:
            if g["name"] == name:
                g["name"] = new
        _save_groups(groups)
        self._reload_skins()

    def _delete_group(self, name: str):
        # Удаляем только группу — её скины уходят в «Без группы» (файлы целы)
        groups = [g for g in _load_groups() if g["name"] != name]
        _save_groups(groups)
        self._reload_skins()

    def _move_skin(self, filename: str, group_name):
        groups = _load_groups()
        for g in groups:                         # убрать из всех групп
            if filename in g["skins"]:
                g["skins"].remove(filename)
        if group_name:                            # добавить в целевую (если не «Без группы»)
            for g in groups:
                if g["name"] == group_name and filename not in g["skins"]:
                    g["skins"].append(filename)
        _save_groups(groups)
        self._reload_skins()

    def _on_change_type(self, path: str):
        if getattr(self, "_picker_busy", False):
            return
        self._picker_busy = True
        dlg = SkinVariantDialog(path, self, self._web_profile)
        try:
            if dlg.exec() == QDialog.DialogCode.Accepted and dlg.chosen:
                _save_variant(Path(path).name, dlg.chosen)
                # перерисовать миниатюру этого скина под новый тип
                for t in self._thumbnails:
                    if t.path == path and self._photographer:
                        self._photographer.request(
                            path, dlg.chosen, lambda px, th=t: self._apply_thumb_render(th, px))
                # если этот скин выбран — обновить большой превью
                if self._selected_skin_path == path:
                    self._on_skin_clicked(path)
        finally:
            self._teardown_picker(dlg)
            self._picker_busy = False

    def _on_delete_skin(self, path: str):
        if QMessageBox.question(
                self, "Удалить скин", f"Удалить «{Path(path).name}»?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            os.remove(path)
        except Exception:
            pass
        fname = Path(path).name
        # убрать запись типа
        d = _load_variants()
        if d.pop(fname, None) is not None:
            try:
                _VARIANTS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
        # убрать из всех групп
        groups = _load_groups()
        changed = False
        for g in groups:
            if fname in g["skins"]:
                g["skins"].remove(fname); changed = True
        if changed:
            _save_groups(groups)
        if self._selected_skin_path == path:
            self._selected_skin_path = None
        self._reload_skins()

    def _on_skin_clicked(self, path: str):
        self._selected_skin_path = path
        for t in self._thumbnails:
            t.set_selected(t.path == path)
        # Большой превью — типом ЭТОГО скина
        model_type = "alex" if variant_of(path) == "slim" else "steve"
        if model_type != self._model._model_name:
            self._model.set_model(model_type)
        self._model.set_skin(path)
        self._model.set_cape(self._preview_cape_for(path))   # плащ этого скина
        settings = auth_client._load_settings()
        if path == settings.get("applied_skin_path"):
            self._apply_btn.setEnabled(False)
            self._apply_btn.setText("Скин установлен")
        else:
            self._apply_btn.setEnabled(True)
            self._apply_btn.setText("Применить скин")

    def _open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите скин 64×64", "", "PNG изображения (*.png)"
        )
        if path:
            self._import_skin(path)

    def _import_skin(self, path: str):
        px = QPixmap(path)
        if px.isNull():
            QMessageBox.warning(self, "Ошибка", "Не удалось открыть PNG.")
            return
        if px.width() != 64 or px.height() not in (32, 64):
            QMessageBox.warning(
                self, "Неверный размер",
                f"Скин должен быть 64×32 или 64×64 пикселей.\nВаш файл: {px.width()}×{px.height()}"
            )
            return
        dest = _SKINS_DIR / Path(path).name
        if not dest.exists():
            shutil.copy2(path, dest)
        # Спросить тип модели (две живые модельки с dance.arm)
        dlg = SkinVariantDialog(str(dest), self, self._web_profile)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.chosen:
            _save_variant(dest.name, dlg.chosen)
        elif not _load_variants().get(dest.name):
            _save_variant(dest.name, "classic")   # отменил — дефолт, чтобы не спрашивать вечно
        # Затем спросить плащ (можно «Без плаща»)
        self._open_cape_picker(str(dest))
        self._reload_skins()
        # Автовыбор только что добавленного
        QTimer.singleShot(50, lambda: self._auto_select(str(dest)))

    def _auto_select(self, path: str):
        for t in self._thumbnails:
            if t.path == path:
                t.clicked.emit(path)
                break

    # ── Apply skin ───────────────────────────────────────────────────────────

    def _apply_skin(self):
        if not self._selected_skin_path:
            return
        settings = auth_client._load_settings()
        if not settings.get("token"):
            QMessageBox.information(self, "Офлайн аккаунт",
                                    "Смена скина на серверах Mojang доступна только для лицензионных аккаунтов.")
            return

        variant = variant_of(self._selected_skin_path)
        self._apply_btn.setEnabled(False)
        self._apply_btn.setText("Загрузка...")
        self._upload_skin(self._selected_skin_path, variant)

    def _upload_skin(self, path: str, variant: str):
        import threading, requests, logging
        log = logging.getLogger("skin")

        def _run():
            try:
                settings = auth_client._load_settings()
                token = settings.get("token", "")
                log.info("[skin] token present=%s len=%d", bool(token), len(token) if token else 0)
                with open(path, "rb") as f:
                    data = f.read()
                log.info("[skin] file=%s size=%d variant=%s", path, len(data), variant)
                resp = requests.post(
                    "https://api.minecraftservices.com/minecraft/profile/skins",
                    headers={"Authorization": f"Bearer {token}"},
                    files={"file": ("skin.png", data, "image/png")},
                    data={"variant": variant},
                    timeout=15,
                )
                log.info("[skin] status=%d body=%s", resp.status_code, resp.text[:300])
                if resp.status_code in (200, 204):
                    auth_client._save_settings({"skin_variant": variant, "applied_skin_path": path})
                    # Активируем плащ этого скина на аккаунте Mojang (в игре)
                    try:
                        import cape_client
                        cid = cape_of(path)
                        cape_client.set_active_cape(token, None if cid == "none" else cid)
                    except Exception:
                        pass
                    self._skin_done.emit(variant)
                else:
                    try:
                        err = resp.json().get("errorMessage", resp.text)[:120]
                    except Exception:
                        err = resp.text[:120]
                    self._skin_fail.emit(err)
            except Exception as e:
                log.error("[skin] exception: %s", e, exc_info=True)
                self._skin_fail.emit(str(e))

        threading.Thread(target=_run, daemon=True).start()

    def _on_skin_uploaded(self, variant: str):
        self._apply_btn.setEnabled(False)
        self._apply_btn.setText("Скин установлен")
        # Mojang CDN обновляет скин с задержкой — ждём 4 сек потом перезагружаем
        def _reload():
            model_type = "alex" if variant == "slim" else "steve"
            self._model.set_model(model_type)
            self._model.set_username(self._username, variant, force_refresh=True)
        QTimer.singleShot(4000, _reload)

    def _on_skin_error(self, msg: str):
        self._apply_btn.setEnabled(True)
        self._apply_btn.setText("Применить скин")
        QMessageBox.warning(self, "Ошибка загрузки скина", msg)

    # ── Discord ──────────────────────────────────────────────────────────────

    def _build_dnd_row(self) -> QWidget:
        import notifications
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        lbl = QLabel("Не беспокоить")
        lbl.setStyleSheet("color: #c0c0d8; font-size: 12px; background: transparent;")
        h.addWidget(lbl)
        h.addStretch()
        sw = ToggleSwitch(notifications.center().is_dnd())
        sw.toggled.connect(lambda v: notifications.center().set_dnd(v))
        h.addWidget(sw)
        return row

    def _build_discord_section(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("QFrame { background: transparent; border: none; }")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        settings = auth_client._load_settings()
        discord_id = settings.get("discord_id")
        discord_username = settings.get("discord_username", "")

        if discord_id:
            row = QHBoxLayout()
            icon = QLabel()
            try:
                from ui.assets import svg_icon as _svg
                icon.setPixmap(_svg("discord.svg", "#5865F2", 18).pixmap(18, 18))
            except Exception:
                icon.setText("🎮")
            icon.setStyleSheet("background: transparent;")
            info = QLabel(f"Discord: {discord_username or discord_id}")
            info.setStyleSheet("color: #5865F2; font-size: 12px; font-weight: 600; background: transparent;")
            row.addWidget(icon)
            row.addWidget(info, 1)
            lay.addLayout(row)
        else:
            link_btn = QPushButton(" Привязать Discord")
            link_btn.setFixedHeight(36)
            try:
                from ui.assets import svg_icon as _svg
                link_btn.setIcon(_svg("discord.svg", "#ffffff", 18))
                link_btn.setIconSize(QSize(18, 18))
            except Exception:
                pass
            link_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(88,101,242,180);
                    color: #fff; border: none; border-radius: 8px;
                    font-size: 12px; font-weight: 600;
                }
                QPushButton:hover { background: rgba(88,101,242,240); }
            """)
            link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            link_btn.clicked.connect(self._link_discord)
            lay.addWidget(link_btn)

        return frame

    def _refresh_discord_section(self):
        old = self._discord_widget
        self._discord_widget = self._build_discord_section()
        left_lay = old.parent().layout() if old.parent() else None
        if left_lay:
            idx = left_lay.indexOf(old)
            left_lay.removeWidget(old)
            old.deleteLater()
            left_lay.insertWidget(idx, self._discord_widget)

    def _link_discord(self):
        from ui.discord_auth_dialog import DiscordAuthDialog
        import config
        dlg = DiscordAuthDialog(config.SITE_URL, self, self._web_profile)
        def _on_linked(dc_username: str, discord_id: str, login_token: str):
            auth_client._save_settings({"discord_id": discord_id, "discord_username": dc_username})
            self._refresh_discord_section()
            self.discord_linked.emit(login_token)
        dlg.login_success.connect(_on_linked)
        dlg.exec()

    def _sync_discord(self):
        """Сверяет привязку с БД сервера (авторитетно) и перерисовывает секцию.
        Если БД не знает привязки — auth_client сотрёт её локально, кнопка вернётся."""
        import threading
        def _run():
            try:
                auth_client.sync_discord_link()
            except Exception:
                pass
            QTimer.singleShot(0, self._refresh_discord_section)
        threading.Thread(target=_run, daemon=True).start()

    def _do_logout(self):
        self.logout_requested.emit()
        self.accept()
