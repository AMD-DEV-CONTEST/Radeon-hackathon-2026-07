import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from privateops.permissions import ConfirmationStore
from privateops.models import ToolResult
from privateops.tools import ToolRegistry


class ToolTests(unittest.TestCase):
    def test_system_tools_use_fixed_inspector_without_forwarding_prompt_arguments(self):
        class FakeInspector:
            def __init__(self):
                self.calls = []

            def collect(self, name):
                self.calls.append(name)
                return ToolResult(name, "completed", "Observed local state.", {"observed": True})

        with tempfile.TemporaryDirectory() as tmp:
            inspector = FakeInspector()
            tools = ToolRegistry(tmp, system_inspector=inspector)

            result = tools.execute("startup_inventory", {"command": "Remove-Item anything"})

            self.assertEqual(result.status, "completed")
            self.assertEqual(inspector.calls, ["startup_inventory"])
            self.assertEqual(result.output, {"observed": True})

    def test_inventory_and_search_are_confined_to_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "README.md").write_text("ROCm private audit", encoding="utf-8")
            outside = Path(tmp) / "secret.txt"
            outside.write_text("do not read", encoding="utf-8")
            tools = ToolRegistry(workspace)

            inventory = tools.execute("workspace_inventory", {})
            search = tools.execute("search_text", {"query": "ROCm"})

            self.assertEqual(inventory.status, "completed")
            self.assertEqual(inventory.output["total_files"], 1)
            self.assertEqual(inventory.output["sample"], ["README.md"])
            self.assertEqual(inventory.output["extensions"], {".md": 1})
            self.assertEqual(search.output["matches"][0]["path"], "README.md")
            self.assertNotIn("secret.txt", str(inventory.to_dict()))

    def test_inventory_excludes_environment_noise_and_reports_categories(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "src").mkdir()
            (workspace / "src" / "app.py").write_text("print('ok')", encoding="utf-8")
            (workspace / "README.md").write_text("PrivateOps", encoding="utf-8")
            for directory in [".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "build"]:
                path = workspace / directory
                path.mkdir()
                (path / "noise.txt").write_text("ignore", encoding="utf-8")
            state = workspace / "data" / "state"
            state.mkdir(parents=True)
            (state / "audit.jsonl").write_text("private state", encoding="utf-8")

            result = ToolRegistry(workspace).execute("workspace_inventory", {})

            self.assertEqual(result.output["total_files"], 2)
            self.assertEqual(result.output["sample"], ["README.md", "src/app.py"])
            self.assertEqual(result.output["extensions"], {".md": 1, ".py": 1})
            self.assertEqual(
                result.output["excluded_directories"],
                [".git", ".pytest_cache", ".venv", "__pycache__", "build", "data/state", "dist", "node_modules", "venv"],
            )
            self.assertNotIn("noise.txt", str(result.output))
            self.assertNotIn("audit.jsonl", str(result.output))

    def test_command_tool_rejects_shell_metacharacters(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = ToolRegistry(tmp)

            result = tools.execute("run_tests", {"command": "python -m unittest; whoami"})

            self.assertEqual(result.status, "blocked")
            self.assertIn("allow-listed", result.summary)

    def test_confirmation_token_is_exact_and_one_use(self):
        now = datetime(2026, 8, 2, tzinfo=timezone.utc)
        store = ConfirmationStore(clock=lambda: now, ttl_seconds=60)
        confirmation = store.issue("run_tests:python -m unittest discover -s tests")

        self.assertFalse(store.consume(confirmation.token, "different-action"))
        self.assertTrue(store.consume(confirmation.token, confirmation.action))
        self.assertFalse(store.consume(confirmation.token, confirmation.action))

    def test_expired_confirmation_token_is_rejected(self):
        moments = [
            datetime(2026, 8, 2, tzinfo=timezone.utc),
            datetime(2026, 8, 2, tzinfo=timezone.utc) + timedelta(seconds=61),
        ]
        store = ConfirmationStore(clock=lambda: moments.pop(0), ttl_seconds=60)
        confirmation = store.issue("action")

        self.assertFalse(store.consume(confirmation.token, "action"))


if __name__ == "__main__":
    unittest.main()
