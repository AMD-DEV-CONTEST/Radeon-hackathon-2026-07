"""Audit report builder (contract section 11) + export ZIP.

Guarantees:
  - no raw transcript text, no PII: every ``text_preview`` field is stripped
  - no absolute host paths anywhere in the serialized JSON (asserted)
Pure stdlib; safe to unit-test without torch/ffmpeg.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

AUDIT_SCHEMA_VERSION = "1.0"

_EVENT_FIELDS = ("id", "kind", "category", "start_s", "end_s", "action", "source", "status", "warnings")

# Quoted JSON string that is an absolute POSIX path (two+ segments under a
# known root) or a Windows drive path.
_ABS_PATH_RE = re.compile(
    r'"(?:/(?:Users|home|root|var|tmp|private|opt|mnt|srv|Volumes|etc|usr)/[^"]*'
    r'|[A-Za-z]:\\\\[^"]*)"'
)

_ZIP_MEMBERS = ("redacted.mp4", "redacted.srt", "audit.json")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _dump(obj: Any) -> Any:
    """Best-effort conversion of pydantic models / dataclass-likes to plain data."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {k: _dump(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_dump(v) for v in obj]
    if isinstance(obj, Path):
        return obj.name
    if hasattr(obj, "__dict__"):
        return {k: _dump(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return str(obj)


def _looks_like_abs_path(text: str) -> bool:
    if re.match(r"^[A-Za-z]:[\\/]", text):
        return True
    return text.startswith("/") and text.count("/") >= 2 and " " not in text[:1]


def sanitize(obj: Any) -> Any:
    """Recursively drop ``text_preview`` keys and reduce absolute-path-looking
    strings to their basename."""
    if isinstance(obj, dict):
        return {
            k: sanitize(v)
            for k, v in obj.items()
            if k != "text_preview"
        }
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, Path):
        return obj.name
    if isinstance(obj, str) and _looks_like_abs_path(obj):
        return Path(obj).name
    return obj


def assert_no_absolute_paths(json_text: str) -> None:
    """Raise ValueError if the serialized JSON contains an absolute host path."""
    match = _ABS_PATH_RE.search(json_text)
    if match:
        raise ValueError(f"audit JSON contains an absolute path: {match.group(0)[:80]}")


def _resolution_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return f"{int(value[0])}x{int(value[1])}"
    if isinstance(value, dict) and "width" in value and "height" in value:
        return f"{int(value['width'])}x{int(value['height'])}"
    return "0x0"


def _media_digest(info: Any) -> dict:
    info = _dump(info) or {}
    if not isinstance(info, dict):
        info = {}
    return {
        "sha256": str(info.get("sha256") or ""),
        "duration_s": float(info.get("duration_s") or 0.0),
        "resolution": _resolution_str(info.get("resolution") or info),
    }


def _default_environment() -> dict:
    env = {
        "gpu_name": None,
        "rocm_version": None,
        "torch_version": None,
        "python": platform.python_version(),
    }
    try:
        from policycut.core.device import device_info  # lazy: other module owns this
        di = device_info() or {}
        env["gpu_name"] = di.get("name")
        env["rocm_version"] = di.get("hip_version")
        env["torch_version"] = di.get("torch_version")
        return env
    except Exception:
        pass
    try:
        import torch  # lazy heavy dep

        env["torch_version"] = str(torch.__version__)
        env["rocm_version"] = getattr(getattr(torch, "version", None), "hip", None)
        if torch.cuda.is_available():
            env["gpu_name"] = torch.cuda.get_device_name(0)
    except Exception:
        logger.debug("torch unavailable for audit environment", exc_info=True)
    return env


def _audit_event(event: Any) -> dict:
    data = _dump(event) or {}
    out = {}
    for field in _EVENT_FIELDS:
        value = data.get(field) if isinstance(data, dict) else None
        if field == "warnings":
            value = list(value or [])
        out[field] = value
    return out


def _counts(events: list) -> dict:
    dumped = [_dump(ev) or {} for ev in events]
    return {
        "auto": sum(1 for e in dumped if e.get("source") == "auto"),
        "manual": sum(1 for e in dumped if e.get("source") == "manual"),
        "confirmed": sum(1 for e in dumped if e.get("status") == "confirmed"),
        "ignored": sum(1 for e in dumped if e.get("status") == "ignored"),
    }


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------

def build_audit(
    project: Any = None,
    policy: Any = None,
    events: list | None = None,
    stage_metrics: dict | None = None,
    input_info: dict | None = None,
    output_info: dict | None = None,
    models: list | None = None,
    environment: dict | None = None,
    review_history_count: int = 0,
    warnings: list | None = None,
) -> dict:
    """Build the audit dict per contract section 11.

    ``input_info`` / ``output_info`` are ``{"sha256", "duration_s",
    "resolution"}`` (resolution as "WxH" string, (w, h) pair, or a dict with
    width/height). ``project`` is accepted for call-site convenience but no
    project-identifying data is emitted. The result is fully sanitized: no
    text_preview, no absolute paths.
    """
    events = events or []
    audit = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "input": _media_digest(input_info),
        "output": _media_digest(output_info),
        "policy": _dump(policy),
        "models": [_dump(m) for m in (models or [])],
        "environment": _dump(environment) if environment else _default_environment(),
        "stage_metrics": _dump(stage_metrics or {}),
        "events": [_audit_event(ev) for ev in events],
        "counts": _counts(events),
        "review_history_count": int(review_history_count or 0),
        "warnings": [str(w) for w in (warnings or [])],
    }
    audit = sanitize(audit)
    assert_no_absolute_paths(json.dumps(audit))
    return audit


def write_audit(audit: dict, out_path: str | Path) -> Path:
    """Sanitize, validate and atomically write audit.json."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    clean = sanitize(audit)
    text = json.dumps(clean, indent=2, sort_keys=True, default=str)
    assert_no_absolute_paths(text)
    tmp = out_path.with_name(out_path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, out_path)
    return out_path


def build_zip(exports_dir: str | Path, zip_name: str = "policycut_export.zip") -> Path:
    """Bundle exports/{redacted.mp4, redacted.srt, audit.json} into
    exports/policycut_export.zip (arcnames are basenames only)."""
    exports_dir = Path(exports_dir)
    members = [exports_dir / name for name in _ZIP_MEMBERS if (exports_dir / name).exists()]
    if not members:
        raise FileNotFoundError(
            f"No export artifacts found in {exports_dir.name}/ (expected {', '.join(_ZIP_MEMBERS)})"
        )
    zip_path = exports_dir / zip_name
    tmp = zip_path.with_name(zip_path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w") as zf:
        for member in members:
            compression = (
                zipfile.ZIP_STORED if member.suffix == ".mp4" else zipfile.ZIP_DEFLATED
            )
            zf.write(member, arcname=member.name, compress_type=compression)
    os.replace(tmp, zip_path)
    logger.info("wrote %s with %d members", zip_path.name, len(members))
    return zip_path
