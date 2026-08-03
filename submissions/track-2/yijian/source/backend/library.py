# -*- coding: utf-8 -*-
"""本地单用户棋谱库与教学设置持久化。"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from importers import ImportedGame


BASE = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("GOMENTOR_DB", BASE.parent / "data" / "yijian.db"))


def report_revision(raw: dict) -> str:
    """返回报告当前正文的内容指纹；深算覆盖同一 report id 时会随之变化。"""
    payload = json.dumps(
        raw,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS games (
                id TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL DEFAULT 'mine',
                title TEXT NOT NULL,
                black_name TEXT NOT NULL,
                white_name TEXT NOT NULL,
                black_rank TEXT NOT NULL DEFAULT '',
                white_rank TEXT NOT NULL DEFAULT '',
                aliases_json TEXT NOT NULL DEFAULT '[]',
                event TEXT NOT NULL DEFAULT '',
                played_date TEXT NOT NULL DEFAULT '',
                result TEXT NOT NULL DEFAULT '',
                komi REAL,
                rules TEXT NOT NULL DEFAULT '',
                move_count INTEGER NOT NULL,
                platform TEXT NOT NULL DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]',
                favorite INTEGER NOT NULL DEFAULT 0,
                sgf_text TEXT NOT NULL,
                original_format TEXT NOT NULL,
                source_filename TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                rights TEXT NOT NULL DEFAULT '',
                selection_reason TEXT NOT NULL DEFAULT '',
                is_user_content INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_games_category ON games(category);
            CREATE INDEX IF NOT EXISTS idx_games_date ON games(played_date);
            CREATE TABLE IF NOT EXISTS analysis_cache (
                position_hash TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                engine_version TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS game_reports (
                id TEXT PRIMARY KEY,
                game_id TEXT NOT NULL,
                perspective TEXT NOT NULL,
                signature TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(game_id, perspective, signature),
                FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS analysis_jobs (
                id TEXT PRIMARY KEY,
                game_id TEXT NOT NULL,
                perspective TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'fast',
                signature TEXT NOT NULL,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                progress REAL NOT NULL DEFAULT 0,
                current_turn INTEGER NOT NULL DEFAULT 0,
                total_turns INTEGER NOT NULL DEFAULT 0,
                elapsed_seconds REAL NOT NULL DEFAULT 0,
                eta_seconds REAL,
                rate REAL NOT NULL DEFAULT 0,
                target_seconds REAL NOT NULL DEFAULT 0,
                scan_visits INTEGER NOT NULL DEFAULT 0,
                review_visits INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                report_id TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE,
                FOREIGN KEY(report_id) REFERENCES game_reports(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_reports_game ON game_reports(game_id, perspective);
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON analysis_jobs(status, created_at);
            """
        )
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(analysis_jobs)").fetchall()
        }
        if "mode" not in columns:
            conn.execute(
                "ALTER TABLE analysis_jobs ADD COLUMN mode TEXT NOT NULL DEFAULT 'fast'"
            )
        timing_columns = {
            "elapsed_seconds": "REAL NOT NULL DEFAULT 0",
            "eta_seconds": "REAL",
            "rate": "REAL NOT NULL DEFAULT 0",
            "target_seconds": "REAL NOT NULL DEFAULT 0",
            "scan_visits": "INTEGER NOT NULL DEFAULT 0",
            "review_visits": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, definition in timing_columns.items():
            if name not in columns:
                conn.execute(
                    f"ALTER TABLE analysis_jobs ADD COLUMN {name} {definition}"
                )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row: sqlite3.Row, detail: bool = False) -> dict:
    value = dict(row)
    value["aliases"] = json.loads(value.pop("aliases_json"))
    value["tags"] = json.loads(value.pop("tags_json"))
    value["favorite"] = bool(value["favorite"])
    value["isUserContent"] = bool(value.pop("is_user_content"))
    value["playedDate"] = value.pop("played_date")
    value["blackName"] = value.pop("black_name")
    value["whiteName"] = value.pop("white_name")
    value["blackRank"] = value.pop("black_rank")
    value["whiteRank"] = value.pop("white_rank")
    value["moveCount"] = value.pop("move_count")
    value["originalFormat"] = value.pop("original_format")
    value["sourceFilename"] = value.pop("source_filename")
    value["sourceUrl"] = value.pop("source_url")
    value["selectionReason"] = value.pop("selection_reason")
    value["createdAt"] = value.pop("created_at")
    value["updatedAt"] = value.pop("updated_at")
    value.pop("content_hash", None)
    if not detail:
        value.pop("sgf_text", None)
    else:
        value["sgf"] = value.pop("sgf_text")
    return value


