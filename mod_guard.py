"""Mod protection: enforce mod_protection rules before launching."""
import json
import zipfile
from pathlib import Path
from typing import Callable

from config import CACHE_DIR

ProgressCallback = Callable[[str, float], None] | None


def check_and_enforce(mode: dict, mode_dir: Path, on_progress: ProgressCallback = None) -> list[str]:
    """Check mods folder against protection rules. Returns log of actions taken."""
    mp = mode.get("modpack", {}).get("mod_protection", "none")
    pmode = mp if isinstance(mp, str) else mp.get("mode", "none")
    if pmode == "none":
        return []
    if pmode == "strict":
        return _enforce_strict(mode["id"], mode_dir / "mods", on_progress)
    return []


def _get_manifest(mode_id: str) -> list[str]:
    path = CACHE_DIR / mode_id / "mods_manifest.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _enforce_strict(mode_id: str, mods_dir: Path, on_progress: ProgressCallback) -> list[str]:
    manifest = set(_get_manifest(mode_id))
    if not manifest:
        return []

    actions: list[str] = []

    # Remove extra files not in manifest
    if mods_dir.exists():
        for f in list(mods_dir.iterdir()):
            if f.is_file() and f.name not in manifest:
                f.unlink()
                actions.append(f"Удалён посторонний мод: {f.name}")

    # Restore missing files from cached archive
    existing = {f.name for f in mods_dir.iterdir() if f.is_file()} if mods_dir.exists() else set()
    missing = manifest - existing
    if missing:
        zip_path = CACHE_DIR / mode_id / "modpack.zip"
        if zip_path.exists():
            if on_progress:
                on_progress("Восстановление модов...", 0.0)
            mods_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path) as z:
                for entry in z.namelist():
                    name = Path(entry).name
                    if not name or name not in missing:
                        continue
                    # Принимаем только записи из папки mods/ без path traversal
                    if not entry.startswith("mods/") or ".." in entry:
                        continue
                    target = mods_dir / name
                    if not target.resolve().is_relative_to(mods_dir.resolve()):
                        continue
                    target.write_bytes(z.read(entry))
                    actions.append(f"Восстановлен мод: {name}")
        else:
            actions.append("Архив не найден, восстановление пропущено")

    return actions
