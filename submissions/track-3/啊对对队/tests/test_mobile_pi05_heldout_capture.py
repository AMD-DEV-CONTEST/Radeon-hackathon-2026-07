import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from parcel_sorter.mobile_pi05_contract import PI05ResidualContext, encode_pi05_state
from parcel_sorter.mobile_pi05_heldout_capture import (
    canonical_payload_sha256,
    validate_pi05_heldout_observation,
    validate_pi05_heldout_collection,
    validate_pi05_workspace_block,
    write_pi05_heldout_observation,
)


def _panel() -> dict:
    modes = ("top_suction", "side_suction", "cooperative_cradle")
    return {
        "collection_id": "test-panel",
        "episodes": [
            {"episode_id": f"{mode}-{index}", "grasp_mode": mode}
            for mode in modes
            for index in range(2)
        ]
    }


def _state() -> tuple[float, ...]:
    context = PI05ResidualContext(
        sealed_cup_mask=(False, False, False),
        parcel_shape="box",
        parcel_size_m=(0.2, 0.1, 0.05),
        parcel_mass_kg=0.4,
        grasp_mode="cooperative_cradle",
        retry_index=0,
        stage="pregrasp",
        left_force_history_n=(),
        right_force_history_n=(),
        left_contact_anchor_m=(0.0, 0.0, 0.0),
        right_contact_anchor_m=(0.0, 0.0, 0.0),
        grasp_mode_conditioned=False,
    )
    return encode_pi05_state([0.0] * 43, context)


class MobilePI05HeldoutCaptureTests(unittest.TestCase):
    def test_workspace_positions_are_balanced_across_modes(self) -> None:
        panel = _panel()
        block = {
            "protocol": "pi05-heldout-workspace-block-v1",
            "panel_collection_id": panel["collection_id"],
            "panel_sha256": canonical_payload_sha256(panel),
            "assignments": [
                {"episode_id": item["episode_id"], "pedestal_x_m": (-0.6, -0.2)[index % 2]}
                for index, item in enumerate(panel["episodes"])
            ],
        }

        result = validate_pi05_workspace_block(block, panel)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["positions_per_mode"], [-0.6, -0.2])

    def test_workspace_mode_position_confound_is_rejected(self) -> None:
        panel = _panel()
        block = {
            "protocol": "pi05-heldout-workspace-block-v1",
            "panel_collection_id": panel["collection_id"],
            "panel_sha256": canonical_payload_sha256(panel),
            "assignments": [
                {
                    "episode_id": item["episode_id"],
                    "pedestal_x_m": -0.6 if item["grasp_mode"] == "top_suction" else -0.2,
                }
                for item in panel["episodes"]
            ],
        }

        with self.assertRaisesRegex(ValueError, "balanced"):
            validate_pi05_workspace_block(block, panel)

    def test_capture_has_no_action_arrays_and_hidden_mode_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episode.npz"
            payload = write_pi05_heldout_observation(
                path,
                rgb=np.zeros((8, 8, 3), dtype=np.uint8),
                depth_m=np.ones((8, 8), dtype=np.float32),
                observation_state=_state(),
                metadata={
                    "episode_id": "episode",
                    "task_text": "Move the observed parcel to the destination.",
                    "expected_grasp_mode": "cooperative_cradle",
                },
            )

            result = validate_pi05_heldout_observation(
                path, path.with_suffix(".json")
            )
            with np.load(path, allow_pickle=False) as loaded:
                self.assertEqual(
                    set(loaded.files),
                    {"overhead_rgb", "overhead_depth_m", "observation_state"},
                )
                self.assertTrue(np.allclose(loaded["observation_state"][52:55], 0.0))
            self.assertFalse(payload["contains_actions"])
            self.assertEqual(result["action_arrays"], 0)

    def test_tampered_capture_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episode.npz"
            write_pi05_heldout_observation(
                path,
                rgb=np.zeros((8, 8, 3), dtype=np.uint8),
                depth_m=np.ones((8, 8), dtype=np.float32),
                observation_state=_state(),
                metadata={
                    "episode_id": "episode",
                    "task_text": "Move the observed parcel to the destination.",
                    "expected_grasp_mode": "top_suction",
                },
            )
            sidecar = path.with_suffix(".json")
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            metadata["observation_sha256"] = "0" * 64
            sidecar.write_text(json.dumps(metadata), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "SHA-256"):
                validate_pi05_heldout_observation(path, sidecar)

    def test_collection_audit_binds_every_episode_and_workspace(self) -> None:
        panel = _panel()
        block = {
            "protocol": "pi05-heldout-workspace-block-v1",
            "panel_collection_id": panel["collection_id"],
            "panel_sha256": canonical_payload_sha256(panel),
            "assignments": [
                {"episode_id": item["episode_id"], "pedestal_x_m": (-0.6, -0.2)[index % 2]}
                for index, item in enumerate(panel["episodes"])
            ],
        }
        for item in panel["episodes"]:
            item["task_text"] = "Move the observed parcel to the destination."
        block["panel_sha256"] = canonical_payload_sha256(panel)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            captures = []
            positions = {
                item["episode_id"]: item["pedestal_x_m"]
                for item in block["assignments"]
            }
            for episode in panel["episodes"]:
                path = root / "observations" / f"{episode['episode_id']}.npz"
                payload = write_pi05_heldout_observation(
                    path,
                    rgb=np.zeros((4, 4, 3), dtype=np.uint8),
                    depth_m=np.ones((4, 4), dtype=np.float32),
                    observation_state=_state(),
                    metadata={
                        "episode_id": episode["episode_id"],
                        "task_text": episode["task_text"],
                        "expected_grasp_mode": episode["grasp_mode"],
                        "pedestal_x_m": positions[episode["episode_id"]],
                    },
                )
                captures.append(
                    {
                        "episode_id": episode["episode_id"],
                        "observation": str(path.relative_to(root)),
                        "metadata": str(path.with_suffix(".json").relative_to(root)),
                        "observation_sha256": payload["observation_sha256"],
                    }
                )
            manifest = {
                "protocol": "pi05-heldout-observation-collection-v1",
                "split": "heldout_observation_do_not_train",
                "panel_sha256": canonical_payload_sha256(panel),
                "workspace_block_sha256": canonical_payload_sha256(block),
                "captures": captures,
                "contains_actions": False,
                "contains_recovery": False,
                "contains_outcome": False,
            }
            (root / "PI05_HELDOUT_OBSERVATION_MANIFEST.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

            result = validate_pi05_heldout_collection(root, panel, block)

            self.assertEqual(result["episodes"], 6)
            self.assertEqual(result["action_arrays"], 0)


if __name__ == "__main__":
    unittest.main()