def add_import(game: ImportedGame, *, category: str = "mine", source_url: str = "",
               rights: str = "", reason: str = "", is_user: bool = True) -> tuple[dict, bool]:
    init_db()
    with connect() as conn:
        existing = conn.execute("SELECT * FROM games WHERE content_hash=?", (game.content_hash,)).fetchone()
        if existing:
            aliases = list(dict.fromkeys([
                *json.loads(existing["aliases_json"]), *game.aliases,
            ]))
            conn.execute(
                """
                UPDATE games SET
                  black_name=?, white_name=?,
                  black_rank=CASE WHEN black_rank='' THEN ? ELSE black_rank END,
                  white_rank=CASE WHEN white_rank='' THEN ? ELSE white_rank END,
                  aliases_json=?, result=COALESCE(NULLIF(?,''),result),
                  komi=COALESCE(komi, ?),
                  platform=CASE WHEN platform IN ('','本地棋谱') THEN ? ELSE platform END,
                  updated_at=?
                WHERE id=?
                """,
                (
                    game.black_name, game.white_name, game.black_rank, game.white_rank,
                    json.dumps(aliases, ensure_ascii=False), game.result, game.komi,
                    game.platform, _now(), existing["id"],
                ),
            )
            refreshed = conn.execute("SELECT * FROM games WHERE id=?", (existing["id"],)).fetchone()
            return _row(refreshed, detail=True), False
        game_id = uuid.uuid4().hex
        title = f"{game.black_name} vs {game.white_name}"
        now = _now()
        conn.execute(
            """
            INSERT INTO games (
                id, content_hash, category, title, black_name, white_name, black_rank, white_rank,
                aliases_json, event, played_date, result, komi, rules, move_count, platform,
                tags_json, favorite, sgf_text, original_format, source_filename, source_url,
                rights, selection_reason, is_user_content, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                game_id, game.content_hash, category, title, game.black_name, game.white_name,
                game.black_rank, game.white_rank, json.dumps(game.aliases, ensure_ascii=False),
                game.event, game.date, game.result, game.komi, game.rules, len(game.game.moves),
                game.platform, "[]", 0, game.sgf_text, game.original_format, game.source_filename,
                source_url, rights, reason, int(is_user), now, now,
            ),
        )
        return _row(conn.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone(), detail=True), True


def list_games(category: str = "", query: str = "", sort: str = "recent",
               page: int = 1, page_size: int = 30) -> dict:
    init_db()
    clauses, args = [], []
    if category == "favorites":
        clauses.append("favorite=1")
    elif category:
        clauses.append("category=?")
        args.append(category)
    if query:
        clauses.append(
            "lower(title || ' ' || black_name || ' ' || white_name || ' ' || aliases_json || "
            "' ' || event || ' ' || played_date || ' ' || result || ' ' || platform || ' ' || tags_json) "
            "LIKE lower(?)"
        )
        args.append(f"%{query}%")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    order = {
        "oldest": "played_date ASC, created_at ASC",
        "name": "title COLLATE NOCASE ASC",
        "moves": "move_count DESC",
    }.get(sort, "played_date DESC, created_at DESC")
    page, page_size = max(1, page), min(100, max(1, page_size))
    with connect() as conn:
        total = conn.execute(f"SELECT count(*) FROM games{where}", args).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM games{where} ORDER BY {order} LIMIT ? OFFSET ?",
            (*args, page_size, (page - 1) * page_size),
        ).fetchall()
    return {"items": [_row(row) for row in rows], "total": total, "page": page, "pageSize": page_size}


def get_game(game_id: str) -> dict | None:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    return _row(row, detail=True) if row else None


def update_game(game_id: str, changes: dict) -> dict | None:
    allowed = {}
    if "favorite" in changes:
        allowed["favorite"] = int(bool(changes["favorite"]))
    if "title" in changes and str(changes["title"]).strip():
        allowed["title"] = str(changes["title"]).strip()[:160]
    if "tags" in changes and isinstance(changes["tags"], list):
        allowed["tags_json"] = json.dumps([str(x)[:32] for x in changes["tags"][:20]], ensure_ascii=False)
    if not allowed:
        return get_game(game_id)
    allowed["updated_at"] = _now()
    with connect() as conn:
        conn.execute(
            f"UPDATE games SET {', '.join(f'{key}=?' for key in allowed)} WHERE id=?",
            (*allowed.values(), game_id),
        )
    return get_game(game_id)


def delete_game(game_id: str) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT is_user_content FROM games WHERE id=?", (game_id,)).fetchone()
        if not row or not row["is_user_content"]:
            return False
        conn.execute("DELETE FROM games WHERE id=?", (game_id,))
    return True


def get_setting(key: str, default):
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT value_json FROM app_settings WHERE key=?", (key,)).fetchone()
    return json.loads(row["value_json"]) if row else default


def put_setting(key: str, value) -> None:
    init_db()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO app_settings(key,value_json,updated_at) VALUES(?,?,?)
            ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
            """,
            (key, json.dumps(value, ensure_ascii=False), _now()),
        )


