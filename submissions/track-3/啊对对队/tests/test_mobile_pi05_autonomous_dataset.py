import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from parcel_sorter.mobile_pi05_dataset import (
    MobilePI05AutonomousLeRobotWriter,
    MobilePI05AbsoluteLeRobotWriter,
    PI05AbsoluteRolloutQualification,
    PI05AutonomousAbsoluteFrame,
    PI05AutonomousResidualFrame,
    PI05AutonomousRolloutQualification,
)
from parcel_sorter.mobile_policy_attribution import (
    ABSOLUTE_VLA_AUTHORITY,
    HYBRID_VLA_AUTHORITY,
    PURE_VLA_CONTROL_CLASS,
)


class _FakeDataset:
    def __init__(self) -> None:
        self.frames = []
        self.saved = False
        self.finalized = False
        self.cleared = False

    def add_frame(self, payload) -> None:
        self.frames.append(payload)

    def save_episode(self) -> None:
        self.saved = True

    def finalize(self) -> None:
        self.finalized = True

    def clear_episode_buffer(self) -> None:
        self.frames.clear()
        self.cleared = True


def _qualification(**overrides) -> PI05AutonomousRolloutQualification:
    values = {
        "success": True,
        "policy_type": "pi05",
        "policy_mode": "pi05_residual",
        "residual_contract": True,
        "vla_routes_grasp_mode": True,
        "goal_verdict_required": True,
        "goal_arrival_verified": True,
        "policy_authority": HYBRID_VLA_AUTHORITY,
        "expert_reference_used": True,
        "expert_reference_semantics": ("deterministic_nominal_action",),
        "expert_fallback_count": 0,
        "emergency_stop_count": 0,
        "force_violation_count": 0,
        "recorded_frames": 1,
        "material_residual_frames": 1,
    }
    values.update(overrides)
    return PI05AutonomousRolloutQualification(**values)


