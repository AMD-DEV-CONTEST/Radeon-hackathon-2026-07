from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

from parcel_sorter.controller_probe_confirmation import (
    audit_confirmation,
    select_veto_static,
    summarize_confirmation,
)
from scripts.audit_controller_probe_confirmation_protocol import audit_protocol
from scripts.run_controller_probe_confirmation_collection import planned_runs, run


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = PROJECT_ROOT / "configs/controller_probe_confirmation_v5.toml"


def _row(
    group: int,
    candidate: int,
    *,
    eligible: bool,
    success: bool,
    aborted: bool,
    profile: str = "box",
) -> dict:
    return {
        "group_id": f"{profile}:{group}",
        "profile": profile,
        "candidate_id": f"candidate-{candidate}",
        "static_rank": candidate,
        "strata": {
            "profile_novelty": "unseen_profile",
            "yaw_band": "axis_near_0_15deg",
            "friction_band": "low_le_0p50",
            "camera_noise_band": "low_le_0p010m",
            "mass_band": "light_le_0p50kg",
        },
        "probe": {
            "consumed_trace_frames": 10,
            "feature_map": {
                "probe_completed": float(eligible),
                "probe_safety_aborted": 0.0,
                "contact_acquired": float(eligible),
                "terminal_grasp_contact": float(eligible),
                "terminal_parcel_lifted": float(eligible),
            },
        },
        "labels": {
            "success": success,
            "safety_aborted": aborted,
            "dropped": False,
            "max_contact_force_n": 40.0 if aborted else 10.0,
            "duration_seconds": 8.0,
        },
    }


class ControllerProbeConfirmationTests(unittest.TestCase):
    def test_veto_uses_next_static_candidate_only_when_eligible(self) -> None:
        rows = [
            _row(1, 0, eligible=False, success=False, aborted=True),
            _row(1, 1, eligible=True, success=True, aborted=False),
        ]
        selection = select_veto_static(rows)[0]
        self.assertEqual(selection["model_candidate_id"], "candidate-1")
        self.assertEqual(selection["baseline_candidate_id"], "candidate-0")

    def test_veto_abstains_without_a_hidden_static_fallback(self) -> None:
        rows = [
            _row(1, 0, eligible=False, success=False, aborted=True),
            _row(1, 1, eligible=False, success=False, aborted=True),
        ]
        selection = select_veto_static(rows)[0]
        self.assertEqual(selection["decision"], "safe_abstain")
        self.assertIsNone(selection["model_candidate_id"])

    def test_confirmation_gate_requires_distributed_significant_safety_gain(self) -> None:
        selections = []
        profiles = ("a", "b")
        for index in range(20):
            profile = profiles[index % 2]
            baseline_aborted = index < 6
            rows = [
                _row(index, 0, eligible=not baseline_aborted, success=False, aborted=baseline_aborted, profile=profile),
                _row(index, 1, eligible=False, success=False, aborted=True, profile=profile),
            ]
            selections.extend(select_veto_static(rows))
        summary = summarize_confirmation(selections)
        result = audit_confirmation(
            summary,
            expected_groups=20,
            expected_groups_per_profile=10,
            min_safety_abort_reductions=6,
            min_profiles_with_safety_reduction=2,
            safety_alpha=0.05,
            selection_p95_ms=0.1,
            max_selection_p95_ms=5.0,
        )
        self.assertTrue(result["passes"])
        self.assertLessEqual(
            summary["safety_abort"]["paired"]["p_value_one_sided_exact"],
            0.05,
        )

        concentrated = deepcopy(summary)
        concentrated["by_profile"]["b"]["safety_abort"]["paired"]["baseline_only_positive"] = 0
        result = audit_confirmation(
            concentrated,
            expected_groups=20,
            expected_groups_per_profile=10,
            min_safety_abort_reductions=6,
            min_profiles_with_safety_reduction=2,
            safety_alpha=0.05,
            selection_p95_ms=0.1,
            max_selection_p95_ms=5.0,
        )
        self.assertFalse(result["passes"])
        self.assertIn("safety_benefit_concentrated", result["reasons"])

    def test_protocol_is_disjoint_and_all_box_collection_is_plannable(self) -> None:
        result = audit_protocol(PROTOCOL)
        self.assertEqual(result["status"], "protocol_valid")
        self.assertEqual(result["old_population_overlap_count"], 0)
        self.assertEqual(result["group_count"], 80)
        planned = planned_runs(PROTOCOL, "confirmation", Path("out"))
        self.assertEqual(len(planned), 80)
        result = run(
            type("Args", (), {
                "protocol": PROTOCOL,
                "output_dir": Path("out"),
                "config": PROJECT_ROOT / "configs/catalog_v2.toml",
                "backend": "rocm",
                "max_candidates": 6,
                "repeats": 1,
                "resume": False,
                "dry_run": True,
            })()
        )
        self.assertEqual(result["planning_activation_policy"], "all-boxes")


if __name__ == "__main__":
    unittest.main()