def get_analysis_cache(position_hash: str, engine_version: str) -> dict | None:
    init_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT payload_json FROM analysis_cache WHERE position_hash=? AND engine_version=?",
            (position_hash, engine_version),
        ).fetchone()
    return json.loads(row["payload_json"]) if row else None


def put_analysis_cache(position_hash: str, engine_version: str, payload: dict) -> None:
    init_db()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO analysis_cache(position_hash,payload_json,engine_version,created_at)
            VALUES(?,?,?,?)
            ON CONFLICT(position_hash) DO UPDATE SET
              payload_json=excluded.payload_json,
              engine_version=excluded.engine_version,
              created_at=excluded.created_at
            """,
            (position_hash, json.dumps(payload, ensure_ascii=False), engine_version, _now()),
        )


def get_cached_report(game_id: str, perspective: str, signature: str) -> dict | None:
    init_db()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id, raw_json FROM game_reports
            WHERE game_id=? AND perspective=? AND signature=?
            """,
            (game_id, perspective, signature),
        ).fetchone()
    if not row:
        return None
    raw = json.loads(row["raw_json"])
    return {
        "id": row["id"],
        "revision": report_revision(raw),
        "raw": raw,
    }


def latest_report(game_id: str, perspective: str | None = None) -> dict | None:
    init_db()
    sql = (
        "SELECT id, perspective, signature, raw_json "
        "FROM game_reports WHERE game_id=?"
    )
    args: list = [game_id]
    if perspective:
        sql += " AND perspective=?"
        args.append(perspective)
    sql += " ORDER BY updated_at DESC LIMIT 1"
    with connect() as conn:
        row = conn.execute(sql, args).fetchone()
    if not row:
        return None
    raw = json.loads(row["raw_json"])
    return {
        "id": row["id"], "perspective": row["perspective"],
        "signature": row["signature"], "revision": report_revision(raw),
        "raw": raw,
    }


def get_report(report_id: str, game_id: str | None = None) -> dict | None:
    """按不可变定位符读取报告，并可校验其确属指定棋谱。"""
    init_db()
    sql = (
        "SELECT id, game_id, perspective, signature, raw_json "
        "FROM game_reports WHERE id=?"
    )
    args: list = [report_id]
    if game_id:
        sql += " AND game_id=?"
        args.append(game_id)
    with connect() as conn:
        row = conn.execute(sql, args).fetchone()
    if not row:
        return None
    raw = json.loads(row["raw_json"])
    return {
        "id": row["id"],
        "gameId": row["game_id"],
        "perspective": row["perspective"],
        "signature": row["signature"],
        "revision": report_revision(raw),
        "raw": raw,
    }


