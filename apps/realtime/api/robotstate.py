"""M4.3 RobotState 定时回报 WS.

订阅: GET ws://.../ws/robotstate?hz=2&robot_id=so101-001

每 1/hz 秒推送一个 RobotState 快照 (BotClaw v0.4):
- joints / servo_values     来自 manager.latest_data / last_servo_values
- temperatures_c/currents_a  来自上游 sender 透传 (没有就是 None)
- limits_rad / safety        来自 SafetyGate 常量
- teleop_connected / ui_clients / is_recording / buffer_size  manager 实况
- fps_observed               从最近帧间隔估计

上游 sender 当前 (MVP LeRobotSender) 还没推 temperatures / currents, 所以这些字段会是 None.
M4.1 迁移 sender 进 apps/realtime/sender/ 时一并补上.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from .safety import LIMITS_RAD, MAX_DELTA_RAD
from .websocket import manager

router = APIRouter()


def _build_snapshot(robot_id_default: str) -> dict[str, Any]:
    data = manager.latest_data
    joints: dict[str, float | None]
    if data is not None:
        joints = {
            "1": data.j1, "2": data.j2, "3": data.j3,
            "4": data.j4, "5": data.j5, "6": data.j6,
        }
        ts = data.timestamp
    else:
        joints = {k: None for k in ("1", "2", "3", "4", "5", "6")}
        ts = time.time()

    snapshot: dict[str, Any] = {
        "type": "robot_state",
        "robot_id": manager.last_robot_id or robot_id_default,
        "timestamp": ts,
        "joints": joints,
        "servo_values": manager.last_servo_values,
        "temperatures_c": manager.last_temperatures,
        "currents_a": manager.last_currents,
        "voltages_v": manager.last_voltages,
        "teleop_connected": len(manager.teleop_connections) > 0,
        "ui_clients": len(manager.ui_connections),
        "is_recording": manager.is_recording,
        "buffer_size": len(manager.record_buffer) if manager.is_recording else 0,
        "limits_rad": {k: {"lo": lo, "hi": hi} for k, (lo, hi) in LIMITS_RAD.items()},
        "safety": {
            "estop": bool(getattr(manager, "estop", False)),
            "reason": getattr(manager, "estop_reason", None),
            "clamped": None,
            "max_delta_rad": MAX_DELTA_RAD,
        },
        "fps_observed": manager.fps_observed(),
    }
    return snapshot


@router.websocket("/ws/robotstate")
async def robotstate_ws(
    websocket: WebSocket,
    hz: float = Query(2.0, gt=0.0, le=30.0, description="推送频率, 2Hz 对监控足够"),
    robot_id: str = Query("so101-001"),
):
    await websocket.accept()
    period = 1.0 / hz
    try:
        while True:
            snapshot = _build_snapshot(robot_id)
            try:
                await websocket.send_text(json.dumps(snapshot))
            except Exception:
                return
            await asyncio.sleep(period)
    except WebSocketDisconnect:
        return
    except Exception as e:
        print(f"[ERR] robotstate_ws: {e}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@router.get("/api/robotstate")
async def robotstate_rest(robot_id: str = "so101-001") -> dict[str, Any]:
    """One-shot RobotState snapshot (REST)."""
    return _build_snapshot(robot_id)


@router.get("/api/arms")
async def list_arms() -> dict[str, Any]:
    """M4.2 多臂占位: 列出当前活跃 arm_id (teleop + ui).

    M4 单臂仍返回 [arm_0]. 供 M5+ 多臂面板直接订阅.
    """
    arms: dict[str, dict[str, Any]] = {}
    for client_id, info in manager.clients.items():
        aid = info.get("arm_id", "arm_0")
        a = arms.setdefault(aid, {"arm_id": aid, "teleop": 0, "ui": 0, "clients": []})
        a["clients"].append(client_id)
        if info.get("kind") == "teleop":
            a["teleop"] += 1
        elif info.get("kind") == "ui":
            a["ui"] += 1
    if not arms:
        arms["arm_0"] = {"arm_id": "arm_0", "teleop": 0, "ui": 0, "clients": []}
    return {"total": len(arms), "items": list(arms.values())}
