from __future__ import annotations

import unittest

from parcel_sorter.conservative_grasp_memory import (
    audit_cross_validated_candidate,
    profile_stratified_group_folds,
    robust_feature_statistics,
    select_conservative_memory_candidates,
    select_cross_validated_candidate,
    summarize_conservative_selections,
)
from parcel_sorter.grasp_scoring import GRASP_FEATURE_NAMES


def row(
    group_id: str,
    profile: str,
    candidate_id: str,
    static_rank: int,
    *,
    success: bool = False,
    safety_aborted: bool = False,
    force_n: float = 10.0,
) -> dict:
    return {
        "group_id": group_id,
        "profile": profile,
        "candidate_id": candidate_id,
        "static_rank": static_rank,
        "features": [float(static_rank)] * len(GRASP_FEATURE_NAMES),
        "labels": {
            "success": success,
            "safety_aborted": safety_aborted,
            "max_contact_force_n": force_n,
            "duration_seconds": 8.0,
        },
    }


def memory_evidence(
    candidate_id: str,
    profile: str,
    static_rank: int,
    *,
    unsafe_neighbors: int = 0,
    success_neighbors: int = 2,
    force_upper_n: float = 20.0,
    distance: float = 0.5,
) -> dict:
    return {
        "candidate_id": candidate_id,
        "profile": profile,
        "static_rank": static_rank,
        "neighbor_count": 3,
        "unsafe_neighbor_count": unsafe_neighbors,
        "safe_success_neighbor_count": success_neighbors,
        "force_upper_n": force_upper_n,
        "duration_median_seconds": 8.0,
        "kth_distance": distance,
        "neighbor_group_ids": ["n:1", "n:2", "n:3"],
        "neighbor_candidate_ids": ["a", "b", "c"],
    }


class ConservativeGraspMemoryTests(unittest.TestCase):
    def test_profile_stratified_folds_keep_groups_intact_and_balanced(self) -> None:
        rows = []
        for profile in ("box-a", "box-b"):
            for group_index in range(4):
                group_id = f"{profile}:{group_index}"
                rows.extend(
                    [
                        row(group_id, profile, "base", 0),
                        row(group_id, profile, "alternate", 3),
                    ]
                )

        first = profile_stratified_group_folds(rows, fold_count=2, seed=7)
        second = profile_stratified_group_folds(rows, fold_count=2, seed=7)

        self.assertEqual(first, second)
        self.assertEqual(len(first), 8)
        for fold in (0, 1):
            for profile in ("box-a", "box-b"):
                self.assertEqual(
                    sum(
                        assigned == fold and group_id.startswith(f"{profile}:")
                        for group_id, assigned in first.items()
                    ),
                    2,
                )

    def test_robust_statistics_have_positive_scale_for_constant_columns(self) -> None:
        rows = [
            row("box:1", "box", "a", 0),
            row("box:2", "box", "b", 0),
        ]

        locations, scales = robust_feature_statistics(rows)

        self.assertEqual(len(locations), len(GRASP_FEATURE_NAMES))
        self.assertTrue(all(scale > 0 for scale in scales))

    def test_selects_supported_candidate_and_falls_back_when_none_qualify(self) -> None:
        rows = [
            row("box:1", "box", "base", 0, success=False),
            row("box:1", "box", "alternate", 3, success=True),
            row("box:2", "box", "base", 0, success=True),
            row("box:2", "box", "alternate", 3, success=False),
        ]
        evidence = [
            memory_evidence("base", "box", 0, unsafe_neighbors=1),
            memory_evidence("alternate", "box", 3),
            memory_evidence("base", "box", 0, distance=2.0),
            memory_evidence("alternate", "box", 3, force_upper_n=40.0),
        ]

        selected = select_conservative_memory_candidates(
            rows,
            evidence,
            distance_thresholds={"box": 1.0},
            force_limit_n=35.0,
            minimum_success_ratio=0.5,
            maximum_static_rank=3,
        )

        self.assertEqual(selected[0]["model_candidate_id"], "alternate")
        self.assertEqual(selected[0]["decision"], "memory_supported")
        self.assertEqual(selected[1]["model_candidate_id"], "base")
        self.assertEqual(selected[1]["decision"], "static_fallback")
        summary = summarize_conservative_selections(selected)
        self.assertEqual(summary["model_successes"], 2)
        self.assertEqual(summary["baseline_successes"], 1)
        self.assertEqual(summary["static_fallbacks"], 1)

    def test_rejects_wrong_candidate_order(self) -> None:
        rows = [row("box:1", "box", "base", 0)]
        evidence = [memory_evidence("different", "box", 0)]

        with self.assertRaisesRegex(ValueError, "candidate order"):
            select_conservative_memory_candidates(
                rows,
                evidence,
                distance_thresholds={"box": 1.0},
                force_limit_n=35.0,
                minimum_success_ratio=0.5,
                maximum_static_rank=3,
            )

    def test_cv_gate_rejects_fold_safety_regression(self) -> None:
        summary = {
            "group_count": 4,
            "model_successes": 3,
            "model_safety_aborts": 1,
            "baseline_successes": 2,
            "baseline_safety_aborts": 1,
            "model_mean_force_n": 10.0,
            "changed_from_baseline": 1,
            "per_profile": {
                "box": {
                    "group_count": 4,
                    "model_safety_aborts": 1,
                    "baseline_safety_aborts": 1,
                }
            },
        }
        folds = [
            {"model_safety_aborts": 1, "baseline_safety_aborts": 0},
            {"model_safety_aborts": 0, "baseline_safety_aborts": 1},
        ]

        audit = audit_cross_validated_candidate(
            "candidate",
            summary,
            folds,
            expected_group_count=4,
            expected_profile_group_count=4,
            max_warm_p95_ms=5.0,
            warm_p95_ms=1.0,
        )

        self.assertFalse(audit["passes"])
        self.assertIn("per_fold_safety_regression", audit["reasons"])
        decision = select_cross_validated_candidate((audit,))
        self.assertEqual(decision["status"], "no_cv_candidate")
        self.assertFalse(decision["new_physics_authorized"])

    def test_cv_selection_is_safety_first_and_does_not_authorize_physics(self) -> None:
        safer = {
            "name": "safer",
            "passes": True,
            "warm_p95_ms": 1.0,
            "summary": {
                "model_safety_aborts": 0,
                "model_successes": 2,
                "model_mean_force_n": 10.0,
                "changed_from_baseline": 1,
            },
        }
        more_successful = {
            "name": "more-successful",
            "passes": True,
            "warm_p95_ms": 1.0,
            "summary": {
                "model_safety_aborts": 1,
                "model_successes": 4,
                "model_mean_force_n": 9.0,
                "changed_from_baseline": 2,
            },
        }

        decision = select_cross_validated_candidate((more_successful, safer))

        self.assertEqual(decision["status"], "cv_candidate_found")
        self.assertEqual(decision["selected"], "safer")
        self.assertFalse(decision["new_physics_authorized"])


if __name__ == "__main__":
    unittest.main()
