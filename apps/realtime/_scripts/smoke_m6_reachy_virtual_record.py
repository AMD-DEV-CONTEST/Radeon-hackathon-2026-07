"""Reachy virtual mode + record endpoint dry smoke (no hardware).

Requires realtime API on http://127.0.0.1:8002 or set REACHY_SMOKE_BASE.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("REACHY_SMOKE_BASE", "http://127.0.0.1:8002").rstrip("/")


def _request(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    url = f"{BASE}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return resp.status, payload if isinstance(payload, dict) else {"raw": payload}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return exc.code, payload if isinstance(payload, dict) else {"detail": payload}


def main() -> None:
    print("=" * 60)
    print("Reachy virtual + record smoke")
    print("=" * 60)
    print(f"BASE={BASE}")

    code, virtual = _request("GET", "/api/reachy/virtual/status")
    assert code == 200, virtual
    print("[1] virtual status OK")

    code, start = _request("POST", "/api/reachy/virtual/start")
    assert code == 200 and start.get("active"), start
    print("[2] virtual start OK")

    code, state = _request("GET", "/api/reachy/state/full")
    assert code == 200 and "body_yaw" in state, state
    print("[3] virtual state/full OK")

    code, play = _request("POST", "/api/reachy/move/play/local-move/hello")
    assert code == 200 and play.get("uuid"), play
    print("[4] virtual local play hello OK")

    code, stop = _request("POST", "/api/reachy/move/stop", {"uuid": play.get("uuid")})
    assert code == 200, stop
    print("[5] virtual move stop OK")

    code, record = _request("POST", "/api/reachy/record/start", {"name": "smoke_test"})
    assert code in (409, 503), record
    print(f"[6] record start rejected without daemon (HTTP {code}) OK")

    code, _ = _request("POST", "/api/reachy/virtual/stop")
    assert code == 200, _
    print("[7] virtual stop OK")

    print()
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"[FAIL] {exc}")
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"[SKIP] API not reachable: {exc}")
        print("Start realtime on :8002 or set REACHY_SMOKE_BASE")
        sys.exit(0)
