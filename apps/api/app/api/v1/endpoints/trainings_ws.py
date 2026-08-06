"""Training job 进度 WebSocket (M3.3).

每 0.5s 从 DB 读一遍 TrainingJob 推一帧. job 终态(成功/失败/取消)即关流.

消息体:
  {"type": "job_update", "id", "status", "progress_pct", "epoch", "total_epochs", "loss", "error_msg"}
  {"type": "job_done",   "id", "status", "model_id"}
  {"type": "error",      "message"}

为了开发简单, 此 WS 不强制 token (同 /ws/playback); 生产部署可在 gateway 做保护.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.models.database import SessionLocal
from app.models.training import TrainingJob
from app.services.training_service import job_to_dict

router = APIRouter()


TERMINAL = {"succeeded", "failed", "cancelled"}


@router.websocket("/ws/trainings/{job_id}")
async def training_progress_ws(websocket: WebSocket, job_id: str):
    await websocket.accept()
    try:
        last_snapshot: dict | None = None
        while True:
            db = SessionLocal()
            try:
                row = db.query(TrainingJob).filter(TrainingJob.id == job_id).first()
            finally:
                db.close()

            if row is None:
                await websocket.send_json({"type": "error", "message": f"job {job_id} not found"})
                break

            snap = job_to_dict(row)
            # 只在关键字段变化时推
            relevant = {k: snap[k] for k in ("status", "progress_pct", "epoch", "loss", "error_msg")}
            if relevant != last_snapshot:
                await websocket.send_json({"type": "job_update", **snap})
                last_snapshot = relevant

            if snap["status"] in TERMINAL:
                await websocket.send_json({
                    "type": "job_done",
                    "id": snap["id"],
                    "status": snap["status"],
                    "model_id": snap.get("model_id"),
                })
                break

            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
