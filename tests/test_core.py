import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import (
    LocalMemory,
    ModelResult,
    RequirementGuardian,
    chunk_text,
    extract_json_object,
    search_chunks,
    tokenize,
)


class FakeLLM:
    model = "local-test-model"

    def __init__(self):
        self.calls = 0

    def chat(self, system, user, max_tokens=700):
        self.calls += 1
        responses = [
            '{"goal":"Audit submission","steps":["search","write","verify"],"search_queries":["video English","Radeon ROCm"]}',
            "# Executive Summary\nReady.\n## Mandatory Requirements\n- [ ] English materials [Evidence 1]\n## Deliverables Checklist\n- [ ] Demo video [Evidence 1]\n## Execution Plan\n1. Submit\n## Risks and Missing Information\nNone.\n## Evidence Used\n[Evidence 1]",
            '{"status":"PASS","coverage_score":100,"missing_items":[],"unsupported_claims":[]}',
        ]
        return ModelResult(responses[self.calls - 1], 0.1, 20, 10)


class CoreTests(unittest.TestCase):
    def test_tokenize_supports_english_and_numbers(self):
        tokens = tokenize("Track 2 requires English files")
        self.assertTrue({"track", "2", "requires", "english", "files"} <= tokens)

    def test_chunk_and_search_returns_relevant_evidence(self):
        text = (
            "The demo video must be three to five minutes.\n\n"
            "All materials must be written in English.\n\n"
            "The model runs on AMD Radeon using ROCm."
        )
        chunks = chunk_text(text, max_chars=55)
        hits = search_chunks(chunks, "English materials", top_k=1)
        self.assertEqual(len(hits), 1)
        self.assertIn("English", hits[0]["text"])

    def test_extract_json_ignores_reasoning_wrapper(self):
        parsed = extract_json_object('<think>hidden</think> text {"status":"PASS"}')
        self.assertEqual(parsed, {"status": "PASS"})

    def test_sqlite_memory_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = LocalMemory(Path(directory) / "memory.db")
            memory.save("Prepare hackathon submission", "Video and PDF are required")
            recalled = memory.recall("hackathon video")
            self.assertEqual(len(recalled), 1)
            self.assertIn("Video and PDF", recalled[0])
            memory.close()

    def test_complete_agent_loop_with_local_fake_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "requirements.txt"
            document.write_text(
                "All materials must be in English. A demo video is required. "
                "Inference must run on Radeon with ROCm.",
                encoding="utf-8",
            )
            memory = LocalMemory(root / "memory.db")
            fake = FakeLLM()
            with patch("agent.OUTPUT_DIR", root / "output"):
                result = RequirementGuardian(llm=fake, memory=memory).run(
                    str(document), "Audit the submission"
                )
            trace = json.loads(result["trace"])
            self.assertEqual(fake.calls, 3)
            self.assertIn("English materials", result["report"])
            self.assertTrue(any(item.get("tool") == "search_document" for item in trace))
            self.assertTrue((root / "output" / "latest_report.md").exists())
            memory.close()


if __name__ == "__main__":
    unittest.main()
