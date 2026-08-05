from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    port = free_port()
    command = [
        sys.executable,
        "-c",
        f"from privateops.server import run_server,create_app; run_server(create_app(), port={port})",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(40):
            try:
                get_json(base + "/api/health")
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("PrivateOps server did not become ready.")
        status = get_json(base + "/api/status")
        audit_before = get_json(base + "/api/audit")
        try:
            post_json(base + "/api/chat", {"prompt": "Audit this project for hackathon submission readiness"})
        except urllib.error.HTTPError as error:
            assert error.code == 409
            error_payload = json.loads(error.read().decode("utf-8"))
        else:
            raise AssertionError("An unconfigured server must require a provider.")
        audit_after = get_json(base + "/api/audit")
        assert status["provider_mode"] == "development"
        assert error_payload["error"]["code"] == "provider_required"
        assert audit_after == audit_before
        print(json.dumps({"status": "ok", "provider": status["provider"], "provider_required": True, "audit_unchanged": True}, indent=2))
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    main()
