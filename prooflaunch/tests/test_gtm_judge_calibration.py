from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_judge_calibration import (
    HUMAN_ATTESTATION,
    PRIVATE_NAME,
    PUBLIC_NAME,
    JudgeCalibrationAuthorizationError,
    JudgeCalibrationConflictError,
    JudgeCalibrationError,
    JudgeCalibrationService,
    calibration_review_digest,
    compile_judge_calibration_bundle,
)


TOKENS = {
    slot: f"judge-calibration-reviewer-token-{slot}-000000"
    for slot in range(1, 6)
}


def cases(*, positive_errors: int = 5, negative_errors: int = 5) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(100):
        gold = index < 50
        prediction = gold
        if gold and index < positive_errors:
            prediction = False
        if not gold and 50 <= index < 50 + negative_errors:
            prediction = True
        rows.append(
            {
                "case_id": f"case-{index:03d}",
                "artifact_sha256": hashlib.sha256(
                    f"distinct-artifact-{index}".encode("utf-8")
                ).hexdigest(),
                "evaluation_prompt": "Does this frozen artifact pass the named criterion?",
                "evidence_locator": f"fixture://judge-calibration/case-{index:03d}",
                "failure_slice": "strategy" if index % 2 == 0 else "execution",
                "judge_prediction": prediction,
            }
        )
    return rows


def human_gold(case_id: str) -> bool:
    return int(case_id.rsplit("-", 1)[-1]) < 50


def contains_key(value: object, forbidden: str) -> bool:
    if isinstance(value, dict):
        return forbidden in value or any(
            contains_key(item, forbidden) for item in value.values()
        )
    if isinstance(value, list):
        return any(contains_key(item, forbidden) for item in value)
    return False


def review_for(task: dict[str, object], *, label: bool | None = None) -> dict[str, object]:
    slot = int(task["reviewer_slot"])
    row: dict[str, object] = {
        "schema": "ProofLaunchJudgeCalibrationHumanLabelV1",
        "review_task_id": task["review_task_id"],
        "case_id": task["case_id"],
        "case_sha256": task["case_sha256"],
        "reviewer_slot": slot,
        "reviewer_pseudonym": f"named-human-slot-{slot}",
        "human_attestation": HUMAN_ATTESTATION,
        "human_label": human_gold(str(task["case_id"])) if label is None else label,
        "reason": "Independent blinded evaluation against the frozen binary rubric.",
        "reviewed_at": "2026-08-02T13:00:00+00:00",
        "review_content_sha256": None,
    }
    row["review_content_sha256"] = calibration_review_digest(row)
    return row


class JudgeCalibrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "calibration"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def compile(self, rows: list[dict[str, object]] | None = None) -> JudgeCalibrationService:
        receipt = compile_judge_calibration_bundle(
            rows or cases(),
            self.root,
            assignment_seed="test-only-sealed-assignment-seed-v1",
        )
        self.assertFalse(receipt["human_labels_present"])
        self.assertFalse(receipt["judge_calibrated"])
        return JudgeCalibrationService(self.root, reviewer_tokens=TOKENS)

    def test_compiler_requires_distinct_balanced_hundred_case_queue(self) -> None:
        with self.assertRaises(JudgeCalibrationError):
            compile_judge_calibration_bundle(
                cases()[:99],
                self.root,
                assignment_seed="test-only-sealed-assignment-seed-v1",
            )
        duplicate = cases()
        duplicate[1]["artifact_sha256"] = duplicate[0]["artifact_sha256"]
        with self.assertRaises(JudgeCalibrationError):
            compile_judge_calibration_bundle(
                duplicate,
                self.root,
                assignment_seed="test-only-sealed-assignment-seed-v1",
            )
        unbalanced = cases()
        for row in unbalanced[:61]:
            row["judge_prediction"] = True
        for row in unbalanced[61:]:
            row["judge_prediction"] = False
        with self.assertRaises(JudgeCalibrationError):
            compile_judge_calibration_bundle(
                unbalanced,
                self.root,
                assignment_seed="test-only-sealed-assignment-seed-v1",
            )

    def test_public_packet_is_blinded_and_private_mapping_is_owner_only(self) -> None:
        service = self.compile()
        public = json.loads((self.root / PUBLIC_NAME).read_text(encoding="utf-8"))
        private_text = (self.root / PRIVATE_NAME).read_text(encoding="utf-8")
        self.assertEqual(public["case_count"], 100)
        self.assertEqual(public["expected_review_count"], 300)
        self.assertEqual(len({item["artifact_sha256"] for item in public["cases"]}), 100)
        self.assertFalse(contains_key(public, "judge_prediction"))
        self.assertIn("judge_prediction", private_text)
        self.assertEqual((self.root / PRIVATE_NAME).stat().st_mode & 0o077, 0)
        self.assertFalse(service.status()["judge_calibrated"])

    def test_authorization_and_immutable_submission(self) -> None:
        service = self.compile()
        with self.assertRaises(JudgeCalibrationAuthorizationError):
            service.tasks_for_slot(1, reviewer_token="wrong-token")
        task = service.tasks_for_slot(1, reviewer_token=TOKENS[1])["tasks"][0]
        row = review_for(task)
        with self.assertRaises(JudgeCalibrationAuthorizationError):
            service.submit(row, reviewer_token=TOKENS[2])
        first = service.submit(row, reviewer_token=TOKENS[1])
        self.assertFalse(first["idempotent_replay"])
        replay = service.submit(row, reviewer_token=TOKENS[1])
        self.assertTrue(replay["idempotent_replay"])
        changed = dict(row)
        changed["human_label"] = not bool(row["human_label"])
        changed["review_content_sha256"] = calibration_review_digest(changed)
        with self.assertRaises(JudgeCalibrationConflictError):
            service.submit(changed, reviewer_token=TOKENS[1])

    def test_partial_queue_never_deblinds_or_aggregates(self) -> None:
        service = self.compile()
        task = service.tasks_for_slot(1, reviewer_token=TOKENS[1])["tasks"][0]
        self.assertFalse(contains_key(task, "judge_prediction"))
        service.submit(review_for(task), reviewer_token=TOKENS[1])
        status = service.status()
        self.assertEqual(status["submitted_review_count"], 1)
        self.assertFalse(status["review_complete"])
        self.assertIsNone(status["aggregate_content_sha256"])
        with self.assertRaises(JudgeCalibrationConflictError):
            service.aggregate()

    def test_reviewer_identity_drift_and_reuse_are_rejected(self) -> None:
        service = self.compile()
        task_one = service.tasks_for_slot(1, reviewer_token=TOKENS[1])["tasks"][0]
        service.submit(review_for(task_one), reviewer_token=TOKENS[1])
        task_two = service.tasks_for_slot(1, reviewer_token=TOKENS[1])["tasks"][0]
        drift = review_for(task_two)
        drift["reviewer_pseudonym"] = "different-human"
        drift["review_content_sha256"] = calibration_review_digest(drift)
        with self.assertRaises(JudgeCalibrationConflictError):
            service.submit(drift, reviewer_token=TOKENS[1])
        task_slot_two = service.tasks_for_slot(2, reviewer_token=TOKENS[2])["tasks"][0]
        reused = review_for(task_slot_two)
        reused["reviewer_pseudonym"] = "named-human-slot-1"
        reused["review_content_sha256"] = calibration_review_digest(reused)
        with self.assertRaises(JudgeCalibrationConflictError):
            service.submit(reused, reviewer_token=TOKENS[2])

    def test_complete_blind_queue_calibrates_only_above_strict_metric_gates(self) -> None:
        service = self.compile()
        for slot in range(1, 6):
            assignment = service.tasks_for_slot(slot, reviewer_token=TOKENS[slot])
            for task in assignment["tasks"]:
                service.submit(review_for(task), reviewer_token=TOKENS[slot])
        aggregate = service.aggregate()
        self.assertEqual(aggregate["human_labeled_case_count"], 100)
        self.assertEqual(aggregate["submitted_human_label_count"], 300)
        self.assertEqual(aggregate["distinct_reviewer_count"], 5)
        self.assertEqual(aggregate["true_positive_rate"], 0.9)
        self.assertEqual(aggregate["true_negative_rate"], 0.9)
        self.assertTrue(aggregate["reviewer_reliability_gate_passed"])
        self.assertTrue(aggregate["judge_calibrated"])
        self.assertFalse(aggregate["automatic_judge_promotion_enabled"])
        self.assertFalse(aggregate["judge_based_promotion_executed"])
        self.assertFalse(aggregate["external_publish_executed"])

    def test_exact_point_eight_tpr_is_not_calibrated(self) -> None:
        service = self.compile(cases(positive_errors=10, negative_errors=5))
        for slot in range(1, 6):
            assignment = service.tasks_for_slot(slot, reviewer_token=TOKENS[slot])
            for task in assignment["tasks"]:
                service.submit(review_for(task), reviewer_token=TOKENS[slot])
        aggregate = service.aggregate()
        self.assertEqual(aggregate["true_positive_rate"], 0.8)
        self.assertFalse(aggregate["judge_calibration_metric_gate_passed"])
        self.assertFalse(aggregate["judge_calibrated"])

    def test_manifest_and_persisted_review_tampering_fail_closed(self) -> None:
        service = self.compile()
        task = service.tasks_for_slot(1, reviewer_token=TOKENS[1])["tasks"][0]
        service.submit(review_for(task), reviewer_token=TOKENS[1])
        path = service.review_root / f"{task['review_task_id']}.json"
        tampered = json.loads(path.read_text(encoding="utf-8"))
        tampered["reason"] = "tampered after immutable submission"
        path.write_text(json.dumps(tampered), encoding="utf-8")
        with self.assertRaises(JudgeCalibrationError):
            service.status()

    def test_owner_resigned_malformed_private_mapping_still_fails_closed(self) -> None:
        compile_judge_calibration_bundle(
            cases(),
            self.root,
            assignment_seed="test-only-sealed-assignment-seed-v1",
        )
        path = self.root / PRIVATE_NAME
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["cases"][0]["judge_prediction"] = "true"
        unsigned = dict(payload)
        unsigned.pop("content_sha256")
        payload["content_sha256"] = hashlib.sha256(
            json.dumps(
                unsigned,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        path.write_text(json.dumps(payload), encoding="utf-8")
        path.chmod(0o600)
        with self.assertRaises(JudgeCalibrationError):
            JudgeCalibrationService(self.root, reviewer_tokens=TOKENS)


if __name__ == "__main__":
    unittest.main()
