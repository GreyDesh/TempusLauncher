import sys
import os
import logging
import traceback
from pathlib import Path

# Убедимся что рабочая директория — папка лаунчера
os.chdir(os.path.dirname(os.path.abspath(__file__)))

_SSL_STATUS = ""
try:
    import truststore
    truststore.inject_into_ssl()
    _SSL_STATUS = "truststore OK — Windows cert store active"
except ImportError as _e:
    _SSL_STATUS = f"truststore not found: {_e}"
    try:
        import certifi as _certifi
        os.environ.setdefault('SSL_CERT_FILE',      _certifi.where())
        os.environ.setdefault('REQUESTS_CA_BUNDLE', _certifi.where())
        _SSL_STATUS += f" | certifi fallback: {_certifi.where()}"
    except Exception as _e2:
        _SSL_STATUS += f" | certifi also failed: {_e2}"
except Exception as _e:
    _SSL_STATUS = f"truststore inject failed: {_e}"

# Разрешаем самоподписанный сертификат в QtWebEngine (до инициализации Qt)
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--ignore-certificate-errors"

# Логирование (LOGS)
def _setup_logging():
    from config import DATA_DIR
    log_path = DATA_DIR / "launcher.log"
    # Очищаем лог при каждом запуске
    log_path.write_text("", encoding="utf-8")

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

_setup_logging()
log = logging.getLogger("main")
log.info("=== TempusLauncher запущен ===")
log.info("[ssl] %s", _SSL_STATUS)


def _excepthook(exc_type, exc_value, exc_tb):
    log.critical("Необработанное исключение", exc_info=(exc_type, exc_value, exc_tb))
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = _excepthook


# Обновление обрабатывает bootstrap (TempusLauncher.exe) — app.exe не дублирует проверку
# OLD


from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from ui.styles import DARK_GLASS_QSS


_MUTEX_NAME = "TempusLauncher_AppMutex"

def _create_mutex():
    try:
        import ctypes
        h = ctypes.windll.kernel32.CreateMutexW(None, True, _MUTEX_NAME)
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            return False
        return True
    except Exception:
        return True  # не Windows или ошибка — разрешаем запуск

def main():
    # Отключаем WAM (Windows Account Manager) в Chromium/WebEngine —
    # иначе Windows перехватывает Microsoft логин и предлагает USB ключ / Windows Hello
    # Grand FIX
    os.environ.setdefault(
        "QTWEBENGINE_CHROMIUM_FLAGS",
        "--disable-features=msSingleSignOn,WinSSOEnabled,WebAuthentication,WebAuthenticationRemoteDesktopSupport"
    )

    if not _create_mutex():
        # Уже запущен — выходим молча
        sys.exit(0)

    # Устанавливаем AppUserModelID — без этого Windows показывает стандартную иконку в taskbar
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TempusLauncher.App")
    except Exception:
        pass

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("TempusLauncher")
    app.setStyleSheet(DARK_GLASS_QSS)

    # Иконка приложения (панель задач + Alt+Tab) (ICO)
    from PyQt6.QtGui import QIcon
    from PyQt6.QtCore import QByteArray
    import asset_pack
    icon_data = asset_pack.read("assets/launcher_logo.png")
    if icon_data:
        px_icon = __import__("PyQt6.QtGui", fromlist=["QPixmap"]).QPixmap()
        px_icon.loadFromData(icon_data)
        app.setWindowIcon(QIcon(px_icon))

    # Диалог первого запуска (SmartScreen инструкция)
    from ui.first_run_dialog import show_if_first_run
    show_if_first_run()

    # Splash — загрузка всего нужного
    from ui.splash import SplashScreen
    splash = SplashScreen()

    def on_loaded(config: dict, news: list, username):
        if username:
            # Сессия действительна — сразу главное окно
            _open_main(app, config, news, username)
        else:
            # Нужен логин
            _open_login(app, config, news)

    splash.load_done.connect(on_loaded)
    splash.show()
    sys.exit(app.exec())


def _open_login(app: QApplication, config: dict, news: list):
    from ui.login_window import LoginWindow
    win = LoginWindow(config)

    def on_login(username: str):
        win.close()
        _open_main(app, config, news, username)

    win.login_success.connect(on_login)
    win.show()
    app._login_win = win  # Удерживаем ссылку
    # Я узнал что ссылка Microsoft дается на некоторое врямя и сбрасывается, нужно перехватить!


