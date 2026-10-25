import sys
from pathlib import Path

# Настройки лаунчера (вшиты в код)
LAUNCHER_NAME = "TempusLauncher"
LOGIN_BACKGROUND_URL     = "timeout/background.png"
MASKOT_LOGIN_PATH        = "timeout/maskot_login.png"   # относительно корня проекта

# URL connect.json на GitHub — источник адреса сервера
CONNECT_JSON_URL = "https://raw.githubusercontent.com/GreyDesh/grand_server_wiki/main/connect.json"

# Лаунчерный API-сервер (заполняется из connect.json при запуске)
SERVER_URL = "https://176.107.240.3:9000"
SERVER_IP  = "176.107.240.3"

# Сайт/банк (заполняется из connect.json при запуске; по умолчанию = SERVER_URL)
SITE_URL = "https://176.107.240.3:9000"

# Из connect.json (GitHub) — заполняются в fetch_connect_json
SOCIAL         = {}   # {"telegram": ..., "discord": ...}
# Маскот и фон логина теперь ЛОКАЛЬНЫЕ (в assets/), а не из connect.json.
MASKOT_URL     = "assets/maskot_login.png"        # маскот на экране логина
BACKGROUND_URL = "assets/background_launcher.jpg" # фон экрана логина/главной

# Версии Java и ссылки на JRE — ВШИТЫ в лаунчер (раньше были в meta.json)
JAVA = {
    "java8":  "https://github.com/adoptium/temurin8-binaries/releases/download/jdk8u412-b08/OpenJDK8U-jre_x64_windows_hotspot_8u412b08.zip",
    "java11": "https://github.com/adoptium/temurin11-binaries/releases/download/jdk-11.0.23%2B9/OpenJDK11U-jre_x64_windows_hotspot_11.0.23_9.zip",
    "java17": "https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.11%2B9/OpenJDK17U-jre_x64_windows_hotspot_17.0.11_9.zip",
    "java21": "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.3%2B9/OpenJDK21U-jre_x64_windows_hotspot_21.0.3_9.zip",
    "java25": "https://download.java.net/java/GA/jdk25.0.2/b1e0dfa218384cb9959bdcb897162d4e/10/GPL/openjdk-25.0.2_windows-x64_bin.zip",
}

# Отключить авторизацию для локального тестирования (True = сервер не нужен)
DEV_BYPASS_AUTH = False
DEV_USERNAME    = "Dev"

# Конфиг лаунчера берётся с сервера (заполняется после fetch_connect_json)
LAUNCHER_JSON_URL = ""  # будет: {SERVER_URL}/api/launcher/config
NEWS_JSON_URL     = "https://raw.githubusercontent.com/YOUR_USER/YOUR_REPO/main/news.json"

# Интервал проверки обновлений JSON (мс)
JSON_POLL_INTERVAL_MS = 5 * 60 * 1000  # 5 минут

# Пути
BASE_DIR  = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent

# Путь к самоподписанному сертификату сервера (для verify= в requests)
SERVER_CERT = BASE_DIR / "assets" / "server.crt"

# False = не проверять CA (self-signed сертификат).
# Трафик всё равно шифруется. Включить True когда будет нормальный сертификат.
SSL_VERIFY = False
DATA_DIR  = Path.home() / "AppData" / "Roaming" / ".grandlauncher"

# Кэш храним рядом с программой (в папке установки), чтобы он удалялся при
# деинсталляции лаунчера. Определяем embeddable-базу по маркерам рядом с pythonw.exe;
# в dev (запуск из исходников системным Python) — старое место в LocalAppData.
_INSTALL_ROOT = Path(sys.executable).parent
if (_INSTALL_ROOT / "python311.zip").exists() and (_INSTALL_ROOT / "pythonw.exe").exists():
    CACHE_DIR = _INSTALL_ROOT / "cache"
else:
    CACHE_DIR = Path.home() / "AppData" / "Local" / ".grandlauncher" / "cache"
MEDIA_CACHE_DIR = CACHE_DIR / "media"      # картинки режимов (media_cache/<имя>)
MINECRAFT_DIR = DATA_DIR / "minecraft"
SHARED_MC_DIR = MINECRAFT_DIR / "_shared"  # общие libraries/assets/versions
JAVA_DIR  = DATA_DIR / "java"

SETTINGS_FILE  = DATA_DIR / "settings.json"
INSTALLED_FILE = DATA_DIR / "installed.json"

# Minecraft RAM по умолчанию (МБ)
DEFAULT_RAM_MB = 2048

# Размеры окна
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 720
SIDEBAR_WIDTH = 230

# Цвета
COLOR_BG = "#0d0d14"
COLOR_PANEL = "rgba(18, 18, 30, 210)"
COLOR_GLASS = "rgba(255, 255, 255, 12)"
COLOR_ACCENT = "#5B8CFF"
COLOR_ACCENT_HOVER = "#7aa3ff"
COLOR_TEXT = "#e8e8f0"
COLOR_TEXT_DIM = "#8888aa"
COLOR_SUCCESS = "#4caf7d"
COLOR_DANGER = "#ff5c5c"

# Анимации (мс)
ANIM_FAST = 200
ANIM_NORMAL = 350
ANIM_SLOW = 500

for d in (DATA_DIR, CACHE_DIR, MEDIA_CACHE_DIR, MINECRAFT_DIR, SHARED_MC_DIR, JAVA_DIR):
    d.mkdir(parents=True, exist_ok=True)
