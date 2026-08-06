"""Analysis and render pipelines for PolicyCut.

Implements docs/CONTRACTS.md section 7.

``run_analysis`` and ``run_render`` orchestrate the module pipeline. Heavy ML
modules (torch, transformers, sam2, whisper, presidio) are imported lazily
inside each stage and wrapped in try/except: a missing dependency or model is
recorded as a fallback warning and the pipeline continues on a degraded path
wherever one exists. When ``POLICYCUT_REQUIRE_ROCM=1`` the core model stages
raise ``RuntimeError`` instead of falling back to CPU.

Because sibling modules are developed in parallel and the contract fixes only
some function names/signatures, calls into them go through a small adaptive
binder (:func:`_call_flex`) that fills parameters by name.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import inspect
import json
import logging
import os
import platform
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from policycut.core.ids import new_id
from policycut.core.models import BoxKeyframe, RedactionEvent

logger = logging.getLogger(__name__)

__all__ = ["JobCancelled", "run_analysis", "run_render"]

ProgressCallback = Callable[..., None]

ANALYSIS_STAGES = [
    "NORMALIZING",
    "PARSING_POLICY",
    "TRANSCRIBING",
    "DETECTING_PII",
    "DETECTING_VISUAL",
    "TRACKING",
    "BUILDING_PREVIEW",
    "REVIEW_READY",
]
RENDER_STAGES = ["RENDERING", "MUXING", "AUDITING", "COMPLETE"]


class JobCancelled(Exception):
    """Raised when a job's cancel event is set; the queue marks the job cancelled."""


# ---------------------------------------------------------------------------
# Small generic helpers
# ---------------------------------------------------------------------------


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_cancel(cancel_event: Any) -> None:
    if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
        raise JobCancelled("job cancelled")


def _safe_cb(
    progress_cb: Optional[ProgressCallback],
    stage: str,
    progress: float,
    message: str = "",
    metrics: Optional[dict] = None,
) -> None:
    """Invoke the progress callback without letting UI plumbing kill the job."""
    if progress_cb is None:
        return
    try:
        progress_cb(stage, float(progress), message, metrics)
    except TypeError:
        try:
            progress_cb(stage, float(progress), message)
        except Exception:  # pragma: no cover - defensive
            logger.debug("progress callback failed", exc_info=True)
    except Exception:  # pragma: no cover - defensive
        logger.debug("progress callback failed", exc_info=True)


def _log(store: Any, project_id: str, stage: str, level: str, msg: str, extra: Optional[dict] = None) -> None:
    """Log to the module logger and append to the per-project pipeline.jsonl."""
    log_fn = getattr(logger, level if level in ("debug", "info", "warning", "error") else "info")
    log_fn("[%s] %s: %s", project_id, stage, msg)
    try:
        path = store.path(project_id, "logs", "pipeline.jsonl")
        line = json.dumps(
            {"ts": _utcnow(), "stage": stage, "level": level, "msg": msg, "extra": extra or {}}
        )
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:  # pragma: no cover - logging must never crash the pipeline
        logger.debug("could not append pipeline log", exc_info=True)


def _float(value: Any, default: float) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    """Fetch the first non-None attribute or dict key among ``names``."""
    for name in names:
        if isinstance(obj, dict):
            value = obj.get(name)
        else:
            value = getattr(obj, name, None)
        if value is not None:
            return value
    return default


def _write_json_atomic(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _sha256(path: Path) -> Optional[str]:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except Exception:
        return None


def _to_jsonable(obj: Any, _depth: int = 0) -> Any:
    """Best-effort conversion to JSON-serializable data (drops bulky masks)."""
    if _depth > 10:
        return None
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, Path):
        return obj.name  # never leak absolute host paths
    if hasattr(obj, "model_dump"):
        try:
            return _to_jsonable(obj.model_dump(), _depth + 1)
        except Exception:
            pass
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        try:
            return _to_jsonable(dataclasses.asdict(obj), _depth + 1)
        except Exception:
            pass
    if isinstance(obj, dict):
        return {
            str(k): _to_jsonable(v, _depth + 1)
            for k, v in obj.items()
            if str(k) not in ("masks", "mask")
        }
    if isinstance(obj, (list, tuple, set)):
        return [_to_jsonable(v, _depth + 1) for v in obj]
    try:  # numpy scalars / small arrays
        import numpy as np  # noqa: WPS433 (lazy)

        if isinstance(obj, np.generic):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist() if obj.size <= 4096 else None
    except Exception:
        pass
    if hasattr(obj, "__dict__"):
        return _to_jsonable(
            {k: v for k, v in vars(obj).items() if not k.startswith("_")}, _depth + 1
        )
    return str(obj)


# ---------------------------------------------------------------------------
# Adaptive binding to sibling modules
# ---------------------------------------------------------------------------

_ALIAS_MAP: dict[str, tuple[str, ...]] = {
    "project_id": ("project_id", "pid"),
    "store": ("store",),
    "settings": ("settings", "config", "cfg"),
    "project": ("project", "proj"),
    "policy": ("policy", "spec", "policy_spec"),
    "media": ("media", "media_info", "video_info", "info"),
    "input_path": (
        "input_path", "in_path", "src", "source", "source_path", "src_path",
        "path", "video_path", "video", "input_file", "video_file", "infile",
        "normalized_path", "normalized",
    ),
    "output_path": (
        "output_path", "out_path", "dst", "dest", "destination", "dst_path",
        "output", "output_file", "out_file", "outfile",
    ),
    "audio_path": ("audio_path", "wav_path", "audio", "wav", "audio_file"),
    "transcript": ("transcript", "asr", "transcription"),
    "events": ("events", "redaction_events", "confirmed_events"),
    "detections": ("detections", "dets"),
    "tracks": ("tracks",),
    "masks_dir": ("masks_dir", "mask_dir", "masks_path"),
    "cancel_event": ("cancel_event", "cancel", "stop_event"),
    "proxy_path": ("proxy_path", "proxy"),
    "work_dir": ("work_dir", "working_dir", "workdir", "out_dir", "output_dir"),
    "language": ("language", "lang"),
}


def _ctx(**named: Any) -> dict[str, Any]:
    """Build a parameter-name -> value context with common aliases."""
    ctx: dict[str, Any] = {}
    for key, value in named.items():
        for alias in _ALIAS_MAP.get(key, (key,)):
            ctx.setdefault(alias, value)
    return ctx


