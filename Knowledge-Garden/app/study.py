"""app/study.py — learning, assessment, and review services (Todo 7).

Transcribes the NORMATIVE contract from docs/domain-contract.md §2/§4/§5 (no design
freedom): exact transition table, SM-2 scheduling order, grading contract with
server-recomputed authoritative score, fail-closed grading, idempotency keys,
and the single-active-session partial unique index.

Key guarantees:
  - One SQLite transaction per graded attempt, in the contract's exact order:
    insert attempt -> version-checked progress update -> scheduling -> completion.
  - Idempotency: UNIQUE(session_id, idempotency_key, payload_hash); same key +
    same payload returns the original attempt (no new row); same key + different
    payload -> 409.
  - Single-active-session enforced by the partial unique index
    (skill_id, session_type) WHERE status='active' — a concurrent duplicate
    INSERT fails and the caller resumes the existing active session.
  - Fail-closed grading: malformed/unavailable judgment -> attempt row
    status='failed', NO schedule update, session stays active, retryable error.
  - Starting assessment/review on a skill with no verified units -> 409 and no
    session is created.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import grading, schedule
from .processing import UNIT_PREVIEW, UNIT_VERIFIED, connect, ensure_schema

DEFAULT_DB = Path("/persistent/learning-companion/data/learning.db")

SESSION_LEARN = "learn"
SESSION_ASSESSMENT = "assessment"
SESSION_REVIEW = "review"
SESSION_ACTIVE = "active"
SESSION_COMPLETED = "completed"
SESSION_ABANDONED = "abandoned"

PROG_UNLEARNED = "unlearned"
PROG_LEARNING = "learning"
PROG_ASSESSMENT_DUE = "assessment_due"
PROG_REVIEW_DUE = "review_due"
PROG_MASTERED = "mastered"

STATUS_BUD = "萌芽"
STATUS_GROWING = "生长中"
STATUS_MATURE = "成熟"
STATUS_DECAYING = "衰退"


class StudyError(Exception):
    """Domain error surfaced as an HTTP status by the API layer."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def resolve_db() -> Path:
    return Path(os.environ.get("LC_DB_PATH", str(DEFAULT_DB)))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _payload_hash(recall: str) -> str:
    return hashlib.sha256(recall.encode("utf-8")).hexdigest()


def _unit_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in ("key_points", "accepted_misconceptions"):
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k] or "[]")
            except json.JSONDecodeError:
                d[k] = []
    return d


def _verified_units(con: sqlite3.Connection, skill_id: int) -> list[dict]:
    rows = con.execute(
        "SELECT * FROM learning_units WHERE skill_id=? AND status=? ORDER BY id",
        (skill_id, UNIT_VERIFIED)).fetchall()
    return [_unit_dict(r) for r in rows]


def _preview_units(con: sqlite3.Connection, skill_id: int) -> list[dict]:
    rows = con.execute(
        "SELECT * FROM learning_units WHERE skill_id=? AND status=? ORDER BY id",
        (skill_id, UNIT_PREVIEW)).fetchall()
    return [_unit_dict(r) for r in rows]


def _active_session(con: sqlite3.Connection, skill_id: int, session_type: str) -> Optional[sqlite3.Row]:
    return con.execute(
        "SELECT * FROM study_sessions WHERE skill_id=? AND session_type=? AND status=? LIMIT 1",
        (skill_id, session_type, SESSION_ACTIVE)).fetchone()


def _progress(con: sqlite3.Connection, unit_id: int) -> Optional[sqlite3.Row]:
    return con.execute("SELECT * FROM learning_progress WHERE unit_id=?", (unit_id,)).fetchone()


def _get_or_create_progress(con: sqlite3.Connection, unit_id: int) -> sqlite3.Row:
    row = _progress(con, unit_id)
    if row is None:
        con.execute(
            "INSERT INTO learning_progress(unit_id, progress_status, ease_factor) VALUES(?,?,?)",
            (unit_id, PROG_UNLEARNED, 2.5))
        row = _progress(con, unit_id)
    return row


