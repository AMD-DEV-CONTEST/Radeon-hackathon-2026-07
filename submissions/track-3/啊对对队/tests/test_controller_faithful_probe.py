from __future__ import annotations

import copy
import unittest

from parcel_sorter.controller_faithful_probe import (
    PROBE_FEATURE_NAMES,
    audit_controller_faithful_probe_candidate,
    extract_controller_faithful_probe,
    select_controller_faithful_probe_policy,
    select_controller_faithful_probe_candidate,
    summarize_controller_faithful_probe,
)


def _trace(*, post_boundary_force: float = 999.0) -> list[dict]:
    rows = []
    stages = ("approach", "approach", "grasp", "verify", "verify", "lift", "lift", "place")
    for frame, stage in enumerate(stages):
        relative = [0.01, 0.02, 0.03]
        if stage == "lift":
            relative[2] = 0.031 + (frame - 5) * 0.001
        rows.append(
            {
                "frame": frame,
                "stage": stage,
                "contact_force_n": 4.0 + frame,
                "ee_position_m": [0.1, 0.2, 0.3 + frame * 0.01],
                "parcel_position_m": [0.1, 0.2, 0.1 + (0.02 if frame >= 7 else 0.0)],
                "ee_parcel_relative_position_m": relative,
                "grasp_contact": stage in {"verify", "lift", "place"},
                "parcel_lifted": stage == "place",
                "transport_slip": False,
            }
        )
    rows.append(
        {
            "frame": len(rows),
            "stage": "release",
            "contact_force_n": post_boundary_force,
            "ee_position_m": [9.0, 9.0, 9.0],
            "parcel_position_m": [9.0, 9.0, 9.0],
            "ee_parcel_relative_position_m": [9.0, 9.0, 9.0],
            "grasp_contact": False,
            "parcel_lifted": False,
            "transport_slip": True,
        }
    )
    return rows


def _payload(*, labels: tuple[bool, bool] = (True, False)) -> dict:
    rollouts = []
    for index, (success, safety_aborted) in enumerate((labels, (False, True))):
        candidate_id = f"candidate-{index}"
        rollouts.append(
            {
                "candidate_id": candidate_id,
                "selected_candidate_id": candidate_id,
                "repeat": 0,
                "static_rank": index,
                "success": success,
                "safety_aborted": safety_aborted,
                "max_contact_force_n": 12.0 if not safety_aborted else 41.0,
                "duration_seconds": 8.0,
                "report": {"trace": _trace()},
            }
        )
    return {
        "profile": "medium_carton",
        "episode": 1,
        "contract": {
            "controller_faithful": True,
            "fresh_scene_per_rollout": True,
            "force_abort_n": 35.0,
        },
        "rollouts": rollouts,
    }


