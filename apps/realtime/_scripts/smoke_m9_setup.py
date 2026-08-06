"""M9.1 smoke test — setup / onboarding preflight endpoints.

Exercised endpoints:

  Realtime (:8002):
    GET  /api/setup/health
    GET  /api/setup/ports
    POST /api/setup/wiggle        (dry run — expect 'available' True/False)

  API (:8000):
    GET  /api/v1/setup/status

Hardware is not required. A machine with no SO-101 plugged in should still
pass: ports list will be empty-ish, wiggle will return ok=False with a clear
message, and /status should return overall='warning' not 'error'.

Run from repo root:

    ./apps/realtime/.venv/bin/python apps/realtime/_scripts/smoke_m9_setup.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict

import httpx

REALTIME_URL = os.environ.get("REALTIME_URL", "http://localhost:8002")
API_URL = os.environ.get("API_URL", "http://localhost:8000")


def pp(label: str, obj: Any) -> None:
    print(f"\n--- {label} ---")
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str)[:2000])


def check(cond: bool, msg: str) -> None:
    print(("[PASS] " if cond else "[FAIL] ") + msg)
    if not cond:
        sys.exit(1)


def main() -> None:
    # Strip proxies to avoid SOCKS/httpx interference in dev shells.
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
              "all_proxy", "ALL_PROXY"):
        os.environ.pop(k, None)

    with httpx.Client(timeout=10.0, trust_env=False) as client:
        # --- Realtime health -------------------------------------------
        r = client.get(f"{REALTIME_URL}/api/setup/health")
        check(r.status_code == 200, f"GET /api/setup/health -> {r.status_code}")
        health = r.json()
        pp("realtime health", health)
        check("video_device_count" in health, "health payload has video_device_count")
        check("serial_device_count" in health, "health payload has serial_device_count")
        check("rocm_probe_ok" in health, "health payload has rocm_probe_ok")

        # --- Realtime port scan ----------------------------------------
        t0 = time.time()
        r = client.get(f"{REALTIME_URL}/api/setup/ports")
        dt = time.time() - t0
        check(r.status_code == 200, f"GET /api/setup/ports -> {r.status_code}")
        ports = r.json()
        pp(f"realtime ports (scan took {dt:.2f}s)", ports)
        check("ports" in ports and isinstance(ports["ports"], list), "ports payload shape")
        # Hardware-less CI: scanned_count may be 0. Both acceptable.
        check(ports.get("scanned_count", -1) >= 0, "scanned_count present")

        # --- Wiggle dry-run --------------------------------------------
        first_port = ports["ports"][0]["port"] if ports["ports"] else "/dev/null"
        r = client.post(
            f"{REALTIME_URL}/api/setup/wiggle",
            json={"port": first_port, "delta_deg": 5, "cycles": 2},
        )
        check(r.status_code == 200, f"POST /api/setup/wiggle -> {r.status_code}")
        wig = r.json()
        pp("wiggle response", wig)
        check("ok" in wig and "available" in wig, "wiggle payload shape")
        # Safety: amplitude clamp
        r = client.post(
            f"{REALTIME_URL}/api/setup/wiggle",
            json={"port": "/dev/null", "delta_deg": 999, "cycles": 2},
        )
        check(r.status_code == 400, "wiggle rejects delta_deg=999 (safety)")

        # --- API aggregated status -------------------------------------
        r = client.get(f"{API_URL}/api/v1/setup/status")
        check(r.status_code == 200, f"GET /api/v1/setup/status -> {r.status_code}")
        status = r.json()
        pp("api status aggregator", status)
        check(status.get("overall") in ("ok", "warning", "error"),
              "status.overall is ok|warning|error")
        check(status["checks"]["realtime"]["reachable"] is True,
              "API -> Realtime reachable from inside status aggregator")
        check(isinstance(status.get("issues"), list), "status.issues is a list")
        check("next_action" in status and "path" in status["next_action"],
              "status.next_action has path")

    print("\n=== M9.1 SMOKE: PASS ===")


if __name__ == "__main__":
    main()
