import tempfile
import unittest
from pathlib import Path

from privateops.retrieval import DocumentStore


class DocumentStoreTests(unittest.TestCase):
    def test_competition_demo_has_matching_chinese_evidence(self):
        store = DocumentStore("data/knowledge")

        results = store.search("审计本项目的黑客松提交准备情况，并运行安全检查。")

        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0].source, "06-submission-workflow-zh.md")
        self.assertIn("本地", results[0].snippet)

    def test_real_knowledge_pack_routes_distinct_topics(self):
        store = DocumentStore("data/knowledge")
        cases = [
            ("为什么 AI 获得整台电脑查看权限后仍然不能随便修改？", "01-permission-contract-zh.md"),
            ("开机自启 Windows Defender 监听端口有哪些只读检查？", "03-windows-observation-zh.md"),
            ("same-instance loopback vLLM ROCm gfx1100", "04-radeon-rocm-runtime-en.md"),
            ("1511.072 32.427 measured benchmark integrity", "05-performance-evidence-en.md"),
            ("比赛提交准备 视频 Fork PR 哪些最后由用户完成？", "06-submission-workflow-zh.md"),
            ("模型端点失败时是否会静默降级到远程 API？", "07-failure-and-troubleshooting-zh.md"),
        ]

        for query, source in cases:
            with self.subTest(query=query):
                results = store.search(query)
                self.assertGreaterEqual(len(results), 1)
                self.assertEqual(results[0].source, source)

    def test_real_knowledge_pack_contains_fourteen_bilingual_sources(self):
        store = DocumentStore("data/knowledge")

        self.assertEqual(len(store.documents), 14)
        self.assertFalse(any("sample" in document.source for document in store.documents))

    def test_search_returns_ranked_evidence_snippets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "security.md").write_text(
                "PrivateOps keeps permission decisions visible. Risky file changes require confirmation.",
                encoding="utf-8",
            )
            (root / "rocm.md").write_text(
                "The final demo runs model inference on AMD Radeon GPU with ROCm in Radeon Cloud.",
                encoding="utf-8",
            )

            store = DocumentStore(root)
            results = store.search("AMD Radeon ROCm inference", limit=2)

            self.assertEqual(results[0].source, "rocm.md")
            self.assertGreater(results[0].score, 0)
            self.assertIn("AMD Radeon GPU", results[0].snippet)

    def test_evidence_id_is_stable_and_unsupported_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "notes.json").write_text('{"proof": "AMD ROCm"}', encoding="utf-8")
            (root / "archive.bin").write_bytes(b"AMD ROCm")

            first = DocumentStore(root).search("AMD ROCm")[0]
            second = DocumentStore(root).search("AMD ROCm")[0]

            self.assertEqual(first.evidence_id, second.evidence_id)
            self.assertTrue(first.evidence_id.startswith("ev-"))
            self.assertEqual(first.source, "notes.json")


if __name__ == "__main__":
    unittest.main()