class ControllerFaithfulProbeTests(unittest.TestCase):
    def test_extracts_only_through_place_boundary(self) -> None:
        source = _payload()
        evidence = extract_controller_faithful_probe(
            source,
            source["rollouts"][0],
        )

        self.assertEqual(evidence["boundary_stage"], "place")
        self.assertEqual(evidence["boundary_frame"], 7)
        self.assertEqual(evidence["source_trace_frames"], 9)
        self.assertEqual(evidence["consumed_trace_frames"], 8)
        self.assertEqual(len(evidence["features"]), len(PROBE_FEATURE_NAMES))
        self.assertEqual(evidence["feature_map"]["probe_safety_aborted"], 0.0)
        self.assertEqual(evidence["feature_map"]["terminal_parcel_lifted"], 1.0)

    def test_post_boundary_mutation_cannot_change_features(self) -> None:
        source = _payload()
        first = extract_controller_faithful_probe(source, source["rollouts"][0])
        source["rollouts"][0]["report"]["trace"][-1]["contact_force_n"] = 0.0
        source["rollouts"][0]["report"]["trace"][-1]["ee_parcel_relative_position_m"] = [
            -100.0,
            -100.0,
            -100.0,
        ]
        second = extract_controller_faithful_probe(source, source["rollouts"][0])
        self.assertEqual(first["features"], second["features"])

    def test_policy_selection_does_not_read_final_labels(self) -> None:
        source = _payload()
        rows = []
        for rollout in source["rollouts"]:
            probe = extract_controller_faithful_probe(source, rollout)
            rows.append(
                {
                    "group_id": "medium_carton:1",
                    "profile": "medium_carton",
                    "candidate_id": rollout["candidate_id"],
                    "static_rank": rollout["static_rank"],
                    "probe": probe,
                    "labels": {
                        "success": rollout["success"],
                        "safety_aborted": rollout["safety_aborted"],
                        "max_contact_force_n": rollout["max_contact_force_n"],
                        "duration_seconds": rollout["duration_seconds"],
                    },
                }
            )
        changed = copy.deepcopy(rows)
        changed[0]["labels"], changed[1]["labels"] = (
            changed[1]["labels"],
            changed[0]["labels"],
        )
        first = select_controller_faithful_probe_policy(rows, policy="force-first")
        second = select_controller_faithful_probe_policy(changed, policy="force-first")
        self.assertEqual(first[0]["model_candidate_id"], second[0]["model_candidate_id"])

    def test_no_eligible_candidate_abstains_instead_of_static_fallback(self) -> None:
        source = _payload()
        rows = []
        for rollout in source["rollouts"]:
            probe = extract_controller_faithful_probe(source, rollout)
            probe["feature_map"]["terminal_parcel_lifted"] = 0.0
            rows.append(
                {
                    "group_id": "medium_carton:1",
                    "profile": "medium_carton",
                    "candidate_id": rollout["candidate_id"],
                    "static_rank": rollout["static_rank"],
                    "probe": probe,
                    "labels": {
                        "success": bool(rollout["success"]),
                        "safety_aborted": bool(rollout["safety_aborted"]),
                        "max_contact_force_n": rollout["max_contact_force_n"],
                        "duration_seconds": 8.0,
                    },
                }
            )
        selected = select_controller_faithful_probe_policy(rows, policy="veto-static")
        self.assertIsNone(selected[0]["model_candidate_id"])
        self.assertEqual(selected[0]["decision"], "safe_abstain")

    def test_gate_rejects_success_regression_even_without_safety_regression(self) -> None:
        summary = {
            "group_count": 4,
            "model_successes": 1,
            "model_safety_aborts": 0,
            "baseline_successes": 2,
            "baseline_safety_aborts": 1,
            "per_profile": {
                "box": {
                    "group_count": 4,
                    "model_successes": 1,
                    "model_safety_aborts": 0,
                    "baseline_successes": 2,
                    "baseline_safety_aborts": 1,
                }
            },
        }
        audit = audit_controller_faithful_probe_candidate(
            "probe",
            summary,
            [{"model_successes": 1, "baseline_successes": 2, "model_safety_aborts": 0, "baseline_safety_aborts": 1}],
            expected_group_count=4,
            expected_profile_group_count=4,
            max_selection_p95_ms=5.0,
            selection_p95_ms=1.0,
        )
        self.assertFalse(audit["passes"])
        self.assertIn("per_profile_success_regression", audit["reasons"])
        self.assertEqual(
            select_controller_faithful_probe_candidate((audit,))["status"],
            "no_probe_candidate",
        )

    def test_summary_tracks_safe_abstention_separately(self) -> None:
        source = _payload()
        rows = []
        for rollout in source["rollouts"]:
            rows.append(
                {
                    "group_id": "medium_carton:1",
                    "profile": "medium_carton",
                    "candidate_id": rollout["candidate_id"],
                    "static_rank": rollout["static_rank"],
                    "probe": extract_controller_faithful_probe(source, rollout),
                    "labels": {
                        "success": bool(rollout["success"]),
                        "safety_aborted": bool(rollout["safety_aborted"]),
                        "max_contact_force_n": rollout["max_contact_force_n"],
                        "duration_seconds": 8.0,
                    },
                }
            )
        summary = summarize_controller_faithful_probe(
            select_controller_faithful_probe_policy(rows, policy="veto-static")
        )
        self.assertEqual(summary["group_count"], 1)
        self.assertEqual(summary["safe_abstentions"], 0)
        self.assertEqual(summary["executed_group_count"], 1)


if __name__ == "__main__":
    unittest.main()
