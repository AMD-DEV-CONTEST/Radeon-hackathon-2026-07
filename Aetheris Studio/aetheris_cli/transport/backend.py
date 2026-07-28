"""
Backend health check, automatic process spawner with model env injection, and clean process termination.
Verifies backend availability on localhost port 8001, automatically spawns app.py with requested model, and terminates the server on CLI exit.
"""

import atexit
import os
import subprocess
import sys
import time
from typing import Optional, Tuple
from aetheris_cli.transport.client import AetherisClient

_SPAWNED_PROCESS: Optional[subprocess.Popen] = None


def stop_backend_server() -> None:
    global _SPAWNED_PROCESS
    if _SPAWNED_PROCESS and _SPAWNED_PROCESS.poll() is None:
        try:
            _SPAWNED_PROCESS.terminate()
            _SPAWNED_PROCESS.wait(timeout=3)
        except Exception:
            try:
                _SPAWNED_PROCESS.kill()
            except Exception:
                pass
        _SPAWNED_PROCESS = None


atexit.register(stop_backend_server)


def ensure_backend_running(client: AetherisClient, auto_spawn: bool = True, timeout: int = 30, model: str = "") -> Tuple[bool, str]:
    global _SPAWNED_PROCESS
    if client.is_backend_alive():
        try:
            health = client.get_health()
            return True, f"Backend online. Status: {health.get('status', 'ok')}"
        except Exception:
            return True, "Backend online."

    if not auto_spawn:
        return False, "Aetheris backend is not running at http://127.0.0.1:8001."

    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
    app_py_path = os.path.join(project_root, "app.py")

    if not os.path.exists(app_py_path):
        return False, f"app.py not found at {app_py_path}"

    sys.stdout.write("Aetheris backend server is starting in background (app.py)...\n")
    sys.stdout.flush()

    creation_flags = 0
    if os.name == "nt":
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    env = os.environ.copy()
    if model:
        env["AETHERIS_DEFAULT_MODEL"] = model

    try:
        _SPAWNED_PROCESS = subprocess.Popen(
            [sys.executable, app_py_path],
            cwd=project_root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
    except Exception as e:
        return False, f"Failed to spawn backend process: {e}"

    start_wait = time.time()
    while time.time() - start_wait < timeout:
        time.sleep(0.5)
        if not client.token:
            client.token = client._resolve_token()
            client.session.headers["X-Internal-Token"] = client.token
        if client.is_backend_alive():
            sys.stdout.write("Backend server started successfully!\n")
            sys.stdout.flush()
            return True, "Backend server started successfully."

    return False, f"Backend failed to respond within {timeout} seconds."


def check_backend_availability(client: AetherisClient, model: str = "") -> Tuple[bool, str]:
    return ensure_backend_running(client=client, auto_spawn=True, model=model)
