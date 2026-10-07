"""SQLite audit database — queryable detail store for independent auditability.

Complements audit_log.jsonl (tamper-evident chain) with structured, queryable
records of every calculation, LLM call, and agent execution.

Auditors can open output/finveritas.db with DB Browser for SQLite and query
any run, agent, or LLM prompt/response without touching the application code.
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

_DEFAULT_DB = Path("output/finveritas.db")
_lock = Lock()


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id            TEXT PRIMARY KEY,
    ts                TEXT NOT NULL,
    entity            TEXT,
    source_type       TEXT,
    credibility_score INTEGER,
    input_hash        TEXT,
    consent_timestamp TEXT
);

CREATE TABLE IF NOT EXISTS agent_executions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT REFERENCES runs(run_id),
    agent_name    TEXT NOT NULL,
    status        TEXT NOT NULL,
    metrics_json  TEXT,
    analysis_text TEXT,
    error_message TEXT,
    duration_ms   INTEGER
);

CREATE TABLE IF NOT EXISTS llm_calls (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           TEXT REFERENCES runs(run_id),
    agent_name       TEXT NOT NULL,
    attempt          INTEGER DEFAULT 1,
    model            TEXT,
    base_url         TEXT,
    system_prompt    TEXT,
    human_prompt     TEXT,
    response_text    TEXT,
    violations_found TEXT,
    duration_ms      INTEGER,
    ts               TEXT
);
"""


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init(path: Path) -> None:
    with _lock:
        conn = _connect(path)
        conn.executescript(_SCHEMA)
        conn.commit()
        conn.close()


# ── Write helpers ─────────────────────────────────────────────────────────────

def log_run(
    *,
    run_id: str,
    entity: str,
    source_type: str,
    credibility_score: int | None,
    input_hash: str | None,
    consent_timestamp: str | None,
    db_path: Path | None = None,
) -> None:
    path = db_path or _DEFAULT_DB
    _init(path)
    with _lock:
        conn = _connect(path)
        conn.execute(
            "INSERT OR IGNORE INTO runs "
            "(run_id, ts, entity, source_type, credibility_score, input_hash, consent_timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, datetime.now(timezone.utc).isoformat(),
             entity, source_type, credibility_score, input_hash, consent_timestamp),
        )
        conn.commit()
        conn.close()


def log_agent(
    *,
    run_id: str,
    agent_name: str,
    status: str,
    metrics: dict[str, Any] | None = None,
    analysis_text: str | None = None,
    error_message: str | None = None,
    duration_ms: int | None = None,
    db_path: Path | None = None,
) -> None:
    path = db_path or _DEFAULT_DB
    _init(path)
    with _lock:
        conn = _connect(path)
        conn.execute(
            "INSERT INTO agent_executions "
            "(run_id, agent_name, status, metrics_json, analysis_text, error_message, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, agent_name, status,
             json.dumps(metrics, ensure_ascii=False) if metrics is not None else None,
             analysis_text, error_message, duration_ms),
        )
        conn.commit()
        conn.close()


def log_llm_call(
    *,
    run_id: str,
    agent_name: str,
    attempt: int,
    model: str,
    base_url: str,
    system_prompt: str,
    human_prompt: str,
    response_text: str,
    violations_found: list[str] | None = None,
    duration_ms: int | None = None,
    db_path: Path | None = None,
) -> None:
    path = db_path or _DEFAULT_DB
    _init(path)
    with _lock:
        conn = _connect(path)
        conn.execute(
            "INSERT INTO llm_calls "
            "(run_id, agent_name, attempt, model, base_url, system_prompt, human_prompt, "
            "response_text, violations_found, duration_ms, ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, agent_name, attempt, model, base_url,
             system_prompt, human_prompt, response_text,
             json.dumps(violations_found) if violations_found else None,
             duration_ms, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()


# ── LLM call instrumentation ──────────────────────────────────────────────────

def instrumented_invoke(
    llm: Any,
    messages: list,
    *,
    run_id: str | None,
    agent_name: str,
    model: str,
    base_url: str,
    attempt: int = 1,
    violations_found: list[str] | None = None,
    db_path: Path | None = None,
) -> Any:
    """Wrap llm.invoke(), log the call, and return the response unchanged."""
    t0 = time.monotonic()
    resp = llm.invoke(messages)
    duration_ms = int((time.monotonic() - t0) * 1000)

    if run_id:
        sys_text = next(
            (getattr(m, "content", "") for m in messages if type(m).__name__ == "SystemMessage"), ""
        )
        human_text = next(
            (getattr(m, "content", "") for m in messages if type(m).__name__ == "HumanMessage"), ""
        )
        try:
            log_llm_call(
                run_id=run_id,
                agent_name=agent_name,
                attempt=attempt,
                model=model,
                base_url=base_url,
                system_prompt=sys_text,
                human_prompt=human_text,
                response_text=getattr(resp, "content", "") or "",
                violations_found=violations_found,
                duration_ms=duration_ms,
                db_path=db_path,
            )
        except Exception:
            pass

    return resp


# ── Read helpers ──────────────────────────────────────────────────────────────

def query_runs(db_path: Path | None = None) -> list[dict[str, Any]]:
    path = db_path or _DEFAULT_DB
    if not path.exists():
        return []
    conn = _connect(path)
    rows = conn.execute("SELECT * FROM runs ORDER BY ts DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_run_agents(run_id: str, db_path: Path | None = None) -> list[dict[str, Any]]:
    path = db_path or _DEFAULT_DB
    if not path.exists():
        return []
    conn = _connect(path)
    rows = conn.execute(
        "SELECT * FROM agent_executions WHERE run_id = ? ORDER BY id", (run_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_run_llm_calls(run_id: str, db_path: Path | None = None) -> list[dict[str, Any]]:
    path = db_path or _DEFAULT_DB
    if not path.exists():
        return []
    conn = _connect(path)
    rows = conn.execute(
        "SELECT * FROM llm_calls WHERE run_id = ? ORDER BY id", (run_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
