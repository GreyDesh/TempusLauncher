"""
Загрузчик data.dat — читает и расшифровывает ассеты в памяти.
В режиме разработки (не frozen) читает файлы напрямую с диска.
"""
import struct
import sys
from pathlib import Path

_MAGIC = b"TDAT"
_NOT_FROZEN = not getattr(sys, "frozen", False)


def _xor(data: bytes) -> bytes:
    from asset_key import _KEY
    kl = len(_KEY)
    return bytes(b ^ _KEY[i % kl] for i, b in enumerate(data))


class _AssetPack:
    def __init__(self):
        self._index: dict[str, tuple[int, int]] = {}  # name → (offset, size)
        self._payload: bytes = b""
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        if _NOT_FROZEN:
            return  # в dev режиме читаем с диска
        path = Path(sys.executable).parent / "data.dat"
        if not path.exists():
            return
        with open(path, "rb") as f:
            magic = f.read(4)
            if magic != _MAGIC:
                return
            f.read(1)  # version
            num = struct.unpack(">I", f.read(4))[0]
            for _ in range(num):
                name_len = struct.unpack(">H", f.read(2))[0]
                name = f.read(name_len).decode("utf-8")
                offset, size = struct.unpack(">QQ", f.read(16))
                self._index[name] = (offset, size)
            self._payload = f.read()

    def read(self, name: str) -> bytes | None:
        """Читает файл по имени (например 'assets/icon.svg' или 'model/alex.png')."""
        self._load()
        if _NOT_FROZEN:
            return self._read_dev(name)
        entry = self._index.get(name)
        if entry is None:
            return None
        offset, size = entry
        return _xor(self._payload[offset: offset + size])

    def _read_dev(self, name: str) -> bytes | None:
        prefix, _, rel = name.partition("/")
        if prefix == "assets":
            p = Path(__file__).parent / "assets" / rel
        elif prefix == "model":
            p = Path(__file__).parent.parent / "model" / rel
        else:
            return None
        return p.read_bytes() if p.exists() else None

    def has(self, name: str) -> bool:
        self._load()
        if _NOT_FROZEN:
            return self._read_dev(name) is not None
        return name in self._index


_pack = _AssetPack()


def read(name: str) -> bytes | None:
    return _pack.read(name)
