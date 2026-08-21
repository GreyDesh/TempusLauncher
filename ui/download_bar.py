"""Попап загрузок — всплывает над кнопкой Загрузки в сайдбаре."""
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QSizePolicy
)
from download_manager import DownloadManager, DownloadTask


class _TaskRow(QWidget):
    ROW_H = 72

    def __init__(self, task: DownloadTask, parent=None):
        super().__init__(parent)
        self._task = task
        self.setFixedHeight(self.ROW_H)
        self.setStyleSheet("background: transparent;")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 8, 14, 8)
        root.setSpacing(5)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)

        self._name_lbl = QLabel(getattr(task, "title", task.mode_name))
        self._name_lbl.setStyleSheet(
            "color: #E6EDF3; font-size: 12px; font-weight: 600; background: transparent;"
        )
        self._name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._state_lbl = QLabel("")
        self._state_lbl.setStyleSheet("color: #7D8590; font-size: 11px; background: transparent;")
        self._state_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._close_btn = QPushButton()
        self._close_btn.setFixedSize(22, 22)
        try:
            from ui.assets import svg_icon as _svg
            self._close_btn.setIcon(_svg("cross.svg", "#ff5c5c", 12))
        except Exception:
            self._close_btn.setText("✕")
        self._close_btn.setStyleSheet("""
            QPushButton { background: transparent; border: 1px solid transparent; border-radius: 4px; }
            QPushButton:hover { border: 1px solid #ff5c5c; background: rgba(255,92,92,15); }
        """)
        self._close_btn.hide()
        self._close_btn.setToolTip("Отменить")
        self._close_btn.clicked.connect(self._on_close_clicked)

        top.addWidget(self._name_lbl)
        top.addWidget(self._state_lbl)
        top.addWidget(self._close_btn)

        self._bar = QProgressBar()
        self._bar.setFixedHeight(3)
        self._bar.setTextVisible(False)
        self._bar.setRange(0, 1000)
        self._bar.setStyleSheet("""
            QProgressBar { background: rgba(255,255,255,10); border-radius: 2px; border: none; }
            QProgressBar::chunk { background: #5B8CFF; border-radius: 2px; }
        """)

        self._msg_lbl = QLabel("")
        self._msg_lbl.setStyleSheet("color: #5a6070; font-size: 10px; background: transparent;")
        self._msg_lbl.setVisible(False)

        root.addLayout(top)
        root.addWidget(self._msg_lbl)
        root.addWidget(self._bar)
        self.update_from_task()

    def _on_close_clicked(self):
        t = self._task
        if t.state == DownloadTask.ERROR:
            DownloadManager.instance().dismiss_error(t.mode_id)
        else:
            DownloadManager.instance().cancel_task(t.mode_id)

    def update_from_task(self):
        t = self._task
        pct = int(t.frac * 100)

        if t.state == DownloadTask.RUNNING:
            self._state_lbl.setText(f"{pct}%")
            self._state_lbl.setStyleSheet("color: #5B8CFF; font-size: 11px; background: transparent;")
            self._bar.setValue(int(t.frac * 1000))
            self._bar.setStyleSheet("""
                QProgressBar { background: rgba(255,255,255,10); border-radius: 2px; border: none; }
                QProgressBar::chunk { background: #5B8CFF; border-radius: 2px; }
            """)
            self._close_btn.show()
            self._close_btn.setToolTip("Отменить")
            self._name_lbl.setText(getattr(t, "title", t.mode_name))
            if t.msg:
                self._msg_lbl.setText(t.msg[:48])
                self._msg_lbl.setVisible(True)
            else:
                self._msg_lbl.setVisible(False)

        elif t.state == DownloadTask.DONE:
            self._state_lbl.setText("Готово")
            self._state_lbl.setStyleSheet("color: #3FB950; font-size: 11px; background: transparent;")
            self._bar.setValue(1000)
            self._bar.setStyleSheet("""
                QProgressBar { background: rgba(255,255,255,10); border-radius: 2px; border: none; }
                QProgressBar::chunk { background: #3FB950; border-radius: 2px; }
            """)
            self._close_btn.hide()
            self._name_lbl.setText(getattr(t, "title", t.mode_name))
            self._msg_lbl.setVisible(False)

        elif t.state == DownloadTask.ERROR:
            self._state_lbl.setText("Ошибка")
            self._state_lbl.setStyleSheet("color: #ff5c5c; font-size: 11px; background: transparent;")
            self._bar.setValue(0)
            self._bar.setStyleSheet("""
                QProgressBar { background: rgba(255,255,255,10); border-radius: 2px; border: none; }
                QProgressBar::chunk { background: #ff5c5c; border-radius: 2px; }
            """)
            self._close_btn.show()
            self._close_btn.setToolTip("Закрыть")
            self._name_lbl.setText(getattr(t, "title", t.mode_name))
            if t.error_msg:
                self._msg_lbl.setText(t.error_msg[:48])
                self._msg_lbl.setVisible(True)
            else:
                self._msg_lbl.setVisible(False)

        elif t.state == DownloadTask.QUEUED:
            self._state_lbl.setText("В очереди")
            self._state_lbl.setStyleSheet("color: #7D8590; font-size: 11px; background: transparent;")
            self._bar.setValue(0)
            self._close_btn.show()
            self._close_btn.setToolTip("Отменить")
            self._name_lbl.setText(getattr(t, "title", t.mode_name))
            self._msg_lbl.setVisible(False)


