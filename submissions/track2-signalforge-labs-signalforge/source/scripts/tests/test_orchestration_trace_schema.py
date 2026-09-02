import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]


class OrchestrationTraceSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        schema = json.loads(
            (ROOT / "contracts" / "orchestration-trace.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(schema)
        self.validator = Draft202012Validator(schema)

    def trace(self, event_type: str) -> dict:
        return {
            "schema_version": "signalforge/orchestration-trace/v1",
            "run_id": "run-1",
            "request_id": "request-1",
            "events": [
                {
                    "sequence": 1,
                    "run_id": "run-1",
                    "step_id": "step-1",
                    "type": event_type,
                    "status": "completed",
                    "at": "2026-07-25T12:00:00Z",
                }
            ],
            "max_concurrent_context": 1,
            "started_at": "2026-07-25T12:00:00Z",
            "completed_at": "2026-07-25T12:00:01Z",
        }

    def test_schema_accepts_every_runtime_event_type(self) -> None:
        for event_type in (
            "interpretation",
            "planning",
            "plan",
            "wave",
            "context",
            "model",
            "retrieval",
            "tool",
            "review",
            "synthesis",
            "run",
            "retention",
            "workspace",
        ):
            with self.subTest(event_type=event_type):
                self.validator.validate(self.trace(event_type))

    def test_schema_rejects_unknown_event_type(self) -> None:
        with self.assertRaises(Exception):
            self.validator.validate(self.trace("private_model_payload"))


if __name__ == "__main__":
    unittest.main()