def _apply_sm2(progress: sqlite3.Row, grade: int, first_assessment: bool) -> dict:
    """SM-2 step per domain-contract §3 (exact order: ease, then interval)."""
    prev_ef = float(progress["ease_factor"])
    prev_reps = int(progress["repetitions"])
    prev_interval = float(progress["interval_days"])
    new_ef = schedule.update_ease(prev_ef, grade)
    if first_assessment:
        new_reps, new_interval = schedule.compute_interval(prev_ef, prev_reps, grade, prev_interval)
        new_status = PROG_REVIEW_DUE
    else:  # review of a review_due unit
        if grade < 3:
            new_reps, new_interval = 0, schedule.FIRST_INTERVAL_DAYS
            new_status = PROG_LEARNING
        else:
            new_reps, new_interval = schedule.compute_interval(prev_ef, prev_reps, grade, prev_interval)
            new_status = PROG_REVIEW_DUE
        if new_status == PROG_REVIEW_DUE and new_reps >= 6 and new_interval >= 30 and grade >= 4:
            new_status = PROG_MASTERED  # terminal
    next_review_at = schedule.due_at(new_interval) if new_status != PROG_MASTERED else None
    return {
        "progress_status": new_status,
        "mastery_level": grade,
        "repetitions": new_reps,
        "ease_factor": round(new_ef, 4),
        "interval_days": float(new_interval),
        "next_review_at": next_review_at.isoformat() if next_review_at else None,
    }


# ---- learning sessions -------------------------------------------------------

def start_learning_session(skill_id: int, db_path: Optional[Path] = None,
                           idempotency_key: Optional[str] = None) -> dict:
    """Create a learn session; mark verified units unlearned->learning.

    Guards: skill exists; at least one VERIFIED unit exists (else 409, no
    session created). Single active session per (skill, 'learn') enforced by the
    partial unique index; a concurrent duplicate INSERT is caught and the
    existing active session is returned (resume semantics).
    """
    db = Path(db_path) if db_path else resolve_db()
    ensure_schema(db)
    con = connect(db)
    try:
        skill = con.execute("SELECT id FROM skills WHERE id=?", (skill_id,)).fetchone()
        if skill is None:
            raise StudyError(404, "skill not found")
        units = _verified_units(con, skill_id)
        if not units:
            raise StudyError(409, "no verified units; learning requires verified content")
        try:
            cur = con.execute(
                "INSERT INTO study_sessions(skill_id, session_type, status, idempotency_key, created_at) "
                "VALUES(?,?,?,?,?)",
                (skill_id, SESSION_LEARN, SESSION_ACTIVE, idempotency_key, _now()))
        except sqlite3.IntegrityError:
            # partial unique index (skill_id, 'learn') WHERE active — resume
            existing = _active_session(con, skill_id, SESSION_LEARN)
            if existing is None:
                raise
            sid = existing["id"]
            resumed = True
        else:
            sid = cur.lastrowid
            resumed = False
        # mark verified units unlearned -> learning
        for u in units:
            prog = _get_or_create_progress(con, u["id"])
            if prog["progress_status"] == PROG_UNLEARNED:
                con.execute(
                    "UPDATE learning_progress SET progress_status=?, progress_version=progress_version+1 "
                    "WHERE unit_id=? AND progress_version=?",
                    (PROG_LEARNING, u["id"], prog["progress_version"]))
        con.commit()
        session = dict(con.execute("SELECT * FROM study_sessions WHERE id=?", (sid,)).fetchone())
        return {"session": session, "units": units, "resumed": resumed}
    finally:
        con.close()


