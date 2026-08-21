#Окно переписки с другом — UI-СКЕЛЕТ.

#Визуальная часть готова (пузыри, read-receipts, поле ввода). 
# Данные пока идут через заглушки chat_client (см. TODO там). Реальную загрузку истории и доставку по SSE подключим на этапе бэкенда.

import threading
from datetime import datetime, timezone

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QScrollArea, QWidget, QFrame, QSizePolicy,
)

import chat_client

# Кэш истории в памяти: friend_uuid -> список сообщений. Живёт всё время работы
# лаунчера, поэтому повторное открытие переписки мгновенно, без пустого мигания.
_history_cache: dict[str, list] = {}


def preload_all():
    """После запуска лаунчера фоново подгружает историю всех переписок в кэш,
    чтобы любое окно чата открывалось мгновенно (без запроса и пустого мигания)."""
    def _run():
        try:
            import requests, config, auth_client
            r = requests.get(
                f"{config.SERVER_URL}/api/friends",
                headers=auth_client.session_headers(),
                timeout=8, verify=chat_client._verify())
            friends = r.json().get("friends", []) if r.status_code == 200 else []
        except Exception:
            friends = []
        for f in friends:
            u = f.get("uuid")
            if u and u not in _history_cache:
                try:
                    _history_cache[u] = chat_client.fetch_history(u)
                except Exception:
                    pass
    threading.Thread(target=_run, daemon=True).start()


def _fmt_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso).astimezone()
        return dt.strftime("%H:%M")
    except Exception:
        return ""


class MessageBubble(QWidget):
    """Один пузырь сообщения. Для своих — справа (синий) + галочки прочтения."""

    def __init__(self, msg: dict, parent=None):
        super().__init__(parent)
        self._mine = bool(msg.get("mine"))
        self._read = bool(msg.get("read"))
        self._read_lbl: QLabel | None = None
        self._build(msg)

    def _build(self, msg: dict):
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        bubble = QFrame()
        bubble.setMaximumWidth(300)
        bubble.setStyleSheet(
            "QFrame { background: %s; border-radius: 12px; }"
            % ("rgba(88,101,242,210)" if self._mine else "rgba(255,255,255,16)")
        )
        b = QVBoxLayout(bubble)
        b.setContentsMargins(12, 8, 12, 6)
        b.setSpacing(2)

        text = QLabel(msg.get("body", ""))
        text.setWordWrap(True)
        text.setStyleSheet("color: #ffffff; background: transparent; font-size: 13px;")
        b.addWidget(text)

        meta = QHBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(6)
        meta.addStretch()
        time_lbl = QLabel(_fmt_time(msg.get("created_at", "")))
        time_lbl.setStyleSheet("color: rgba(255,255,255,150); background: transparent; font-size: 10px;")
        meta.addWidget(time_lbl)
        if self._mine:
            self._read_lbl = QLabel("✓✓" if self._read else "✓")
            self._read_lbl.setStyleSheet(
                "color: %s; background: transparent; font-size: 10px; font-weight: 700;"
                % ("#9fd0ff" if self._read else "rgba(255,255,255,150)")
            )
            meta.addWidget(self._read_lbl)
        b.addLayout(meta)

        if self._mine:
            row.addStretch()
            row.addWidget(bubble)
        else:
            row.addWidget(bubble)
            row.addStretch()

    def set_read(self, read: bool):
        """Отметить своё сообщение прочитанным (галочки → синие ✓✓)."""
        self._read = read
        if self._read_lbl:
            self._read_lbl.setText("✓✓" if read else "✓")
            self._read_lbl.setStyleSheet(
                "color: %s; background: transparent; font-size: 10px; font-weight: 700;"
                % ("#9fd0ff" if read else "rgba(255,255,255,150)")
            )


