from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NODE_TEST = ROOT / "tests" / "tokenfactory_open_todo_quality.test.mjs"


class TokenFactoryOpenTodoQualityNodeTests(unittest.TestCase):
    def test_node_quality_contract(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.fail("node is required to execute the Token Factory quality contract tests")

        completed = subprocess.run(
            [node, "--test", str(NODE_TEST)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        output = "\n".join(
            part for part in (completed.stdout, completed.stderr) if part
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"Node quality contract tests failed:\n{output}",
        )


if __name__ == "__main__":
    unittest.main()
