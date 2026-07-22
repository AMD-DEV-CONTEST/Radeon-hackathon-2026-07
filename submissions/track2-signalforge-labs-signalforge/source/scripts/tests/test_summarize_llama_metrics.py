import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "summarize_llama_metrics.py"
SPEC = importlib.util.spec_from_file_location("llama_metrics", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class LlamaMetricsSummaryTests(unittest.TestCase):
    def test_computes_counter_deltas_and_throughput(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = root / "before.prom"
            after = root / "after.prom"
            before.write_text(
                "llamacpp:prompt_tokens_total 100\n"
                "llamacpp:prompt_seconds_total 2\n"
                "llamacpp:tokens_predicted_total 50\n"
                "llamacpp:tokens_predicted_seconds_total 1\n",
                encoding="utf-8",
            )
            after.write_text(
                "llamacpp:prompt_tokens_total 500\n"
                "llamacpp:prompt_seconds_total 4\n"
                "llamacpp:tokens_predicted_total 250\n"
                "llamacpp:tokens_predicted_seconds_total 5\n"
                "llamacpp:n_decode_total 25\n"
                "llamacpp:n_busy_slots_per_decode 2.5\n",
                encoding="utf-8",
            )
            result = MODULE.summarize(before, after)

        self.assertEqual(result["deltas"]["prompt_tokens"], 400)
        self.assertEqual(result["throughput"]["prompt_tokens_per_second"], 200)
        self.assertEqual(result["throughput"]["predicted_tokens_per_second"], 50)
        self.assertEqual(result["final_gauges"]["n_busy_slots_per_decode"], 2.5)


if __name__ == "__main__":
    unittest.main()
