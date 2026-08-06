"""Grok Build 代码引擎模块的确定性测试（无网络，stdlib unittest，零外部依赖）。"""

from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.grok_build_engine import (  # noqa: E402
    default_engine,
    StubGitTool,
    StubRefactorTool,
    StubRepoParser,
    StubTerminalTool,
    StubTestGenTool,
    StubVulnScanner,
)


class GrokBuildEngineTest(unittest.TestCase):
    """Stub 工具链与 CodeEngine 的行为契约。"""

    def setUp(self):
        self._tmpdirs: list[str] = []

    def tearDown(self):
        for d in self._tmpdirs:
            shutil.rmtree(d, ignore_errors=True)

    # ---- helpers ----

    def _mkdtemp(self, prefix: str) -> str:
        d = tempfile.mkdtemp(prefix=prefix)
        self._tmpdirs.append(d)
        return d

    def _make_temp_tree(self) -> str:
        root = self._mkdtemp("grok_test_tree_")
        p = pathlib.Path(root)
        (p / "a.py").write_text("print('hi')\n", encoding="utf-8")
        (p / "sub").mkdir()
        (p / "sub" / "b.txt").write_text("hello world\n", encoding="utf-8")
        (p / "sub" / "c.md").write_text("# title\n", encoding="utf-8")
        (p / "d.json").write_text("{}", encoding="utf-8")
        return root

    # ---- tests ----

    def test_repo_parser_counts_files(self):
        res = StubRepoParser().scan(self._make_temp_tree())
        self.assertEqual(res["files"], 4)
        self.assertEqual(res["languages"][".py"], 1)
        self.assertEqual(res["languages"][".json"], 1)
        self.assertEqual(len(res["tree_sample"]), 4)

    def test_vuln_scanner_flags_dangerous_calls(self):
        root = self._mkdtemp("grok_vuln_")
        (pathlib.Path(root) / "bad.py").write_text(
            "x = eval('1')\ny = os.system('ls')\nz = 1\n", encoding="utf-8"
        )
        res = StubVulnScanner().scan(root)
        self.assertTrue(res.ok)
        self.assertEqual(res.data["count"], 2)
        patterns = {f["pattern"] for f in res.data["findings"]}
        self.assertIn("eval(", patterns)
        self.assertIn("os.system(", patterns)

    def test_refactor_dry_run_counts_without_modifying(self):
        root = self._make_temp_tree()
        target = pathlib.Path(root) / "sub" / "b.txt"
        orig = target.read_text()
        res = StubRefactorTool().refactor(root, "hello", "goodbye", dry_run=True)
        self.assertEqual(res.data["matches"], 1)
        self.assertFalse(res.data["modified"])
        self.assertEqual(target.read_text(), orig, "dry_run 不得改动磁盘")

    def test_git_commit_dry_run_returns_planned_command(self):
        res = StubGitTool().commit("/repo/x", "wip", dry_run=True)
        self.assertTrue(res.ok)
        self.assertIn("commit -m", res.data["planned_cmd"])
        self.assertIn("/repo/x", res.data["planned_cmd"])

    def test_terminal_dry_run_returns_planned_cmd(self):
        res = StubTerminalTool().run("ls -la", cwd="/tmp", dry_run=True)
        self.assertEqual(res.data["planned_cmd"], "ls -la")
        self.assertEqual(res.data["cwd"], "/tmp")

    def test_gen_tests_returns_plan(self):
        res = StubTestGenTool().gen("module.py")
        self.assertEqual(res.data["target"], "module.py")
        self.assertEqual(
            res.data["cases"], ["test_init", "test_happy_path", "test_edge_case"]
        )

    def test_engine_analyze_integrates_parser_and_scanner(self):
        root = self._mkdtemp("grok_analyze_")
        (pathlib.Path(root) / "v.py").write_text("exec('pass')\n", encoding="utf-8")
        (pathlib.Path(root) / "ok.py").write_text("x = 1\n", encoding="utf-8")
        out = default_engine().analyze(root)
        self.assertEqual(out["files"], 2)
        self.assertEqual(out["vuln_count"], 1)
        self.assertEqual(out["vuln_findings"][0]["pattern"], "exec(")

    def test_default_engine_methods_routable(self):
        engine = default_engine()
        self.assertTrue(engine.git_commit("r", "msg").ok)
        self.assertTrue(engine.run_terminal("pwd").ok)
        self.assertTrue(engine.gen_tests("f.py").ok)


if __name__ == "__main__":
    unittest.main()
