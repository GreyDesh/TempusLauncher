import logging
from PyQt6.QtCore import Qt, QThread, pyqtSignal

log = logging.getLogger("splash")
from PyQt6.QtGui import QFont, QColor, QPainter, QLinearGradient
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar, QApplication


class LoadWorker(QThread):
    progress = pyqtSignal(str, float)   # message, 0-1
    finished = pyqtSignal(dict, list, object)  # config, news, username
    server_error = pyqtSignal(str)

    def run(self):
        # Весь запуск отказоустойчив: если нет интернета / сервер лёг — не падаем,
        # а открываем лаунчер в ОФФЛАЙН-режиме на кэше (конфиг/новости кэшируются).
        # Любой сетевой сбой в шаге не должен ронять остальные и, главное, поток.
        import api
        import auth_client
        import assets_cache

        steps = 6
        step = 0
        offline = False

        def prog(msg, frac=None):
            nonlocal step
            overall = (step + (frac or 0)) / steps
            self.progress.emit(msg, overall)

        config: dict = {}
        news: list = []
        username = None

        try:
            # 1. Адрес сервера из connect.json
            prog("Определение адреса сервера...", 0)
            log.info("Загрузка connect.json...")
            try:
                api.fetch_connect_json()
            except Exception as e:
                log.warning("connect.json недоступен: %s", e)
                offline = True

            # 2. Конфигурация лаунчера (при сбое api вернёт кэш/фолбэк)
            prog("Загрузка конфигурации...", 0)
            try:
                config = api.fetch_launcher_config(lambda m: self.progress.emit(m, step / steps)) or {}
            except Exception as e:
                log.warning("Конфиг недоступен: %s", e)
                config, offline = {}, True
            step += 1

            # 2. Новости
            prog("Загрузка новостей...", 0)
            try:
                news = api.fetch_news(lambda m: self.progress.emit(m, step / steps)) or []
            except Exception as e:
                log.warning("Новости недоступны: %s", e)
                news, offline = [], True
            step += 1

            # 3. Проверка авторизации + сессия
            prog("Проверка авторизации...", 0)
            try:
                username = auth_client.verify_token()
            except Exception as e:
                log.warning("verify_token не удался: %s", e)
                username, offline = None, True
            step += 1

            # 4. Сессия + роли + плейтайм (если залогинен). Оффлайн — работаем на кэше.
            if not username:
                try:
                    username = auth_client._load_settings().get("username")
                except Exception:
                    username = None
            if username:
                try:
                    prog("Создание сессии...", 0)
                    auth_client.create_session()
                    prog("Загрузка ролей Discord...", 0)
                    auth_client.fetch_discord_roles()
                    prog("Загрузка статистики...", 0.5)
                    import playtime as pt
                    if not pt.fetch_from_server():
                        offline = True
                except Exception as e:
                    log.warning("Сессия/роли/плейтайм недоступны: %s", e)
                    offline = True
            step += 1
        except Exception as e:
            # Страховочная сеть: что бы ни случилось — лаунчер всё равно откроется.
            log.exception("Ошибка загрузки на старте: %s", e)
            offline = True

        # 5. Предзагрузка ресурсов — целиком в try (сбой не должен мешать открытию).
        try:
            self._preload_resources(config, news, step)
        except Exception as e:
            log.warning("Предзагрузка ресурсов частично не удалась: %s", e)
            offline = True

        # Фоновая предзагрузка друзей — тихо, не блокирует запуск
        if username:
            self._prefetch_friends_async(auth_client)

        log.info("Загрузка завершена, пользователь: %s (offline=%s)",
                 username or "не авторизован", offline)
        if offline:
            self.server_error.emit(
                "Не удалось связаться с сервером.\n\n"
                "Возможные причины:\n"
                "• Нет подключения к интернету\n"
                "• Технические работы на сервере\n\n"
                "Лаунчер запущен в офлайн-режиме: доступны сохранённые данные "
                "и уже установленные сборки. Онлайн-функции появятся при "
                "восстановлении связи."
            )
        self.progress.emit("Готово!", 1.0)
        self.finished.emit(config, news, username)

    def _preload_resources(self, config: dict, news: list, step: int):
        steps = 6
        # 5. Сбор URL для предзагрузки
        urls = []
        bg_url = (config.get("_meta") or {}).get("background_url", "")
        if not bg_url:
            from config import LOGIN_BACKGROUND_URL
            bg_url = LOGIN_BACKGROUND_URL
        if bg_url:
            urls.append(bg_url)
        for mode in config.get("modes", []):
            for key in ("logo_url", "banner_url", "background_url", "background_blur_url", "title_png_url"):
                u = mode.get(key, "")
                if u:
                    urls.append(u)
        for item in news:
            if item.get("image_url"):
                urls.append(item["image_url"])
        step += 1

        # 5a. Картинки режимов (media_cache/...) — через media_sync: bundle или точечно
        try:
            import media_sync
            media_sync.sync(on_progress=lambda t, p: self.progress.emit(t, (step + p) / steps))
        except Exception:
            pass

        # 5b. Остальные http-ресурсы (фон логина, маскот, картинки новостей) — параллельно
        http_urls = [u for u in urls if u.startswith("http")]
        total = len(http_urls)
        if total:
            import requests as req
            import hashlib
            from config import CACHE_DIR
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def _download_one(url):
                ext = url.split("?")[0].rsplit(".", 1)[-1]
                if ext not in ("png", "jpg", "jpeg", "webp", "gif"):
                    ext = "png"
                path = CACHE_DIR / f"{hashlib.md5(url.encode()).hexdigest()}.{ext}"
                if not path.exists():
                    try:
                        r = req.get(url, timeout=15)
                        r.raise_for_status()
                        path.write_bytes(r.content)
                    except Exception:
                        pass

            done = 0
            with ThreadPoolExecutor(max_workers=8) as pool:
                for _ in as_completed([pool.submit(_download_one, u) for u in http_urls]):
                    done += 1
                    self.progress.emit(f"Загрузка ресурсов... {done}/{total}",
                                       (step + done / total) / steps)
        step += 1

    def _prefetch_friends_async(self, auth_client):
        """Фоновая предзагрузка друзей — тихо, не блокирует запуск и не роняет его."""
        try:
            import threading

            def _prefetch_friends():
                try:
                    import requests as _req
                    from config import SERVER_URL, SERVER_CERT
                    from ui.friends_panel import set_prefetch_cache
                    import sys
                    verify = str(SERVER_CERT) if SERVER_CERT.exists() else (True if getattr(sys, 'frozen', False) else __import__('certifi').where())
                    data = None
                    for attempt in range(3):
                        r = _req.get(f"{SERVER_URL}/api/friends",
                                     headers=auth_client.session_headers(),
                                     timeout=5, verify=verify)
                        if r.status_code in (401, 422) and attempt < 2:
                            auth_client.create_session()
                            continue
                        r.raise_for_status()
                        data = r.json()
                        break
                    if data is None:
                        raise RuntimeError("friends prefetch failed")
                    set_prefetch_cache(data)
                    # Индикатор уведомлений сразу после запуска (жёлтая точка —
                    # есть входящие заявки), не дожидаясь открытия панели друзей.
                    try:
                        import notifications
                        notifications.center().set_requests(bool(data.get("incoming")))
                    except Exception:
                        pass
                except Exception:
                    pass
            threading.Thread(target=_prefetch_friends, daemon=True).start()
        except Exception:
            pass


