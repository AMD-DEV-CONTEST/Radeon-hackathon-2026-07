"""Inference / compare WS (M3.5).

GET /api/inference/models — 列出本地 apps/realtime/models/*/model.json
GET /api/inference/{model_key}/meta — 模型元信息
WS  /ws/compare/{model_key}?dataset_id=&fps=30&loop=false

compare WS 每 tick 发一条:
  {
    "type": "compare_frame",
    "frame_index": i,
    "t_dataset": ts,
    "gt":   {"1".."6": <state[t+1]>},
    "pred": {"1".."6": <state[t] + model(state[t])>},
    "error": {"1".."6": pred - gt},
    "step_rmse": rmse_over_6_joints,
    "latency_ms": forward pass 毫秒
  }
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from .safety import SafetyGate
from .websocket import manager

router = APIRouter()


# 活跃 echo 会话: key = model_key:dataset_id, value = dict with cancel event + gate
_echo_sessions: dict[str, dict] = {}


# ------- paths -------


def _models_root() -> Path:
    # apps/realtime/api/inference.py -> apps/realtime -> models
    return Path(__file__).resolve().parents[1] / "models"


def _datasets_root() -> Path:
    return Path(__file__).resolve().parents[1] / "datasets"


def _find_model(model_key: str) -> Path:
    d = _models_root() / model_key
    if not d.exists():
        raise HTTPException(404, f"model '{model_key}' not found at {d}")
    return d


def _load_meta(model_dir: Path) -> dict[str, Any]:
    p = model_dir / "model.json"
    if not p.exists():
        raise HTTPException(500, f"missing model.json in {model_dir}")
    return json.loads(p.read_text(encoding="utf-8"))


# ------- model cache -------
# 避免每次 ws 都重新 load 文件. key: checkpoint path str.
_model_cache: dict[str, Any] = {}


def _load_torch_model(model_dir: Path, meta: dict[str, Any]):
    import torch
    import torch.nn as nn

    ckpt_path = model_dir / meta.get("checkpoint", "checkpoint.pt")
    key = str(ckpt_path)
    if key in _model_cache:
        return _model_cache[key]

    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    hidden = int(ckpt.get("hidden", 64))
    in_dim = int(ckpt.get("input_dim", 6))
    out_dim = int(ckpt.get("output_dim", 6))
    model = nn.Sequential(
        nn.Linear(in_dim, hidden),
        nn.ReLU(),
        nn.Linear(hidden, hidden),
        nn.ReLU(),
        nn.Linear(hidden, out_dim),
    )
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    _model_cache[key] = (model, ckpt.get("prediction_mode", "delta"))
    return _model_cache[key]


def _load_frames(dataset_id: str) -> list[list[float]]:
    import pyarrow.parquet as pq

    dataset_dir = _datasets_root() / dataset_id
    if not dataset_dir.exists():
        raise HTTPException(404, f"dataset '{dataset_id}' not found")
    parquets = sorted(dataset_dir.rglob("*.parquet"))
    if not parquets:
        raise HTTPException(404, f"no parquet under {dataset_dir}")

    frames: list[list[float]] = []
    for pq_file in parquets:
        df = pq.read_table(pq_file).to_pandas()
        if "observation.state" not in df.columns:
            continue
        for v in df["observation.state"]:
            try:
                arr = [float(x) for x in v][:6]
                if len(arr) == 6:
                    frames.append(arr)
            except Exception:
                continue
    return frames


# ------- REST -------


@router.get("/api/inference/models")
async def list_local_models() -> dict[str, Any]:
    root = _models_root()
    out: list[dict[str, Any]] = []
    if root.exists():
        for d in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not d.is_dir():
                continue
            meta_path = d / "model.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            out.append({
                "model_key": meta.get("model_key", d.name),
                "algo": meta.get("algo"),
                "dataset_id": meta.get("dataset_id"),
                "metrics": meta.get("metrics"),
                "hparams": meta.get("hparams"),
                "path": str(d),
            })
    return {"total": len(out), "items": out, "storage_root": str(root)}


@router.get("/api/inference/{model_key}/meta")
async def model_meta(model_key: str) -> dict[str, Any]:
    d = _find_model(model_key)
    meta = _load_meta(d)
    return {**meta, "path": str(d)}


@router.post("/api/inference/estop")
async def emergency_stop_all() -> dict[str, Any]:
    """M4.4 / M5 紧急停止.

    - 标记每个活跃 compare_ws(echo=true) 的 SafetyGate 为 stopped
      → 下一帧 fatal + 广播冻结值
    - 设置全局 `manager.estop=True`, 让 /ws/robotstate 立即把 safety.estop
      推出去, 真机 follower 一发觉就 disable_torque() — 不依赖 compare_ws
      会话是否活着.
    """
    stopped = 0
    for k, s in list(_echo_sessions.items()):
        gate: SafetyGate = s.get("gate")
        if gate is not None:
            gate.emergency_stop("rest_estop")
            stopped += 1
    manager.estop = True
    manager.estop_reason = "rest_estop"
    return {"stopped_sessions": stopped, "global_estop": True}


@router.post("/api/inference/resume")
async def resume_after_estop() -> dict[str, Any]:
    """M5: 清除全局 estop 标志.

    不重启 realtime 进程也能恢复. 注意: 各 compare_ws 会话的 per-gate
    emergency_stop 是一次性的 (gate 已经 fatal 关闭), resume 只清全局标志,
    下一次新建的 compare_ws 会正常工作.
    """
    prev = manager.estop
    manager.estop = False
    manager.estop_reason = None
    return {"ok": True, "was_stopped": prev}


# ------- WS -------


@router.websocket("/ws/compare/{model_key}")
async def compare_ws(
    websocket: WebSocket,
    model_key: str,
    dataset_id: str = Query(...),
    fps: float = Query(30.0),
    loop: bool = Query(False),
    echo: bool = Query(False, description="M4.4: 若为 true, 把 pred 经安全闸后广播到 /ws/ui 总线"),
    robot_id: str = Query("so101-inference", description="echo 时写进 meta.robot_id, 让 UI 区分真机/推断"),
):
    """Compare 流.

    默认只做"对比可视化": 发 compare_meta + compare_frame + compare_done.

    echo=true 时进入 **M4.4 在线推理回推模式**:
    - 每一帧 pred 走 SafetyGate (限位 + 速率 + NaN) 得到 safe_pred
    - safe_pred 作为 `joint_update` 广播到 manager.ui_connections
      (同样是 6 关节 dict, 只是 meta.source="inference", meta.clamped=[...])
    - 浏览器可在 compare_frame 消息里额外收到 safe_pred + gate 诊断
    - WS 关闭 (前端主动或异常) = 紧急停止, 不再广播新帧
    """
    await websocket.accept()
    try:
        model_dir = _find_model(model_key)
        meta = _load_meta(model_dir)
        frames = _load_frames(dataset_id)
        if len(frames) < 2:
            await websocket.send_json({"type": "error", "message": "dataset too short"})
            return

        import torch

        model, mode = _load_torch_model(model_dir, meta)
        period = 1.0 / max(1.0, float(fps))
        gate = SafetyGate() if echo else None
        session_key = f"{model_key}:{dataset_id}:{id(websocket)}" if echo else None
        if echo and session_key is not None:
            _echo_sessions[session_key] = {"gate": gate, "model_key": model_key, "dataset_id": dataset_id}

        await websocket.send_json({
            "type": "compare_meta",
            "model_key": model_key,
            "dataset_id": dataset_id,
            "frame_count": len(frames) - 1,
            "fps": fps,
            "prediction_mode": mode,
            "echo": echo,
            "robot_id": robot_id if echo else None,
        })

        sum_sq = 0.0
        count = 0

        try:
            while True:
                start = time.time()
                for i in range(len(frames) - 1):
                    state_t = frames[i]
                    state_next = frames[i + 1]

                    x = torch.tensor([state_t], dtype=torch.float32)
                    t0 = time.perf_counter()
                    with torch.no_grad():
                        y = model(x).squeeze(0).tolist()
                    latency_ms = (time.perf_counter() - t0) * 1000.0

                    if mode == "delta":
                        pred = [state_t[k] + y[k] for k in range(6)]
                    else:
                        pred = y

                    gt = state_next
                    err = [pred[k] - gt[k] for k in range(6)]
                    step_rmse = math.sqrt(sum(e * e for e in err) / 6.0)
                    sum_sq += sum(e * e for e in err)
                    count += 6

                    pred_map = {str(k + 1): pred[k] for k in range(6)}
                    gt_map = {str(k + 1): gt[k] for k in range(6)}
                    err_map = {str(k + 1): err[k] for k in range(6)}

                    safe_map: dict[str, float] | None = None
                    clamped: list[str] = []
                    gate_fatal = False
                    if gate is not None:
                        g = gate.apply(pred_map)
                        safe_map = g.safe_joints
                        clamped = g.clamped
                        gate_fatal = g.fatal

                        # 广播 "joint_update" 给 UI 总线, meta.source="inference"
                        # 让其他订阅者 (Teleop URDF viewer, 未来真机 listener) 当正规遥操作帧消费.
                        broadcast_payload = {
                            "type": "joint_update",
                            "robot_id": robot_id,
                            "timestamp": time.time(),
                            "joints": safe_map,
                            "meta": {
                                "source": "inference",
                                "model_key": model_key,
                                "dataset_id": dataset_id,
                                "frame_index": i,
                                "clamped": clamped,
                                "latency_ms": latency_ms,
                            },
                        }
                        try:
                            await manager.broadcast(broadcast_payload)
                        except Exception as exc:
                            # 广播失败不该把本 WS 连带挂掉
                            print(f"[echo] broadcast failed: {exc}")

                    frame_msg: dict[str, Any] = {
                        "type": "compare_frame",
                        "frame_index": i,
                        "gt": gt_map,
                        "pred": pred_map,
                        "error": err_map,
                        "step_rmse": step_rmse,
                        "latency_ms": latency_ms,
                    }
                    if echo:
                        frame_msg["safe_pred"] = safe_map
                        frame_msg["clamped"] = clamped
                        frame_msg["gate_fatal"] = gate_fatal
                    await websocket.send_json(frame_msg)

                    if gate_fatal:
                        await websocket.send_json({
                            "type": "error",
                            "message": "safety gate fatal, stopping echo",
                        })
                        return

                    target = start + (i + 1) * period
                    delay = target - time.time()
                    if delay > 0:
                        await asyncio.sleep(delay)
                if not loop:
                    break
                sum_sq = 0.0
                count = 0

            total_rmse = math.sqrt(sum_sq / max(1, count))
            await websocket.send_json({
                "type": "compare_done",
                "total_rmse": total_rmse,
                "frames": len(frames) - 1,
            })
        except WebSocketDisconnect:
            return
    except HTTPException as e:
        try:
            await websocket.send_json({"type": "error", "message": e.detail})
        except Exception:
            pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        if echo:
            sk = f"{model_key}:{dataset_id}:{id(websocket)}"
            _echo_sessions.pop(sk, None)
            # M5.x: broadcast inference-stop so follower watchdog fires immediately
            # instead of waiting for residual frames to drain.
            try:
                await manager.broadcast({
                    "type": "joint_update",
                    "robot_id": robot_id,
                    "timestamp": time.time(),
                    "joints": {},
                    "meta": {
                        "source": "inference-stop",
                        "model_key": model_key,
                        "dataset_id": dataset_id,
                    },
                })
            except Exception:
                pass
        try:
            await websocket.close()
        except Exception:
            pass