def abandon_session(session_id: int, db_path: Optional[Path] = None) -> dict:
    db = Path(db_path) if db_path else resolve_db()
    ensure_schema(db)
    con = connect(db)
    try:
        cur = con.execute(
            "UPDATE study_sessions SET status=?, completed_at=? WHERE id=? AND status=?",
            (SESSION_ABANDONED, _now(), session_id, SESSION_ACTIVE))
        con.commit()
        if cur.rowcount == 0:
            raise StudyError(404, "no active session to abandon")
        return {"ok": True, "session_id": session_id, "status": SESSION_ABANDONED}
    finally:
        con.close()


# ---- assessment / review submission ------------------------------------------

def _grade_and_record(session_id: int, unit_id: int, idempotency_key: str, recall: str,
                      session_type: str, db_path: Optional[Path], grader) -> dict:
    """Shared atomic assessment/review submission (contract §5 exact order).

    Returns {"attempt": {...}, "progress": {...}, "session": {...}}.
    Raises StudyError(409) for idempotency conflicts / stale versions and
    StudyError(503) for fail-closed grading.
    """
    db = Path(db_path) if db_path else resolve_db()
    ensure_schema(db)
    phash = _payload_hash(recall)

    con = connect(db)
    try:
        session = con.execute("SELECT * FROM study_sessions WHERE id=?", (session_id,)).fetchone()
        if session is None:
            raise StudyError(404, "session not found")

        # idempotency by (session_id, idempotency_key)
        existing = con.execute(
            "SELECT * FROM assessment_attempts WHERE session_id=? AND idempotency_key=?",
            (session_id, idempotency_key)).fetchone()
        if existing is not None:
            if existing["payload_hash"] == phash:
                return {"attempt": dict(existing), "replayed": True}
            raise StudyError(409, "idempotency key already used with a different payload")

        if session["status"] != SESSION_ACTIVE:
            raise StudyError(409, "session is not active (stale or already completed)")

        unit = con.execute("SELECT * FROM learning_units WHERE id=?", (unit_id,)).fetchone()
        if unit is None:
            raise StudyError(404, "unit not found")
        if unit["skill_id"] != session["skill_id"]:
            raise StudyError(409, "unit does not belong to the session's skill")
        if unit["status"] != UNIT_VERIFIED:
            raise StudyError(409, "unit is not verified; verified content is required")
        unit_d = _unit_dict(unit)

        # ---- grading (fail-closed) ----
        try:
            judgment = grader(unit_d, recall)
            matched = judgment.get("matched_key_points", [])
            authoritative = grading.authoritative_score(unit_d, matched)
            needs_retry = bool(judgment.get("needs_retry", False))
            if grading.misconception_hit(unit_d, recall):
                needs_retry = True
        except (grading.GradingUnavailable, grading.GradingMalformed) as e:
            # fail-closed: failed attempt row, NO schedule update, session stays active
            con.execute(
                "INSERT INTO assessment_attempts(session_id, unit_id, idempotency_key, payload_hash, "
                "recall_text, status, needs_retry, created_at) VALUES(?,?,?,?,?,?,?,?)",
                (session_id, unit_id, idempotency_key, phash, recall, "failed", 1, _now()))
            con.commit()
            raise StudyError(503, f"grading unavailable (fail-closed): {e}")

        first_assessment = session["session_type"] in (SESSION_LEARN, SESSION_ASSESSMENT) or \
            (session["session_type"] == SESSION_REVIEW and
             _get_or_create_progress(con, unit_id)["progress_status"] in (PROG_UNLEARNED, PROG_LEARNING, PROG_ASSESSMENT_DUE))

        progress = _get_or_create_progress(con, unit_id)
        expected_version = progress["progress_version"]
        sm2 = _apply_sm2(progress, authoritative, first_assessment)

        # ---- atomic transaction: insert attempt -> version-checked update -> scheduling -> completion ----
        try:
            con.execute("BEGIN IMMEDIATE")
            cur = con.execute(
                "INSERT INTO assessment_attempts(session_id, unit_id, idempotency_key, payload_hash, "
                "recall_text, status, score, mastery_level, needs_retry, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (session_id, unit_id, idempotency_key, phash, recall, "judged",
                 authoritative, sm2["mastery_level"], int(needs_retry), _now()))
            attempt_id = cur.lastrowid
            upd = con.execute(
                "UPDATE learning_progress SET progress_status=?, mastery_level=?, repetitions=?, "
                "ease_factor=?, interval_days=?, next_review_at=?, progress_version=progress_version+1 "
                "WHERE unit_id=? AND progress_version=?",
                (sm2["progress_status"], sm2["mastery_level"], sm2["repetitions"],
                 sm2["ease_factor"], sm2["interval_days"], sm2["next_review_at"],
                 unit_id, expected_version))
            if upd.rowcount != 1:
                raise StudyError(409, "stale progress_version; no double advancement")
            # session completion: all verified units of the skill judged in this session
            verified = con.execute(
                "SELECT COUNT(*) AS c FROM learning_units WHERE skill_id=? AND status=?",
                (session["skill_id"], UNIT_VERIFIED)).fetchone()["c"]
            judged = con.execute(
                "SELECT COUNT(DISTINCT unit_id) AS c FROM assessment_attempts "
                "WHERE session_id=? AND status='judged'", (session_id,)).fetchone()["c"]
            if verified > 0 and judged >= verified:
                con.execute("UPDATE study_sessions SET status=?, completed_at=? WHERE id=?",
                            (SESSION_COMPLETED, _now(), session_id))
            con.commit()
        except StudyError:
            con.rollback()
            raise
        except sqlite3.IntegrityError as e:
            con.rollback()
            # duplicate (session_id, idempotency_key, payload_hash) — replay original
            dup = con.execute(
                "SELECT * FROM assessment_attempts WHERE session_id=? AND idempotency_key=? AND payload_hash=?",
                (session_id, idempotency_key, phash)).fetchone()
            if dup is not None:
                return {"attempt": dict(dup), "replayed": True}
            raise StudyError(409, f"idempotency constraint: {e}") from e

        attempt = dict(con.execute("SELECT * FROM assessment_attempts WHERE id=?", (attempt_id,)).fetchone())
        new_prog = dict(_progress(con, unit_id))
        sess = dict(con.execute("SELECT * FROM study_sessions WHERE id=?", (session_id,)).fetchone())
        return {"attempt": attempt, "progress": new_prog, "session": sess}
    finally:
        con.close()


