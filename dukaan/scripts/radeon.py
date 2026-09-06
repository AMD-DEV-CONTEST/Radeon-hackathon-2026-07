"""Drive the Radeon instance from a laptop: copy files up, run commands, pull files down.

The cloud exposes JupyterLab over HTTPS, so its REST API doubles as a file
transfer and remote shell channel. That is enough to deploy and run Dukaan on
the GPU box without ssh.

    export DUKAAN_INSTANCE=https://<host>/instances/<instance-id>

    python scripts/radeon.py put scripts/radeon_ltx.py dukaan/radeon_ltx.py
    python scripts/radeon.py run "rocm-smi --showproductname"
    python scripts/radeon.py get dukaan/frames/000.png /tmp/000.png
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import uuid
from pathlib import Path

import requests
import websocket

BASE = os.environ.get("DUKAAN_INSTANCE", "").rstrip("/")
if not BASE:
    sys.exit("set DUKAAN_INSTANCE to the JupyterLab base URL of the instance")


def put(local: str, remote: str) -> None:
    data = base64.b64encode(Path(local).read_bytes()).decode()
    r = requests.put(
        f"{BASE}/api/contents/{remote}",
        json={"type": "file", "format": "base64", "content": data},
        timeout=600,
    )
    r.raise_for_status()
    print(f"{local} -> {remote} ({len(data) * 3 // 4} bytes)")


def get(remote: str, local: str) -> None:
    r = requests.get(f"{BASE}/api/contents/{remote}", params={"format": "base64"}, timeout=600)
    r.raise_for_status()
    Path(local).write_bytes(base64.b64decode(r.json()["content"]))
    print(f"{remote} -> {local}")


def _kernel() -> str:
    r = requests.post(f"{BASE}/api/kernels", json={"name": "python3"}, timeout=120)
    r.raise_for_status()
    return r.json()["id"]


def _shutdown(kid: str) -> None:
    try:
        requests.delete(f"{BASE}/api/kernels/{kid}", timeout=60)
    except Exception:
        pass


def run(code: str, timeout: int = 3600, kid: str | None = None) -> str:
    """Execute python in a kernel on the instance, streaming stdout back."""
    own = kid is None
    kid = kid or _kernel()
    ws_url = f"{BASE.replace('https://', 'wss://').replace('http://', 'ws://')}/api/kernels/{kid}/channels"
    ws = websocket.create_connection(ws_url, timeout=60)
    msg_id = uuid.uuid4().hex
    ws.send(
        json.dumps(
            {
                "header": {"msg_id": msg_id, "username": "d", "session": uuid.uuid4().hex,
                           "msg_type": "execute_request", "version": "5.3"},
                "parent_header": {}, "metadata": {},
                "content": {"code": code, "silent": False, "store_history": False,
                            "user_expressions": {}, "allow_stdin": False, "stop_on_error": True},
                "channel": "shell",
            }
        )
    )
    out, deadline = [], time.time() + timeout
    try:
        while time.time() < deadline:
            ws.settimeout(max(1, deadline - time.time()))
            try:
                m = json.loads(ws.recv())
            except websocket.WebSocketTimeoutException:
                continue
            if m.get("parent_header", {}).get("msg_id") != msg_id:
                continue
            t = m["header"]["msg_type"]
            if t == "stream":
                sys.stdout.write(m["content"]["text"])
                sys.stdout.flush()
                out.append(m["content"]["text"])
            elif t == "error":
                text = f"{m['content']['ename']}: {m['content']['evalue']}\n" + "\n".join(
                    m["content"].get("traceback", [])[-6:]
                )
                print(text)
                out.append(text)
            elif t == "status" and m["content"]["execution_state"] == "idle":
                break
    finally:
        ws.close()
        if own:
            _shutdown(kid)
    return "".join(out)


def shell(cmd: str, timeout: int = 3600) -> str:
    """Run a shell command, streaming output line by line as it happens."""
    code = (
        "import subprocess, sys\n"
        f"p = subprocess.Popen({cmd!r}, shell=True, stdout=subprocess.PIPE,\n"
        "                     stderr=subprocess.STDOUT, text=True, bufsize=1)\n"
        "for line in p.stdout:\n"
        "    sys.stdout.write(line); sys.stdout.flush()\n"
        "print('EXIT', p.wait())\n"
    )
    return run(code, timeout=timeout)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    verb, rest = sys.argv[1], sys.argv[2:]
    if verb == "put":
        put(rest[0], rest[1])
    elif verb == "get":
        get(rest[0], rest[1])
    elif verb == "run":
        shell(" ".join(rest))
    else:
        sys.exit(f"unknown verb {verb}")
