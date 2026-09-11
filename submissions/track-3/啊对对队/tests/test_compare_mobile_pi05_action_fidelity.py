import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "compare_mobile_pi05_action_fidelity.py"
)
SPEC = importlib.util.spec_from_file_location(
    "compare_mobile_pi05_action_fidelity", SCRIPT
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _screen(
    path: Path,
    contract: str,
    errors: list[tuple[float, float]],
    *,
    step: int | None = None,
    status: str = "passed",
) -> Path:
    modes = ("top_suction", "side_suction", "cooperative_cradle")
    checkpoint_step = step or (
        3000 if contract == MODULE.CANDIDATE_CONTRACT else 12000
    )
    payload = {
        "protocol": MODULE.SCREEN_PROTOCOL,
        "status": status,
        "checkpoint": f"/run/checkpoints/{checkpoint_step:06d}/pretrained_model",
        "action_contract": contract,
        "observation_panel_role": MODULE.PANEL_ROLE,
        "sample_seeds": [20260727, 20260728, 20260729],
        "sampling_seed_protocol": "common-random-numbers-per-observation-v1",
        "modes": [],
    }
    for index, (position, orientation) in enumerate(errors):
        payload["modes"].append(
            {
                "expected_mode": modes[index // 2],
                "dataset_index": index * 100,
                "stage": "pregrasp",
                "observable_object_context": {
                    "shape": "box",
                    "size_m": [0.1, 0.1, 0.1],
                    "mass_kg": 0.2,
                },
                "action_fidelity": {
                    "finite": True,
                    "median_maximum_arm_position_l2_m": position,
                    "median_maximum_arm_orientation_error_rad": orientation,
                },
            }
        )
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _stage_weighted_config(
    path: Path, control: Path, checkpoint_steps: list[int]
) -> Path:
    payload = {
        "frozen_before_candidate_training": True,
        "candidate": MODULE.STAGE_WEIGHTED_CANDIDATE,
        "isolated_factor": {
            "name": MODULE.STAGE_WEIGHTING_FACTOR,
            "treatment": [2.0, 2.0, 1.2, 0.4, 0.6, 0.4],
            "scope": MODULE.STAGE_WEIGHTING_SCOPE,
        },
        "control": {
            "name": "B2",
            "screen_sha256": MODULE._sha256(control),
        },
        "selection": {
            "checkpoint_steps": checkpoint_steps,
            "rule": (
                "earliest checkpoint passing the complete six-observation route "
                "and action-fidelity development gate"
            ),
        },
        "promotion_gate": {
            "paired_action_fidelity_units": 6,
            "zero_paired_pose_error_regressions": True,
            "mean_normalized_pose_error_improvement_strictly_positive": True,
            "one_sided_95pct_bootstrap_lower_bound_minimum": 0.0,
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _mode_flow_weighted_config(
    path: Path, control: Path, checkpoint_steps: list[int]
) -> Path:
    payload = {
        "frozen_before_candidate_training": True,
        "candidate": MODULE.MODE_FLOW_WEIGHTED_CANDIDATE,
        "isolated_factor": {
            "name": MODULE.MODE_FLOW_WEIGHTING_FACTOR,
            "treatment": [0.75, 1.0, 1.5],
            "joint_population_normalizer": 1.01,
            "scope": MODULE.MODE_FLOW_WEIGHTING_SCOPE,
        },
        "control": {
            "name": MODULE.STAGE_WEIGHTED_CANDIDATE,
            "screen_sha256": MODULE._sha256(control),
        },
        "selection": {
            "checkpoint_steps": checkpoint_steps,
            "rule": (
                "earliest checkpoint passing the complete six-observation route "
                "and action-fidelity development gate"
            ),
        },
        "promotion_gate": {
            "paired_action_fidelity_units": 6,
            "zero_paired_pose_error_regressions": True,
            "mean_normalized_pose_error_improvement_strictly_positive": True,
            "one_sided_95pct_bootstrap_lower_bound_minimum": 0.0,
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class CompareMobilePI05ActionFidelityTests(unittest.TestCase):
    def test_promotes_six_paired_improvements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = _screen(root / "control.json", MODULE.CONTROL_CONTRACT, [(0.06, 0.6)] * 6)
            candidate = _screen(root / "candidate.json", MODULE.CANDIDATE_CONTRACT, [(0.03, 0.3)] * 6)

            summary = MODULE.compare_action_fidelity(control, [candidate])

        self.assertEqual(summary["status"], "promoted")
        comparison = summary["comparisons"][0]
        self.assertEqual(comparison["improved_observations"], 6)
        self.assertEqual(comparison["regressed_observations"], 0)
        self.assertEqual(
            comparison["exact_sign_test"]["one_sided_p_value"], 1 / 64
        )
        self.assertEqual(
            comparison["exact_enumerated_percentile_bootstrap"]["resamples"],
            6**6,
        )
        self.assertAlmostEqual(
            comparison["exact_enumerated_percentile_bootstrap"]["lower_bound"],
            0.5,
        )

    def test_rejects_one_paired_regression(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = _screen(root / "control.json", MODULE.CONTROL_CONTRACT, [(0.06, 0.6)] * 6)
            candidate_errors = [(0.03, 0.3)] * 5 + [(0.09, 0.9)]
            candidate = _screen(root / "candidate.json", MODULE.CANDIDATE_CONTRACT, candidate_errors)

            summary = MODULE.compare_action_fidelity(control, [candidate])

        comparison = summary["comparisons"][0]
        self.assertEqual(summary["status"], "not_promoted")
        self.assertEqual(comparison["regressed_observations"], 1)
        self.assertFalse(
            comparison["promotion_gates"]["zero_paired_regressions"]
        )

    def test_rejects_seed_panel_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = _screen(root / "control.json", MODULE.CONTROL_CONTRACT, [(0.06, 0.6)] * 6)
            candidate = _screen(root / "candidate.json", MODULE.CANDIDATE_CONTRACT, [(0.03, 0.3)] * 6)
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            payload["sample_seeds"] = [1, 2, 3]
            candidate.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "seed panels"):
                MODULE.compare_action_fidelity(control, [candidate])

    def test_selected_candidate_must_belong_to_panel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = _screen(root / "control.json", MODULE.CONTROL_CONTRACT, [(0.06, 0.6)] * 6)
            candidate = _screen(root / "candidate.json", MODULE.CANDIDATE_CONTRACT, [(0.03, 0.3)] * 6)

            with self.assertRaisesRegex(ValueError, "not in the candidate"):
                MODULE.compare_action_fidelity(
                    control,
                    [candidate],
                    selected_candidate_path=root / "other.json",
                )

    def test_rejects_preregistered_control_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = _screen(root / "control.json", MODULE.CONTROL_CONTRACT, [(0.06, 0.6)] * 6)
            candidate = _screen(root / "candidate.json", MODULE.CANDIDATE_CONTRACT, [(0.03, 0.3)] * 6)
            config = root / "analysis.json"
            config.write_text(
                json.dumps(
                    {
                        "candidate": "B3",
                        "isolated_factor": {"treatment": "incremental_se3_v1"},
                        "control": {
                            "screen_sha256": "0" * 64,
                            "action_contract": MODULE.CONTROL_CONTRACT,
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "preregistered hash"):
                MODULE.compare_action_fidelity(
                    control,
                    [candidate],
                    preregistered_config_path=config,
                )

    def test_stage_weighted_selects_earliest_passing_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = _screen(
                root / "control.json",
                MODULE.CONTROL_CONTRACT,
                [(0.06, 0.6)] * 6,
                step=12000,
            )
            step_3000 = _screen(
                root / "step-3000.json",
                MODULE.CONTROL_CONTRACT,
                [(0.03, 0.3)] * 6,
                step=3000,
            )
            step_6000 = _screen(
                root / "step-6000.json",
                MODULE.CONTROL_CONTRACT,
                [(0.02, 0.2)] * 6,
                step=6000,
            )
            config = _stage_weighted_config(
                root / "config.json", control, [3000, 6000]
            )

            summary = MODULE.compare_action_fidelity(
                control,
                [step_6000, step_3000],
                preregistered_config_path=config,
            )

        self.assertEqual(summary["protocol"], MODULE.STAGE_WEIGHTED_PROTOCOL)
        self.assertEqual(summary["status"], "promoted")
        self.assertEqual(summary["selected_candidate_step"], 3000)
        self.assertEqual(summary["candidate_action_contract"], MODULE.CONTROL_CONTRACT)

    def test_stage_weighted_excludes_failed_screen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = _screen(
                root / "control.json", MODULE.CONTROL_CONTRACT, [(0.06, 0.6)] * 6
            )
            failed_3000 = _screen(
                root / "step-3000.json",
                MODULE.CONTROL_CONTRACT,
                [(0.03, 0.3)] * 6,
                step=3000,
                status="failed",
            )
            passed_6000 = _screen(
                root / "step-6000.json",
                MODULE.CONTROL_CONTRACT,
                [(0.03, 0.3)] * 6,
                step=6000,
            )
            config = _stage_weighted_config(
                root / "config.json", control, [3000, 6000]
            )

            summary = MODULE.compare_action_fidelity(
                control,
                [failed_3000, passed_6000],
                preregistered_config_path=config,
            )

        self.assertEqual(summary["selected_candidate_step"], 6000)
        self.assertFalse(summary["comparisons"][0]["promotion_passed"])

    def test_stage_weighted_rejects_manual_later_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = _screen(
                root / "control.json", MODULE.CONTROL_CONTRACT, [(0.06, 0.6)] * 6
            )
            step_3000 = _screen(
                root / "step-3000.json",
                MODULE.CONTROL_CONTRACT,
                [(0.03, 0.3)] * 6,
                step=3000,
            )
            step_6000 = _screen(
                root / "step-6000.json",
                MODULE.CONTROL_CONTRACT,
                [(0.02, 0.2)] * 6,
                step=6000,
            )
            config = _stage_weighted_config(
                root / "config.json", control, [3000, 6000]
            )

            with self.assertRaisesRegex(ValueError, "not the earliest checkpoint"):
                MODULE.compare_action_fidelity(
                    control,
                    [step_3000, step_6000],
                    selected_candidate_path=step_6000,
                    preregistered_config_path=config,
                )

    def test_stage_weighted_reports_no_selection_when_all_regress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = _screen(
                root / "control.json", MODULE.CONTROL_CONTRACT, [(0.06, 0.6)] * 6
            )
            candidate = _screen(
                root / "step-3000.json",
                MODULE.CONTROL_CONTRACT,
                [(0.09, 0.9)] * 6,
                step=3000,
            )
            config = _stage_weighted_config(root / "config.json", control, [3000])

            summary = MODULE.compare_action_fidelity(
                control,
                [candidate],
                preregistered_config_path=config,
            )

        self.assertEqual(summary["status"], "not_promoted")
        self.assertIsNone(summary["selected_candidate_screen"])
        self.assertIsNone(summary["selected_candidate_step"])
        self.assertFalse(summary["selected_candidate_promotion_passed"])

    def test_mode_flow_weighted_candidate_uses_b3_sw_as_paired_control(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = _screen(
                root / "control.json",
                MODULE.CONTROL_CONTRACT,
                [(0.06, 0.6)] * 6,
                step=12000,
            )
            candidate = _screen(
                root / "step-3000.json",
                MODULE.CONTROL_CONTRACT,
                [(0.03, 0.3)] * 6,
                step=3000,
            )
            config = _mode_flow_weighted_config(
                root / "config.json", control, [3000]
            )

            summary = MODULE.compare_action_fidelity(
                control,
                [candidate],
                preregistered_config_path=config,
            )

        self.assertEqual(summary["protocol"], MODULE.MODE_FLOW_WEIGHTED_PROTOCOL)
        self.assertEqual(summary["candidate"], MODULE.MODE_FLOW_WEIGHTED_CANDIDATE)
        self.assertEqual(summary["status"], "promoted")
        self.assertEqual(summary["selected_candidate_step"], 3000)


if __name__ == "__main__":
    unittest.main()
