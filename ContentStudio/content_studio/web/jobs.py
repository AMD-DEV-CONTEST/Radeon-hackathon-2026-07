"""内存任务表 + 磁盘持久化（重启不丢已完成的任务）。"""
from __future__ import annotations

import base64
import json
import threading
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

JOBS_DIR = Path.home() / ".content_studio" / "jobs"
KEEP = 50  # 最多保留多少条历史


@dataclass
class Job:
    id: str
    stage: str = "queued"
    progress: float = 0.0
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str = ""


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, bytes):
        return {"__b64__": base64.b64encode(obj).decode("ascii")}
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    return obj


def _unjsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        if "__b64__" in obj:
            return base64.b64decode(obj["__b64__"])
        return {k: _unjsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_unjsonable(v) for v in obj]
    return obj


def _save(job: Job) -> None:
    try:
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        path = JOBS_DIR / f"{job.id}.json"
        data = {"id": job.id, "stage": job.stage, "progress": job.progress,
                "result": _jsonable(job.result), "error": job.error, "created_at": job.created_at}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _gc() -> None:
    """保留最近 KEEP 条，删旧的。"""
    try:
        files = sorted(JOBS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files[KEEP:]:
            p.unlink(missing_ok=True)
    except Exception:
        pass


def _load_all() -> None:
    """启动时把磁盘上的历史任务读进内存。"""
    if not JOBS_DIR.exists():
        return
    for p in JOBS_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            job = Job(
                id=d.get("id", p.stem), stage=d.get("stage", "done"),
                progress=d.get("progress", 1.0), result=_unjsonable(d.get("result")),
                error=d.get("error"), created_at=d.get("created_at", ""),
            )
            _jobs[job.id] = job
        except Exception:
            pass


_load_all()


def create_job() -> Job:
    jid = uuid.uuid4().hex[:12]
    job = Job(id=jid, created_at=datetime.now().isoformat(timespec="seconds"))
    with _lock:
        _jobs[jid] = job
    return job


def get_job(jid: str) -> Optional[Job]:
    with _lock:
        return _jobs.get(jid)


def update_job(jid: str, **kw: Any) -> None:
    with _lock:
        j = _jobs.get(jid)
        if j is None:
            return
        for k, v in kw.items():
            setattr(j, k, v)
        if j.stage == "done" and j.result:
            _save(j)
            _gc()


def list_jobs() -> list[Job]:
    """按时间倒序返回所有任务。"""
    with _lock:
        js = list(_jobs.values())
    js.sort(key=lambda j: j.created_at, reverse=True)
    return js


def delete_job(jid: str) -> bool:
    """从内存和磁盘删除一条任务。"""
    with _lock:
        existed = _jobs.pop(jid, None) is not None
    try:
        path = JOBS_DIR / f"{jid}.json"
        if path.exists():
            path.unlink()
            existed = True
    except Exception:
        pass
    return existed
