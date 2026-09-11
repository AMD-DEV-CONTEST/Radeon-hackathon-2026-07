import unittest

from parcel_sorter.failure_analysis import analyze_expert_summary


def _trace_frame(
    frame: int,
    stage: str,
    command: str,
    reason: str,
    *,
    force: float = 0.0,
    pregrasp: bool = False,
    contact: bool = False,
    lifted: bool = False,
) -> dict[str, object]:
    return {
        "frame": frame,
        "stage": stage,
        "command": command,
        "reason": reason,
        "contact_force_n": force,
        "excessive_contact_force": force > 35.0,
        "at_pregrasp": pregrasp,
        "grasp_contact": contact,
        "parcel_lifted": lifted,
    }


def _episode(
    index: int,
    profile: str,
    trace: list[dict[str, object]],
    *,
    success: bool = False,
    dropped: bool = False,
) -> dict[str, object]:
    return {
        "episode_index": index,
        "terminal_stage": trace[-1]["stage"],
        "result": {
            "success": success,
            "dropped": dropped,
            "retries": 0,
            "max_contact_force_n": max(float(item["contact_force_n"]) for item in trace),
        },
        "sample": {
            "profile_id": profile,
            "shape": "box",
            "orientation_mode": "yaw",
            "dimensions_m": [0.20, 0.06, 0.08],
            "position_xy": [0.55, 0.05],
            "mass_kg": 0.5,
            "friction": 0.6,
            "yaw_rad": 0.2,
            "action_delay_steps": 1,
        },
        "trace": trace,
    }


class FailureAnalysisTests(unittest.TestCase):
    def test_classifies_force_context_and_non_force_failures(self) -> None:
        complete = _episode(
            1,
            "box",
            [
                _trace_frame(0, "approach", "move_pregrasp", "approaching parcel"),
                _trace_frame(1, "complete", "stop", "parcel sorted", pregrasp=True, contact=True, lifted=True),
            ],
            success=True,
        )
        force_abort = _episode(
            2,
            "box",
            [
                _trace_frame(0, "approach", "move_pregrasp", "approaching parcel", force=5.0),
                _trace_frame(1, "abort", "stop", "safety fault", force=45.0),
            ],
        )
        approach_timeout = _episode(
            3,
            "tube",
            [_trace_frame(0, "approach", "move_pregrasp", "approaching parcel")],
        )
        lost_lift = _episode(
            4,
            "tube",
            [
                _trace_frame(0, "verify", "hold", "checking contact", pregrasp=True, contact=True),
                _trace_frame(1, "abort", "stop", "grasp lost during lift", pregrasp=True, lifted=True),
            ],
        )
        analysis = analyze_expert_summary(
            {
                "config": {"task": {"max_contact_force_n": 35.0}},
                "episodes": [complete, force_abort, approach_timeout, lost_lift],
            }
        )

        self.assertEqual(analysis["global"]["attempts"], 4)
        self.assertEqual(analysis["global"]["successes"], 1)
        self.assertEqual(analysis["global"]["force_safety_violations"], 1)
        self.assertEqual(
            analysis["profiles"]["box"]["failure_mode_counts"],
            {"complete": 1, "force_safety_abort": 1},
        )
        force_episode = next(
            item for item in analysis["failed_episodes"] if item["episode_index"] == 2
        )
        self.assertEqual(force_episode["force_context_stage"], "approach")
        self.assertEqual(force_episode["force_context_command"], "move_pregrasp")
        self.assertEqual(force_episode["force_jump_n"], 40.0)
        self.assertEqual(
            analysis["profiles"]["tube"]["failure_mode_counts"],
            {"approach_timeout": 1, "grasp_lost_during_lift": 1},
        )

    def test_rejects_missing_trace_and_invalid_threshold(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-empty trace"):
            analyze_expert_summary(
                {
                    "config": {"task": {"max_contact_force_n": 35.0}},
                    "episodes": [
                        {
                            "episode_index": 0,
                            "sample": {},
                            "result": {},
                            "trace": [],
                        }
                    ],
                }
            )
        with self.assertRaisesRegex(ValueError, "positive and finite"):
            analyze_expert_summary(
                {
                    "config": {"task": {"max_contact_force_n": 0.0}},
                    "episodes": [{}],
                }
            )


if __name__ == "__main__":
    unittest.main()