def save_report(game_id: str, perspective: str, signature: str, raw: dict) -> str:
    init_db()
    report_id, now = uuid.uuid4().hex, _now()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO game_reports(id,game_id,perspective,signature,raw_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(game_id,perspective,signature) DO UPDATE SET
              raw_json=excluded.raw_json, updated_at=excluded.updated_at
            """,
            (
                report_id, game_id, perspective, signature,
                json.dumps(raw, ensure_ascii=False), now, now,
            ),
        )
        row = conn.execute(
            "SELECT id FROM game_reports WHERE game_id=? AND perspective=? AND signature=?",
            (game_id, perspective, signature),
        ).fetchone()
    return row["id"]


def create_analysis_job(game_id: str, perspective: str, signature: str,
                        total_turns: int, *, status: str = "queued",
                        report_id: str | None = None, mode: str = "fast") -> dict:
    init_db()
    job_id, now = uuid.uuid4().hex, _now()
    progress = 100 if status == "completed" else 0
    stage = "completed" if status == "completed" else "queued"
    message = "已读取本地分析缓存" if status == "completed" else "等待本地 KataGo 分析"
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO analysis_jobs(
              id,game_id,perspective,mode,signature,status,stage,progress,current_turn,total_turns,
              elapsed_seconds,eta_seconds,rate,target_seconds,message,error,report_id,
              scan_visits,review_visits,cancel_requested,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                job_id, game_id, perspective, mode, signature, status, stage, progress, 0,
                total_turns, 0, 0 if status == "completed" else None, 0, 0,
                message, "", report_id, 0, 0, 0, now, now,
            ),
        )
    return get_analysis_job(job_id)


def update_analysis_job(job_id: str, **changes) -> dict | None:
    column_map = {
        "status": "status", "stage": "stage", "progress": "progress",
        "currentTurn": "current_turn", "totalTurns": "total_turns",
        "elapsedSeconds": "elapsed_seconds", "etaSeconds": "eta_seconds",
        "rate": "rate", "targetSeconds": "target_seconds",
        "scanVisits": "scan_visits", "reviewVisits": "review_visits",
        "message": "message", "error": "error", "reportId": "report_id",
        "cancelRequested": "cancel_requested",
    }
    values = {
        column_map[key]: (int(value) if key == "cancelRequested" else value)
        for key, value in changes.items() if key in column_map
    }
    if not values:
        return get_analysis_job(job_id)
    values["updated_at"] = _now()
    with connect() as conn:
        conn.execute(
            f"UPDATE analysis_jobs SET {', '.join(f'{key}=?' for key in values)} WHERE id=?",
            (*values.values(), job_id),
        )
    return get_analysis_job(job_id)


def get_analysis_job(job_id: str) -> dict | None:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM analysis_jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        return None
    value = dict(row)
    for source, target in (
        ("game_id", "gameId"), ("current_turn", "currentTurn"),
        ("total_turns", "totalTurns"), ("report_id", "reportId"),
        ("elapsed_seconds", "elapsedSeconds"), ("eta_seconds", "etaSeconds"),
        ("target_seconds", "targetSeconds"),
        ("scan_visits", "scanVisits"), ("review_visits", "reviewVisits"),
        ("cancel_requested", "cancelRequested"), ("created_at", "createdAt"),
        ("updated_at", "updatedAt"),
    ):
        value[target] = value.pop(source)
    value["cancelRequested"] = bool(value["cancelRequested"])
    return value


def request_cancel(job_id: str) -> dict | None:
    return update_analysis_job(
        job_id, cancelRequested=True, message="正在安全停止本地分析…"
    )


def cancel_requested(job_id: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT cancel_requested FROM analysis_jobs WHERE id=?", (job_id,)
        ).fetchone()
    return bool(row and row["cancel_requested"])


def recover_interrupted_jobs() -> None:
    init_db()
    with connect() as conn:
        conn.execute(
            """
            UPDATE analysis_jobs
            SET status='failed', stage='interrupted',
                error='应用重启导致分析中断，请重新分析', updated_at=?
            WHERE status IN ('queued','running')
            """,
            (_now(),),
        )