def submit_assessment(session_id: int, unit_id: int, idempotency_key: str, recall: str,
                      db_path: Optional[Path] = None, grader=grading.call_grader) -> dict:
    return _grade_and_record(session_id, unit_id, idempotency_key, recall,
                             SESSION_ASSESSMENT, db_path, grader)


def submit_review(session_id: int, unit_id: int, idempotency_key: str, recall: str,
                  db_path: Optional[Path] = None, grader=grading.call_grader) -> dict:
    return _grade_and_record(session_id, unit_id, idempotency_key, recall,
                             SESSION_REVIEW, db_path, grader)


def start_review_session(skill_id: int, db_path: Optional[Path] = None) -> dict:
    """Create (or resume) a due-review session (hide answer content; source-grounded prompts).

    409 when the skill has no verified units or nothing is due; no session is
    created in either case. A second call for the same skill resumes the existing
    active review session (partial unique index) instead of failing.
    """
    db = Path(db_path) if db_path else resolve_db()
    ensure_schema(db)
    con = connect(db)
    try:
        skill = con.execute("SELECT id FROM skills WHERE id=?", (skill_id,)).fetchone()
        if skill is None:
            raise StudyError(404, "skill not found")
        now = _now()
        due = con.execute(
            "SELECT u.id, u.source_quote, u.source_start, u.source_end, u.content "
            "FROM learning_units u JOIN learning_progress p ON p.unit_id = u.id "
            "WHERE u.skill_id=? AND u.status=? AND p.progress_status=? AND p.next_review_at IS NOT NULL "
            "AND p.next_review_at <= ? ORDER BY u.id",
            (skill_id, UNIT_VERIFIED, PROG_REVIEW_DUE, now)).fetchall()
        if not due:
            raise StudyError(409, "no verified units due for review; nothing to review")
        # resume existing active review session if present (partial unique index)
        existing = _active_session(con, skill_id, SESSION_REVIEW)
        if existing is not None:
            sid = existing["id"]
            resumed = True
        else:
            cur = con.execute(
                "INSERT INTO study_sessions(skill_id, session_type, status, created_at) VALUES(?,?,?,?)",
                (skill_id, SESSION_REVIEW, SESSION_ACTIVE, _now()))
            sid = cur.lastrowid
            resumed = False
        con.commit()
        # hide answer content: return only source-grounded recall prompt material
        units = [{
            "id": r["id"],
            "source_quote": r["source_quote"],
            "source_start": r["source_start"],
            "source_end": r["source_end"],
        } for r in due]
        session = dict(con.execute("SELECT * FROM study_sessions WHERE id=?", (sid,)).fetchone())
        return {"session": session, "units": units, "resumed": resumed}
    finally:
        con.close()


