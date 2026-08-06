from __future__ import annotations

import unittest

from src.agent.permissions import PermissionDenied, PermissionPolicy
from src.agent.tool_registry import ToolDefinition, ToolRegistry


class ToolPermissionTests(unittest.TestCase):
    def test_registered_tool_is_audited(self) -> None:
        registry = ToolRegistry(
            definitions=(
                ToolDefinition(
                    "local_test",
                    "Test local GPU-like permission auditing.",
                    "AMD Radeon GPU / ROCm HIP",
                    ("read_uploaded_image", "gpu_inference"),
                ),
            )
        )
        result = registry.invoke(
            "local_test",
            lambda: {"status": "pass"},
            input_summary={"image_filename": "portrait.jpg"},
            output_summary=lambda value: value,
        )
        self.assertEqual(result["status"], "pass")
        self.assertEqual(registry.calls[0]["status"], "completed")
        self.assertEqual(
            {entry["decision"] for entry in registry.permission_audit},
            {"allow"},
        )
        self.assertNotIn("image_bytes", registry.calls[0]["input"])

    def test_external_network_permission_is_denied(self) -> None:
        registry = ToolRegistry(
            policy=PermissionPolicy(),
            definitions=(
                ToolDefinition(
                    "remote_test",
                    "A forbidden remote tool.",
                    "network",
                    ("external_network",),
                ),
            ),
        )
        with self.assertRaises(PermissionDenied):
            registry.invoke("remote_test", lambda: "must not run")
        self.assertEqual(registry.calls[0]["status"], "denied")
        self.assertEqual(
            registry.permission_audit[0],
            {
                "tool": "remote_test",
                "permission": "external_network",
                "decision": "deny",
                "reason": (
                    "Core inference must remain fully local; "
                    "external network access is denied."
                ),
            },
        )

    def test_manifest_is_framework_neutral(self) -> None:
        manifest = ToolRegistry().manifest()
        names = {tool["name"] for tool in manifest}
        self.assertTrue(
            {
                "vision_analyzer",
                "photography_planner",
                "plan_critic",
                "pose_analyzer",
                "pose_card_renderer",
            }.issubset(names)
        )


if __name__ == "__main__":
    unittest.main()