def _call_flex(fn: Callable, ctx: dict[str, Any]) -> Any:
    """Call ``fn`` binding its parameters by name from ``ctx``."""
    sig = inspect.signature(fn)
    kwargs: dict[str, Any] = {}
    missing: list[str] = []
    for name, param in sig.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if name in ctx:
            kwargs[name] = ctx[name]
        elif param.default is inspect.Parameter.empty:
            missing.append(name)
    if missing:
        raise TypeError(
            f"{getattr(fn, '__name__', fn)!s} has required parameters {missing} "
            "that the pipeline cannot supply"
        )
    return fn(**kwargs)


def _resolve_fn(module: Any, names: Iterable[str], keyword: Optional[str] = None) -> Callable:
    """Find the module's entry point among candidate names, else by keyword."""
    for name in names:
        fn = getattr(module, name, None)
        if callable(fn):
            return fn
    if keyword:
        candidates = []
        for attr in dir(module):
            if attr.startswith("_") or keyword not in attr.lower():
                continue
            fn = getattr(module, attr, None)
            if inspect.isfunction(fn) and getattr(fn, "__module__", "") == module.__name__:
                candidates.append(fn)
        if len(candidates) == 1:
            return candidates[0]
    raise AttributeError(f"no callable {list(names)} found in {module.__name__}")


# ---------------------------------------------------------------------------
# Device / metrics helpers
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _fallback_stage_metrics(stage: str):
    metrics: dict[str, Any] = {"frames": None, "precision": None}
    started = time.time()
    try:
        yield metrics
    finally:
        metrics["wall_s"] = round(time.time() - started, 3)
        metrics.setdefault("peak_vram_mb", None)


def _stage_metrics(stage: str):
    try:
        from policycut.core import device as core_device

        fn = getattr(core_device, "stage_metrics", None)
        if callable(fn):
            return fn(stage)
    except Exception:
        logger.debug("core.device.stage_metrics unavailable; using fallback timer")
    return _fallback_stage_metrics(stage)


def _record_metrics(
    metrics_all: dict[str, dict], stage: str, raw: Any, fallbacks: Optional[list[str]] = None
) -> dict:
    entry: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    entry.setdefault("wall_s", None)
    entry.setdefault("peak_vram_mb", None)
    entry.setdefault("frames", None)
    entry.setdefault("precision", None)
    merged = list(entry.get("fallbacks") or [])
    for item in fallbacks or []:
        if item not in merged:
            merged.append(item)
    entry["fallbacks"] = merged
    metrics_all[stage] = entry
    return entry


def _rocm_required(settings: Any) -> bool:
    return bool(getattr(settings, "require_rocm", False)) or os.environ.get(
        "POLICYCUT_REQUIRE_ROCM"
    ) == "1"


def _ensure_gpu(settings: Any, stage: str) -> None:
    """Raise RuntimeError when ROCm is required but no GPU is usable."""
    if not _rocm_required(settings):
        return
    try:
        from policycut.core import device as core_device
    except Exception as exc:  # pragma: no cover - device helpers are contract-owned
        raise RuntimeError(
            f"{stage}: POLICYCUT_REQUIRE_ROCM=1 but device helpers are unavailable: {exc}"
        )
    for name in ("ensure_gpu", "require_gpu", "check_require_rocm"):
        fn = getattr(core_device, name, None)
        if callable(fn):
            fn()
            return
    if core_device.get_device() != "cuda":
        raise RuntimeError(
            f"{stage}: ROCm GPU required (POLICYCUT_REQUIRE_ROCM=1) but no GPU is available"
        )


def _device_info() -> dict:
    try:
        from policycut.core.device import device_info

        return device_info()
    except Exception:
        return {
            "available": False,
            "name": "unknown",
            "torch_version": None,
            "hip_version": None,
            "rocm": False,
        }


def _free_gpu_cache() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _unload_whisper() -> None:
    try:
        from policycut.audio import transcribe as transcribe_mod

        fn = getattr(transcribe_mod, "unload_whisper", None)
        if callable(fn):
            fn()
            return
    except Exception:
        pass
    _free_gpu_cache()


