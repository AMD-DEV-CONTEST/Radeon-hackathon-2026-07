"""
生成可公示开发日志 DEVLOG.md。
数据来源：git log（提交历史）+ tasks DB（任务经验）+ events DB（重要事件）。

用于专业评审场景，展示系统从零到落地的工程轨迹。

使用：
    python scripts/generate_devlog.py
    python scripts/generate_devlog.py --out docs/DEVLOG.md
    python scripts/generate_devlog.py --since 2026-06-01 --until 2026-06-07
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("DATABASE_URL")
REPO_DIR = os.environ.get("REPO_DIR", str(Path(__file__).resolve().parent.parent))
OUT_DEFAULT = str(Path(__file__).resolve().parent.parent / "docs" / "DEVLOG.md")

# 提交过滤：跳过低信息 commit
SKIP_PATTERNS = [
    r"^chore: lint",
    r"^chore: format",
    r"^fix: typo",
    r"^Merge (pull request|branch)",
    r"^chore: update lock",
    r"^chore: bump version",
]
SKIP_RE = re.compile("|".join(SKIP_PATTERNS), re.IGNORECASE)


def connect():
    if not DATABASE_URL:
        print("WARNING: DATABASE_URL not set, skipping DB queries", file=sys.stderr)
        return None
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def get_git_log(since: str | None, until: str | None) -> list[dict]:
    """Parse git log into structured entries."""
    fmt = "%H\x1f%ad\x1f%an\x1f%s\x1f%b\x1e"
    args = ["git", "-C", REPO_DIR, "log", f"--format={fmt}", "--date=short"]
    if since:
        args.append(f"--after={since}")
    if until:
        args.append(f"--before={until}")

    try:
        output = subprocess.check_output(args, stderr=subprocess.DEVNULL, text=True)
    except subprocess.CalledProcessError as e:
        print(f"WARNING: git log failed: {e}", file=sys.stderr)
        return []

    commits = []
    for record in output.strip().split("\x1e"):
        record = record.strip()
        if not record:
            continue
        parts = record.split("\x1f", 4)
        if len(parts) < 4:
            continue
        sha, date_str, author, subject = parts[0], parts[1], parts[2], parts[3]
        body = parts[4].strip() if len(parts) > 4 else ""

        if SKIP_RE.match(subject):
            continue

        commits.append({
            "sha": sha[:8],
            "date": date_str,
            "author": author,
            "subject": subject,
            "body": body[:300] if body else "",
        })
    return commits


def get_tasks_by_date(conn, since: str | None, until: str | None) -> dict[str, list[dict]]:
    """Group completed/failed tasks by finish date."""
    if conn is None:
        return {}

    conditions = ["t.status IN ('done', 'failed_final')", "t.finished_at IS NOT NULL"]
    params: list[Any] = []
    if since:
        conditions.append("t.finished_at >= %s")
        params.append(since)
    if until:
        conditions.append("t.finished_at <= %s")
        params.append(until + " 23:59:59")

    where = " AND ".join(conditions)
    rows = conn.execute(
        f"""
        SELECT DISTINCT ON (t.id)
            t.id::text, t.title, t.task_type, t.status,
            t.finished_at::date::text AS finish_date,
            a.summary
        FROM tasks t
        LEFT JOIN task_attempts a ON a.task_id = t.id
        WHERE {where}
        ORDER BY t.id, a.attempt_no DESC
        """,
        params,
    ).fetchall()

    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_date[r["finish_date"]].append(dict(r))
    return dict(by_date)


def get_events_by_date(conn, since: str | None, until: str | None) -> dict[str, list[dict]]:
    """Get notable error/warn events grouped by date."""
    if conn is None:
        return {}

    conditions = ["level IN ('error', 'warn')", "message IS NOT NULL"]
    params: list[Any] = []
    if since:
        conditions.append("created_at >= %s")
        params.append(since)
    if until:
        conditions.append("created_at <= %s")
        params.append(until + " 23:59:59")

    where = " AND ".join(conditions)
    try:
        rows = conn.execute(
            f"""
            SELECT event_type, message, level,
                   created_at::date::text AS event_date
            FROM events
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT 100
            """,
            params,
        ).fetchall()
    except Exception:
        return {}

    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_date[r["event_date"]].append(dict(r))
    return dict(by_date)


def commit_type_label(subject: str) -> str:
    prefixes = {
        "feat": "✨ Feature", "fix": "🐛 Fix", "docs": "📄 Docs",
        "refactor": "♻️  Refactor", "test": "🧪 Test", "deploy": "🚀 Deploy",
        "chore": "🔧 Chore", "perf": "⚡ Perf",
    }
    for prefix, label in prefixes.items():
        if subject.lower().startswith(prefix + "(") or subject.lower().startswith(prefix + ":"):
            return label
    return "📌 Change"


def render_day(day: str, commits: list[dict], tasks: list[dict], events: list[dict]) -> str:
    lines = [f"\n## {day}\n"]

    if commits:
        lines.append("### Commits\n")
        for c in commits:
            label = commit_type_label(c["subject"])
            lines.append(f"- **{label}** `{c['sha']}` {c['subject']}")
            if c["body"]:
                for bline in c["body"].splitlines()[:3]:
                    if bline.strip():
                        lines.append(f"  > {bline.strip()}")
        lines.append("")

    if tasks:
        done = [t for t in tasks if t["status"] == "done"]
        failed = [t for t in tasks if t["status"] == "failed_final"]
        if done:
            lines.append("### Tasks Completed\n")
            for t in done:
                lines.append(f"- [{t['task_type']}] {t['title']}")
                if t.get("summary"):
                    lines.append(f"  - {t['summary'][:120]}")
            lines.append("")
        if failed:
            lines.append("### Tasks Escalated (failed_final)\n")
            for t in failed:
                lines.append(f"- [{t['task_type']}] {t['title']}")
            lines.append("")

    if events:
        lines.append("### Notable Events\n")
        seen: set[str] = set()
        for e in events[:5]:
            msg = (e["message"] or "")[:120]
            if msg in seen:
                continue
            seen.add(msg)
            icon = "🔴" if e["level"] == "error" else "🟡"
            lines.append(f"- {icon} [{e['event_type']}] {msg}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=OUT_DEFAULT, help="输出文件路径")
    parser.add_argument("--since", default=None, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--until", default=None, help="结束日期 YYYY-MM-DD")
    args = parser.parse_args()

    print(f"读取 git log（repo={REPO_DIR}）...")
    commits = get_git_log(args.since, args.until)
    print(f"  {len(commits)} 条有效提交")

    conn = connect()
    tasks_by_date = get_tasks_by_date(conn, args.since, args.until)
    events_by_date = get_events_by_date(conn, args.since, args.until)
    if conn:
        conn.close()

    total_tasks = sum(len(v) for v in tasks_by_date.values())
    print(f"  {total_tasks} 条有效任务")

    # 按日期合并
    commits_by_date: dict[str, list[dict]] = defaultdict(list)
    for c in commits:
        commits_by_date[c["date"]].append(c)

    all_dates = sorted(
        set(list(commits_by_date.keys()) + list(tasks_by_date.keys())),
        reverse=True,
    )

    # 生成统计
    total_commits = len(commits)
    done_tasks = sum(1 for tasks in tasks_by_date.values() for t in tasks if t["status"] == "done")

    header = f"""# UnionAgents System — Development Log

