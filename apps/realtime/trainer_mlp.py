"""Joint-only MLP baseline trainer (M3.2 original, moved to realtime venv for M8.4).

Same next-state-delta MLP as apps/api/app/services/trainer.py originally
implemented inline, extracted here so the API layer can dispatch both
`mlp_baseline` and `vision_mlp_baseline` the same way (subprocess → realtime
venv where torch actually lives).

Input dataset format (LeRobot):
    <dataset_root>/<episode>/data/chunk-*/*.parquet
    columns include: observation.state (list[float], len=6)

Output (same layout as trainer_vision.py so the existing inference_router
and registry scanner keep working):
    <output_dir>/checkpoint.pt     # {state_dict, input_dim, output_dim, hidden, prediction_mode}
    <output_dir>/model.json
    <output_dir>/loss_history.json

PROGRESS events on stdout match trainer_vision.py so the API orchestrator
can share the progress parser:

    PROGRESS {"stage":"epoch","epoch":3,"epochs":10,"train_loss":...,"val_loss":...}
    PROGRESS {"stage":"done","model_key":"...","final_val_loss":...,"final_val_rmse":...}
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any


for _s in ("stdout", "stderr"):
    _st = getattr(sys, _s, None)
    if _st is not None and hasattr(_st, "buffer") and getattr(_st, "encoding", "").lower() != "utf-8":
        try:
            setattr(sys, _s, io.TextIOWrapper(_st.buffer, encoding="utf-8", line_buffering=True))
        except Exception:
            pass


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[trainer_mlp {ts}] {msg}", flush=True)


def _progress(stage: str, **fields: Any) -> None:
    print("PROGRESS " + json.dumps({"stage": stage, **fields}, ensure_ascii=False), flush=True)


def _load_states(dataset_dir: Path):
    import pyarrow.parquet as pq
    import torch

    parquets = sorted(dataset_dir.rglob("*.parquet"))
    if not parquets:
        raise RuntimeError(f"no parquet under {dataset_dir}")
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
    states = torch.tensor(frames, dtype=torch.float32)
    x = states[:-1]
    y = states[1:] - states[:-1]
    return x, y


def _build_model(in_dim: int, out_dim: int, hidden: int):
    import torch.nn as nn
    return nn.Sequential(
        nn.Linear(in_dim, hidden),
        nn.ReLU(),
        nn.Linear(hidden, hidden),
        nn.ReLU(),
        nn.Linear(hidden, out_dim),
    )


def _split(x, y, val_ratio: float):
    import torch
    n = x.shape[0]
    idx = torch.randperm(n)
    n_val = max(1, int(n * val_ratio))
    return x[idx[n_val:]], y[idx[n_val:]], x[idx[:n_val]], y[idx[:n_val]]


def train(
    dataset_dir: Path,
    output_dir: Path,
    epochs: int,
    batch_size: int,
    lr: float,
    hidden: int,
    val_ratio: float = 0.1,
    seed: int = 42,
    model_key: str | None = None,
) -> dict[str, Any]:
    import torch
    import torch.nn as nn

    torch.manual_seed(seed)

    x, y = _load_states(dataset_dir)
    _log(f"loaded {x.shape[0]} (state, delta) pairs")

    x_tr, y_tr, x_val, y_val = _split(x, y, val_ratio)
    model = _build_model(in_dim=6, out_dim=6, hidden=hidden)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.MSELoss()

    history: list[dict[str, float]] = []
    _log(f"training: n_train={x_tr.shape[0]} n_val={x_val.shape[0]} epochs={epochs} bs={batch_size} lr={lr} hidden={hidden}")
    _progress("train_start", n_train=int(x_tr.shape[0]), n_val=int(x_val.shape[0]), epochs=epochs)

    for ep in range(1, epochs + 1):
        model.train()
        n = x_tr.shape[0]
        perm = torch.randperm(n)
        total = 0.0
        cnt = 0
        for i in range(0, n, batch_size):
            ii = perm[i : i + batch_size]
            bx, by = x_tr[ii], y_tr[ii]
            opt.zero_grad()
            pred = model(bx)
            loss = loss_fn(pred, by)
            loss.backward()
            opt.step()
            total += float(loss.item()) * bx.shape[0]
            cnt += int(bx.shape[0])
        tr_loss = total / max(1, cnt)

        model.eval()
        with torch.no_grad():
            val_loss = float(loss_fn(model(x_val), y_val).item())

        history.append({"epoch": ep, "train_loss": tr_loss, "val_loss": val_loss})
        _log(f"epoch {ep}/{epochs}  train={tr_loss:.6f}  val={val_loss:.6f}")
        _progress("epoch", epoch=ep, epochs=epochs, train_loss=tr_loss, val_loss=val_loss)

    model.eval()
    with torch.no_grad():
        val_rmse = float(torch.sqrt(((model(x_val) - y_val) ** 2).mean()).item())

    if model_key is None:
        model_key = output_dir.name
    output_dir.mkdir(parents=True, exist_ok=True)

    ckpt_path = output_dir / "checkpoint.pt"
    torch.save({
        "state_dict": model.state_dict(),
        "input_dim": 6,
        "output_dim": 6,
        "hidden": hidden,
        "algo": "mlp_baseline",
        "prediction_mode": "delta",
    }, ckpt_path)

    meta = {
        "model_key": model_key,
        "name": model_key,
        "algo": "mlp_baseline",
        "dataset_id": dataset_dir.name,
        "checkpoint": "checkpoint.pt",
        "input_dim": 6,
        "output_dim": 6,
        "hparams": {"epochs": epochs, "batch_size": batch_size, "lr": lr, "hidden": hidden},
        "metrics": {
            "final_train_loss": history[-1]["train_loss"],
            "final_val_loss": history[-1]["val_loss"],
            "final_val_rmse_delta": val_rmse,
            "epochs": epochs,
            "samples": int(x.shape[0]),
        },
        "prediction_mode": "delta",
    }
    (output_dir / "model.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    (output_dir / "loss_history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")

    _log(f"saved model to {output_dir} (val_rmse={val_rmse:.6f})")
    _progress(
        "done",
        model_key=model_key,
        output_dir=str(output_dir),
        final_train_loss=history[-1]["train_loss"],
        final_val_loss=history[-1]["val_loss"],
        final_val_rmse=val_rmse,
    )
    return meta


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="M3/M8.4 joint-only MLP baseline trainer")
    p.add_argument("--dataset", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--model-key", default=None)
    p.add_argument("--epochs", type=int, default=10)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--hidden", type=int, default=64)
    p.add_argument("--val-ratio", type=float, default=0.1)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    dataset_dir = Path(args.dataset).resolve()
    if not dataset_dir.exists():
        print(f"error: dataset dir not found: {dataset_dir}", file=sys.stderr)
        return 2
    out_dir = Path(args.output_dir).resolve()

    try:
        train(
            dataset_dir=dataset_dir,
            output_dir=out_dir,
            epochs=args.epochs,
            batch_size=args.batch_size,
            lr=args.lr,
            hidden=args.hidden,
            val_ratio=args.val_ratio,
            seed=args.seed,
            model_key=args.model_key,
        )
    except Exception as e:
        _log(f"TRAINING FAILED: {e}")
        traceback.print_exc()
        _progress("failed", error=str(e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
