#!/usr/bin/env python3
"""
Hub Worker — P3-D1 (基础版)
接收用户自然语言需求 → DeepSeek 拆为子任务 → POST /tasks → 监控 → 继续推进。

Plan-Execute loop (参考 LobeHub agent-runtime):
  1. 用户输入目标
  2. Hub 规划子任务列表 (with required_capabilities + dependencies)
  3. POST /tasks 批量创建
  4. 轮询直到全部 done / failed
  5. 收集结果 → 继续推进或报告完成

Usage:
    DEEPSEEK_API_KEY=... python worker/hub_worker.py --goal "给 Omima 加登录页"
    DEEPSEEK_API_KEY=... python worker/hub_worker.py --session-id <uuid>  # resume
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
import urllib.request
import urllib.error
from typing import Any

logger = logging.getLogger("hub_worker")

ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://111.228.42.18:8000")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE = "https://api.deepseek.com"
MODEL = "deepseek-chat"
POLL_INTERVAL = 5.0


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def post_json(base_url: str, path: str, payload: dict) -> dict:
    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def get_json(base_url: str, path: str) -> Any:
    url = f"{base_url.rstrip('/')}{path}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read())


def deepseek_chat(messages: list[dict], system: str | None = None) -> str:
    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    payload = {
        "model": MODEL,
        "messages": msgs,
        "max_tokens": 4096,
        "temperature": 0.3,
    }
    url = f"{DEEPSEEK_BASE}/v1/chat/completions"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
    return result["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Orchestrator helpers
# ---------------------------------------------------------------------------

def create_task(base_url: str, task: dict) -> dict:
    return post_json(base_url, "/tasks", task)


def create_hub_session(base_url: str, goal: str, session_id: str) -> dict:
    return post_json(base_url, "/hub-sessions", {
        "title": goal[:80] or f"Hub session {session_id[:8]}",
        "objective": goal,
        "model_policy": MODEL,
        "owner": "hub-worker",
    })


def get_task(base_url: str, task_id: str) -> dict:
    return get_json(base_url, f"/tasks/{task_id}")


# ---------------------------------------------------------------------------
# Hub planning prompts
# ---------------------------------------------------------------------------

PLAN_SYSTEM = """You are Hub, a software project orchestrator.
Decompose the user's goal into concrete subtasks for specialized agents.

Available agent types:
- claude: Planning, code review, architecture decisions, documentation
- reasonix: File editing, code implementation, running commands, tests
- codex: Complex multi-file implementation, refactoring

Output ONLY a JSON array — no markdown, no explanation. Each element:
{
  "title": "short title (≤60 chars)",
  "task_type": "coding",
  "payload": { "instruction": "detailed instruction for the agent" },
  "required_capabilities": ["agent:claude"],
  "dependencies": [],
  "priority": 5
}

Rules:
- Keep tasks atomic (one agent, one concern)
- Use dependencies as 0-based indices into the array
- Default to reasonix for implementation, claude for review
- Maximum 8 tasks per plan
"""

CONTINUE_SYSTEM = """You are Hub, a software project orchestrator.
All tasks in the current round have finished. Decide next step:
A) More tasks needed → output a JSON array (same format as before)
B) Goal is complete → output {"done": true, "summary": "one-line summary"}

