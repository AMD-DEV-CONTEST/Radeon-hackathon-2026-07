import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "fetch_artificial_analysis_models.py"
SPEC = importlib.util.spec_from_file_location("aa_models", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ArtificialAnalysisSnapshotTests(unittest.TestCase):
    def test_fetch_all_follows_pagination(self):
        def fake_fetcher(api_key, endpoint, page, prompt_type):
            self.assertEqual(api_key, "secret")
            self.assertEqual(endpoint, "/language/models")
            self.assertEqual(prompt_type, "long")
            return (
                {
                    "tier": "pro",
                    "intelligence_index_version": 4.1,
                    "pagination": {"has_more": page == 1},
                    "data": [{"slug": f"model-{page}"}],
                },
                {"remaining": str(500 - page)},
            )

        models, metadata, rate_limit = MODULE.fetch_all(
            "secret", "/language/models", "long", fake_fetcher
        )
        self.assertEqual([model["slug"] for model in models], ["model-1", "model-2"])
        self.assertEqual(metadata["intelligence_index_version"], 4.1)
        self.assertEqual(rate_limit["remaining"], "498")

    def test_snapshot_filters_slugs_and_preserves_attribution(self):
        snapshot = MODULE.build_snapshot(
            [{"slug": "qwen"}, {"slug": "gemma"}],
            {"tier": "pro", "intelligence_index_version": 4.1},
            {"remaining": "499"},
            "/language/models",
            "medium",
            ["qwen", "missing"],
        )
        self.assertTrue(snapshot["source"]["attribution_required"])
        self.assertEqual(snapshot["request"]["missing_slugs"], ["missing"])
        self.assertEqual(snapshot["models"], [{"slug": "qwen"}])


if __name__ == "__main__":
    unittest.main()
