"""SQLite 任务存储"""
import json
import sqlite3
import time
import uuid
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "jobs.db"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                workflow TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                params TEXT DEFAULT '{}',
                prompt_id TEXT,
                outputs TEXT,
                error TEXT,
                created_at REAL NOT NULL,
                batch TEXT DEFAULT ''
            )
            """
        )
        cols = [r[1] for r in conn.execute("PRAGMA table_info(jobs)")]
        if "batch" not in cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN batch TEXT DEFAULT ''")


def create_job(workflow: str, params: dict, batch: str = "") -> str:
    job_id = uuid.uuid4().hex[:12]
    with _conn() as conn:
        conn.execute(
            "INSERT INTO jobs (id, workflow, status, params, created_at, batch) VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, workflow, "queued", json.dumps(params, ensure_ascii=False), time.time(), batch),
        )
    return job_id


def get_job(job_id: str):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    job = dict(row)
    job["params"] = json.loads(job["params"] or "{}")
    job["outputs"] = json.loads(job["outputs"] or "[]")
    return job


def update_job(job_id: str, **fields) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    with _conn() as conn:
        conn.execute(f"UPDATE jobs SET {sets} WHERE id = ?", (*fields.values(), job_id))


def list_jobs(limit: int = 20, batch: str = ""):
    with _conn() as conn:
        if batch:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE batch = ? ORDER BY created_at DESC LIMIT ?", (batch, limit)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    jobs = []
    for row in rows:
        job = dict(row)
        job["params"] = json.loads(job["params"] or "{}")
        job["outputs"] = json.loads(job["outputs"] or "[]")
        jobs.append(job)
    return jobs