class ChatWindow(QDialog):
    """Немодальное окно переписки (можно открыть несколько на разных друзей)."""

    closed = pyqtSignal(str)   # friend_uuid — чтобы панель могла убрать из реестра
    _history_ready = pyqtSignal(list)   # маршалинг истории из фонового потока в UI
    _avatar_ready = pyqtSignal(str)     # путь к файлу головы (строим QPixmap в UI-потоке)

    def __init__(self, friend_uuid: str, friend_name: str, online: bool = False, parent=None):
        super().__init__(parent)
        self._uuid = friend_uuid
        self._name = friend_name
        self._online = online
        self._bubbles: list[MessageBubble] = []
        self._history_ready.connect(self._on_history)
        self._avatar_ready.connect(self._set_avatar)

        self.setWindowTitle(f"Чат · {friend_name}")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog | Qt.WindowType.Tool)
        self.setStyleSheet("QDialog { background: #0d0d18; }")
        # Ширина фиксирована, высота — минимум (DPI-safe, растёт под контент)
        self.setFixedWidth(440)
        self.setMinimumHeight(560)

        self._build_ui()
        self._load_history()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        from ui.titlebar import TitleBar
        tb = TitleBar(self, f"Чат · {self._name}", show_maximize=False, show_minimize=False)
        tb.setFixedWidth(440)
        root.addWidget(tb)

        # Шапка: аватар + имя + статус
        header = QWidget()
        header.setObjectName("chatHeader")
        # Селектор #chatHeader — чтобы border-bottom НЕ каскадился на дочерние QLabel
        header.setStyleSheet(
            "#chatHeader { background: rgba(255,255,255,4);"
            " border-bottom: 1px solid rgba(255,255,255,10); }")
        h = QHBoxLayout(header)
        h.setContentsMargins(14, 8, 14, 8)
        h.setSpacing(10)

        self._avatar = QLabel()
        self._avatar.setFixedSize(34, 34)
        self._avatar.setStyleSheet("background: #1a1a2e; border-radius: 7px;")
        h.addWidget(self._avatar)

        col = QVBoxLayout()
        col.setSpacing(0)
        name = QLabel(self._name)
        name.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        name.setStyleSheet("color: #e6edf3; background: transparent;")
        status = QLabel("В сети" if self._online else "Не в сети")
        status.setStyleSheet(
            "color: %s; background: transparent; font-size: 11px;"
            % ("#5B8CFF" if self._online else "#555570")
        )
        col.addWidget(name)
        col.addWidget(status)
        h.addLayout(col, 1)
        root.addWidget(header)

        # Лента сообщений
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { background: transparent; width: 6px; }
            QScrollBar::handle:vertical { background: #2a2a4a; border-radius: 3px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        self._list_w = QWidget()
        self._list_w.setStyleSheet("background: transparent;")
        self._list = QVBoxLayout(self._list_w)
        self._list.setContentsMargins(12, 12, 12, 12)
        self._list.setSpacing(8)
        self._list.addStretch()   # прижимаем сообщения к низу, когда их мало
        self._scroll.setWidget(self._list_w)
        root.addWidget(self._scroll, 1)

        # Пустое состояние — по центру области сообщений (отдельный блок, переключается
        # со скроллом: нет сообщений → показываем его, есть → показываем ленту)
        self._empty_lbl = QLabel("Пока нет сообщений.\nНапишите первым!")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet("color: #555570; font-size: 12px; background: transparent;")
        root.addWidget(self._empty_lbl, 1)

        # Индикатор загрузки (пока история тянется с сервера, если её нет в кэше)
        self._loading_lbl = QLabel("Загрузка…")
        self._loading_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_lbl.setStyleSheet("color: #8888aa; font-size: 12px; background: transparent;")
        root.addWidget(self._loading_lbl, 1)
        self._loading_lbl.hide()

        self._scroll.hide()   # по умолчанию сообщений нет

        # Ввод
        input_row = QWidget()
        input_row.setObjectName("chatInput")
        input_row.setStyleSheet(
            "#chatInput { background: rgba(255,255,255,4);"
            " border-top: 1px solid rgba(255,255,255,10); }")
        ir = QHBoxLayout(input_row)
        ir.setContentsMargins(12, 10, 12, 12)
        ir.setSpacing(8)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Сообщение…")
        self._input.setFixedHeight(38)
        self._input.setMaxLength(2000)
        self._input.setStyleSheet("""
            QLineEdit { background: rgba(255,255,255,10); color: #e0e0f0;
                border: 1px solid rgba(255,255,255,15); border-radius: 10px;
                padding: 0 12px; font-size: 13px; }
            QLineEdit:focus { border-color: rgba(88,101,242,170); }
        """)
        self._input.returnPressed.connect(self._on_send)
        send_btn = QPushButton()
        send_btn.setFixedSize(44, 38)
        send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        try:
            from ui.assets import svg_icon as _svg
            from PyQt6.QtCore import QSize
            send_btn.setIcon(_svg("paper_plane.svg", "#ffffff", 18))
            send_btn.setIconSize(QSize(18, 18))
        except Exception:
            send_btn.setText("➤")
        send_btn.setStyleSheet("""
            QPushButton { background: #5865F2; color: #fff; border: none;
                border-radius: 10px; font-size: 16px; font-weight: 700; }
            QPushButton:hover { background: #7983f5; }
        """)
        send_btn.clicked.connect(self._on_send)
        ir.addWidget(self._input, 1)
        ir.addWidget(send_btn)
        root.addWidget(input_row)

        self._load_avatar()

    # ── Данные ──────────────────────────────────────────────────────────────────

    def _load_history(self):
        """Мгновенно рисуем из кэша (если есть), затем в фоне тянем свежее с сервера."""
        cached = _history_cache.get(self._uuid)
        if cached is not None:
            self._on_history(cached)
        else:
            # нет кэша — показываем индикатор загрузки вместо «нет сообщений»
            self._empty_lbl.hide()
            self._scroll.hide()
            self._loading_lbl.show()
        def _run():
            msgs = chat_client.fetch_history(self._uuid)
            _history_cache[self._uuid] = msgs
            self._history_ready.emit(msgs)
            chat_client.mark_read(self._uuid)
        threading.Thread(target=_run, daemon=True).start()

    def _on_history(self, msgs: list):
        self._loading_lbl.hide()
        # Не перерисовываем, если содержимое (id + прочитанность) не изменилось —
        # это убирает мигание при повторном открытии/обновлении.
        sig = [(m.get("id"), bool(m.get("read"))) for m in msgs]
        if sig == getattr(self, "_sig", None):
            return
        self._sig = sig
        for b in self._bubbles:
            b.deleteLater()
        self._bubbles.clear()
        if not msgs:
            if self._scroll.isVisible():
                self._scroll.hide()
            self._empty_lbl.show()
            return
        for m in msgs:
            self._append_bubble(m)

    def refresh(self):
        """Перечитать историю с сервера (по SSE 'message'/'message_read')."""
        self._load_history()

    def _append_bubble(self, msg: dict):
        if not self._scroll.isVisible():
            self._empty_lbl.hide()
            self._scroll.show()
        bubble = MessageBubble(msg, self._list_w)
        self._bubbles.append(bubble)
        # вставляем перед завершающим stretch
        self._list.insertWidget(self._list.count() - 1, bubble)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_send(self):
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        # Оптимистично показываем своё сообщение сразу, отправку делаем в фоне.
        msg = {
            "body": text, "mine": True, "read": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._append_bubble(msg)
        _history_cache.setdefault(self._uuid, []).append(msg)  # оптимистично в кэш
        to_uuid = self._uuid
        threading.Thread(
            target=lambda: chat_client.send_message(to_uuid, text), daemon=True).start()

    def _load_avatar(self):
        name = self._name

        def _run():
            try:
                import requests
                from config import CACHE_DIR
                path = CACHE_DIR / f"head_{name}.png"
                if not path.exists():
                    r = requests.get(f"https://mc-heads.net/avatar/{name}/64", timeout=6)
                    r.raise_for_status()
                    path.write_bytes(r.content)
                # Сигнал потокобезопасно маршалит в UI-поток (QTimer из фонового
                # потока НЕ срабатывает — у него нет event loop).
                self._avatar_ready.emit(str(path))
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True).start()

    def _set_avatar(self, path: str):
        px = QPixmap(path)
        if not px.isNull():
            self._avatar.setPixmap(px.scaled(
                34, 34, Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def keyPressEvent(self, e):
        # Enter уже обработан returnPressed (отправка). Гасим событие, чтобы QDialog
        # не закрылся (иначе окно диалога закрывается при каждой отправке).
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            e.accept()
            return
        super().keyPressEvent(e)

    def closeEvent(self, e):
        self.closed.emit(self._uuid)
        super().closeEvent(e)
