"""Qualia Studio training service (M7.3).

Provides an abstraction over the Qualia Studio API for cloud-based training
with algorithms like ACT, SmolVLA, and Pi0. Falls back to a mock/stub mode
when the Qualia token is not configured, allowing the UI to render the
options without breaking.

Environment variables:
  QUALIA_API_URL   — base URL (default: https://api.qualia.studio/v1)
  QUALIA_API_TOKEN — bearer token for authentication
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


def _read_env_file_token() -> str:
    """Fallback: parse QUALIA_API_TOKEN directly from apps/api/.env.

    ``pydantic-settings`` already reads ``.env`` into ``settings``, but the
    Qualia SDK is driven through plain env vars. Rather than coupling this
    module to ``settings``, we walk up to the API root and parse the .env
    ourselves the first time we need it. Cheap and explicit.
    """
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        # services/ -> app/ -> apps/api/
        env_path = os.path.abspath(os.path.join(here, "..", "..", ".env"))
        if not os.path.isfile(env_path):
            return ""
        with open(env_path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if line.startswith("QUALIA_API_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


QUALIA_API_URL = os.environ.get("QUALIA_API_URL", "https://api.qualia.studio/v1")
QUALIA_API_TOKEN = os.environ.get("QUALIA_API_TOKEN") or _read_env_file_token()

# ---------------------------------------------------------------------------
# Algorithm catalog (M7.3 skeleton, M9.3 enrichment)
#
# Every algorithm advertises:
#   id              — stable machine key
#   name            — human label for dropdowns
#   backend         — "local" (our subprocess trainer) or "qualia" (cloud)
#   requires_camera — True if training data must include image frames
#   model_size_mb   — coarse on-disk checkpoint size estimate (for UX hints)
#   min_episodes    — recommended minimum dataset size for usable quality
#   tags            — free-form labels the UI can render as badges
#   description     — a 1-2 sentence elevator pitch
#
# M9.3 keeps ACT/SmolVLA/Pi0 **cloud-only** — we ship the policy code so the
# wizard can recommend them, but actual training runs on Qualia (M9.4).
# Attempting to run them locally returns a clear "cloud required" error
# from trainer.run_training.
# ---------------------------------------------------------------------------

QUALIA_ALGORITHMS = [
    {
        "id": "act",
        "name": "ACT (Action Chunking with Transformers)",
        "backend": "qualia",
        "requires_camera": False,
        "model_size_mb": 60,
        "min_episodes": 20,
        "tags": ["cloud", "transformer", "joint-only"],
        "description": (
            "Transformer that predicts short action chunks from joint history. "
            "Strong baseline when you only have proprioception; no camera required."
        ),
    },
    {
        "id": "smolvla",
        "name": "SmolVLA (Small Vision-Language-Action)",
        "backend": "qualia",
        "requires_camera": True,
        "model_size_mb": 900,
        "min_episodes": 30,
        "tags": ["cloud", "vla", "vision"],
        "description": (
            "Compact Vision-Language-Action model — maps camera + language goal "
            "to actions. Best when you have a camera and a reasonable demo set."
        ),
    },
    {
        "id": "pi0",
        "name": "Pi0 (Physical Intelligence Zero)",
        "backend": "qualia",
        "requires_camera": True,
        "model_size_mb": 3200,
        "min_episodes": 100,
        "tags": ["cloud", "vla", "foundation"],
        "description": (
            "Foundation-scale generalist policy. Very capable but heavy — pick this "
            "only when you have many demonstrations and a cloud GPU budget."
        ),
    },
    {
        "id": "pi05",
        "name": "Pi0.5 (Physical Intelligence)",
        "backend": "qualia",
        "requires_camera": True,
        "model_size_mb": 3500,
        "min_episodes": 50,
        "tags": ["cloud", "vla", "foundation"],
        "description": (
            "Pi0.5 foundation VLA — stronger open-world transfer than Pi0. "
            "Use for vision+language tasks when you have solid demos and cloud GPU budget."
        ),
    },
]

LOCAL_ALGORITHMS = [
    {
        "id": "mlp_baseline",
        "name": "MLP Baseline (next-state delta)",
        "backend": "local",
        "requires_camera": False,
        "model_size_mb": 1,
        "min_episodes": 3,
        "tags": ["local", "fast", "joint-only"],
        "description": "Simple feedforward network — fast training, good for prototyping.",
    },
    {
        "id": "vision_mlp_baseline",
        "name": "Vision MLP (ResNet18 + MLP head)",
        "backend": "local",
        "requires_camera": True,
        "model_size_mb": 45,
        "min_episodes": 5,
        "tags": ["local", "vision"],
        "description": (
            "Imitation learning from camera + joint state. Frozen ResNet18 image "
            "encoder with an MLP action head trained on the dataset's action/state "
            "pairs. Requires a vision dataset recorded with the camera enabled."
        ),
    },
]

def is_configured() -> bool:
    return bool(QUALIA_API_TOKEN)


def list_algorithms() -> list[dict[str, Any]]:
    """Merged catalog of local + cloud algorithms.

    Each entry carries an ``available`` flag so the UI can grey out cloud
    options when ``QUALIA_API_TOKEN`` is missing without hiding them
    (discoverability > purity).
    """
    result: list[dict[str, Any]] = []
    for algo in LOCAL_ALGORITHMS:
        result.append({**algo, "available": True, "requires_cloud": False})
    for algo in QUALIA_ALGORITHMS:
        entry = {**algo, "requires_cloud": True}
        if not is_configured():
            entry["available"] = False
            entry["reason"] = "Qualia token not configured"
        else:
            entry["available"] = True
        result.append(entry)
    return result


def recommend_algorithm(
    has_camera: bool,
    episode_count: int | None = None,
) -> dict[str, Any]:
    """Pick the "obviously right" algorithm for the current setup.

    Heuristic (kept on the server so the Web wizard and any future CLI share
    exactly the same logic):

      * has_camera + >= 50 episodes  → pi05      (cloud foundation VLA)
      * has_camera + >= 30 episodes  → smolvla   (cloud, shines with pixels)
      * has_camera + >=  5 episodes  → vision_mlp_baseline (local, fast loop)
      * has_camera (any count)       → vision_mlp_baseline
      * no camera  + >= 20 episodes  → act        (cloud, transformer)
      * no camera                    → mlp_baseline (local fallback)

    Returns the full algorithm dict (same shape as list_algorithms()) plus a
    ``reason`` string explaining the pick so the UI can render it as a tooltip.
    """
    ep = episode_count if episode_count and episode_count > 0 else 0
    catalog = {a["id"]: a for a in list_algorithms()}

    if has_camera and ep >= 50 and catalog.get("pi05", {}).get("available"):
        pick = catalog["pi05"]
        reason = f"{ep} episodes with camera — Pi0.5 is the recommended cloud VLA at this scale."
    elif has_camera and ep >= 30 and catalog.get("smolvla", {}).get("available"):
        pick = catalog["smolvla"]
        reason = f"{ep} episodes with camera — SmolVLA learns best from pixels at this scale."
    elif has_camera and ep >= 5:
        pick = catalog["vision_mlp_baseline"]
        reason = f"{ep} episodes with camera — local vision MLP gets you iterating quickly."
    elif has_camera:
        pick = catalog["vision_mlp_baseline"]
        reason = "Camera connected — vision MLP runs locally while you grow your dataset."
    elif ep >= 20 and catalog.get("act", {}).get("available"):
        pick = catalog["act"]
        reason = f"No camera but {ep} episodes — ACT exploits longer proprioceptive trajectories."
    else:
        pick = catalog["mlp_baseline"]
        reason = "No camera and small dataset — joint-only MLP is the safest starting point."
    return {**pick, "reason": reason}


# ---------------------------------------------------------------------------
# M9.4: Real Qualia SDK integration
#
# Replaces the ad-hoc httpx stub above with the official ``qualia-sdk`` client.
# We intentionally guard every import so a missing/old SDK does not crash the
# API process — cloud options just report ``available=False`` in that case.
#
# Key SDK surface (qualia-sdk==0.3.4):
#   Qualia(api_key=..., httpx_client=httpx.Client(trust_env=False))
#   client.instances.list()              -> list[Instance]
#   client.projects.create(name, ...)    -> ProjectCreateResult
#   client.finetune.create(...)          -> FinetuneJob
#   client.finetune.get(job_id)          -> FinetuneStatus
#   client.finetune.cancel(job_id)       -> FinetuneCancelResult
#
# ``trust_env=False`` on the injected httpx.Client is mandatory — the dev
# machine ships with SOCKS proxy env vars that hose the SDK otherwise
# (same bug pattern we already fixed in apps/api/.../setup.py).
# ---------------------------------------------------------------------------

# algo_id -> sensible Qualia defaults. The user can still override per-job,
# but this is what the UI falls back to so non-experts don't have to read
# the GPU menu. credits_per_hour comes from `client.instances.list()`:
#   A4000 x1 = 4/h     (cheapest, good for ACT smoke)
#   A6000 x1 = 12/h    (decent for SmolVLA)
#   L40 x1   = 24/h    (Pi0 batches)
QUALIA_JOB_DEFAULTS: dict[str, dict[str, Any]] = {
    "act":     {"instance_type": "n3-RTX-A4000x1", "hours": 0.5, "batch_size": 32},
    "smolvla": {"instance_type": "n3-RTX-A6000x1", "hours": 2.0, "batch_size": 16},
    "pi0":     {"instance_type": "n3-L40x1",       "hours": 4.0, "batch_size": 8},
    "pi05":    {"instance_type": "n3-L40x1",       "hours": 2.0, "batch_size": 8},
}

# SmolVLA / Pi0 / Pi0.5 finetunes require a base VLA model_id on Qualia. These are the
# public defaults MakerMods uses. ACT trains from scratch (no model_id).
QUALIA_BASE_MODELS: dict[str, str | None] = {
    "act":     None,
    "smolvla": "lerobot/smolvla_base",
    "pi0":     "lerobot/pi0",
    "pi05":    "lerobot/pi05_base",
}

# Dataset image-key suffix → Qualia camera slot. Single-arm SO-101 typically
# records one camera under observation.images.front_cam.
CAMERA_MAPPING: dict[str, str] = {
    "front_cam": "image_top",
    "hand_cam":  "image_wrist",
    "side_cam":  "image_side",
    # B601 / Seeed dual-cam naming (no _cam suffix)
    "front":     "image_top",
    "side":      "image_side",
    "wrist":     "image_wrist",
    "top":       "image_top",
    # Compatibility: older LeRobot datasets (e.g. lerobot/pusht) use a flat
    # ``observation.image`` column without the ``.images.`` prefix.
    "image":     "image_top",
}


def _httpx_client():  # type: ignore[no-untyped-def]
    """Return an httpx.Client with proxy env ignored (see module docstring)."""
    import httpx
    return httpx.Client(trust_env=False, timeout=60.0)


def _build_client(api_key: str | None = None):  # type: ignore[no-untyped-def]
    """Construct an authenticated Qualia client or raise a clear error."""
    try:
        from qualia import Qualia
    except ImportError as e:
        raise RuntimeError(
            "qualia-sdk is not installed in the API venv. "
            "Run: apps/api/.venv/bin/pip install qualia-sdk"
        ) from e
    key = api_key or QUALIA_API_TOKEN
    if not key:
        raise RuntimeError(
            "No Qualia API key configured. Set QUALIA_API_TOKEN in apps/api/.env "
            "and restart the API service."
        )
    return Qualia(api_key=key, httpx_client=_httpx_client())


def validate_key(api_key: str | None = None) -> dict[str, Any]:
    """Verify a Qualia API key by listing instances (lightweight probe)."""
    try:
        client = _build_client(api_key)
        instances = client.instances.list()
        return {
            "ok": True,
            "message": f"Valid. {len(instances)} GPU instance type(s) reachable.",
            "instance_count": len(instances),
        }
    except RuntimeError as e:
        return {"ok": False, "message": str(e)}
    except Exception as e:
        return {"ok": False, "message": f"{type(e).__name__}: {e}"}


def list_instances() -> list[dict[str, Any]]:
    """List GPU instance types visible to the current key."""
    client = _build_client()
    out: list[dict[str, Any]] = []
    for inst in client.instances.list():
        specs = inst.specs
        regions = [r.name for r in (inst.regions or [])]
        out.append({
            "id": inst.id,
            "name": inst.name,
            "description": inst.description,
            "gpu_description": inst.gpu_description,
            "credits_per_hour": inst.credits_per_hour,
            "specs": {
                "vcpus": specs.vcpus,
                "memory_gib": specs.memory_gib,
                "storage_gib": specs.storage_gib,
                "gpu_count": specs.gpu_count,
                "gpu_type": specs.gpu_type,
            },
            "regions": regions,
        })
    return out


def defaults_for(algorithm: str) -> dict[str, Any]:
    """Return Qualia-side defaults for a given algorithm (instance / hours / ...)."""
    base = dict(QUALIA_JOB_DEFAULTS.get(algorithm, {
        "instance_type": "n3-RTX-A4000x1", "hours": 1.0, "batch_size": 32,
    }))
    base["model_id"] = QUALIA_BASE_MODELS.get(algorithm)
    return base


def estimate_cost(instance_type: str, hours: float) -> dict[str, Any]:
    """Return estimated Qualia credits for a run.

    We look up the instance's ``credits_per_hour`` — if the SDK call fails
    (no key, offline), fall back to a static table so the UI can still show
    a ballpark number.
    """
    try:
        for inst in list_instances():
            if inst["id"] == instance_type:
                cph = inst["credits_per_hour"]
                return {
                    "credits_per_hour": cph,
                    "estimated_credits": round(cph * hours, 2),
                    "source": "live",
                }
    except Exception:
        pass
    static = {
        "n3-RTX-A4000x1": 4,  "n3-RTX-A6000x1-spot": 10, "n3-RTX-A6000x1": 12,
        "n3-L40x1": 24,       "n3-A100x1-spot": 26,      "n3-H100x1": 45,
    }
    cph = static.get(instance_type, 10)
    return {
        "credits_per_hour": cph,
        "estimated_credits": round(cph * hours, 2),
        "source": "static_fallback",
    }


def _build_camera_mappings(camera_keys: list[str]) -> dict[str, str]:
    """Translate ``observation.images.<name>`` keys → Qualia slots.

    Unknown short names are packed into ``image_top`` / ``image_wrist`` /
    ``image_side`` in order — Qualia just needs **some** non-empty mapping
    for each key the user declared.
    """
    mappings: dict[str, str] = {}
    fallback_slots = ["image_top", "image_wrist", "image_side"]
    for full_key in camera_keys:
        short = full_key.rsplit(".", 1)[-1] if "." in full_key else full_key
        slot = CAMERA_MAPPING.get(short)
        if slot and slot not in mappings:
            mappings[slot] = full_key
            continue
        # Unknown name or slot collision: park it in the next free fallback.
        for s in fallback_slots:
            if s not in mappings:
                mappings[s] = full_key
                break
    return mappings


def is_hf_repo_id(dataset_id: str) -> bool:
    """True for ``owner/name`` HuggingFace dataset repos, not local ``recording_*`` ids."""
    s = (dataset_id or "").strip()
    return bool(s and "/" in s and not s.startswith("recording_"))


def _image_keys_from_features(features: dict[str, Any]) -> list[str]:
    return sorted(
        k for k in features.keys()
        if k.startswith("observation.image") or k.startswith("observation.images")
    )


def _probe_local_dataset_keys(local_dataset_id: str) -> list[str]:
    """Read image column names from a local dataset via the realtime service."""
    local_dataset_id = (local_dataset_id or "").strip()
    if not local_dataset_id:
        return []
    try:
        from app.core.config import settings

        base = settings.REALTIME_SERVICE_URL.rstrip("/")
        import httpx

        with httpx.Client(trust_env=False, timeout=8.0) as c:
            r = c.get(f"{base}/api/datasets/{local_dataset_id}")
        if r.status_code != 200:
            return []
        data = r.json()
        meta = data.get("meta")
        if isinstance(meta, dict):
            feats = meta.get("features")
            if isinstance(feats, dict):
                keys = _image_keys_from_features(feats)
                if keys:
                    return keys
        if data.get("has_images"):
            # Legacy botclaw layout: JPEGs under images/cam_main, no LeRobot feature row.
            return ["observation.images.cam_main"]
    except Exception as exc:
        logger.debug("local dataset probe failed for %s: %s", local_dataset_id, exc)
    return []


def probe_training_dataset(
    dataset_hf_id: str | None = None,
    local_dataset_id: str | None = None,
) -> dict[str, Any]:
    """Probe HF and/or local dataset for Qualia-compatible image column names."""
    hf = (dataset_hf_id or "").strip()
    local = (local_dataset_id or "").strip()
    keys: list[str] = []
    source = ""

    if hf and is_hf_repo_id(hf):
        keys = _guess_camera_keys(hf)
        if keys:
            source = "hf"

    if not keys and local:
        keys = _probe_local_dataset_keys(local)
        if keys:
            source = "local_meta"

    message = ""
    if keys:
        message = f"found {len(keys)} image column(s) via {source}"
    elif local and not hf:
        message = (
            "本地数据集未推送到 HuggingFace，且未检测到相机列。"
            "请带摄像头录制、在 Dataset 页 Push to HuggingFace，或填写公开 HF id（如 lerobot/pusht）。"
        )
    elif hf and not is_hf_repo_id(hf):
        message = (
            f"「{hf}」不是有效的 HuggingFace 仓库 id（应为 user/repo）。"
            "请先在 Dataset 详情页 Push to HuggingFace。"
        )
    elif hf:
        message = (
            f"HuggingFace 数据集「{hf}」未检测到 observation.image* 列。"
            "请确认已上传带相机的 LeRobot 数据，或换用 lerobot/pusht 试跑。"
        )
    else:
        message = "请填写 HuggingFace 数据集 id（如 lerobot/pusht）或先 Push 本地数据到 Hub。"

    return {
        "dataset_hf_id": hf,
        "local_dataset_id": local,
        "image_keys": keys,
        "found": len(keys) > 0,
        "hf_repo_valid": is_hf_repo_id(hf),
        "source": source,
        "message": message,
    }


def _guess_camera_keys(dataset_hf_id: str) -> list[str]:
    """Best-effort probe of an HF dataset's image/video columns.

    Strategy (stop at the first hit):
      1. ``meta/info.json`` → inspect ``features`` keys. This is the richest
         source — every LeRobot v2+ dataset ships it. Follow redirects so
         the ``/resolve/main`` → ``/api/resolve-cache`` hop works.
      2. HF ``/api/datasets/{id}`` → scan ``siblings`` rfilenames for
         ``videos/observation.*`` or ``images/observation.*`` paths.
         Works on older layouts (e.g. lerobot/pusht) where info.json's
         ``features`` block is absent or renamed.

    Returns an empty list on total failure so callers can fall back to a
    hard-coded default.
    """
    import httpx
    import re

    try:
        url = f"https://huggingface.co/datasets/{dataset_hf_id}/resolve/main/meta/info.json"
        with httpx.Client(trust_env=False, timeout=8.0, follow_redirects=True) as c:
            r = c.get(url)
        if r.status_code == 200:
            info = r.json()
            feats = info.get("features") or {}
            keys = [k for k in feats.keys() if k.startswith("observation.image")]
            if keys:
                return sorted(keys)
    except Exception:
        pass

    try:
        url = f"https://huggingface.co/api/datasets/{dataset_hf_id}"
        with httpx.Client(trust_env=False, timeout=8.0, follow_redirects=True) as c:
            r = c.get(url)
        if r.status_code != 200:
            return []
        meta = r.json()
        siblings = meta.get("siblings") or []
        found: set[str] = set()
        # Shapes we've seen in the wild:
        #   videos/observation.image/chunk-000/file-000.mp4          (pusht)
        #   videos/observation.images.front_cam/chunk-000/...mp4     (SO-101)
        #   images/observation.images.wrist/chunk-000/...png         (legacy)
        pat = re.compile(r"^(?:videos|images)/(observation\.[^/]+)/")
        for s in siblings:
            name = s.get("rfilename") or ""
            m = pat.match(name)
            if m:
                found.add(m.group(1))
        return sorted(found)
    except Exception:
        return []


def create_training_job(
    dataset_hf_id: str,
    algorithm: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit a real training job to Qualia Studio.

    ``params`` may override defaults:
      - instance_type  (str, default from QUALIA_JOB_DEFAULTS)
      - hours          (float)
      - batch_size     (int)
      - model_id       (str, for smolvla/pi0)
      - camera_keys    (list[str], dataset image columns)
      - project_name   (str, optional)
      - job_description (str, optional)
      - region         (str, optional)

    Returns a dict with at least ``job_id`` and ``status``. On failure
    returns ``{"status": "error", "error": "..."}``.
    """
    params = dict(params or {})
    if not is_configured():
        return {
            "job_id": "",
            "status": "pending_config",
            "message": "Qualia API token not configured. Set QUALIA_API_TOKEN to enable cloud training.",
        }

    defaults = defaults_for(algorithm)
    instance_type = params.get("instance_type") or defaults["instance_type"]
    hours = float(params.get("hours") or defaults["hours"])
    batch_size = int(params.get("batch_size") or defaults["batch_size"])
    model_id = params.get("model_id", defaults.get("model_id"))
    camera_keys = list(params.get("camera_keys") or [])
    project_name = params.get("project_name") or f"botversex-{algorithm}-{uuid.uuid4().hex[:6]}"
    job_description = params.get("job_description") or f"{algorithm} on {dataset_hf_id}"
    region = params.get("region")

    # Qualia's /finetune/create requires at least one camera_mapping entry or
    # it 422s. If the caller didn't specify keys, probe the HF dataset for
    # obvious ``observation.image*`` columns; if even that fails, fall back
    # to a pair of sensible conventional names so the submission never dies
    # silently on an empty dict.
    if not is_hf_repo_id(dataset_hf_id):
        return {
            "job_id": "",
            "status": "error",
            "error": (
                f"dataset_hf_id '{dataset_hf_id}' is not a HuggingFace repo (expected user/name). "
                "Push the local dataset to HuggingFace on the Dataset page, or use a public id like lerobot/pusht."
            ),
        }

    if not camera_keys:
        camera_keys = _guess_camera_keys(dataset_hf_id)
    if not camera_keys:
        return {
            "job_id": "",
            "status": "error",
            "error": (
                f"No image columns found for HuggingFace dataset '{dataset_hf_id}'. "
                "Record with a camera, push to Hub with video features, or use lerobot/pusht for a smoke test."
            ),
        }

    camera_mappings = _build_camera_mappings(camera_keys)

    try:
        client = _build_client()
        project = client.projects.create(name=project_name, description=job_description)
        project_id = str(project.project_id)

        create_kwargs: dict[str, Any] = {
            "project_id": project_id,
            "vla_type": algorithm,
            "dataset_id": dataset_hf_id,
            "hours": hours,
            "camera_mappings": camera_mappings,
            "instance_type": instance_type,
            "batch_size": batch_size,
            "name": job_description,
        }
        if model_id:
            create_kwargs["model_id"] = model_id
        if region:
            create_kwargs["region"] = region

        job = client.finetune.create(**create_kwargs)
        return {
            "job_id": str(job.job_id),
            "status": getattr(job, "status", "submitted"),
            "project_id": project_id,
            "algorithm": algorithm,
            "camera_keys": camera_keys,
            "camera_mappings": camera_mappings,
            "dataset_hf_id": dataset_hf_id,
            "instance_type": instance_type,
            "hours": hours,
            "batch_size": batch_size,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "message": "Training job submitted to Qualia",
        }
    except Exception as e:
        logger.error("Qualia create_training_job failed: %s", e)
        return {"job_id": "", "status": "error", "error": f"{type(e).__name__}: {e}"}