class DownloadBar(QWidget):
    """Попап загрузок. Позиционируется над кнопкой-триггером."""

    WIDTH = 290
    ROW_H = _TaskRow.ROW_H
    EMPTY_H = 52
    MAX_VISIBLE = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.WIDTH)
        self._rows: dict[str, _TaskRow] = {}
        self._anchor: QPoint = QPoint(0, 0)  # позиция кнопки в координатах parent

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_WState_ExplicitShowHide)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Пустое состояние
        self._empty_lbl = QLabel("Нет активных загрузок")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet(
            "color: #4A5260; font-size: 12px; background: transparent;"
        )
        self._empty_lbl.setFixedHeight(self.EMPTY_H)
        root.addWidget(self._empty_lbl)

        # Список задач (скрыт пока нет задач)
        self._task_container = QWidget()
        self._task_container.setStyleSheet("background: transparent;")
        self._task_lay = QVBoxLayout(self._task_container)
        self._task_lay.setContentsMargins(0, 0, 0, 0)
        self._task_lay.setSpacing(0)
        self._task_container.hide()
        root.addWidget(self._task_container)

        dm = DownloadManager.instance()
        dm.task_added.connect(self._on_task_added)
        dm.task_updated.connect(self._on_task_updated)
        dm.task_removed.connect(self._on_task_removed)

        self._relayout()
        self.hide()

    def set_anchor(self, pos: QPoint):
        """Запоминаем позицию кнопки-триггера (в coord. parent)."""
        self._anchor = pos
        self._reposition()

    def _on_task_added(self, task: DownloadTask):
        row = _TaskRow(task, self._task_container)
        self._rows[task.mode_id] = row
        self._task_lay.addWidget(row)
        self._relayout()
        if self.isVisible():
            self.raise_()

    def _on_task_updated(self, task: DownloadTask):
        row = self._rows.get(task.mode_id)
        if row:
            row.update_from_task()

    def _on_task_removed(self, mode_id: str):
        row = self._rows.pop(mode_id, None)
        if row:
            self._task_lay.removeWidget(row)
            row.deleteLater()
        self._relayout()

    def _relayout(self):
        n = len(self._rows)
        if n == 0:
            self._empty_lbl.show()
            self._task_container.hide()
            total = self.EMPTY_H
        else:
            self._empty_lbl.hide()
            self._task_container.show()
            total = min(n, self.MAX_VISIBLE) * self.ROW_H
            self._task_container.setFixedHeight(total)

        self.setFixedHeight(total)
        self._reposition()

    def _reposition(self):
        parent = self.parent()
        if not parent:
            return
        # Выравниваем левый край по кнопке, появляемся ВЫШЕ неё
        x = self._anchor.x()
        y = self._anchor.y() - self.height() - 8
        # Не выходить за левый край
        x = max(4, x)
        # Не выходить за правый край
        x = min(x, parent.width() - self.WIDTH - 4)
        self.move(x, y)

    def reposition(self):
        self._reposition()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 10, 10)
        p.fillPath(path, QColor(18, 22, 30, 242))
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.drawPath(path)
