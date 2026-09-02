"""Token 用量记账层（usage_log）。

零依赖（纯标准库 sqlite3）。所有模型调用的 usage 统一入账 ~/.xai/app.db。
source 取值：chat / canvas_execute / grok_build / search / other
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

_DB_PATH = os.path.expanduser("~/.xai/app.db")
_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    session TEXT DEFAULT '',
    model TEXT DEFAULT '',
    provider TEXT DEFAULT '',
    source TEXT DEFAULT 'chat',
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_log(ts);
CREATE INDEX IF NOT EXISTS idx_usage_model ON usage_log(model);
"""

# 云端模型单价（¥/1M tokens），本地模型不计费
_PRICE_PER_M = {
    # model 名关键字 -> (输入单价, 输出单价)
    "deepseek-v4-flash": (1.0, 4.0),
    "deepseek-v4-pro": (4.0, 16.0),
}


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.executescript(_SCHEMA)
    return conn


def record_usage(
    usage: Optional[Dict[str, Any]],
    *,
    session: str = "",
    model: str = "",
    provider: str = "",
    source: str = "chat",
) -> bool:
    """入账一次调用。usage 为 None/空时不入账，返回 False。"""
    if not usage:
        return False
    pt = int(usage.get("prompt_tokens") or 0)
    ct = int(usage.get("completion_tokens") or 0)
    tt = int(usage.get("total_tokens") or (pt + ct))
    if tt <= 0:
        return False
    try:
        with _LOCK:
            conn = _conn()
            try:
                conn.execute(
                    "INSERT INTO usage_log(ts,session,model,provider,source,"
                    "prompt_tokens,completion_tokens,total_tokens) VALUES(?,?,?,?,?,?,?,?)",
                    (time.time(), session or "", model or "", provider or "", source, pt, ct, tt),
                )
                conn.commit()
            finally:
                conn.close()
        return True
    except Exception:
        return False


def _estimate_cost(model: str, pt: int, ct: int) -> Optional[float]:
    m = (model or "").lower()
    for key, (pin, pout) in _PRICE_PER_M.items():
        if key in m:
            return round(pt / 1e6 * pin + ct / 1e6 * pout, 4)
    return None


def get_stats(days: int = 30) -> Dict[str, Any]:
    """聚合统计：总量 / 今日 / 按模型 / 按日 / 按 source。"""
    since = time.time() - days * 86400
    day_start = time.time() - (time.time() % 86400) + time.timezone
    try:
        with _LOCK:
            conn = _conn()
            try:
                total = conn.execute(
                    "SELECT COALESCE(SUM(prompt_tokens),0),COALESCE(SUM(completion_tokens),0),"
                    "COALESCE(SUM(total_tokens),0),COUNT(*) FROM usage_log WHERE ts>=?",
                    (since,),
                ).fetchone()
                today = conn.execute(
                    "SELECT COALESCE(SUM(total_tokens),0),COUNT(*) FROM usage_log "
                    "WHERE ts>=strftime('%s','now','localtime','start of day','utc')",
                ).fetchone()
                by_model = conn.execute(
                    "SELECT model,provider,SUM(prompt_tokens),SUM(completion_tokens),"
                    "SUM(total_tokens),COUNT(*) FROM usage_log WHERE ts>=? "
                    "GROUP BY model ORDER BY SUM(total_tokens) DESC LIMIT 10",
                    (since,),
                ).fetchall()
                by_day = conn.execute(
                    "SELECT date(ts,'unixepoch','localtime') d,SUM(total_tokens) FROM usage_log "
                    "WHERE ts>=? GROUP BY d ORDER BY d DESC LIMIT 14",
                    (since,),
                ).fetchall()
                by_source = conn.execute(
                    "SELECT source,SUM(total_tokens),COUNT(*) FROM usage_log WHERE ts>=? "
                    "GROUP BY source ORDER BY 2 DESC",
                    (since,),
                ).fetchall()
            finally:
                conn.close()
    except Exception as e:
        return {"status": "error", "error": str(e)}

    models = []
    total_cost = 0.0
    has_cost = False
    for m, prov, pt, ct, tt, n in by_model:
        cost = _estimate_cost(m, pt or 0, ct or 0)
        if cost is not None:
            total_cost += cost
            has_cost = True
        models.append({
            "model": m, "provider": prov,
            "prompt_tokens": pt or 0, "completion_tokens": ct or 0,
            "total_tokens": tt or 0, "calls": n,
            "est_cost_cny": cost,
        })
    return {
        "status": "ok",
        "window_days": days,
        "total": {
            "prompt_tokens": total[0], "completion_tokens": total[1],
            "total_tokens": total[2], "calls": total[3],
            "est_cost_cny": round(total_cost, 4) if has_cost else None,
        },
        "today": {"total_tokens": today[0], "calls": today[1]},
        "by_model": models,
        "by_day": [{"date": d, "total_tokens": t} for d, t in by_day],
        "by_source": [{"source": s, "total_tokens": t, "calls": n} for s, t, n in by_source],
    }


def get_recent(limit: int = 50) -> List[Dict[str, Any]]:
    try:
        with _LOCK:
            conn = _conn()
            try:
                rows = conn.execute(
                    "SELECT ts,session,model,provider,source,prompt_tokens,"
                    "completion_tokens,total_tokens FROM usage_log "
                    "ORDER BY id DESC LIMIT ?",
                    (max(1, min(int(limit), 500)),),
                ).fetchall()
            finally:
                conn.close()
    except Exception:
        return []
    return [
        {
            "ts": r[0], "session": r[1], "model": r[2], "provider": r[3],
            "source": r[4], "prompt_tokens": r[5],
            "completion_tokens": r[6], "total_tokens": r[7],
        }
        for r in rows
    ]
