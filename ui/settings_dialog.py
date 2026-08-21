import json
import shutil
from pathlib import Path
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QSlider, QLineEdit, QPushButton, QCheckBox,
    QFileDialog, QFrame
)
from config import SETTINGS_FILE, DEFAULT_RAM_MB


def _load() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(data: dict):
    existing = _load()
    existing.update(data)
    SETTINGS_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


class SettingsDialog(QDialog):
    verify_requested = pyqtSignal(dict)   # запросить проверку целостности сборки
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        # Ширина фиксирована, высота — минимум (растёт под контент при масштабе Windows >100%,
        # иначе нижние кнопки Сохранить/Отмена обрезались).
        self.setFixedWidth(480)
        self.setMinimumHeight(596)
        self.setStyleSheet("""
            QDialog { background: #0d0d18; border-radius: 14px; }
        """)
        self._mode: dict = {}
        self._launcher_config: dict = {}
        self.delete_requested = False
        self._build_ui()
        self._load_settings()

    def set_mode(self, mode: dict, launcher_config: dict = None):
        self._mode = mode
        self._launcher_config = launcher_config or {}
        self.delete_requested = False
        installed = False
        if mode.get("id"):
            from downloader import is_installed
            installed = is_installed(mode)
        self._delete_section.setVisible(installed)
        if installed:
            self._delete_lbl.setText(f"Сборка «{mode.get('name', '')}» установлена")
        version = mode.get("modpack", {}).get("version") or mode.get("version")
        self._version_lbl.setText(f"v{version}" if version else "")

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        from ui.titlebar import TitleBar
        tb = TitleBar(self, "Настройки", show_maximize=False, show_minimize=False)
        tb.setFixedWidth(480)
        root.addWidget(tb)

        inner = QVBoxLayout()
        inner.setContentsMargins(28, 16, 28, 24)
        inner.setSpacing(20)
        root.addLayout(inner)
        root = inner

        title = QLabel("Настройки Minecraft")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff;")
        root.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: rgba(255,255,255,15);")
        root.addWidget(sep)

        # RAM
        ram_section = QVBoxLayout()
        ram_header = QHBoxLayout()
        ram_lbl = QLabel("Оперативная память")
        ram_lbl.setStyleSheet("color: #c8c8e0; font-weight: 600;")
        self._ram_value_lbl = QLabel("2048 МБ")
        self._ram_value_lbl.setStyleSheet("color: #5B8CFF; font-weight: 600;")
        ram_header.addWidget(ram_lbl)
        ram_header.addStretch()
        ram_header.addWidget(self._ram_value_lbl)

        self._ram_auto_check = QCheckBox("Авто")
        self._ram_auto_check.setStyleSheet("color: #8888aa; font-size: 11px;")
        self._ram_auto_check.toggled.connect(self._on_ram_auto_toggled)
        ram_header.addSpacing(10)
        ram_header.addWidget(self._ram_auto_check)

        self._ram_slider = QSlider(Qt.Orientation.Horizontal)
        self._ram_slider.setRange(512, 16384)
        self._ram_slider.setSingleStep(256)
        self._ram_slider.setPageStep(512)
        self._ram_slider.valueChanged.connect(self._on_ram_changed)
        ram_section.addLayout(ram_header)
        ram_section.addWidget(self._ram_slider)
        root.addLayout(ram_section)

        # Java path
        java_section = QVBoxLayout()
        java_section.setSpacing(6)
        java_lbl = QLabel("Путь к Java")
        java_lbl.setStyleSheet("color: #c8c8e0; font-weight: 600;")
        java_row = QHBoxLayout()
        java_row.setSpacing(8)
        self._java_edit = QLineEdit()
        self._java_edit.setPlaceholderText("Авто (определится автоматически)")
        self._java_edit.setFixedHeight(38)
        java_browse = QPushButton("Обзор")
        java_browse.setFixedHeight(38)
        java_browse.setFixedWidth(110)
        java_browse.clicked.connect(self._browse_java)
        java_row.addWidget(self._java_edit)
        java_row.addWidget(java_browse)
        java_section.addWidget(java_lbl)
        java_section.addLayout(java_row)
        root.addLayout(java_section)

        # Show logs
        self._logs_check = QCheckBox("Показывать консоль логов при запуске")
        self._logs_check.setStyleSheet("color: #c8c8e0;")
        root.addWidget(self._logs_check)

        root.addStretch()

        # Удаление сборки
        self._delete_section = QFrame()
        self._delete_section.setStyleSheet("""
            QFrame { background: rgba(255,255,255,5);
                     border: 1px solid rgba(255,255,255,12); border-radius: 10px; }
        """)
        self._delete_section.setVisible(False)
        del_lay = QVBoxLayout(self._delete_section)
        del_lay.setContentsMargins(14, 14, 14, 14)
        del_lay.setSpacing(14)

        self._delete_lbl = QLabel("")
        self._delete_lbl.setStyleSheet("color: #8888aa; font-size: 11px; background: transparent; border: none;")

        from ui.assets import svg_icon
        open_btn = QPushButton("  Открыть папку с игрой")
        open_btn.setIcon(svg_icon("folder.svg", "#ffffff"))
        open_btn.setIconSize(__import__('PyQt6.QtCore', fromlist=['QSize']).QSize(16, 16))
        open_btn.setFixedHeight(36)
        open_btn.setStyleSheet("""
            QPushButton { background: rgba(91,140,255,100); color: #fff;
                border: none; border-radius: 8px; font-weight: 600; font-size: 12px; }
            QPushButton:hover { background: rgba(91,140,255,180); }
        """)
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.clicked.connect(self._on_open_folder)

        verify_btn = QPushButton("  Проверка целостности файлов")
        try:
            verify_btn.setIcon(svg_icon("refresh.svg", "#ffffff"))
            verify_btn.setIconSize(__import__('PyQt6.QtCore', fromlist=['QSize']).QSize(16, 16))
        except Exception:
            pass
        verify_btn.setFixedHeight(36)
        verify_btn.setStyleSheet("""
            QPushButton { background: rgba(245,158,11,200); color: #fff;
                border: none; border-radius: 8px; font-weight: 600; font-size: 12px; }
            QPushButton:hover { background: rgba(245,158,11,255); }
            QPushButton:disabled { background: rgba(245,158,11,90); color: rgba(255,255,255,140); }
        """)
        verify_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        verify_btn.clicked.connect(self._on_verify)
        self._verify_btn = verify_btn

        del_btn = QPushButton("  Удалить сборку")
        del_btn.setIcon(svg_icon("trash.svg", "#ffffff"))
        del_btn.setIconSize(__import__('PyQt6.QtCore', fromlist=['QSize']).QSize(16, 16))
        del_btn.setFixedHeight(36)
        del_btn.setStyleSheet("""
            QPushButton { background: rgba(255,92,92,100); color: #fff;
                border: none; border-radius: 8px; font-weight: 600; font-size: 12px; }
            QPushButton:hover { background: rgba(255,92,92,200); }
        """)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.clicked.connect(self._on_delete)

        del_lay.addWidget(self._delete_lbl)
        del_lay.addWidget(open_btn)
        del_lay.addWidget(verify_btn)
        del_lay.addWidget(del_btn)
        root.addWidget(self._delete_section)

        # Кнопки
        btn_row = QHBoxLayout()
        self._version_lbl = QLabel("")
        self._version_lbl.setStyleSheet("color: rgba(255,255,255,0.18); font-size: 11px;")
        btn_row.addWidget(self._version_lbl)
        btn_row.addStretch()
        save_btn = QPushButton("Сохранить")
        save_btn.setFixedHeight(40)
        save_btn.setFixedWidth(120)
        save_btn.clicked.connect(self._save_and_close)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.setFixedHeight(40)
        cancel_btn.setFixedWidth(100)
        cancel_btn.setProperty("class", "secondary")
        cancel_btn.setStyleSheet("""
            QPushButton { background: rgba(255,255,255,12); color: #c8c8e0;
                border: 1px solid rgba(255,255,255,18); border-radius: 8px; font-size: 13px; }
            QPushButton:hover { background: rgba(255,255,255,22); }
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

    def _on_ram_auto_toggled(self, checked: bool):
        self._ram_slider.setEnabled(not checked)
        if checked:
            from launcher import auto_ram_mb
            auto = auto_ram_mb()
            self._ram_slider.setValue(auto)
            self._ram_value_lbl.setText(f"{auto} МБ  (авто)")
        else:
            self._on_ram_changed(self._ram_slider.value())

    def _on_ram_changed(self, value: int):
        if not self._ram_auto_check.isChecked():
            self._ram_value_lbl.setText(f"{value} МБ")

    def _browse_java(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выберите java.exe", "", "Java (java.exe);;Все файлы (*)")
        if path:
            self._java_edit.setText(path)

    def _load_settings(self):
        s = _load()
        ram_auto = s.get("ram_auto", True)
        self._ram_auto_check.setChecked(ram_auto)
        if ram_auto:
            from launcher import auto_ram_mb
            auto = auto_ram_mb()
            self._ram_slider.setValue(auto)
            self._ram_slider.setEnabled(False)
            self._ram_value_lbl.setText(f"{auto} МБ  (авто)")
        else:
            ram = s.get("ram_mb", DEFAULT_RAM_MB)
            self._ram_slider.setValue(ram)
            self._ram_value_lbl.setText(f"{ram} МБ")
        java = s.get("java_path", "")
        if java:
            self._java_edit.setText(java)
        self._logs_check.setChecked(s.get("show_logs", False))

    def _on_open_folder(self):
        import subprocess
        from config import MINECRAFT_DIR
        folder = MINECRAFT_DIR / self._mode.get("id", "")
        if folder.exists():
            subprocess.Popen(f'explorer "{folder}"')

    def _on_verify(self):
        if not self._mode.get("id"):
            return
        # Проверка идёт через общий менеджер загрузок: видна во вкладке «Загрузки»,
        # блокирует «Играть». Закрываем окно, чтобы показать прогресс на главном экране.
        self.verify_requested.emit(self._mode)
        self.accept()

    def _on_delete(self):
        from PyQt6.QtWidgets import QMessageBox
        from downloader import remove_mode
        name = self._mode.get("name", "эту сборку")
        reply = QMessageBox.question(
            self, "Удалить сборку",
            f"Удалить «{name}»?\nВсе файлы игры будут удалены.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            remove_mode(self._mode.get("id", ""))
            self.delete_requested = True
            self._delete_section.setVisible(False)
            self.accept()

    def _save_and_close(self):
        _save({
            "ram_auto": self._ram_auto_check.isChecked(),
            "ram_mb": self._ram_slider.value(),
            "java_path": self._java_edit.text().strip() or None,
            "show_logs": self._logs_check.isChecked(),
        })
        self.accept()