> **System**: UAS (Union Agent System) — distributed multi-agent orchestration platform
> **Period**: {all_dates[-1] if all_dates else "N/A"} → {all_dates[0] if all_dates else "N/A"}
> **Stats**: {total_commits} commits · {done_tasks} tasks completed · {len(all_dates)} active days
> **Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

This log is generated from real engineering artifacts: git commits, task execution records,
and system events. It provides an auditable trail of architectural decisions, problem-solving
cycles, and system evolution — from API scaffold to production multi-agent governance layer.

---

## Architecture Milestones

| Date | Milestone |
|------|-----------|
| 2026-06-01 | Project bootstrap — FastAPI scaffold, PostgreSQL schema, agent heartbeat |
| 2026-06-02 | Iron Law System (ILS) v1.0 — 5 gates, 3 hooks, intake pipeline |
| 2026-06-03 | Gateway WebSocket — real-time task dispatch to agents |
| 2026-06-04 | Multi-agent routing — SCC/老三 online, decomposer with BGE embeddings |
| 2026-06-05 | P0 Fix — needs_review infinite loop, GATE_EXEMPT_TASK_TYPES |
| 2026-06-06 | ACP v1.0 — Agent Collaboration Protocol, agent_protocol context injection |

---
"""

    body_parts = [header]
    for day in all_dates:
        day_commits = commits_by_date.get(day, [])
        day_tasks = tasks_by_date.get(day, [])
        day_events = events_by_date.get(day, [])
        if not day_commits and not day_tasks:
            continue
        body_parts.append(render_day(day, day_commits, day_tasks, day_events))

    body_parts.append("\n---\n*Log generated by `scripts/generate_devlog.py` from live system data.*\n")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(body_parts), encoding="utf-8")

    print(f"\n✅ DEVLOG 已生成: {out_path}")
    print(f"   {len(all_dates)} 天 · {total_commits} 提交 · {done_tasks} 任务")


if __name__ == "__main__":
    main()