def override_review(session_id: int, unit_id: int, db_path: Optional[Path] = None) -> dict:
    """One user override with recorded audit: grade=3, interval capped at 3 days.

    Records an audited attempt (idempotency_key='__override__') so the override
    is permanently observable.
    """
    db = Path(db_path) if db_path else resolve_db()
    ensure_schema(db)
    con = connect(db)
    try:
        session = con.execute("SELECT * FROM study_sessions WHERE id=?", (session_id,)).fetchone()
        if session is None:
            raise StudyError(404, "session not found")
        if session["status"] != SESSION_ACTIVE:
            raise StudyError(409, "session is not active")
        unit = con.execute("SELECT * FROM learning_units WHERE id=?", (unit_id,)).fetchone()
        if unit is None or unit["skill_id"] != session["skill_id"] or unit["status"] != UNIT_VERIFIED:
            raise StudyError(409, "unit is not verified for this session")

        progress = _get_or_create_progress(con, unit_id)
        expected_version = progress["progress_version"]
        prev_ef = float(progress["ease_factor"])
        prev_reps = int(progress["repetitions"])
        prev_interval = float(progress["interval_days"])
        grade = schedule.override_grade()  # 3
        new_ef = schedule.update_ease(prev_ef, grade)
        new_reps, new_interval = schedule.compute_interval(prev_ef, prev_reps, grade, prev_interval)
        new_interval = min(new_interval, schedule.override_interval_cap())  # cap 3 days
        next_at = schedule.due_at(new_interval)
        try:
            con.execute("BEGIN IMMEDIATE")
            cur = con.execute(
                "INSERT INTO assessment_attempts(session_id, unit_id, idempotency_key, payload_hash, "
                "recall_text, status, score, mastery_level, needs_retry, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (session_id, unit_id, "__override__", "override", "<user_override_audit>",
                 "judged", grade, grade, 0, _now()))
            upd = con.execute(
                "UPDATE learning_progress SET progress_status=?, mastery_level=?, repetitions=?, "
                "ease_factor=?, interval_days=?, next_review_at=?, progress_version=progress_version+1 "
                "WHERE unit_id=? AND progress_version=?",
                (PROG_REVIEW_DUE, grade, new_reps, round(new_ef, 4), new_interval,
                 next_at.isoformat(), unit_id, expected_version))
            if upd.rowcount != 1:
                raise StudyError(409, "stale progress_version; override rejected")
            con.commit()
        except StudyError:
            con.rollback()
            raise
        attempt = dict(con.execute("SELECT * FROM assessment_attempts WHERE id=?", (cur.lastrowid,)).fetchone())
        return {"attempt": attempt, "progress": dict(_progress(con, unit_id))}
    finally:
        con.close()


