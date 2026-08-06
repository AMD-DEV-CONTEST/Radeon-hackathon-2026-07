from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_four_a_transfer_corpus.py"
SPEC = importlib.util.spec_from_file_location(
    "validate_four_a_transfer_corpus",
    SCRIPT,
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def synthesis_episode(
    *,
    reference_case_ids: list[str] | None = None,
) -> dict[str, object]:
    records = []
    for todo_id in ("0001", "0002"):
        records.append(
            {
                "todo_id": todo_id,
                "reference_case_ids": reference_case_ids or [],
                "observed_evidence": "Source-bound observation or no fit.",
                "strategic_transfer": "Decision grammar only.",
                "creative_mechanism": "Testable mechanism.",
                "channel_and_craft": "Blind comparison.",
                "effectiveness_test": "Pre-registered test.",
                "negative_control": "Placebo creative.",
                "what_not_to_copy": "No identity, copy, layout, footage, or offer.",
                "rights_partition": "research_reference",
                "admission_status": "research_only",
            }
        )
    output = json.dumps({"records": records}, separators=(",", ":"))
    return {
        "schema": MODULE.EXPECTED_SCHEMA,
        "status": "passed",
        "stage": "four_a_deep_synthesis",
        "quality_protocol": MODULE.EXPECTED_PROTOCOL,
        "batch_id": "0001-0002",
        "todo_ids": ["0001", "0002"],
        "provider": MODULE.EXPECTED_PROVIDER,
        "four_a_context_sha256": "a" * 64,
        "evidence_class": MODULE.EXPECTED_EVIDENCE_CLASS,
        "competition_core_eligible": False,
        "hidden_reasoning_persisted": False,
        "credential": {"persisted": False, "redacted": True},
        "finish_reason": "stop",
        "quality_violations": [],
        "output": output,
        "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
    }


class FourATransferCorpusValidationTests(unittest.TestCase):
    def test_valid_synthesis_episode_passes(self) -> None:
        self.assertEqual(
            MODULE.validate_episode(
                synthesis_episode(reference_case_ids=["os26-ce002g"]),
                stage="four_a_deep_synthesis",
                batch_id="0001-0002",
            ),
            [],
        )

    def test_unbound_reference_and_partition_change_are_blocking(self) -> None:
        payload = synthesis_episode(reference_case_ids=["invented-case"])
        document = json.loads(str(payload["output"]))
        document["records"][0]["rights_partition"] = "training_candidate"
        output = json.dumps(document, separators=(",", ":"))
        payload["output"] = output
        payload["output_sha256"] = hashlib.sha256(output.encode()).hexdigest()
        codes = {
            item.code
            for item in MODULE.validate_episode(
                payload,
                stage="four_a_deep_synthesis",
                batch_id="0001-0002",
            )
        }
        self.assertIn("synthesis_reference_ids", codes)
        self.assertIn("synthesis_rights_partition", codes)

    def test_incomplete_audit_reports_counts_without_claiming_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "four_a_deep_synthesis" / "0001-0002.json"
            target.parent.mkdir(parents=True)
            target.write_text(
                json.dumps(synthesis_episode()),
                encoding="utf-8",
            )
            receipt = MODULE.validate_corpus(root, require_complete=False)
        self.assertTrue(receipt["status"] in {"passed", "blocked"})
        self.assertFalse(receipt["complete"])
        self.assertFalse(receipt["competition_core_eligible"])


if __name__ == "__main__":
    unittest.main()
