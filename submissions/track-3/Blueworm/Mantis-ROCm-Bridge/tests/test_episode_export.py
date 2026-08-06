from __future__ import annotations

import json
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:  # Minimal contract-only test environments omit NumPy.
    np = None

from mantis_rocm_bridge.contracts import ContractError
from mantis_rocm_bridge.episode_export import MantisLeRobotExportSession
from mantis_rocm_bridge.episode_state import replay_stage_trace
from mantis_rocm_bridge.gripper import virtual_to_physical


ROOT = Path(__file__).resolve().parents[1]


class FakeImage:
    def __init__(self, shape, byte: int) -> None:
        self.shape = shape
        self.dtype = "uint8"
        self._byte = byte

    def tobytes(self) -> bytes:
        return bytes([self._byte])


class FakeSink:
    def __init__(self) -> None:
        self.frames = []
        self.saved_frames = []
        self.saved = 0
        self.cleared = 0
        self.finalized = False

    def add_frame(self, frame) -> None:
        self.frames.append(frame)

    def save_episode(self) -> None:
        self.saved += 1
        self.saved_frames.extend(self.frames)
        self.frames = []

    def clear_episode_buffer(self, *, delete_images: bool) -> None:
        self.cleared += 1
        self.frames = []

    def finalize(self) -> None:
        self.finalized = True


