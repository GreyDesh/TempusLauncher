"""Диалог первого запуска — объясняет предупреждение Windows SmartScreen."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget
)


class FirstRunDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TempusLauncher")
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Высота — минимум (растёт под контент при масштабе Windows >100%).
        self.setFixedWidth(420)
        self.setMinimumHeight(320)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(0)

        card = QWidget()
        card.setObjectName("card")
        card.setStyleSheet("""
            QWidget#card {
                background: #0d0d14;
                border: 1px solid rgba(91,140,255,60);
                border-radius: 14px;
            }
        """)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(28, 24, 28, 24)
        card_lay.setSpacing(14)

        # Заголовок
        title_row = QHBoxLayout()
        title_row.setSpacing(10)

        icon_lbl = QLabel("⚠")
        icon_lbl.setStyleSheet("color: #f0a500; font-size: 22px; background: transparent;")
        icon_lbl.setFixedWidth(30)

        title_lbl = QLabel("Предупреждение Windows")
        title_lbl.setStyleSheet(
            "color: #E6EDF3; font-size: 15px; font-weight: 700; background: transparent;"
        )

        title_row.addWidget(icon_lbl)
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        card_lay.addLayout(title_row)

        # Разделитель
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(255,255,255,10); border: none;")
        card_lay.addWidget(sep)
        card_lay.addSpacing(4)

        # Основной текст
        body = QLabel(
            "При первом запуске <b>TempusLauncher.exe</b> Windows может показать "
            "предупреждение безопасности:\n"
            "<i>«Windows защитила ваш компьютер»</i>\n\n"
            "Это происходит потому что приложение не прошло платную "
            "верификацию Microsoft. Лаунчер безопасен."
        )
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setStyleSheet(
            "color: #8b949e; font-size: 12px; line-height: 1.5; background: transparent;"
        )
        card_lay.addWidget(body)

        # Инструкция
        steps_bg = QWidget()
        steps_bg.setStyleSheet(
            "background: rgba(91,140,255,12); border-radius: 8px; border: 1px solid rgba(91,140,255,30);"
        )
        steps_lay = QVBoxLayout(steps_bg)
        steps_lay.setContentsMargins(14, 10, 14, 10)
        steps_lay.setSpacing(5)

        def _step(text):
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #c9d1d9; font-size: 12px; background: transparent;")
            lbl.setWordWrap(True)
            return lbl

        steps_lay.addWidget(_step("1. Нажмите  <b style='color:#5B8CFF'>Подробнее</b>"))
        steps_lay.addWidget(_step("2. Нажмите  <b style='color:#3FB950'>Выполнить всё равно</b>"))
        card_lay.addWidget(steps_bg)

        card_lay.addSpacing(6)

        # Кнопка
        btn = QPushButton("Понятно, не показывать снова")
        btn.setFixedHeight(38)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                background: rgba(91,140,255,20);
                color: #5B8CFF;
                border: 1px solid rgba(91,140,255,60);
                border-radius: 8px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(91,140,255,35);
                border-color: rgba(91,140,255,120);
                color: #ffffff;
            }
            QPushButton:pressed {
                background: rgba(91,140,255,50);
            }
        """)
        btn.clicked.connect(self.accept)
        card_lay.addWidget(btn)

        root.addWidget(card)

    def paintEvent(self, e):
        pass  # фон прозрачный, карточка рисует себя сама


def show_if_first_run() -> bool:
    """Показывает диалог если первый запуск. Возвращает True если показал."""
    from config import DATA_DIR
    flag = DATA_DIR / ".first_run_done"
    if flag.exists():
        return False
    dlg = FirstRunDialog()
    dlg.exec()
    flag.touch()
    return True
