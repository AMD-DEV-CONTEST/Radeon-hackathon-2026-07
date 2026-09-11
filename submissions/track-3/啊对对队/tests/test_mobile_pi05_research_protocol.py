import json
from pathlib import Path
import unittest

from parcel_sorter.mobile_pi05_contract import PI05_GRASP_MODES
from parcel_sorter.mobile_pi05_research_protocol import (
    ACTION_THRESHOLD_FIELDS,
    PI05_ACTION_THRESHOLDS_PROTOCOL,
    PI05_DEVELOPMENT_ROLE,
    PI05_TASK_STAGES,
    PI05_TINY_OVERFIT_GATE_PROTOCOL,
    PI05_TINY_OVERFIT_ROLE,
    build_stage_panel,
    build_training_launch_audit,
    canonical_payload_sha256,
    validate_action_thresholds,
    validate_stage_panel,
    validate_tiny_overfit_gate,
)


DIGEST = "a" * 64


def _observations(*, independent_sources: int = 1) -> list[dict]:
    rows = []
    index = 0
    for mode_index, mode in enumerate(PI05_GRASP_MODES):
        for stage_index, stage in enumerate(PI05_TASK_STAGES):
            rows.append(
                {
                    "observation_id": f"observation-{index}",
                    "dataset_index": index,
                    "episode_index": mode_index * 10 + stage_index,
                    "source_identity": f"source-{stage_index % independent_sources}",
                    "grasp_mode": mode,
                    "stage": stage,
                    "action_label_available": True,
                }
            )
            index += 1
    return rows


def _thresholds(*, role: str) -> dict:
    values = {
        "median_position_m": 0.005,
        "maximum_position_m": 0.010,
        "median_orientation_rad": 0.10,
        "maximum_orientation_rad": 0.20,
        "median_base_velocity": 0.02,
        "maximum_base_velocity": 0.04,
        "median_progress_error": 0.05,
        "minimum_tool_accuracy": 1.0,
    }
    payload = {
        "schema_version": 1,
        "protocol": PI05_ACTION_THRESHOLDS_PROTOCOL,
        "status": "contract_test" if role == PI05_TINY_OVERFIT_ROLE else "calibrated",
        "deployment_calibrated": role == PI05_DEVELOPMENT_ROLE,
        "calibration_evidence": (
            {
                "independent_successful_trajectories": 2,
                "source_summary_sha256": ["b" * 64, "c" * 64],
            }
            if role == PI05_DEVELOPMENT_ROLE
            else None
        ),
        "by_stage": {stage: dict(values) for stage in PI05_TASK_STAGES},
    }
    payload["thresholds_sha256"] = canonical_payload_sha256(
        payload, hash_field="thresholds_sha256"
    )
    return payload


def _tiny_gate() -> dict:
    payload = {
        "schema_version": 1,
        "protocol": PI05_TINY_OVERFIT_GATE_PROTOCOL,
        "status": "passed",
        "panel_role": PI05_TINY_OVERFIT_ROLE,
        "action_contract": "absolute_v1",
        "routing_error_count": 0,
        "action_fidelity_error_count": 0,
        "structural_error_count": 0,
        "mode_stage_cells": 18,
        "panel_sha256": "b" * 64,
        "thresholds_sha256": "c" * 64,
        "checkpoint_sha256": "d" * 64,
        "training_contract_sha256": "e" * 64,
        "dataset_manifest_sha256": DIGEST,
        "screen_sha256": "f" * 64,
    }
    payload["gate_sha256"] = canonical_payload_sha256(
        payload, hash_field="gate_sha256"
    )
    return payload


