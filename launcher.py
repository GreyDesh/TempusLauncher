import ctypes
import json
import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("launcher")

import minecraft_launcher_lib as mll

from config import MINECRAFT_DIR, SHARED_MC_DIR, SETTINGS_FILE
from downloader import _load_installed


def _total_ram_mb() -> int:
    """Returns total physical RAM in MB (Windows only, fallback 4096)."""
    try:
        class _MEMSTATUS(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        s = _MEMSTATUS()
        s.dwLength = ctypes.sizeof(_MEMSTATUS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
        return int(s.ullTotalPhys // (1024 * 1024))
    except Exception:
        return 4096

# Спасибо лично HP Notepad - Intel Core 2 Duo 2GB без GPU, за мой опыт страдания, Аминь!
def auto_ram_mb() -> int:
    """50% of total RAM, but leaves 2 GB for the OS. Clamped to [1024, 8192] MB."""
    total = _total_ram_mb()
    half = total // 2
    safe = total - 2048          # оставьте 2 ГБ для ОС
    value = min(half, safe)
    return max(1024, min(value, 8192))


def _load_settings() -> dict:
    import auth_client
    return auth_client._load_settings()


def _java_version(java_exe: str) -> int:
    """Возвращает major-версию Java (8, 11, 17, 21...). 0 если не удалось определить."""
    try:
        import subprocess as _sp
        out = _sp.check_output([java_exe, "-version"], stderr=_sp.STDOUT, text=True, timeout=5)
        import re
        m = re.search(r'"(\d+)(?:\.(\d+))?', out)
        if m:
            major = int(m.group(1))
            return 8 if major == 1 else major
    except Exception:
        pass
    return 0


def _find_java_modern() -> str | None:
    """Ищет Java 17+ в стандартных путях Windows."""
    import glob as _glob
    candidates = []
    for root in [
        r"C:\Program Files\Java",
        r"C:\Program Files\Eclipse Adoptium",
        r"C:\Program Files\Microsoft",
        r"C:\Program Files\Zulu",
        r"C:\Program Files\BellSoft",
    ]:
        for exe in _glob.glob(f"{root}\\*/bin\\java.exe"):
            candidates.append(exe)
    # Предпочитаем 17, затем 21, затем любую >= 17
    # JAVA
    for preferred in (17, 21):
        for exe in candidates:
            if _java_version(exe) == preferred:
                return exe
    for exe in candidates:
        if _java_version(exe) >= 17:
            return exe
    return None


def _find_java(info: dict, require_java8: bool = False) -> str:
    # 1. Ручной путь из настроек
    settings = _load_settings()
    custom = settings.get("java_path")
    if custom and Path(custom).exists():
        return custom
    # 2. Портативная Java скачанная при установке режима
    saved = info.get("java")
    if saved and Path(saved).exists():
        ver = _java_version(saved)
        if require_java8:
            if ver == 8:
                return saved
        else:
            if ver >= 9:
                return saved
    # 3. Системная Java
    java_sys = shutil.which("java")
    if java_sys:
        ver = _java_version(java_sys)
        if require_java8 and ver == 8:
            return java_sys
        if not require_java8 and ver >= 9:
            return java_sys
    # 4. Поиск Java 17+ по стандартным путям (только если не нужна java8)
    if not require_java8:
        modern = _find_java_modern()
        if modern:
            return modern
    return java_sys if java_sys else "java"


def _find_installed_version_id(mc_dir: Path, mc_version: str, loader_type: str,
                               loader_version: str = "") -> str | None:
    """Находит id установленной версии в папке versions (например '1.7.10-Forge...')."""
    versions_dir = mc_dir / "versions"
    if not versions_dir.exists():
        return None

    loader_type = loader_type.lower()

    # Для ванильного — точное совпадение
    if loader_type == "vanilla":
        if (versions_dir / mc_version).exists():
            return mc_version
        return None

    # custom: точное имя папки профиля (modpack.version_id), передано в loader_version
    if loader_type == "custom":
        if loader_version and (versions_dir / loader_version).is_dir():
            return loader_version
        return None

    # NeoForge: папки называются 'neoforge-<версия>' БЕЗ версии MC в имени
    if loader_type == "neoforge":
        if loader_version:
            exact = versions_dir / f"neoforge-{loader_version}"
            if exact.is_dir():
                return exact.name
        cands = [d.name for d in versions_dir.iterdir()
                 if d.is_dir() and "neoforge" in d.name.lower()]
        return sorted(cands)[-1] if cands else None

    # Для остальных модлоадеров ищем папку содержащую версию MC и имя лоадера
    keywords = {
        "forge": "forge",
        "neoforge": "neoforge",
        "fabric": "fabric-loader",
        "quilt": "quilt-loader",
    }
    keyword = keywords.get(loader_type, loader_type)

    candidates = []
    for d in versions_dir.iterdir():
        if d.is_dir() and mc_version in d.name and keyword in d.name.lower():
            candidates.append(d.name)

    if not candidates:
        return None
    # Берём последнюю по имени
    return sorted(candidates)[-1]


def launch_mode(mode: dict, username: str) -> subprocess.Popen:
    mode_id = mode["id"]
    installed = _load_installed()
    info = installed.get(mode_id)
    if not info:
        raise RuntimeError("Сборка не установлена")

    # Обновляем Minecraft-токен прямо перед запуском: игра должна получить
    # свежий токен (~24ч), иначе лицензионные серверы считают сессию пираткой.
    import auth_client
    auth_client.refresh_for_launch()

    settings = _load_settings()
    if settings.get("ram_auto", True):
        ram_mb = auto_ram_mb()
    else:
        ram_mb = settings.get("ram_mb", 2048)

    # Техническая версия MC — из modpack (верхний minecraft_version только для показа).
    mc_version = mode.get("modpack", {}).get("minecraft_version") or mode.get("minecraft_version", "1.20.1")
    loader_type = mode.get("modpack", {}).get("type", "vanilla").lower()
    mode_dir = Path(info["path"])

    java_key = mode.get("modpack", {}).get("java") or mode.get("java", "")
    require_java8 = java_key == "java8"
    java = _find_java(info, require_java8=require_java8)

    # Определяем id версии для minecraft-launcher-lib (ищем в общей папке SHARED_MC_DIR)
    # custom: имя папки профиля берём из modpack.version_id
    loader_version = mode.get("modpack", {}).get("forge_version", "") or mode.get("modpack", {}).get("version_id", "")
    version_id = _find_installed_version_id(SHARED_MC_DIR, mc_version, loader_type, loader_version)
    log.debug("launch: mc_version=%s loader=%s version_id=%s shared_dir=%s", mc_version, loader_type, version_id, SHARED_MC_DIR)
    versions_dir = SHARED_MC_DIR / "versions"
    if versions_dir.exists():
        log.debug("launch: versions= %s", [d.name for d in versions_dir.iterdir() if d.is_dir()])
    if not version_id:
        raise RuntimeError(
            f"Версия Minecraft не найдена в {SHARED_MC_DIR / 'versions'}.\n"
            "Попробуйте переустановить сборку."
        )

    raw_uuid     = settings.get("uuid", "00000000000000000000000000000000")
    s = raw_uuid.replace("-", "")
    player_uuid  = f"{s[:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:]}" if len(s) == 32 else raw_uuid
    mc_token     = settings.get("token") or "0"
    options: mll.types.MinecraftOptions = {
        "username": username,
        "uuid":     player_uuid,
        "token":    mc_token,
        "jvmArguments": [
            f"-Xmx{ram_mb}M",
            f"-Xms{min(512, ram_mb)}M",
            "-XX:+UseG1GC",
            "-XX:+UnlockExperimentalVMOptions",
            "-XX:G1NewSizePercent=20",
            "-XX:G1ReservePercent=20",
            "-XX:MaxGCPauseMillis=50",
            "-XX:G1HeapRegionSize=32m",
            "-Dfml.ignoreInvalidMinecraftCertificates=true",
            "-Dfml.ignorePatchDiscrepancies=true",
        ] + list(mode.get("modpack", {}).get("jvm_args", [])),
        "executablePath": java,
        "gameDirectory": str(mode_dir),
        "launcherName": "TempusLauncher",
        "launcherVersion": "1.0",
    }

    try:
        import mod_guard
        for action in mod_guard.check_and_enforce(mode, mode_dir):
            print(action)
    except Exception as e:
        print(f"[mod_guard] {e}")

    cmd = mll.command.get_minecraft_command(version_id, str(SHARED_MC_DIR), options)

    join_server = mode.get("_join_server")
    join_port   = mode.get("_join_port", "25565")
    if join_server:
        cmd += ["--server", join_server, "--port", str(join_port)]

    proc = subprocess.Popen(
        cmd,
        cwd=str(mode_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return proc
