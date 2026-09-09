import tempfile
import unittest
from pathlib import Path

from privateops.langchain_tools import LangChainToolAdapter
from privateops.tools import ToolRegistry


class LangChainToolAdapterTests(unittest.TestCase):
    def test_structured_tool_invocation_uses_real_guarded_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "evidence.md").write_text("private evidence", encoding="utf-8")
            adapter = LangChainToolAdapter(ToolRegistry(workspace))

            result = adapter.invoke("workspace_inventory", {})

            self.assertEqual(adapter.framework_name, "LangChain Core")
            self.assertEqual(result.status, "completed")
            self.assertIn("evidence.md", result.output["sample"])

    def test_unknown_tool_preserves_registry_block_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = LangChainToolAdapter(ToolRegistry(tmp))

            result = adapter.invoke("unregistered_network_tool", {"url": "https://example.com"})

            self.assertEqual(result.status, "blocked")
            self.assertIn("Unknown tools", result.summary)


if __name__ == "__main__":
    unittest.main()