def _open_main(app: QApplication, config: dict, news: list, username: str):
    from ui.main_window import MainWindow
    from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
    from PyQt6.QtGui import QIcon, QPixmap
    from PyQt6.QtCore import QByteArray
    import asset_pack

    win = MainWindow(config, news, username)

    # Трей иконка
    icon_data = asset_pack.read("assets/launcher_logo.png")
    tray_icon = QSystemTrayIcon(app)
    if icon_data:
        px = QPixmap()
        px.loadFromData(icon_data)
        tray_icon.setIcon(QIcon(px))
    tray_icon.setToolTip("TempusLauncher")

    # Точка-индикатор уведомлений на иконке трея (жёлтая=заявка, красная=сообщение)
    import notifications
    _tray_base = px if icon_data else None
    def _update_tray_dot(color: str):
        if _tray_base is not None:
            tray_icon.setIcon(QIcon(notifications.compose_dot(_tray_base, color)))
    notifications.center().indicator_changed.connect(_update_tray_dot)
    _update_tray_dot(notifications.center().current_indicator())

    tray_menu = QMenu()
    tray_menu.setStyleSheet("""
        QMenu {
            background-color: #0d0d14;
            border: 1px solid rgba(91, 140, 255, 60);
            border-radius: 10px;
            padding: 6px 4px;
            font-family: 'Segoe UI';
            font-size: 13px;
            color: #e8e8f0;
        }
        QMenu::item {
            padding: 8px 20px 8px 14px;
            border-radius: 6px;
            margin: 1px 4px;
        }
        QMenu::item:selected {
            background: rgba(91, 140, 255, 30);
            color: #ffffff;
        }
        QMenu::item#quit:selected {
            background: rgba(255, 92, 92, 25);
            color: #ff5c5c;
        }
        QMenu::separator {
            height: 1px;
            background: rgba(255, 255, 255, 12);
            margin: 4px 10px;
        }
    """)

    act_open = tray_menu.addAction("  Открыть лаунчер")
    act_open.setObjectName("open")

    # Установленные режимы
    from downloader import _load_installed
    installed = _load_installed()
    modes = config.get("modes", [])
    # Только видимые режимы: закрытый (visible:false) не должен быстро запускаться из трея,
    # даже если установлен. hidden-режимы уже отфильтрованы сервером (нет в config без роли).
    installed_modes = [m for m in modes
                       if m.get("id") in installed and m.get("visible", True) is not False]
    if installed_modes:
        from assets_cache import AssetCache
        tray_menu.addSeparator()
        for mode in installed_modes:
            act_mode = tray_menu.addAction(f" {mode.get('name', mode['id'])}")
            def _launch(checked=False, m=mode):
                win._on_play(m)
            act_mode.triggered.connect(_launch)
            logo_url = mode.get("logo_url", "")
            if logo_url:
                def _set_icon(url, px, act=act_mode):
                    scaled = px.scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
                    act.setIcon(QIcon(scaled))
                AssetCache.load(logo_url, _set_icon)

    tray_menu.addSeparator()
    act_quit = tray_menu.addAction("  Выйти из лаунчера")
    act_quit.setObjectName("quit")


    def _show():
        win.showNormal()
        win.activateWindow()
        win.raise_()

    act_open.triggered.connect(_show)
    def _quit():
        win._watcher.stop()
        tray_icon.hide()
        app.quit()

    act_quit.triggered.connect(_quit)
    tray_icon.activated.connect(
        lambda reason: _show() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None
    )
    tray_icon.setContextMenu(tray_menu)
    tray_icon.show()

    app.setQuitOnLastWindowClosed(False)
    win._tray_icon = tray_icon  # удерживаем ссылку
    win.show()
    app._main_win = win

    import threading
    import auth_client
    def _load_roles():
        auth_client.fetch_discord_roles()
        win._roles_loaded_signal.emit()
    threading.Thread(target=_load_roles, daemon=True).start()

    # Слушатель показа окна: когда юзер жмёт ярлык у свёрнутой в трей программы,
    # updater сигналит именованным событием, а окно показывает себя САМО (через
    # свой Qt-поток) — внешний ShowWindow из чужого процесса вешает Qt-окно.
    _start_show_listener(win)


def _start_show_listener(win):
    import threading, ctypes
    from PyQt6.QtCore import QObject, pyqtSignal

    class _Bridge(QObject):
        show_sig = pyqtSignal()

    k32 = ctypes.windll.kernel32
    ev = k32.CreateEventW(None, False, False, "TempusLauncher_ShowEvent")
    if not ev:
        return
    bridge = _Bridge()

    def _bring():
        win.showNormal()
        win.raise_()
        win.activateWindow()

    bridge.show_sig.connect(_bring)   # выполнится в Qt-потоке (queued)
    win._show_bridge = bridge         # держим ссылку

    def _loop():
        while True:
            if k32.WaitForSingleObject(ev, 0xFFFFFFFF) == 0:  # INFINITE, signaled
                bridge.show_sig.emit()

    threading.Thread(target=_loop, daemon=True).start()


if __name__ == "__main__":
    main()