# ---- garden summary (derived values, no client-provided mastery) -------------

def compute_garden(skill_id: int, db_path: Optional[Path] = None) -> dict:
    """Derived garden growth/status per domain-contract §3 formula."""
    db = Path(db_path) if db_path else resolve_db()
    ensure_schema(db)
    con = connect(db)
    try:
        skill = con.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
        if skill is None:
            raise StudyError(404, "skill not found")
        units = _verified_units(con, skill_id)
        total = len(units)
        if total == 0:
            return {"skill_id": skill_id, "name": skill["name"], "growth_value": 0,
                    "status": STATUS_BUD, "learned_verified": 0, "total_verified": 0,
                    "overdue_count": 0}
        learned = 0
        masteries: list[int] = []
        overdue = 0
        now = _now()
        for u in units:
            p = _progress(con, u["id"])
            if p is None:
                continue
            if p["progress_status"] != PROG_UNLEARNED:
                learned += 1
            masteries.append(int(p["mastery_level"] or 0))
            if p["next_review_at"] is not None and p["next_review_at"] < now:
                overdue += 1
        growth = schedule.growth_value(total, learned, masteries, overdue)
        status = STATUS_DECAYING if overdue > 0 else (
            STATUS_MATURE if growth >= 70 else (STATUS_GROWING if growth >= 30 else STATUS_BUD))
        return {"skill_id": skill_id, "name": skill["name"], "growth_value": growth,
                "status": status, "learned_verified": learned, "total_verified": total,
                "overdue_count": overdue}
    finally:
        con.close()


def list_gardens(db_path: Optional[Path] = None) -> list[dict]:
    """Derived garden summaries for all skills (garden list view).

    Uses a SINGLE connection + bulk queries (avoids N+1 connect overhead that
    made the garden list ~2s for several skills).
    """
    db = Path(db_path) if db_path else resolve_db()
    ensure_schema(db)
    con = connect(db)
    try:
        skills = con.execute("SELECT id, name FROM skills ORDER BY id").fetchall()
        # bulk load verified units per skill + their progress in one pass
        units = con.execute(
            "SELECT u.id, u.skill_id, p.progress_status AS ps, p.mastery_level AS ml, "
            "p.next_review_at AS nra "
            "FROM learning_units u LEFT JOIN learning_progress p ON p.unit_id = u.id "
            "WHERE u.status=? ORDER BY u.skill_id, u.id", (UNIT_VERIFIED,)).fetchall()
        by_skill: dict[int, list] = {}
        for u in units:
            by_skill.setdefault(u["skill_id"], []).append(u)
        now = _now()
        out = []
        for s in skills:
            sid = s["id"]
            sunits = by_skill.get(sid, [])
            total = len(sunits)
            if total == 0:
                out.append({"skill_id": sid, "name": s["name"], "growth_value": 0,
                            "status": STATUS_BUD, "learned_verified": 0,
                            "total_verified": 0, "overdue_count": 0})
                continue
            learned = sum(1 for u in sunits if u["ps"] != PROG_UNLEARNED)
            masteries = [int(u["ml"] or 0) for u in sunits]
            overdue = sum(1 for u in sunits
                          if u["nra"] is not None and u["nra"] < now)
            growth = schedule.growth_value(total, learned, masteries, overdue)
            status = STATUS_DECAYING if overdue > 0 else (
                STATUS_MATURE if growth >= 70 else
                (STATUS_GROWING if growth >= 30 else STATUS_BUD))
            out.append({"skill_id": sid, "name": s["name"], "growth_value": growth,
                        "status": status, "learned_verified": learned,
                        "total_verified": total, "overdue_count": overdue})
        return out
    finally:
        con.close()
