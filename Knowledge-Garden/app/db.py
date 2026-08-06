"""db.py — SQLite data layer for the Learning Companion.

Schema (from implementation plan):
  Skill          — id, name, description, growth_value(0-100), decay_rate,
                   last_reviewed_at, status(萌芽/生长中/成熟/衰退), last_decay_at
  Card           — id, skill_id(FK), content, source_material,
                   mastery_level(0-5), last_reviewed_at
  ReviewSession  — id, skill_id(FK), card_ids[], status(进行中/已完成/已放弃),
                   transcript(实时落库), ai_judgment(JSON), user_override,
                   created_at, completed_at

Design notes:
- WAL mode for crash safety + concurrent reads.
- decay is IDEMPOTENT: each skill stores last_decay_at (a DATE). apply_decay
  only applies decay for whole days elapsed since last_decay_at, then advances
  last_decay_at to today. A process restart can never double-apply the same day.
- growth_value only changes on session COMPLETION (not abandonment), enforced
  in the service layer that calls mark_completed().
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, date
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
# LC_DB_PATH 环境变量覆盖（disposable QA / 本地盘避免 NFS 抖动卡死），与 study.py 保持一致
DB_PATH = Path(os.environ.get("LC_DB_PATH", str(DATA_DIR / "learning.db")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# 生长值状态分档
STATUS_BUD = "萌芽"        # 0-30
STATUS_GROWING = "生长中"   # 30-70
STATUS_MATURE = "成熟"      # 70-100
STATUS_DECAYING = "衰退"    # 曾高但持续下降

GROWTH_PER_COMPLETION = 15  # 完成一次复习对话增长值
DECAY_DEFAULT_RATE = 3.0    # 每天默认衰减值


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return date.today().isoformat()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS skills (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL UNIQUE,
            description     TEXT DEFAULT '',
            growth_value    REAL NOT NULL DEFAULT 0,
            decay_rate      REAL NOT NULL DEFAULT 3.0,
            status          TEXT NOT NULL DEFAULT '萌芽',
            last_reviewed_at TEXT,
            last_decay_at   TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cards (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_id        INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
            content         TEXT NOT NULL,
            source_material TEXT DEFAULT '',
            mastery_level   INTEGER NOT NULL DEFAULT 0,
            last_reviewed_at TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cards_skill ON cards(skill_id);

        CREATE TABLE IF NOT EXISTS review_sessions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_id        INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
            status          TEXT NOT NULL DEFAULT '进行中',
            card_ids        TEXT NOT NULL DEFAULT '[]',
            transcript      TEXT NOT NULL DEFAULT '[]',
            ai_judgment     TEXT,
            state_json      TEXT NOT NULL DEFAULT '{}',
            user_override   INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT NOT NULL,
            completed_at    TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_skill ON review_sessions(skill_id);
        """
    )
    conn.commit()
    # 兼容旧库：确保 state_json 列存在
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(review_sessions)").fetchall()}
    if "state_json" not in cols:
        conn.execute("ALTER TABLE review_sessions ADD COLUMN state_json TEXT NOT NULL DEFAULT '{}'")
        conn.commit()
    conn.close()


def _skill_status(growth: float) -> str:
    if growth >= 70:
        return STATUS_MATURE
    if growth >= 30:
        return STATUS_GROWING
    return STATUS_BUD


# ---- Skills ---------------------------------------------------------------

