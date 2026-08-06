"""
Iron Law — 巡检服务 (port 8020)
独立 FastAPI 服务，提供 POST /boundary/check 端点。
按 check_type 分派到对应的检查器。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from iron_law.boundary.checker import check_dag, check_final, check_structuring

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("boundary")

app = FastAPI(
    title="UAS 巡检服务",
    description="Iron Law 边界巡检 — 任务包合规性校验与自动修复",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://127.0.0.1:8001"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class BoundaryCheckRequest(BaseModel):
    check_type: Literal["structuring", "task_dag", "final"]
    data: dict[str, Any]


class BoundaryCheckResponse(BaseModel):
    compliant: bool
    issues: list[dict[str, Any]]
    can_auto_fix: bool
    fixed_data: dict[str, Any] | None
    summary: str
    checked_at: str


@app.post("/boundary/check", response_model=BoundaryCheckResponse)
def boundary_check(req: BoundaryCheckRequest) -> BoundaryCheckResponse:
    """
    巡检入口：
    - check_type=structuring → 检查结构化输出字段完整性
    - check_type=task_dag    → 检查任务 DAG（acceptance_check、粒度、依赖）
    - check_type=final       → 检查完成报告（summary 和 acceptance_result）
    """
    logger.info("boundary check type=%s", req.check_type)

    if req.check_type == "task_dag":
        tasks = req.data.get("tasks", [])
        result = check_dag(tasks)
    elif req.check_type == "structuring":
        result = check_structuring(req.data)
    elif req.check_type == "final":
        result = check_final(req.data)
    else:
        result = {"compliant": True, "issues": [], "can_auto_fix": False, "fixed_data": None, "summary": "unknown type"}

    return BoundaryCheckResponse(
        compliant=result["compliant"],
        issues=result["issues"],
        can_auto_fix=result.get("can_auto_fix", False),
        fixed_data=result.get("fixed_data"),
        summary=result.get("summary", f"{len(result['issues'])} issues"),
        checked_at=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "boundary",
        "time": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8020)
