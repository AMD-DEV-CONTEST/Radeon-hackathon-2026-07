#!/usr/bin/env python3
"""End-to-end demo: orchestrator → worker → task lifecycle.

Usage:
    python examples/run_demo.py

Requires:
    - PostgreSQL with DATABASE_URL env var (or set below)
    - orchestrator + worker packages installed (pip install -e .)
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib import error, request

REPO_ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://127.0.0.1:8000")
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://unionagents:unionagents@localhost:5432/unionagents"
)
WORKER_NAME = "demo-worker"


def _post_json(path: str, payload: dict) -> dict:
    url = f"{ORCHESTRATOR_URL.rstrip('/')}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"POST {url} {exc.code}: {detail}") from exc
    return json.loads(body) if body else {}


def _get_json(path: str) -> dict:
    url = f"{ORCHESTRATOR_URL.rstrip('/')}{path}"
    with request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_for_health(timeout: int = 30) -> None:
    print("[demo] waiting for orchestrator health check...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = _get_json("/health")
            if resp.get("status") == "ok":
                print(f"[demo] orchestrator healthy: {resp}")
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("Orchestrator did not become healthy within timeout.")


def main() -> int:
    os.environ["DATABASE_URL"] = DATABASE_URL

    # ── start orchestrator ─────────────────────────────────────────────
    print("[demo] starting orchestrator (uvicorn)...")
    orch = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "orchestrator.main:app",
            "--host", "127.0.0.1",
            "--port", "8000",
        ],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    worker = None
    try:
        wait_for_health()

        # ── register worker ────────────────────────────────────────────
        print("[demo] registering worker...")
        reg = _post_json("/agents/register", {
            "name": WORKER_NAME,
            "agent_type": "generic",
            "host_id": "demo-host",
            "os": "windows" if os.name == "nt" else "linux",
            "shell": "powershell" if os.name == "nt" else "bash",
            "python_version": sys.version.split()[0],
            "available_commands": ["echo", "python"],
            "workspace_root": str(REPO_ROOT),
            "max_concurrency": 1,
            "network_capabilities": ["outbound-http"],
            "capabilities": {},
        })
        agent_id = reg["agent_id"]
        print(f"[demo] worker registered: agent_id={agent_id}")

        # ── create demo task ───────────────────────────────────────────
        print("[demo] creating demo task...")
        task_def = json.loads((REPO_ROOT / "examples" / "demo_task.json").read_text())
        task_resp = _post_json("/tasks", task_def)
        task_id = task_resp["id"]
        print(f"[demo] task created: task_id={task_id}")

        # ── start worker in polling mode ───────────────────────────────
        print("[demo] starting worker CLI (poll loop)...")
        worker = subprocess.Popen(
            [
                sys.executable, "-m", "worker.worker_cli",
                "--orchestrator-url", ORCHESTRATOR_URL,
                "--name", WORKER_NAME,
                "--host-id", "demo-host",
                "--agent-type", "generic",
                "--workspace-root", str(REPO_ROOT),
                "--max-concurrency", "1",
                "--poll-interval", "2",
                "run",
            ],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        # ── wait for task → done ───────────────────────────────────────
        print("[demo] waiting for task to reach 'done'...")
        deadline = time.time() + 120
        final_status = None
        while time.time() < deadline:
            status_json = _get_json(f"/tasks/{task_id}")
            final_status = status_json.get("status")
            print(f"[demo]   task status: {final_status}")
            if final_status in ("done", "failed_final", "cancelled"):
                break
            time.sleep(2)

        if final_status == "done":
            print("\n✅ DEMO PASSED — task completed with status 'done'")
            return 0
        else:
            print(f"\n❌ DEMO FAILED — task ended with status '{final_status}'")
            return 1

    finally:
        print("[demo] stopping orchestrator...")
        orch.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
        orch.wait(timeout=10)
        # kill worker if still running
        if worker is not None:
            worker.terminate()
            worker.wait(timeout=5)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
