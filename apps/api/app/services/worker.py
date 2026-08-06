"""本地 subprocess 训练 worker (M3.2).

- spawn_job(job_id): fork 一个 python 进程跑 apps/api/app/services/trainer.py, 写 pid
- cancel_job(job_id): 通过 pid 杀进程, 更新 status=cancelled
- 进程内会自己 update TrainingJob.status/progress/loss (通过独立 DB session)

M3.1 只给出骨架, 真实逻辑由 trainer.py 承担.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from app.models.database import SessionLocal
from app.models.training import TrainingJob
from app.services import training_service as svc


def _trainer_entrypoint() -> Path:
    # apps/api/app/services/worker.py -> apps/api/app -> app/services/trainer.py
    return Path(__file__).resolve().parent / "trainer.py"


def spawn_job(job_id: str) -> int:
    """启动 training subprocess, 返回 pid.

    trainer.py 会自己从 DB 读 job 配置 + 更新 status/progress.
    """
    trainer = _trainer_entrypoint()
    if not trainer.exists():
        raise RuntimeError(f"trainer entrypoint missing: {trainer}")

    log_dir = svc.get_logs_root()
    log_path = log_dir / f"job_{job_id}.log"

    # Windows: subprocess 不用 os.setsid. 新控制台避免继承 stdout 冲突.
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    log_fh = open(log_path, "w", encoding="utf-8", buffering=1)

    # trainer.py 需要 import 'app.*', cwd=apps/api 但还要把它加到 PYTHONPATH, 避免 subprocess
    # 丢掉父进程的 sys.path.
    api_root = trainer.parent.parent.parent  # apps/api
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (str(api_root) + os.pathsep + existing_pp) if existing_pp else str(api_root)

    proc = subprocess.Popen(
        [sys.executable, str(trainer), "--job-id", job_id],
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        cwd=str(api_root),
        creationflags=creationflags,
        close_fds=(os.name != "nt"),
        env=env,
    )

    db = SessionLocal()
    try:
        row = db.query(TrainingJob).filter(TrainingJob.id == job_id).first()
        if row:
            row.pid = proc.pid
            row.log_path = str(log_path)
            row.started_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()

    return proc.pid


def cancel_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        row = db.query(TrainingJob).filter(TrainingJob.id == job_id).first()
        if not row or not row.pid:
            return
        pid = row.pid

    finally:
        db.close()

    try:
        if os.name == "nt":
            # windows 没 SIGTERM, 用 taskkill
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], check=False)
        else:
            os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
