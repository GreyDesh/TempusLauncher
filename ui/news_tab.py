from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QFrame
)
from assets_cache import AssetCache


class NewsCard(QFrame):
    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QFrame {
                background: rgba(255,255,255,6);
                border-radius: 12px;
                border: 1px solid rgba(255,255,255,12);
            }
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(16)

        # Изображение
        if item.get("image_url"):
            self._img = QLabel()
            self._img.setFixedSize(120, 80)
            self._img.setStyleSheet("border-radius: 8px; background: rgba(255,255,255,10);")
            self._img.setAlignment(Qt.AlignmentFlag.AlignCenter)
            AssetCache.load(item["image_url"], self._on_img)
            layout.addWidget(self._img)

        # Текст
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        date_lbl = QLabel(item.get("date", ""))
        date_lbl.setStyleSheet("color: #5B8CFF; font-size: 11px; font-weight: 600;")

        title_lbl = QLabel(item.get("title", ""))
        title_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #e8e8f0;")
        title_lbl.setWordWrap(True)

        content_lbl = QLabel(item.get("content", ""))
        content_lbl.setStyleSheet("color: #8888aa; font-size: 12px;")
        content_lbl.setWordWrap(True)

        text_layout.addWidget(date_lbl)
        text_layout.addWidget(title_lbl)
        text_layout.addWidget(content_lbl)
        text_layout.addStretch()
        layout.addLayout(text_layout, 1)

    def _on_img(self, url: str, px: QPixmap):
        self._img.setPixmap(
            px.scaled(120, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )


class NewsTab(QWidget):
    def __init__(self, news: list, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(0)

        title = QLabel("Новости")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff; margin-bottom: 12px;")
        root.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 8, 0)
        self._list_layout.setSpacing(10)

        for item in news:
            self._list_layout.addWidget(NewsCard(item))
        self._list_layout.addStretch()

        scroll.setWidget(self._list_widget)
        root.addWidget(scroll)

    def update_news(self, news: list):
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for item in news:
            self._list_layout.addWidget(NewsCard(item))
        self._list_layout.addStretch()