@unittest.skipIf(np is None, "NumPy is required for LeRobot export tests")
class EpisodeExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.port = json.loads(
            (ROOT / "configs/mantis-port-config.json").read_text(encoding="utf-8")
        )
        cls.interface = json.loads(
            (ROOT / "configs/mantis-lerobot-interface-v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.task = json.loads(
            (ROOT / "configs/task-pack-v1.json").read_text(encoding="utf-8")
        )
        cls.export = json.loads(
            (ROOT / "configs/sim-episode-export-v1.json").read_text(encoding="utf-8")
        )

    def make_session(self):
        sink = FakeSink()
        session = self._build(self.export, sink=sink)
        return sink, session

    def _build(self, export, *, sink=None):
        return MantisLeRobotExportSession(
            sink=sink if sink is not None else FakeSink(),
            port=self.port,
            interface=self.interface,
            task=self.task,
            export_contract=export,
            allow_unverified_gripper=True,
        )

    def physical(self, frame: int):
        virtual = [0.01 * index for index in range(16)]
        virtual[1] = frame * 0.001
        virtual[7] = 0.5
        virtual[9] = -frame * 0.001
        virtual[15] = 0.5
        return virtual_to_physical(virtual, self.port, allow_unverified=True)

    def _physical_left_asymmetric(
        self, e_right_joint: float = 0.2, e_left_joint: float = 0.8
    ) -> list[float]:
        """Symmetric frame-0 physical whose left gripper resolves to the given estimates.

        The right gripper stays symmetric so only the left side carries the asymmetry
        under test.
        """
        physical = self.physical(0)
        order = self.port["target"]["physical_joint_order"]
        coefficients = self.port["assets"]["virtual_gripper_mapping"]["coefficients"][
            "left_gripper_joint"
        ]
        offsets = self.port["assets"]["virtual_gripper_mapping"]["offsets"][
            "left_gripper_joint"
        ]
        physical[order.index("left_clamp_right_joint")] = (
            float(offsets["left_clamp_right_joint"])
            + e_right_joint * float(coefficients["left_clamp_right_joint"])
        )
        physical[order.index("left_clamp_left_joint")] = (
            float(offsets["left_clamp_left_joint"])
            + e_left_joint * float(coefficients["left_clamp_left_joint"])
        )
        return physical

    def images(self, frame: int):
        return {
            key: FakeImage(shape, frame % 256)
            for key, shape in self.interface["camera_features"].items()
        }

    def complete_trace(self, session) -> None:
        for index, stage in enumerate(self.task["stages"]):
            details = {}
            if stage == self.task["stages"][-1]:
                details = {
                    "strict_frame_success": True,
                    "stable_frames": 12,
                    "no_safety_failure": True,
                    "no_physics_divergence": True,
                }
            session.complete_stage(stage, policy_step=index * 4, details=details)

    def add_frames(self, session, count: int = 31) -> None:
        for frame in range(count):
            physical = self.physical(frame)
            session.add_frame(
                timestamp_s=frame / 30.0,
                physical_state=physical,
                physical_action=physical,
                images=self.images(frame),
            )

    def _build_successful_trace(self, seed: int = 1) -> dict:
        """A serialized strict-success stage trace, shaped like a capture trace file."""
        events = []
        for index, stage in enumerate(self.task["stages"]):
            details = {}
            if stage == self.task["stages"][-1]:
                details = {
                    "strict_frame_success": True,
                    "stable_frames": 12,
                    "no_safety_failure": True,
                    "no_physics_divergence": True,
                }
            events.append(
                {
                    "stage": stage,
                    "status": "completed",
                    "policy_step": index * 4,
                    "details": details,
                }
            )
        return {"seed": seed, "events": events}

    def test_successful_strict_episode_is_saved_and_manifested(self) -> None:
        sink, session = self.make_session()
        session.begin_episode(seed=1)
        self.complete_trace(session)
        self.add_frames(session)
        receipt = session.finish_episode()
        result = session.finalize()
        self.assertEqual(receipt["dataset_acceptance"], "accepted")
        self.assertEqual(sink.saved, 1)
        self.assertEqual(result["accepted_episodes"], 1)
        self.assertEqual(result["episodes"][0]["frame_count"], 31)
        self.assertTrue(sink.finalized)
        self.assertNotIn("timestamp", sink.saved_frames[0])
        self.assertIsInstance(
            sink.saved_frames[0]["observation.state"], np.ndarray
        )
        self.assertEqual(
            sink.saved_frames[0]["observation.state"].dtype, np.dtype("float32")
        )
        self.assertIsInstance(sink.saved_frames[0]["action"], np.ndarray)
        self.assertEqual(
            sink.saved_frames[0]["action"].dtype, np.dtype("float32")
        )

    def test_failed_episode_is_cleared_not_saved(self) -> None:
        sink, session = self.make_session()
        session.begin_episode(seed=1)
        session.fail_stage(
            self.task["stages"][0],
            failure_stage="runtime_error",
            policy_step=0,
        )
        self.add_frames(session)
        receipt = session.finish_episode()
        self.assertEqual(receipt["dataset_acceptance"], "rejected")
        self.assertEqual(sink.saved, 0)
        self.assertEqual(sink.cleared, 1)
        with self.assertRaises(ContractError):
            session.finalize()

    def test_camera_shape_drift_is_rejected_before_sink_write(self) -> None:
        sink, session = self.make_session()
        session.begin_episode(seed=1)
        physical = self.physical(0)
        images = self.images(0)
        images["observation.images.env_cam"] = FakeImage([1, 1, 3], 0)
        with self.assertRaises(ContractError):
            session.add_frame(
                timestamp_s=0.0,
                physical_state=physical,
                physical_action=physical,
                images=images,
            )
        self.assertEqual(sink.frames, [])

    def test_small_simulated_finger_tracking_asymmetry_is_averaged(self) -> None:
        sink, session = self.make_session()
        session.begin_episode(seed=1)
        physical = self.physical(0)
        left_finger = self.port["target"]["physical_joint_order"].index(
            "left_clamp_left_joint"
        )
        physical[left_finger] += 0.00002
        session.add_frame(
            timestamp_s=0.0,
            physical_state=physical,
            physical_action=self.physical(0),
            images=self.images(0),
        )
        self.assertEqual(len(sink.frames), 1)

    def test_small_command_finger_tracking_asymmetry_is_averaged(self) -> None:
        sink, session = self.make_session()
        session.begin_episode(seed=1)
        action = self.physical(0)
        left_finger = self.port["target"]["physical_joint_order"].index(
            "left_clamp_left_joint"
        )
        action[left_finger] += 0.00002
        session.add_frame(
            timestamp_s=0.0,
            physical_state=self.physical(0),
            physical_action=action,
            images=self.images(0),
        )
        self.assertEqual(len(sink.frames), 1)

    def test_export_rejects_excessive_action_gripper_pair_tolerance(self) -> None:
        export = dict(self.export)
        export["action_gripper_pair_tolerance_normalized"] = 0.021
        with self.assertRaises(ContractError):
            self._build(export)

    def test_action_gripper_pair_tolerance_hard_cap_boundary(self) -> None:
        export = dict(self.export)
        export["action_gripper_pair_tolerance_normalized"] = 0.02
        self._build(export)  # exactly at the hard cap is accepted
        export = dict(self.export)
        export["action_gripper_pair_tolerance_normalized"] = 0.0200001
        with self.assertRaises(ContractError):
            self._build(export)

    def test_export_rejects_bad_gripper_reduction_contract_version(self) -> None:
        export = dict(self.export)
        export["gripper_reduction_contract_version"] = 3
        with self.assertRaises(ContractError):
            self._build(export)

    def test_export_rejects_bad_state_gripper_reduction_mode(self) -> None:
        export = dict(self.export)
        export["state_gripper_reduction"] = "strict_symmetric_inverse"
        with self.assertRaises(ContractError):
            self._build(export)

    def test_export_rejects_bad_action_gripper_reduction_mode(self) -> None:
        export = dict(self.export)
        export["action_gripper_reduction"] = "bounded_mean_with_residual"
        with self.assertRaises(ContractError):
            self._build(export)

    def test_export_clamps_only_bounded_gripper_range_noise(self) -> None:
        sink, session = self.make_session()
        session.begin_episode(seed=1)
        physical = virtual_to_physical(
            [0.0] * 16, self.port, allow_unverified=True
        )
        left_finger = self.port["target"]["physical_joint_order"].index(
            "left_clamp_left_joint"
        )
        coefficient = self.port["assets"]["virtual_gripper_mapping"]["coefficients"][
            "left_gripper_joint"
        ]["left_clamp_left_joint"]
        physical[left_finger] -= 0.002 * coefficient
        session.add_frame(
            timestamp_s=0.0,
            physical_state=physical,
            physical_action=self.physical(0),
            images=self.images(0),
        )
        self.assertEqual(len(sink.frames), 1)

        sink, session = self.make_session()
        session.begin_episode(seed=1)
        physical = virtual_to_physical(
            [0.0] * 16, self.port, allow_unverified=True
        )
        physical[left_finger] -= 0.008 * coefficient
        with self.assertRaises(ContractError):
            session.add_frame(
                timestamp_s=0.0,
                physical_state=physical,
                physical_action=self.physical(0),
                images=self.images(0),
            )

    def test_export_rejects_excessive_gripper_range_tolerance(self) -> None:
        export = dict(self.export)
        export["gripper_range_tolerance_normalized"] = 0.006
        with self.assertRaises(ContractError):
            MantisLeRobotExportSession(
                sink=FakeSink(),
                port=self.port,
                interface=self.interface,
                task=self.task,
                export_contract=export,
                allow_unverified_gripper=True,
            )

    def test_state_large_in_range_asymmetry_projected_and_receipt_records_it(
        self,
    ) -> None:
        sink, session = self.make_session()
        session.begin_episode(seed=1)
        self.complete_trace(session)
        # State carries a large but per-finger-in-range left-gripper asymmetry on every
        # frame; bounded projection accepts it (no pair-spread rejection) but the receipt
        # must record the residual.
        state = self._physical_left_asymmetric(0.2, 0.8)
        for frame in range(31):
            session.add_frame(
                timestamp_s=frame / 30.0,
                physical_state=state,
                physical_action=self.physical(frame),
                images=self.images(frame),
            )
        receipt = session.finish_episode()
        self.assertEqual(receipt["dataset_acceptance"], "accepted")
        diag = receipt["gripper_reduction_diagnostics"]
        self.assertEqual(diag["contract_version"], 2)
        self.assertEqual(diag["state_mode"], "bounded_mean_with_residual")
        self.assertEqual(diag["action_mode"], "strict_symmetric_inverse")
        self.assertAlmostEqual(diag["range_tolerance_normalized"], 0.003)
        self.assertAlmostEqual(diag["action_pair_tolerance_normalized"], 0.011)
        self.assertAlmostEqual(diag["state"]["left_max_spread"], 0.6, places=6)
        self.assertAlmostEqual(diag["state"]["left_max_residual"], 0.3, places=6)
        state_left = diag["state"]["per_channel"]["left_gripper_joint"]
        self.assertAlmostEqual(state_left["max_spread"], 0.6, places=6)
        self.assertAlmostEqual(state_left["max_residual"], 0.3, places=6)
        self.assertEqual(state_left["frame_index"], 0)
        self.assertEqual(
            [round(value, 6) for value in state_left["estimates"]], [0.2, 0.8]
        )
        self.assertEqual(diag["state"]["frames_above_action_tolerance"], 31)
        # Action was symmetric on every frame.
        self.assertEqual(diag["action"]["frames_above_action_tolerance"], 0)
        self.assertEqual(
            diag["action"]["per_channel"]["left_gripper_joint"]["max_spread"], 0.0
        )
        result = session.finalize()
        self.assertIn("gripper_reduction_diagnostics", result["episodes"][0])

    def test_action_large_asymmetry_rejected_with_context_and_diagnostics(
        self,
    ) -> None:
        sink, session = self.make_session()
        session.begin_episode(seed=1)
        action = self._physical_left_asymmetric(0.2, 0.8)
        with self.assertRaises(ContractError) as ctx:
            session.add_frame(
                timestamp_s=0.0,
                physical_state=self.physical(0),
                physical_action=action,
                images=self.images(0),
            )
        message = str(ctx.exception)
        self.assertIn("frame 0", message)
        self.assertIn("left_gripper_joint", message)
        self.assertIn("spread", message)
        self.assertIn("0.011", message)
        self.assertIn("estimates", message)
        # No frame reached the sink.
        self.assertEqual(sink.frames, [])
        # Diagnostics are updated before the rejection so the violation is auditable.
        receipt = session.finish_episode()
        self.assertEqual(receipt["dataset_acceptance"], "rejected")
        action_diag = receipt["gripper_reduction_diagnostics"]["action"]
        self.assertEqual(action_diag["frames_above_action_tolerance"], 1)
        self.assertAlmostEqual(
            action_diag["per_channel"]["left_gripper_joint"]["max_spread"],
            0.6,
            places=6,
        )
        self.assertEqual(
            action_diag["per_channel"]["left_gripper_joint"]["frame_index"], 0
        )

    def test_per_finger_out_of_range_state_rejected_even_when_mean_in_range(
        self,
    ) -> None:
        sink, session = self.make_session()
        session.begin_episode(seed=1)
        # Estimates 1.2 and -0.2 average to 0.5 (in range) but each finger is out of range.
        state = self._physical_left_asymmetric(1.2, -0.2)
        with self.assertRaises(ContractError):
            session.add_frame(
                timestamp_s=0.0,
                physical_state=state,
                physical_action=self.physical(0),
                images=self.images(0),
            )
        self.assertEqual(sink.frames, [])

    def test_replay_success_keeps_success_without_episode_claim(self) -> None:
        sink, session = self.make_session()
        session.begin_episode(seed=1, generation_mode="replay")
        self.complete_trace(session)
        self.add_frames(session)
        receipt = session.finish_episode()
        # Replay preserves strict success but must not advertise an episode_success_claim
        # or a G1 claim.
        self.assertTrue(receipt["success"])
        self.assertEqual(receipt["generation_mode"], "replay")
        self.assertFalse(receipt["episode_success_claim"])
        self.assertFalse(receipt["g1_claim"])
        self.assertEqual(receipt["dataset_acceptance"], "accepted")

    def test_default_generation_mode_is_online(self) -> None:
        sink, session = self.make_session()
        session.begin_episode(seed=1)
        self.complete_trace(session)
        self.add_frames(session)
        receipt = session.finish_episode()
        # Existing online callers that omit generation_mode stay accepted and claim success.
        self.assertEqual(receipt["generation_mode"], "online")
        self.assertTrue(receipt["success"])
        self.assertTrue(receipt["episode_success_claim"])
        self.assertFalse(receipt["g1_claim"])
        self.assertEqual(receipt["dataset_acceptance"], "accepted")

    def test_illegal_generation_mode_and_step_limit_rejected(self) -> None:
        sink, session = self.make_session()
        with self.assertRaises(ContractError):
            session.begin_episode(seed=1, generation_mode="bogus")
        with self.assertRaises(ContractError):
            session.begin_episode(seed=1, effective_policy_step_limit=0)

    def test_tool_threads_trace_generation_fields(self) -> None:
        # Mirror the export tool's trace-field extraction (defaults online / None / False).
        trace = self._build_successful_trace(seed=1)
        generation_mode = trace.get("generation_mode", "online")
        effective_policy_step_limit = trace.get("effective_policy_step_limit")
        g1_claim = trace.get("g1_claim", False)
        receipt = replay_stage_trace(
            self.task,
            trace,
            g1_claim=g1_claim,
            generation_mode=generation_mode,
            effective_policy_step_limit=effective_policy_step_limit,
        )
        # Default-online passthrough keeps the strict success claim.
        self.assertTrue(receipt["success"])
        self.assertEqual(receipt["generation_mode"], "online")
        self.assertTrue(receipt["episode_success_claim"])

        # Explicit replay passthrough with a non-default limit threaded end to end.
        replay_trace = self._build_successful_trace(seed=2)
        replay_trace["generation_mode"] = "replay"
        replay_trace["effective_policy_step_limit"] = self.task["max_policy_steps"]
        replay_trace["g1_claim"] = False
        replay_receipt = replay_stage_trace(
            self.task,
            replay_trace,
            g1_claim=replay_trace.get("g1_claim", False),
            generation_mode=replay_trace.get("generation_mode", "online"),
            effective_policy_step_limit=replay_trace.get("effective_policy_step_limit"),
        )
        self.assertTrue(replay_receipt["success"])
        self.assertEqual(replay_receipt["generation_mode"], "replay")
        self.assertFalse(replay_receipt["episode_success_claim"])
        self.assertFalse(replay_receipt["g1_claim"])
        self.assertEqual(
            replay_receipt["effective_policy_step_limit"],
            self.task["max_policy_steps"],
        )


if __name__ == "__main__":
    unittest.main()
