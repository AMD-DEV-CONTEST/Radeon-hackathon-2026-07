#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import socket
from pathlib import Path


WORKSPACE = Path("/work")
SECRET_PATH = Path("/run/secrets/prooflaunch_tool_token")


def _blocked_write(path: Path) -> tuple[bool, str]:
    try:
        path.write_text("escape", encoding="utf-8")
    except OSError as error:
        return True, type(error).__name__
    return False, "write_unexpectedly_succeeded"


def _dns_blocked() -> tuple[bool, str]:
    try:
        socket.getaddrinfo("example.com", 443)
    except OSError as error:
        return True, type(error).__name__
    return False, "dns_unexpectedly_succeeded"


def _tcp_blocked() -> tuple[bool, str]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        sock.connect(("1.1.1.1", 443))
    except OSError as error:
        return True, type(error).__name__
    finally:
        sock.close()
    return False, "tcp_unexpectedly_succeeded"


def main() -> int:
    job_context = os.environ.get("PROOFLAUNCH_JOB_CONTEXT", "")
    secret_value = SECRET_PATH.read_text(encoding="utf-8").strip()
    if not secret_value:
        raise RuntimeError("tool-boundary secret is empty")
    allowed_payload = b"prooflaunch-sandbox-workspace-write-v1\n"
    allowed_path = WORKSPACE / "allowed-output.bin"
    allowed_path.write_bytes(allowed_payload)
    root_blocked, root_error = _blocked_write(Path("/rootfs-escape.txt"))
    parent_blocked, parent_error = _blocked_write(WORKSPACE / ".." / "workspace-escape.txt")
    dns_blocked, dns_error = _dns_blocked()
    tcp_blocked, tcp_error = _tcp_blocked()
    environment_values = tuple(os.environ.values())
    inner = {
        "schema": "ProofLaunchToolSandboxInnerProbeV1",
        "identity": {"uid": os.getuid(), "gid": os.getgid(), "cwd": str(Path.cwd())},
        "probes": {
            "workspace_write_succeeded": allowed_path.read_bytes() == allowed_payload,
            "workspace_output_sha256": hashlib.sha256(allowed_payload).hexdigest(),
            "root_filesystem_write_blocked": root_blocked,
            "root_filesystem_error": root_error,
            "filesystem_escape_blocked": parent_blocked,
            "filesystem_escape_error": parent_error,
            "dns_egress_blocked": dns_blocked,
            "dns_egress_error": dns_error,
            "tcp_egress_blocked": tcp_blocked,
            "tcp_egress_error": tcp_error,
        },
        "secret_boundary": {
            "mounted_at_tool_boundary": SECRET_PATH.is_file(),
            "readable_by_tool": True,
            "present_in_environment": any(secret_value in value for value in environment_values),
            "present_in_job_context": secret_value in job_context,
            "persisted_in_receipt": False,
            "secret_length": len(secret_value),
        },
    }
    serialized = json.dumps(inner, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if secret_value in serialized:
        raise RuntimeError("secret literal entered the probe receipt")
    (WORKSPACE / "inner-probe.json").write_text(serialized, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

