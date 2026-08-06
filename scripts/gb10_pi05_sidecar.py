#!/usr/bin/env python3
"""Minimal Pi0.5 HTTP sidecar for GB10 (LAN inference).

Proven load path from BotverseX smoke model. Listens on 0.0.0.0:8010 by default.

Endpoints:
  GET  /healthz
  POST /load     {model_key, prefer_device, task_prompt}
  POST /predict  {joint_state[7], images_b64:{front,side}|image_b64, task_prompt?, reset?}
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gb10_pi05_sidecar")

DEFAULT_MODEL = os.environ.get(
    "PI05_MODEL_PATH",
    str(Path.home() / "outputs/pi05_smoke_patched"),
)
DEFAULT_TASK = os.environ.get(
    "PI05_TASK",
    "冰球游戏，将对方击过来的红色圆盘击回去",
)

_lock = threading.Lock()
_state: dict[str, Any] = {"session": None}


class LoadRequest(BaseModel):
    model_key: str = DEFAULT_MODEL
    prefer_device: str = "cuda"
    task_prompt: str = DEFAULT_TASK


class PredictRequest(BaseModel):
    joint_state: list[float]
    image_b64: str | None = None
    images_b64: dict[str, str] = Field(default_factory=dict)
    task_prompt: str | None = None
    reset: bool = False


def _ensure_patched_config(model_dir: Path) -> Path:
    """Strip Qualia-only config keys that older PI05Config rejects."""
    src_cfg = model_dir / "config.json"
    if not src_cfg.exists():
        raise FileNotFoundError(f"missing config.json under {model_dir}")
    cfg = json.loads(src_cfg.read_text())
    drop = {
        "use_relative_actions",
        "relative_exclude_joints",
        "action_feature_names",
        "license",
        "tags",
        "private",
        "repo_id",
        "pretrained_path",
        "push_to_hub",
        "use_amp",
        "use_peft",
    }
    changed = False
    for k in drop:
        if k in cfg:
            cfg.pop(k)
            changed = True
    if changed:
        patched = Path.home() / "outputs/pi05_smoke_patched"
        patched.mkdir(parents=True, exist_ok=True)
        for f in model_dir.iterdir():
            link = patched / f.name
            if f.name == "config.json":
                continue
            if not link.exists():
                try:
                    link.symlink_to(f)
                except FileExistsError:
                    pass
        (patched / "config.json").write_text(json.dumps(cfg, indent=2))
        return patched
    return model_dir


def _decode_jpeg_b64(b64: str, h: int, w: int) -> np.ndarray:
    from PIL import Image

    raw = base64.b64decode(b64, validate=False)
    img = Image.open(io.BytesIO(raw)).convert("RGB").resize((w, h), Image.BILINEAR)
    return np.asarray(img, dtype=np.uint8)  # HWC


def _load(model_key: str, device: str, task_prompt: str) -> dict[str, Any]:
    import torch
    from lerobot.policies.pi05.modeling_pi05 import PI05Policy
    from lerobot.processor import PolicyProcessorPipeline

    path = Path(model_key).expanduser()
    if not path.exists():
        # Hub id — leave to from_pretrained
        load_path = model_key
    else:
        load_path = str(_ensure_patched_config(path))

    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"

    logger.info("loading policy path=%s device=%s", load_path, device)
    t0 = time.time()
    policy = PI05Policy.from_pretrained(load_path)
    policy.to(device)
    policy.eval()
    pre = PolicyProcessorPipeline.from_pretrained(
        load_path, config_filename="policy_preprocessor.json"
    )
    post = None
    try:
        from lerobot.processor.converters import (
            policy_action_to_transition,
            transition_to_policy_action,
        )

        post = PolicyProcessorPipeline.from_pretrained(
            load_path,
            config_filename="policy_postprocessor.json",
            to_transition=policy_action_to_transition,
            to_output=transition_to_policy_action,
        )
    except Exception as exc:
        logger.warning("postprocessor load skipped: %s", exc)

    image_keys = list(getattr(policy.config, "image_features", {}) or {})
    if not image_keys:
        image_keys = ["observation.images.front", "observation.images.side"]
    ih, iw = 224, 224
    feats = getattr(policy.config, "image_features", {}) or {}
    if feats:
        feat = next(iter(feats.values()))
        shape = getattr(feat, "shape", None)
        if shape and len(shape) >= 3:
            ih, iw = int(shape[-2]), int(shape[-1])

    logger.info("loaded_in %.1fs keys=%s", time.time() - t0, image_keys)
    return {
        "policy": policy,
        "preprocessor": pre,
        "postprocessor": post,
        "device": device,
        "model_key": load_path,
        "task_prompt": task_prompt or DEFAULT_TASK,
        "image_keys": image_keys,
        "image_h": ih,
        "image_w": iw,
        "loaded_at": time.time(),
    }


app = FastAPI(title="GB10 Pi0.5 Sidecar", version="0.1")


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    s = _state.get("session")
    return {
        "ok": True,
        "loaded": s is not None,
        "model_key": s["model_key"] if s else None,
        "policy_family": "pi05",
        "device": s["device"] if s else None,
        "image_keys": s["image_keys"] if s else [],
        "image_hw": [s["image_h"], s["image_w"]] if s else None,
        "task_prompt": s["task_prompt"] if s else None,
        "loaded_at": s["loaded_at"] if s else None,
        "pid": os.getpid(),
    }


@app.post("/load")
def load_model(req: LoadRequest) -> dict[str, Any]:
    with _lock:
        try:
            session = _load(req.model_key or DEFAULT_MODEL, req.prefer_device, req.task_prompt)
        except Exception as exc:
            logger.exception("load failed")
            raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc
        _state["session"] = session
        return {
            "ok": True,
            "model_key": session["model_key"],
            "policy_family": "pi05",
            "device": session["device"],
            "image_keys": session["image_keys"],
            "image_hw": [session["image_h"], session["image_w"]],
            "task_prompt": session["task_prompt"],
        }


@app.post("/predict")
def predict(req: PredictRequest) -> dict[str, Any]:
    import torch

    s = _state.get("session")
    if s is None:
        raise HTTPException(409, "no model loaded; POST /load first")
    if len(req.joint_state) < 6:
        raise HTTPException(400, f"joint_state need >=6, got {len(req.joint_state)}")

    h, w = s["image_h"], s["image_w"]
    images: dict[str, np.ndarray] = {}
    if req.images_b64:
        for name, b64 in req.images_b64.items():
            key = name if name.startswith("observation.") else f"observation.images.{name}"
            images[key] = _decode_jpeg_b64(b64, h, w)
    elif req.image_b64:
        arr = _decode_jpeg_b64(req.image_b64, h, w)
        for key in s["image_keys"]:
            images[key] = arr
    else:
        raise HTTPException(400, "image_b64 or images_b64 required")

    # Fill missing cams by duplicating first available
    if images:
        first = next(iter(images.values()))
        for key in s["image_keys"]:
            images.setdefault(key, first)

    state = np.asarray(req.joint_state[:7], dtype=np.float32).reshape(1, -1)
    task = req.task_prompt or s["task_prompt"]
    batch: dict[str, Any] = {
        "observation.state": state,
        "task": [task],
    }
    for key, arr in images.items():
        batch[key] = arr.reshape(1, h, w, 3)  # NHWC uint8 for preprocessor

    with _lock:
        t0 = time.perf_counter()
        try:
            if req.reset:
                reset_fn = getattr(s["policy"], "reset", None)
                if callable(reset_fn):
                    reset_fn()
            proc = s["preprocessor"](batch)
            for k, v in list(proc.items()):
                if not torch.is_tensor(v):
                    continue
                v = v.to(s["device"])
                if "images" in k:
                    if v.ndim == 4 and v.shape[-1] == 3:
                        v = v.permute(0, 3, 1, 2).contiguous()
                    if v.dtype == torch.uint8:
                        v = v.float() / 255.0
                    v = v * 2.0 - 1.0
                proc[k] = v
            with torch.inference_mode():
                action = s["policy"].select_action(proc)
            if isinstance(action, torch.Tensor) and action.dim() >= 2:
                action = action.squeeze(0)
            if s["postprocessor"] is not None:
                try:
                    action = s["postprocessor"](action)
                except Exception as exc:
                    logger.warning("postprocessor failed: %s", exc)
            if hasattr(action, "detach"):
                action = action.detach().cpu().numpy()
            action_np = np.asarray(action).reshape(-1)
            latency_ms = (time.perf_counter() - t0) * 1000.0
        except Exception as exc:
            logger.exception("predict failed")
            raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc

    action_list = [float(x) for x in action_np.tolist()]
    return {
        "action": action_list,
        "latency_ms": latency_ms,
        "device": s["device"],
        "model_key": s["model_key"],
        "policy_family": "pi05",
        "action_dim": len(action_list),
    }


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("PI0_SIDECAR_HOST", "0.0.0.0")
    port = int(os.environ.get("PI0_SIDECAR_PORT", "8010"))
    uvicorn.run(app, host=host, port=port, log_level="info")
