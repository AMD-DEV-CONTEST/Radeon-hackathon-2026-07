"""M8.4 vision-training end-to-end smoke test.

Exercises the full happy path:

    (1)  trainer_vision.py standalone invocation
         → produces apps/realtime/models/<key>/{checkpoint.pt, model.json}
    (2)  POST /api/vision_inference/load  with that model_key
    (3)  GET  /api/vision_inference/status to confirm loaded=True
    (4)  WS  /ws/vision_inference?camera_device=…  for a handful of frames
    (5)  POST /api/vision_inference/unload

Does NOT go through the API /api/v1/trainings path — that is covered by a
manual curl run and is sensitive to auth setup. This script is pure plumbing
verification and can be run on any box that has the realtime service up.

Usage
-----
    cd apps/realtime
    .venv/bin/python _scripts/smoke_m8_vision_train.py                  # uses most recent vision dataset
    REALTIME_SMOKE_DATASET=datasets/recording_20260421_010836 \
        .venv/bin/python _scripts/smoke_m8_vision_train.py
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import websockets


REALTIME_ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("REALTIME_BASE", "http://localhost:8002")
WS_BASE = BASE.replace("http://", "ws://").replace("https://", "wss://")
CAM = os.environ.get("REALTIME_SMOKE_CAM", "0")
N_FRAMES = int(os.environ.get("REALTIME_SMOKE_N", "10"))
FPS = float(os.environ.get("REALTIME_SMOKE_FPS", "10"))
EPOCHS = int(os.environ.get("REALTIME_SMOKE_EPOCHS", "5"))


def _pick_dataset() -> Path:
    """Pick the most recently modified recording with images/cam_main/."""
    explicit = os.environ.get("REALTIME_SMOKE_DATASET")
    if explicit:
        p = (REALTIME_ROOT / explicit) if not os.path.isabs(explicit) else Path(explicit)
        if not p.exists():
            raise SystemExit(f"REALTIME_SMOKE_DATASET points to nonexistent path: {p}")
        return p

    roots = list((REALTIME_ROOT / "datasets").glob("recording_*"))
    roots = [r for r in roots if (r / "images" / "cam_main").exists() and any((r / "images" / "cam_main").iterdir())]
    if not roots:
        raise SystemExit(
            f"no vision dataset under {REALTIME_ROOT / 'datasets'}. "
            "Record one first via the Teleop page with 'Record with camera' enabled, "
            "or run the M8.2 vision-record smoke test."
        )
    roots.sort(key=lambda r: r.stat().st_mtime, reverse=True)
    return roots[0]


def _pp(label: str, obj: Any) -> None:
    print(f"\n[{label}]")
    print(json.dumps(obj, indent=2, default=str))


async def run() -> int:
    failures: list[str] = []
    dataset = _pick_dataset()
    print(f"Using dataset: {dataset}")

    # -------- (1) Standalone training --------
    out_dir = REALTIME_ROOT / "models" / f"vision_smoke_{int(time.time())}"
    cmd = [
        sys.executable,
        str(REALTIME_ROOT / "trainer_vision.py"),
        "--dataset", str(dataset),
        "--output-dir", str(out_dir),
        "--epochs", str(EPOCHS),
        "--batch-size", "8",
        "--hidden", "64",
        "--val-ratio", "0.2",
        "--no-pretrained",  # speed; we only care about the plumbing
    ]
    print(f"\n[1] training subprocess: {' '.join(cmd)}")
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    dt = time.time() - t0
    print(f"  exit_code={res.returncode}  dt={dt:.1f}s")
    for line in (res.stdout or "").splitlines()[-8:]:
        print(f"  > {line}")
    if res.returncode != 0:
        print(f"STDERR tail:")
        for line in (res.stderr or "").splitlines()[-10:]:
            print(f"  ! {line}")
        failures.append(f"trainer_vision exit_code={res.returncode}")

    meta_path = out_dir / "model.json"
    ckpt_path = out_dir / "checkpoint.pt"
    if not meta_path.exists() or not ckpt_path.exists():
        failures.append(f"training output missing: meta={meta_path.exists()} ckpt={ckpt_path.exists()}")
    else:
        meta = json.loads(meta_path.read_text())
        _pp("model.json metrics", meta.get("metrics"))
        rmse = (meta.get("metrics") or {}).get("final_val_rmse_delta")
        if rmse is None or rmse > 0.5:  # sanity bound: delta rmse > 0.5rad = almost certainly broken
            failures.append(f"suspicious final_val_rmse_delta={rmse}")

    if failures:
        print("\nABORT: training step failed, skipping inference smoke")
        print(f"\nFAIL ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1

    model_key = out_dir.name

    # -------- (2) Load via vision_inference --------
    async with httpx.AsyncClient(timeout=20.0, trust_env=False) as http:
        r = await http.post(
            f"{BASE}/api/vision_inference/load",
            json={"model_key": model_key, "prefer_device": "auto"},
        )
        if r.status_code != 200:
            failures.append(f"/load returned {r.status_code}: {r.text[:200]}")
        else:
            _pp("load", r.json())

        # -------- (3) Status check --------
        r = await http.get(f"{BASE}/api/vision_inference/status")
        r.raise_for_status()
        s = r.json()
        _pp("status post-load", s)
        if not s.get("loaded"):
            failures.append("status.loaded != True after load")
        if s.get("model_key") != model_key:
            failures.append(f"status.model_key = {s.get('model_key')!r}, expected {model_key!r}")

        # -------- (4) WS a few frames --------
        uri = f"{WS_BASE}/ws/vision_inference?camera_device={CAM}&fps={FPS}&echo=false"
        print(f"\n[4] connecting {uri}")
        frames_seen = 0
        latencies: list[float] = []
        try:
            async with websockets.connect(uri, max_size=8 * 1024 * 1024) as ws:
                deadline = time.time() + max(8.0, N_FRAMES / FPS + 4.0)
                while frames_seen < N_FRAMES and time.time() < deadline:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=6.0))
                    if msg.get("type") == "vision_infer_frame":
                        frames_seen += 1
                        latencies.append(float(msg.get("latency_ms", 0.0)))
                    elif msg.get("type") == "error":
                        failures.append(f"ws error: {msg.get('message')}")
                        break
        except Exception as exc:
            failures.append(f"ws exception: {type(exc).__name__}: {exc}")

        if frames_seen < N_FRAMES:
            failures.append(f"only {frames_seen}/{N_FRAMES} frames received")
        if latencies:
            avg = sum(latencies) / len(latencies)
            print(f"  avg latency over {len(latencies)} frames: {avg:.1f} ms")

        # -------- (5) Unload --------
        r = await http.post(f"{BASE}/api/vision_inference/unload")
        r.raise_for_status()
        _pp("unload", r.json())

    print("\n" + "=" * 60)
    if failures:
        print(f"FAIL ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("OK: M8.4 vision training + inference smoke passed")
    print(f"     trained model:   {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
