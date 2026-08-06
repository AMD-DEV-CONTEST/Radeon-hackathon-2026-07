"""Vision-conditioned imitation-learning trainer (M8.4).

This is a *standalone* CLI trainer that consumes LeRobot-format vision datasets
produced by the M8.2 recording pipeline and writes checkpoints the M8.3
`vision_inference` loader can consume directly — no DB, no HTTP, no magic.

Why standalone
--------------
Heavy deps (torch + torchvision + opencv) live in the realtime venv, not the
API venv. So the orchestration goes:

    apps/api trainer.py  (db / DB status)
        └── subprocess → apps/realtime/.venv/bin/python trainer_vision.py …
                         (actual compute here)

For interactive/debug use you can also run trainer_vision.py directly:

    cd apps/realtime
    .venv/bin/python trainer_vision.py \
        --dataset datasets/recording_20260421_010836 \
        --output-dir models/vision_demo \
        --epochs 10 --batch-size 16 --hidden 128

Dataset contract (M8.2 output)
------------------------------
    <dataset_root>/
      episode_0/data/chunk-000/file-000.parquet      # one episode per recording
        columns: action, observation.state, observation.images.cam_main, …
      images/cam_main/frame_NNNNNN.jpg               # keyed by frame_index

We train the same architecture as the inference-time `VisionJointPolicy`
(frozen ResNet18 + 3-layer MLP head) so the saved `state_dict` plugs into
`vision_inference._load_policy` with zero reshaping.

Label space
-----------
`prediction_mode = "delta"`:  target  = action[t] − observation.state[t]
`prediction_mode = "absolute"`: target = action[t]

Default is "delta" to match the non-vision MLP baseline and to give the
SafetyGate natural slack (small deltas clamp cleanly).
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import math
import os
import random
import sys
import time
import traceback
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional


# utf-8 stdout for subprocess scenarios
for _s in ("stdout", "stderr"):
    _st = getattr(sys, _s, None)
    if _st is not None and hasattr(_st, "buffer") and getattr(_st, "encoding", "").lower() != "utf-8":
        try:
            setattr(sys, _s, io.TextIOWrapper(_st.buffer, encoding="utf-8", line_buffering=True))
        except Exception:
            pass


logger = logging.getLogger("trainer_vision")


IMG_SIZE = 224
IMAGE_FEATURE_DIM = 512


# --------------------------------------------------------------------------- #
# Logging helper
# --------------------------------------------------------------------------- #


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[trainer_vision {ts}] {msg}", flush=True)


def _progress(stage: str, **fields: Any) -> None:
    """Emit a machine-parsable progress line for the API to scrape.

    Shape:  PROGRESS {"stage":"epoch","epoch":3,"epochs":10,"train_loss":0.01,"val_loss":0.012}
    """
    payload = {"stage": stage, **fields}
    print("PROGRESS " + json.dumps(payload, ensure_ascii=False), flush=True)


# --------------------------------------------------------------------------- #
# Dataset
# --------------------------------------------------------------------------- #


@dataclass
class Sample:
    image_path: Path
    state: list[float]     # (6,)
    action: list[float]    # (6,)


def _collect_samples(dataset_dir: Path) -> list[Sample]:
    """Walk parquet(s) under the dataset dir and build a sample list."""
    import pyarrow.parquet as pq

    parquets = sorted(dataset_dir.rglob("*.parquet"))
    if not parquets:
        raise RuntimeError(f"no parquet under {dataset_dir}")

    samples: list[Sample] = []
    missing_imgs = 0
    for pq_file in parquets:
        df = pq.read_table(pq_file).to_pandas()
        needed = {"observation.state", "action", "observation.images.cam_main"}
        if not needed.issubset(df.columns):
            raise RuntimeError(
                f"{pq_file} missing required columns; have {list(df.columns)}, need {sorted(needed)}"
            )
        for _, row in df.iterrows():
            img_rel = row["observation.images.cam_main"]
            if not isinstance(img_rel, str) or not img_rel:
                missing_imgs += 1
                continue
            img_path = dataset_dir / img_rel
            if not img_path.exists():
                missing_imgs += 1
                continue
            try:
                state = [float(x) for x in row["observation.state"]][:6]
                action = [float(x) for x in row["action"]][:6]
            except Exception:
                continue
            if len(state) != 6 or len(action) != 6:
                continue
            samples.append(Sample(image_path=img_path, state=state, action=action))

    _log(f"collected {len(samples)} vision samples from {len(parquets)} parquet(s), skipped {missing_imgs}")
    return samples


def _decode_and_resize(path: Path):
    """Load JPEG → (3, 224, 224) float32 tensor in [0,1]."""
    import cv2
    import numpy as np
    import torch

    arr = np.fromfile(str(path), dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"failed to decode image {path}")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    rgb = cv2.resize(rgb, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)
    return torch.from_numpy(rgb).permute(2, 0, 1).contiguous().float().div_(255.0)


class VisionDataset:
    """Light Dataset wrapper — small enough that we keep one pre-computed image
    feature per sample in RAM after a single pass through the frozen encoder.

    This matters: re-running ResNet18 every epoch on CPU for hundreds of
    images is wasteful. Since the encoder is frozen, its output is a fixed
    function of the image, so we cache (N, 512) feature vectors once and
    only train the MLP head on top. That cuts per-epoch time by ~100x and
    is the same speed-up trick ACT/SmolVLA do during fine-tuning.
    """

    def __init__(
        self,
        samples: list[Sample],
        encoder,
        device: str,
        batch_size: int = 16,
    ) -> None:
        import torch

        self.samples = samples
        self.device = device
        self._cache_features: Optional[torch.Tensor] = None
        self._cache_states: Optional[torch.Tensor] = None
        self._cache_actions: Optional[torch.Tensor] = None

        self._precompute(encoder, batch_size=batch_size)

    def _precompute(self, encoder, batch_size: int) -> None:
        import torch

        n = len(self.samples)
        if n == 0:
            raise RuntimeError("no samples to precompute features for")

        _log(f"precomputing {n} image features via frozen ResNet18 on {self.device} …")
        feats = torch.empty((n, IMAGE_FEATURE_DIM), dtype=torch.float32)
        states = torch.empty((n, 6), dtype=torch.float32)
        actions = torch.empty((n, 6), dtype=torch.float32)

        encoder.eval()
        t0 = time.time()
        for i in range(0, n, batch_size):
            batch = self.samples[i : i + batch_size]
            imgs = torch.stack([_decode_and_resize(s.image_path) for s in batch], dim=0).to(self.device)
            with torch.no_grad():
                out = encoder(imgs).detach().cpu()
            feats[i : i + out.shape[0]] = out
            for j, s in enumerate(batch):
                states[i + j] = torch.tensor(s.state, dtype=torch.float32)
                actions[i + j] = torch.tensor(s.action, dtype=torch.float32)
            if i % (batch_size * 4) == 0:
                _progress("encode", done=i + out.shape[0], total=n)
        dt = time.time() - t0
        _log(f"  done in {dt:.1f}s ({n/dt:.1f} img/s)")

        self._cache_features = feats
        self._cache_states = states
        self._cache_actions = actions

    def tensors(self, prediction_mode: str):
        """Return (X, Y) tensors; X = [feat ‖ state] (N, 518),  Y depends on mode."""
        import torch

        assert self._cache_features is not None
        x = torch.cat([self._cache_features, self._cache_states], dim=1)  # (N, 518)
        if prediction_mode == "delta":
            y = self._cache_actions - self._cache_states
        elif prediction_mode == "absolute":
            y = self._cache_actions
        else:
            raise ValueError(f"unknown prediction_mode: {prediction_mode}")
        return x, y


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #


def _build_encoder(device: str, pretrained: bool = True):
    """Frozen ResNet18, fc replaced by Identity → (N, 512)."""
    import torch.nn as nn
    from torchvision.models import resnet18

    try:
        from torchvision.models import ResNet18_Weights
        weights = ResNet18_Weights.DEFAULT if pretrained else None
    except Exception:  # older torchvision
        weights = None

    try:
        m = resnet18(weights=weights)
    except Exception as exc:
        _log(f"WARN: pretrained weights download failed ({exc}); using random init")
        m = resnet18(weights=None)

    m.fc = nn.Identity()
    for p in m.parameters():
        p.requires_grad = False
    return m.to(device).eval()


def _build_head(input_dim: int, output_dim: int, hidden: int, image_feature_dim: int):
    import torch.nn as nn

    return nn.Sequential(
        nn.Linear(image_feature_dim + input_dim, hidden),
        nn.ReLU(),
        nn.Linear(hidden, hidden),
        nn.ReLU(),
        nn.Linear(hidden, output_dim),
    )


# --------------------------------------------------------------------------- #
# Device selection (mirror vision_inference._try_cuda_forward)
# --------------------------------------------------------------------------- #


def _resolve_device(prefer: str) -> tuple[str, dict[str, Any]]:
    import torch

    info: dict[str, Any] = {
        "requested": prefer,
        "cuda_advertised": bool(torch.cuda.is_available()),
        "cuda_usable": False,
        "probe_error": None,
    }
    if prefer == "cpu":
        info["resolved"] = "cpu"
        return "cpu", info

    if not torch.cuda.is_available():
        info["probe_error"] = "torch.cuda.is_available() is False"
        info["resolved"] = "cpu"
        return "cpu", info

    try:
        x = torch.randn(4, 4, device="cuda")
        y = (x @ x).sum().item()
        _ = float(y)
        info["cuda_usable"] = True
        info["resolved"] = "cuda"
        try:
            info["device_name"] = torch.cuda.get_device_name(0)
        except Exception:
            info["device_name"] = "cuda:0"
        return "cuda", info
    except Exception as exc:
        info["probe_error"] = f"{type(exc).__name__}: {exc}"
        if prefer == "cuda":
            # explicit cuda request but it's broken — fall back with warning
            _log(f"WARN: --device cuda requested but HIP kernel probe failed ({exc}); falling back to CPU")
        info["resolved"] = "cpu"
        return "cpu", info


# --------------------------------------------------------------------------- #
# Training
# --------------------------------------------------------------------------- #


@dataclass
class TrainResult:
    model_key: str
    output_dir: Path
    final_train_loss: float
    final_val_loss: float
    final_val_rmse: float
    epochs: int
    samples: int
    device: dict[str, Any]
    history: list[dict[str, float]]


def train(
    dataset_dir: Path,
    output_dir: Path,
    epochs: int = 20,
    batch_size: int = 32,
    lr: float = 1e-3,
    hidden: int = 128,
    val_ratio: float = 0.1,
    prediction_mode: str = "delta",
    prefer_device: str = "auto",
    seed: int = 42,
    pretrained_encoder: bool = True,
    model_key: Optional[str] = None,
) -> TrainResult:
    import torch
    import torch.nn as nn

    random.seed(seed)
    torch.manual_seed(seed)

    device, device_info = _resolve_device(prefer_device)
    _log(f"device resolved: {device}  {device_info}")
    _progress("device", **device_info)

    samples = _collect_samples(dataset_dir)
    if len(samples) < 8:
        raise RuntimeError(
            f"dataset too small for training: {len(samples)} samples "
            f"(need >= 8). Record a longer episode first."
        )

    encoder = _build_encoder(device, pretrained=pretrained_encoder)
    dataset = VisionDataset(samples=samples, encoder=encoder, device=device, batch_size=min(16, batch_size))

    x, y = dataset.tensors(prediction_mode=prediction_mode)
    n = x.shape[0]
    idx = torch.randperm(n)
    n_val = max(1, int(n * val_ratio))
    val_idx = idx[:n_val]
    tr_idx = idx[n_val:]
    x_tr, y_tr = x[tr_idx].to(device), y[tr_idx].to(device)
    x_val, y_val = x[val_idx].to(device), y[val_idx].to(device)

    head = _build_head(
        input_dim=6,
        output_dim=6,
        hidden=hidden,
        image_feature_dim=IMAGE_FEATURE_DIM,
    ).to(device)
    optim = torch.optim.Adam(head.parameters(), lr=lr)
    loss_fn = nn.MSELoss()

    history: list[dict[str, float]] = []
    _log(f"training: n_train={x_tr.shape[0]} n_val={x_val.shape[0]} epochs={epochs} bs={batch_size} lr={lr} hidden={hidden} mode={prediction_mode}")
    _progress("train_start", n_train=int(x_tr.shape[0]), n_val=int(x_val.shape[0]), epochs=epochs)

    for ep in range(1, epochs + 1):
        head.train()
        perm = torch.randperm(x_tr.shape[0])
        total = 0.0
        count = 0
        for i in range(0, x_tr.shape[0], batch_size):
            ii = perm[i : i + batch_size]
            bx = x_tr[ii]
            by = y_tr[ii]
            optim.zero_grad()
            pred = head(bx)
            loss = loss_fn(pred, by)
            loss.backward()
            optim.step()
            total += float(loss.item()) * bx.shape[0]
            count += int(bx.shape[0])
        tr_loss = total / max(1, count)

        head.eval()
        with torch.no_grad():
            val_pred = head(x_val)
            val_loss = float(loss_fn(val_pred, y_val).item())

        history.append({"epoch": ep, "train_loss": tr_loss, "val_loss": val_loss})
        _log(f"epoch {ep}/{epochs}  train={tr_loss:.6f}  val={val_loss:.6f}")
        _progress("epoch", epoch=ep, epochs=epochs, train_loss=tr_loss, val_loss=val_loss)

    head.eval()
    with torch.no_grad():
        val_pred = head(x_val)
        val_rmse = float(torch.sqrt(((val_pred - y_val) ** 2).mean()).item())

    # ---- save ----
    if model_key is None:
        model_key = output_dir.name
    output_dir.mkdir(parents=True, exist_ok=True)

    ckpt_path = output_dir / "checkpoint.pt"
    torch.save({
        "state_dict": head.state_dict(),
        "input_dim": 6,
        "output_dim": 6,
        "hidden": hidden,
        "image_feature_dim": IMAGE_FEATURE_DIM,
        "prediction_mode": prediction_mode,
        "algo": "vision_mlp_baseline",
    }, ckpt_path)

    meta = {
        "model_key": model_key,
        "name": model_key,
        "algo": "vision_mlp_baseline",
        "dataset_id": dataset_dir.name,
        "checkpoint": "checkpoint.pt",
        "input_dim": 6,
        "output_dim": 6,
        "image_feature_dim": IMAGE_FEATURE_DIM,
        "hparams": {
            "epochs": epochs,
            "batch_size": batch_size,
            "lr": lr,
            "hidden": hidden,
            "prediction_mode": prediction_mode,
            "pretrained_encoder": bool(pretrained_encoder),
        },
        "metrics": {
            "final_train_loss": history[-1]["train_loss"],
            "final_val_loss": history[-1]["val_loss"],
            "final_val_rmse_delta": val_rmse,
            "epochs": epochs,
            "samples": int(n),
        },
        "prediction_mode": prediction_mode,
        "device_info": device_info,
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

    return TrainResult(
        model_key=model_key,
        output_dir=output_dir,
        final_train_loss=history[-1]["train_loss"],
        final_val_loss=history[-1]["val_loss"],
        final_val_rmse=val_rmse,
        epochs=epochs,
        samples=int(n),
        device=device_info,
        history=history,
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _default_output_dir(dataset_dir: Path) -> Path:
    models_root = Path(__file__).resolve().parent / "models"
    models_root.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    import uuid as _uuid
    mk = f"vision_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{_uuid.uuid4().hex[:6]}"
    return models_root / mk


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="M8.4 vision-conditioned imitation-learning trainer")
    p.add_argument("--dataset", required=True, help="path to LeRobot-format dataset dir (recording_*)")
    p.add_argument("--output-dir", default=None, help="where to write model; defaults to apps/realtime/models/vision_<ts>")
    p.add_argument("--model-key", default=None, help="explicit model_key (defaults to output dir name)")
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--hidden", type=int, default=128)
    p.add_argument("--val-ratio", type=float, default=0.1)
    p.add_argument("--prediction-mode", choices=["delta", "absolute"], default="delta")
    p.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto", dest="prefer_device")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--no-pretrained", action="store_true", help="use random-init ResNet18 (offline / privacy)")
    args = p.parse_args(argv)

    dataset_dir = Path(args.dataset).resolve()
    if not dataset_dir.exists():
        print(f"error: dataset dir not found: {dataset_dir}", file=sys.stderr)
        return 2
    out_dir = Path(args.output_dir).resolve() if args.output_dir else _default_output_dir(dataset_dir)

    try:
        res = train(
            dataset_dir=dataset_dir,
            output_dir=out_dir,
            epochs=args.epochs,
            batch_size=args.batch_size,
            lr=args.lr,
            hidden=args.hidden,
            val_ratio=args.val_ratio,
            prediction_mode=args.prediction_mode,
            prefer_device=args.prefer_device,
            seed=args.seed,
            pretrained_encoder=not args.no_pretrained,
            model_key=args.model_key,
        )
    except Exception as e:
        _log(f"TRAINING FAILED: {e}")
        traceback.print_exc()
        _progress("failed", error=str(e))
        return 1

    _log("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
