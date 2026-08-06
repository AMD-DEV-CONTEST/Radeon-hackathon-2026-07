"""LeRobot HF inference sidecar (FastAPI, Python 3.12).

Hosts **ACT**, **Pi0**, and **Pi0.5** checkpoints from Hugging Face Hub in a
venv isolated from ``apps/realtime`` (Python 3.11 + ROCm). Policy type is read
from ``config.json`` (``"type": "act"`` / ``"pi0"`` / ``"pi05"``) and the
correct ``*Policy.from_pretrained`` class is selected.

Design constraints
------------------
- One policy loaded at a time (memory + GPU budget). ``/load`` swaps.
- Stateless ``/predict``: realtime owns camera + joint state + safety gate.
  We map (image, state, optional task prompt) → action vector (6 for SO-101,
  7 for B601 / Pi0.5 finetunes — preserve model output length, pad only if short).
- Pi0 / Pi0.5 batches include a ``task`` string; ACT batches do not.
- Image resize uses the policy config's first image feature shape (e.g. ACT
  often 480×640, Pi0 often 224×224).

Request / response wire format is intentionally simple JSON + base64 so we
do not need a shared pydantic schema between the two venvs.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("pi0_sidecar")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _patch_lerobot_constants() -> None:
    """Work around a lerobot 0.5.2 release bug.

    ``lerobot/utils/__init__.py`` imports ``DEFAULT_FEATURES`` from
    ``lerobot.utils.constants``, but the constant was only declared in
    ``lerobot.datasets.utils`` — so ANY ``import lerobot.<anything>`` dies
    with::

        ImportError: cannot import name 'DEFAULT_FEATURES' from
        'lerobot.utils.constants'

    We preload ``lerobot.utils.constants`` ourselves and graft the missing
    symbol onto it BEFORE anything else touches ``lerobot``. This is the
    same dict that lives in ``lerobot/datasets/utils.py``; if lerobot later
    ships a fix, this patch becomes a no-op.
    """
    import importlib.util
    import sys
    from pathlib import Path

    try:
        import lerobot  # noqa: F401  — locates the installed package
    except Exception as exc:
        logger.warning("lerobot not importable yet: %s", exc)
        return

    try:
        lerobot_root = Path(lerobot.__file__).resolve().parent  # type: ignore[arg-type]
    except TypeError:
        # Namespace package: fall back to the first search path.
        lerobot_root = Path(next(iter(lerobot.__path__))).resolve()
    constants_py = lerobot_root / "utils" / "constants.py"
    if not constants_py.exists():
        logger.warning("lerobot constants.py not found at %s", constants_py)
        return

    default_features = {
        "timestamp": {"dtype": "float32", "shape": (1,), "names": None},
        "frame_index": {"dtype": "int64", "shape": (1,), "names": None},
        "episode_index": {"dtype": "int64", "shape": (1,), "names": None},
        "index": {"dtype": "int64", "shape": (1,), "names": None},
        "task_index": {"dtype": "int64", "shape": (1,), "names": None},
    }

    # Load constants.py as a standalone module WITHOUT going through
    # lerobot.utils/__init__.py (which is the one that blows up).
    spec = importlib.util.spec_from_file_location(
        "lerobot.utils.constants", str(constants_py)
    )
    if spec is None or spec.loader is None:
        logger.warning("could not build spec for %s", constants_py)
        return
    constants_mod = importlib.util.module_from_spec(spec)
    sys.modules["lerobot.utils.constants"] = constants_mod
    try:
        spec.loader.exec_module(constants_mod)
    except Exception as exc:
        logger.warning("failed to exec constants.py standalone: %s", exc)
        return

    patched: list[str] = []
    if not hasattr(constants_mod, "DEFAULT_FEATURES"):
        constants_mod.DEFAULT_FEATURES = default_features
        patched.append("DEFAULT_FEATURES")
    if not hasattr(constants_mod, "IMAGENET_STATS"):
        # Standard torchvision ImageNet normalization — matches what
        # ``lerobot/utils/visualization_utils.py`` expects downstream.
        constants_mod.IMAGENET_STATS = {
            "mean": [0.485, 0.456, 0.406],
            "std": [0.229, 0.224, 0.225],
        }
        patched.append("IMAGENET_STATS")
    if patched:
        logger.info("patched lerobot.utils.constants: %s (0.5.2 bug)", patched)


_patch_lerobot_constants()


def _patch_hf_hub_filename_aliases() -> None:
    """Provide compatibility aliases for model repos with renamed processor files."""
    import huggingface_hub as hfh
    import huggingface_hub.file_download as hfh_file_download

    if getattr(hfh, "_botversex_alias_patch", False):
        return

    original = hfh.hf_hub_download
    aliases = {
        "preprocessor_config.json": "policy_preprocessor.json",
        "postprocessor_config.json": "policy_postprocessor.json",
    }

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        filename = kwargs.get("filename")
        if filename is None and len(args) >= 2:
            filename = args[1]
        try:
            return original(*args, **kwargs)
        except Exception as exc:
            alt = aliases.get(str(filename))
            if alt is None:
                raise
            alt_kwargs = dict(kwargs)
            alt_kwargs["filename"] = alt
            logger.info("hf_hub_download alias retry: %s -> %s", filename, alt)
            return original(*args[:1], **alt_kwargs)

    hfh.hf_hub_download = wrapped  # type: ignore[assignment]
    hfh_file_download.hf_hub_download = wrapped  # type: ignore[assignment]
    hfh._botversex_alias_patch = True  # type: ignore[attr-defined]


_patch_hf_hub_filename_aliases()

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------


@dataclass
class LoadedSession:
    model_key: str
    device: str
    task_prompt: str
    policy_family: str                   # "act" | "pi0" | ...
    policy: Any                            # ACTPolicy | PI0Policy
    preprocessor: Any                      # PolicyProcessorPipeline
    postprocessor: Any                     # PolicyProcessorPipeline
    image_keys: list[str] = field(default_factory=list)
    state_key: str = "observation.state"
    action_key: str = "action"
    image_h: int = 224
    image_w: int = 224
    include_task_in_batch: bool = True
    loaded_at: float = field(default_factory=time.time)


_state: dict[str, Any] = {"session": None}
_load_lock = threading.Lock()
_predict_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _select_device(prefer: str) -> str:
    """Resolve 'cpu' / 'cuda' / 'auto' → concrete device string.

    Keeps parity with apps/realtime/api/vision_inference._try_cuda_forward
    but intentionally does not *require* ROCm — this sidecar is CPU-first.
    """
    prefer = (prefer or "cpu").lower()
    if prefer == "cpu":
        return "cpu"
    try:
        import torch
        if not torch.cuda.is_available():
            return "cpu"
        x = torch.randn(4, 4, device="cuda")
        _ = (x @ x).sum().item()
        return "cuda"
    except Exception as exc:
        logger.warning("cuda probe failed, falling back to cpu: %s", exc)
        return "cpu"


def _infer_image_hw_from_config(policy_cfg: Any) -> tuple[int, int]:
    """Return (H, W) from first image feature shape [C, H, W], else (224, 224)."""
    feats = getattr(policy_cfg, "image_features", None) or {}
    if not feats:
        return 224, 224
    feat = next(iter(feats.values()))
    shape = getattr(feat, "shape", None)
    if shape is None and isinstance(feat, dict):
        shape = feat.get("shape")
    if not shape or len(shape) < 3:
        return 224, 224
    return int(shape[-2]), int(shape[-1])


def _hub_policy_type(model_key: str) -> str:
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(repo_id=model_key, filename="config.json")
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    return str(cfg.get("type", "")).lower()


def _load_processor_pipeline(model_key: str, kind: str) -> Any:
    """Load policy processor with filename compatibility fallback.

    Some exports publish:
    - policy_preprocessor.json / policy_postprocessor.json
    while older paths used:
    - preprocessor_config.json / postprocessor_config.json

    For the postprocessor we also swap ``to_transition``/``to_output`` to the
    action-tensor converters so ``postprocessor(action_tensor)`` works the way
    ``lerobot_eval.py`` uses it — ``from_pretrained`` otherwise hard-codes the
    dict-based ``batch_to_transition`` and would reject a raw Tensor with
    "EnvTransition must be a dictionary. Got Tensor".
    """
    from pathlib import Path

    from huggingface_hub import hf_hub_download
    from lerobot.processor import PolicyProcessorPipeline
    from lerobot.processor.converters import (
        policy_action_to_transition,
        transition_to_policy_action,
    )

    assert kind in ("pre", "post")
    extra_kwargs: dict[str, Any] = {}
    if kind == "post":
        extra_kwargs["to_transition"] = policy_action_to_transition
        extra_kwargs["to_output"] = transition_to_policy_action
    candidates = (
        ["policy_preprocessor.json", "preprocessor_config.json"]
        if kind == "pre"
        else ["policy_postprocessor.json", "postprocessor_config.json"]
    )
    last_exc: Exception | None = None
    for cfg_name in candidates:
        try:
            return PolicyProcessorPipeline.from_pretrained(
                model_key, config_filename=cfg_name, **extra_kwargs
            )
        except Exception as exc:
            last_exc = exc
            logger.info("processor load retry repo=%s kind=%s cfg=%s err=%s", model_key, kind, cfg_name, exc)
            # Some exported processor configs are hard-pinned to "cuda", which
            # breaks on CPU-only hosts. Rewrite that step to CPU and retry from
            # the local snapshot directory.
            msg = str(exc).lower()
            if "device_processor" in msg and "cuda" in msg:
                try:
                    cfg_path = Path(hf_hub_download(repo_id=model_key, filename=cfg_name))
                    snapshot_dir = cfg_path.parent
                    patched_name = cfg_name.replace(".json", "_cpu.json")
                    patched_path = snapshot_dir / patched_name
                    with open(cfg_path, encoding="utf-8") as fh:
                        cfg = json.load(fh)
                    for step in cfg.get("steps", []):
                        if step.get("registry_name") == "device_processor":
                            step_cfg = step.setdefault("config", {})
                            step_cfg["device"] = "cpu"
                    with open(patched_path, "w", encoding="utf-8") as fh:
                        json.dump(cfg, fh, ensure_ascii=True, indent=2)
                    logger.info(
                        "processor cpu patch applied repo=%s kind=%s src=%s patched=%s",
                        model_key,
                        kind,
                        cfg_name,
                        patched_name,
                    )
                    return PolicyProcessorPipeline.from_pretrained(
                        str(snapshot_dir),
                        config_filename=patched_name,
                        local_files_only=True,
                        **extra_kwargs,
                    )
                except Exception as patch_exc:
                    last_exc = patch_exc
                    logger.info(
                        "processor cpu patch retry failed repo=%s kind=%s cfg=%s err=%s",
                        model_key,
                        kind,
                        cfg_name,
                        patch_exc,
                    )
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"processor loader reached unexpected state (repo={model_key}, kind={kind})")


def _load_pi0_family(
    model_key: str,
    device: str,
    task_prompt: str,
    *,
    policy_type: str,
) -> LoadedSession:
    """Materialize PI0 / PI05 policy + pre/post processors from an HF repo id."""
    from lerobot.utils.constants import ACTION, OBS_STATE

    if policy_type == "pi05":
        from lerobot.policies.pi05 import PI05Policy as PolicyCls
        family = "pi05"
    else:
        from lerobot.policies.pi0 import PI0Policy as PolicyCls
        family = "pi0"

    logger.info("loading %s repo=%s device=%s", family, model_key, device)

    policy = PolicyCls.from_pretrained(model_key)
    policy.config.device = device
    policy.to(device)
    policy.eval()

    preprocessor = _load_processor_pipeline(model_key, kind="pre")
    postprocessor = _load_processor_pipeline(model_key, kind="post")

    image_keys = (
        list(policy.config.image_features.keys())
        if getattr(policy.config, "image_features", None)
        else ["observation.images.top"]
    )
    ih, iw = _infer_image_hw_from_config(policy.config)

    return LoadedSession(
        model_key=model_key,
        device=device,
        task_prompt=task_prompt or "perform the task",
        policy_family=family,
        policy=policy,
        preprocessor=preprocessor,
        postprocessor=postprocessor,
        image_keys=image_keys,
        state_key=OBS_STATE,
        action_key=ACTION,
        image_h=ih,
        image_w=iw,
        include_task_in_batch=True,
    )


def _load_pi0(model_key: str, device: str, task_prompt: str) -> LoadedSession:
    """Back-compat wrapper for Pi0 loads."""
    return _load_pi0_family(model_key, device, task_prompt, policy_type="pi0")


def _load_act(model_key: str, device: str, task_prompt: str) -> LoadedSession:
    """Materialize ACTPolicy + pre/post processors from an HF repo id."""
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.utils.constants import ACTION, OBS_STATE

    logger.info("loading ACT repo=%s device=%s", model_key, device)

    policy = ACTPolicy.from_pretrained(model_key)
    policy.config.device = device
    policy.to(device)
    policy.eval()

    preprocessor = _load_processor_pipeline(model_key, kind="pre")
    postprocessor = _load_processor_pipeline(model_key, kind="post")

    image_keys = (
        list(policy.config.image_features.keys())
        if getattr(policy.config, "image_features", None)
        else ["observation.images.top"]
    )
    ih, iw = _infer_image_hw_from_config(policy.config)

    return LoadedSession(
        model_key=model_key,
        device=device,
        task_prompt=task_prompt or "perform the task",
        policy_family="act",
        policy=policy,
        preprocessor=preprocessor,
        postprocessor=postprocessor,
        image_keys=image_keys,
        state_key=OBS_STATE,
        action_key=ACTION,
        image_h=ih,
        image_w=iw,
        include_task_in_batch=False,
    )


def _load_policy_auto(model_key: str, device: str, task_prompt: str) -> LoadedSession:
    ptype = _hub_policy_type(model_key)
    if ptype == "act":
        return _load_act(model_key, device, task_prompt)
    if ptype == "pi05":
        return _load_pi0_family(model_key, device, task_prompt, policy_type="pi05")
    if ptype in ("pi0", "pi0_fast"):
        return _load_pi0_family(model_key, device, task_prompt, policy_type="pi0")
    raise ValueError(
        f"unsupported HuggingFace policy type {ptype!r} in config.json "
        f"(repo={model_key}); extend apps/pi0_sidecar/server.py"
    )


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------


def _decode_image_b64(b64_bytes: str, height: int, width: int) -> np.ndarray:
    """Base64-encoded JPEG/PNG → float32 CHW in [0, 1], RGB, resized to (H, W)."""
    if not b64_bytes:
        raise HTTPException(400, "image_b64 is required")
    try:
        raw = base64.b64decode(b64_bytes, validate=False)
    except Exception as exc:
        raise HTTPException(400, f"image_b64 not valid base64: {exc}") from exc

    from PIL import Image

    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB").resize(
            (int(width), int(height)), Image.BILINEAR
        )
    except Exception as exc:
        raise HTTPException(400, f"could not decode image: {exc}") from exc

    arr = np.asarray(img, dtype=np.float32) / 255.0
    return np.transpose(arr, (2, 0, 1))  # CHW


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------


class LoadRequest(BaseModel):
    model_key: str
    prefer_device: str = "cpu"
    task_prompt: str = "perform the task"


class PredictRequest(BaseModel):
    joint_state: list[float]
    image_b64: str
    task_prompt: str | None = None
    reset: bool = False  # ACT/Pi0 keep an internal action chunk queue; set
                         # True to force a fresh forward pass every frame.


app = FastAPI(title="BotverseX LeRobot HF Sidecar", version="1.0")


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    s: LoadedSession | None = _state.get("session")
    return {
        "ok": True,
        "loaded": s is not None,
        "model_key": s.model_key if s else None,
        "policy_family": s.policy_family if s else None,
        "device": s.device if s else None,
        "image_keys": s.image_keys if s else [],
        "image_hw": [s.image_h, s.image_w] if s else None,
        "task_prompt": s.task_prompt if s else None,
        "loaded_at": s.loaded_at if s else None,
        "pid": os.getpid(),
    }


@app.post("/load")
def load_model(req: LoadRequest) -> dict[str, Any]:
    with _load_lock:
        try:
            device = _select_device(req.prefer_device)
            session = _load_policy_auto(req.model_key, device, req.task_prompt)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("load failed")
            raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc

        # Release the previous policy explicitly so we don't double-allocate.
        prev = _state.get("session")
        _state["session"] = session
        if prev is not None:
            try:
                del prev
                import gc
                gc.collect()
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

        return {
            "ok": True,
            "model_key": session.model_key,
            "policy_family": session.policy_family,
            "device": session.device,
            "image_keys": session.image_keys,
            "image_hw": [session.image_h, session.image_w],
            "task_prompt": session.task_prompt,
        }


@app.post("/unload")
def unload_model() -> dict[str, Any]:
    s = _state.get("session")
    _state["session"] = None
    return {"ok": True, "was_loaded": s is not None}


@app.post("/predict")
def predict(req: PredictRequest) -> dict[str, Any]:
    s: LoadedSession | None = _state.get("session")
    if s is None:
        raise HTTPException(409, "no model loaded; POST /load first")

    if len(req.joint_state) < 6:
        raise HTTPException(
            400, f"joint_state must have >=6 floats (got {len(req.joint_state)})"
        )

    import torch

    img_chw = _decode_image_b64(req.image_b64, s.image_h, s.image_w)
    img_tensor = torch.from_numpy(img_chw)  # (3, H, W)

    state_tensor = torch.tensor(list(req.joint_state), dtype=torch.float32)  # (D,)

    batch: dict[str, Any] = {s.state_key: state_tensor}
    if s.include_task_in_batch:
        batch["task"] = req.task_prompt or s.task_prompt
    for key in s.image_keys:
        batch[key] = img_tensor

    with _predict_lock:
        try:
            t0 = time.perf_counter()
            batch = s.preprocessor(batch)
            # Policies expect a leading batch dim; preprocessor doesn't add one
            # when called outside a DataLoader, so we add it here for tensor
            # fields only (leave "task" strings alone).
            for k, v in list(batch.items()):
                if isinstance(v, torch.Tensor) and v.dim() >= 1 and k != "task":
                    if (k.startswith("observation.images") and v.dim() == 3) or \
                       (k == s.state_key and v.dim() == 1):
                        batch[k] = v.unsqueeze(0)
            # ACT/Pi0 keep an internal action chunk queue; only reset when
            # the client asks (e.g. right after loading a new episode).
            if req.reset:
                reset_fn = getattr(s.policy, "reset", None)
                if callable(reset_fn):
                    try:
                        reset_fn()
                    except Exception:
                        pass
            with torch.no_grad():
                action = s.policy.select_action(batch)
            if isinstance(action, torch.Tensor) and action.dim() >= 2:
                action = action.squeeze(0)
            action = s.postprocessor(action)
            if hasattr(action, "detach"):
                action = action.detach().cpu().numpy()
            action_np = np.asarray(action).reshape(-1)
            latency_ms = (time.perf_counter() - t0) * 1000.0
        except Exception as exc:
            logger.exception("predict failed")
            raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc

    action_list = [float(x) for x in action_np.tolist()]
    # Preserve full DoF (B601=7, SO-101=6). Only pad if the policy returned
    # fewer than 6 dims; never truncate a longer vector.
    if len(action_list) < 6:
        action_list = action_list + [0.0] * (6 - len(action_list))

    return {
        "action": action_list,
        "latency_ms": latency_ms,
        "device": s.device,
        "model_key": s.model_key,
        "policy_family": s.policy_family,
        "action_dim": len(action_list),
    }
