import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Callable

import requests

from config import MINECRAFT_DIR, SHARED_MC_DIR, JAVA_DIR, INSTALLED_FILE, CACHE_DIR

ProgressCallback = Callable[[str, float], None]


# installed.json helpers

def _load_installed() -> dict:
    if INSTALLED_FILE.exists():
        try:
            return json.loads(INSTALLED_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_installed(data: dict):
    INSTALLED_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _sanitize_path(name: str) -> str:
    """Убирает управляющие символы из имени файла/пути из zip."""
    return "".join(c for c in name if c >= " " or c in ("\t",))


_PRESERVE_FILES = {
    "options.txt",
    "servers.dat",
    "hotbar.nbt",
    "realms_persistence.json",
}


def _safe_extractall(zip_path: Path, dest: Path, is_update: bool = False):
    """extractall с защитой от path traversal и недопустимых символов в именах.
    При is_update=True не перезаписывает пользовательские файлы."""
    dest_resolved = dest.resolve()
    with zipfile.ZipFile(zip_path, "r") as z:
        for member in z.infolist():
            clean_name = _sanitize_path(member.filename)
            if not clean_name or clean_name != member.filename:
                if not clean_name:
                    continue
                target = (dest / clean_name).resolve()
                if not target.is_relative_to(dest_resolved):
                    continue
                if is_update and target.name in _PRESERVE_FILES and target.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                if not member.is_dir():
                    with z.open(member) as src, open(target, "wb") as dst:
                        dst.write(src.read())
                continue
            target = (dest / member.filename).resolve()
            if not target.is_relative_to(dest_resolved):
                continue
            if is_update and target.name in _PRESERVE_FILES and target.exists():
                continue
            z.extract(member, dest)


def _save_mods_manifest(mode_id: str, mode_dir: Path):
    mods_dir = mode_dir / "mods"
    files = sorted(f.name for f in mods_dir.iterdir() if f.is_file()) if mods_dir.exists() else []
    _save_managed_manifest(mode_id, files)


# .mrpack (Modrinth modpack)
# Формат: zip с modrinth.index.json (моды по ссылкам на CDN + sha1) и папкой
# overrides/ (config, options.txt и ПРИВАТНЫЕ моды в overrides/mods/).

def _mods_manifest_path(mode_id: str) -> Path:
    return CACHE_DIR / mode_id / "mods_manifest.json"


def _save_managed_manifest(mode_id: str, names: list[str]):
    """Сохраняет список НАШИХ (managed) модов — для чистки при обновлении и mod_guard."""
    p = _mods_manifest_path(mode_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sorted(set(names))), encoding="utf-8")


def _load_managed_manifest(mode_id: str) -> list[str]:
    try:
        return json.loads(_mods_manifest_path(mode_id).read_text(encoding="utf-8"))
    except Exception:
        return []


# Доп. файлы сборки из .mrpack (не моды): ресурспаки, шейдеры. Хранятся как
# ОТНОСИТЕЛЬНЫЕ пути ("resourcepacks/X.zip") в отдельном манифесте — чтобы при
# обновлении чистить орфаны в их папках, не трогая mods_manifest/mod_guard.
_EXTRA_PREFIXES = ("resourcepacks/", "shaderpacks/")


def _extra_manifest_path(mode_id: str) -> Path:
    return CACHE_DIR / mode_id / "extra_manifest.json"


def _save_managed_extra(mode_id: str, rels: list[str]):
    p = _extra_manifest_path(mode_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sorted(set(rels))), encoding="utf-8")


def _load_managed_extra(mode_id: str) -> list[str]:
    try:
        return json.loads(_extra_manifest_path(mode_id).read_text(encoding="utf-8"))
    except Exception:
        return []


def _overrides_extra_paths(zip_path: Path) -> list[str]:
    """Ресурспаки/шейдеры внутри overrides/ (приватные, не с Modrinth) — отн. пути."""
    out = []
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            if n.endswith("/"):
                continue
            rel = n[len("overrides/"):] if n.startswith("overrides/") else ""
            if rel.startswith(_EXTRA_PREFIXES):
                out.append(rel)
    return out