class MobilePI05ResearchProtocolTests(unittest.TestCase):
    def test_legacy_b0_does_not_infer_missing_action_evidence_as_zero(self) -> None:
        path = (
            Path(__file__).parents[1]
            / "evidence/pi05_b3_swm_v1/RESULTS.json"
        )
        screen = json.loads(path.read_text(encoding="utf-8"))["original_b0"][
            "offline_screen_12k"
        ]

        self.assertIsNone(screen["action_fidelity_error_count"])
        self.assertIn("not_evaluated", screen["status"])

    def test_screen_script_has_no_hand_picked_dataset_indices(self) -> None:
        path = Path(__file__).parents[1] / "scripts/screen_mobile_pi05_checkpoints_rocm.sh"
        text = path.read_text(encoding="utf-8")

        self.assertNotIn("--index", text)
        self.assertIn("--panel", text)
        self.assertIn("--thresholds", text)

    def test_high_noise_diagnostics_cannot_restore_the_six_training_indices(self) -> None:
        root = Path(__file__).parents[1]
        probe = (root / "scripts/probe_mobile_pi05_high_noise_mode_rocm.py").read_text(
            encoding="utf-8"
        )
        postscreen = (root / "scripts/postscreen_mobile_pi05_training_rocm.sh").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("--index", probe)
        self.assertIn("--panel", probe)
        self.assertIn('--panel "${STAGE_PANEL}"', postscreen)
        for index in (0, 644, 1286, 3636, 4699, 5285):
            self.assertNotIn(f"--index {index}", postscreen)

    def test_candidate_training_cannot_skip_gate_or_scheduler_contract(self) -> None:
        path = Path(__file__).parents[1] / "scripts/train_mobile_pi05_rocm.sh"
        text = path.read_text(encoding="utf-8")

        self.assertIn("MOBILE_PI05_TRAINING_ROLE", text)
        self.assertIn("candidate training requires MOBILE_PI05_TINY_OVERFIT_GATE", text)
        self.assertIn('--policy.scheduler_decay_steps "${SCHEDULER_DECAY_STEPS}"', text)
        self.assertIn('--policy.scheduler_warmup_steps "${SCHEDULER_WARMUP_STEPS}"', text)
        self.assertNotIn("--scheduler.num_decay_steps", text)
        self.assertNotIn("--scheduler.num_warmup_steps", text)
        self.assertNotIn('MOBILE_PI05_ALLOW_ZERO_SEED:-0}" "${WRIST_RGBD}', text)

    def test_checked_in_tiny_thresholds_are_fingerprinted_contract_only(self) -> None:
        path = (
            Path(__file__).parents[1]
            / "configs/mobile_pi05_tiny_overfit_action_thresholds_v1.json"
        )
        thresholds = json.loads(path.read_text(encoding="utf-8"))

        audit = validate_action_thresholds(
            thresholds, panel_role=PI05_TINY_OVERFIT_ROLE
        )

        self.assertEqual(audit["status"], "passed")
        self.assertFalse(audit["deployment_calibrated"])

    def test_builds_stage_complete_tiny_overfit_panel(self) -> None:
        panel = build_stage_panel(
            _observations(),
            role=PI05_TINY_OVERFIT_ROLE,
            dataset_root="dataset",
            dataset_manifest_sha256=DIGEST,
            minimum_observations_per_mode_stage=1,
            minimum_independent_sources_per_mode=1,
        )

        audit = validate_stage_panel(panel, expected_role=PI05_TINY_OVERFIT_ROLE)

        self.assertEqual(audit["mode_stage_cells"], 18)
        self.assertEqual(audit["observations"], 18)

    def test_development_panel_requires_independent_nontraining_sources(self) -> None:
        with self.assertRaisesRegex(ValueError, "overlaps training"):
            build_stage_panel(
                _observations(independent_sources=2),
                role=PI05_DEVELOPMENT_ROLE,
                dataset_root="dataset",
                dataset_manifest_sha256=DIGEST,
                minimum_observations_per_mode_stage=1,
                minimum_independent_sources_per_mode=2,
                training_source_identities={"source-0"},
            )

    def test_panel_rejects_missing_action_label(self) -> None:
        observations = _observations()
        observations[0]["action_label_available"] = False
        with self.assertRaisesRegex(ValueError, "action labels"):
            build_stage_panel(
                observations,
                role=PI05_TINY_OVERFIT_ROLE,
                dataset_root="dataset",
                dataset_manifest_sha256=DIGEST,
                minimum_observations_per_mode_stage=1,
                minimum_independent_sources_per_mode=1,
            )

    def test_development_thresholds_require_contact_calibration(self) -> None:
        thresholds = _thresholds(role=PI05_DEVELOPMENT_ROLE)
        thresholds["calibration_evidence"]["independent_successful_trajectories"] = 1
        thresholds["thresholds_sha256"] = canonical_payload_sha256(
            thresholds, hash_field="thresholds_sha256"
        )

        with self.assertRaisesRegex(ValueError, "lacks independent"):
            validate_action_thresholds(
                thresholds, panel_role=PI05_DEVELOPMENT_ROLE
            )

    def test_threshold_profiles_have_exact_fields(self) -> None:
        thresholds = _thresholds(role=PI05_TINY_OVERFIT_ROLE)
        del thresholds["by_stage"]["lift"][ACTION_THRESHOLD_FIELDS[0]]
        thresholds["thresholds_sha256"] = canonical_payload_sha256(
            thresholds, hash_field="thresholds_sha256"
        )
        with self.assertRaisesRegex(ValueError, "incomplete"):
            validate_action_thresholds(
                thresholds, panel_role=PI05_TINY_OVERFIT_ROLE
            )

    def test_candidate_launch_requires_tiny_gate_and_two_sources_per_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires a passed"):
            build_training_launch_audit(
                training_role="candidate",
                action_contract="absolute_v1",
                dataset_manifest_sha256=DIGEST,
                requested_training_steps=12000,
                scheduler_warmup_steps=1000,
                scheduler_decay_steps=12000,
                independent_source_counts={mode: 2 for mode in PI05_GRASP_MODES},
            )
        with self.assertRaisesRegex(ValueError, "lacks independent sources"):
            build_training_launch_audit(
                training_role="candidate",
                action_contract="absolute_v1",
                dataset_manifest_sha256=DIGEST,
                requested_training_steps=12000,
                scheduler_warmup_steps=1000,
                scheduler_decay_steps=12000,
                tiny_overfit_gate=_tiny_gate(),
                independent_source_counts={mode: 1 for mode in PI05_GRASP_MODES},
            )

    def test_tiny_gate_rejects_missing_evidence_as_failure(self) -> None:
        gate = _tiny_gate()
        gate["action_fidelity_error_count"] = None
        gate["gate_sha256"] = canonical_payload_sha256(
            gate, hash_field="gate_sha256"
        )
        with self.assertRaisesRegex(ValueError, "action_fidelity_error_count"):
            validate_tiny_overfit_gate(gate, action_contract="absolute_v1")


if __name__ == "__main__":
    unittest.main()
