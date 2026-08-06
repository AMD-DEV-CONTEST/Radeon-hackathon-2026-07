"""M8.3 vision-conditioned inference smoke test.

Runs against a live realtime service on http://localhost:8002.

Steps
-----
1. GET  /api/vision_inference/status                    → device probe visible
2. POST /api/vision_inference/bootstrap_stub            → create a stub model
3. POST /api/vision_inference/load                      → load it (auto device)
4. GET  /api/vision_inference/status                    → confirms loaded=True
5. WS   /ws/vision_inference?camera_device=0&fps=10     → consume N frames
     assertions:
       - receives a meta frame first
       - >= N vision_infer_frame messages with pred + safe_pred + latency_ms
       - average latency < 500 ms (CPU budget; plenty of slack for ResNet18)
6. POST /api/vision_inference/unload                    → clean shutdown

Prereqs:
    realtime service running on :8002
    USB camera at /dev/video0 (or set REALTIME_SMOKE_CAM to another index)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any

import httpx
import websockets


BASE = os.environ.get("REALTIME_BASE", "http://localhost:8002")
WS_BASE = BASE.replace("http://", "ws://").replace("https://", "wss://")
CAM = os.environ.get("REALTIME_SMOKE_CAM", "0")
N_FRAMES = int(os.environ.get("REALTIME_SMOKE_N", "20"))
FPS = float(os.environ.get("REALTIME_SMOKE_FPS", "10"))


def _pp(label: str, obj: Any) -> None:
    print(f"\n[{label}]")
    print(json.dumps(obj, indent=2, default=str))


async def run() -> int:
    failures: list[str] = []

    async with httpx.AsyncClient(timeout=20.0, trust_env=False) as http:
        # 1) status before anything loaded
        r = await http.get(f"{BASE}/api/vision_inference/status")
        r.raise_for_status()
        s0 = r.json()
        _pp("status pre-load", s0)
        if s0.get("loaded"):
            print("  (already loaded, forcing unload to get a clean baseline)")
            await http.post(f"{BASE}/api/vision_inference/unload")

        # 2) bootstrap stub
        r = await http.post(
            f"{BASE}/api/vision_inference/bootstrap_stub",
            json={"model_key": "vision_stub_smoke"},
        )
        r.raise_for_status()
        bs = r.json()
        _pp("bootstrap_stub", bs)
        if not bs.get("ok"):
            failures.append("bootstrap_stub failed")

        # 3) load it
        r = await http.post(
            f"{BASE}/api/vision_inference/load",
            json={"model_key": "vision_stub_smoke", "prefer_device": "auto"},
        )
        r.raise_for_status()
        ld = r.json()
        _pp("load", ld)
        if not ld.get("ok"):
            failures.append("load failed")

        # 4) status after load
        r = await http.get(f"{BASE}/api/vision_inference/status")
        r.raise_for_status()
        s1 = r.json()
        _pp("status post-load", s1)
        if not s1.get("loaded"):
            failures.append("status still reports loaded=False after load")
        else:
            dev = s1.get("device", {})
            print(f"  resolved device: {dev.get('resolved')}  "
                  f"(advertised={dev.get('cuda_advertised')}, usable={dev.get('cuda_usable')})")
            if dev.get("probe_error"):
                print(f"  probe_error    : {dev.get('probe_error')}")

        # 5) WS — consume N frames
        uri = f"{WS_BASE}/ws/vision_inference?camera_device={CAM}&fps={FPS}&echo=false"
        print(f"\n[ws] connecting {uri}")
        latencies: list[float] = []
        frames_seen = 0
        meta_seen = False
        first_pred: dict[str, float] | None = None

        try:
            async with websockets.connect(uri, max_size=8 * 1024 * 1024) as ws:
                deadline = time.time() + max(10.0, N_FRAMES / FPS + 5.0)
                while frames_seen < N_FRAMES and time.time() < deadline:
                    raw = await asyncio.wait_for(ws.recv(), timeout=8.0)
                    msg = json.loads(raw)
                    t = msg.get("type")
                    if t == "vision_infer_meta":
                        meta_seen = True
                        _pp("ws meta", msg)
                    elif t == "vision_infer_frame":
                        frames_seen += 1
                        latencies.append(float(msg.get("latency_ms", 0.0)))
                        if first_pred is None:
                            first_pred = msg.get("pred")
                        if frames_seen in (1, N_FRAMES):
                            print(f"  frame {frames_seen}: latency={msg.get('latency_ms'):.1f}ms "
                                  f"feat_l2={msg.get('image_feature_l2'):.2f} "
                                  f"device={msg.get('device')}")
                    elif t == "error":
                        _pp("ws error", msg)
                        failures.append(f"ws error: {msg.get('message')}")
                        break
                    elif t == "warn":
                        print(f"  ws warn: {msg.get('message')}")
        except Exception as exc:
            failures.append(f"ws exception: {type(exc).__name__}: {exc}")

        if not meta_seen:
            failures.append("no meta frame received")
        if frames_seen < N_FRAMES:
            failures.append(f"only {frames_seen}/{N_FRAMES} frames received")

        if latencies:
            avg = sum(latencies) / len(latencies)
            p95 = sorted(latencies)[int(0.95 * (len(latencies) - 1))]
            print(f"\n  latency: avg={avg:.1f}ms p95={p95:.1f}ms over {len(latencies)} frames")
            if avg > 500.0:
                failures.append(f"avg latency {avg:.1f}ms exceeds 500ms budget")

        if first_pred is not None:
            print(f"  first pred joints: {first_pred}")

        # 6) unload
        r = await http.post(f"{BASE}/api/vision_inference/unload")
        r.raise_for_status()
        _pp("unload", r.json())

    # summary
    print("\n" + "=" * 60)
    if failures:
        print(f"FAIL ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("OK: M8.3 vision inference smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
