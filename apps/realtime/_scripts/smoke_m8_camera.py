#!/usr/bin/env python3
"""M8.1 Camera smoke test.

Verifies:
  1. GET /api/camera/devices  → 200, returns device list
  2. GET /api/camera/snapshot → JPEG bytes (if camera attached) or 503
  3. GET /api/camera/mjpeg    → multipart stream header (if camera attached)
  4. WS  /ws/camera           → binary JPEG frame (if camera attached)

Usage:
    python _scripts/smoke_m8_camera.py [--base http://localhost:8002]
"""
from __future__ import annotations

import argparse
import sys

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
    skip_count = 0

    # 1. Device list
    print("\n--- M8.1 Camera Smoke Test ---\n")
    try:
        r = httpx.get(f"{base}/api/camera/devices", timeout=10)
        assert r.status_code == 200, f"status={r.status_code}"
        data = r.json()
        devices = data.get("devices", [])
        print(f"  {PASS} GET /api/camera/devices  → {len(devices)} device(s)")
        for d in devices:
            print(f"      /dev/video{d['index']}  {d['width']}×{d['height']}  {d.get('fps',0):.0f}fps  {d.get('backend','')}")
        ok_count += 1
    except Exception as e:
        print(f"  {FAIL} GET /api/camera/devices  → {e}")
        fail_count += 1
        devices = []

    has_camera = len(devices) > 0

    # 2. Snapshot
    if has_camera:
        try:
            r = httpx.get(f"{base}/api/camera/snapshot", timeout=10)
            assert r.status_code == 200, f"status={r.status_code}"
            assert r.headers.get("content-type", "").startswith("image/jpeg")
            size_kb = len(r.content) / 1024
            assert size_kb > 1, "JPEG too small"
            print(f"  {PASS} GET /api/camera/snapshot → {size_kb:.1f} KB JPEG")
            ok_count += 1
        except Exception as e:
            print(f"  {FAIL} GET /api/camera/snapshot → {e}")
            fail_count += 1
    else:
        print(f"  {SKIP} GET /api/camera/snapshot  (no camera)")
        skip_count += 1

    # 3. MJPEG stream (just check we get the right content-type + first boundary)
    if has_camera:
        try:
            with httpx.stream("GET", f"{base}/api/camera/mjpeg?fps=5", timeout=10) as r:
                assert r.status_code == 200, f"status={r.status_code}"
                ct = r.headers.get("content-type", "")
                assert "multipart/x-mixed-replace" in ct, f"bad content-type: {ct}"
                chunk = b""
                for part in r.iter_bytes():
                    chunk += part
                    if b"--frame" in chunk and b"\xff\xd8" in chunk:
                        break
                    if len(chunk) > 500_000:
                        break
                assert b"--frame" in chunk, "no MJPEG boundary found"
                print(f"  {PASS} GET /api/camera/mjpeg   → streaming OK ({len(chunk)} bytes read)")
                ok_count += 1
        except Exception as e:
            print(f"  {FAIL} GET /api/camera/mjpeg   → {e}")
            fail_count += 1
    else:
        print(f"  {SKIP} GET /api/camera/mjpeg    (no camera)")
        skip_count += 1

    # 4. WebSocket binary frames — wait briefly for MJPEG to release the device
    import time
    time.sleep(1)
    if has_camera:
        try:
            import websockets.sync.client as wsc
            with wsc.connect(f"{base.replace('http','ws')}/ws/camera?fps=5", close_timeout=5) as ws:
                frame = ws.recv(timeout=5)
                assert isinstance(frame, bytes), "expected binary frame"
                assert len(frame) > 500, f"frame too small ({len(frame)} bytes)"
                assert frame[:2] == b"\xff\xd8", "not a JPEG"
                print(f"  {PASS} WS  /ws/camera          → {len(frame)/1024:.1f} KB JPEG frame")
                ok_count += 1
        except ImportError:
            print(f"  {SKIP} WS  /ws/camera           (websockets not installed)")
            skip_count += 1
        except Exception as e:
            print(f"  {FAIL} WS  /ws/camera          → {e}")
            fail_count += 1
    else:
        print(f"  {SKIP} WS  /ws/camera           (no camera)")
        skip_count += 1

    # Summary
    total = ok_count + fail_count + skip_count
    print(f"\n  Results: {ok_count}/{total} passed, {fail_count} failed, {skip_count} skipped\n")
    sys.exit(1 if fail_count > 0 else 0)


if __name__ == "__main__":
    main()
