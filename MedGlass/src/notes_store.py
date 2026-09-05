"""Persistent note history store.

Every generated SOAP note is archived under ``output/notes/<id>.json`` with
full metadata (session, source, transcript, visual findings, timestamps) so the
dashboard can list, view and export past visits. The latest note is also
mirrored to the legacy ``output/soap_note.{txt,json}`` files.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from utils import write_json

from config import CONFIG
from crypto import decrypt_text, encrypt_text, is_encrypted

LOG = logging.getLogger("medglass.notes")

NOTES_DIR = Path("output") / "notes"
ID_PREFIX = "mg"

REQUIRED = ("id", "created_at", "session_id", "source", "note")


def _crypto_enabled() -> bool:
    try:
        return bool(CONFIG["encrypt_at_rest"])
    except Exception:
        return False


def _ensure_dir() -> Path:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    return NOTES_DIR


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return f"{ID_PREFIX}_{int(time.time())}_{secrets.token_hex(2)}"


def save_note(*, note: str, session_id: str, source: str,
              sections: dict[str, str] | None = None,
              transcript: str = "",
              visual_findings: list[dict] | None = None,
              photos: list[dict] | None = None,
              patient_id: str = "",
              provider: str = "") -> dict:
    """Archive a note and return its record. Mirrors the latest to soap_note.*"""
    record = {
        "id": _new_id(),
        "created_at": _utc_now(),
        "session_id": session_id or "default",
        "source": source or "api",
        "patient_id": patient_id or "",
        "provider": provider or "",
        "note": note,
        "sections": sections or {},
        "transcript": transcript or "",
        "visual_findings": visual_findings or [],
        "photos": photos or [],
    }
    path = _ensure_dir() / f"{record['id']}.json"
    payload = json.dumps(record, indent=2)
    if _crypto_enabled():
        path.write_text(encrypt_text(payload), encoding="utf-8")
        LOG.info("note archived (encrypted): %s (source=%s, photos=%d)",
                 record["id"], record["source"], len(record["photos"]))
    else:
        write_json(path, record)
        LOG.info("note archived: %s (source=%s, photos=%d)",
                 record["id"], record["source"], len(record["photos"]))
    return record


def _read_record(path: Path) -> dict | None:
    """Read a note file, transparently decrypting v1 blobs."""
    try:
        text = path.read_text(encoding="utf-8")
        if is_encrypted(text):
            text = decrypt_text(text)
        return json.loads(text)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        LOG.warning("skipping unreadable note %s: %s", path.name, exc)
        return None


def list_notes() -> list[dict]:
    """All archived notes, newest first."""
    out: list[dict] = []
    if not NOTES_DIR.exists():
        return out
    for path in sorted(NOTES_DIR.glob(f"{ID_PREFIX}_*.json"),
                       reverse=True):
        record = _read_record(path)
        if record and all(record.get(k) is not None for k in REQUIRED):
            out.append(record)
    return out


def get_note(note_id: str) -> dict | None:
    path = NOTES_DIR / f"{note_id}.json"
    if not path.exists():
        return None
    record = _read_record(path)
    if record is None:
        LOG.warning("note %s unreadable", note_id)
        return None
    return record


def delete_note(note_id: str) -> bool:
    path = NOTES_DIR / f"{note_id}.json"
    if not path.exists():
        return False
    try:
        path.unlink()
    except OSError as exc:
        LOG.warning("failed to delete note %s: %s", note_id, exc)
        return False
    LOG.info("note deleted: %s", note_id)
    return True


def mirror_latest(record: dict) -> None:
    """Keep the legacy output/soap_note.{txt,json} mirrors in sync."""
    out = Path("output")
    out.mkdir(parents=True, exist_ok=True)
    json_payload = json.dumps({
        "id": record["id"],
        "created_at": record["created_at"],
        "source": record["source"],
        "note": record["note"],
        "sections": record["sections"],
        "transcript": record["transcript"],
        "visual_findings": record["visual_findings"],
        "photos": record["photos"],
    }, indent=2)
    txt_payload = record["note"]
    if _crypto_enabled():
        (out / "soap_note.json").write_text(encrypt_text(json_payload), encoding="utf-8")
        (out / "soap_note.txt").write_text(encrypt_text(txt_payload), encoding="utf-8")
    else:
        write_json(out / "soap_note.json", json.loads(json_payload))
        (out / "soap_note.txt").write_text(txt_payload, encoding="utf-8")
