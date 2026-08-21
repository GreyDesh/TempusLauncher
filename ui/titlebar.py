from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton


class TitleBar(QWidget):
    """Кастомный заголовок окна с кнопками сворачивания/разворачивания/закрытия."""

    def __init__(self, parent: QWidget, title: str = "", show_maximize: bool = True, show_minimize: bool = True):
        super().__init__(parent)
        self._parent = parent
        self._drag_pos: QPoint | None = None
        self.setFixedHeight(44)
        self.setStyleSheet("background: rgba(8,8,18,200); border-bottom: 1px solid rgba(255,255,255,12);")
        self._build_ui(title, show_maximize, show_minimize)

    def _build_ui(self, title: str, show_maximize: bool, show_minimize: bool = True):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 12, 0)
        layout.setSpacing(0)

        self._title_lbl = QLabel(title)
        self._title_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet("color: #c8c8e0; background: transparent;")

        layout.addWidget(self._title_lbl)
        layout.addStretch()

        btn_style = """
            QPushButton {{
                background: transparent;
                color: {color};
                border: none;
                font-size: 16px;
                width: 36px;
                height: 36px;
                border-radius: 8px;
                padding: 0;
            }}
            QPushButton:hover {{ background: {hover}; }}
        """

        self._min_btn = QPushButton("─")
        self._min_btn.setFixedSize(36, 36)
        self._min_btn.setStyleSheet(btn_style.format(color="#8888aa", hover="rgba(255,255,255,15)"))
        self._min_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._min_btn.clicked.connect(self._parent.showMinimized)

        if show_maximize:
            self._max_btn = QPushButton("□")
            self._max_btn.setFixedSize(36, 36)
            self._max_btn.setStyleSheet(btn_style.format(color="#8888aa", hover="rgba(255,255,255,15)"))
            self._max_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._max_btn.clicked.connect(self._toggle_maximize)

        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(36, 36)
        self._close_btn.setStyleSheet(btn_style.format(color="#ff5c5c", hover="rgba(255,92,92,40)"))
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.clicked.connect(self._parent.close)

        if show_minimize:
            layout.addWidget(self._min_btn)
        if show_maximize:
            layout.addWidget(self._max_btn)
        layout.addWidget(self._close_btn)

    def set_title(self, title: str):
        self._title_lbl.setText(title)

    def _toggle_maximize(self):
        if self._parent.isMaximized():
            self._parent.showNormal()
            self._max_btn.setText("□")
        else:
            self._parent.showMaximized()
            self._max_btn.setText("❐")

    # ── Drag to move ──────────────────────────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self._parent.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            if self._parent.isMaximized():
                self._parent.showNormal()
                if hasattr(self, "_max_btn"):
                    self._max_btn.setText("□")
            self._parent.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
