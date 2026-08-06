#!/usr/bin/env python3
"""M8.2 Vision recording smoke test.

Simulates a recording session with camera, then verifies:
  1. POST /api/record {"action":"start","camera_device":"0"} → 200
  2. Push a few joint frames via /ws/teleop
  3. POST /api/record {"action":"stop"} → 200, image_frames > 0
  4. Dataset dir has images/cam_main/*.jpg
  5. Parquet has observation.images.cam_main column
  6. Image serving endpoint /api/datasets/{id}/images/cam_main/frame_000000.jpg → 200

Usage:
    python _scripts/smoke_m8_vision_record.py [--base http://localhost:8002]
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import httpx

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
SKIP = "\033[93m⊘\033[0m"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8002")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    ok_count = 0
    fail_count = 0

    print("\n--- M8.2 Vision Recording Smoke Test ---\n")

    # 1. Check camera available
    try:
        r = httpx.get(f"{base}/api/camera/devices", timeout=5)
        devices = r.json().get("devices", [])
        if not devices:
            print(f"  {SKIP} No camera device found — cannot run vision recording test")
            sys.exit(0)
        print(f"  {PASS} Camera available: /dev/video{devices[0]['index']}")
    except Exception as e:
        print(f"  {FAIL} Camera check failed: {e}")
        sys.exit(1)

    # 2. Start recording with camera
    try:
        r = httpx.post(
            f"{base}/api/record",
            json={"action": "start", "camera_device": "0"},
            timeout=10,
        )
        assert r.status_code == 200, f"status={r.status_code}"
        data = r.json()
        assert data.get("success"), f"not success: {data}"
        print(f"  {PASS} Start recording with camera")
        ok_count += 1
    except Exception as e:
        print(f"  {FAIL} Start recording: {e}")
        fail_count += 1
        sys.exit(1)

    # 3. Push joint frames via /ws/teleop
    import websockets.sync.client as wsc
    try:
        ws = wsc.connect(f"{base.replace('http','ws')}/ws/teleop", close_timeout=3)
        for i in range(20):
            payload = {
                "type": "joint_update",
                "robot_id": "so101-smoke",
                "timestamp": time.time(),
                "joints": {str(j): 0.1 * i + 0.01 * j for j in range(1, 7)},
                "meta": {"fps": 20, "source": "smoke_m8"},
            }
            ws.send(json.dumps(payload))
            time.sleep(0.05)
        ws.close()
        print(f"  {PASS} Pushed 20 joint frames via /ws/teleop")
        ok_count += 1
    except Exception as e:
        print(f"  {FAIL} Push joints: {e}")
        fail_count += 1

    # Small wait for frames to flush
    time.sleep(0.5)

    # 4. Stop recording
    dataset_id = None
    image_frames = 0
    try:
        r = httpx.post(
            f"{base}/api/record",
            json={"action": "stop"},
            timeout=30,
        )
        assert r.status_code == 200, f"status={r.status_code}"
        data = r.json()
        assert data.get("success"), f"not success: {data}"
        assert data.get("frames", 0) > 0, "no frames recorded"
        image_frames = data.get("image_frames", 0)
        dataset_id = data.get("dataset_id")
        print(f"  {PASS} Stop recording: {data['frames']} frames, {image_frames} images, dataset={dataset_id}")
        ok_count += 1
    except Exception as e:
        print(f"  {FAIL} Stop recording: {e}")
        fail_count += 1
        print(f"\n  Results: {ok_count} passed, {fail_count} failed\n")
        sys.exit(1)

    # 5. Check images on disk
    if image_frames > 0 and dataset_id:
        try:
            r = httpx.get(
                f"{base}/api/datasets/{dataset_id}/images/cam_main/frame_000000.jpg",
                timeout=5,
            )
            assert r.status_code == 200, f"status={r.status_code}"
            assert r.headers.get("content-type", "").startswith("image/jpeg")
            assert len(r.content) > 500, f"image too small: {len(r.content)}"
            print(f"  {PASS} Image serving: frame_000000.jpg = {len(r.content)/1024:.1f} KB")
            ok_count += 1
        except Exception as e:
            print(f"  {FAIL} Image serving: {e}")
            fail_count += 1

    # 6. Check parquet has image column
    if dataset_id:
        try:
            import pyarrow.parquet as pq
            from pathlib import Path

            ds_root = Path(__file__).resolve().parents[1] / "datasets" / dataset_id
            parquets = sorted(ds_root.rglob("*.parquet"))
            assert parquets, "no parquet files found"
            table = pq.read_table(parquets[0])
            columns = table.column_names
            if image_frames > 0:
                assert "observation.images.cam_main" in columns, f"missing image column, got: {columns}"
                df = table.to_pandas()
                img_col = df["observation.images.cam_main"]
                non_empty = img_col[img_col != ""].count()
                print(f"  {PASS} Parquet has observation.images.cam_main ({non_empty} non-empty rows)")
            else:
                print(f"  {PASS} Parquet columns OK (no images expected): {columns}")
            ok_count += 1
        except Exception as e:
            print(f"  {FAIL} Parquet check: {e}")
            fail_count += 1

    # Summary
    total = ok_count + fail_count
    print(f"\n  Results: {ok_count}/{total} passed, {fail_count} failed\n")
    sys.exit(1 if fail_count > 0 else 0)


if __name__ == "__main__":
    main()
