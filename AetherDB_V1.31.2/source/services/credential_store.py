"""Local encrypted storage for cloud model credentials.

Credential values are protected with Windows DPAPI and only opaque references
are stored in the model registry. The encrypted payload lives under app_data,
which is a runtime-only ignored directory.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import threading
from ctypes import wintypes
from pathlib import Path

from app.config import get_runtime_path


_SECRET_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,119}$")
_ENTROPY = b"AetherDB:model-credential:v1"
_LOCK = threading.RLock()


class CredentialStoreError(RuntimeError):
    pass


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    return _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


class WindowsDpapiProtector:
    """Encrypt secrets for the current Windows user."""

    def __init__(self):
        if os.name != "nt":
            raise CredentialStoreError("Encrypted credential storage is only available on Windows")
        self._crypt32 = ctypes.windll.crypt32
        self._kernel32 = ctypes.windll.kernel32
        self._crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DATA_BLOB),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DATA_BLOB),
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(_DATA_BLOB),
        ]
        self._crypt32.CryptProtectData.restype = wintypes.BOOL
        self._crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DATA_BLOB),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DATA_BLOB),
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(_DATA_BLOB),
        ]
        self._crypt32.CryptUnprotectData.restype = wintypes.BOOL
        self._kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        self._kernel32.LocalFree.restype = wintypes.HLOCAL

    def protect(self, value: bytes) -> bytes:
        source, source_buffer = _blob(value)
        entropy, entropy_buffer = _blob(_ENTROPY)
        output = _DATA_BLOB()
        if not self._crypt32.CryptProtectData(
            ctypes.byref(source),
            "AetherDB model credential",
            ctypes.byref(entropy),
            None,
            None,
            0,
            ctypes.byref(output),
        ):
            raise CredentialStoreError("Windows could not encrypt the model credential")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._kernel32.LocalFree(output.pbData)

    def unprotect(self, value: bytes) -> bytes:
        source, source_buffer = _blob(value)
        entropy, entropy_buffer = _blob(_ENTROPY)
        output = _DATA_BLOB()
        if not self._crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            ctypes.byref(entropy),
            None,
            None,
            0,
            ctypes.byref(output),
        ):
            raise CredentialStoreError("Windows could not decrypt the model credential")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._kernel32.LocalFree(output.pbData)


class ModelCredentialStore:
    def __init__(self, path: Path | None = None, protector=None):
        self.path = Path(path or get_runtime_path("app_data", "model_credentials.json"))
        self._protector = protector or WindowsDpapiProtector()

    @staticmethod
    def _validate_name(name: str) -> str:
        if not _SECRET_NAME_RE.fullmatch(name or ""):
            raise CredentialStoreError("Invalid credential name")
        return name

    def _load(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "items": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CredentialStoreError("Model credential store is unreadable") from exc
        if payload.get("version") != 1 or not isinstance(payload.get("items"), dict):
            raise CredentialStoreError("Model credential store has an unsupported format")
        return payload

    def _save(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, self.path)

    def set_secret(self, name: str, value: str) -> None:
        name = self._validate_name(name)
        if not isinstance(value, str) or not value or len(value) > 8192:
            raise CredentialStoreError("Invalid credential value")
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise CredentialStoreError("Credential contains control characters")
        encrypted = self._protector.protect(value.encode("utf-8"))
        with _LOCK:
            payload = self._load()
            payload["items"][name] = base64.b64encode(encrypted).decode("ascii")
            self._save(payload)

    def get_secret(self, name: str) -> str:
        name = self._validate_name(name)
        with _LOCK:
            encoded = self._load()["items"].get(name)
        if not encoded:
            raise CredentialStoreError("Credential reference is not configured")
        try:
            encrypted = base64.b64decode(encoded, validate=True)
            return self._protector.unprotect(encrypted).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise CredentialStoreError("Stored model credential is invalid") from exc

    def delete_secret(self, name: str) -> bool:
        name = self._validate_name(name)
        with _LOCK:
            payload = self._load()
            removed = payload["items"].pop(name, None) is not None
            if removed:
                self._save(payload)
            return removed

    def has_secret(self, name: str) -> bool:
        name = self._validate_name(name)
        with _LOCK:
            return name in self._load()["items"]


def get_model_credential_store() -> ModelCredentialStore:
    return ModelCredentialStore()