def create_skill(name: str, description: str = "", decay_rate: float = DECAY_DEFAULT_RATE) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO skills (name, description, decay_rate, status, last_decay_at, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (name, description, decay_rate, STATUS_BUD, _today(), _now(), _now()),
    )
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def get_skill(skill_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_skills() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM skills ORDER BY growth_value DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_skill(skill_id: int, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    conn = get_conn()
    conn.execute(f"UPDATE skills SET {cols}, updated_at=? WHERE id=?",
                 (*fields.values(), _now(), skill_id))
    conn.commit()
    conn.close()


def _recompute_status(skill_id: int) -> None:
    """Derive status from growth_value (成熟/生长中/萌芽)."""
    s = get_skill(skill_id)
    if s is None:
        return
    update_skill(skill_id, status=_skill_status(s["growth_value"]))


# ---- Cards ----------------------------------------------------------------

def create_card(skill_id: int, content: str, source_material: str = "") -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO cards (skill_id, content, source_material, created_at, updated_at) VALUES (?,?,?,?,?)",
        (skill_id, content, source_material, _now(), _now()),
    )
    conn.commit()
    cid = cur.lastrowid
    conn.close()
    return cid


def list_cards(skill_id: int | None = None) -> list[dict]:
    conn = get_conn()
    if skill_id is not None:
        rows = conn.execute(
            "SELECT * FROM cards WHERE skill_id=? ORDER BY id", (skill_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM cards ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_card(card_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_card(card_id: int, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    conn = get_conn()
    conn.execute(f"UPDATE cards SET {cols}, updated_at=? WHERE id=?",
                 (*fields.values(), _now(), card_id))
    conn.commit()
    conn.close()


# ---- Review Sessions ------------------------------------------------------

def create_session(skill_id: int, card_ids: list[int]) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO review_sessions (skill_id, card_ids, status, created_at) VALUES (?,?,?,?)",
        (skill_id, json.dumps(card_ids), "进行中", _now()),
    )
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def get_session(session_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM review_sessions WHERE id=?", (session_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    d = dict(row)
    d["card_ids"] = json.loads(d["card_ids"] or "[]")
    d["transcript"] = json.loads(d["transcript"] or "[]")
    d["state_json"] = json.loads(d["state_json"] or "{}")
    if d.get("ai_judgment"):
        d["ai_judgment"] = json.loads(d["ai_judgment"])
    return d


def set_session_state(session_id: int, state: dict) -> None:
    """持久化复习会话的显式状态机（card_index / phase / retries / judged）。"""
    conn = get_conn()
    conn.execute("UPDATE review_sessions SET state_json=? WHERE id=?",
                 (json.dumps(state, ensure_ascii=False), session_id))
    conn.commit()
    conn.close()


def active_session_for_skill(skill_id: int) -> dict | None:
    """同一技能同时只允许一个活跃 session（多端接续的基础）。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM review_sessions WHERE skill_id=? AND status='进行中' ORDER BY id DESC LIMIT 1",
        (skill_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    d = dict(row)
    d["card_ids"] = json.loads(d["card_ids"] or "[]")
    d["transcript"] = json.loads(d["transcript"] or "[]")
    d["state_json"] = json.loads(d["state_json"] or "{}")
    if d.get("ai_judgment"):
        d["ai_judgment"] = json.loads(d["ai_judgment"])
    return d


def list_sessions(skill_id: int | None = None) -> list[dict]:
    conn = get_conn()
    if skill_id is not None:
        rows = conn.execute(
            "SELECT * FROM review_sessions WHERE skill_id=? ORDER BY id DESC", (skill_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM review_sessions ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def append_transcript(session_id: int, entry: dict) -> None:
    """实时落库：每轮对话立即追加，防止中途关页丢数据。"""
    s = get_session(session_id)
    if s is None:
        return
    s["transcript"].append(entry)
    conn = get_conn()
    conn.execute("UPDATE review_sessions SET transcript=? WHERE id=?",
                 (json.dumps(s["transcript"], ensure_ascii=False), session_id))
    conn.commit()
    conn.close()


def set_judgment(session_id: int, judgment: dict, user_override: bool = False) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE review_sessions SET ai_judgment=?, user_override=?, status='进行中' WHERE id=?",
        (json.dumps(judgment, ensure_ascii=False), int(user_override), session_id),
    )
    conn.commit()
    conn.close()


def complete_session(session_id: int) -> dict:
    """标记已完成，并按已完成状态更新 skill growth_value（中途放弃不计入）。"""
    conn = get_conn()
    row = conn.execute(
        "UPDATE review_sessions SET status='已完成', completed_at=? WHERE id=? RETURNING skill_id",
        (_now(), session_id),
    ).fetchone()
    conn.commit()
    conn.close()
    if row is None:
        return {"ok": False, "error": "session not found"}

    skill_id = row["skill_id"]
    growth = get_skill(skill_id)["growth_value"]
    new_growth = min(100.0, growth + GROWTH_PER_COMPLETION)
    update_skill(skill_id, growth_value=new_growth, last_reviewed_at=_now())
    _recompute_status(skill_id)
    return {"ok": True, "skill_id": skill_id, "growth_value": new_growth}


def abandon_session(session_id: int) -> None:
    """标记放弃；growth_value 不更新。"""
    conn = get_conn()
    conn.execute("UPDATE review_sessions SET status='已放弃' WHERE id=?", (session_id,))
    conn.commit()
    conn.close()


# ---- Idempotent decay ------------------------------------------------------

def apply_decay() -> dict:
    """每天对每个技能应用一次衰减（幂等）。

    幂等性原理：skill.last_decay_at 记录上次应用衰减的日期。
    每次只处理 last_decay_at 到今天之间【完整经过】的天数，然后把
    last_decay_at 推进到今天。进程重启后同一天不会重复衰减。
    """
    conn = get_conn()
    rows = conn.execute("SELECT id, growth_value, decay_rate, last_decay_at FROM skills").fetchall()
    today = _today()
    applied = []
    for r in rows:
        last = r["last_decay_at"] or today
        try:
            days = (date.fromisoformat(today) - date.fromisoformat(last)).days
        except ValueError:
            days = 0
        if days >= 1:
            new_growth = max(0.0, r["growth_value"] - r["decay_rate"] * days)
            conn.execute(
                "UPDATE skills SET growth_value=?, last_decay_at=?, updated_at=? WHERE id=?",
                (new_growth, today, _now(), r["id"]),
            )
            applied.append({"skill_id": r["id"], "days": days, "new_growth": round(new_growth, 1)})
    conn.commit()
    conn.close()
    # 重算状态
    for a in applied:
        _recompute_status(a["skill_id"])
    return {"applied": applied, "today": today}


# ---- init ---------------------------------------------------------------

init_db()
