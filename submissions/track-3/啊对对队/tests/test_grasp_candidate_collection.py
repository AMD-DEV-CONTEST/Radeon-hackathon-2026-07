from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.run_grasp_candidate_collection import planned_runs, run


class GraspCandidateCollectionTests(unittest.TestCase):
    def _protocol(self, directory: str) -> Path:
        path = Path(directory) / "protocol.toml"
        path.write_text(
            """
[[splits]]
name = "train"
profile_id = "medium_carton"
episode_ids = [2, 1]

[[splits]]
name = "holdout"
profile_id = "medium_carton"
episode_ids = [3]
""".strip(),
            encoding="utf-8",
        )
        return path

    def test_plans_split_in_stable_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rows = planned_runs(
                self._protocol(directory),
                "train",
                Path(directory) / "output",
            )

        self.assertEqual([row["episode"] for row in rows], [1, 2])
        self.assertEqual(
            Path(rows[0]["output"]).parts[-3:],
            ("train", "medium_carton", "1.json"),
        )

    def test_holdout_is_locked_before_any_process_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            protocol = self._protocol(directory)
            args = argparse.Namespace(
                protocol=protocol,
                split="holdout",
                output_dir=Path(directory) / "output",
                config=Path(directory) / "config.toml",
                backend="rocm",
                max_candidates=6,
                repeats=1,
                resume=False,
                dry_run=True,
                unlock_holdout=False,
            )
            with self.assertRaisesRegex(PermissionError, "holdout collection is locked"):
                run(args)

    def test_dry_run_does_not_create_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            protocol = self._protocol(directory)
            output = Path(directory) / "output"
            args = argparse.Namespace(
                protocol=protocol,
                split="train",
                output_dir=output,
                config=Path(directory) / "config.toml",
                backend="rocm",
                max_candidates=6,
                repeats=1,
                resume=False,
                dry_run=True,
                unlock_holdout=False,
            )

            result = run(args)

            self.assertEqual(result["planned_episode_count"], 2)
            self.assertEqual(result["planned_max_rollouts"], 12)
            self.assertIn("--inactive-gate", result["runs"][0]["command"])
            self.assertEqual(result["planning_activation_policy"], "reset-fallback")
            self.assertFalse((output / "train/manifest.json").exists())

    def test_geometry_eligible_policy_is_forwarded_from_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            protocol = self._protocol(directory)
            original = protocol.read_text(encoding="utf-8")
            protocol.write_text(
                '[collection]\nplanning_activation_policy = "geometry-eligible"\n\n'
                + original,
                encoding="utf-8",
            )
            args = argparse.Namespace(
                protocol=protocol,
                split="train",
                output_dir=Path(directory) / "output",
                config=Path(directory) / "config.toml",
                backend="rocm",
                max_candidates=6,
                repeats=1,
                resume=False,
                dry_run=True,
                unlock_holdout=False,
            )

            result = run(args)

            command = result["runs"][0]["command"]
            self.assertEqual(
                command[command.index("--planning-activation") + 1],
                "geometry-eligible",
            )

    def test_accepts_sigsegv_only_after_complete_output_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            protocol = self._protocol(directory)
            output = Path(directory) / "output"
            args = argparse.Namespace(
                protocol=protocol,
                split="train",
                output_dir=output,
                config=Path(directory) / "config.toml",
                backend="rocm",
                max_candidates=1,
                repeats=1,
                resume=False,
                dry_run=False,
                unlock_holdout=False,
            )

            def write_complete(command, **_kwargs):
                output_path = Path(command[command.index("--output") + 1])
                episode = int(command[command.index("--episode") + 1])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    json.dumps(
                        {
                            "status": "complete",
                            "backend": command[command.index("--backend") + 1],
                            "config": str(
                                Path(command[command.index("--config") + 1]).resolve()
                            ),
                            "profile": "medium_carton",
                            "episode": episode,
                            "repeat_count": 1,
                            "contract": {
                                "controller_faithful": True,
                                "fresh_scene_per_rollout": True,
                                "collision_checked_reset_enabled": True,
                                "reset_fallback_gate_enabled": True,
                                "transport_contract_enabled": True,
                                "max_grasp_retries": 0,
                            },
                            "tested_candidate_ids": ["candidate-0"],
                            "rollouts": [
                                {"candidate_id": "candidate-0", "repeat": 0}
                            ],
                            "ranked_rollouts": [
                                {"candidate_id": "candidate-0", "repeat": 0}
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, -signal.SIGSEGV)

            with patch(
                "scripts.run_grasp_candidate_collection.subprocess.run",
                side_effect=write_complete,
            ):
                result = run(args)

            self.assertEqual(result["complete_episode_count"], 2)
            self.assertTrue(result["runs"][0]["accepted_cleanup_failure"])
            self.assertEqual(result["runs"][0]["child_returncode"], -signal.SIGSEGV)

    def test_rejects_sigsegv_when_output_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            protocol = self._protocol(directory)
            output = Path(directory) / "output"
            args = argparse.Namespace(
                protocol=protocol,
                split="train",
                output_dir=output,
                config=Path(directory) / "config.toml",
                backend="rocm",
                max_candidates=1,
                repeats=1,
                resume=False,
                dry_run=False,
                unlock_holdout=False,
            )

            def write_incomplete(command, **_kwargs):
                output_path = Path(command[command.index("--output") + 1])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    json.dumps(
                        {
                            "status": "complete",
                            "backend": command[command.index("--backend") + 1],
                            "config": str(
                                Path(command[command.index("--config") + 1]).resolve()
                            ),
                            "profile": "medium_carton",
                            "episode": int(command[command.index("--episode") + 1]),
                            "repeat_count": 1,
                            "contract": {
                                "controller_faithful": True,
                                "fresh_scene_per_rollout": True,
                                "collision_checked_reset_enabled": True,
                                "reset_fallback_gate_enabled": True,
                                "transport_contract_enabled": True,
                                "max_grasp_retries": 0,
                            },
                            "tested_candidate_ids": ["candidate-0"],
                            "rollouts": [],
                            "ranked_rollouts": [],
                        }
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, -signal.SIGSEGV)

            with patch(
                "scripts.run_grasp_candidate_collection.subprocess.run",
                side_effect=write_incomplete,
            ):
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    run(args)

            manifest = json.loads(
                (output / "train/manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["runs"][0]["status"], "failed")
            self.assertEqual(manifest["runs"][0]["child_returncode"], -signal.SIGSEGV)


if __name__ == "__main__":
    unittest.main()
