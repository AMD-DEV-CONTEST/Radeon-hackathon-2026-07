from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_tokenfactory_corpus.py"
SPEC = importlib.util.spec_from_file_location(
    "validate_tokenfactory_corpus",
    SCRIPT,
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def episode(
    *,
    output: str = "Source-bound HOLD record with a named test and stop rule.",
) -> dict[str, object]:
    return {
        "schema": "ProofLaunchTokenFactoryTeacherEpisodeV1",
        "status": "passed",
        "stage": "architect",
        "quality_protocol": MODULE.QUALITY_PROTOCOL,
        "batch_id": "0001-0002",
        "todo_ids": ["0001", "0002"],
        "provider": MODULE.EXPECTED_PROVIDER,
        "evidence_class": MODULE.EXPECTED_EVIDENCE_CLASS,
        "competition_core_eligible": False,
        "hidden_reasoning_persisted": False,
        "credential": {"persisted": False, "redacted": True},
        "finish_reason": "stop",
        "quality_violations": [],
        "output": output,
        "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
    }


class TokenFactoryCorpusValidationTests(unittest.TestCase):
    def test_valid_episode_passes_fail_closed_contract(self) -> None:
        issues = MODULE.validate_episode(
            episode(),
            stage="architect",
            batch_id="0001-0002",
        )
        self.assertEqual(issues, [])

    def test_truncation_inferred_license_and_secret_are_blocking(self) -> None:
        payload = episode(output="License: MIT (inferred) rc-" + "a" * 24)
        payload["finish_reason"] = "length"
        payload["output_sha256"] = hashlib.sha256(
            str(payload["output"]).encode()
        ).hexdigest()
        codes = {
            item.code
            for item in MODULE.validate_episode(
                payload,
                stage="architect",
                batch_id="0001-0002",
            )
        }
        self.assertTrue(
            {"truncated_output", "inferred_license", "secret"}.issubset(codes)
        )

    def test_incomplete_corpus_can_be_audited_without_being_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "architect" / "0001-0002.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(episode()), encoding="utf-8")
            receipt = MODULE.validate_corpus(root, require_complete=False)
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["stage_valid_counts"]["architect"], 1)
        self.assertFalse(receipt["competition_core_eligible"])

    def test_synthesis_must_be_strict_complete_json_without_fake_closure(
        self,
    ) -> None:
        required = {
            "todo_id": "0001",
            "dependencies": [],
            "D": {},
            "A": {},
            "I": {},
            "E": {},
            "implementation_steps": [],
            "test_ids": [],
            "acceptance_metrics": [],
            "budget": {},
            "stop_rule": "stop",
            "rollback": "rollback",
            "evidence_class": "external_teacher_advisory",
            "radeon_action": "pending",
            "external_blockers": [],
            "current_status": "not_started",
        }
        second = dict(required, todo_id="0002")
        output = json.dumps({"records": [required, second]})
        payload = episode(output=output)
        payload["stage"] = "synthesis"
        self.assertEqual(
            MODULE.validate_episode(
                payload,
                stage="synthesis",
                batch_id="0001-0002",
            ),
            [],
        )
        payload["output"] = json.dumps(
            {
                "records": [
                    dict(required, current_status="passed"),
                    second,
                ]
            }
        )
        payload["output_sha256"] = hashlib.sha256(
            str(payload["output"]).encode()
        ).hexdigest()
        codes = {
            item.code
            for item in MODULE.validate_episode(
                payload,
                stage="synthesis",
                batch_id="0001-0002",
            )
        }
        self.assertIn("synthesis_invalid_status", codes)


if __name__ == "__main__":
    unittest.main()