class MobilePI05AutonomousDatasetTests(unittest.TestCase):
    def _writer(self, root: Path) -> tuple[MobilePI05AutonomousLeRobotWriter, _FakeDataset]:
        fake = _FakeDataset()

        def factory(**_kwargs):
            return fake

        return (
            MobilePI05AutonomousLeRobotWriter(root, dataset_factory=factory),
            fake,
        )

    def _add_frame(self, writer: MobilePI05AutonomousLeRobotWriter) -> None:
        state = tuple(float(index) / 100.0 for index in range(80))
        action = (0.001,) + tuple(float(index) / 1000.0 for index in range(1, 14))
        writer.add_frame(
            PI05AutonomousResidualFrame(
                frame_index=0,
                timestamp_seconds=0.0,
                stage="pregrasp",
                state=state,
                raw_residual_action=action,
                privileged_state=(0.0,) * 7,
                task="pick and place the parcel",
                inference_performed=True,
                inference_call_index=0,
                chunk_step_index=0,
                rgb=np.zeros((224, 224, 3), dtype=np.uint8),
                depth=np.ones((224, 224), dtype=np.float32),
            )
        )

    def _provenance(self, root: Path) -> tuple[Path, Path]:
        checkpoint = root / "checkpoint"
        checkpoint.mkdir()
        (checkpoint / "adapter_model.safetensors").write_bytes(b"adapter")
        summary = root / "summary.json"
        summary.write_text('{"success": true}', encoding="utf-8")
        return checkpoint, summary

    def test_failed_rollout_cannot_finalize_or_leave_bc_frames(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            writer, fake = self._writer(root / "dataset")
            self._add_frame(writer)
            checkpoint, summary = self._provenance(root)
            manifest = writer.commit_or_reject(
                _qualification(success=False),
                checkpoint=checkpoint,
                training_contract_sha256="contract",
                chunk_execution_protocol="first-action-hold-v1",
                source_summary=summary,
            )
            self.assertFalse(manifest["accepted_for_behavior_cloning"])
            self.assertIn("task_failed", manifest["rejection_reasons"])
            self.assertTrue(fake.cleared)
            self.assertFalse(fake.saved)
            self.assertFalse(fake.finalized)
            self.assertEqual(fake.frames, [])

    def test_expert_fallback_rollout_cannot_finalize(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            writer, fake = self._writer(root / "dataset")
            self._add_frame(writer)
            checkpoint, summary = self._provenance(root)
            manifest = writer.commit_or_reject(
                _qualification(expert_fallback_count=1),
                checkpoint=checkpoint,
                training_contract_sha256="contract",
                chunk_execution_protocol="first-action-hold-v1",
                source_summary=summary,
            )
            self.assertFalse(manifest["accepted_for_behavior_cloning"])
            self.assertIn("expert_fallback_used", manifest["rejection_reasons"])
            self.assertTrue(fake.cleared)
            self.assertFalse(fake.saved)

    def test_verified_rollout_preserves_exact_contract_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            writer, fake = self._writer(root / "dataset")
            self._add_frame(writer)
            checkpoint, summary = self._provenance(root)
            manifest = writer.commit_or_reject(
                _qualification(),
                checkpoint=checkpoint,
                training_contract_sha256="contract-sha",
                chunk_execution_protocol="pi05-open-loop-queue-v1",
                source_summary=summary,
            )
            self.assertTrue(manifest["accepted_for_behavior_cloning"])
            self.assertFalse(manifest["accepted_as_pure_vla_experience"])
            self.assertEqual(manifest["replay_authority_scope"], HYBRID_VLA_AUTHORITY)
            self.assertTrue(fake.saved)
            self.assertTrue(fake.finalized)
            np.testing.assert_array_equal(
                fake.frames[0]["observation.state"],
                np.asarray(
                    [float(index) / 100.0 for index in range(80)], dtype=np.float32
                ),
            )
            expected_action = [0.001] + [float(index) / 1000.0 for index in range(1, 14)]
            np.testing.assert_array_equal(
                fake.frames[0]["action"],
                np.asarray(expected_action, dtype=np.float32),
            )
            self.assertEqual(manifest["training_contract_sha256"], "contract-sha")
            self.assertEqual(
                manifest["checkpoint_artifact_sha256"],
                hashlib.sha256(b"adapter").hexdigest(),
            )
            self.assertEqual(
                manifest["source_summary_sha256"],
                hashlib.sha256(summary.read_bytes()).hexdigest(),
            )
            saved_manifest = json.loads(
                (root / "dataset" / "PI05_AUTONOMOUS_REPLAY_MANIFEST.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(saved_manifest["failed_attempts_are_bc_labels"])

    def test_residual_contract_cannot_be_relabelled_as_pure_absolute_vla(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            writer, _ = self._writer(root / "dataset")
            self._add_frame(writer)
            checkpoint, summary = self._provenance(root)

            manifest = writer.commit_or_reject(
                _qualification(
                    policy_authority=ABSOLUTE_VLA_AUTHORITY,
                    expert_reference_used=False,
                    expert_reference_semantics=(),
                ),
                checkpoint=checkpoint,
                training_contract_sha256="contract",
                chunk_execution_protocol="first-action-hold-v1",
                source_summary=summary,
            )

            self.assertFalse(manifest["accepted_as_pure_vla_experience"])
            self.assertFalse(manifest["accepted_for_behavior_cloning"])
            self.assertIn(
                "residual_policy_authority_is_not_hybrid",
                manifest["rejection_reasons"],
            )

    def test_unknown_authority_rollout_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            writer, fake = self._writer(root / "dataset")
            self._add_frame(writer)
            checkpoint, summary = self._provenance(root)

            manifest = writer.commit_or_reject(
                _qualification(policy_authority="unknown"),
                checkpoint=checkpoint,
                training_contract_sha256="contract",
                chunk_execution_protocol="first-action-hold-v1",
                source_summary=summary,
            )

            self.assertFalse(manifest["accepted_for_behavior_cloning"])
            self.assertIn(
                "residual_policy_authority_is_not_hybrid",
                manifest["rejection_reasons"],
            )
            self.assertTrue(fake.cleared)

    def test_wrist_replay_writer_requires_and_saves_wrist_rgbd(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            captured = {}
            fake = _FakeDataset()

            def factory(**kwargs):
                captured.update(kwargs)
                return fake

            writer = MobilePI05AutonomousLeRobotWriter(
                Path(directory),
                dataset_factory=factory,
                include_wrist_rgbd=True,
                image_size=(8, 8),
            )
            frame = PI05AutonomousResidualFrame(
                frame_index=0,
                timestamp_seconds=0.0,
                stage="pregrasp",
                state=(0.0,) * 80,
                raw_residual_action=(0.001,) + (0.0,) * 13,
                privileged_state=(0.0,) * 7,
                task="task",
                inference_performed=True,
                inference_call_index=0,
                chunk_step_index=0,
                rgb=np.zeros((8, 8, 3), dtype=np.uint8),
                depth=np.ones((8, 8), dtype=np.float32),
                wrist_rgb=np.zeros((8, 8, 3), dtype=np.uint8),
                wrist_depth=np.ones((8, 8), dtype=np.float32),
            )

            writer.add_frame(frame)

            self.assertIn("observation.images.left_wrist_rgb", captured["features"])
            self.assertIn(
                "observation.images.left_wrist_depth_rgb", fake.frames[0]
            )

    def test_absolute_writer_admits_only_full_authority_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = _FakeDataset()
            captured = {}

            def factory(**kwargs):
                captured.update(kwargs)
                return fake

            writer = MobilePI05AbsoluteLeRobotWriter(
                root / "dataset", dataset_factory=factory, image_size=(8, 8)
            )
            state = [0.0] * 80
            state[24:27] = [0.4, 0.1, 0.3]
            state[31:34] = [0.4, -0.1, 0.3]
            state[74:77] = state[24:27]
            state[77:80] = state[31:34]
            action = [0.03, 0.0, 0.0]
            action.extend([0.42, 0.1, 0.3, 1.0, 0.0, 0.0, 0.0, 1.0])
            action.extend([0.42, -0.1, 0.3, 1.0, 0.0, 0.0, 0.0, 1.0])
            action.extend([1.0, -1.0, -1.0, 0.5])
            writer.add_frame(
                PI05AutonomousAbsoluteFrame(
                    frame_index=0,
                    timestamp_seconds=0.0,
                    stage="transport",
                    state=tuple(state),
                    absolute_action_target=tuple(action),
                    privileged_state=(0.0,) * 7,
                    task="Pick up the parcel and place it safely.",
                    inference_performed=True,
                    inference_call_index=0,
                    chunk_step_index=0,
                    rgb=np.zeros((8, 8, 3), dtype=np.uint8),
                    depth=np.ones((8, 8), dtype=np.float32),
                )
            )
            checkpoint, summary = self._provenance(root)
            qualification = PI05AbsoluteRolloutQualification(
                success=True,
                policy_type="pi05",
                policy_mode="pi05_absolute",
                absolute_contract=True,
                grasp_mode="top_suction",
                vla_routes_grasp_mode=True,
                goal_verdict_required=True,
                goal_arrival_verified=True,
                policy_authority=ABSOLUTE_VLA_AUTHORITY,
                system_control_class=PURE_VLA_CONTROL_CLASS,
                task_action_correction_count=0,
                expert_reference_used=False,
                expert_reference_semantics=(),
                expert_fallback_count=0,
                emergency_stop_count=0,
                force_violation_count=0,
                minimum_selected_scale=1.0,
                transport_deadline_handoff=False,
                recorded_frames=1,
                material_action_frames=1,
                nonzero_base_command_frames=1,
            )
            manifest = writer.commit_or_reject(
                qualification,
                checkpoint=checkpoint,
                training_contract_sha256="contract",
                chunk_execution_protocol="first-action-hold-v1",
                source_summary=summary,
            )

            self.assertTrue(manifest["accepted_as_pure_vla_experience"])
            self.assertTrue(fake.saved)
            self.assertEqual(captured["features"]["action"]["shape"], (23,))
            training_manifest = json.loads(
                (root / "dataset" / "PI05_ABSOLUTE_DATASET_MANIFEST.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(training_manifest["expert_reference_used"])
            self.assertEqual(training_manifest["nonzero_base_command_frames"], 1)

    def test_absolute_writer_rejects_safety_blended_rollout(self) -> None:
        qualification = PI05AbsoluteRolloutQualification(
            success=True,
            policy_type="pi05",
            policy_mode="pi05_absolute",
            absolute_contract=True,
            grasp_mode="side_suction",
            vla_routes_grasp_mode=True,
            goal_verdict_required=True,
            goal_arrival_verified=True,
            policy_authority=ABSOLUTE_VLA_AUTHORITY,
            system_control_class=PURE_VLA_CONTROL_CLASS,
            task_action_correction_count=0,
            expert_reference_used=False,
            expert_reference_semantics=(),
            expert_fallback_count=0,
            emergency_stop_count=0,
            force_violation_count=0,
            minimum_selected_scale=0.75,
            transport_deadline_handoff=False,
            recorded_frames=1,
            material_action_frames=1,
            nonzero_base_command_frames=1,
        )
        self.assertIn(
            "absolute_vla_not_full_authority", qualification.rejection_reasons()
        )

    def test_absolute_writer_rejects_external_stage_machine_as_pure_vla(self) -> None:
        qualification = PI05AbsoluteRolloutQualification(
            success=True,
            policy_type="pi05",
            policy_mode="pi05_absolute",
            absolute_contract=True,
            grasp_mode="top_suction",
            vla_routes_grasp_mode=True,
            goal_verdict_required=True,
            goal_arrival_verified=True,
            policy_authority=ABSOLUTE_VLA_AUTHORITY,
            system_control_class="shielded_vla",
            task_action_correction_count=1,
            expert_reference_used=False,
            expert_reference_semantics=(),
            expert_fallback_count=0,
            emergency_stop_count=0,
            force_violation_count=0,
            minimum_selected_scale=1.0,
            transport_deadline_handoff=False,
            recorded_frames=1,
            material_action_frames=1,
            nonzero_base_command_frames=1,
        )
        reasons = qualification.rejection_reasons()
        self.assertIn("system_control_is_not_pure_vla", reasons)
        self.assertIn("task_action_correction_used", reasons)


if __name__ == "__main__":
    unittest.main()
