#«Фотограф» скинов: рендерит 3D-модель со скином в статичной позе и отдаёт бюст-миниатюру (голова+торс). Результат кэшируется на диск по sha1 скина+варианте.

# Использует скрытый PlayerGLWidget (общий GL-контекст, AA_ShareOpenGLContexts).
# Снимки делаются лениво, по одному за тик — UI не блокируется. 
# Поза выбирается детерминированно из sha1 скина (выглядит рандомно по скинам, но стабильно для одного → кэш не инвалидируется).

import hashlib
import logging
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, Qt
from PyQt6.QtGui import QPixmap, QImage

from config import CACHE_DIR
from ui.player_gl_widget import PlayerGLWidget

_log = logging.getLogger("skin_photo")

_POSES = [
    "animation.pose.norm", "animation.pose.idle", "animation.pose.hoy",
    "animation.pose.honnor", "animation.pose.disco", "animation.pose.jjp1",
]

# Размер офскрин-рендера (полная модель); бюст обрезаем из верхней части.
_RENDER_W, _RENDER_H = 200, 300
# Бюст = голова + торс: доля кадра по вертикали (сверху) и горизонтальный кроп.
_BUST_TOP, _BUST_BOT = 0.06, 0.60   # от высоты кадра
_BUST_LEFT, _BUST_RIGHT = 0.20, 0.80  # от ширины кадра


def _sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    h.update(path.read_bytes())
    return h.hexdigest()


def _pose_for(sha1_hex: str) -> str:
    return _POSES[int(sha1_hex[:8], 16) % len(_POSES)]


# Кадрировка «фигура» для плитки плаща (видно спину/плащ почти целиком)
_FIG_TOP, _FIG_BOT = 0.04, 0.92
_FIG_LEFT, _FIG_RIGHT = 0.24, 0.76


def _crop_figure(img: QImage) -> QImage:
    w, h = img.width(), img.height()
    if w <= 0 or h <= 0:
        return img
    x = int(w * _FIG_LEFT); y = int(h * _FIG_TOP)
    cw = int(w * (_FIG_RIGHT - _FIG_LEFT)); ch = int(h * (_FIG_BOT - _FIG_TOP))
    return img.copy(x, y, max(1, cw), max(1, ch))


def _crop_bust(img: QImage) -> QImage:
    w, h = img.width(), img.height()
    if w <= 0 or h <= 0:
        return img
    x = int(w * _BUST_LEFT)
    y = int(h * _BUST_TOP)
    cw = int(w * (_BUST_RIGHT - _BUST_LEFT))
    ch = int(h * (_BUST_BOT - _BUST_TOP))
    return img.copy(x, y, max(1, cw), max(1, ch))


class SkinPhotographer(QObject):
    """Один экземпляр на диалог. request(skin_path, variant, callback)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # QOpenGLWidget рисует только когда «показан», поэтому делаем офскрин-окно
        # (top-level, вынесено далеко за экран, без активации/таскбара). Скрытый
        # (hide/WA_DontShowOnScreen) виджет grabFramebuffer'ит пустой кадр.
        from PyQt6.QtWidgets import QApplication
        self._gl = PlayerGLWidget("steve")
        self._gl.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnBottomHint)
        self._gl.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._gl.setFixedSize(_RENDER_W, _RENDER_H)
        self._gl.move(-4000, -4000)
        self._gl.show()
        try:
            self._gl._no_auto_timer = True   # showEvent не должен перезапускать таймер
            self._gl._timer.stop()   # статично — не крутим анимацию/тик
        except Exception:
            pass
        self._queue: list[tuple] = []
        self._busy = False
        self._warm = False
        self._ok = True

    def close(self):
        """Закрыть офскрин-окно рендера (top-level, не дочернее)."""
        self._queue.clear()
        try:
            self._gl.close()
            self._gl.deleteLater()
        except Exception:
            pass

    def request(self, skin_path: str, variant: str, callback):
        """Бюст скина. callback(QPixmap|None). Кэш-хит → синхронно; иначе в очередь."""
        try:
            p = Path(skin_path)
            if not p.exists():
                callback(None); return
            key = f"{_sha1_file(p)}_{variant}"
            cache = CACHE_DIR / f"skinshot_{key}.png"
            if cache.exists():
                px = QPixmap(str(cache))
                callback(px if not px.isNull() else None)
                return
            self._queue.append({"kind": "skin", "path": str(p), "variant": variant,
                                "cache": cache, "cb": callback})
            self._pump()
        except Exception as e:
            _log.warning("request error: %s", e)
            callback(None)

    def request_cape(self, cape_id, cape_path, callback):
        """Плитка плаща: Стив + плащ в позе cape.demo. Кэш по cape_id (Стив постоянен)."""
        try:
            key = f"cape_{cape_id or 'none'}"
            cache = CACHE_DIR / f"capeshot_{key}.png"
            if cache.exists():
                px = QPixmap(str(cache))
                callback(px if not px.isNull() else None)
                return
            self._queue.append({"kind": "cape", "cape_id": cape_id, "cape_path": cape_path,
                                "cache": cache, "cb": callback})
            self._pump()
        except Exception as e:
            _log.warning("request_cape error: %s", e)
            callback(None)

    def _pump(self):
        if self._busy or not self._queue or not self._ok:
            return
        self._busy = True
        job = self._queue.pop(0)
        try:
            # Прогрев: первый grab инициализирует GL-контекст.
            if not self._warm:
                self._gl.grabFramebuffer()
                self._gl.set_clear_transparent()   # прозрачный фон под градиент
                self._warm = True
            if job["kind"] == "skin":
                model = "alex" if job["variant"] == "slim" else "steve"
                if model != self._gl._model_name:
                    self._gl.set_model(model)
                self._gl.set_cape(None)
                self._gl.set_skin(job["path"])
                self._gl.set_static_pose(_pose_for(_sha1_file(Path(job["path"]))))
                crop = _crop_bust
            else:  # cape — Стив (дефолтный скин) + плащ, поза cape.demo
                if self._gl._model_name != "steve":
                    self._gl.set_model("steve")
                self._gl.set_skin(None)
                self._gl.set_cape(job["cape_path"])
                self._gl.set_static_pose("animation.cape.demo")
                crop = _crop_figure
            QTimer.singleShot(40, lambda: self._grab(job["cache"], job["cb"], crop))
        except Exception as e:
            _log.warning("pump error: %s", e)
            self._ok = False
            self._busy = False
            try:
                job["cb"](None)
            except Exception:
                pass

    def _grab(self, cache: Path, cb, crop):
        px = None
        try:
            img = self._gl.grabFramebuffer()   # QImage
            if img is not None and not img.isNull():
                cropped = crop(img)
                try:
                    cropped.save(str(cache), "PNG")
                except Exception:
                    pass
                px = QPixmap.fromImage(cropped)
        except Exception as e:
            _log.warning("grab error: %s", e)
            self._ok = False
        try:
            cb(px)
        except Exception:
            pass
        self._busy = False
        QTimer.singleShot(0, self._pump)   # следующий из очереди
