from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QPushButton, QFrame, QApplication
)


class LogDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Логи")
        self.resize(700, 440)
        self.setStyleSheet("QDialog { background: #0a0a14; }")
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        self._title_lbl = QLabel("Логи запуска")
        self._title_lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet("color: #ffffff;")
        root.addWidget(self._title_lbl)

        self._error_banner = QLabel("")
        self._error_banner.setWordWrap(True)
        self._error_banner.setStyleSheet("""
            background: rgba(255,92,92,30);
            border: 1px solid rgba(255,92,92,80);
            border-radius: 8px;
            color: #ff8888;
            padding: 10px 14px;
            font-size: 13px;
        """)
        self._error_banner.hide()
        root.addWidget(self._error_banner)

        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setFont(QFont("Consolas", 11))
        root.addWidget(self._log_edit)

        btn_row = QHBoxLayout()
        copy_btn = QPushButton("Скопировать лог")
        copy_btn.setFixedHeight(38)
        copy_btn.clicked.connect(self._copy_log)

        close_btn = QPushButton("Закрыть")
        close_btn.setFixedHeight(38)
        close_btn.setProperty("class", "secondary")
        close_btn.setStyleSheet("""
            QPushButton { background: rgba(255,255,255,12); color: #c8c8e0;
                border: 1px solid rgba(255,255,255,18); border-radius: 8px; }
            QPushButton:hover { background: rgba(255,255,255,22); }
        """)
        close_btn.clicked.connect(self.hide)

        btn_row.addStretch()
        btn_row.addWidget(copy_btn)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    def set_title(self, title: str):
        self.setWindowTitle(title)
        self._title_lbl.setText(title)

    def show_error(self, message: str):
        self._error_banner.setText(f"⚠  {message}")
        self._error_banner.show()

    @pyqtSlot(str)
    def append_log(self, line: str):
        self._log_edit.append(line)
        sb = self._log_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _copy_log(self):
        QApplication.clipboard().setText(self._log_edit.toPlainText())

    def clear(self):
        self._log_edit.clear()
        self._error_banner.hide()
