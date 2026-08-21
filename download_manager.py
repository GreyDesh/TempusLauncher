# Глобальный менеджер загрузок — синглтон, живёт всё время работы лаунчера.
from __future__ import annotations
from PyQt6.QtCore import QObject, pyqtSignal, QThread


class DownloadTask(QObject):
    progress = pyqtSignal(str, float)   # (msg, 0..1)
    done     = pyqtSignal()
    error    = pyqtSignal(str)

    QUEUED      = "queued"
    RUNNING     = "running"
    DONE        = "done"
    ERROR       = "error"

    def __init__(self, mode: dict, launcher_config: dict):
        super().__init__()
        self.mode            = mode
        self.launcher_config = launcher_config
        self.mode_id: str    = mode["id"]
        self.mode_name: str  = mode.get("name", mode["id"])
        self.title: str      = self.mode_name   # что показывать в баре загрузок
        self.kind: str       = "install"        # install | verify
        self.state: str      = self.QUEUED
        self.msg: str        = ""
        self.frac: float     = 0.0
        self.error_msg: str  = ""
        self._thread: _Worker | None = None

    def start(self):
        self.state = self.RUNNING
        self._thread = _Worker(self.mode, self.launcher_config)
        self._thread.progress.connect(self._on_progress)
        self._thread.done.connect(self._on_done)
        self._thread.error.connect(self._on_error)
        self._thread.start()

    def cancel(self):
        if self._thread:
            self._thread.cancel()
        self.state = "cancelled"

    def _on_progress(self, msg: str, frac: float):
        self.msg  = msg
        self.frac = frac
        self.progress.emit(msg, frac)

    def _on_done(self):
        self.state = self.DONE
        self.frac  = 1.0
        self.done.emit()

    def _on_error(self, err: str):
        self.state     = self.ERROR
        self.error_msg = err
        self.error.emit(err)


class _Worker(QThread):
    progress = pyqtSignal(str, float)
    done     = pyqtSignal()
    error    = pyqtSignal(str)

    def __init__(self, mode: dict, launcher_config: dict):
        super().__init__()
        self._mode      = mode
        self._config    = launcher_config
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        self.requestInterruption()
        self.terminate()

    def run(self):
        try:
            from downloader import install_mode
            install_mode(self._mode, lambda m, f: self.progress.emit(m, f), self._config)
            if not self._cancelled:
                self.done.emit()
        except Exception as e:
            if not self._cancelled:
                self.error.emit(str(e))


class DownloadManager(QObject):
    """Синглтон. Хранит задачи, нотифицирует слушателей."""
    task_added   = pyqtSignal(object)   # DownloadTask
    task_updated = pyqtSignal(object)   # DownloadTask
    task_removed = pyqtSignal(str)      # mode_id

    _instance: DownloadManager | None = None

    @classmethod
    def instance(cls) -> "DownloadManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._tasks: dict[str, DownloadTask] = {}

    def enqueue(self, mode: dict, launcher_config: dict,
                title: str = None, kind: str = "install") -> DownloadTask:
        mode_id = mode["id"]
        if mode_id in self._tasks:
            return self._tasks[mode_id]
        task = DownloadTask(mode, launcher_config)
        if title:
            task.title = title
        task.kind = kind
        self._tasks[mode_id] = task
        task.progress.connect(lambda m, f, t=task: self.task_updated.emit(t))
        task.done.connect(lambda t=task: self._on_done(t))
        task.error.connect(lambda e, t=task: self._on_error(t))
        self.task_added.emit(task)
        task.start()
        return task

    def get(self, mode_id: str) -> DownloadTask | None:
        return self._tasks.get(mode_id)

    def is_active(self, mode_id: str) -> bool:
        t = self._tasks.get(mode_id)
        return t is not None and t.state in (DownloadTask.QUEUED, DownloadTask.RUNNING)

    def _on_done(self, task: DownloadTask):
        self.task_updated.emit(task)
        # Тост «готово» для установки/обновления (для проверки целостности — не показываем).
        # Без звука: это результат действия самого игрока, не внешнее уведомление.
        if getattr(task, "kind", "install") != "verify":
            try:
                from ui.toast import show_toast
                icon = ""
                logo = (task.mode or {}).get("logo_url", "")
                if logo:
                    from config import MEDIA_CACHE_DIR
                    from pathlib import Path
                    cand = MEDIA_CACHE_DIR / Path(logo).name
                    if cand.exists():
                        icon = str(cand)
                show_toast(task.mode_name, "Установлено — можно играть", icon)
            except Exception:
                pass
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(3000, lambda: self._remove(task.mode_id))

    def _on_error(self, task: DownloadTask):
        self.task_updated.emit(task)

    def _remove(self, mode_id: str):
        self._tasks.pop(mode_id, None)
        self.task_removed.emit(mode_id)

    def cancel_task(self, mode_id: str):
        task = self._tasks.get(mode_id)
        if task:
            task.cancel()
            self._remove(mode_id)

    def dismiss_error(self, mode_id: str):
        self._remove(mode_id)

    @property
    def tasks(self) -> list[DownloadTask]:
        return list(self._tasks.values())
