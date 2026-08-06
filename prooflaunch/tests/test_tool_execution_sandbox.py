from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.tool_execution_sandbox import (
    SCHEMA,
    content_digest,
    validate_tool_sandbox_receipt,
)


def valid_receipt() -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema": SCHEMA,
        "image": {"image_id": "sha256:" + "a" * 64},
        "container_security": {
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
        },
        "probes": {
            "workspace_write_succeeded": True,
            "root_filesystem_write_blocked": True,
            "filesystem_escape_blocked": True,
            "dns_egress_blocked": True,
            "tcp_egress_blocked": True,
        },
        "secret_boundary": {
            "mounted_at_tool_boundary": True,
            "readable_by_tool": True,
            "present_in_environment": False,
            "present_in_job_context": False,
            "persisted_in_receipt": False,
        },
        "passed": True,
    }
    receipt["content_sha256"] = content_digest(receipt)
    return receipt


class ToolExecutionSandboxTests(unittest.TestCase):
    def test_complete_receipt_passes(self) -> None:
        validate_tool_sandbox_receipt(valid_receipt())

    def test_security_or_secret_tamper_fails(self) -> None:
        for section, name, value in (
            ("container_security", "network_mode_none", False),
            ("probes", "filesystem_escape_blocked", False),
            ("secret_boundary", "present_in_environment", True),
        ):
            with self.subTest(section=section, name=name):
                receipt = copy.deepcopy(valid_receipt())
                receipt[section][name] = value  # type: ignore[index]
                receipt["content_sha256"] = content_digest(
                    {key: item for key, item in receipt.items() if key != "content_sha256"}
                )
                with self.assertRaises(ValueError):
                    validate_tool_sandbox_receipt(receipt)


if __name__ == "__main__":
    unittest.main()

