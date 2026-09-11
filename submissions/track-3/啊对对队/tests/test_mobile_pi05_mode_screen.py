import importlib.util
from pathlib import Path
import unittest

from parcel_sorter.mobile_pi05_contract import PI05_GRASP_MODES
from parcel_sorter.mobile_pi05_research_protocol import (
    PI05_ACTION_THRESHOLDS_PROTOCOL,
    PI05_DEVELOPMENT_ROLE,
    PI05_TASK_STAGES,
    build_stage_panel,
    canonical_payload_sha256,
)


SCRIPT = Path(__file__).parents[1] / "scripts" / "summarize_mobile_pi05_mode_screen.py"
SPEC = importlib.util.spec_from_file_location("summarize_mobile_pi05_mode_screen", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _design() -> dict:
    observations = []
    index = 0
    for mode in PI05_GRASP_MODES:
        for stage_index, stage in enumerate(PI05_TASK_STAGES):
            observations.append(
                {
                    "observation_id": f"observation-{index}",
                    "dataset_index": index,
                    "episode_index": index,
                    "source_identity": f"heldout-{stage_index % 2}",
                    "grasp_mode": mode,
                    "stage": stage,
                    "action_label_available": True,
                }
            )
            index += 1
    return build_stage_panel(
        observations,
        role=PI05_DEVELOPMENT_ROLE,
        dataset_root="/dataset",
        dataset_manifest_sha256="a" * 64,
        minimum_observations_per_mode_stage=1,
        minimum_independent_sources_per_mode=2,
        training_source_identities={"training-a", "training-b"},
    )


def _thresholds() -> dict:
    values = {
        "median_position_m": 0.01,
        "maximum_position_m": 0.02,
        "median_orientation_rad": 0.20,
        "maximum_orientation_rad": 0.30,
        "median_base_velocity": 0.02,
        "maximum_base_velocity": 0.04,
        "median_progress_error": 0.10,
        "minimum_tool_accuracy": 1.0,
    }
    payload = {
        "protocol": PI05_ACTION_THRESHOLDS_PROTOCOL,
        "status": "calibrated",
        "deployment_calibrated": True,
        "calibration_evidence": {
            "independent_successful_trajectories": 2,
            "source_summary_sha256": ["b" * 64, "c" * 64],
        },
        "by_stage": {stage: dict(values) for stage in PI05_TASK_STAGES},
    }
    payload["thresholds_sha256"] = canonical_payload_sha256(
        payload, hash_field="thresholds_sha256"
    )
    return payload


def _probes(design: dict) -> list[dict]:
    result = []
    for item in design["observations"]:
        mode = item["grasp_mode"]
        result.append(
            {
                "checkpoint": "/checkpoint",
                "dataset": design["dataset_root"],
                "dataset_manifest_sha256": design["dataset_manifest_sha256"],
                "stage_panel_sha256": design["panel_sha256"],
                "observation_panel_role": design["role"],
                "observation_id": item["observation_id"],
                "dataset_index": item["dataset_index"],
                "episode_index": item["episode_index"],
                "source_identity": item["source_identity"],
                "stage": item["stage"],
                "expected_grasp_mode": mode,
                "predicted_grasp_mode": mode,
                "grasp_mode_conditioned": False,
                "sample_count": 3,
                "sample_seeds": [20260727, 20260728, 20260729],
                "sampling_seed_protocol": "common-random-numbers-per-observation-v1",
                "grasp_mode_correct": True,
                "finite": True,
                "material_action": True,
                "fallback_to_expert": False,
                "expert_reference_used": False,
                "pure_vla_qualified": True,
                "selected_scale_min": 1.0,
                "policy_type": "pi05",
                "action_contract": "pi05_absolute_v1",
                "action_fidelity": {
                    "finite": True,
                    "median_maximum_arm_position_l2_m": 0.005,
                    "maximum_maximum_arm_position_l2_m": 0.010,
                    "median_maximum_arm_orientation_error_rad": 0.10,
                    "maximum_maximum_arm_orientation_error_rad": 0.20,
                    "median_base_velocity_l2": 0.01,
                    "maximum_base_velocity_l2": 0.02,
                    "median_progress_absolute_error": 0.05,
                    "left_tool_accuracy": 1.0,
                    "right_tool_accuracy": 1.0,
                },
            }
        )
    return result


class MobilePI05ModeScreenTests(unittest.TestCase):
    def test_passes_complete_stage_action_screen(self) -> None:
        design = _design()
        summary = MODULE.summarize_mode_screen(
            _probes(design), design=design, thresholds=_thresholds()
        )

        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["metrics"]["probes"], 18)
        self.assertEqual(summary["mode_stage_cells"], 18)
        self.assertEqual(summary["action_fidelity_error_count"], 0)

    def test_stage_specific_action_failure_is_not_a_route_pass(self) -> None:
        design = _design()
        probes = _probes(design)
        lift = next(probe for probe in probes if probe["stage"] == "lift")
        lift["action_fidelity"]["median_maximum_arm_position_l2_m"] = 0.5

        summary = MODULE.summarize_mode_screen(
            probes, design=design, thresholds=_thresholds()
        )

        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["routing_error_count"], 0)
        self.assertEqual(summary["action_fidelity_error_count"], 1)

    def test_missing_action_evidence_fails_closed(self) -> None:
        design = _design()
        probes = _probes(design)
        probes[0].pop("action_fidelity")

        summary = MODULE.summarize_mode_screen(
            probes, design=design, thresholds=_thresholds()
        )

        self.assertIn("action_fidelity_available", summary["action_fidelity_errors"][0])

    def test_rejects_probe_not_in_frozen_panel(self) -> None:
        design = _design()
        probes = _probes(design)
        probes[0]["observation_id"] = "hand-picked-index"

        with self.assertRaisesRegex(ValueError, "does not match frozen design"):
            MODULE.summarize_mode_screen(
                probes, design=design, thresholds=_thresholds()
            )


if __name__ == "__main__":
    unittest.main()
