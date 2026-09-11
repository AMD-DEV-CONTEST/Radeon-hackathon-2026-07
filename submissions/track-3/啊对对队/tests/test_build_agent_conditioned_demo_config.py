from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_agent_conditioned_demo_config.py"


class BuildAgentConditionedDemoConfigTests(unittest.TestCase):
    def test_filters_mode_shape_and_stale_bulk_quotas(self) -> None:
        source = {
            "cells": [
                {
                    "cell_id": "box-top",
                    "grasp_mode": "top_suction",
                    "candidate_attempts": 10,
                    "target_successes": 8,
                },
                {
                    "cell_id": "box-side",
                    "grasp_mode": "side_suction",
                    "candidate_attempts": 10,
                    "target_successes": 8,
                },
            ],
            "planned_attempts": 20,
            "target_successes": 16,
            "success_quotas_by_sampling_stratum": {"stale": 8},
            "episodes": [
                {
                    "episode_id": "top-box",
                    "shape": "box",
                    "grasp_mode": "top_suction",
                    "design_cell": "box-top",
                },
                {
                    "episode_id": "side-cylinder",
                    "shape": "cylinder",
                    "grasp_mode": "side_suction",
                    "design_cell": "box-side",
                },
                {
                    "episode_id": "side-box",
                    "shape": "box",
                    "grasp_mode": "side_suction",
                    "design_cell": "box-side",
                },
            ],
        }
        plan = {
            "protocol": "parcel-agent-pi05-episode-plan-v1",
            "status": "passed",
            "agent_trace": {
                "status": "passed",
                "requested_model": "gpt-5.6-luna",
                "actual_model": "gpt-5.5",
                "fallback_used": True,
            },
            "directive": {"directive_id": "test-directive"},
            "pi05_task_bridge": {
                "authority": "task_conditioning_only",
                "task_text": "pick the box with side suction",
                "runtime_grasp_mode": "side_suction",
                "recovery_strategy": "reobserve",
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "source.json"
            plan_path = root / "plan.json"
            output_path = root / "output.json"
            source_path.write_text(json.dumps(source), encoding="utf-8")
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-config",
                    str(source_path),
                    "--agent-plan",
                    str(plan_path),
                    "--output",
                    str(output_path),
                    "--shape",
                    "box",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            result = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(
            [item["episode_id"] for item in result["episodes"]], ["side-box"]
        )
        self.assertEqual(result["planned_attempts"], 1)
        self.assertEqual(result["target_successes"], 0)
        self.assertNotIn("success_quotas_by_sampling_stratum", result)
        self.assertEqual(result["cells"][0]["cell_id"], "box-side")
        self.assertEqual(result["cells"][0]["candidate_attempts"], 1)
        self.assertEqual(result["cells"][0]["target_successes"], 0)
        self.assertEqual(result["agent_plan"]["path"], "plan.json")
        self.assertRegex(result["agent_plan"]["sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
