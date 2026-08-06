"""Vision-conditioned inference pipeline (M8.3).

Extends the existing joint-only inference (see `inference.py`) with a live
vision loop that conditions predictions on the most recent camera frame.

Architecture
------------
    USB camera ──► JPEG frame ─┐
                               ├─► VisionJointPolicy ──► joint delta ──► SafetyGate ──► /ws/ui broadcast
    manager.latest_data ───────┘                                                    ├─► forwarded back on the WS client
                                                                                    └─► (optional) real follower via existing sender loop

The policy itself is intentionally simple and device-agnostic so the CPU path
is a real fallback, not a stub:

    ResNet18 (frozen, ImageNet pretrained, fc replaced by Identity)  ──► 512d image feature
    joint_state (6d)                                                  ──► 6d  state feature
    concat -> MLP(518 → hidden → hidden → 6) -> joint delta

This is a "vision ACT-lite" head: same shape as a real ACT/SmolVLA action
head, just without the transformer decoder. It's enough to validate the
whole plumbing end-to-end (camera → policy → safety gate → broadcast) and
exposes the same REST + WS surface that a heavier policy will plug into.

Device selection
----------------
ROCm on gfx1151 currently fails at kernel-launch time even when
`torch.cuda.is_available()` returns True. We treat that advertised CUDA
availability as *untrusted* and verify it with an actual tiny forward pass
(`_try_cuda_forward`). If that raises, we pin the model to CPU and remember
the reason so `/status` can surface it to the UI. When ROCm is fixed later,
the same code flips to GPU with zero changes.

Model format (apps/realtime/models/<key>/)
------------------------------------------
    model.json:
      {
        "model_key": "...",
        "algo": "vision_mlp_baseline",  # or "mlp_baseline" for legacy joint-only
        "checkpoint": "checkpoint.pt",
        "input_dim": 6,  "output_dim": 6,  "hidden": 128,
        "image_feature_dim": 512,
        "prediction_mode": "delta"
      }
    checkpoint.pt:
      {"state_dict": <head weights>, ...}    # image encoder weights come from torchvision

REST
----
    GET  /api/vision_inference/status           → current device, loaded model, probe outcome
    POST /api/vision_inference/load             → body {model_key, prefer_device?}
    POST /api/vision_inference/unload           → drop model from memory
    POST /api/vision_inference/estop            → stop any active session (alias of inference.estop for UX clarity)
    POST /api/vision_inference/bootstrap_stub   → write a demo vision model into models/<...> for testing

WS
--
    /ws/vision_inference?camera_device=0&fps=15&echo=false&robot_id=so101-inference
        sends, per tick:
          {"type": "vision_infer_frame", "frame_index", "latency_ms",
           "joint_state", "pred", "safe_pred", "clamped", "image_feature_l2"}
        if echo=true, safe_pred is also broadcast as a joint_update on the UI bus
        (same shape as compare_ws / teleop), so URDF viewer + follower react
        uniformly regardless of where the command originated.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np
from fastapi import APIRouter, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .pi0_runtime import (
    Pi0Session,
    get_predict_health,
    load_pi0,
    looks_like_hf_repo,
    predict_action as pi0_predict_action,
)
from .safety import NormalizedSafetyGate, SafetyGate
from .websocket import manager


def _make_action_gate() -> SafetyGate:
    """Pick the right safety gate for model-generated joint commands.

    ACT / Pi0 / vision_mlp output lerobot-normalized units (±100 per joint,
    0..100 for gripper). Gating those through the radians SafetyGate used
    to silently clamp every frame to ±3.14 and then rate-limit it to
    ±0.18/tick, which on the UI showed up as "pred is fine but follower
    never moves" — exactly the symptom we saw in the field.

    Default is the normalized gate. Set BOTVERSEX_VISION_GATE_MODE=rad to
    fall back to the legacy radians gate (only useful if the upstream
    pipeline is converting to radians before this point).
    """
    import os

    mode = (os.environ.get("BOTVERSEX_VISION_GATE_MODE") or "normalized").strip().lower()
    if mode == "rad":
        return SafetyGate()
    return NormalizedSafetyGate()

logger = logging.getLogger(__name__)

router = APIRouter()


# --------------------------------------------------------------------------- #
# Device probe
# --------------------------------------------------------------------------- #


@dataclass
class DeviceStatus:
    requested: str                 # "auto" | "cpu" | "cuda"
    resolved: str                  # actual device used ("cpu" or "cuda")
    cuda_advertised: bool          # torch.cuda.is_available()
    cuda_usable: bool              # verified by real forward pass
    probe_error: Optional[str]
    device_name: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "resolved": self.resolved,
            "cuda_advertised": self.cuda_advertised,
            "cuda_usable": self.cuda_usable,
            "probe_error": self.probe_error,
            "device_name": self.device_name,
        }


def _try_cuda_forward() -> tuple[bool, Optional[str]]:
    """Run a tiny matmul on cuda:0 to verify HIP/ROCm kernels actually launch.

    `torch.cuda.is_available()` only checks driver advertisement; on gfx1151
    with ROCm 6.3 userspace it returns True but the first real kernel throws
    a HIP error. This catches that and lets us fall back to CPU gracefully.
    """
    try:
        import torch

        if not torch.cuda.is_available():
            return False, "torch.cuda.is_available() is False"
        x = torch.randn(4, 4, device="cuda")
        y = (x @ x).sum().item()
        _ = float(y)
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _resolve_device(prefer: str = "auto") -> DeviceStatus:
    import torch

    advertised = bool(torch.cuda.is_available())
    usable, err = (False, None)
    name: Optional[str] = None

    if prefer in ("auto", "cuda"):
        usable, err = _try_cuda_forward()

    if prefer == "cpu":
        resolved = "cpu"
    elif prefer == "cuda":
        resolved = "cuda" if usable else "cpu"
    else:  # auto
        resolved = "cuda" if usable else "cpu"

    if resolved == "cuda":
        try:
            name = torch.cuda.get_device_name(0)
        except Exception as exc:
            name = f"cuda:? ({exc})"
    else:
        name = "cpu"

    return DeviceStatus(
        requested=prefer,
        resolved=resolved,
        cuda_advertised=advertised,
        cuda_usable=usable,
        probe_error=err,
        device_name=name,
    )


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #


IMG_SIZE = 224
IMAGE_FEATURE_DIM = 512  # ResNet18 avgpool output


def _build_policy(input_dim: int, output_dim: int, hidden: int, image_feature_dim: int):
    import torch.nn as nn

    return nn.Sequential(
        nn.Linear(image_feature_dim + input_dim, hidden),
        nn.ReLU(),
        nn.Linear(hidden, hidden),
        nn.ReLU(),
        nn.Linear(hidden, output_dim),
    )


def _build_image_encoder():
    """Frozen ResNet18 with fc stripped. Returns an nn.Module mapping (N,3,224,224)→(N,512)."""
    import torch.nn as nn
    from torchvision.models import resnet18

    backbone = resnet18(weights=None)  # weights downloaded lazily if user opts in
    backbone.fc = nn.Identity()
    for p in backbone.parameters():
        p.requires_grad = False
    backbone.eval()
    return backbone


def _preprocess_bgr_jpeg(jpeg_bytes: bytes):
    """Decode JPEG, resize to 224x224, convert to torch float tensor (1,3,H,W) normalized to [0,1]."""
    import torch

    arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("failed to decode JPEG frame")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    rgb = cv2.resize(rgb, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)
    # HWC uint8 → CHW float32 in [0,1]
    tensor = torch.from_numpy(rgb).permute(2, 0, 1).contiguous().float().div_(255.0).unsqueeze(0)
    return tensor


# --------------------------------------------------------------------------- #
# Session state (one global loaded model at a time — keeps memory predictable)
# --------------------------------------------------------------------------- #


@dataclass
class LoadedPolicy:
    model_key: str
    meta: dict[str, Any]
    head: Any                  # nn.Module | None  (None for Pi0)
    encoder: Any               # nn.Module | None  (None for Pi0)
    device: DeviceStatus
    input_dim: int
    output_dim: int
    prediction_mode: str
    loaded_at: float
    kind: str = "vision_mlp"       # "vision_mlp" | "pi0" | "act" | … (HF / sidecar)
    pi0: Optional[Pi0Session] = None
    task_prompt: str = "perform the task"


_state: dict[str, Any] = {
    "policy": None,           # LoadedPolicy | None
    "active_ws": 0,           # concurrent /ws/vision_inference sessions
    "inference_priority": 0,  # 0=free shared, 10=pro, 20=creator (from X-Inference-Priority)
}


def _models_root() -> Path:
    return Path(__file__).resolve().parents[1] / "models"


def _load_meta(model_dir: Path) -> dict[str, Any]:
    p = model_dir / "model.json"
    if not p.exists():
        raise HTTPException(500, f"missing model.json in {model_dir}")
    return json.loads(p.read_text(encoding="utf-8"))


def _load_policy(model_key: str, prefer_device: str = "auto", task_prompt: str = "perform the task") -> LoadedPolicy:
    import torch

    # ---- LeRobot HF (ACT / Pi0 / …) via sidecar ---------------------------
    if looks_like_hf_repo(model_key) and not (_models_root() / model_key).exists():
        dev_status = _resolve_device(prefer_device)
        session = load_pi0(model_key, dev_status.resolved, task_prompt=task_prompt)
        fam = (session.policy_family or "pi0").lower()
        return LoadedPolicy(
            model_key=model_key,
            meta={"algo": fam, "repo_id": model_key, "image_keys": session.image_keys},
            head=None,
            encoder=None,
            device=dev_status,
            input_dim=6,
            output_dim=6,
            prediction_mode="absolute",
            loaded_at=time.time(),
            kind=fam,
            pi0=session,
            task_prompt=task_prompt,
        )

    # ---- Local vision_mlp / mlp branch (existing behaviour) ---------------
    model_dir = _models_root() / model_key
    if not model_dir.exists():
        raise HTTPException(404, f"model '{model_key}' not found at {model_dir}")
    meta = _load_meta(model_dir)

    dev_status = _resolve_device(prefer_device)
    device = dev_status.resolved

    input_dim = int(meta.get("input_dim", 6))
    output_dim = int(meta.get("output_dim", 6))
    image_feature_dim = int(meta.get("image_feature_dim", IMAGE_FEATURE_DIM))
    hidden = int(meta.get("hparams", {}).get("hidden", 128))

    encoder = _build_image_encoder().to(device)
    head = _build_policy(input_dim, output_dim, hidden, image_feature_dim).to(device)

    ckpt_path = model_dir / meta.get("checkpoint", "checkpoint.pt")
    if ckpt_path.exists():
        ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
        state_dict = ckpt.get("state_dict", ckpt)
        try:
            head.load_state_dict(state_dict, strict=False)
        except Exception as exc:
            logger.warning("[vision_inference] head state_dict load failed: %s", exc)
    else:
        logger.warning("[vision_inference] no checkpoint for %s, using random init", model_key)

    head.eval()

    return LoadedPolicy(
        model_key=model_key,
        meta=meta,
        head=head,
        encoder=encoder,
        device=dev_status,
        input_dim=input_dim,
        output_dim=output_dim,
        prediction_mode=str(meta.get("prediction_mode", "delta")),
        loaded_at=time.time(),
    )


# --------------------------------------------------------------------------- #
# REST
# --------------------------------------------------------------------------- #


class LoadRequest(BaseModel):
    model_key: str
    prefer_device: str = "auto"   # "auto" | "cpu" | "cuda"
    task_prompt: str = "perform the task"  # only used by Pi0 / VLA policies


class BootstrapStubRequest(BaseModel):
    model_key: str = "vision_stub_demo"


@router.get("/api/vision_inference/status")
async def vision_status(
    prefer: str = Query("cpu", description="device probe mode for status: cpu|auto|cuda"),
) -> dict[str, Any]:
    p: Optional[LoadedPolicy] = _state.get("policy")
    if prefer not in ("cpu", "auto", "cuda"):
        prefer = "cpu"
    # Keep status endpoint responsive even when ROCm auto-probe can hang.
    dev = _resolve_device(prefer)
    return {
        "loaded": p is not None,
        "model_key": p.model_key if p else None,
        "kind": p.kind if p else None,
        "task_prompt": p.task_prompt if p else None,
        "prediction_mode": p.prediction_mode if p else None,
        "device": (p.device.to_dict() if p else dev.to_dict()),
        "active_ws": _state.get("active_ws", 0),
        "loaded_at": p.loaded_at if p else None,
        "global_estop": bool(manager.estop),
        "estop_reason": manager.estop_reason,
        "pi0_predict_health": get_predict_health(),
        "inference_priority": int(_state.get("inference_priority", 0)),
        "queue_tier": (
            "priority" if int(_state.get("inference_priority", 0)) >= 10 else "shared"
        ),
    }


@router.post("/api/vision_inference/load")
async def vision_load(
    req: LoadRequest,
    x_inference_priority: int | None = Header(default=None, alias="X-Inference-Priority"),
) -> dict[str, Any]:
    if x_inference_priority is not None:
        _state["inference_priority"] = max(0, min(100, int(x_inference_priority)))
    if req.prefer_device not in ("auto", "cpu", "cuda"):
        raise HTTPException(400, f"invalid prefer_device: {req.prefer_device}")
    try:
        policy = _load_policy(req.model_key, req.prefer_device, task_prompt=req.task_prompt)
        _state["policy"] = policy
        return {
            "ok": True,
            "model_key": policy.model_key,
            "kind": policy.kind,
            "device": policy.device.to_dict(),
            "input_dim": policy.input_dim,
            "output_dim": policy.output_dim,
            "prediction_mode": policy.prediction_mode,
            "task_prompt": policy.task_prompt,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[vision_inference] load failed model_key=%s", req.model_key)
        raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc


@router.post("/api/vision_inference/unload")
async def vision_unload() -> dict[str, Any]:
    p = _state.get("policy")
    _state["policy"] = None
    if p is None:
        return {"ok": True, "was_loaded": False}
    # help gc on cuda; harmless on cpu
    try:
        import torch
        if p.device.resolved == "cuda":
            torch.cuda.empty_cache()
    except Exception:
        pass
    return {"ok": True, "was_loaded": True, "model_key": p.model_key}


@router.post("/api/vision_inference/estop")
async def vision_estop() -> dict[str, Any]:
    manager.estop = True
    manager.estop_reason = "vision_inference_estop"
    return {"ok": True, "global_estop": True}


@router.post("/api/vision_inference/bootstrap_stub")
async def bootstrap_stub(req: BootstrapStubRequest) -> dict[str, Any]:
    """Write a minimal vision_mlp_baseline model with random head weights.

    Lets the /status + WS pipeline be smoke-tested without running the full
    training loop first. Not intended to produce useful actions.
    """
    import torch

    model_dir = _models_root() / req.model_key
    model_dir.mkdir(parents=True, exist_ok=True)

    input_dim, output_dim, hidden = 6, 6, 128
    head = _build_policy(input_dim, output_dim, hidden, IMAGE_FEATURE_DIM)
    ckpt = {
        "state_dict": head.state_dict(),
        "input_dim": input_dim,
        "output_dim": output_dim,
        "hidden": hidden,
        "image_feature_dim": IMAGE_FEATURE_DIM,
        "prediction_mode": "delta",
    }
    torch.save(ckpt, model_dir / "checkpoint.pt")
    meta = {
        "model_key": req.model_key,
        "name": req.model_key,
        "algo": "vision_mlp_baseline",
        "dataset_id": None,
        "checkpoint": "checkpoint.pt",
        "input_dim": input_dim,
        "output_dim": output_dim,
        "image_feature_dim": IMAGE_FEATURE_DIM,
        "hparams": {"hidden": hidden},
        "metrics": {"note": "random-init stub for plumbing tests"},
        "prediction_mode": "delta",
    }
    (model_dir / "model.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"ok": True, "model_key": req.model_key, "path": str(model_dir)}


# --------------------------------------------------------------------------- #
# WS
# --------------------------------------------------------------------------- #


def _current_joint_state() -> list[float]:
    d = manager.latest_data
    if d is None:
        return [0.0] * 6
    return [d.j1, d.j2, d.j3, d.j4, d.j5, d.j6]


def _open_camera(device: str, w: int = 640, h: int = 480):
    dev = int(device) if device.isdigit() else device
    cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
    if not cap.isOpened():
        cap = cv2.VideoCapture(dev)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


@router.websocket("/ws/vision_inference")
async def vision_infer_ws(
    websocket: WebSocket,
    camera_device: str = Query("0"),
    fps: float = Query(15.0),
    echo: bool = Query(False, description="broadcast safe_pred on /ws/ui as joint_update"),
    robot_id: str = Query("so101-inference"),
    frame_in_msg: bool = Query(False, description="include downsized JPEG (base64) in each frame msg"),
):
    """Live vision-conditioned inference loop.

    Pulls camera frames from `camera_device` directly, composes with the
    latest teleop joint_state held in the ConnectionManager, runs the
    loaded policy, clamps via SafetyGate, and optionally re-broadcasts the
    safe command on the shared UI bus.
    """
    await websocket.accept()
    _state["active_ws"] = _state.get("active_ws", 0) + 1
    cap = None
    gate = _make_action_gate()

    try:
        policy: Optional[LoadedPolicy] = _state.get("policy")
        if policy is None:
            await websocket.send_json({
                "type": "error",
                "message": "no model loaded, POST /api/vision_inference/load first",
            })
            return

        cap = _open_camera(camera_device)
        if cap is None:
            await websocket.send_json({
                "type": "error",
                "message": f"cannot open camera {camera_device}",
            })
            return

        import torch

        device = policy.device.resolved
        period = 1.0 / max(1.0, float(fps))

        await websocket.send_json({
            "type": "vision_infer_meta",
            "model_key": policy.model_key,
            "device": policy.device.to_dict(),
            "fps": fps,
            "echo": echo,
            "robot_id": robot_id if echo else None,
            "prediction_mode": policy.prediction_mode,
            "image_size": IMG_SIZE,
        })

        frame_index = 0
        last_safe: Optional[dict[str, float]] = None

        while True:
            tick_start = time.time()

            if manager.estop:
                await websocket.send_json({
                    "type": "error",
                    "message": f"global estop set ({manager.estop_reason})",
                })
                return

            ok, bgr = cap.read()
            if not ok or bgr is None:
                await websocket.send_json({"type": "warn", "message": "camera read failed, retrying"})
                await asyncio.sleep(0.05)
                continue

            joint_state = _current_joint_state()

            if policy.pi0 is not None:
                t0 = time.perf_counter()
                try:
                    pred = pi0_predict_action(policy.pi0, bgr, joint_state, policy.task_prompt)
                except Exception as exc:
                    logger.exception("[vision_inference] lerobot hub predict failed")
                    await websocket.send_json({"type": "error", "message": f"lerobot hub predict failed: {exc}"})
                    return
                latency_ms = (time.perf_counter() - t0) * 1000.0
                feat_norm = 0.0  # not meaningful for pi0; keep field shape for UI
            else:
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                rgb = cv2.resize(rgb, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)
                x_img = torch.from_numpy(rgb).permute(2, 0, 1).contiguous().float().div_(255.0).unsqueeze(0).to(device)
                x_state = torch.tensor([joint_state], dtype=torch.float32, device=device)

                t0 = time.perf_counter()
                with torch.no_grad():
                    feat = policy.encoder(x_img)               # (1, 512)
                    inp = torch.cat([feat, x_state], dim=1)    # (1, 512+6)
                    y = policy.head(inp).squeeze(0).tolist()
                latency_ms = (time.perf_counter() - t0) * 1000.0
                feat_norm = float(torch.linalg.norm(feat).item())

                if policy.prediction_mode == "delta":
                    pred = [joint_state[k] + y[k] for k in range(policy.output_dim)]
                else:
                    pred = list(y)

            pred_map = {str(k + 1): pred[k] for k in range(6)}
            gate_result = gate.apply(pred_map)
            safe_map = gate_result.safe_joints
            last_safe = safe_map

            if echo:
                try:
                    await manager.broadcast({
                        "type": "joint_update",
                        "robot_id": robot_id,
                        "timestamp": time.time(),
                        "joints": safe_map,
                        "meta": {
                            # Keep "inference" here so the existing follower
                            # (BotclawFollower, --source-filter=inference by
                            # default) forwards these commands to the real
                            # arm. The original class ("vision_inference") is
                            # preserved in source_class for telemetry.
                            "source": "inference",
                            "source_class": "vision_inference",
                            "model_key": policy.model_key,
                            "frame_index": frame_index,
                            "clamped": gate_result.clamped,
                            "latency_ms": latency_ms,
                            "device": policy.device.resolved,
                        },
                    })
                except Exception as exc:
                    logger.warning("[vision_inference] ui broadcast failed: %s", exc)

            msg: dict[str, Any] = {
                "type": "vision_infer_frame",
                "frame_index": frame_index,
                "latency_ms": latency_ms,
                "joint_state": {str(k + 1): joint_state[k] for k in range(6)},
                "pred": pred_map,
                "safe_pred": safe_map,
                "clamped": gate_result.clamped,
                "gate_fatal": gate_result.fatal,
                "image_feature_l2": feat_norm,
                "device": policy.device.resolved,
            }
            if frame_in_msg:
                _, jpg = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 70])
                msg["frame_jpeg_b64"] = base64.b64encode(bytes(jpg)).decode("ascii")

            try:
                await websocket.send_json(msg)
            except WebSocketDisconnect:
                return

            if gate_result.fatal:
                await websocket.send_json({
                    "type": "error",
                    "message": "safety gate fatal, stopping vision inference",
                })
                return

            frame_index += 1
            delay = (tick_start + period) - time.time()
            if delay > 0:
                await asyncio.sleep(delay)

    except WebSocketDisconnect:
        return
    except HTTPException as e:
        try:
            await websocket.send_json({"type": "error", "message": e.detail})
        except Exception:
            pass
    except Exception as e:
        logger.exception("[vision_inference] ws error")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        _state["active_ws"] = max(0, _state.get("active_ws", 0) - 1)
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
        if echo and last_safe is not None:
            # match compare_ws convention: emit inference-stop so followers release
            try:
                await manager.broadcast({
                    "type": "joint_update",
                    "robot_id": robot_id,
                    "timestamp": time.time(),
                    "joints": {},
                    "meta": {"source": "inference-stop", "model_key": _state.get("policy").model_key if _state.get("policy") else None},
                })
            except Exception:
                pass
        try:
            await websocket.close()
        except Exception:
            pass
