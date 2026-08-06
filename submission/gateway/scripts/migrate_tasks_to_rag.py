"""
批量将历史任务经验迁移到 RAG Service。
幂等：已存在的 case_id 跳过（RAG service 409 → skip）。

使用：
    python scripts/migrate_tasks_to_rag.py
    python scripts/migrate_tasks_to_rag.py --dry-run      # 只统计，不写入
    python scripts/migrate_tasks_to_rag.py --status done  # 只迁移 done 状态
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("migrate_rag")

DATABASE_URL = os.environ.get("DATABASE_URL")
RAG_BASE_URL = os.environ.get("RAG_BASE_URL", "http://127.0.0.1:8010")

# 质量过滤阈值
MIN_SUMMARY_LENGTH = 30  # 过短的 summary 没有经验价值


def connect():
    if not DATABASE_URL:
        sys.exit("DATABASE_URL is not set")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def fetch_tasks(conn, status_filter: str) -> list[dict]:
    """
    取有效历史任务：join 最近一次有 summary 的 attempt。
    task_type IN exempt 类型的任务用 category='research/review'。
    """
    statuses = [s.strip() for s in status_filter.split(",")]
    placeholder = ",".join([f"'{s}'" for s in statuses])

    rows = conn.execute(
        f"""
        SELECT DISTINCT ON (t.id)
            t.id::text            AS task_id,
            t.title,
            t.description,
            t.task_type,
            t.status,
            t.created_at,
            t.finished_at,
            a.summary,
            a.error_message,
            a.attempt_no
        FROM tasks t
        JOIN task_attempts a ON a.task_id = t.id
        WHERE t.status IN ({placeholder})
          AND a.summary IS NOT NULL
          AND length(trim(a.summary)) >= {MIN_SUMMARY_LENGTH}
        ORDER BY t.id, a.attempt_no DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def build_case(task: dict) -> dict:
    category_map = {
        "review": "review", "audit": "review", "research": "research",
        "analysis": "research", "planning": "research",
        "coding": "implementation", "debug": "bugfix", "fix": "bugfix",
        "deployment": "deployment", "ops": "deployment",
    }
    task_type = (task["task_type"] or "coding").lower()
    category = category_map.get(task_type, "implementation")

    summary = task["summary"] or ""
    error = task["error_message"] or ""

    content: dict = {
        "what_worked": summary[:500] if task["status"] == "done" else "",
        "what_failed": error[:300] if task["status"] == "failed_final" else "",
        "task_type": task_type,
        "status": task["status"],
    }

    finished_str = ""
    if task.get("finished_at"):
        finished_str = task["finished_at"].strftime("%Y-%m-%d") if hasattr(task["finished_at"], "strftime") else str(task["finished_at"])[:10]

    return {
        "case_id": f"task-{task['task_id']}",
        "title": task["title"][:200],
        "description": (task["description"] or "")[:400],
        "category": category,
        "tags": [task_type, task["status"], finished_str] if finished_str else [task_type, task["status"]],
        "content": content,
        "metadata": {
            "source": "historical_migration",
            "original_task_id": task["task_id"],
            "migrated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def write_case_to_rag(case: dict) -> str:
    """Returns: 'written' | 'skipped' | 'error'"""
    payload = json.dumps(case, ensure_ascii=False).encode()
    req = urllib.request.Request(
        f"{RAG_BASE_URL}/cases",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return "written" if resp.status in (200, 201) else "error"
    except urllib.error.HTTPError as e:
        if e.code == 409:
            return "skipped"
        logger.warning("RAG write error %s for case %s: %s", e.code, case["case_id"], e.read()[:100])
        return "error"
    except Exception as exc:
        logger.warning("RAG unreachable: %s", exc)
        return "error"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写入 RAG")
    parser.add_argument("--status", default="done,failed_final", help="任务状态过滤，逗号分隔")
    parser.add_argument("--limit", type=int, default=0, help="最多处理 N 条（0=全部）")
    args = parser.parse_args()

    logger.info("连接数据库...")
    with connect() as conn:
        tasks = fetch_tasks(conn, args.status)

    if args.limit:
        tasks = tasks[: args.limit]

    logger.info("找到 %d 条有效历史任务（status=%s，summary≥%d字）", len(tasks), args.status, MIN_SUMMARY_LENGTH)

    if args.dry_run:
        by_type: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for t in tasks:
            by_type[t["task_type"] or "unknown"] = by_type.get(t["task_type"] or "unknown", 0) + 1
            by_status[t["status"]] = by_status.get(t["status"], 0) + 1
        print("\n=== DRY RUN ===")
        print(f"总计: {len(tasks)} 条")
        print("按 status:", json.dumps(by_status, ensure_ascii=False))
        print("按 task_type:", json.dumps(by_type, ensure_ascii=False))
        return

    written = skipped = errors = 0
    for i, task in enumerate(tasks, 1):
        case = build_case(task)
        result = write_case_to_rag(case)
        if result == "written":
            written += 1
            logger.info("[%d/%d] ✅ 写入 %s — %s", i, len(tasks), case["case_id"], task["title"][:60])
        elif result == "skipped":
            skipped += 1
            logger.debug("[%d/%d] ⏭  跳过 %s（已存在）", i, len(tasks), case["case_id"])
        else:
            errors += 1
            logger.warning("[%d/%d] ❌ 错误 %s", i, len(tasks), case["case_id"])

    print(f"\n=== 迁移完成 ===")
    print(f"写入: {written}  跳过: {skipped}  错误: {errors}  合计: {len(tasks)}")


if __name__ == "__main__":
    main()
