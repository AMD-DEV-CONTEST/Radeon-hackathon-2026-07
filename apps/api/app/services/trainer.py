"""Training subprocess entrypoint (M3.2 真实训练).

baseline = MLP 次帧增量回归:
    x = state[t]  (6D)
    y = state[t+1] - state[t]  (6D)
    pred = MLP(x), loss = MSE(pred, y)

读 parquet 不依赖 lerobot, 只要 pyarrow + pandas + torch(CPU).

产出布局:
    apps/realtime/models/<model_key>/
        checkpoint.pt     (torch state dict)
        model.json        (元数据, registry 用)
        loss_history.json (每 epoch 的 train/val loss)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# 强制 utf-8 输出, 避免 windows GBK 报错
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name)
    if hasattr(_stream, "buffer") and getattr(_stream, "encoding", "").lower() != "utf-8":
        try:
            setattr(sys, _stream_name, io.TextIOWrapper(_stream.buffer, encoding="utf-8", line_buffering=True))
        except Exception:
            pass


def _log(msg: str) -> None:
    ts = datetime.utcnow().strftime("%H:%M:%S")
    print(f"[trainer {ts}] {msg}", flush=True)


def _load_dataset(dataset_path: Path) -> tuple["torch.Tensor", "torch.Tensor"]:
    import pandas as pd
    import pyarrow.parquet as pq
    import torch

    parquets = sorted(dataset_path.rglob("*.parquet"))
    if not parquets:
        raise RuntimeError(f"no parquet under {dataset_path}")

    frames: list[list[float]] = []
    for pq_file in parquets:
        df = pq.read_table(pq_file).to_pandas()
        if "observation.state" not in df.columns:
            raise RuntimeError(f"'observation.state' column missing in {pq_file}")
        for v in df["observation.state"]:
            try:
                arr = [float(x) for x in v][:6]
                if len(arr) == 6:
                    frames.append(arr)
            except Exception:
                continue

    if len(frames) < 32:
        raise RuntimeError(f"dataset too small: {len(frames)} valid frames (need >=32)")

    states = torch.tensor(frames, dtype=torch.float32)  # [N, 6]
    x = states[:-1]
    y = states[1:] - states[:-1]  # 次帧 delta
    return x, y


def _make_model(in_dim: int, out_dim: int, hidden: int):
    import torch.nn as nn

    return nn.Sequential(
        nn.Linear(in_dim, hidden),
        nn.ReLU(),
        nn.Linear(hidden, hidden),
        nn.ReLU(),
        nn.Linear(hidden, out_dim),
    )


def _split(x, y, val_ratio: float = 0.1):
    import torch

    n = x.shape[0]
    idx = torch.randperm(n)
    n_val = max(1, int(n * val_ratio))
    val_idx = idx[:n_val]
    tr_idx = idx[n_val:]
    return x[tr_idx], y[tr_idx], x[val_idx], y[val_idx]


def run_training(job_id: str) -> None:
    """主训练流程. 所有 DB 更新走独立 session.

    算法分派 (M8.4):
      - algo == "vision_mlp_baseline" → 委托给 apps/realtime/trainer_vision.py
        (需要 torch+torchvision+cv2, 这些只在 realtime 的 venv 里)
      - 其他 (默认 mlp_baseline) → 本进程内 torch MLP 训练
    """
    from app.models.database import SessionLocal
    from app.models.training import Model, TrainingJob
    from app.services import training_service as svc

    db = SessionLocal()
    try:
        job = db.query(TrainingJob).filter(TrainingJob.id == job_id).first()
        if not job:
            _log(f"job {job_id} not found in DB")
            return
        hp = job.hparams_json or {}
        epochs = int(hp.get("epochs", 10))
        batch_size = int(hp.get("batch_size", 32))
        lr = float(hp.get("lr", 1e-3))
        hidden = int(hp.get("hidden", 64))
        dataset_id = job.dataset_id
        algo = job.algo

        # 定位 dataset 目录 — 支持两种根：
        #   1. recording_*           -> apps/realtime/datasets/<id>
        #   2. owner/name (HF 风格)  -> $HF_HOME/lerobot/<owner>/<name>
        from app.services.dataset_service import resolve_dataset_dir, get_storage_root, get_lerobot_cache_root

        dataset_path = resolve_dataset_dir(dataset_id)
        if dataset_path is None:
            raise RuntimeError(
                f"dataset dir not found for id='{dataset_id}' "
                f"(checked {get_storage_root()} and {get_lerobot_cache_root()})"
            )

        # M9.3: algo catalog gate. act/smolvla/pi0 are registered as "qualia"
        # backend only. Local dispatch must refuse them with a clear message so
        # the user (or the Web form) knows to flip train_backend=qualia instead.
        from app.services import qualia_service as qualia_svc

        cloud_only = {a["id"] for a in qualia_svc.QUALIA_ALGORITHMS}
        if algo in cloud_only and job.train_backend != "qualia":
            raise RuntimeError(
                f"algorithm '{algo}' only runs on Qualia cloud. "
                f"Resubmit the job with train_backend='qualia' "
                f"(needs QUALIA_API_TOKEN). Local training is not available "
                f"for cloud-only algorithms."
            )

        job.status = "running"
        job.started_at = datetime.utcnow()
        db.commit()
        _log(f"job={job_id} algo={algo} dataset={dataset_id} epochs={epochs} bs={batch_size} lr={lr} hidden={hidden}")

        # ---------- M8.4: 所有训练统一走 realtime venv 的子进程, 因为 torch
        #            只装在 apps/realtime/.venv 里, API venv 是轻量的. ----------
        if algo == "vision_mlp_baseline":
            _run_subprocess_training(
                db=db, job_id=job_id,
                dataset_id=dataset_id, dataset_path=dataset_path,
                epochs=epochs, batch_size=batch_size, lr=lr, hidden=hidden,
                algo=algo,
                script_name="trainer_vision.py",
                extra_args=[
                    "--prediction-mode", str(hp.get("prediction_mode", "delta")),
                    "--device", str(hp.get("device", "auto")),
                ],
                model_key_prefix="vision",
            )
        else:
            _run_subprocess_training(
                db=db, job_id=job_id,
                dataset_id=dataset_id, dataset_path=dataset_path,
                epochs=epochs, batch_size=batch_size, lr=lr, hidden=hidden,
                algo=algo,
                script_name="trainer_mlp.py",
                extra_args=[],
                model_key_prefix="model",
            )
    except Exception as e:
        _log(f"FAILED: {e}")
        _log(traceback.format_exc())
        try:
            job = db.query(TrainingJob).filter(TrainingJob.id == job_id).first()
            if job:
                job.status = "failed"
                job.error_msg = str(e)[:500]
                job.finished_at = datetime.utcnow()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _realtime_python() -> Path:
    """Resolve the realtime venv's python interpreter.

    trainer_vision.py depends on torch+torchvision+cv2 which only exist in
    apps/realtime/.venv. We deliberately keep those heavy deps out of the
    api venv to avoid a multi-GB install on API-only deployments.
    """
    # apps/api/app/services/trainer.py → apps/api/app/services → apps/api/app → apps/api → apps → <root>
    root = Path(__file__).resolve().parents[4]
    candidate = root / "apps" / "realtime" / ".venv" / "bin" / "python"
    if candidate.exists():
        return candidate
    # Windows layout fallback
    candidate_win = root / "apps" / "realtime" / ".venv" / "Scripts" / "python.exe"
    if candidate_win.exists():
        return candidate_win
    raise RuntimeError(
        f"realtime venv python not found at {candidate} (or Scripts/python.exe). "
        "Install apps/realtime requirements first."
    )


def _realtime_trainer_script(name: str) -> Path:
    root = Path(__file__).resolve().parents[4]
    script = root / "apps" / "realtime" / name
    if not script.exists():
        raise RuntimeError(f"{name} not found at {script}")
    return script


def _run_subprocess_training(
    *,
    db,
    job_id: str,
    dataset_id: str,
    dataset_path: Path,
    epochs: int,
    batch_size: int,
    lr: float,
    hidden: int,
    algo: str,
    script_name: str,
    extra_args: list[str],
    model_key_prefix: str,
) -> None:
    """Generic dispatcher: spawn a trainer script in the realtime venv.

    Both `trainer_mlp.py` and `trainer_vision.py` speak the same stdout
    protocol — plain logs for humans plus one-line `PROGRESS {json}` events
    that this function parses to bump DB progress. On successful exit we
    re-read the generated `model.json` and create the Model row.
    """
    from app.models.training import Model, TrainingJob

    interpreter = _realtime_python()
    script = _realtime_trainer_script(script_name)

    from app.services import training_service as svc
    models_root = svc.get_models_root()
    model_key = f"{model_key_prefix}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    out_dir = models_root / model_key
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(interpreter),
        str(script),
        "--dataset", str(dataset_path),
        "--output-dir", str(out_dir),
        "--model-key", model_key,
        "--epochs", str(epochs),
        "--batch-size", str(batch_size),
        "--lr", str(lr),
        "--hidden", str(hidden),
        *extra_args,
    ]
    _log(f"subprocess dispatch ({algo}): {' '.join(cmd)}")

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        cwd=str(script.parent),
    )

    saw_done = False
    saw_failed = False
    final_payload: dict[str, Any] = {}

    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            line = line.rstrip("\r\n")
            print(line, flush=True)

            if not line.startswith("PROGRESS "):
                continue
            try:
                payload = json.loads(line[len("PROGRESS "):])
            except Exception:
                continue
            stage = payload.get("stage")
            if stage == "epoch":
                ep = int(payload.get("epoch", 0))
                total = int(payload.get("epochs", epochs))
                try:
                    row = db.query(TrainingJob).filter(TrainingJob.id == job_id).first()
                    if row is None:
                        continue
                    if row.status == "cancelled":
                        _log("job cancelled mid-training, terminating subprocess")
                        proc.terminate()
                        return
                    row.epoch = ep
                    row.total_epochs = total
                    row.progress_pct = 100.0 * ep / max(1, total)
                    row.loss = float(payload.get("val_loss", 0.0))
                    db.commit()
                except Exception as exc:
                    _log(f"DB progress update failed (ignored): {exc}")
            elif stage == "done":
                saw_done = True
                final_payload = dict(payload)
            elif stage == "failed":
                saw_failed = True
                final_payload = dict(payload)
    finally:
        rc = proc.wait()
    _log(f"{algo} subprocess exit_code={rc} done={saw_done} failed={saw_failed}")

    if rc != 0 or saw_failed or not saw_done:
        msg = f"{algo} training failed (rc={rc})"
        if final_payload.get("error"):
            msg += f": {final_payload['error']}"
        raise RuntimeError(msg)

    meta_path = out_dir / "model.json"
    if not meta_path.exists():
        raise RuntimeError(f"expected model.json at {meta_path}, subprocess exited cleanly but wrote nothing")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    ckpt_path = out_dir / meta.get("checkpoint", "checkpoint.pt")
    if not ckpt_path.exists():
        raise RuntimeError(f"checkpoint missing at {ckpt_path}")

    model_row = Model(
        model_key=model_key,
        name=meta.get("name", model_key),
        algo=meta.get("algo", algo),
        dataset_id=dataset_id,
        checkpoint_path=str(ckpt_path),
        size_bytes=ckpt_path.stat().st_size,
        metrics_json=meta.get("metrics") or {},
        hparams_json=meta.get("hparams") or {},
        input_dim=int(meta.get("input_dim", 6)),
        output_dim=int(meta.get("output_dim", 6)),
    )
    db.add(model_row)
    db.commit()
    db.refresh(model_row)

    row = db.query(TrainingJob).filter(TrainingJob.id == job_id).first()
    if row is None:
        _log("job row vanished after training, cannot finalize")
        return
    row.model_id = model_row.id
    row.status = "succeeded"
    row.progress_pct = 100.0
    row.finished_at = datetime.utcnow()
    row.loss = float(meta.get("metrics", {}).get("final_val_loss", row.loss or 0.0))
    db.commit()
    _log(f"OK ({algo}) model_key={model_key} ckpt={ckpt_path} rmse={meta.get('metrics', {}).get('final_val_rmse_delta')}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--job-id", required=True)
    args = p.parse_args()
    run_training(args.job_id)


if __name__ == "__main__":
    main()