def _unload_detector() -> None:
    try:
        from policycut.vision import detector as detector_mod

        for name in ("unload", "unload_models", "unload_dino", "release", "cleanup"):
            fn = getattr(detector_mod, name, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    logger.debug("detector unload failed", exc_info=True)
                return
    except Exception:
        pass
    _free_gpu_cache()


# ---------------------------------------------------------------------------
# Project / event helpers
# ---------------------------------------------------------------------------


def _find_source(store: Any, project_id: str) -> Optional[Path]:
    src_dir = Path(store.project_dir(project_id)) / "source"
    if src_dir.is_dir():
        for path in sorted(src_dir.iterdir()):
            if path.is_file() and path.stem == "original":
                return path
    return None


def _set_project_status(store: Any, project_id: str, status: str, error: Optional[str]) -> None:
    try:
        project = store.get_project(project_id)
        if project is None:
            return
        project.status = status
        project.error = error
        project.updated_at = _utcnow()
        store.save_project(project)
    except Exception:  # never mask the original failure
        logger.exception("could not persist project status %s for %s", status, project_id)


def _audio_action_for(policy: Any, category: str) -> dict:
    for target in getattr(policy, "audio_targets", []) or []:
        if getattr(target, "category", None) == category:
            action = getattr(target, "action", None)
            if hasattr(action, "model_dump"):
                return action.model_dump()
            if isinstance(action, dict):
                return dict(action)
    return {"type": "mute"}


def _visual_action_for(policy: Any, category: str) -> dict:
    for target in getattr(policy, "visual_targets", []) or []:
        if getattr(target, "category", None) == category:
            action = getattr(target, "action", None)
            if hasattr(action, "model_dump"):
                return action.model_dump()
            if isinstance(action, dict):
                return dict(action)
    return {"type": "pixelate", "strength": 65}


def _draft_to_audio_event(draft: Any, policy: Any) -> Optional[RedactionEvent]:
    """Convert an audio PII draft (arbitrary shape) into a RedactionEvent."""
    if isinstance(draft, RedactionEvent):
        if not draft.id:
            draft.id = new_id("e")
        draft.kind = "audio"
        draft.source = "auto"
        draft.status = "pending"
        if not draft.action:
            draft.action = _audio_action_for(policy, draft.category)
        return draft
    category = str(_get(draft, "category", default="phone")).lower()
    start = _get(draft, "start_s", "start", "t0")
    end = _get(draft, "end_s", "end", "t1")
    if start is None:
        return None
    start_f = _float(start, 0.0)
    end_f = _float(end, start_f)
    if end_f < start_f:
        start_f, end_f = end_f, start_f
    action = _get(draft, "action")
    if hasattr(action, "model_dump"):
        action = action.model_dump()
    if not isinstance(action, dict) or "type" not in action:
        action = _audio_action_for(policy, category)
    preview = str(_get(draft, "text_preview", "preview", "label", default="") or category.upper())
    warnings = [str(w) for w in (_get(draft, "warnings", default=None) or [])]
    return RedactionEvent(
        id=new_id("e"),
        kind="audio",
        category=category,
        status="pending",
        source="auto",
        start_s=start_f,
        end_s=end_f,
        action=action,
        confidence=_float(_get(draft, "confidence", "score"), 1.0),
        text_preview=preview,
        warnings=warnings,
    )


def _to_box_keyframe(kf: Any) -> Optional[BoxKeyframe]:
    if isinstance(kf, BoxKeyframe):
        return kf
    try:
        if isinstance(kf, (list, tuple)) and len(kf) == 5:
            t, x, y, w, h = kf
            return BoxKeyframe(t=float(t), x=float(x), y=float(y), w=float(w), h=float(h))
        if (
            isinstance(kf, (list, tuple))
            and len(kf) == 2
            and isinstance(kf[1], (list, tuple))
            and len(kf[1]) == 4
        ):
            # tracker.Track keyframe format: (t, (x, y, w, h))
            t, (x, y, w, h) = kf
            return BoxKeyframe(t=float(t), x=float(x), y=float(y), w=float(w), h=float(h))
        if isinstance(kf, dict):
            src: dict[str, Any] = dict(kf)
        else:
            src = {
                name: getattr(kf, name, None)
                for name in ("t", "time", "x", "y", "w", "h", "width", "height",
                             "box", "box_norm", "bbox")
            }
        t = src.get("t", src.get("time"))
        x, y = src.get("x"), src.get("y")
        w = src.get("w", src.get("width"))
        h = src.get("h", src.get("height"))
        if x is None:
            box = src.get("box") or src.get("box_norm") or src.get("bbox")
            if isinstance(box, (list, tuple)) and len(box) == 4:
                x, y, w, h = box
        if t is None or x is None or y is None or w is None or h is None:
            return None
        return BoxKeyframe(t=float(t), x=float(x), y=float(y), w=float(w), h=float(h))
    except Exception:
        return None


def _track_to_event(track: Any, policy: Any) -> Optional[RedactionEvent]:
    """Convert a Track (arbitrary shape) into one visual RedactionEvent."""
    if isinstance(track, RedactionEvent):
        if not track.id:
            track.id = new_id("e")
        track.kind = "visual"
        track.source = "auto"
        track.status = "pending"
        if not track.track_id:
            track.track_id = new_id("t")
        if not track.action:
            track.action = _visual_action_for(policy, track.category)
        return track
    boxes: list[BoxKeyframe] = []
    for kf in _get(track, "boxes", "keyframes", "kfs", default=None) or []:
        box = _to_box_keyframe(kf)
        if box is not None:
            boxes.append(box)
    if not boxes:
        return None
    boxes.sort(key=lambda b: b.t)
    track_id = str(_get(track, "id", "track_id", default=None) or new_id("t"))
    category = str(_get(track, "category", default="face"))
    start = _float(_get(track, "start_s", "start"), boxes[0].t)
    end = _float(_get(track, "end_s", "end"), boxes[-1].t)
    warnings = [str(w) for w in (_get(track, "warnings", default=None) or [])]
    return RedactionEvent(
        id=new_id("e"),
        kind="visual",
        category=category,
        status="pending",
        source="auto",
        start_s=start,
        end_s=end,
        action=_visual_action_for(policy, category),
        confidence=_float(_get(track, "confidence", "score", "min_score", "score_min"), 1.0),
        track_id=track_id,
        boxes=boxes,
        warnings=warnings,
    )


def _save_track_masks(store: Any, project_id: str, track: Any, track_id: str) -> bool:
    """Persist a track's masks dict to analysis/masks/<track_id>.npz if present."""
    masks = _get(track, "masks", default=None)
    if not masks or not isinstance(masks, dict):
        return False
    try:
        import numpy as np

        arrays = {}
        for t, mask in masks.items():
            arrays[f"{_float(t, 0.0):.3f}"] = np.asarray(mask)
        if not arrays:
            return False
        path = store.path(project_id, "analysis", "masks", f"{track_id}.npz")
        np.savez_compressed(path, **arrays)
        return True
    except Exception:
        logger.debug("could not save masks for track %s", track_id, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Stage metrics persistence
# ---------------------------------------------------------------------------


def _stage_metrics_path(store: Any, project_id: str) -> Path:
    return Path(store.project_dir(project_id)) / "analysis" / "stage_metrics.json"


def _load_stage_metrics(store: Any, project_id: str) -> dict:
    try:
        path = _stage_metrics_path(store, project_id)
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _write_stage_metrics(store: Any, project_id: str, metrics: dict) -> None:
    try:
        existing = _load_stage_metrics(store, project_id)
        existing.update(_to_jsonable(metrics) or {})
        path = store.path(project_id, "analysis", "stage_metrics.json")
        _write_json_atomic(Path(path), existing)
    except Exception:
        logger.debug("could not write stage_metrics.json", exc_info=True)


# ---------------------------------------------------------------------------
# SRT generation (pure-python fallback)
# ---------------------------------------------------------------------------

_SRT_CATEGORIES = {"phone": "PHONE", "email": "EMAIL", "address": "ADDRESS"}


def _redaction_tag(category: Any) -> str:
    return f"[REDACTED: {_SRT_CATEGORIES.get(str(category).lower(), 'MANUAL')}]"


def _srt_time(t: float) -> str:
    ms_total = max(0, int(round(float(t) * 1000)))
    hours, rem = divmod(ms_total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"


def _transcript_segments(data: Any) -> list[dict]:
    if data is None:
        return []
    if isinstance(data, dict):
        segments = data.get("segments") or data.get("chunks") or []
    elif isinstance(data, list):
        segments = data
    else:
        segments = getattr(data, "segments", None) or []
    out: list[dict] = []
    for seg in segments:
        if hasattr(seg, "model_dump"):
            try:
                seg = seg.model_dump()
            except Exception:
                continue
        if not isinstance(seg, dict):
            continue
        start = seg.get("start", seg.get("start_s", seg.get("begin")))
        end = seg.get("end", seg.get("end_s"))
        ts = seg.get("timestamp")
        if start is None and isinstance(ts, (list, tuple)) and len(ts) == 2:
            start, end = ts
        if start is None:
            continue
        out.append(
            {
                "start": _float(start, 0.0),
                "end": _float(end, _float(start, 0.0)),
                "text": str(seg.get("text", "") or "").strip(),
                "words": seg.get("words") or seg.get("word_timestamps") or [],
            }
        )
    return out


def _word_span(word: Any) -> tuple[Optional[float], Optional[float], str]:
    if isinstance(word, dict):
        start = word.get("start", word.get("start_s", word.get("t0")))
        end = word.get("end", word.get("end_s", word.get("t1")))
        ts = word.get("timestamp")
        if start is None and isinstance(ts, (list, tuple)) and len(ts) == 2:
            start, end = ts
        text = str(word.get("word", word.get("text", "")) or "")
        return (
            None if start is None else _float(start, 0.0),
            None if end is None else _float(end, 0.0),
            text,
        )
    return None, None, str(word)


def _redacted_segment_text(segment: dict, audio_events: list[RedactionEvent]) -> str:
    overlapping = [
        e for e in audio_events if e.end_s > segment["start"] and e.start_s < segment["end"]
    ]
    if not overlapping:
        return segment["text"]
    words = segment.get("words") or []
    if words:
        tokens: list[str] = []
        last_tag: Optional[str] = None
        for word in words:
            w_start, w_end, w_text = _word_span(word)
            tag = None
            if w_start is not None:
                midpoint = (w_start + (w_end if w_end is not None else w_start)) / 2.0
                for event in overlapping:
                    if event.start_s <= midpoint <= event.end_s:
                        tag = _redaction_tag(event.category)
                        break
            if tag:
                if tag != last_tag:
                    tokens.append(tag)
                last_tag = tag
            else:
                if w_text.strip():
                    tokens.append(w_text.strip())
                last_tag = None
        if tokens:
            return " ".join(tokens)
    # Segment-level fallback: replace the whole segment text with the tag(s).
    tags = list(dict.fromkeys(_redaction_tag(e.category) for e in overlapping))
    return " ".join(tags)


def _write_srt(transcript_data: Any, audio_events: list[RedactionEvent], out_path: Path) -> bool:
    segments = _transcript_segments(transcript_data)
    if not segments:
        return False
    lines: list[str] = []
    index = 1
    for segment in segments:
        text = _redacted_segment_text(segment, audio_events)
        if not text:
            continue
        lines.append(str(index))
        lines.append(f"{_srt_time(segment['start'])} --> {_srt_time(segment['end'])}")
        lines.append(text)
        lines.append("")
        index += 1
    if index == 1:
        return False
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, out_path)
    return True


# ---------------------------------------------------------------------------
# Audit fallback
# ---------------------------------------------------------------------------


def _probe_safe(path: Path) -> Any:
    try:
        from policycut.media import probe as probe_mod

        for name in ("probe_media", "probe", "get_media_info", "ffprobe", "probe_video"):
            fn = getattr(probe_mod, name, None)
            if callable(fn):
                return fn(path)
    except Exception:
        pass
    return None


def _fallback_audit(
    *,
    audit_path: Path,
    project: Any,
    policy: Any,
    events: list[RedactionEvent],
    settings: Any,
    stage_metrics: dict,
    input_path: Optional[Path],
    output_path: Path,
    input_sha256: Optional[str],
    output_sha256: Optional[str],
    review_history_count: int,
    warnings: list[str],
) -> None:
    """Write a contract-compliant audit.json without the audit module."""
    dev = _device_info()
    media = getattr(project, "media", None)
    in_res = f"{getattr(media, 'width', 0)}x{getattr(media, 'height', 0)}" if media else None
    in_dur = getattr(media, "duration_s", None) if media else None
    out_dur, out_res = in_dur, in_res
    out_info = _probe_safe(output_path)
    if out_info is not None:
        out_dur = _float(_get(out_info, "duration_s", "duration"), _float(in_dur, 0.0))
        width = _get(out_info, "width")
        height = _get(out_info, "height")
        if width and height:
            out_res = f"{int(width)}x{int(height)}"
    device_name = dev.get("name") if dev.get("available") else "cpu"
    models = []
    for stage, model_id in (
        ("policy_parsing", getattr(settings, "qwen_model", None)),
        ("transcription", getattr(settings, "whisper_model", None)),
        ("visual_detection", getattr(settings, "dino_model", None)),
        ("tracking", getattr(settings, "sam2_model", None)),
    ):
        if model_id:
            models.append(
                {"stage": stage, "model_id": model_id, "precision": None, "device": device_name}
            )
    counts = {
        "auto": sum(1 for e in events if e.source == "auto"),
        "manual": sum(1 for e in events if e.source == "manual"),
        "confirmed": sum(1 for e in events if e.status == "confirmed"),
        "ignored": sum(1 for e in events if e.status == "ignored"),
    }
    audit = {
        "schema_version": "1.0",
        "generated_at": _utcnow(),
        "input": {"sha256": input_sha256, "duration_s": in_dur, "resolution": in_res},
        "output": {"sha256": output_sha256, "duration_s": out_dur, "resolution": out_res},
        "policy": _to_jsonable(policy),
        "models": models,
        "environment": {
            "gpu_name": dev.get("name"),
            "rocm_version": dev.get("hip_version"),
            "torch_version": dev.get("torch_version"),
            "python": platform.python_version(),
        },
        "stage_metrics": _to_jsonable(stage_metrics) or {},
        "events": [
            {
                "id": e.id,
                "kind": e.kind,
                "category": e.category,
                "start_s": e.start_s,
                "end_s": e.end_s,
                "action": e.action,
                "source": e.source,
                "status": e.status,
                "warnings": e.warnings,
            }
            for e in events
        ],
        "counts": counts,
        "review_history_count": review_history_count,
        "warnings": warnings,
    }
    _write_json_atomic(audit_path, audit)


def _fallback_zip(exports_dir: Path, zip_path: Path) -> None:
    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = zip_path.with_name(zip_path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in ("redacted.mp4", "redacted.srt", "audit.json"):
            path = exports_dir / name
            if path.is_file():
                zf.write(path, arcname=name)
    os.replace(tmp, zip_path)


def _review_history_count(store: Any, project_id: str) -> int:
    try:
        path = Path(store.project_dir(project_id)) / "review_history.jsonl"
        if path.is_file():
            with open(path, "r", encoding="utf-8") as fh:
                return sum(1 for line in fh if line.strip())
    except Exception:
        pass
    return 0


# ---------------------------------------------------------------------------
# run_analysis
# ---------------------------------------------------------------------------


def run_analysis(
    project_id: str,
    store: Any,
    settings: Any,
    progress_cb: Optional[ProgressCallback],
    cancel_event: Any,
) -> None:
    """Run the full analysis pipeline (contract section 7)."""
    try:
        _analysis_impl(project_id, store, settings, progress_cb, cancel_event)
    except JobCancelled:
        _set_project_status(store, project_id, "draft", None)
        _log(store, project_id, "CANCELLED", "info", "analysis cancelled by user")
        raise
    except Exception as exc:
        _set_project_status(store, project_id, "error", f"{type(exc).__name__}: {exc}")
        _log(store, project_id, "ERROR", "error", f"analysis failed: {exc}")
        raise


def _analysis_impl(
    project_id: str,
    store: Any,
    settings: Any,
    progress_cb: Optional[ProgressCallback],
    cancel_event: Any,
) -> None:
    project = store.get_project(project_id)
    if project is None:
        raise ValueError(f"Unknown project: {project_id}")
    if project.media is None:
        raise ValueError("No media uploaded for this project")

    metrics_all: dict[str, dict] = {}
    pipeline_warnings: list[str] = []
    project_dir = Path(store.project_dir(project_id))
    work_dir = project_dir / "working"

    # ---------------- NORMALIZING ----------------
    _check_cancel(cancel_event)
    stage = "NORMALIZING"
    _safe_cb(progress_cb, stage, 0.02, "Normalizing video")
    _log(store, project_id, stage, "info", "start")
    source_path = _find_source(store, project_id)
    if source_path is None:
        raise ValueError("Source video file is missing on disk")
    normalized_target = Path(store.path(project_id, "working", "normalized.mp4"))
    norm_ret = None
    fallbacks: list[str] = []
    with _stage_metrics(stage) as m:
        try:
            from policycut.media import normalize as normalize_mod

            fn = _resolve_fn(normalize_mod, ("normalize_video", "normalize"), keyword="normalize")
            norm_ret = _call_flex(
                fn,
                _ctx(
                    project_id=project_id,
                    store=store,
                    settings=settings,
                    project=project,
                    media=project.media,
                    input_path=source_path,
                    output_path=normalized_target,
                    work_dir=work_dir,
                    cancel_event=cancel_event,
                ),
            )
        except JobCancelled:
            raise
        except Exception as exc:
            fallbacks.append("normalize_failed")
            pipeline_warnings.append(f"normalization fallback: {exc}")
            _log(store, project_id, stage, "warning",
                 f"normalize failed, using source file directly: {exc}")
    entry = _record_metrics(metrics_all, stage, m, fallbacks)
    _safe_cb(progress_cb, stage, 0.10, "Normalization done", {stage: entry})

    normalized_path = normalized_target if normalized_target.is_file() else source_path
    proxy_candidates = sorted(work_dir.glob("proxy*.mp4")) if work_dir.is_dir() else []
    proxy_path = proxy_candidates[0] if proxy_candidates else normalized_path
    asr_wav = work_dir / "asr.wav"
    asr_wav = asr_wav if asr_wav.is_file() else None
    video_info = project.media
    for candidate in (norm_ret, _get(norm_ret, "media", "media_info", "info") if norm_ret is not None else None):
        if candidate is not None and hasattr(candidate, "duration_s") and hasattr(candidate, "fps"):
            video_info = candidate
            break

    # ---------------- PARSING_POLICY ----------------
    _check_cancel(cancel_event)
    stage = "PARSING_POLICY"
    _safe_cb(progress_cb, stage, 0.11, "Validating saved policy")
    with _stage_metrics(stage) as m:
        policy = store.load_policy(project_id)
        if policy is None:
            raise ValueError("No saved policy for this project; save a policy before analysis")
        from policycut.policy.schema import PolicySpec

        policy = PolicySpec.model_validate(
            policy.model_dump() if hasattr(policy, "model_dump") else policy
        )
    entry = _record_metrics(metrics_all, stage, m, [])
    _safe_cb(
        progress_cb, stage, 0.13,
        f"Policy loaded: {len(policy.visual_targets)} visual, {len(policy.audio_targets)} audio targets",
        {stage: entry},
    )
    _log(store, project_id, stage, "info",
         f"policy ok: visual={len(policy.visual_targets)} audio={len(policy.audio_targets)}")

    # ---------------- TRANSCRIBING ----------------
    stage = "TRANSCRIBING"
    transcript: Any = None
    has_audio = bool(getattr(video_info, "has_audio", False))
    if not has_audio or not policy.audio_targets:
        reason = "no audio track in video" if not has_audio else "no audio targets in policy"
        _log(store, project_id, stage, "info", f"skipped ({reason})")
        entry = _record_metrics(metrics_all, stage, {"wall_s": 0.0}, ["skipped"])
        _safe_cb(progress_cb, stage, 0.33, f"Skipped ({reason})", {stage: entry})
    else:
        _check_cancel(cancel_event)
        _safe_cb(progress_cb, stage, 0.15, "Transcribing audio (Whisper)")
        _log(store, project_id, stage, "info", "start")
        _ensure_gpu(settings, stage)
        fallbacks = []
        with _stage_metrics(stage) as m:
            try:
                from policycut.audio import transcribe as transcribe_mod

                fn = _resolve_fn(
                    transcribe_mod,
                    ("transcribe", "transcribe_audio", "run_transcription", "run"),
                    keyword="transcribe",
                )
                audio_input = asr_wav or normalized_path
                transcript = _call_flex(
                    fn,
                    _ctx(
                        project_id=project_id,
                        store=store,
                        settings=settings,
                        policy=policy,
                        input_path=audio_input,
                        audio_path=audio_input,
                        media=video_info,
                        language=policy.language,
                        cancel_event=cancel_event,
                    ),
                )
            except JobCancelled:
                raise
            except Exception as exc:
                transcript = None
                fallbacks.append("whisper_unavailable")
                pipeline_warnings.append(f"transcription fallback: {exc}")
                _log(store, project_id, stage, "warning", f"transcription failed: {exc}")
        entry = _record_metrics(metrics_all, stage, m, fallbacks)
        _safe_cb(progress_cb, stage, 0.33,
                 "Transcription done" if transcript is not None else "Transcription unavailable",
                 {stage: entry})

    transcript_file = project_dir / "analysis" / "transcript.private.json"
    if transcript is not None:
        try:
            _write_json_atomic(
                Path(store.path(project_id, "analysis", "transcript.private.json")),
                _to_jsonable(transcript),
            )
        except Exception:
            pipeline_warnings.append("transcript_save_failed")
    elif transcript_file.is_file():
        # transcribe module may have persisted it directly
        try:
            transcript = json.loads(transcript_file.read_text(encoding="utf-8"))
        except Exception:
            transcript = None

    # ---------------- DETECTING_PII ----------------
    stage = "DETECTING_PII"
    audio_events: list[RedactionEvent] = []
    if transcript is None:
        _log(store, project_id, stage, "info", "skipped (no transcript)")
        entry = _record_metrics(metrics_all, stage, {"wall_s": 0.0}, ["skipped"])
        _safe_cb(progress_cb, stage, 0.38, "Skipped (no transcript)", {stage: entry})
    else:
        _check_cancel(cancel_event)
        _safe_cb(progress_cb, stage, 0.34, "Scanning transcript for PII")
        fallbacks = []
        with _stage_metrics(stage) as m:
            try:
                from policycut.audio import pii as pii_mod

                fn = getattr(pii_mod, "detect_pii")
                try:
                    drafts = fn(transcript, policy)
                except TypeError:
                    drafts = _call_flex(
                        fn,
                        _ctx(transcript=transcript, policy=policy, settings=settings,
                             media=video_info, store=store, project_id=project_id),
                    )
                for draft in drafts or []:
                    event = _draft_to_audio_event(draft, policy)
                    if event is not None:
                        audio_events.append(event)
            except Exception as exc:
                fallbacks.append("pii_detection_failed")
                pipeline_warnings.append(f"audio PII fallback: {exc}")
                _log(store, project_id, stage, "warning", f"PII detection failed: {exc}")
        entry = _record_metrics(metrics_all, stage, m, fallbacks)
        _safe_cb(progress_cb, stage, 0.38,
                 f"{len(audio_events)} audio PII events found", {stage: entry})
        _log(store, project_id, stage, "info", f"{len(audio_events)} audio events")
    # Sequential model memory: whisper is no longer needed.
    _unload_whisper()
    try:
        _write_json_atomic(
            Path(store.path(project_id, "analysis", "audio_events.json")),
            [e.model_dump() for e in audio_events],
        )
    except Exception:
        logger.debug("could not save audio_events.json", exc_info=True)

    # ---------------- DETECTING_VISUAL ----------------
    stage = "DETECTING_VISUAL"
    detections: list[Any] = []
    if not policy.visual_targets:
        _log(store, project_id, stage, "info", "skipped (no visual targets in policy)")
        entry = _record_metrics(metrics_all, stage, {"wall_s": 0.0}, ["skipped"])
        _safe_cb(progress_cb, stage, 0.62, "Skipped (no visual targets)", {stage: entry})
    else:
        _check_cancel(cancel_event)
        _safe_cb(progress_cb, stage, 0.40, "Detecting visual targets (GroundingDINO + YuNet)")
        _log(store, project_id, stage, "info", "start")
        _ensure_gpu(settings, stage)
        fallbacks = []
        with _stage_metrics(stage) as m:
            try:
                from policycut.vision import detector as detector_mod

                fn = _resolve_fn(
                    detector_mod,
                    ("detect", "run_detection", "detect_objects", "detect_keyframes", "run"),
                    keyword="detect",
                )
                detections = _call_flex(
                    fn,
                    _ctx(
                        project_id=project_id,
                        store=store,
                        settings=settings,
                        policy=policy,
                        input_path=proxy_path,
                        proxy_path=proxy_path,
                        media=video_info,
                        cancel_event=cancel_event,
                    ),
                ) or []
            except JobCancelled:
                raise
            except Exception as exc:
                detections = []
                fallbacks.append("visual_detection_failed")
                pipeline_warnings.append(f"visual detection fallback: {exc}")
                _log(store, project_id, stage, "warning", f"visual detection failed: {exc}")
        entry = _record_metrics(metrics_all, stage, m, fallbacks)
        _safe_cb(progress_cb, stage, 0.62,
                 f"{len(detections)} raw detections", {stage: entry})

    # ---------------- TRACKING ----------------
    _check_cancel(cancel_event)
    stage = "TRACKING"
    _safe_cb(progress_cb, stage, 0.64, "Building tracks")
    visual_events: list[RedactionEvent] = []
    tracks: list[Any] = []
    fallbacks = []
    masks_dir = project_dir / "analysis" / "masks"
    with _stage_metrics(stage) as m:
        if detections:
            try:
                from policycut.vision import tracker as tracker_mod

                fn = getattr(tracker_mod, "build_tracks")
                try:
                    tracks = fn(detections, video_info, policy) or []
                except TypeError:
                    tracks = _call_flex(
                        fn,
                        _ctx(
                            detections=detections,
                            media=video_info,
                            policy=policy,
                            settings=settings,
                            input_path=proxy_path,
                            proxy_path=proxy_path,
                            store=store,
                            project_id=project_id,
                            duration_s=_float(getattr(video_info, "duration_s", None), 0.0),
                            fps=_float(getattr(video_info, "fps", None), 0.0),
                        ),
                    ) or []
            except Exception as exc:
                fallbacks.append("tracking_failed")
                pipeline_warnings.append(f"tracking fallback: {exc}")
                _log(store, project_id, stage, "warning", f"tracking failed: {exc}")
        if tracks:
            # Sequential model memory: unload DINO before SAM2.
            _unload_detector()
            _check_cancel(cancel_event)
            try:
                masks_dir.mkdir(parents=True, exist_ok=True)
                from policycut.vision import sam2_tracker as sam2_mod

                fn = _resolve_fn(
                    sam2_mod,
                    ("refine_tracks", "refine", "propagate_tracks", "propagate", "run", "track_video"),
                    keyword="refine",
                )
                refined = _call_flex(
                    fn,
                    _ctx(
                        tracks=tracks,
                        input_path=proxy_path,
                        proxy_path=proxy_path,
                        settings=settings,
                        store=store,
                        project_id=project_id,
                        media=video_info,
                        masks_dir=masks_dir,
                        cancel_event=cancel_event,
                    ),
                )
                if isinstance(refined, list) and refined:
                    tracks = refined
            except JobCancelled:
                raise
            except Exception as exc:
                fallbacks.append("sam2_unavailable")
                pipeline_warnings.append(f"SAM2 fallback (box interpolation): {exc}")
                _log(store, project_id, stage, "warning",
                     f"SAM2 refinement unavailable, using box interpolation: {exc}")
        for track in tracks:
            event = _track_to_event(track, policy)
            if event is None:
                continue
            _save_track_masks(store, project_id, track, event.track_id or "")
            if not (masks_dir / f"{event.track_id}.npz").is_file():
                if "rect_fallback" not in event.warnings:
                    event.warnings.append("rect_fallback")
            if event.confidence < 0.35 and "low_confidence" not in event.warnings:
                event.warnings.append("low_confidence")
            visual_events.append(event)
        try:
            _write_json_atomic(
                Path(store.path(project_id, "analysis", "tracks.json")),
                {"tracks": _to_jsonable(tracks)},
            )
        except Exception:
            fallbacks.append("tracks_save_failed")
    entry = _record_metrics(metrics_all, stage, m, fallbacks)
    _safe_cb(progress_cb, stage, 0.85,
             f"{len(visual_events)} visual events from {len(tracks)} tracks", {stage: entry})
    _log(store, project_id, stage, "info",
         f"{len(tracks)} tracks -> {len(visual_events)} visual events")

    # ---------------- BUILDING_PREVIEW ----------------
    _check_cancel(cancel_event)
    stage = "BUILDING_PREVIEW"
    _safe_cb(progress_cb, stage, 0.88, "Building review overlay")
    fallbacks = []
    with _stage_metrics(stage) as m:
        if not visual_events and not audio_events:
            fallbacks.append("skipped_no_events")
            _log(store, project_id, stage, "info",
                 "skipped (no events; preview endpoint falls back to normalized video)")
        else:
            overlay_target = Path(store.path(project_id, "working", "review_overlay.mp4"))
            try:
                from policycut.review import overlay as overlay_mod

                fn = _resolve_fn(
                    overlay_mod,
                    ("build_overlay", "build_review_overlay", "render_overlay", "build",
                     "create_overlay"),
                    keyword="overlay",
                )
                _call_flex(
                    fn,
                    _ctx(
                        project_id=project_id,
                        store=store,
                        settings=settings,
                        project=project,
                        policy=policy,
                        events=visual_events + audio_events,
                        input_path=normalized_path,
                        output_path=overlay_target,
                        media=video_info,
                        cancel_event=cancel_event,
                    ),
                )
            except JobCancelled:
                raise
            except Exception as exc:
                fallbacks.append("overlay_failed")
                pipeline_warnings.append(f"review overlay fallback: {exc}")
                _log(store, project_id, stage, "warning",
                     f"overlay build failed (frontend falls back to original preview): {exc}")
    entry = _record_metrics(metrics_all, stage, m, fallbacks)
    _safe_cb(progress_cb, stage, 0.97, "Preview ready", {stage: entry})

    # ---------------- finalize ----------------
    _check_cancel(cancel_event)
    events = visual_events + audio_events
    events.sort(key=lambda e: (e.start_s, e.kind))
    store.save_events(project_id, events)
    if pipeline_warnings:
        metrics_all.setdefault("_warnings", {})  # keep shape stage -> dict
        metrics_all["_warnings"] = {"fallbacks": pipeline_warnings, "wall_s": None,
                                    "peak_vram_mb": None, "frames": None, "precision": None}
    _write_stage_metrics(store, project_id, metrics_all)

    project = store.get_project(project_id) or project
    project.status = "review_ready"
    project.revision = int(project.revision) + 1
    project.exports_stale = (project_dir / "exports" / "redacted.mp4").is_file()
    project.error = None
    project.updated_at = _utcnow()
    store.save_project(project)
    try:
        store.append_review_history(
            project_id,
            {"ts": _utcnow(), "action": "analysis_complete", "events": len(events),
             "revision": project.revision},
        )
    except Exception:
        logger.debug("could not append review history", exc_info=True)
    _log(store, project_id, "REVIEW_READY", "info",
         f"analysis complete: {len(events)} events")
    _safe_cb(progress_cb, "REVIEW_READY", 1.0,
             f"Analysis complete: {len(events)} events ready for review", metrics_all)


# ---------------------------------------------------------------------------
# run_render
# ---------------------------------------------------------------------------


def run_render(
    project_id: str,
    store: Any,
    settings: Any,
    progress_cb: Optional[ProgressCallback],
    cancel_event: Any,
) -> None:
    """Run the render/export pipeline (contract section 7)."""
    try:
        _render_impl(project_id, store, settings, progress_cb, cancel_event)
    except JobCancelled:
        _set_project_status(store, project_id, "review_ready", None)
        _log(store, project_id, "CANCELLED", "info", "render cancelled by user")
        raise
    except Exception as exc:
        _set_project_status(store, project_id, "error", f"{type(exc).__name__}: {exc}")
        _log(store, project_id, "ERROR", "error", f"render failed: {exc}")
        raise


def _render_impl(
    project_id: str,
    store: Any,
    settings: Any,
    progress_cb: Optional[ProgressCallback],
    cancel_event: Any,
) -> None:
    project = store.get_project(project_id)
    if project is None:
        raise ValueError(f"Unknown project: {project_id}")
    events = store.load_events(project_id)
    pending_auto = [e for e in events if e.source == "auto" and e.status == "pending"]
    if pending_auto:
        raise ValueError(
            f"Cannot render: {len(pending_auto)} auto-detected events are still pending review"
        )
    confirmed = [e for e in events if e.status == "confirmed"]
    policy = store.load_policy(project_id)

    project_dir = Path(store.project_dir(project_id))
    source_path = _find_source(store, project_id)
    normalized = project_dir / "working" / "normalized.mp4"
    input_video = normalized if normalized.is_file() else source_path
    if input_video is None:
        raise ValueError("No source video available to render")
    output_video = Path(store.path(project_id, "exports", "redacted.mp4"))
    masks_dir = project_dir / "analysis" / "masks"
    render_warnings: list[str] = []
    metrics_all: dict[str, dict] = {}

    # ---------------- RENDERING ----------------
    _check_cancel(cancel_event)
    stage = "RENDERING"
    _safe_cb(progress_cb, stage, 0.05, f"Rendering {len(confirmed)} confirmed redactions")
    _log(store, project_id, stage, "info", f"start ({len(confirmed)} confirmed events)")
    with _stage_metrics(stage) as m:
        from policycut.media import render as render_mod

        fn = getattr(render_mod, "render_video", None)
        if not callable(fn):
            fn = _resolve_fn(render_mod, ("render", "render_project"), keyword="render")
        ctx = _ctx(
            project_id=project_id,
            store=store,
            settings=settings,
            project=project,
            policy=policy,
            events=confirmed,
            input_path=input_video,
            output_path=output_video,
            masks_dir=masks_dir,
            media=project.media,
            cancel_event=cancel_event,
        )
        ctx["paths"] = {
            "normalized": input_video,
            "exports_dir": output_video.parent,
            "masks_dir": masks_dir,
        }
        ctx["progress_cb"] = progress_cb
        result = _call_flex(fn, ctx)
    if not output_video.is_file():
        if isinstance(result, (str, Path)) and Path(result).is_file():
            shutil.move(str(result), str(output_video))
        else:
            raise RuntimeError("Render did not produce exports/redacted.mp4")
    entry = _record_metrics(metrics_all, stage, m, [])
    _safe_cb(progress_cb, stage, 0.75, "Render done", {stage: entry})

    # ---------------- MUXING ----------------
    _check_cancel(cancel_event)
    stage = "MUXING"
    _safe_cb(progress_cb, stage, 0.78, "Writing subtitles and validating output")
    fallbacks: list[str] = []
    with _stage_metrics(stage) as m:
        srt_path = Path(store.path(project_id, "exports", "redacted.srt"))
        transcript_file = project_dir / "analysis" / "transcript.private.json"
        if transcript_file.is_file():
            audio_confirmed = [e for e in confirmed if e.kind == "audio"]
            transcript_data: Any = None
            try:
                transcript_data = json.loads(transcript_file.read_text(encoding="utf-8"))
            except Exception:
                fallbacks.append("transcript_unreadable")
            wrote = False
            if transcript_data is not None:
                try:
                    from policycut.media import render as render_mod

                    srt_fn = _resolve_fn(
                        render_mod,
                        ("write_srt", "build_srt", "render_srt", "make_srt", "export_srt"),
                        keyword="srt",
                    )
                    _call_flex(
                        srt_fn,
                        _ctx(
                            transcript=transcript_data,
                            events=audio_confirmed,
                            output_path=srt_path,
                            srt_path=srt_path,
                            path=srt_path,
                            project_id=project_id,
                            store=store,
                            settings=settings,
                        ),
                    )
                    wrote = srt_path.is_file()
                except Exception:
                    wrote = False
                if not wrote:
                    try:
                        wrote = _write_srt(transcript_data, audio_confirmed, srt_path)
                    except Exception as exc:
                        fallbacks.append("srt_failed")
                        render_warnings.append(f"srt generation failed: {exc}")
            if not wrote and "srt_failed" not in fallbacks and transcript_data is not None:
                fallbacks.append("srt_empty")
        else:
            _log(store, project_id, stage, "info", "no transcript; skipping SRT")
    entry = _record_metrics(metrics_all, stage, m, fallbacks)
    _safe_cb(progress_cb, stage, 0.85, "Mux/subtitles done", {stage: entry})

    # ---------------- AUDITING ----------------
    _check_cancel(cancel_event)
    stage = "AUDITING"
    _safe_cb(progress_cb, stage, 0.88, "Building audit trail")
    fallbacks = []
    with _stage_metrics(stage) as m:
        analysis_metrics = _load_stage_metrics(store, project_id)
        combined_metrics = dict(analysis_metrics)
        combined_metrics.update(_to_jsonable(metrics_all) or {})
        input_sha = _sha256(source_path) if source_path else None
        output_sha = _sha256(output_video)
        history_count = _review_history_count(store, project_id)
        audit_path = Path(store.path(project_id, "exports", "audit.json"))
        dev = _device_info()
        built = False
        audit_ctx = _ctx(
            project_id=project_id,
            store=store,
            settings=settings,
            project=project,
            policy=policy,
            events=events,
            media=project.media,
            input_path=source_path,
            output_path=output_video,
            stage_metrics=combined_metrics,
            metrics=combined_metrics,
            device_info=dev,
            environment=dev,
            input_sha256=input_sha,
            output_sha256=output_sha,
            review_history_count=history_count,
            audit_path=audit_path,
            warnings=render_warnings,
        )
        try:
            from policycut.audit import builder as audit_mod

            fn = getattr(audit_mod, "build_audit", None)
            if not callable(fn):
                fn = _resolve_fn(audit_mod, ("build", "build_audit_json"), keyword="audit")
            # build_audit expects input_info/output_info digests and a models
            # list; supply them explicitly, then persist via write_audit (the
            # builder returns a dict — it does not write the file itself).
            audit_ctx = dict(audit_ctx)
            audit_ctx["input_info"] = {
                "sha256": input_sha,
                "duration_s": getattr(project.media, "duration_s", None) if project.media else None,
                "resolution": (f"{project.media.width}x{project.media.height}"
                               if project.media else None),
            }
            audit_ctx["output_info"] = {
                "sha256": output_sha,
                "duration_s": getattr(project.media, "duration_s", None) if project.media else None,
                "resolution": (f"{project.media.width}x{project.media.height}"
                               if project.media else None),
            }
            device_name = dev.get("name") if dev.get("available") else "cpu"
            audit_ctx["models"] = [
                {"stage": s, "model_id": mid, "precision": None, "device": device_name}
                for s, mid in (
                    ("policy_parsing", getattr(settings, "qwen_model", None)),
                    ("transcription", getattr(settings, "whisper_model", None)),
                    ("visual_detection", getattr(settings, "dino_model", None)),
                    ("tracking", getattr(settings, "sam2_model", None)),
                )
                if mid
            ]
            result = _call_flex(fn, audit_ctx)
            if isinstance(result, dict) and result:
                writer = getattr(audit_mod, "write_audit", None)
                if callable(writer):
                    writer(result, audit_path)
                else:
                    _write_json_atomic(audit_path, result)
            built = audit_path.is_file()
        except Exception as exc:
            _log(store, project_id, stage, "warning",
                 f"audit builder unavailable, using fallback: {exc}")
        if not built:
            fallbacks.append("audit_builder_fallback")
            _fallback_audit(
                audit_path=audit_path,
                project=project,
                policy=policy,
                events=events,
                settings=settings,
                stage_metrics=combined_metrics,
                input_path=source_path,
                output_path=output_video,
                input_sha256=input_sha,
                output_sha256=output_sha,
                review_history_count=history_count,
                warnings=render_warnings,
            )
        # Export zip
        zip_path = Path(store.path(project_id, "exports", "policycut_export.zip"))
        zipped = False
        try:
            from policycut.audit import builder as audit_mod

            zip_ctx = dict(audit_ctx)
            zip_ctx["exports_dir"] = project_dir / "exports"
            for name in ("build_zip", "build_export_zip", "make_zip", "zip_export", "create_zip"):
                zfn = getattr(audit_mod, name, None)
                if callable(zfn):
                    _call_flex(zfn, zip_ctx)
                    zipped = zip_path.is_file()
                    break
        except Exception:
            zipped = False
        if not zipped or not zip_path.is_file():
            _fallback_zip(project_dir / "exports", zip_path)
    entry = _record_metrics(metrics_all, stage, m, fallbacks)
    _safe_cb(progress_cb, stage, 0.97, "Audit trail written", {stage: entry})

    _write_stage_metrics(store, project_id, metrics_all)

    # ---------------- COMPLETE ----------------
    project = store.get_project(project_id) or project
    project.status = "complete"
    project.exports_stale = False
    project.error = None
    project.updated_at = _utcnow()
    store.save_project(project)
    try:
        store.append_review_history(
            project_id, {"ts": _utcnow(), "action": "render_complete"}
        )
    except Exception:
        logger.debug("could not append review history", exc_info=True)
    _log(store, project_id, "COMPLETE", "info", "render complete")
    _safe_cb(progress_cb, "COMPLETE", 1.0, "Render complete", metrics_all)