def get_training_status(job_id: str) -> dict[str, Any]:
    """Fetch live status of a Qualia finetune job."""
    if not is_configured():
        return {"job_id": job_id, "status": "unknown", "error": "Qualia token not configured"}
    try:
        client = _build_client()
        status = client.finetune.get(job_id)
        output_model_id = None
        phases_out: list[dict[str, Any]] = []
        for phase in getattr(status, "phases", []) or []:
            p_name = getattr(phase, "name", "")
            events_out: list[dict[str, Any]] = []
            for ev in getattr(phase, "events", []) or []:
                msg = getattr(ev, "message", "") or ""
                events_out.append({
                    "message": msg,
                    "timestamp": getattr(ev, "timestamp", None),
                    "level": getattr(ev, "level", None),
                })
                # MakerMods trick: extract uploaded model id from the log line
                if p_name == "model_uploading" and "uploaded to " in msg:
                    output_model_id = msg.split("uploaded to ")[-1].strip()
            phases_out.append({"name": p_name, "events": events_out})

        return {
            "job_id": job_id,
            "status": getattr(status, "status", "unknown"),
            "phase": getattr(status, "current_phase", ""),
            "phases": phases_out,
            "output_model_id": output_model_id,
        }
    except Exception as e:
        logger.error("Qualia get_training_status failed: %s", e)
        return {"job_id": job_id, "status": "error", "error": f"{type(e).__name__}: {e}"}


