
# Windows DPAPI — шифрование данных ключом текущей учётной записи Windows.
# Расшифровать может только тот же пользователь на том же ПК.
# Fallback: если DPAPI недоступен (не Windows / ошибка) — хранит как есть.

import ctypes
import ctypes.wintypes
import base64


def encrypt(plaintext: str) -> str:
    """Шифрует строку через DPAPI. Возвращает base64-строку."""
    try:
        data = plaintext.encode("utf-8")
        blob_in  = _make_blob(data)
        blob_out = _DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0,
            ctypes.byref(blob_out),
        )
        if not ok:
            return plaintext  # fallback
        encrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return base64.b64encode(encrypted).decode("ascii")
    except Exception:
        return plaintext  # fallback


def decrypt(ciphertext: str) -> str:
    """Расшифровывает строку, зашифрованную encrypt(). Fallback: возвращает как есть."""
    try:
        raw = base64.b64decode(ciphertext)
    except Exception:
        return ciphertext  # не base64 — уже plaintext (старый формат)
    try:
        blob_in  = _make_blob(raw)
        blob_out = _DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0,
            ctypes.byref(blob_out),
        )
        if not ok:
            return ciphertext  # fallback
        decrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return decrypted.decode("utf-8")
    except Exception:
        return ciphertext  # fallback


# Internal

class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _make_blob(data: bytes) -> _DATA_BLOB:
    blob = _DATA_BLOB()
    blob.cbData = len(data)
    blob.pbData = ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char))
    return blob
