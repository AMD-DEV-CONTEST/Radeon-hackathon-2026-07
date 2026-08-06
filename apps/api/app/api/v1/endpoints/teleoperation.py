"""
遥操作API
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Literal
from datetime import datetime
from sqlalchemy.orm import Session
import uuid

from app.api.v1.endpoints.auth import get_current_user
from app.api.deps import get_db
from app.models.user import User

router = APIRouter()

# 内存中的会话存储（生产环境应使用Redis）
active_sessions = {}


class TeleoperationStartRequest(BaseModel):
    """启动遥操作请求"""
    mode: Literal["leader_follower", "keyboard", "vr"] = "leader_follower"
    robot_id: str


class TeleoperationStatusResponse(BaseModel):
    """遥操作状态响应"""
    session_id: str
    robot_id: str
    mode: str
    status: Literal["idle", "running", "paused", "stopped"]
    started_at: datetime | None
    control_frequency: int  # Hz


@router.post("/sessions", response_model=TeleoperationStatusResponse)
async def start_teleoperation(
    request: TeleoperationStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    启动遥操作会话

    需要权限: robot:control
    """
    # 检查权限 (兼容 permissions 既可能是 list 也可能是 dict 的历史存储)
    perms = current_user.permissions
    if isinstance(perms, dict):
        perms = perms.get("permissions", [])
    if "robot:control" not in (perms or []):
        raise HTTPException(status_code=403, detail="没有机器人控制权限")

    # 检查是否已有活跃会话
    for session_id, session in active_sessions.items():
        if session["robot_id"] == request.robot_id and session["status"] == "running":
            raise HTTPException(
                status_code=400,
                detail=f"机器人 {request.robot_id} 已在使用中"
            )

    # 创建遥操作会话
    session_id = str(uuid.uuid4())
    session_data = {
        "session_id": session_id,
        "robot_id": request.robot_id,
        "mode": request.mode,
        "status": "running",
        "started_at": datetime.utcnow(),
        "control_frequency": 200,
        "user_id": current_user.id,
    }
    active_sessions[session_id] = session_data

    # TODO: 启动实时控制层（C++/Rust服务）
    # TODO: 记录审计日志

    return TeleoperationStatusResponse(
        session_id=session_id,
        robot_id=request.robot_id,
        mode=request.mode,
        status="running",
        started_at=session_data["started_at"],
        control_frequency=200,
    )


@router.get("/sessions/{session_id}", response_model=TeleoperationStatusResponse)
async def get_teleoperation_status(
    session_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    获取遥操作会话状态
    """
    session = active_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 检查权限
    if session["user_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此会话")

    return TeleoperationStatusResponse(
        session_id=session["session_id"],
        robot_id=session["robot_id"],
        mode=session["mode"],
        status=session["status"],
        started_at=session["started_at"],
        control_frequency=session["control_frequency"],
    )


@router.delete("/sessions/{session_id}")
async def stop_teleoperation(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    停止遥操作会话
    """
    session = active_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 检查权限
    if session["user_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="无权停止此会话")

    # 更新会话状态
    session["status"] = "stopped"

    # TODO: 停止实时控制层
    # TODO: 记录审计日志

    # 从活跃会话中移除
    del active_sessions[session_id]

    return {"message": "遥操作已停止", "session_id": session_id}


@router.post("/emergency-stop")
async def emergency_stop(db: Session = Depends(get_db)):
    """
    紧急停止（无需认证，任何人都可以触发）
    """
    timestamp = datetime.utcnow()

    # 停止所有活跃会话
    stopped_sessions = []
    for session_id, session in list(active_sessions.items()):
        session["status"] = "stopped"
        stopped_sessions.append(session_id)
        del active_sessions[session_id]

    # TODO: 立即停止所有机器人（调用实时控制层）
    # TODO: 记录审计日志
    # TODO: 通知所有连接的WebSocket客户端

    return {
        "message": "紧急停止已触发",
        "timestamp": timestamp,
        "stopped_sessions": stopped_sessions,
    }


# M0 注: 原 V1 `/ws` 数据录制端点依赖 app.services.websocket_manager 和
# timeseries_service (已随服务目录一同裁剪). 实时录制在 M0 阶段直接走
# apps/realtime (:8002) 的 `/api/record`. M1.6 会在本文件加 `POST /record/start|stop`
# 透传到 apps/realtime.
# TODO(M2): 如需恢复 v1 帧级录制 ws, 同步恢复 app.services.* 模块.
