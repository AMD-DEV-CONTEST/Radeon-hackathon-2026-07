"""Photo capture store.

Every photo taken on the Mentra glasses (or via /vision/process) is saved to
``output/photos/`` as the original JPEG, and a small metadata record (with the
detections / OCR found) is returned so it can be tied to a session and archived
with the note.

Files are served back under ``/photos/<name>`` (token-gated) so the dashboard
can show the pictures belonging to a case.
"""

from __future__ import annotations

import logging
import re
import secrets
import time
from pathlib import Path

from config import CONFIG
from crypto import decrypt_bytes, encrypt_bytes, is_encrypted

PHOTOS_DIR = Path("output") / "photos"


def _crypto_enabled() -> bool:
    try:
        return bool(CONFIG["encrypt_at_rest"])
    except Exception:
        return False


def _write(path: Path, data: bytes) -> None:
    if _crypto_enabled():
        token = encrypt_bytes(data)
        path.write_text(token, encoding="utf-8") if token else path.write_bytes(data)
    else:
        path.write_bytes(data)


def read_photo(path: Path) -> bytes:
    """Return decrypted photo bytes (transparent for plaintext files)."""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    if is_encrypted(text):
        return decrypt_bytes(text)
    return raw


def _ensure_dir() -> Path:
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    return PHOTOS_DIR


def _slug(session_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "session")[:40]


def save_photo(session_id: str, original_jpeg: bytes,
               detections: list[dict]) -> dict:
    """Persist a photo JPEG and return a photo metadata record.

    ``detections`` is a list of dicts describing what was found in the frame
    (e.g. ``{"kind": "medication", "detail": "lisinopril 10mg"}``).
    """
    name = f"{_slug(session_id)}_{int(time.time())}_{secrets.token_hex(2)}"
    _ensure_dir()
    original_path = PHOTOS_DIR / f"{name}.jpg"
    _write(original_path, original_jpeg or b"")
    record = {
        "id": name,
        "ts": time.time(),
        "original": f"/photos/{original_path.name}",
        "detections": detections or [],
    }
    logging.getLogger("medglass.notes").info(
        "photo saved: %s (%d detections)", name, len(record["detections"]))
    return record


def photo_path(filename: str) -> Path | None:
    """Resolve a photo filename to a file path (validates the name)."""
    name = Path(filename).name
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.jpg", name):
        return None
    path = PHOTOS_DIR / name
    return path if path.exists() else None


def photo_mime(filename: str) -> str:
    return "image/jpeg"
