import json
from pathlib import Path
import tempfile
import unittest

from scripts.compact_expert_summary import compact_payload, sha256


class CompactExpertSummaryTests(unittest.TestCase):
    def test_preserves_episode_safety_summary_and_source_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "summary.json"
            payload = {
                "episodes": [
                    {
                        "episode_index": 7_000_000,
                        "result": {"success": False},
                        "terminal_stage": "approach",
                        "sample": {"profile_id": "large_narrow_carton"},
                        "safety_summary": {
                            "precontact_aabb_guard_filter_count": 6,
                        },
                        "trace": [{"frame": 0}],
                    }
                ]
            }
            source.write_text(json.dumps(payload), encoding="utf-8")
            source_hash = sha256(source)

            compact = compact_payload(payload, source)

        self.assertEqual(
            compact["episodes"][0]["safety_summary"][
                "precontact_aabb_guard_filter_count"
            ],
            6,
        )
        self.assertNotIn("trace", compact["episodes"][0])
        self.assertEqual(compact["source_summary"]["sha256"], source_hash)
        self.assertTrue(compact["source_summary"]["trace_omitted"])


if __name__ == "__main__":
    unittest.main()
