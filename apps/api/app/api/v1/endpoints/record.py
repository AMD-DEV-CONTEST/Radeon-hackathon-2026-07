"""Record 控制透传端点.

M1.6: apps/api 自己不碰串口/文件, 所有录制操作都是薄代理, 直接打到
apps/realtime (:8002) 的 `/api/record`. 这样 CLI / 前端可以只记一个
业务域域名, 未来也能在此层统一加审计 / 用户权限.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Any, Literal

import httpx

from app.core.config import settings
from app.api.v1.endpoints.auth import get_current_user
from app.models.user import User

router = APIRouter()


class RecordActionRequest(BaseModel):
    action: Literal["start", "stop"]


async def _forward(action: str) -> dict[str, Any]:
    url = f"{settings.REALTIME_SERVICE_URL.rstrip('/')}/api/record"
    # stop 时 realtime 会同步做 parquet 转换, 大 session 可能 10s+, 给 60s 容限
    timeout = 60.0 if action == "stop" else 10.0
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json={"action": action})
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"realtime service unreachable: {e}") from e
    if resp.status_code >= 500:
        raise HTTPException(status_code=502, detail=f"realtime error {resp.status_code}: {resp.text}")
    data = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=data.get("detail", resp.text))
    return data


@router.post("/start")
async def record_start(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """开始录制 (透传到 realtime)."""
    _ = current_user  # 未来可接入审计
    return await _forward("start")


@router.post("/stop")
async def record_stop(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """停止录制并导出 parquet (透传到 realtime)."""
    _ = current_user
    return await _forward("stop")


@router.post("")
async def record(
    req: RecordActionRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """统一入口: `{"action": "start" | "stop"}` (与 realtime 对齐)."""
    _ = current_user
    return await _forward(req.action)
