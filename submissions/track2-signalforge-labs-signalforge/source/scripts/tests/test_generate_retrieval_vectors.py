import importlib.util
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).parents[1] / "generate_retrieval_vectors.py"
SPEC = importlib.util.spec_from_file_location("generate_retrieval_vectors", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RetrievalMetricTests(unittest.TestCase):
    def test_metrics_distinguish_complete_and_partial_evidence(self):
        evaluation = {
            "questions": [
                {"question_id": "q1", "top_k": 2, "relevant_chunk_ids": ["a", "b"]},
                {"question_id": "q2", "top_k": 1, "relevant_chunk_ids": ["c"]},
            ]
        }
        chunks = {key: {"text": key * 8} for key in ("a", "b", "c", "d")}
        result = MODULE.metrics(evaluation, {"q1": ["a", "d"], "q2": ["c"]}, chunks)
        self.assertEqual(result["recall_at_k"], 0.75)
        self.assertEqual(result["complete_evidence_rate"], 0.5)
        self.assertEqual(result["citation_correctness"], 1.0)


if __name__ == "__main__":
    unittest.main()
