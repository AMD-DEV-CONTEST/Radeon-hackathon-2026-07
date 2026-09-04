from __future__ import annotations

import unittest

from app.evidence.errors import ModelResponseError
from app.evidence.fact_extractor import _validated_result
from app.evidence.model_client import ModelCall, strict_json


class FactExtractorTests(unittest.TestCase):
    def test_strict_json_accepts_fenced_object(self) -> None:
        self.assertEqual(strict_json("```json\n{\"ok\": true}\n```"), {"ok": True})

    def test_rejects_hallucinated_evidence_reference(self) -> None:
        call = ModelCall(
            content="{}",
            model="local-test",
            latency_seconds=0.1,
            usage={},
        )
        payload = {
            "observations": [
                {
                    "evidence_node_id": "NODE-HALLUCINATED",
                    "statement": "画面中可见汽车",
                    "subject": "汽车",
                    "predicate": "是否可见",
                    "value": "是",
                    "confidence": 0.8,
                    "uncertainty": "",
                }
            ],
            "timeline": [],
        }
        with self.assertRaises(ModelResponseError):
            _validated_result("CASE-1", payload, {"NODE-REAL"}, call)

    def test_caps_uncalibrated_model_confidence(self) -> None:
        call = ModelCall(
            content="{}",
            model="local-test",
            latency_seconds=0.1,
            usage={},
        )
        payload = {
            "observations": [
                {
                    "evidence_node_id": "NODE-REAL",
                    "statement": "画面中可见车辆",
                    "subject": "车辆",
                    "predicate": "是否可见",
                    "value": "是",
                    "confidence": 1.0,
                    "uncertainty": "",
                },
                {
                    "evidence_node_id": "NODE-REAL",
                    "statement": "车辆类型可能为轿车",
                    "subject": "车辆",
                    "predicate": "车辆类型",
                    "value": "轿车",
                    "confidence": 1.0,
                    "uncertainty": "画面为简化示意图",
                },
            ],
            "timeline": [],
        }
        result = _validated_result("CASE-1", payload, {"NODE-REAL"}, call)
        self.assertEqual(result.facts[0].confidence, 0.9)
        self.assertEqual(result.facts[1].confidence, 0.7)


if __name__ == "__main__":
    unittest.main()
