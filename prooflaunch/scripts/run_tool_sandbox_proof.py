#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.tool_execution_sandbox import (
    SCHEMA,
    content_digest,
    validate_tool_sandbox_receipt,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "evidence/v10/tool-execution-sandbox-v1.json"
DEFAULT_IMAGE = "python:3.12-alpine3.22"


def _run(argv: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, check=check, capture_output=True, text=True)


def _ensure_image(image: str) -> None:
    if _run(["docker", "image", "inspect", image], check=False).returncode != 0:
        _run(["docker", "pull", image])


def _mount_flags(inspect: dict[str, object]) -> dict[str, bool]:
    mounts = inspect.get("Mounts")
    if not isinstance(mounts, list):
        mounts = []
    by_destination = {
        str(item.get("Destination")): item
        for item in mounts
        if isinstance(item, dict)
    }
    work = by_destination.get("/work", {})
    probe = by_destination.get("/opt/prooflaunch/tool_sandbox_probe.py", {})
    secret = by_destination.get("/run/secrets/prooflaunch_tool_token", {})
    writable_binds = [
        item
        for item in mounts
        if isinstance(item, dict)
        and item.get("Type") == "bind"
        and item.get("RW") is True
    ]
    return {
        "workspace_is_only_writable_bind": (
            len(writable_binds) == 1
            and work.get("RW") is True
            and work.get("Type") == "bind"
        ),
        "probe_code_readonly": probe.get("RW") is False,
        "secret_mount_readonly": secret.get("RW") is False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run and seal the Docker tool-sandbox proof.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    args = parser.parse_args()
    if args.image != DEFAULT_IMAGE:
        raise SystemExit("only the reviewed sandbox image is admitted")
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    _ensure_image(args.image)
    container_name = f"prooflaunch-tool-sandbox-{os.getpid()}-{secrets.token_hex(4)}"
    secret_value = secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory(prefix="prooflaunch-tool-sandbox-") as temp_name:
        temp = Path(temp_name)
        workspace = temp / "work"
        workspace.mkdir()
        workspace.chmod(0o777)
        secret_path = temp / "tool-token"
        secret_path.write_text(secret_value, encoding="utf-8")
        secret_path.chmod(0o444)
        probe_path = ROOT / "scripts/tool_sandbox_probe.py"
        create_argv = [
            "docker", "create",
            "--name", container_name,
            "--label", "prooflaunch.scope=tool-sandbox-proof",
            "--network", "none",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true",
            "--user", "10001:10001",
            "--pids-limit", "32",
            "--memory", "256m",
            "--cpus", "1.0",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m",
            "--env", "PROOFLAUNCH_JOB_CONTEXT=public-synthetic-bounded-tool-job",
            "--mount", f"type=bind,src={workspace},dst=/work",
            "--mount", f"type=bind,src={probe_path},dst=/opt/prooflaunch/tool_sandbox_probe.py,readonly",
            "--mount", f"type=bind,src={secret_path},dst=/run/secrets/prooflaunch_tool_token,readonly",
            args.image,
            "python", "/opt/prooflaunch/tool_sandbox_probe.py",
        ]
        try:
            _run(create_argv)
            started = _run(["docker", "start", "--attach", container_name], check=False)
            inspect_rows = json.loads(_run(["docker", "inspect", container_name]).stdout)
            if started.returncode != 0:
                raise RuntimeError(f"sandbox container failed: {started.stderr.strip()}")
            if not isinstance(inspect_rows, list) or len(inspect_rows) != 1:
                raise RuntimeError("sandbox container inspect shape is invalid")
            inspect = inspect_rows[0]
            inner_path = workspace / "inner-probe.json"
            inner_text = inner_path.read_text(encoding="utf-8")
            if secret_value in inner_text:
                raise RuntimeError("secret literal persisted in inner receipt")
            inner = json.loads(inner_text)
            image_rows = json.loads(_run(["docker", "image", "inspect", args.image]).stdout)
            if not isinstance(image_rows, list) or len(image_rows) != 1:
                raise RuntimeError("sandbox image inspect shape is invalid")
            image_inspect = image_rows[0]
            host = inspect["HostConfig"]
            config = inspect["Config"]
            security = {
                "network_mode_none": host.get("NetworkMode") == "none",
                "readonly_rootfs": host.get("ReadonlyRootfs") is True,
                "all_capabilities_dropped": "ALL" in (host.get("CapDrop") or []),
                "no_new_privileges": "no-new-privileges:true" in (host.get("SecurityOpt") or []),
                "non_root_user": str(config.get("User")) not in {"", "0", "0:0", "root"},
                "pids_limited": int(host.get("PidsLimit") or 0) == 32,
                "memory_limited": int(host.get("Memory") or 0) == 256 * 1024 * 1024,
                "cpu_limited": int(host.get("NanoCpus") or 0) == 1_000_000_000,
                **_mount_flags(inspect),
            }
            receipt: dict[str, object] = {
                "schema": SCHEMA,
                "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "runtime": "docker",
                "image": {
                    "requested_ref": args.image,
                    "image_id": image_inspect["Id"],
                    "repo_digests": image_inspect.get("RepoDigests") or [],
                },
                "container_security": security,
                "identity": inner["identity"],
                "probes": inner["probes"],
                "secret_boundary": inner["secret_boundary"],
                "probe_source_sha256": sha256_file(probe_path),
                "automatic_external_action_enabled": False,
                "passed": all(security.values()) and all(
                    inner["probes"].get(name) is True
                    for name in (
                        "workspace_write_succeeded",
                        "root_filesystem_write_blocked",
                        "filesystem_escape_blocked",
                        "dns_egress_blocked",
                        "tcp_egress_blocked",
                    )
                ) and all(
                    inner["secret_boundary"].get(name) is expected
                    for name, expected in {
                        "mounted_at_tool_boundary": True,
                        "readable_by_tool": True,
                        "present_in_environment": False,
                        "present_in_job_context": False,
                        "persisted_in_receipt": False,
                    }.items()
                ),
                "truth_boundary": (
                    "This receipt proves the reviewed Docker tool adapter blocked filesystem escape "
                    "and all egress for one representative bounded job. It does not prove a hosted "
                    "deployment, connector authorization, business effect, Radeon execution, or all future tools."
                ),
            }
            receipt["content_sha256"] = content_digest(receipt)
            serialized = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            if secret_value in serialized:
                raise RuntimeError("secret literal persisted in final receipt")
            validate_tool_sandbox_receipt(receipt)
            atomic_write_text(output, serialized)
        finally:
            _run(["docker", "rm", "--force", container_name], check=False)
    print(json.dumps({"output": str(output), "passed": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