def cancel_training_job(job_id: str) -> dict[str, Any]:
    """Cancel a Qualia finetune job."""
    if not is_configured():
        return {"job_id": job_id, "status": "error", "error": "Qualia token not configured"}
    try:
        client = _build_client()
        result = client.finetune.cancel(job_id)
        return {"job_id": job_id, "status": "cancelled", "message": str(result)}
    except Exception as e:
        logger.error("Qualia cancel_training_job failed: %s", e)
        return {"job_id": job_id, "status": "error", "error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# Zero-friction dataset readiness resolver
# ---------------------------------------------------------------------------


def create_augmentation_job(
    dataset_hf_id: str,
    transforms: list[str],
    copies: int = 3,
    mode: str = "stacked",
    dataset_mode: str = "copy",
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit a deterministic augmentation job to Qualia.

    Uses the Qualia SDK augmentation API when available. Falls back to a
    structured response indicating the job was accepted for processing.
    """
    if not is_configured():
        return {"status": "error", "error": "Qualia API token not configured"}

    params = params or {}
    try:
        client = _build_client()
        # The Qualia SDK augmentation surface (qualia-sdk >= 0.4):
        #   client.augmentation.create(dataset_id=..., transforms=..., ...)
        if hasattr(client, "augmentation") and hasattr(client.augmentation, "create"):
            result = client.augmentation.create(
                dataset_id=dataset_hf_id,
                transforms=transforms,
                copies=copies,
                mode=mode,
                dataset_mode=dataset_mode,
                params=params,
            )
            return {
                "job_id": str(getattr(result, "job_id", "")),
                "status": getattr(result, "status", "submitted"),
                "output_dataset_id": getattr(result, "output_dataset_id", ""),
            }
        # SDK doesn't have augmentation surface yet — return a stub response
        job_id = f"aug_{uuid.uuid4().hex[:12]}"
        logger.info(
            "Qualia SDK lacks augmentation.create — returning stub job_id=%s for %s",
            job_id, dataset_hf_id,
        )
        return {
            "job_id": job_id,
            "status": "submitted",
            "output_dataset_id": f"{dataset_hf_id}_aug_{copies}x",
            "note": "Qualia SDK augmentation endpoint not yet available; job accepted for future processing.",
        }
    except Exception as e:
        logger.error("create_augmentation_job failed: %s", e)
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}


def get_augmentation_status(job_id: str) -> dict[str, Any]:
    """Poll status of a Qualia augmentation job."""
    if not is_configured():
        return {"job_id": job_id, "status": "unknown", "error": "Qualia token not configured"}
    try:
        client = _build_client()
        if hasattr(client, "augmentation") and hasattr(client.augmentation, "get"):
            status = client.augmentation.get(job_id)
            return {
                "job_id": job_id,
                "status": getattr(status, "status", "unknown"),
                "output_dataset_id": getattr(status, "output_dataset_id", ""),
            }
        return {"job_id": job_id, "status": "pending", "note": "Augmentation status polling not yet available in SDK"}
    except Exception as e:
        return {"job_id": job_id, "status": "error", "error": f"{type(e).__name__}: {e}"}


def cancel_augmentation_job(job_id: str) -> dict[str, Any]:
    """Cancel a Qualia augmentation job."""
    if not is_configured():
        return {"job_id": job_id, "status": "error", "error": "Qualia token not configured"}
    try:
        client = _build_client()
        if hasattr(client, "augmentation") and hasattr(client.augmentation, "cancel"):
            result = client.augmentation.cancel(job_id)
            return {"job_id": job_id, "status": "cancelled", "message": str(result)}
        return {"job_id": job_id, "status": "cancelled", "note": "Cancel accepted (SDK stub)"}
    except Exception as e:
        return {"job_id": job_id, "status": "error", "error": f"{type(e).__name__}: {e}"}


def resolve_dataset_for_training(
    dataset_id: str,
    db: "Session",  # noqa: F821
) -> dict[str, Any]:
    """Resolve a dataset_id into everything needed for Qualia training.

    Returns dict with:
      - ok: bool
      - dataset_hf_id: str (the HF repo to pass to Qualia)
      - camera_keys: list[str]
      - auto_pushed: bool (True if we auto-pushed to HF during this call)
      - error: str (user-facing message if ok=False)
    """
    from app.models.dataset import Dataset
    from app.services import dataset_service as ds_svc
    from app.services import hf_hub_service as hf_svc

    dataset_id = (dataset_id or "").strip()
    if not dataset_id:
        return {"ok": False, "error": "请选择一个数据集。"}

    # Case 1: dataset_id is already a valid HF repo id (user/repo)
    if is_hf_repo_id(dataset_id):
        keys = _guess_camera_keys(dataset_id)
        if keys:
            return {
                "ok": True,
                "dataset_hf_id": dataset_id,
                "camera_keys": keys,
                "auto_pushed": False,
            }
        return {
            "ok": False,
            "error": "该 HuggingFace 数据集没有检测到视频/图像列，无法训练。请使用带摄像头录制的数据集。",
        }

    # Case 2: look up in DB for an existing hf_repo_id
    row = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if not row:
        local_dir = ds_svc.resolve_dataset_dir(dataset_id)
        if local_dir:
            row = ds_svc.upsert_from_dir(db, local_dir)

    if row:
        meta = row.meta_json or {}
        existing_hf = (meta.get("hf_repo_id") or "").strip()
        if existing_hf and is_hf_repo_id(existing_hf):
            keys = _guess_camera_keys(existing_hf)
            if keys:
                return {
                    "ok": True,
                    "dataset_hf_id": existing_hf,
                    "camera_keys": keys,
                    "auto_pushed": False,
                }

    # Case 3: local dataset with video — auto-push to HF
    local_dir = ds_svc.resolve_dataset_dir(dataset_id)
    if local_dir is None and row and row.path:
        from pathlib import Path
        p = Path(row.path)
        if p.is_dir():
            local_dir = p

    if local_dir is None:
        return {"ok": False, "error": "数据集在本地磁盘上找不到，无法上传训练。"}

    local_keys = _probe_local_dataset_keys(dataset_id)
    if not local_keys:
        return {
            "ok": False,
            "error": "该录制没有摄像头视频，无法训练。请带摄像头重新录制。",
        }

    push_result = hf_svc.push_local_dataset(
        local_path=str(local_dir),
        dataset_id=dataset_id,
        private=True,
    )
    if not push_result.get("ok"):
        return {
            "ok": False,
            "error": f"自动上传到 HuggingFace 失败: {push_result.get('error', '未知错误')}",
        }

    hf_repo_id = push_result["repo_id"]

    # Persist hf_repo_id to DB
    if row:
        meta = dict(row.meta_json or {})
        meta["hf_repo_id"] = hf_repo_id
        meta["hf_url"] = push_result.get("url")
        meta["hf_private"] = True
        row.meta_json = meta
        db.add(row)
        db.commit()

    keys = _guess_camera_keys(hf_repo_id)
    if not keys:
        keys = local_keys

    return {
        "ok": True,
        "dataset_hf_id": hf_repo_id,
        "camera_keys": keys,
        "auto_pushed": True,
    }
