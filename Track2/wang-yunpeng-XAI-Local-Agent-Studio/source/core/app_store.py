#!/usr/bin/env python3
"""XAI 应用层持久化（任务 / 专家团 / 自动化 / 定时任务 / 画布）。

纯 SQLite，存于 $XAI_HOME/app.db（默认 ~/.xai/app.db）。
与 engine 解耦：本模块不 import engine，可被 server 独立调用与单测。
线程安全：每次操作新建连接（本地小数据，开销可忽略），避免 sqlite 跨线程问题。
"""
from __future__ import annotations
import os
import json
import time
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id          TEXT PRIMARY KEY,
  title       TEXT NOT NULL,
  description TEXT DEFAULT '',
  assignee    TEXT DEFAULT '',
  priority    TEXT DEFAULT 'normal',
  status      TEXT DEFAULT 'todo',
  due         TEXT DEFAULT '',
  created_at  TEXT,
  updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS teams (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  description TEXT DEFAULT '',
  members     TEXT DEFAULT '[]',
  created_at  TEXT
);
CREATE TABLE IF NOT EXISTS automations (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  trigger     TEXT DEFAULT '{}',
  actions     TEXT DEFAULT '[]',
  enabled     INTEGER DEFAULT 1,
  created_at  TEXT
);
CREATE TABLE IF NOT EXISTS schedules (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  frequency   TEXT DEFAULT 'daily',
  run_time    TEXT DEFAULT '09:00',
  prompt      TEXT DEFAULT '',
  task_ref    TEXT DEFAULT '',
  enabled     INTEGER DEFAULT 1,
  last_run    TEXT DEFAULT '',
  next_run    TEXT DEFAULT '',
  created_at  TEXT
);
CREATE TABLE IF NOT EXISTS canvas (
  id          TEXT PRIMARY KEY,
  nodes       TEXT DEFAULT '[]',
  edges       TEXT DEFAULT '[]',
  updated_at  TEXT,
  version     INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS canvas_history (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  canvas_id   TEXT NOT NULL,
  version     INTEGER NOT NULL,
  nodes       TEXT DEFAULT '[]',
  edges       TEXT DEFAULT '[]',
  created_at  TEXT
);
CREATE TABLE IF NOT EXISTS settings (
  key         TEXT PRIMARY KEY,
  value       TEXT NOT NULL,
  updated_at  TEXT
);
"""

# 自动化的扩展列（Phase B：对标 Coze 触发器 / WorkBuddy 自动化）
_AUTOMATION_COLS = [
    "timezone TEXT DEFAULT ''",
    "task_type TEXT DEFAULT 'prompt'",
    "prompt TEXT DEFAULT ''",
    "plugin_id TEXT DEFAULT ''",
    "workflow_id TEXT DEFAULT ''",
    "channels TEXT DEFAULT '[]'",
    "memory_enabled INTEGER DEFAULT 1",
    "retry INTEGER DEFAULT 0",
    "timeout INTEGER DEFAULT 120",
    "last_run TEXT DEFAULT ''",
    "next_run TEXT DEFAULT ''",
    "run_count INTEGER DEFAULT 0",
    "run_history TEXT DEFAULT '[]'",
]
# 定时任务的扩展列
_SCHEDULE_COLS = [
    "cron TEXT DEFAULT ''",
    "timezone TEXT DEFAULT ''",
    "task_type TEXT DEFAULT 'prompt'",
    "plugin_id TEXT DEFAULT ''",
    "workflow_id TEXT DEFAULT ''",
    "channels TEXT DEFAULT '[]'",
    "memory_enabled INTEGER DEFAULT 1",
    "retry INTEGER DEFAULT 0",
    "timeout INTEGER DEFAULT 120",
    "run_count INTEGER DEFAULT 0",
    "run_history TEXT DEFAULT '[]'",
]

# 设置项默认值（前端 Settings → 后端 的落点）
_SETTINGS_DEFAULTS = {
    "scheduler.timezone": "Asia/Shanghai",
    "scheduler.retry": "0",
    "scheduler.timeout": "120",
    "forward.channels": "[]",
    "governance.p0_confirm": "true",
    "features.thinking_viz": "true",
    "features.iteration_branch": "true",
    "features.canvas_exec": "true",
}


def _db_path() -> str:
    home = os.environ.get("XAI_HOME", os.path.expanduser("~/.xai"))
    os.makedirs(home, exist_ok=True)
    return os.path.join(home, "app.db")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_db_path())
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    c = _conn()
    try:
        c.executescript(_SCHEMA)
        for col in _AUTOMATION_COLS:
            name = col.split()[0]
            try:
                c.execute(f"ALTER TABLE automations ADD COLUMN {col}")
            except Exception:
                pass  # 已存在则忽略
        for col in _SCHEDULE_COLS:
            name = col.split()[0]
            try:
                c.execute(f"ALTER TABLE schedules ADD COLUMN {col}")
            except Exception:
                pass
        # canvas version 列迁移
        try:
            c.execute("ALTER TABLE canvas ADD COLUMN version INTEGER DEFAULT 1")
        except Exception:
            pass
        # 设置项默认种子
        for k, v in _SETTINGS_DEFAULTS.items():
            if not c.execute("SELECT 1 FROM settings WHERE key=?", (k,)).fetchone():
                c.execute("INSERT INTO settings (key,value,updated_at) VALUES (?,?,?)",
                          (k, v, _now()))
        c.commit()
    finally:
        c.close()


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _uid(prefix: str) -> str:
    return f"{prefix}:{int(time.time()*1000)}:{os.urandom(3).hex()}"


def _load(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    for k in ("members", "trigger", "actions", "nodes", "edges", "channels", "run_history"):
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                d[k] = [] if k in ("members", "actions", "nodes", "edges", "channels", "run_history") else {}
    # 布尔/数字兼容
    for bk in ("enabled", "memory_enabled"):
        if bk in d:
            d[bk] = bool(d[bk])
    return d


def _j(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ---------------- Tasks ----------------

def tasks_list() -> List[Dict[str, Any]]:
    c = _conn()
    try:
        rows = c.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
        return [_load(r) for r in rows]
    finally:
        c.close()


def task_get(tid: str) -> Optional[Dict[str, Any]]:
    c = _conn()
    try:
        r = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        return _load(r) if r else None
    finally:
        c.close()


def task_create(data: Dict[str, Any]) -> Dict[str, Any]:
    tid = data.get("id") or _uid("task")
    now = _now()
    c = _conn()
    try:
        c.execute(
            """INSERT INTO tasks (id,title,description,assignee,priority,status,due,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (tid, data.get("title", "未命名任务"), data.get("description", ""),
             data.get("assignee", ""), data.get("priority", "normal"),
             data.get("status", "todo"), data.get("due", ""), now, now),
        )
        c.commit()
    finally:
        c.close()
    return task_get(tid)


def task_update(tid: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    existing = task_get(tid)
    if not existing:
        return None
    merged = {**existing, **{k: v for k, v in data.items() if v is not None}}
    c = _conn()
    try:
        c.execute(
            """UPDATE tasks SET title=?,description=?,assignee=?,priority=?,status=?,due=?,updated_at=?
               WHERE id=?""",
            (merged["title"], merged["description"], merged["assignee"], merged["priority"],
             merged["status"], merged["due"], _now(), tid),
        )
        c.commit()
    finally:
        c.close()
    return task_get(tid)


def task_delete(tid: str) -> bool:
    c = _conn()
    try:
        cur = c.execute("DELETE FROM tasks WHERE id=?", (tid,))
        c.commit()
        return cur.rowcount > 0
    finally:
        c.close()


# ---------------- Teams ----------------

def teams_list() -> List[Dict[str, Any]]:
    c = _conn()
    try:
        rows = c.execute("SELECT * FROM teams ORDER BY created_at DESC").fetchall()
        return [_load(r) for r in rows]
    finally:
        c.close()


def team_create(data: Dict[str, Any]) -> Dict[str, Any]:
    tid = data.get("id") or _uid("team")
    members = data.get("members", [])
    if not isinstance(members, list):
        members = []
    c = _conn()
    try:
        c.execute(
            "INSERT INTO teams (id,name,description,members,created_at) VALUES (?,?,?,?,?)",
            (tid, data.get("name", "未命名团队"), data.get("description", ""), _j(members), _now()),
        )
        c.commit()
    finally:
        c.close()
    return team_get(tid)


def team_get(tid: str) -> Optional[Dict[str, Any]]:
    c = _conn()
    try:
        r = c.execute("SELECT * FROM teams WHERE id=?", (tid,)).fetchone()
        return _load(r) if r else None
    finally:
        c.close()


def team_delete(tid: str) -> bool:
    c = _conn()
    try:
        cur = c.execute("DELETE FROM teams WHERE id=?", (tid,))
        c.commit()
        return cur.rowcount > 0
    finally:
        c.close()


def team_update(tid: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    existing = team_get(tid)
    if not existing:
        return None
    merged = {**existing, **{k: v for k, v in data.items() if v is not None}}
    members = merged.get("members", [])
    if not isinstance(members, list):
        members = []
    c = _conn()
    try:
        c.execute(
            "UPDATE teams SET name=?,description=?,members=? WHERE id=?",
            (merged["name"], merged.get("description", ""), _j(members), tid),
        )
        c.commit()
    finally:
        c.close()
    return team_get(tid)


# ---------------- Automations ----------------

def automations_list() -> List[Dict[str, Any]]:
    c = _conn()
    try:
        rows = c.execute("SELECT * FROM automations ORDER BY created_at DESC").fetchall()
        return [_load(r) for r in rows]
    finally:
        c.close()


def _compute_auto_next(trigger: Dict[str, Any]) -> str:
    ttype = trigger.get("type", "schedule")
    if ttype != "schedule":
        return ""
    cron = trigger.get("cron", "")
    if not cron:
        return ""
    tz = trigger.get("timezone") or settings_get_value("scheduler.timezone", "Asia/Shanghai")
    from core import cronutil
    dt = cronutil.next_run(cron, tz)
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""


def automation_create(data: Dict[str, Any]) -> Dict[str, Any]:
    aid = data.get("id") or _uid("auto")
    trigger = data.get("trigger") or {}
    if not isinstance(trigger, dict):
        trigger = {}
    actions = data.get("actions") or []
    if not isinstance(actions, list):
        actions = []
    channels = data.get("channels") or []
    if not isinstance(channels, list):
        channels = []
    cron = trigger.get("cron", "")
    tz = trigger.get("timezone") or settings_get_value("scheduler.timezone", "Asia/Shanghai")
    next_run = _compute_auto_next(trigger)
    c = _conn()
    try:
        c.execute(
            """INSERT INTO automations
               (id,name,trigger,actions,enabled,timezone,task_type,prompt,plugin_id,workflow_id,
                channels,memory_enabled,retry,timeout,last_run,next_run,run_count,run_history,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (aid, data.get("name", "未命名自动化"), _j(trigger), _j(actions),
             1 if data.get("enabled", True) else 0,
             tz, data.get("task_type", "prompt"), data.get("prompt", ""),
             data.get("plugin_id", ""), data.get("workflow_id", ""),
             _j(channels), 1 if data.get("memory_enabled", True) else 0,
             int(data.get("retry", 0)), int(data.get("timeout", 120)),
             "", next_run, 0, "[]", _now()),
        )
        c.commit()
    finally:
        c.close()
    return automation_get(aid)


def automation_get(aid: str) -> Optional[Dict[str, Any]]:
    c = _conn()
    try:
        r = c.execute("SELECT * FROM automations WHERE id=?", (aid,)).fetchone()
        return _load(r) if r else None
    finally:
        c.close()


def automation_update(aid: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    existing = automation_get(aid)
    if not existing:
        return None
    merged = {**existing, **{k: v for k, v in data.items() if v is not None}}
    trigger = merged.get("trigger", {})
    actions = merged.get("actions", [])
    if not isinstance(trigger, dict):
        trigger = {}
    if not isinstance(actions, list):
        actions = []
    channels = merged.get("channels", [])
    if not isinstance(channels, list):
        channels = []
    next_run = _compute_auto_next(trigger) if data.get("trigger") is not None else merged.get("next_run", "")
    c = _conn()
    try:
        c.execute(
            """UPDATE automations
               SET name=?,trigger=?,actions=?,enabled=?,timezone=?,task_type=?,prompt=?,
                   plugin_id=?,workflow_id=?,channels=?,memory_enabled=?,retry=?,timeout=?,next_run=?
               WHERE id=?""",
            (merged["name"], _j(trigger), _j(actions),
             1 if merged.get("enabled", True) else 0,
             trigger.get("timezone") or merged.get("timezone", "") or settings_get_value("scheduler.timezone", "Asia/Shanghai"),
             merged.get("task_type", "prompt"), merged.get("prompt", ""),
             merged.get("plugin_id", ""), merged.get("workflow_id", ""),
             _j(channels), 1 if merged.get("memory_enabled", True) else 0,
             int(merged.get("retry", 0)), int(merged.get("timeout", 120)),
             next_run, aid),
        )
        c.commit()
    finally:
        c.close()
    return automation_get(aid)


def automation_delete(aid: str) -> bool:
    c = _conn()
    try:
        cur = c.execute("DELETE FROM automations WHERE id=?", (aid,))
        c.commit()
        return cur.rowcount > 0
    finally:
        c.close()


def automation_mark_run(aid: str, ok: bool = True, detail: str = "") -> None:
    """写入一次运行记录：更新 last_run / next_run / run_count / run_history（保留最近 20 条）。"""
    item = automation_get(aid)
    if not item:
        return
    try:
        history = item.get("run_history") or []
    except Exception:
        history = []
    history.insert(0, {"ts": _now(), "ok": bool(ok), "detail": str(detail)[:500]})
    history = history[:20]
    next_run = _compute_auto_next(item.get("trigger") or {})
    c = _conn()
    try:
        c.execute(
            "UPDATE automations SET last_run=?,next_run=?,run_count=?,run_history=? WHERE id=?",
            (_now(), next_run, int(item.get("run_count", 0)) + 1, _j(history), aid),
        )
        c.commit()
    finally:
        c.close()


# ---------------- Schedules ----------------

def schedules_list() -> List[Dict[str, Any]]:
    c = _conn()
    try:
        rows = c.execute("SELECT * FROM schedules ORDER BY created_at DESC").fetchall()
        return [_load(r) for r in rows]
    finally:
        c.close()


def _compute_sched_next(data: Dict[str, Any]) -> str:
    cron = data.get("cron", "")
    tz = data.get("timezone") or settings_get_value("scheduler.timezone", "Asia/Shanghai")
    if cron:
        from core import cronutil
        dt = cronutil.next_run(cron, tz)
        return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""
    # 兼容旧版 frequency/run_time
    freq = data.get("frequency", "daily")
    rt = data.get("run_time", "09:00")
    try:
        h, m = (int(x) for x in rt.split(":"))
    except Exception:
        h, m = 9, 0
    now = time.localtime()
    if freq == "daily":
        base = time.mktime(time.strptime(
            f"{now.tm_year}-{now.tm_mon:02d}-{now.tm_mday} {h:02d}:{m:02d}:00", "%Y-%m-%d %H:%M:%S"))
        if base < time.time():
            base += 86400
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(base))
    if freq == "hourly":
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + 3600))
    return ""


def schedule_create(data: Dict[str, Any]) -> Dict[str, Any]:
    sid = data.get("id") or _uid("sched")
    cron = data.get("cron", "")
    tz = data.get("timezone") or settings_get_value("scheduler.timezone", "Asia/Shanghai")
    channels = data.get("channels") or []
    if not isinstance(channels, list):
        channels = []
    next_run = _compute_sched_next(data)
    c = _conn()
    try:
        c.execute(
            """INSERT INTO schedules
               (id,name,frequency,run_time,prompt,task_ref,enabled,last_run,next_run,created_at,
                cron,timezone,task_type,plugin_id,workflow_id,channels,memory_enabled,retry,timeout,run_count,run_history)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, data.get("name", "未命名定时任务"), data.get("frequency", "daily"),
             data.get("run_time", "09:00"), data.get("prompt", ""), data.get("task_ref", ""),
             1 if data.get("enabled", True) else 0, "", next_run, _now(),
             cron, tz, data.get("task_type", "prompt"), data.get("plugin_id", ""),
             data.get("workflow_id", ""), _j(channels),
             1 if data.get("memory_enabled", True) else 0,
             int(data.get("retry", 0)), int(data.get("timeout", 120)), 0, "[]"),
        )
        c.commit()
    finally:
        c.close()
    return schedule_get(sid)


def schedule_get(sid: str) -> Optional[Dict[str, Any]]:
    c = _conn()
    try:
        r = c.execute("SELECT * FROM schedules WHERE id=?", (sid,)).fetchone()
        return _load(r) if r else None
    finally:
        c.close()


def schedule_update(sid: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    existing = schedule_get(sid)
    if not existing:
        return None
    merged = {**existing, **{k: v for k, v in data.items() if v is not None}}
    channels = merged.get("channels", [])
    if not isinstance(channels, list):
        channels = []
    # 若改了 cron/时区/频率，重算 next_run
    recompute = data.get("cron") is not None or data.get("frequency") is not None \
        or data.get("run_time") is not None or data.get("timezone") is not None
    next_run = _compute_sched_next(merged) if recompute else (merged.get("next_run") or "")
    c = _conn()
    try:
        c.execute(
            """UPDATE schedules
               SET name=?,frequency=?,run_time=?,prompt=?,task_ref=?,enabled=?,next_run=?,
                   cron=?,timezone=?,task_type=?,plugin_id=?,workflow_id=?,channels=?,memory_enabled=?,retry=?,timeout=?
               WHERE id=?""",
            (merged["name"], merged["frequency"], merged["run_time"], merged["prompt"],
             merged["task_ref"], 1 if merged.get("enabled", True) else 0, next_run,
             merged.get("cron", ""), merged.get("timezone", "") or settings_get_value("scheduler.timezone", "Asia/Shanghai"),
             merged.get("task_type", "prompt"), merged.get("plugin_id", ""),
             merged.get("workflow_id", ""), _j(channels),
             1 if merged.get("memory_enabled", True) else 0,
             int(merged.get("retry", 0)), int(merged.get("timeout", 120)), sid),
        )
        c.commit()
    finally:
        c.close()
    return schedule_get(sid)


def schedule_mark_run(sid: str, next_run: str = "", ok: bool = True, detail: str = "") -> None:
    item = schedule_get(sid)
    if not item:
        return
    try:
        history = item.get("run_history") or []
    except Exception:
        history = []
    history.insert(0, {"ts": _now(), "ok": bool(ok), "detail": str(detail)[:500]})
    history = history[:20]
    if not next_run:
        merged = {**item}
        next_run = _compute_sched_next(merged)
    c = _conn()
    try:
        c.execute(
            "UPDATE schedules SET last_run=?,next_run=?,run_count=?,run_history=? WHERE id=?",
            (_now(), next_run, int(item.get("run_count", 0)) + 1, _j(history), sid),
        )
        c.commit()
    finally:
        c.close()


def schedule_delete(sid: str) -> bool:
    c = _conn()
    try:
        cur = c.execute("DELETE FROM schedules WHERE id=?", (sid,))
        c.commit()
        return cur.rowcount > 0
    finally:
        c.close()


# ---------------- Canvas ----------------

def canvas_get(cid: str = "main") -> Dict[str, Any]:
    c = _conn()
    try:
        r = c.execute("SELECT * FROM canvas WHERE id=?", (cid,)).fetchone()
        if r:
            d = _load(r)
            d["version"] = r["version"] if "version" in r.keys() else 1
            return d
        # 不存在则返回空画布并创建
        c.execute("INSERT INTO canvas (id,nodes,edges,updated_at,version) VALUES (?,?,?,?,?)",
                  (cid, "[]", "[]", _now(), 1))
        c.commit()
        return {"id": cid, "nodes": [], "edges": [], "updated_at": _now(), "version": 1}
    finally:
        c.close()


def canvas_peek(cid: str = "main") -> Optional[Dict[str, Any]]:
    """只读查看画布，不存在时返回 None（不创建空画布）。

    用于对话上下文注入等「读而不写」场景，避免每次对话都顺手建出空画布记录。
    """
    c = _conn()
    try:
        r = c.execute("SELECT * FROM canvas WHERE id=?", (cid,)).fetchone()
        if not r:
            return None
        d = _load(r)
        d["version"] = r["version"] if "version" in r.keys() else 1
        return d
    finally:
        c.close()


def canvas_save(cid: str, nodes: Any, edges: Any) -> Dict[str, Any]:
    if not isinstance(nodes, list):
        nodes = []
    if not isinstance(edges, list):
        edges = []
    now = _now()
    c = _conn()
    try:
        existing = c.execute("SELECT id, version FROM canvas WHERE id=?", (cid,)).fetchone()
        if existing:
            new_version = (existing["version"] or 0) + 1
            c.execute("UPDATE canvas SET nodes=?,edges=?,updated_at=?,version=? WHERE id=?",
                      (_j(nodes), _j(edges), now, new_version, cid))
        else:
            new_version = 1
            c.execute("INSERT INTO canvas (id,nodes,edges,updated_at,version) VALUES (?,?,?,?,?)",
                      (cid, _j(nodes), _j(edges), now, new_version))
        # 写入历史记录
        c.execute("INSERT INTO canvas_history (canvas_id,version,nodes,edges,created_at) VALUES (?,?,?,?,?)",
                  (cid, new_version, _j(nodes), _j(edges), now))
        c.commit()
    finally:
        c.close()
    return {"id": cid, "saved": True, "updated_at": now, "version": new_version}


def canvas_list() -> list:
    """列出所有保存的画布，含节点数和边数。"""
    c = _conn()
    try:
        rows = c.execute("SELECT id, nodes, edges FROM canvas ORDER BY updated_at DESC").fetchall()
        result = []
        for r in rows:
            try:
                nodes = json.loads(r["nodes"]) if r["nodes"] else []
                edges = json.loads(r["edges"]) if r["edges"] else []
            except Exception:
                nodes, edges = [], []
            result.append({"id": r["id"], "nodes_count": len(nodes), "edges_count": len(edges)})
        return result
    finally:
        c.close()


def canvas_delete(cid: str) -> dict:
    """删除指定画布。"""
    c = _conn()
    try:
        c.execute("DELETE FROM canvas WHERE id=?", (cid,))
        c.commit()
        return {"deleted": cid, "ok": True}
    finally:
        c.close()


def canvas_history(cid: str = "main") -> list:
    """返回画布的所有历史版本（按 version 降序）。"""
    c = _conn()
    try:
        rows = c.execute(
            "SELECT id, canvas_id, version, nodes, edges, created_at FROM canvas_history WHERE canvas_id=? ORDER BY version DESC",
            (cid,),
        ).fetchall()
        result = []
        for r in rows:
            try:
                nodes = json.loads(r["nodes"]) if r["nodes"] else []
                edges = json.loads(r["edges"]) if r["edges"] else []
            except Exception:
                nodes, edges = [], []
            result.append({
                "id": r["id"],
                "canvas_id": r["canvas_id"],
                "version": r["version"],
                "nodes": nodes,
                "edges": edges,
                "created_at": r["created_at"],
            })
        return result
    finally:
        c.close()


# ---------------- Settings（前端设置 → 后端）----------------

def settings_get() -> Dict[str, Any]:
    c = _conn()
    try:
        rows = c.execute("SELECT key,value FROM settings").fetchall()
        return {r["key"]: _coerce_setting(r["value"]) for r in rows}
    finally:
        c.close()


def _coerce_setting(v: str):
    if v == "true":
        return True
    if v == "false":
        return False
    try:
        if "." in v:
            return float(v)
        return int(v)
    except Exception:
        try:
            return json.loads(v)
        except Exception:
            return v


def settings_get_value(key: str, default: Any = None) -> Any:
    c = _conn()
    try:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return _coerce_setting(r["value"]) if r else default
    finally:
        c.close()


def settings_set(data: Dict[str, Any]) -> Dict[str, Any]:
    """批量写入设置项（前端 Settings 页保存即落库）。值统一转字符串存储。"""
    c = _conn()
    try:
        for k, v in data.items():
            val = _j(v) if isinstance(v, (dict, list)) else str(v)
            c.execute(
                "INSERT INTO settings (key,value,updated_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (k, val, _now()),
            )
        c.commit()
    finally:
        c.close()
    return settings_get()


if __name__ == "__main__":
    init_db()
    print("app_store initialized at", _db_path())