def _sha1_file(p: Path) -> str:
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _archive_is_mrpack(zip_path: Path) -> bool:
    try:
        with zipfile.ZipFile(zip_path) as z:
            return "modrinth.index.json" in z.namelist()
    except Exception:
        return False


def _overrides_mod_names(zip_path: Path) -> list[str]:
    """Имена jar-модов внутри overrides/mods/ (приватные, не с Modrinth)."""
    out = []
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            if n.startswith("overrides/mods/") and n.lower().endswith(".jar") and not n.endswith("/"):
                out.append(Path(n).name)
    return out


def _download_one_mod(f: dict, mode_dir: Path, attempts: int = 3) -> bool:
    """Качает один мод из индекса. True — файл на месте и хеш совпал, False — не удалось."""
    target = mode_dir / f["path"]                      # mods/X.jar
    sha1 = (f.get("hashes") or {}).get("sha1", "")
    if target.exists() and (not sha1 or _sha1_file(target) == sha1):
        return True                                    # уже есть и совпадает
    for url in f.get("downloads", []):
        for _ in range(attempts):
            try:
                resp = requests.get(url, timeout=120)
                if resp.status_code != 200:
                    continue                           # 403/500/… — повтор той же ссылки
                data = resp.content
                if sha1 and hashlib.sha1(data).hexdigest() != sha1:
                    break                              # контент битый — на следующее зеркало
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                return True
            except Exception:
                continue                               # сетевой сбой — повтор
    return False


