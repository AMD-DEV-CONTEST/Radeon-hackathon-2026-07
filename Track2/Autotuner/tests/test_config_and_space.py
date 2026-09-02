import unittest
import json
from importlib import resources
from pathlib import Path

from autotuner.config import load_config
from autotuner.space import build_candidates


ROOT = Path(__file__).resolve().parents[1]


class ConfigAndSpaceTests(unittest.TestCase):
    def test_packaged_demo_matches_reviewable_demo(self) -> None:
        source = json.loads((ROOT / "configs" / "demo.json").read_text())
        packaged = json.loads(
            resources.files("autotuner.data")
            .joinpath("demo.json")
            .read_text()
        )
        self.assertEqual(source, packaged)

    def test_demo_configuration_builds_unique_candidates(self) -> None:
        config = load_config(ROOT / "configs" / "demo.json")
        candidates = build_candidates(config)
        keys = {candidate.key() for candidate in candidates}
        self.assertEqual(len(candidates), len(keys))
        self.assertGreaterEqual(len(candidates), config.trials)

    def test_speculative_pairs_are_valid(self) -> None:
        config = load_config(ROOT / "configs" / "demo.json")
        for candidate in build_candidates(config):
            self.assertEqual(
                bool(candidate.speculative_model),
                candidate.num_speculative_tokens > 0,
            )

    def test_baseline_uses_first_value_in_each_dimension(self) -> None:
        config = load_config(ROOT / "configs" / "demo.json")
        baseline = build_candidates(config)[0]
        self.assertEqual(baseline.attention_backend, "auto")
        self.assertEqual(baseline.kv_cache_dtype, "auto")
        self.assertEqual(baseline.max_num_seqs, 4)


if __name__ == "__main__":
    unittest.main()
