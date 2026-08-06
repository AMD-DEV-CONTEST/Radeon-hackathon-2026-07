from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping


SCHEMA = "ProofLaunchToolExecutionSandboxReceiptV1"
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def validate_tool_sandbox_receipt(receipt: Mapping[str, object]) -> None:
    if receipt.get("schema") != SCHEMA:
        raise ValueError("tool sandbox receipt schema is invalid")
    unsigned = dict(receipt)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != content_digest(unsigned):
        raise ValueError("tool sandbox receipt digest is invalid")
    image = receipt.get("image")
    security = receipt.get("container_security")
    probes = receipt.get("probes")
    secret = receipt.get("secret_boundary")
    if not all(isinstance(value, Mapping) for value in (image, security, probes, secret)):
        raise ValueError("tool sandbox receipt sections are incomplete")
    assert isinstance(image, Mapping)
    assert isinstance(security, Mapping)
    assert isinstance(probes, Mapping)
    assert isinstance(secret, Mapping)
    if not _SHA256.fullmatch(str(image.get("image_id", "")).removeprefix("sha256:")):
        raise ValueError("tool sandbox image identity is not immutable")
    required_security = {
        "network_mode_none": True,
        "readonly_rootfs": True,
        "all_capabilities_dropped": True,
        "no_new_privileges": True,
        "non_root_user": True,
        "pids_limited": True,
        "memory_limited": True,
        "cpu_limited": True,
        "workspace_is_only_writable_bind": True,
        "probe_code_readonly": True,
        "secret_mount_readonly": True,
    }
    for name, expected in required_security.items():
        if security.get(name) is not expected:
            raise ValueError(f"tool sandbox security invariant failed: {name}")
    required_probes = {
        "workspace_write_succeeded": True,
        "root_filesystem_write_blocked": True,
        "filesystem_escape_blocked": True,
        "dns_egress_blocked": True,
        "tcp_egress_blocked": True,
    }
    for name, expected in required_probes.items():
        if probes.get(name) is not expected:
            raise ValueError(f"tool sandbox behavioral probe failed: {name}")
    required_secret = {
        "mounted_at_tool_boundary": True,
        "readable_by_tool": True,
        "present_in_environment": False,
        "present_in_job_context": False,
        "persisted_in_receipt": False,
    }
    for name, expected in required_secret.items():
        if secret.get(name) is not expected:
            raise ValueError(f"tool sandbox secret invariant failed: {name}")
    if receipt.get("passed") is not True:
        raise ValueError("tool sandbox receipt did not pass")