def _download_index_mods(files: list, mode_dir: Path, on_progress: ProgressCallback):
    """Качает моды из modrinth.index.json с CDN (параллельно, проверка sha1).
    Проверяет, что скачалось ВСЁ; упавшее докачивает; если не вышло — бросает ошибку."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    (mode_dir / "mods").mkdir(parents=True, exist_ok=True)

    total = len(files)
    done = 0
    failed: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(_download_one_mod, f, mode_dir): f for f in files}
        for fut in as_completed(futs):
            done += 1
            if not fut.result():
                failed.append(futs[fut])
            on_progress(f"Скачивание модов {done}/{total}...", done / max(total, 1))

    # Докачиваем упавшие последовательно (без нагрузки на CDN)
    still: list[dict] = []
    for f in failed:
        on_progress(f"Докачка {Path(f['path']).name}...", done / max(total, 1))
        if not _download_one_mod(f, mode_dir, attempts=5):
            still.append(f)

    if still:
        names = ", ".join(Path(f["path"]).name for f in still)
        raise RuntimeError(
            f"Не удалось скачать моды ({len(still)}): {names}. "
            "Проверьте интернет и переустановите/обновите сборку."
        )


def _extract_overrides(zip_path: Path, mode_dir: Path, is_update: bool):
    """Распаковывает overrides/* в папку режима (config, options.txt, приватные mods)."""
    dest_resolved = mode_dir.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for m in z.infolist():
            n = m.filename
            if not n.startswith("overrides/") or m.is_dir():
                continue
            rel = _sanitize_path(n[len("overrides/"):])
            if not rel:
                continue
            target = (mode_dir / rel).resolve()
            if not target.is_relative_to(dest_resolved):
                continue                                # защита от traversal
            if is_update and target.name in _PRESERVE_FILES and target.exists():
                continue                                # не затираем пользовательские
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(m) as src, open(target, "wb") as dst:
                dst.write(src.read())


def _install_mrpack(mode_id: str, zip_path: Path, mode_dir: Path,
                    on_progress: ProgressCallback, is_update: bool):
    mods_dir = mode_dir / "mods"
    with zipfile.ZipFile(zip_path) as z:
        index = json.loads(z.read("modrinth.index.json"))
    all_files = index.get("files", [])

    def _client_ok(f) -> bool:
        # пропускаем server-only файлы (env.client == "unsupported")
        return (f.get("env") or {}).get("client", "required") != "unsupported"

    mod_files = [f for f in all_files
                 if _client_ok(f) and str(f.get("path", "")).startswith("mods/")]
    # Доп. клиентские файлы сборки: ресурспаки, шейдеры (качаются с Modrinth CDN
    # так же, как моды, но лежат в resourcepacks/ shaderpacks/ — раньше терялись).
    extra_files = [f for f in all_files
                   if _client_ok(f) and str(f.get("path", "")).startswith(_EXTRA_PREFIXES)]

    # 1. Скачиваем/сверяем по хешу (моды + доп.файлы), каждый по своему path.
    #    Бросит ошибку, если что-то не скачалось (дыры больше не проходят молча).
    _download_index_mods(mod_files + extra_files, mode_dir, on_progress)
    # 2. overrides/ (config, options.txt, приватные моды/ресурспаки)
    on_progress("Распаковка конфигов...", 0.9)
    _extract_overrides(zip_path, mode_dir, is_update)

    # 3. managed моды (по имени — для mod_guard и чистки в mods/)
    managed = [Path(f["path"]).name for f in mod_files] + _overrides_mod_names(zip_path)
    # 3b. managed доп.файлы (по отн. пути — ресурспаки/шейдеры из индекса и overrides)
    extra_managed = [f["path"] for f in extra_files] + _overrides_extra_paths(zip_path)

    # 4. Орфаны модов (mods/, по имени) — снятые/старые моды, которых больше нет.
    if is_update and mods_dir.exists():
        managed_set = set(managed)
        for name in set(_load_managed_manifest(mode_id)) - managed_set:
            p = mods_dir / name
            if p.is_file():
                p.unlink()
    # 4b. Орфаны доп.файлов (по отн. пути) — снятые ресурспаки/шейдеры.
    if is_update:
        mode_resolved = mode_dir.resolve()
        for rel in set(_load_managed_extra(mode_id)) - set(extra_managed):
            p = (mode_dir / rel)
            try:
                if p.is_file() and p.resolve().is_relative_to(mode_resolved):
                    p.unlink()
            except Exception:
                pass

    _save_managed_manifest(mode_id, managed)
    _save_managed_extra(mode_id, extra_managed)


def get_installed_version(mode_id: str) -> str | None:
    return _load_installed().get(mode_id, {}).get("version")


def needs_update(mode: dict) -> bool:
    installed = get_installed_version(mode["id"])
    return installed != mode.get("modpack", {}).get("version")


def is_installed(mode: dict) -> bool:
    return get_installed_version(mode["id"]) is not None


# Download helpers

def _download_file(url: str, dest: Path, on_progress: ProgressCallback, label: str, retries: int = 3):
    import time
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, stream=True, timeout=60)
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            done = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        done += len(chunk)
                        if total and on_progress:
                            on_progress(label, done / total)
            if on_progress:
                on_progress(label, 1.0)
            return
        except Exception as e:
            dest.unlink(missing_ok=True)
            if attempt == retries:
                raise
            if on_progress:
                on_progress(f"{label} (повтор {attempt}/{retries - attempt + 1})...", 0.0)
            time.sleep(2 * attempt)


# minecraft-launcher-lib progress callback

def _make_mll_callbacks(on_progress: ProgressCallback):
    """Конвертирует прогресс minecraft-launcher-lib в наш ProgressCallback."""
    state = {"max": 1, "current": 0, "status": ""}

    def set_status(s: str):
        state["status"] = s
        on_progress(s, state["current"] / max(state["max"], 1))

    def set_progress(v: int):
        state["current"] = v
        on_progress(state["status"], v / max(state["max"], 1))

    def set_max(v: int):
        state["max"] = max(v, 1)

    return {"setStatus": set_status, "setProgress": set_progress, "setMax": set_max}


# Java

def _ensure_java(java_url: str | None, java_key: str, on_progress: ProgressCallback) -> Path | None:
    """Скачивает портативную Java. Кэширует в data/java/{java_key}/ — общий для всех режимов."""
    # Сначала проверяем уже скачанную портативную Java
    java_dir = JAVA_DIR / java_key
    for p in java_dir.rglob("java.exe"):
        return p

    # Проверяем системную Java на соответствие версии
    java_sys = shutil.which("java")
    if java_sys:
        try:
            import subprocess as _sp2, re as _re2
            out = _sp2.check_output([java_sys, "-version"], stderr=_sp2.STDOUT, text=True, timeout=5)
            m = _re2.search(r'version "(\d+)(?:\.(\d+))?', out)
            if m:
                major = int(m.group(1))
                if major == 1:
                    major = int(m.group(2) or 0)
                need = 8 if java_key == "java8" else (17 if java_key in ("java17", "java21", "java25") else 11)
                if java_key == "java8" and major == 8:
                    return Path(java_sys)
                if java_key != "java8" and major >= need:
                    return Path(java_sys)
        except Exception:
            pass

    if not java_url:
        return Path(java_sys) if java_sys else None

    java_zip = java_dir / "java.zip"
    java_dir.mkdir(parents=True, exist_ok=True)

    on_progress("Скачивание Java...", 0.0)
    _download_file(java_url, java_zip, on_progress, "Скачивание Java...")
    on_progress("Распаковка Java...", 0.0)
    with zipfile.ZipFile(java_zip, "r") as z:
        z.extractall(java_dir)
    java_zip.unlink(missing_ok=True)

    for p in java_dir.rglob("java.exe"):
        return p
    return None


# Install mode

def install_mode(mode: dict, on_progress: ProgressCallback, launcher_config: dict = None):
    mode_id = mode["id"]
    modpack = mode.get("modpack", {})
    loader_type = modpack.get("type", "").lower()
    # Техническая версия MC — из modpack (верхний minecraft_version только для показа).
    # Fallback на верхний — для старых режимов без modpack.minecraft_version.
    mc_version = modpack.get("minecraft_version") or mode.get("minecraft_version", "")
    mode_dir = MINECRAFT_DIR / mode_id
    is_update = is_installed(mode)  # True если уже установлено — обновление

    mode_dir.mkdir(parents=True, exist_ok=True)

    # Резолвим java_url: сначала ключ из секции java, затем прямой url
    java_url = None
    java_key = modpack.get("java") or "default"
    if launcher_config:
        java_url = launcher_config.get("java", {}).get(java_key)
    if not java_url:
        java_url = modpack.get("java_url")

    java_path = _ensure_java(java_url, java_key, on_progress)

    if loader_type in ("vanilla", "forge", "neoforge", "fabric", "quilt"):
        _install_via_mll(mode_id, mc_version, loader_type, modpack, mode_dir, java_path, on_progress, is_update)
    elif loader_type == "custom":
        _install_custom(mode_id, mc_version, modpack, mode_dir, java_path, on_progress, is_update)
    else:
        _install_legacy(mode_id, modpack, mode_dir, java_path, on_progress, is_update)


def verify_mode(mode: dict, on_progress: ProgressCallback, launcher_config: dict = None):
    """Проверка целостности: перекачивает mrpack-индекс, сверяет ВСЕ моды по sha1,
    докачивает недостающие/битые, удаляет орфанов. Бросает ошибку, если что-то не
    удалось скачать. Моды игрока, config и options.txt не трогаются."""
    install_mode(mode, on_progress, launcher_config)


def _ensure_game_jar_ref(shared_dir: str, loader_type: str, mc_version: str):
    """Чинит fabric/quilt-профиль: если `jar` не задан, а файла <id>.jar нет (mll иначе
    ссылается на несуществующий game-jar), прописываем jar=inheritsFrom → в classpath
    попадёт ванильный <mc>.jar, и Fabric найдёт игру."""
    kw = {"fabric": "fabric-loader", "quilt": "quilt-loader"}.get(loader_type)
    if not kw:
        return
    versions = Path(shared_dir) / "versions"
    if not versions.is_dir():
        return
    for d in versions.iterdir():
        if not (d.is_dir() and mc_version in d.name and kw in d.name):
            continue
        jf = d / f"{d.name}.json"
        if not jf.exists():
            continue
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
            if not data.get("jar") and data.get("inheritsFrom") and not (d / f"{d.name}.jar").exists():
                data["jar"] = data["inheritsFrom"]
                jf.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass


def _install_via_mll(mode_id: str, mc_version: str, loader_type: str,
                     modpack: dict, mode_dir: Path, java_path: Path | None,
                     on_progress: ProgressCallback, is_update: bool = False):
    """Установка через minecraft-launcher-lib."""
    import minecraft_launcher_lib as mll

    shared_dir = str(SHARED_MC_DIR)
    SHARED_MC_DIR.mkdir(parents=True, exist_ok=True)
    callbacks = _make_mll_callbacks(on_progress)

    # Ванилу + ВСЕ библиотеки (включая LWJGL 3) ставим ВСЕГДА: модлоадеры наследуют
    # от ванильной версии, но их установщики (особенно NeoForge) не докачивают
    # базовые библиотеки → иначе краш NoClassDefFoundError: org/lwjgl/Version.
    # install_minecraft_version идемпотентна — уже скачанное пропускает.
    on_progress(f"Установка Minecraft {mc_version}...", 0.0)
    mll.install.install_minecraft_version(mc_version, shared_dir, callback=callbacks)

    if loader_type == "vanilla":
        pass

    elif loader_type == "forge":
        forge_version = modpack.get("forge_version")
        if forge_version:
            full = forge_version  # уже полная строка, например "1.7.10-10.13.4.1614-1.7.10"
        else:
            on_progress("Поиск последней версии Forge...", 0.0)
            full = mll.forge.find_forge_version(mc_version)
            if not full:
                raise RuntimeError(f"Forge для Minecraft {mc_version} не найден")

        on_progress(f"Установка Forge {full}...", 0.0)
        try:
            mll.forge.install_forge_version(full, shared_dir, callback=callbacks)
        except (PermissionError, NotADirectoryError):
            pass  # installer.jar занят Java на Windows — установка прошла успешно

    elif loader_type == "neoforge":
        on_progress(f"Установка NeoForge для {mc_version}...", 0.0)
        nf_version = modpack.get("neoforge_version") or modpack.get("forge_version")
        loader = mll.mod_loader.Neoforge()
        if not nf_version:
            versions = loader.get_loader_versions(mc_version, stable_only=False)
            if not versions:
                raise RuntimeError(f"NeoForge для Minecraft {mc_version} не найден")
            nf_version = versions[0]
        java_exe = str(java_path) if java_path else "java"
        loader.install(mc_version, shared_dir, callbacks, java_exe, nf_version)

    elif loader_type == "fabric":
        on_progress(f"Установка Fabric для {mc_version}...", 0.0)
        fabric_version = modpack.get("fabric_version")
        loader = mll.mod_loader.Fabric()
        if not fabric_version:
            versions = loader.get_loader_versions(mc_version, stable_only=False)
            if not versions:
                raise RuntimeError(f"Fabric для Minecraft {mc_version} не найден")
            fabric_version = versions[0]
        java_exe = str(java_path) if java_path else "java"
        loader.install(mc_version, shared_dir, callbacks, java_exe, fabric_version)

    elif loader_type == "quilt":
        on_progress(f"Установка Quilt для {mc_version}...", 0.0)
        quilt_version = modpack.get("quilt_version")
        loader = mll.mod_loader.Quilt()
        if not quilt_version:
            versions = loader.get_loader_versions(mc_version, stable_only=False)
            if not versions:
                raise RuntimeError(f"Quilt для Minecraft {mc_version} не найден")
            quilt_version = versions[0]
        java_exe = str(java_path) if java_path else "java"
        loader.install(mc_version, shared_dir, callbacks, java_exe, quilt_version)

    # Fabric/Quilt: mll для версии с inheritsFrom+без jar берёт id ЛОАДЕРА как game-jar
    # → несуществующий путь → «Minecraft game provider couldn't locate the game».
    # Прописываем jar=inheritsFrom, чтобы на classpath попал ванильный jar.
    if loader_type in ("fabric", "quilt"):
        _ensure_game_jar_ref(shared_dir, loader_type, mc_version)

    # Скачать ZIP с модами поверх если указан
    zip_url = modpack.get("zip_url")
    if zip_url:
        cache_dir = CACHE_DIR / mode_id
        cache_dir.mkdir(parents=True, exist_ok=True)
        zip_path = cache_dir / "modpack.zip"
        on_progress("Скачивание модпака...", 0.0)
        _download_file(zip_url, zip_path, on_progress, "Скачивание модпака...")
        if _archive_is_mrpack(zip_path):
            # .mrpack: моды с Modrinth CDN + overrides, чистим только наши старые моды
            _install_mrpack(mode_id, zip_path, mode_dir, on_progress, is_update)
        else:
            # обычный zip: моды внутри архива — ПОЛНАЯ замена mods/ (в ноль),
            # чтобы не оставалось снятых/старых модов. config/saves не трогаем.
            on_progress("Распаковка модпака...", 0.0)
            mods_dir = mode_dir / "mods"
            if mods_dir.exists():
                shutil.rmtree(mods_dir, ignore_errors=True)
            _safe_extractall(zip_path, mode_dir, is_update=is_update)
            _save_mods_manifest(mode_id, mode_dir)

    installed = _load_installed()
    installed[mode_id] = {
        "version": modpack.get("version", mc_version),
        "path": str(mode_dir),
        "java": str(java_path) if java_path else None,
    }
    _save_installed(installed)
    on_progress("Установка завершена!", 1.0)


def _merge_jarmod(base_jar: Path, jarmod_jar: Path, out_jar: Path):
    """Классический jarmod: классы jarmod'а поверх ванильного jar (jarmod побеждает),
    META-INF (подпись) выкидывается. Результат — «костюмный» minecraft.jar.
    ВАЖНО: записи-ПАПКИ сохраняем — языковая система BTA (LanguageSeeker/getTips) ищет
    файлы перечислением директорий; без записей-папок tips.txt не находится и getTips
    уходит в бесконечную рекурсию (StackOverflow при user.language=en)."""
    out_jar.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    with zipfile.ZipFile(out_jar, "w", zipfile.ZIP_DEFLATED) as out:
        for src in (jarmod_jar, base_jar):          # jarmod ПЕРВЫМ → выигрывает конфликты
            with zipfile.ZipFile(src) as z:
                for item in z.namelist():
                    if item.startswith("META-INF/"):
                        continue
                    if item in seen:
                        continue
                    seen.add(item)
                    out.writestr(item, z.read(item))


def _build_jarmod_profile(base_id: str, version_id: str, jarmod_jar: Path):
    """Собирает custom-версию из базовой (установленной mll) + jarmod:
    versions/<version_id>/<version_id>.json (копия базовой с новым id) + смёрженный jar."""
    versions = SHARED_MC_DIR / "versions"
    base_json = versions / base_id / f"{base_id}.json"
    base_jar  = versions / base_id / f"{base_id}.jar"
    if not base_json.exists() or not base_jar.exists():
        raise RuntimeError(f"Базовая версия {base_id} не установлена — не из чего собирать профиль")
    out_dir = versions / version_id
    out_dir.mkdir(parents=True, exist_ok=True)
    # version JSON = копия базовой, но:
    #  - id меняем на наш;
    #  - mainClass → прямой net.minecraft.client.Minecraft (ОБХОД launchwrapper: он на
    #    Java 17 падает ClassCastException, а на Java 8 его ASM 4.1 не читает Java-8 байткод
    #    jarmod'а. Классическая бета грузится напрямую: main берёт username/session позиционно);
    #  - downloads убираем, чтобы mll не перекачал client.jar поверх нашего смёрженного.
    data = json.loads(base_json.read_text(encoding="utf-8"))
    data["id"] = version_id
    data["mainClass"] = "net.minecraft.client.Minecraft"
    data.pop("downloads", None)
    (out_dir / f"{version_id}.json").write_text(json.dumps(data), encoding="utf-8")
    _merge_jarmod(base_jar, jarmod_jar, out_dir / f"{version_id}.jar")


def _build_clientjar_profile(base_id: str, version_id: str, client_jar: Path,
                             version_json: Path, on_progress: ProgressCallback):
    """Сборка из «толстого» client.jar (напр. BTA v8): fat-jar мёржится ПОВЕРХ ванильного
    base_jar (иначе BTA ругается «нет официальной Minecraft Beta 1.7.3»), version-JSON
    берётся внешний (mainClass/args/LWJGL3-libs), его библиотеки ставятся через mll."""
    import minecraft_launcher_lib as mll
    versions = SHARED_MC_DIR / "versions"
    base_jar = versions / base_id / f"{base_id}.jar"
    if not base_jar.exists():
        raise RuntimeError(f"Базовая версия {base_id} не установлена — не с чем мёржить client.jar")
    out_dir = versions / version_id
    out_dir.mkdir(parents=True, exist_ok=True)
    data = json.loads(version_json.read_text(encoding="utf-8"))
    data["id"] = version_id
    (out_dir / f"{version_id}.json").write_text(json.dumps(data), encoding="utf-8")
    # fat client.jar (как jarmod) поверх ванильного base — client побеждает, META-INF режется
    _merge_jarmod(base_jar, client_jar, out_dir / f"{version_id}.jar")
    # библиотеки профиля (LWJGL3 и пр.) — в Mojang-формате, mll ставит и извлекает нативы
    on_progress("Установка библиотек...", 0.9)
    mll.install.install_libraries(version_id, data.get("libraries", []),
                                  str(SHARED_MC_DIR), _make_mll_callbacks(on_progress))


def _install_custom(mode_id: str, mc_version: str, modpack: dict, mode_dir: Path,
                    java_path: Path | None, on_progress: ProgressCallback,
                    is_update: bool = False):
    """Кастомный version-профиль (напр. BTA на b1.7.3, свой jar).

    В отличие от модлоадеров, установщика нет — готовый профиль приезжает в
    `modpack.profile_url` (zip с `versions/<id>/<id>.json` + jar + libs) и кладётся
    в ОБЩУЮ папку versions/. Моды/конфиг сборки (mrpack/zip) — как у всех остальных.
    Поля режима: type="custom", minecraft_version (для ассетов/нативов),
    modpack.version_id (имя папки профиля — по нему launch_mode находит версию),
    modpack.profile_url, modpack.zip_url, modpack.java (напр. "java8")."""
    import minecraft_launcher_lib as mll
    shared_dir = str(SHARED_MC_DIR)
    SHARED_MC_DIR.mkdir(parents=True, exist_ok=True)
    cache_dir = CACHE_DIR / mode_id
    cache_dir.mkdir(parents=True, exist_ok=True)

    # База: ассеты (в т.ч. legacy для старых версий), нативы, базовые libs.
    # Идемпотентна. Экзотическую версию может не встать штатно — тогда профиль несёт своё.
    if mc_version:
        on_progress(f"Установка Minecraft {mc_version}...", 0.0)
        try:
            mll.install.install_minecraft_version(mc_version, shared_dir,
                                                  callback=_make_mll_callbacks(on_progress))
        except Exception as e:
            import logging
            logging.getLogger("downloader").warning(
                "custom: базовая версия %s не встала штатно (%s) — продолжаю", mc_version, e)

    version_id = modpack.get("version_id")
    jarmod_url = modpack.get("jarmod_url")
    profile_url = modpack.get("profile_url")
    client_jar_url = modpack.get("client_jar_url")
    version_json_url = modpack.get("version_json_url")

    if client_jar_url and version_json_url and version_id and mc_version:
        # fat client.jar (BTA v8): merge поверх base + внешний version-JSON + его библиотеки
        fat = cache_dir / "client.jar"
        on_progress("Скачивание клиента...", 0.0)
        _download_file(client_jar_url, fat, on_progress, "Скачивание клиента...")
        vjson = cache_dir / "version.json"
        on_progress("Профиль версии...", 0.0)
        _download_file(version_json_url, vjson, on_progress, "Профиль версии...")
        _build_clientjar_profile(mc_version, version_id, fat, vjson, on_progress)
    elif jarmod_url and version_id and mc_version:
        # jarmod-путь (BTA): скачиваем маленький jarmod и мёржим его в базовый jar,
        # генерим version-JSON из базового — лаунчер собирает профиль сам.
        jm_path = cache_dir / "jarmod.jar"
        on_progress("Скачивание jar сборки...", 0.0)
        _download_file(jarmod_url, jm_path, on_progress, "Скачивание jar сборки...")
        on_progress("Сборка версии...", 0.9)
        _build_jarmod_profile(mc_version, version_id, jm_path)
    elif profile_url:
        # Готовый профиль: zip с корнем versions/<id>/... → в ОБЩУЮ versions/
        prof_zip = cache_dir / "profile.zip"
        on_progress("Скачивание профиля версии...", 0.0)
        _download_file(profile_url, prof_zip, on_progress, "Скачивание профиля версии...")
        on_progress("Распаковка профиля версии...", 0.9)
        _safe_extractall(prof_zip, SHARED_MC_DIR, is_update=is_update)

    # Моды/конфиг сборки → в папку режима (как везде)
    zip_url = modpack.get("zip_url")
    if zip_url:
        zip_path = cache_dir / "modpack.zip"
        on_progress("Скачивание сборки...", 0.0)
        _download_file(zip_url, zip_path, on_progress, "Скачивание сборки...")
        if _archive_is_mrpack(zip_path):
            _install_mrpack(mode_id, zip_path, mode_dir, on_progress, is_update)
        else:
            mods_dir = mode_dir / "mods"
            if mods_dir.exists():
                shutil.rmtree(mods_dir, ignore_errors=True)
            _safe_extractall(zip_path, mode_dir, is_update=is_update)
            _save_mods_manifest(mode_id, mode_dir)

    installed = _load_installed()
    installed[mode_id] = {
        "version": modpack.get("version", modpack.get("version_id", "custom")),
        "path": str(mode_dir),
        "java": str(java_path) if java_path else None,
    }
    _save_installed(installed)
    on_progress("Установка завершена!", 1.0)


def _install_legacy(mode_id: str, modpack: dict, mode_dir: Path,
                    java_path: Path | None, on_progress: ProgressCallback,
                    is_update: bool = False):
    """Старый способ: installer JAR + ZIP."""
    if not java_path:
        java_key = modpack.get("java") or "default"
        java_path = _ensure_java(modpack.get("java_url"), java_key, on_progress)

    installer_url = modpack.get("installer_url")
    if installer_url:
        installer_path = mode_dir / "installer.jar"
        on_progress("Скачивание установщика...", 0.0)
        _download_file(installer_url, installer_path, on_progress, "Скачивание установщика...")
        on_progress("Установка...", 0.0)
        java_exe = str(java_path) if java_path else (shutil.which("java") or "java")
        proc = subprocess.run(
            [java_exe, "-jar", str(installer_path), "--installClient"],
            cwd=str(mode_dir), capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Ошибка установщика:\n{proc.stderr}")
        installer_path.unlink(missing_ok=True)

    zip_url = modpack.get("zip_url")
    if zip_url:
        cache_dir = CACHE_DIR / mode_id
        cache_dir.mkdir(parents=True, exist_ok=True)
        zip_path = cache_dir / "modpack.zip"
        on_progress("Скачивание сборки...", 0.0)
        _download_file(zip_url, zip_path, on_progress, "Скачивание сборки...")
        if _archive_is_mrpack(zip_path):
            _install_mrpack(mode_id, zip_path, mode_dir, on_progress, is_update)
        else:
            # обычный zip: полная замена mods/ (в ноль), config/saves не трогаем
            on_progress("Распаковка сборки...", 0.0)
            mods_dir = mode_dir / "mods"
            if mods_dir.exists():
                shutil.rmtree(mods_dir, ignore_errors=True)
            _safe_extractall(zip_path, mode_dir, is_update=is_update)
            _save_mods_manifest(mode_id, mode_dir)

    installed = _load_installed()
    installed[mode_id] = {
        "version": modpack.get("version", "unknown"),
        "path": str(mode_dir),
        "java": str(java_path) if java_path else None,
    }
    _save_installed(installed)
    on_progress("Установка завершена!", 1.0)


def remove_mode(mode_id: str):
    mode_dir = MINECRAFT_DIR / mode_id
    if mode_dir.exists():
        try:
            shutil.rmtree(mode_dir)
        except Exception as e:
            raise RuntimeError(f"Не удалось удалить папку сборки: {e}") from e
    installed = _load_installed()
    installed.pop(mode_id, None)
    _save_installed(installed)