class SplashScreen(QWidget):
    load_done = pyqtSignal(dict, list, object)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(600, 360)
        self._center()
        self._build_ui()
        self._worker = LoadWorker()
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_done)
        self._worker.server_error.connect(self._on_server_error)
        self._worker.start()

    def _center(self):
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2,
        )

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 30)
        layout.setSpacing(16)

        from config import LAUNCHER_NAME
        from ui.assets import launcher_logo
        logo_lbl = QLabel()
        logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_lbl.setStyleSheet("background: transparent;")
        logo_lbl.setPixmap(launcher_logo().scaled(
            80, 80, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(logo_lbl)

        self._title = QLabel(LAUNCHER_NAME)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont("Segoe UI", 56, QFont.Weight.Bold)
        self._title.setFont(font)
        self._title.setStyleSheet("color: #ffffff;")

        self._status = QLabel("Инициализация...")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet("color: #8888aa; font-size: 13px;")

        self._bar = QProgressBar()
        self._bar.setRange(0, 1000)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)
        self._bar.setStyleSheet("""
            QProgressBar { background: rgba(255,255,255,15); border-radius: 3px; border: none; }
            QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #5B8CFF,stop:1 #8B5CFF); border-radius: 3px; }
        """)

        layout.addStretch()
        layout.addWidget(self._title)
        layout.addWidget(self._status)
        layout.addSpacing(10)
        layout.addWidget(self._bar)
        layout.addStretch()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0, QColor(18, 18, 35, 240))
        grad.setColorAt(1, QColor(10, 10, 22, 240))
        painter.setBrush(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 18, 18)

    def _on_progress(self, message: str, frac: float):
        self._status.setText(message)
        self._bar.setValue(int(frac * 1000))

    def _on_server_error(self, message: str):
        from PyQt6.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        msg.setWindowTitle("Проблема с подключением")
        msg.setText(message)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.exec()

    def _on_done(self, config: dict, news: list, username):
        from config import LAUNCHER_NAME
        self._title.setText(LAUNCHER_NAME)
        self.load_done.emit(config, news, username)
        self.close()
