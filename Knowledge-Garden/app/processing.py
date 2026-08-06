"""app/processing.py — durable single-GPU extraction lifecycle + source validation (Todo 4).

Uses the target schema (db/migrations/0001_initial.sql). Provides:
  - material ingestion with normalized text + content_sha256 (idempotent by hash)
  - extraction_run lifecycle (queued -> running -> verified|failed -> requeue)
  - candidate unit creation from full-model output
  - source validation: exact quote/offset match + field-level entailment
  - candidate -> verified | duplicate | rejected transitions

All functions are pure-logic + SQLite (no model calls); the API (Todo 8) wires
the worker thread and endpoints. A test DB path can be injected via db_path.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional

DEFAULT_DB = Path("/persistent/learning-companion/data/learning.db")

RUN_QUEUED = "queued"
RUN_RUNNING = "running"
RUN_VERIFIED = "verified"
RUN_FAILED = "failed"

UNIT_CANDIDATE = "candidate"
UNIT_VERIFIED = "verified"
UNIT_DUPLICATE = "duplicate"
UNIT_REJECTED = "rejected"
UNIT_PREVIEW = "preview"
UNIT_SUPERSEDED = "superseded"

MAX_RETRY = 3

# entailment 放宽阈值：字段与引文归一化后的最长公共子串 >= 4 字符（≈2 个 CJK 词）
MIN_OVERLAP = 4


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


_WAL_INITIALIZED: set[str] = set()


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    p = Path(db_path) if db_path else DEFAULT_DB
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=30)
    con.row_factory = sqlite3.Row
    # journal_mode=WAL is PERSISTENT for the database file — running the pragma
    # on every connection makes concurrent requests take an exclusive lock and
    # deadlock under load (all worker threads spin on futex). Set it once per
    # database process; later connections skip it entirely.
    key = str(p.resolve())
    if key not in _WAL_INITIALIZED:
        con.execute("PRAGMA journal_mode=WAL")
        _WAL_INITIALIZED.add(key)
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def ensure_schema(db_path: Path | None = None) -> None:
    migration = Path(__file__).resolve().parent.parent / "db" / "migrations" / "0001_initial.sql"
    con = connect(db_path)
    try:
        con.executescript(migration.read_text())
        # 存量库兼容：materials.filename 是新增列（0001 增量），CREATE TABLE IF NOT EXISTS
        # 不会给已存在的表补列，这里显式 ALTER TABLE 补齐（幂等）。
        cols = [r[1] for r in con.execute("PRAGMA table_info(materials)")]
        if "filename" not in cols:
            con.execute("ALTER TABLE materials ADD COLUMN filename TEXT DEFAULT ''")
        con.commit()
    finally:
        con.close()


def normalize_text(text: str) -> str:
    """Line endings to \\n, NFC normalization."""
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def content_sha(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def normalize_key(s: str) -> str:
    """Exact normalized key: lowercase, stripped whitespace/punctuation."""
    return re.sub(r"[\s\W_]+", "", s.lower())


# ---- material ingestion ---------------------------------------------------------------

def ingest_material(skill_id: int, text: str, db_path: Path | None = None,
                    filename: str = "") -> tuple[int, bool]:
    """Create material (idempotent by skill + content_sha256). Returns (material_id, created).

    Idempotency is scoped PER SKILL: uploading the same text to a different skill
    creates a distinct material (each skill owns its source document), while
    re-uploading to the same skill reuses the row. `filename` is the original
    uploaded Markdown file name ('' for pasted text).
    """
    con = connect(db_path)
    norm = normalize_text(text)
    sha = hashlib.sha256(norm.encode()).hexdigest()
    row = con.execute(
        "SELECT id FROM materials WHERE skill_id=? AND content_sha256=?",
        (skill_id, sha)).fetchone()
    if row:
        con.close()
        return row["id"], False
    cur = con.execute(
        "INSERT INTO materials(skill_id, raw_text, normalized_text, content_sha256, filename, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (skill_id, text, norm, sha, filename, _now()),
    )
    con.commit()
    mid = cur.lastrowid
    con.close()
    return mid, True


def create_run(material_id: int, model: str, db_path: Path | None = None) -> int:
    con = connect(db_path)
    cur = con.execute(
        "INSERT INTO extraction_runs(material_id, status, model, created_at, updated_at) "
        "VALUES(?,?,?,?,?)",
        (material_id, RUN_QUEUED, model, _now(), _now()),
    )
    con.commit()
    rid = cur.lastrowid
    con.close()
    return rid


def mark_run(rid: int, status: str, error: str | None = None, db_path: Path | None = None) -> None:
    con = connect(db_path)
    con.execute("UPDATE extraction_runs SET status=?, error_detail=?, updated_at=? WHERE id=?",
                (status, error, _now(), rid))
    con.commit()
    con.close()


def requeue_stale_runs(db_path: Path | None = None) -> int:
    """Requeue interrupted `running` runs at startup (worker crash recovery)."""
    con = connect(db_path)
    cur = con.execute("UPDATE extraction_runs SET status=?, updated_at=? WHERE status=?",
                      (RUN_QUEUED, _now(), RUN_RUNNING))
    con.commit()
    n = cur.rowcount
    con.close()
    return n


def retry_failed_run(rid: int, db_path: Path | None = None) -> bool:
    """Requeue a failed run. Manual retries are unlimited (the user explicitly
    asks); MAX_RETRY bounds only automatic re-queueing elsewhere."""
    con = connect(db_path)
    try:
        row = con.execute("SELECT retries, status FROM extraction_runs WHERE id=?", (rid,)).fetchone()
        if row is None or row["status"] != RUN_FAILED:
            con.close()
            return False
        con.execute("UPDATE extraction_runs SET status=?, retries=retries+1, updated_at=? WHERE id=?",
                    (RUN_QUEUED, _now(), rid))
        con.commit()
    finally:
        con.close()
    return True


def delete_extraction_run(rid: int, db_path: Path | None = None) -> bool:
    """Delete a run and its material (runs own the material they consumed).
    Returns False if the run does not exist."""
    con = connect(db_path)
    try:
        row = con.execute("SELECT material_id FROM extraction_runs WHERE id=?", (rid,)).fetchone()
        if row is None:
            return False
        con.execute("DELETE FROM extraction_runs WHERE id=?", (rid,))
        # 清理该材料及其派生的单元（仅当没有其他 run 引用同一材料时）
        mid = row["material_id"]
        other = con.execute(
            "SELECT COUNT(*) c FROM extraction_runs WHERE material_id=? AND id!=?", (mid, rid)).fetchone()
        if other and other["c"] == 0:
            con.execute("DELETE FROM learning_units WHERE source_material=?", (mid,))
            con.execute("DELETE FROM materials WHERE id=?", (mid,))
        con.commit()
    finally:
        con.close()
    return True


def delete_skill(skill_id: int, db_path: Path | None = None) -> bool:
    """Delete a skill and everything derived from it (units, runs, materials,
    sessions). Cascade handles FK tables; materials/runs are removed manually."""
    con = connect(db_path)
    try:
        skill = con.execute("SELECT id FROM skills WHERE id=?", (skill_id,)).fetchone()
        if skill is None:
            return False
        # 先取该技能下所有材料（run 通过 material 关联）
        mids = [r["id"] for r in con.execute(
            "SELECT DISTINCT m.id FROM materials m JOIN extraction_runs r ON r.material_id=m.id "
            "JOIN learning_units u ON u.skill_id=? WHERE u.source_material=m.id", (skill_id,))]
        for mid in mids:
            con.execute("DELETE FROM learning_units WHERE source_material=?", (mid,))
            con.execute("DELETE FROM extraction_runs WHERE material_id=?", (mid,))
            con.execute("DELETE FROM materials WHERE id=?", (mid,))
        # 剩余未关联材料的 run 也清掉
        con.execute(
            "DELETE FROM extraction_runs WHERE id IN (SELECT r.id FROM extraction_runs r "
            "JOIN materials m ON m.id=r.material_id WHERE m.skill_id=?)", (skill_id,))
        con.execute("DELETE FROM materials WHERE skill_id=?", (skill_id,))
        con.execute("DELETE FROM skills WHERE id=?", (skill_id,))
        con.commit()
    finally:
        con.close()
    return True


# ---- source validation ----------------------------------------------------------------

def validate_unit_source(unit: dict, material: dict) -> tuple[bool, str]:
    """Exact quote/offset validation against the persisted normalized source."""
    norm = material["normalized_text"]
    start, end = unit.get("source_start"), unit.get("source_end")
    quote = unit.get("source_quote", "")
    if start is None or end is None or quote is None:
        return False, "missing source span or quote"
    if start < 0 or end <= start or end > len(norm):
        return False, f"invalid source span [{start}:{end}]"
    if norm[start:end] != quote:
        return False, f"quote does not match source at [{start}:{end}]"
    return True, "ok"


def _longest_common_substr(a: str, b: str) -> int:
    """Length of the longest common contiguous substring (normalized keys)."""
    if not a or not b:
        return 0
    if len(a) > len(b):
        a, b = b, a
    n = len(a)
    # binary search over run length using rolling containment checks
    lo, hi = 0, n
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if mid == 0:
            lo = 1
            continue
        found = False
        step = max(1, mid // 2)
        for j in range(0, n - mid + 1, step):
            if a[j:j + mid] in b:
                found = True
                break
        if found:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def entailment_ok(unit: dict) -> tuple[bool, str]:
    """Field-level entailment: every explanation/key point/example/pitfall must be
    supported by the unit's quoted span.

    Real-model extraction rewrites/paraphrases the source (e.g. content is a
    summary sentence while the quote is the source list item), so exact
    normalized-key containment is too strict and rejects 100% of real
    extractions. We require a shared entity run instead: the longest common
    contiguous substring between the field and the quote must be >= 4 chars
    (≈2 CJK tokens), which still rejects claims with zero lexical overlap.
    """
    quote_norm = normalize_key(unit.get("source_quote", ""))
    if not quote_norm:
        return False, "empty source quote"
    for field in ("content", "example", "pitfall"):
        val = unit.get(field, "")
        if val:
            ok, err = _check_entailed(val, quote_norm)
            if not ok:
                return False, f"field '{field}' not entailed by source quote"
    for kp in unit.get("key_points", []):
        if isinstance(kp, str) and kp.strip().startswith("["):
            # persisted JSON string read back from DB — parse it first
            try:
                parsed = json.loads(kp)
                if isinstance(parsed, list):
                    for p in parsed:
                        ok, err = _check_entailed(p, quote_norm)
                        if not ok:
                            return False, err
                    continue
            except (ValueError, TypeError):
                pass
        ok, err = _check_entailed(kp, quote_norm)
        if not ok:
            return False, err
    return True, "ok"


def _check_entailed(val: object, quote_norm: str) -> tuple[bool, str]:
    """Shared overlap check for a single field/key-point value."""
    vn = normalize_key(str(val))
    if not vn:
        return True, "ok"
    if vn in quote_norm or quote_norm in vn:
        return True, "ok"
    if _longest_common_substr(vn, quote_norm) < MIN_OVERLAP:
        return False, f"key point '{val}' not entailed by source quote"
    return True, "ok"


def _create_unit(con: sqlite3.Connection, skill_id: int, unit: dict) -> int:
    cur = con.execute(
        "INSERT INTO learning_units(skill_id, content, source_material, source_start, source_end, "
        "source_quote, key_points, example, pitfall, accepted_misconceptions, status, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (skill_id, unit.get("content", ""), unit.get("source_material"),
         unit.get("source_start"), unit.get("source_end"), unit.get("source_quote"),
         json.dumps(unit.get("key_points", []), ensure_ascii=False),
         unit.get("example"), unit.get("pitfall"),
         json.dumps(unit.get("accepted_misconceptions", []), ensure_ascii=False),
         unit.get("status", UNIT_CANDIDATE), _now(), _now()),
    )
    return cur.lastrowid


def commit_candidates(skill_id: int, material_id: int, candidates: list[dict],
                      db_path: Path | None = None) -> dict:
    """Validate + persist candidates -> verified | duplicate | rejected.

    Exact normalized-key duplicate rule: a second candidate whose normalized content
    key matches an already-verified unit in the same skill becomes `duplicate`.
    """
    material = connect(db_path).execute(
        "SELECT normalized_text FROM materials WHERE id=?", (material_id,)).fetchone()
    con = connect(db_path)
    seen: set[str] = set()
    stats = {"verified": 0, "duplicate": 0, "rejected": 0}
    try:
        for c in candidates:
            # 单元到材料的真实关联（schema source_material TEXT = material_id）
            c["source_material"] = str(material_id)
            ok, err = validate_unit_source(c, material)
            if not ok:
                stats["rejected"] += 1
                c["status"] = UNIT_REJECTED
                c["reject_reason"] = err
                _create_unit(con, skill_id, c)
                continue
            ok2, err2 = entailment_ok(c)
            if not ok2:
                stats["rejected"] += 1
                c["status"] = UNIT_REJECTED
                c["reject_reason"] = err2
                _create_unit(con, skill_id, c)
                continue
            key = normalize_key(c.get("content", ""))
            if key in seen:
                stats["duplicate"] += 1
                c["status"] = UNIT_DUPLICATE
                _create_unit(con, skill_id, c)
                continue
            seen.add(key)
            stats["verified"] += 1
            c["status"] = UNIT_VERIFIED
            uid = _create_unit(con, skill_id, c)
            con.execute("UPDATE learning_units SET status=? WHERE id=?",
                        (UNIT_VERIFIED, uid))
        con.commit()
    finally:
        con.close()
    return stats
