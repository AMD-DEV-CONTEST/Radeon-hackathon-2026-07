"""HuggingFace Hub service (M7.2 + M9.5).

Wraps the `huggingface_hub` Python SDK to search/fetch robot-learning models
and upload datasets. Uses a simple TTL in-memory cache to avoid hammering
the HF API on every page load.

M9.5 adds the "push local dataset to HF" pipeline used by the cloud
training flow: Qualia only accepts HF dataset repos, so every recording
that is going to be trained in the cloud must first be pushed up.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_HF_AVAILABLE = False
try:
    from huggingface_hub import HfApi, ModelInfo  # type: ignore
    _HF_AVAILABLE = True
except ImportError:
    HfApi = None  # type: ignore
    ModelInfo = None  # type: ignore
    logger.warning("huggingface_hub not installed — Hub features will use fallback data")


@dataclass
class _CacheEntry:
    data: Any
    ts: float


_cache: dict[str, _CacheEntry] = {}
_CACHE_TTL_S = 300  # 5 minutes


def _get_cached(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry and (time.time() - entry.ts) < _CACHE_TTL_S:
        return entry.data
    return None


def _set_cached(key: str, data: Any) -> None:
    _cache[key] = _CacheEntry(data=data, ts=time.time())


FALLBACK_MODELS: list[dict[str, Any]] = [
    {
        "repo_id": "lerobot/act_so100_test",
        "author": "lerobot",
        "name": "act_so100_test",
        "description": "ACT policy for SO-100 robot arm — community benchmark",
        "tags": ["robotics", "act", "so100", "joint-control"],
        "downloads": 1200,
        "likes": 45,
        "created_at": "2026-01-15",
        "updated_at": "2026-03-20",
        "size": "85 MB",
        "task_type": "manipulation",
        "robot_type": "so100",
        "compatible_skills": ["so101_generic_teleop"],
    },
    {
        "repo_id": "lerobot/diffusion_pusht",
        "author": "lerobot",
        "name": "diffusion_pusht",
        "description": "Diffusion policy for Push-T benchmark task",
        "tags": ["robotics", "diffusion", "pusht", "benchmark"],
        "downloads": 3400,
        "likes": 128,
        "created_at": "2025-11-01",
        "updated_at": "2026-02-10",
        "size": "220 MB",
        "task_type": "manipulation",
        "robot_type": "universal",
        "compatible_skills": [],
    },
    {
        "repo_id": "huggingface/lerobot",
        "author": "huggingface",
        "name": "lerobot",
        "description": "LeRobot: State-of-the-art robot learning framework by HuggingFace",
        "tags": ["robotics", "lerobot", "framework", "act", "diffusion", "tdmpc"],
        "downloads": 15000,
        "likes": 890,
        "created_at": "2025-06-01",
        "updated_at": "2026-04-01",
        "size": "450 MB",
        "task_type": "multi-task",
        "robot_type": "universal",
        "compatible_skills": ["so101_generic_teleop"],
    },
    {
        "repo_id": "lerobot/act_koch_real",
        "author": "lerobot",
        "name": "act_koch_real",
        "description": "ACT policy trained on real Koch v1.1 robot teleoperation data",
        "tags": ["robotics", "act", "koch", "real-robot"],
        "downloads": 780,
        "likes": 34,
        "created_at": "2026-02-20",
        "updated_at": "2026-04-05",
        "size": "92 MB",
        "task_type": "teleop",
        "robot_type": "koch",
        "compatible_skills": [],
    },
    {
        "repo_id": "cadene/act_aloha_sim_transfer_cube_human",
        "author": "cadene",
        "name": "act_aloha_sim_transfer_cube_human",
        "description": "ACT policy for ALOHA sim — cube transfer task with human demonstration",
        "tags": ["robotics", "act", "aloha", "simulation", "transfer"],
        "downloads": 2200,
        "likes": 67,
        "created_at": "2025-09-15",
        "updated_at": "2026-01-30",
        "size": "156 MB",
        "task_type": "manipulation",
        "robot_type": "aloha",
        "compatible_skills": ["aloha_grasp"],
    },
]


def _model_info_to_dict(info: Any) -> dict[str, Any]:
    """Convert a HfApi ModelInfo object to our standard dict format."""
    model_id: str = getattr(info, "modelId", "") or ""
    tags = list(info.tags or []) if hasattr(info, "tags") else []
    author = getattr(info, "author", None) or (model_id.split("/")[0] if "/" in model_id else "unknown")

    pipeline = getattr(info, "pipeline_tag", None) or ""
    task_type = pipeline if pipeline else "unknown"
    for t in ["manipulation", "teleop", "grasp", "locomotion", "navigation"]:
        if t in tags:
            task_type = t
            break

    robot_type = "universal"
    for r in ["so100", "so101", "koch", "aloha", "reachy"]:
        if any(r in tag for tag in tags):
            robot_type = r
            break

    downloads = getattr(info, "downloads", 0) or 0
    likes = getattr(info, "likes", 0) or 0

    created = str(info.created_at)[:10] if hasattr(info, "created_at") and info.created_at else ""
    last_mod = getattr(info, "last_modified", None) or getattr(info, "lastModified", None)
    updated = str(last_mod)[:10] if last_mod else created

    card_data = getattr(info, "card_data", None)
    description = ""
    if isinstance(card_data, dict):
        description = card_data.get("description", "") or ""
    elif hasattr(card_data, "description"):
        description = getattr(card_data, "description", "") or ""

    return {
        "repo_id": model_id,
        "author": author,
        "name": model_id.split("/")[-1] if model_id else "",
        "description": description,
        "tags": tags[:20],
        "downloads": downloads,
        "likes": likes,
        "created_at": created,
        "updated_at": updated,
        "size": "",
        "task_type": task_type,
        "robot_type": robot_type,
        "compatible_skills": [],
    }


def search_models(
    query: str = "",
    tag: str = "robotics",
    sort: str = "downloads",
    limit: int = 30,
) -> list[dict[str, Any]]:
    cache_key = f"search:{query}:{tag}:{sort}:{limit}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    if not _HF_AVAILABLE:
        logger.info("HF SDK not available, returning fallback models")
        results = FALLBACK_MODELS[:limit]
        _set_cached(cache_key, results)
        return results

    try:
        api = HfApi()
        search_kwargs: dict[str, Any] = {
            "limit": limit,
            "sort": sort if sort in ("downloads", "likes", "lastModified") else "downloads",
        }
        if tag:
            search_kwargs["filter"] = tag
        if query:
            search_kwargs["search"] = query

        models = list(api.list_models(**search_kwargs))
        results = [_model_info_to_dict(m) for m in models]
        _set_cached(cache_key, results)
        return results
    except Exception as e:
        logger.error("HF API search failed: %s", e)
        return FALLBACK_MODELS[:limit]


def get_model_info(repo_id: str) -> dict[str, Any] | None:
    cache_key = f"model:{repo_id}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    if not _HF_AVAILABLE:
        for m in FALLBACK_MODELS:
            if m["repo_id"] == repo_id:
                _set_cached(cache_key, m)
                return m
        return {
            "repo_id": repo_id,
            "author": repo_id.split("/")[0] if "/" in repo_id else "unknown",
            "name": repo_id.split("/")[-1],
            "description": f"Model {repo_id} from HuggingFace",
            "tags": ["robotics"],
            "downloads": 0,
            "likes": 0,
            "created_at": "",
            "updated_at": "",
            "size": "",
            "task_type": "unknown",
            "robot_type": "universal",
            "compatible_skills": [],
        }

    try:
        api = HfApi()
        info = api.model_info(repo_id)
        result = _model_info_to_dict(info)

        readme = ""
        try:
            from huggingface_hub import hf_hub_download
            import tempfile, os
            with tempfile.TemporaryDirectory() as tmp:
                path = hf_hub_download(repo_id=repo_id, filename="README.md", local_dir=tmp)
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    readme = f.read()[:5000]
        except Exception:
            pass

        result["readme"] = readme
        _set_cached(cache_key, result)
        return result
    except Exception as e:
        logger.error("HF API model_info failed for %s: %s", repo_id, e)
        return None


def upload_dataset(local_path: str, repo_id: str, token: str | None = None) -> dict[str, Any]:
    """Upload a local dataset directory to HuggingFace."""
    if not _HF_AVAILABLE:
        return {"success": False, "error": "huggingface_hub not installed"}

    try:
        api = HfApi(token=token)
        api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)
        api.upload_folder(
            folder_path=local_path,
            repo_id=repo_id,
            repo_type="dataset",
        )
        return {
            "success": True,
            "url": f"https://huggingface.co/datasets/{repo_id}",
        }
    except Exception as e:
        logger.error("HF dataset upload failed: %s", e)
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# M9.5 — high-level "push this local dataset to HF" pipeline
#
# Qualia can only train on HF repos, so the onboarding flow hinges on a
# reliable way to take one of our apps/realtime/datasets/recording_... dirs
# and get it onto the Hub. This section wraps ``upload_dataset`` with:
#
#   - token resolution (env var → apps/api/.env fallback, same pattern as
#     qualia_service so the API doesn't need a restart dance to pick up a
#     freshly-saved token)
#   - whoami-based repo naming so users don't have to type their HF org
#   - size guard rails (sync path is for <2 GB only; larger datasets should
#     wait for M9.6's async pipeline)
#   - a small status struct we can surface on the dataset detail page
# ---------------------------------------------------------------------------

# Datasets larger than this should fail fast in the sync path with a clear
# "please wait for async M9.6" message instead of hanging the API for 20min.
_SYNC_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB


def _read_env_file_token() -> str:
    """Parse ``HF_TOKEN`` out of apps/api/.env as a fallback.

    Mirrors the pattern already used by ``qualia_service``: pydantic-settings
    populates ``settings`` from .env, but the HF SDK and our helpers here
    read straight from ``os.environ``, so we need an explicit fallback that
    doesn't require a uvicorn restart.
    """
    try:
        here = Path(__file__).resolve()
        # services/ -> app/ -> apps/api/
        env_path = here.parents[2] / ".env"
        if not env_path.is_file():
            return ""
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("HF_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def get_token() -> str:
    """Return the resolved HF write token, or empty string if unset."""
    return os.environ.get("HF_TOKEN") or _read_env_file_token()


def is_token_configured() -> bool:
    return bool(get_token())


_PROXY_ENV_KEYS = (
    "ALL_PROXY", "all_proxy", "SOCKS_PROXY", "socks_proxy",
    # Leave HTTP/HTTPS_PROXY alone — those are fine for huggingface.co and
    # many of our users need them to reach HF in the first place. The SOCKS
    # variants are the ones that trip httpx's `socksio` ImportError.
)


class _noSocksProxy:
    """Context manager that temporarily strips SOCKS proxy env vars.

    ``huggingface_hub`` newer releases use ``httpx`` under the hood, and
    when ``ALL_PROXY=socks5://...`` is set httpx refuses to proceed unless
    the ``socksio`` extra is installed. We don't want to add a mandatory
    SOCKS dep just to be polite, so we snapshot + unset these vars for the
    duration of each HF call, then restore them. HTTP(S)_PROXY is left
    intact because normal HTTP-proxy setups actually work fine with HF.
    """

    def __enter__(self):
        self._saved = {k: os.environ.pop(k, None) for k in _PROXY_ENV_KEYS}
        return self

    def __exit__(self, *exc):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v


def _whoami(token: str) -> dict[str, Any] | None:
    """Call HF ``/api/whoami-v2`` to discover the username for repo naming."""
    if not _HF_AVAILABLE:
        return None
    try:
        with _noSocksProxy():
            api = HfApi(token=token)
            info = api.whoami()
        # whoami returns either a dict or an object; normalize.
        if isinstance(info, dict):
            return info
        return {"name": getattr(info, "name", "")}
    except Exception as e:
        logger.warning("HF whoami failed: %s", e)
        return None


def validate_token() -> dict[str, Any]:
    """UI-friendly health check for the configured token.

    Returns ``{ok, message, username}`` — ``ok=True`` iff the token is
    present, the SDK is installed, and whoami succeeds.
    """
    token = get_token()
    if not token:
        return {"ok": False, "message": "HF_TOKEN not configured in apps/api/.env"}
    if not _HF_AVAILABLE:
        return {"ok": False, "message": "huggingface_hub not installed in API venv"}
    info = _whoami(token)
    if info is None:
        return {"ok": False, "message": "whoami failed — token may be invalid or expired"}
    return {
        "ok": True,
        "username": info.get("name") or "",
        "message": f"token valid for {info.get('name') or 'unknown user'}",
    }


def _dir_size_bytes(p: Path) -> int:
    total = 0
    try:
        for f in p.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except Exception:
        pass
    return total


def _sanitize_repo_name(name: str) -> str:
    """HF repo names allow [A-Za-z0-9._-]; replace the rest with '-'."""
    import re
    slug = re.sub(r"[^A-Za-z0-9._-]", "-", name).strip("-_.")
    return slug or "dataset"


def push_local_dataset(
    local_path: str,
    dataset_id: str,
    repo_name: str | None = None,
    owner: str | None = None,
    private: bool = True,
) -> dict[str, Any]:
    """Push a local LeRobot dataset directory up to HF Hub (synchronous).

    Args:
      local_path:  absolute path to the dataset folder (the one containing
                   ``meta/info.json`` and ``data/``).
      dataset_id:  business id of the dataset, used as the default repo
                   name suffix.
      repo_name:   optional explicit repo name (no owner prefix). Falls back
                   to ``sanitize(dataset_id)``.
      owner:       optional HF org/user. When ``None`` we use the token's
                   whoami username so the URL becomes ``<you>/<repo>``.
      private:     repo visibility — default private so experimental
                   recordings don't leak.

    Returns ``{ok, repo_id, url, bytes_uploaded, message}``.
    On failure returns ``{ok: False, error: "..."}``.
    """
    if not _HF_AVAILABLE:
        return {"ok": False, "error": "huggingface_hub not installed"}

    token = get_token()
    if not token:
        return {
            "ok": False,
            "error": "HF_TOKEN not configured. Set HF_TOKEN in apps/api/.env",
        }

    p = Path(local_path)
    if not p.is_dir():
        return {"ok": False, "error": f"local_path not a directory: {local_path}"}

    size = _dir_size_bytes(p)
    if size > _SYNC_MAX_BYTES:
        return {
            "ok": False,
            "error": (
                f"dataset is {size / 1e9:.2f} GB — larger than the {_SYNC_MAX_BYTES / 1e9:.0f} GB "
                f"sync limit. Wait for the async push pipeline (M9.6) or split the dataset."
            ),
            "bytes": size,
        }

    # Resolve owner from whoami if not supplied.
    if not owner:
        who = _whoami(token)
        if not who:
            return {"ok": False, "error": "whoami failed — cannot auto-pick HF owner"}
        owner = who.get("name") or ""
        if not owner:
            return {"ok": False, "error": "HF whoami returned no username"}

    # If the caller passed an ``owner/name`` style value (frontend shortcut,
    # or ``dataset_id`` being a HF-style id like ``userresu2026/so101-...``),
    # strip the owner half before sanitizing so we don't end up with a repo
    # called e.g. ``userresu2026-so101-...`` under ``<owner>/``.
    raw_name = (repo_name or dataset_id or "").strip()
    if "/" in raw_name:
        raw_name = raw_name.rsplit("/", 1)[-1]
    name = _sanitize_repo_name(raw_name)
    repo_id = f"{owner}/{name}"

    try:
        with _noSocksProxy():
            api = HfApi(token=token)
            api.create_repo(
                repo_id=repo_id,
                repo_type="dataset",
                private=private,
                exist_ok=True,
            )
            api.upload_folder(
                folder_path=str(p),
                repo_id=repo_id,
                repo_type="dataset",
                commit_message=f"botversex push: {dataset_id}",
            )
        return {
            "ok": True,
            "repo_id": repo_id,
            "url": f"https://huggingface.co/datasets/{repo_id}",
            "bytes_uploaded": size,
            "private": private,
            "message": f"pushed {size / 1e6:.1f} MB to {repo_id}",
        }
    except Exception as e:
        logger.error("HF push_local_dataset failed: %s", e)
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