No markdown. Just JSON.
"""


def plan_tasks(goal: str, context: str = "") -> list[dict]:
    user_msg = f"Goal: {goal}"
    if context:
        user_msg += f"\n\nContext:\n{context}"

    raw = deepseek_chat([{"role": "user", "content": user_msg}], system=PLAN_SYSTEM)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(raw)


def normalize_required_capabilities(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        result: dict[str, Any] = {}
        for item in value:
            if isinstance(item, str) and ":" in item:
                key, raw_value = item.split(":", 1)
                result[key] = raw_value
            elif isinstance(item, str):
                result[item] = True
        return result
    return {}


def decide_continue(goal: str, completed_results: list[dict]) -> dict:
    context = json.dumps(completed_results, indent=2)
    user_msg = (
        f"Original goal: {goal}\n\n"
        f"Completed tasks:\n{context}\n\n"
        "Continue or done?"
    )
    raw = deepseek_chat([{"role": "user", "content": user_msg}], system=CONTINUE_SYSTEM)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    parsed = json.loads(raw)
    if isinstance(parsed, list):
        return {"done": False, "next_tasks": parsed}
    return parsed


# ---------------------------------------------------------------------------
# Task monitoring
# ---------------------------------------------------------------------------

def wait_for_tasks(base_url: str, task_ids: list[str], timeout_s: int = 1800) -> list[dict]:
    deadline = time.time() + timeout_s
    pending = set(task_ids)
    results: dict[str, dict] = {}

    while pending and time.time() < deadline:
        for tid in list(pending):
            try:
                t = get_task(base_url, tid)
                status = t.get("status", "")
                if status in (
                    "done",
                    "failed_retryable",
                    "failed_final",
                    "needs_review",
                    "cancelled",
                    "blocked_auth",
                    "blocked_rate_limit",
                    "blocked_env",
                    "blocked_permission",
                    "timeout_silent",
                ):
                    results[tid] = t
                    pending.discard(tid)
                    logger.info("Task %s → %s", tid[:8], status)
            except Exception as e:
                logger.warning("Error polling task %s: %s", tid[:8], e)
        if pending:
            time.sleep(POLL_INTERVAL)

    for tid in pending:
        results[tid] = {"id": tid, "status": "timeout"}

    return [results[tid] for tid in task_ids]


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_hub(base_url: str, goal: str, session_id: str, dry_run: bool = False) -> None:
    logger.info("Hub session %s: %s", session_id[:8], goal[:80])
    if not dry_run:
        try:
            created_session = create_hub_session(base_url, goal, session_id)
            logger.info("Created hub_session %s", created_session.get("id", "")[:8])
        except Exception as e:
            logger.warning("Failed to create hub_session: %s", e)

    round_num = 0
    max_rounds = 5
    override_tasks: list[dict] | None = None

    while round_num < max_rounds:
        round_num += 1
        logger.info("--- Round %d ---", round_num)

        # Plan (or use continuation tasks from previous round)
        if override_tasks is not None:
            task_specs = override_tasks
            override_tasks = None
        else:
            try:
                task_specs = plan_tasks(goal)
            except Exception as e:
                logger.error("Planning failed: %s", e)
                break

        logger.info("Planned %d tasks", len(task_specs))

        if dry_run:
            print("\n[dry-run] Plan (no tasks created):")
            print(json.dumps(task_specs, indent=2, ensure_ascii=False))
            return

        # Create tasks — resolve index dependencies → task IDs
        created_ids: list[str] = []
        for i, spec in enumerate(task_specs):
            dep_ids = [
                created_ids[idx]
                for idx in (spec.get("dependencies") or [])
                if isinstance(idx, int) and idx < len(created_ids) and created_ids[idx]
            ]
            body = {
                "title": spec["title"],
                "task_type": spec.get("task_type", "coding"),
                "payload": spec.get("payload", {}),
                "required_capabilities": normalize_required_capabilities(
                    spec.get("required_capabilities", {})
                ),
                "dependencies": dep_ids,
                "priority": spec.get("priority", 5),
            }
            try:
                created = create_task(base_url, body)
                tid = created["id"]
                created_ids.append(tid)
                logger.info("  [%d] %s → %s", i, spec["title"][:50], tid[:8])
            except Exception as e:
                logger.error("  [%d] Failed to create: %s", i, e)
                created_ids.append("")

        valid_ids = [tid for tid in created_ids if tid]
        if not valid_ids:
            logger.error("No tasks created, aborting")
            break

        # Monitor
        logger.info("Waiting for %d tasks...", len(valid_ids))
        results = wait_for_tasks(base_url, valid_ids)
        done_n = sum(1 for r in results if r.get("status") == "done")
        fail_n = sum(1 for r in results if r.get("status") == "failed")
        logger.info("Round %d: %d done, %d failed", round_num, done_n, fail_n)

        summaries = [
            {
                "id": r.get("id", "")[:8],
                "title": r.get("title", ""),
                "status": r.get("status", ""),
                "summary": ((r.get("result") or {}).get("summary") or "")[:200],
            }
            for r in results
        ]

        # Decide whether to continue
        try:
            decision = decide_continue(goal, summaries)
        except Exception as e:
            logger.error("Continuation decision failed: %s", e)
            break

        if decision.get("done"):
            summary = decision.get("summary", "")
            logger.info("Goal complete: %s", summary)
            print(f"\n✅ Hub session {session_id[:8]} complete: {summary}")
            return

        next_tasks = decision.get("next_tasks")
        if next_tasks:
            override_tasks = next_tasks
            continue

        logger.warning("Unexpected decision: %s", decision)
        break

    logger.info("Hub session %s finished after %d rounds", session_id[:8], round_num)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Hub Worker — orchestrator brain (P3-D1)")
    parser.add_argument("--goal", "-g", default="", help="Natural language goal")
    parser.add_argument("--orchestrator", default=ORCHESTRATOR_URL)
    parser.add_argument("--session-id", default=str(uuid.uuid4()))
    parser.add_argument("--dry-run", action="store_true", help="Plan only, don't create tasks")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY not set")
        return 1

    if not args.goal:
        print("Hub Worker — enter your goal:")
        try:
            args.goal = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if not args.goal:
            logger.error("No goal provided")
            return 1

    try:
        run_hub(args.orchestrator.rstrip("/"), args.goal, args.session_id, dry_run=args.dry_run)
    except KeyboardInterrupt:
        logger.info("Interrupted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
