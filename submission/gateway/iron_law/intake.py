"""
Iron Law — 接入层 API 处理器
挂载到 orchestrator/main.py 的 /iron-law/* 路由。
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from iron_law.context import assemble_context, assemble_leader_snapshot, save_project_context
from orchestrator.policy import assign_agent as policy_assign_agent
from orchestrator.gateway_client import gateway_post
from iron_law.rules import RuleViolation, validate_task_before_dispatch, GATE_EXEMPT_TASK_TYPES
from iron_law.hooks import on_intake, on_dispatch, on_completion, HookBlockError
from iron_law.intent_packet import IntentPacket, IntentType
from iron_law.ownership import get_registry, OwnershipConflictError
from iron_law.prompts import (
    get_thermos_review_prompt,
    get_pstack_context,
    HANDOFF_SCHEMA,
    HANDOFF_MINIMAL,
)

logger = logging.getLogger("iron_law.intake")

DATABASE_URL = os.environ.get("DATABASE_URL")
BOUNDARY_URL = os.environ.get("BOUNDARY_URL", "http://127.0.0.1:8020")

router = APIRouter(prefix="/iron-law", tags=["iron-law"])


# ── Pydantic 模型 ─────────────────────────────────────────────────────

class IntakeRequest(BaseModel):
    raw_demand: str
    project: str = "omima"
    requester: str = "user"
    priority: int = Field(default=50, ge=1, le=100)
    extra_context: dict[str, Any] = Field(default_factory=dict)


class IntakeResponse(BaseModel):
    intake_id: str
    status: str
    context: dict[str, Any]
    message: str


class TaskWithContextRequest(BaseModel):
    """任务创建请求，必须带 context（铁律规则1）。"""
    title: str
    description: str = ""
    task_type: str = "coding"
    project: str = "omima"
    context_goal: str  # 必填：这个任务服务于什么目标
    relevant_files: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    acceptance_check: dict[str, Any] | None = None
    required_capabilities: dict[str, Any] = Field(default_factory=dict)
    estimated_hours: float | None = None
    max_turns: int = 60
    priority: int = 50
    dependencies: list[str] = Field(default_factory=list)
    # Orchestrate handoff 字段
    handoff_schema: str = "1.0"
    handoff_artifacts: list[str] = Field(default_factory=list)
    handoff_verifier: str | None = None
    handoff_parent_task: str | None = None


class ProjectContextRequest(BaseModel):
    project: str
    context: dict[str, Any]


class SnapshotResponse(BaseModel):
    snapshot: dict[str, Any]


# ── DB helpers ────────────────────────────────────────────────────────

def _db():
    if not DATABASE_URL:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DATABASE_URL is not configured.",
        )
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


def _boundary_check(tasks: list[dict]) -> dict[str, Any]:
    """调用巡检服务校验任务包。失败时返回空（不阻塞主流程）。"""
    payload = json.dumps({"check_type": "task_dag", "data": {"tasks": tasks}}).encode()
    req = urllib.request.Request(
        f"{BOUNDARY_URL}/boundary/check",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        logger.warning("Boundary check unavailable: %s", exc)
        return {"compliant": True, "issues": [], "warning": "boundary service unreachable"}


def _resolve_agent_by_type(conn, agent_type: str):
    """Resolve agent_type to an online agent UUID (local copy to avoid circular imports)."""
    row = conn.execute(
        """
        SELECT id FROM agents
        WHERE agent_type = %s
          AND status IN ('online', 'draining')
        ORDER BY last_heartbeat_at DESC NULLS LAST
        LIMIT 1
        """,
        (agent_type,),
    ).fetchone()
    return row["id"] if row else None


# ── 端点 ─────────────────────────────────────────────────────────────

@router.post("/intake", response_model=IntakeResponse)
def intake(req: IntakeRequest) -> IntakeResponse:
    """
    铁律接入层：接收原始需求，自动组装 context_envelope。
    返回组装好的 context，供后续创建结构化任务使用。
    触发铁律规则1（召回相似案例）。
    """
    intake_id = str(uuid4())
    # Build canonical IntentPacket (ILS v2.2)
    packet = IntentPacket(
        task_id=intake_id,
        raw_input=req.raw_demand,
        normalized_intent=req.raw_demand[:500],
        target_object=req.extra_context.get("target_object", req.raw_demand.split()[0] if req.raw_demand.split() else ""),
        intent_type=IntentType(req.extra_context.get("intent_type", "other")),
        scope_boundary=req.extra_context.get("scope_boundary", ""),
        non_goals=req.extra_context.get("non_goals", []),
        ambiguity_points=req.extra_context.get("ambiguity_points", []),
        asr_noise_suspected=req.extra_context.get("asr_noise_suspected", False),
        confidence=req.extra_context.get("confidence", 0.8),
        required_confirmation=req.extra_context.get("required_confirmation", False),
        project=req.project,
    )
    try:
        on_intake(packet.to_hook_dict())
    except HookBlockError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"gate": exc.gate_id, "failure_code": exc.failure_code, "reasons": exc.reasons},
        )
    logger.info("intake id=%s project=%s demand=%s", intake_id, req.project, req.raw_demand[:60])

    context = assemble_context(
        raw_demand=req.raw_demand,
        project=req.project,
        task_id=intake_id,
        extra=req.extra_context,
    )

    similar_count = len(context.get("similar_cases", []))
    failure_count = len(context.get("prior_failures", []))

    return IntakeResponse(
        intake_id=intake_id,
        status="context_ready",
        context=context,
        message=(
            f"上下文组装完成。召回 {similar_count} 个相似案例，"
            f"{failure_count} 条历史失败记录。"
            "请基于此 context 创建结构化任务，或调用 /iron-law/task 直接发布。"
        ),
    )


@router.post("/task", status_code=status.HTTP_201_CREATED)
def create_task_with_context(
    req: TaskWithContextRequest,
    conn: psycopg.Connection = Depends(_db),
) -> dict[str, Any]:
    """
    铁律任务创建：自动注入上下文，校验规则，发布到 Orchestrator 队列。
    比直接 POST /tasks 多了：上下文注入 + 规则校验 + 巡检。
    """
    # 1. 组装 context (含 pstack 前置推理)
    context = assemble_context(
        raw_demand=req.context_goal,
        project=req.project,
        task_type=req.task_type,
        extra={
            "relevant_files": req.relevant_files,
            "constraints": req.constraints,
            "estimated_hours": req.estimated_hours,
        },
    )

    # 1b. 注入 pstack 前置推理检查表
    pstack_ctx = get_pstack_context(req.task_type)
    context["pstack"] = pstack_ctx

    # 1c. 注入 thermos 审查 prompt（仅 review 类任务）
    instruction = req.description
    if req.task_type == "review":
        review_prompt = get_thermos_review_prompt("both")
        instruction = f"{review_prompt}\n\n---\n## 任务说明\n{req.description}"

    # 2. 构造任务
    # Exempt task types default to "auto" acceptance so Rule 5 doesn't block them.
    acceptance_check = req.acceptance_check
    if acceptance_check is None and req.task_type.lower() in GATE_EXEMPT_TASK_TYPES:
        acceptance_check = {"type": "auto"}

    task_dict = {
        "title": req.title,
        "description": req.description,
        "task_type": req.task_type,
        "acceptance_check": acceptance_check,
        "required_capabilities": req.required_capabilities,
        "handoff": {
            "schema": req.handoff_schema,
            "artifacts": req.handoff_artifacts,
            "verifier": req.handoff_verifier,
            "parent_task": req.handoff_parent_task,
        },
        "payload": {
            "instruction": instruction,
            "context": context,
            "estimated_hours": req.estimated_hours,
            "handoff": {
                "schema": req.handoff_schema,
                "artifacts": req.handoff_artifacts,
                "verifier": req.handoff_verifier,
                "parent_task": req.handoff_parent_task,
            },
        },
    }

    # 3. 铁律规则校验
    try:
        warnings = validate_task_before_dispatch(task_dict)
    except RuleViolation as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"rule": e.rule, "violation": e.message, "auto_fixable": e.auto_fixable},
        )

    # 4. 巡检服务校验
    boundary_result = _boundary_check([task_dict])
    if not boundary_result.get("compliant", True):
        issues = boundary_result.get("issues", [])
        if not boundary_result.get("can_auto_fix"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"boundary_issues": issues},
            )
        # 自动修复
        fixed = boundary_result.get("fixed_data", {})
        if fixed.get("tasks"):
            task_dict.update(fixed["tasks"][0])
        warnings.extend([i.get("reason", "") for i in issues])

    # 4b. Ownership conflict check + dispatch hook (ILS-G004)
    dep_modules = [d for d in req.dependencies if d]
    registry = get_registry()
    conflicts = registry.check_conflict(dep_modules, req.title)
    try:
        on_dispatch(
            task_id="pending",
            agent_id="unassigned",
            required_caps=req.required_capabilities,
            ownership_conflicts=conflicts if conflicts else None,
        )
    except HookBlockError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"gate": exc.gate_id, "failure_code": exc.failure_code, "reasons": exc.reasons},
        )

    # 5. Deterministic routing
    agent_type = policy_assign_agent(req.task_type)
    target_agent_id = _resolve_agent_by_type(conn, agent_type)

    # 6. 写入 Orchestrator DB
    deps = [d for d in req.dependencies if d]
    row = conn.execute(
        """
        INSERT INTO tasks (
            id, title, description, task_type, status, priority,
            acceptance_check, required_capabilities, payload,
            dependencies, max_attempts, created_by, target_agent_id, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), %(title)s, %(description)s, %(task_type)s,
            'queued', %(priority)s,
            %(acceptance_check)s, %(required_capabilities)s, %(payload)s,
            %(dependencies)s, 3, 'iron-law', %(target_agent_id)s, now(), now()
        ) RETURNING id, title, status, created_at
        """,
        {
            "title": req.title,
            "description": req.description,
            "task_type": req.task_type,
            "priority": req.priority,
            "acceptance_check": Jsonb(acceptance_check or {}),
            "required_capabilities": Jsonb(task_dict["required_capabilities"]),
            "payload": Jsonb(task_dict["payload"]),
            "dependencies": Jsonb(deps),
            "target_agent_id": target_agent_id,
        },
    ).fetchone()
    conn.commit()

    logger.info("iron-law task created id=%s title=%s", row["id"], req.title)

    # 7. Notify gateway for deterministic dispatch
    gateway_post("/tasks/dispatch", {
        "task_id": str(row["id"]),
        "required_capabilities": task_dict["required_capabilities"],
        "target_agent_id": str(target_agent_id) if target_agent_id else None,
        "task": {
            "id": str(row["id"]),
            "title": row["title"] or "",
            "description": req.description or "",
            "task_type": req.task_type or "",
            "priority": req.priority or 0,
            "payload": task_dict["payload"] or {},
        },
    })

    return {
        "task_id": str(row["id"]),
        "title": row["title"],
        "status": row["status"],
        "warnings": warnings,
        "boundary": boundary_result,
        "context_summary": {
            "similar_cases": len(context.get("similar_cases", [])),
            "prior_failures": len(context.get("prior_failures", [])),
        },
    }


@router.get("/context/{task_id}")
def get_task_context(task_id: str, project: str = "omima") -> dict[str, Any]:
    """
    Agent 接单后读取完整上下文（铁律 SKILL.md 规则1 要求调用这个端点）。
    """
    context = assemble_context(
        raw_demand=f"task:{task_id}",
        project=project,
        task_id=task_id,
    )
    return {"task_id": task_id, "context": context}


@router.get("/snapshot/{session_id}", response_model=SnapshotResponse)
def get_leader_snapshot(session_id: str, project: str = "omima") -> SnapshotResponse:
    """
    Leader 进会议室时调用：读全局快照（目标、Agent状态、开放任务、事件摘要）。
    铁律 SKILL.md Leader 专属规则要求的第一步。
    """
    snapshot = assemble_leader_snapshot(session_id=session_id, project=project)
    return SnapshotResponse(snapshot=snapshot)


@router.post("/project-context")
def set_project_context(req: ProjectContextRequest) -> dict[str, str]:
    """
    保存项目级上下文（约束、关键文件、项目背景）。
    由用户或 Leader 在项目开始时设置，之后所有任务自动继承。
    """
    save_project_context(project=req.project, context=req.context)
    return {"status": "saved", "project": req.project}


@router.post("/ownership/claim")
def claim_ownership(
    module_id: str,
    agent_id: str,
    scope: str = "",
    lease_seconds: int | None = None,
) -> dict[str, Any]:
    """Claim ownership of a module/resource (ILS v2.2)."""
    registry = get_registry()
    try:
        claim = registry.claim(module_id, agent_id, scope, lease_seconds)
        return {"status": "claimed", "claim": claim.to_dict()}
    except OwnershipConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": str(exc), "current_owner": exc.current_owner},
        )


@router.post("/ownership/release")
def release_ownership(module_id: str, agent_id: str) -> dict[str, Any]:
    """Release ownership of a module/resource (ILS v2.2)."""
    registry = get_registry()
    released = registry.release(module_id, agent_id)
    if not released:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active ownership claim found for this module/agent combination.",
        )
    return {"status": "released", "module_id": module_id}


@router.get("/ownership/check/{module_id}")
def check_ownership(module_id: str) -> dict[str, Any]:
    """Check who owns a module (ILS v2.2)."""
    registry = get_registry()
    claim = registry.check(module_id)
    if claim:
        return {"owned": True, "claim": claim.to_dict()}
    return {"owned": False}


@router.get("/health")
def health() -> dict[str, Any]:
    """铁律系统健康检查。"""
    rag_ok = False
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:8010/health", timeout=3) as r:
            rag_ok = r.status == 200
    except Exception:
        pass

    boundary_ok = False
    try:
        with urllib.request.urlopen(f"{BOUNDARY_URL}/health", timeout=3) as r:
            boundary_ok = r.status == 200
    except Exception:
        pass

    return {
        "status": "ok",
        "service": "iron-law",
        "rag_service": "ok" if rag_ok else "unavailable",
        "boundary_service": "ok" if boundary_ok else "unavailable",
        "time": datetime.now(timezone.utc).isoformat(),
    }
