#!/usr/bin/env python3
"""bootstrap_study_fixture.py — disposable study-service fixture (Todo 7).

Creates the disposable target schema (db/migrations/0001_initial.sql) with:
  - one verified skill/unit (gold source span + rubric key points)
  - one PREVIEW-ONLY skill (no verified units)
  - with --fresh-skill: an additional skill with NO active session
    (fresh_skill_id, used by the concurrency QA so the partial-unique-index
    test is not contaminated by a pre-existing active session)

The script is IDEMPOTENT per named entity: re-running against an existing DB
reuses skills/units by name, so the plan's fenced QA block can (1) bootstrap the
DB, then (3) append the fresh skill to the SAME DB for the concurrency case.

Writes JSON to --out with fields: skill_id, unit_id, preview_skill_id,
gold_recall_text [, fresh_skill_id].

Usage:
  python scripts/bootstrap_study_fixture.py --db <path> --out <path> [--fresh-skill]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.processing import connect, ensure_schema  # noqa: E402

GOLD_TEXT = (
    "Raft 通过强领导者简化共识协议。领导者选举使用随机超时选举，多数票胜出。"
    "日志复制由领导者发起，多数确认后提交。"
)
GOLD_QUOTE = "Raft 通过强领导者简化共识协议"
KEY_POINTS = ["强领导者", "多数确认后提交", "随机超时选举"]
MISCONCEPTIONS = ["Raft 使用中心化仲裁者"]
UNIT_CONTENT = "Raft 通过强领导者简化共识协议，日志由领导者复制、多数确认后提交。"
EXAMPLE = "选举时每个节点等待随机超时，先到者发起投票并多数胜出。"
PITFALL = "误以为多数确认发生在提交之前而非复制阶段。"
PREVIEW_TEXT = "预览内容：此技能尚无已验证单元。"

SKILL_VERIFIED_NAME = "Raft 共识算法（已验证）"
SKILL_PREVIEW_NAME = "预览技能（无已验证单元）"
SKILL_FRESH_NAME = "并发测试技能（无活跃会话）"
SKILL_OVERDUE_NAME = "到期复习技能（已到期）"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _insert_skill(con, name: str, description: str = "") -> int:
    """Insert a skill by name; return existing id if the name is already present."""
    row = con.execute("SELECT id FROM skills WHERE name=?", (name,)).fetchone()
    if row is not None:
        return row["id"]
    cur = con.execute(
        "INSERT INTO skills(name, description, created_at, updated_at) VALUES(?,?,?,?)",
        (name, description, _now(), _now()))
    return cur.lastrowid


def _insert_verified_unit(con, skill_id: int, text: str) -> int:
    """Insert gold verified unit; reuse existing verified unit if present."""
    existing = con.execute(
        "SELECT id FROM learning_units WHERE skill_id=? AND status='verified' LIMIT 1",
        (skill_id,)).fetchone()
    if existing is not None:
        return existing["id"]
    quote_start = text.find(GOLD_QUOTE)
    assert quote_start >= 0, "gold quote must appear in material"
    quote_end = quote_start + len(GOLD_QUOTE)
    cur = con.execute(
        "INSERT INTO materials(skill_id, raw_text, normalized_text, content_sha256, created_at) "
        "VALUES(?,?,?,?,?)",
        (skill_id, text, text, "stub-sha256", _now()))
    mid = cur.lastrowid
    cur = con.execute(
        "INSERT INTO learning_units(skill_id, content, source_material, source_start, source_end, "
        "source_quote, key_points, example, pitfall, accepted_misconceptions, status, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (skill_id, UNIT_CONTENT, mid, quote_start, quote_end, GOLD_QUOTE,
         json.dumps(KEY_POINTS, ensure_ascii=False), EXAMPLE, PITFALL,
         json.dumps(MISCONCEPTIONS, ensure_ascii=False), "verified", _now(), _now()))
    uid = cur.lastrowid
    con.execute(
        "INSERT INTO learning_progress(unit_id, progress_status) VALUES(?,?)",
        (uid, "unlearned"))
    return uid


def _insert_preview_unit(con, skill_id: int) -> int:
    cur = con.execute(
        "INSERT INTO learning_units(skill_id, content, key_points, status, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?)",
        (skill_id, PREVIEW_TEXT, json.dumps([], ensure_ascii=False), "preview", _now(), _now()))
    return cur.lastrowid


def _insert_overdue_unit(con, skill_id: int, text: str) -> int:
    """Insert a verified unit whose review is ALREADY due (next_review_at in the past)."""
    existing = con.execute(
        "SELECT id FROM learning_units WHERE skill_id=? AND status='verified' LIMIT 1",
        (skill_id,)).fetchone()
    if existing is not None:
        # ensure its progress is due for review
        con.execute(
            "UPDATE learning_progress SET progress_status='review_due', next_review_at='2000-01-01T00:00:00Z' "
            "WHERE unit_id=?", (existing["id"],))
        return existing["id"]
    uid = _insert_verified_unit(con, skill_id, text)
    con.execute(
        "UPDATE learning_progress SET progress_status='review_due', next_review_at='2000-01-01T00:00:00Z' "
        "WHERE unit_id=?", (uid,))
    return uid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="path to disposable SQLite DB")
    ap.add_argument("--out", required=True, help="path to write fixture JSON")
    ap.add_argument("--fresh-skill", action="store_true",
                    help="additionally create a skill with no active session")
    ap.add_argument("--overdue-skill", action="store_true",
                    help="additionally create a skill with an already-due review unit")
    args = ap.parse_args()

    db = Path(args.db)
    ensure_schema(db)
    con = connect(db)
    try:
        skill_id = _insert_skill(con, SKILL_VERIFIED_NAME, "已验证学习技能")
        unit_id = _insert_verified_unit(con, skill_id, GOLD_TEXT)
        preview_skill_id = _insert_skill(con, SKILL_PREVIEW_NAME, "仅预览内容")
        _insert_preview_unit(con, preview_skill_id)
        fixture = {
            "skill_id": skill_id,
            "unit_id": unit_id,
            "preview_skill_id": preview_skill_id,
            "gold_recall_text": GOLD_TEXT,
        }
        if args.fresh_skill:
            fresh_skill_id = _insert_skill(con, SKILL_FRESH_NAME, "并发测试")
            _insert_verified_unit(con, fresh_skill_id, GOLD_TEXT)
            fixture["fresh_skill_id"] = fresh_skill_id
        if args.overdue_skill:
            overdue_skill_id = _insert_skill(con, SKILL_OVERDUE_NAME, "到期复习")
            overdue_unit_id = _insert_overdue_unit(con, overdue_skill_id, GOLD_TEXT)
            fixture["overdue_skill_id"] = overdue_skill_id
            fixture["overdue_unit_id"] = overdue_unit_id
        con.commit()
    finally:
        con.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fixture, ensure_ascii=False, indent=2))
    print(f"FIXTURE_OK: db={db} out={out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
