# Упаковщик ассетов — запускается при сборке.
# Упаковывает assets/ и model/ в один data.dat файл.

# Использование: py -3.11 pack_assets.py

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from asset_key import _KEY

MAGIC = b"TDAT"
VERSION = 1

ASSET_DIRS = [
    ("assets", Path(__file__).parent / "assets"),
    ("model",  Path(__file__).parent.parent / "model"),
]

OUT_FILE = Path(__file__).parent / "data.dat"


def _xor(data: bytes) -> bytes:
    key = _KEY
    kl = len(key)
    return bytes(b ^ key[i % kl] for i, b in enumerate(data))


def pack():
    entries: list[tuple[str, bytes]] = []

    for prefix, folder in ASSET_DIRS:
        if not folder.exists():
            print(f"[!] Папка не найдена: {folder}")
            continue
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                rel = f"{prefix}/{path.relative_to(folder).as_posix()}"
                data = path.read_bytes()
                entries.append((rel, data))
                print(f"  + {rel}  ({len(data)} б)")

    # Собираем payload (зашифрованные данные подряд)
    payload = bytearray()
    index: list[tuple[str, int, int]] = []  # (name, offset, size)
    for name, data in entries:
        enc = _xor(data)
        index.append((name, len(payload), len(enc)))
        payload.extend(enc)

    # Сериализуем индекс
    index_buf = bytearray()
    index_buf += struct.pack(">I", len(index))
    for name, offset, size in index:
        name_b = name.encode("utf-8")
        index_buf += struct.pack(">H", len(name_b))
        index_buf += name_b
        index_buf += struct.pack(">QQ", offset, size)

    with open(OUT_FILE, "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack(">B", VERSION))
        f.write(index_buf)
        f.write(payload)

    total = OUT_FILE.stat().st_size
    print(f"\n[OK] {OUT_FILE}  ({total / 1024 / 1024:.1f} МБ, {len(entries)} файлов)")


if __name__ == "__main__":
    pack()
