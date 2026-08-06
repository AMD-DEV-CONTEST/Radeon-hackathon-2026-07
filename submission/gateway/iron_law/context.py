"""
Iron Law — Context Assembler
将 RAG 召回 + DB 历史 + 项目配置 组装成任务 context_envelope。
项目上下文存在 iron_law/data/projects/{project}.json，不依赖特定 DB 表结构。
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger("iron_law.context")

RAG_BASE_URL = os.environ.get("RAG_BASE_URL", "http://127.0.0.1:8010")
DATABASE_URL = os.environ.get("DATABASE_URL")
DEFAULT_TOP_K = int(os.environ.get("ILS_DEFAULT_TOP_K", "3"))
MIN_SIMILARITY = float(os.environ.get("ILS_MIN_SIMILARITY", "0.4"))

# Agent operational protocol — injected into every task context so agents
# don't need to know where the docs are. Mirrors ACP §5 (docs/UAS-ACP-v1.0.md).
_AGENT_PROTOCOL: dict[str, Any] = {
    "version": "1.0",
    "doc": "docs/UAS-ACP-v1.0.md",
    "action_sequence": [
        "1. GET /iron-law/context/{task_id}  — read similar cases + prior failures + this protocol",
        "2. POST /tasks/{task_id}/lease {agent_id}  — acquire exclusive lock",
        "3. POST /tasks/{task_id}/heartbeat {agent_id}  — every 30s, or lease expires",
        "4. POST /tasks/{task_id}/complete {agent_id, acceptance_result, summary, artifact_uris}",
        "5. On blocker: POST /tasks/{task_id}/fail {agent_id, reason, error_type}",
    ],
    "acceptance_result": {
        "pass": "work done, acceptance criteria met → status=done → RAG sedimentation",
        "fail": "criteria not met, system will retry with backoff → status=failed_retryable",
        "needs_review": "human decision required → status=needs_review (use sparingly)",
    },
    "gate_exempt_task_types": [
        "review", "audit", "research", "analysis", "read_only", "planning", "discussion",
    ],
    "gate_exempt_rules": [
        "Exempt types: submit acceptance_result='pass', NOT 'needs_review'",
        "needs_review on exempt types causes infinite loop (system overrides, but still wrong)",
        "Rule 1 (context.goal) and Rule 5 (acceptance_check) are skipped for exempt types",
        "Rule 3 (granularity ≤1h) applies to ALL task types including exempt",
    ],
    "error_types": {
        "blocked_permission": "need authorization from 老何",
        "blocked_auth": "need API key / credentials",
        "blocked_rate_limit": "rate limited, set blocked_until in fail payload",
        "blocked_env": "missing dependency or config",
        "acceptance_failed": "acceptance_check ran and failed",
    },
    "do_not": [
        "Submit needs_review for audit/review/research tasks",
        "Stop heartbeat during long execution (lease expires after ~5min)",
        "Mark done without evidence in summary (ILS-R006 requires execution proof)",
        "Scope-creep beyond task description (create a new task instead)",
    ],
}

# 项目上下文存储目录
DATA_DIR = Path(os.environ.get("ILS_DATA_DIR", Path(__file__).resolve().parent / "data"))


def _connect_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


# ── RAG 调用 ──────────────────────────────────────────────────────────

def _rag_search(query: str, top_k: int = DEFAULT_TOP_K) -> list[dict[str, Any]]:
    """向 RAG Service 查询相似案例，返回 top-k 结果。"""
    payload = json.dumps({
        "query": query,
        "top_k": top_k,
        "min_similarity": MIN_SIMILARITY,
    }).encode()
    req = urllib.request.Request(
        f"{RAG_BASE_URL}/cases/search",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
            return [
                {
                    "case_id": r["case"]["case_id"],
                    "title": r["case"]["title"],
                    "similarity": round(r["similarity"], 3),
                    "summary": _extract_summary(r["case"]),
                }
                for r in data.get("results", [])
            ]
    except Exception as exc:
        logger.warning("RAG search failed: %s", exc)
        return []


def _extract_summary(case: dict[str, Any]) -> str:
    content = case.get("content", {})
    parts = []
    if content.get("what_worked"):
        parts.append(f"解法: {str(content['what_worked'])[:120]}")
    if content.get("key_files"):
        parts.append(f"文件: {', '.join(str(f) for f in content['key_files'][:3])}")
    desc = case.get("description", "")
    if desc and len(desc) < 150:
        parts.append(desc)
    return " | ".join(parts) if parts else case.get("title", "")


def rag_write_case(
    case_id: str,
    title: str,
    description: str,
    category: str,
    content: dict[str, Any],
    tags: list[str] | None = None,
) -> bool:
    """向 RAG Service 写入新案例（任务完成后调用）。"""
    payload = json.dumps({
        "case_id": case_id,
        "title": title,
        "description": description,
        "category": category,
        "tags": tags or [],
        "content": content,
        "metadata": {
            "source": "task_completion",
            "ts": datetime.now(timezone.utc).isoformat(),
        },
    }).encode()
    req = urllib.request.Request(
        f"{RAG_BASE_URL}/cases",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            ok = resp.status in (200, 201)
            if ok:
                logger.info("RAG case written: %s", case_id)
            return ok
    except Exception as exc:
        logger.warning("RAG write case failed: %s", exc)
        return False


# ── 项目上下文（文件存储）─────────────────────────────────────────────

def _project_file(project: str) -> Path:
    safe_project = "".join(ch for ch in project if ch.isalnum() or ch in {"-", "_"})
    if not safe_project:
        safe_project = "default"
    path = DATA_DIR / "projects"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{safe_project}.json"


def save_project_context(project: str, context: dict[str, Any]) -> None:
    """保存项目上下文（约束、关键文件、背景）到本地 JSON。"""
    path = _project_file(project)
    context["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("project context saved: %s", path)


def _get_project_context(project: str) -> dict[str, Any]:
    path = _project_file(project)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to read project context %s: %s", path, exc)
    return {}


# ── DB 查询 ───────────────────────────────────────────────────────────

def _get_prior_failures(project: str, limit: int = 5) -> list[str]:
    """读最近几次 failed_final 任务的 summary，帮 Agent 避开老坑。"""
    try:
        with _connect_db() as conn:
            rows = conn.execute(
                """
                SELECT t.title, a.summary, a.error_message
                FROM tasks t
                JOIN task_attempts a ON a.task_id = t.id
                WHERE t.status = 'failed_final'
                  AND (t.description ILIKE %s OR t.title ILIKE %s)
                  AND a.status IN ('failed_final', 'failed_retryable')
                ORDER BY t.updated_at DESC LIMIT %s
                """,
                (f"%{project}%", f"%{project}%", limit),
            ).fetchall()
            failures = []
            for r in rows:
                msg = r["summary"] or r["error_message"] or "(no detail)"
                failures.append(f"[{r['title']}] {str(msg)[:150]}")
            return failures
    except Exception as exc:
        logger.warning("DB prior_failures query failed: %s", exc)
        return []


def get_open_tasks(limit: int = 20) -> list[dict[str, Any]]:
    """读所有未完成任务（供 Leader snapshot 使用）。"""
    try:
        with _connect_db() as conn:
            rows = conn.execute(
                """
                SELECT id, title, status, required_capabilities, updated_at
                FROM tasks
                WHERE status NOT IN ('done', 'failed_final', 'cancelled')
                ORDER BY created_at DESC LIMIT %s
                """,
                (limit,),
            ).fetchall()
            return [
                {
                    "id": str(r["id"]),
                    "title": r["title"],
                    "status": r["status"],
                }
                for r in rows
            ]
    except Exception as exc:
        logger.warning("DB open_tasks query failed: %s", exc)
        return []


def get_recent_events(limit: int = 20) -> list[dict[str, Any]]:
    """读最近 N 条事件（供 Leader snapshot 使用）。"""
    try:
        with _connect_db() as conn:
            rows = conn.execute(
                """
                SELECT event_type, message, level, created_at
                FROM events
                ORDER BY created_at DESC LIMIT %s
                """,
                (limit,),
            ).fetchall()
            return [
                {"type": r["event_type"], "message": (r["message"] or "")[:100]}
                for r in rows
            ]
    except Exception as exc:
        logger.warning("DB recent_events query failed: %s", exc)
        return []


def get_rounds_from_db(session_id: str, limit: int = 5) -> list[dict[str, Any]]:
    """从 DB 读回合记录（session_rounds 表）。"""
    try:
        with _connect_db() as conn:
            rows = conn.execute(
                """
                SELECT round_id, leader_instruction, decision,
                       blockers, agent_outputs, created_at, closed_at
                FROM session_rounds
                WHERE session_id = %s
                ORDER BY round_id DESC LIMIT %s
                """,
                (session_id, limit),
            ).fetchall()
            return [
                {
                    "round_id": r["round_id"],
                    "session_id": session_id,
                    "leader_instruction": r["leader_instruction"],
                    "participant_assignments": {},
                    "agent_outputs": r["agent_outputs"] or {},
                    "artifacts": [],
                    "blockers": r["blockers"] or [],
                    "leader_review": "",
                    "deployment_opinion": "",
                    "decision": r["decision"] or "",
                    "next_action": "",
                    "created_at": r["created_at"].isoformat() if r["created_at"] else "",
                    "closed_at": r["closed_at"].isoformat() if r["closed_at"] else "",
                }
                for r in rows
            ]
    except Exception as exc:
        logger.warning("DB rounds query failed for %s: %s", session_id, exc)
        return []


def get_online_agents() -> list[dict[str, Any]]:
    """读在线 Agent 列表。"""
    try:
        with _connect_db() as conn:
            rows = conn.execute(
                """
                SELECT name, agent_type, status, capabilities, host_id
                FROM agents WHERE status = 'online'
                """,
            ).fetchall()
            return [
                {
                    "name": r["name"],
                    "type": r["agent_type"],
                    "host": r["host_id"],
                    "caps": r["capabilities"],
                }
                for r in rows
            ]
    except Exception as exc:
        logger.warning("DB agents query failed: %s", exc)
        return []


# ── 核心：context_envelope 组装 ───────────────────────────────────────

def assemble_context(
    raw_demand: str,
    project: str = "omima",
    task_id: str | None = None,
    task_type: str = "coding",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    组装完整的 context_envelope，注入到任务 payload 里。

    结构：
    {
      "goal": str,
      "similar_cases": [...],       ← RAG 召回
      "project_context": {...},     ← 项目约束 / 背景（文件读取）
      "prior_failures": [...],      ← 历史失败摘要（DB 查询）
      "assembled_at": str,
    }
    """
    similar_cases = _rag_search(raw_demand)
    project_ctx = _get_project_context(project)
    prior_failures = _get_prior_failures(project)

    envelope: dict[str, Any] = {
        "goal": raw_demand,
        "similar_cases": similar_cases,
        "project_context": project_ctx,
        "prior_failures": prior_failures,
        "agent_protocol": _AGENT_PROTOCOL,
        "assembled_at": datetime.now(timezone.utc).isoformat(),
    }
    if task_id:
        envelope["task_id"] = task_id
    if extra:
        envelope.update({k: v for k, v in extra.items() if v is not None})

    logger.info(
        "context assembled: %d similar cases, %d prior failures, project=%s",
        len(similar_cases), len(prior_failures), project,
    )
    return envelope


def assemble_leader_snapshot(session_id: str, project: str = "omima") -> dict[str, Any]:
    """
    Leader 进会议室时的全局快照：目标、参与者、开放任务、事件摘要。
    通过 GET /iron-law/snapshot/{session_id} 暴露给 Agent。
    """
    return {
        "session_id": session_id,
        "project": project,
        "project_context": _get_project_context(project),
        "open_tasks": get_open_tasks(),
        "recent_events": get_recent_events(),
        "recent_rounds": get_rounds_from_db(session_id),
        "online_agents": get_online_agents(),
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
    }
