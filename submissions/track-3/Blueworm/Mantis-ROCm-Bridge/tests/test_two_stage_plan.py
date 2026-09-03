"""Pure-Python tests for two-stage plan construction and validation.

These tests are dependency-free (no numpy) and can run in environments
without Genesis or ROCm. They validate schema, invariants, hash matching,
and deterministic plan behavior.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mantis_rocm_bridge.two_stage_plan import (
    ReplayPlan,
    ReplayPlanStep,
    sha256_file,
    validate_candidate_tuple,
    validate_finite_offset,
    validate_ordered_poses,
    plan_needs_reprobe,
)
from mantis_rocm_bridge.candidate_isolation import CANDIDATE_ISOLATION_VERSION


class TestReplayPlanStepValidation(unittest.TestCase):
    """Test ReplayPlanStep frozen dataclass validation."""

    def test_valid_right_step(self) -> None:
        """A valid right-side step constructs successfully."""
        step = ReplayPlanStep(
            level=0,
            bowl="bowl1",
            assigned_side="right",
            source_position_xyz_m=(0.1, 0.2, 0.74),
            right_grasp_candidate_index=0,
            right_grasp_candidate_tuple=(0.0, -0.03, 0.70),
            place_xy_offset_m=(0.001, -0.002),
            dual_clamp_required=True,
            probe_placement_position_xyz_m=(0.001, 0.0, 0.74),
            probe_placement_gate_pass=True,
        )
        self.assertEqual(step.level, 0)
        self.assertEqual(step.assigned_side, "right")
        self.assertEqual(step.right_grasp_candidate_index, 0)

    def test_valid_left_step(self) -> None:
        """A valid left-side step constructs successfully."""
        step = ReplayPlanStep(
            level=1,
            bowl="bowl2",
            assigned_side="left",
            source_position_xyz_m=(-0.1, 0.2, 0.74),
            right_grasp_candidate_index=None,
            right_grasp_candidate_tuple=None,
            place_xy_offset_m=(0.0, 0.0),
            dual_clamp_required=False,
            probe_placement_position_xyz_m=(0.0, -0.1, 0.77),
            probe_placement_gate_pass=True,
        )
        self.assertEqual(step.level, 1)
        self.assertEqual(step.assigned_side, "left")
        self.assertIsNone(step.right_grasp_candidate_index)

    def test_invalid_level_rejected(self) -> None:
        """Negative or non-integer levels are rejected."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlanStep(
                level=-1,
                bowl="bowl1",
                assigned_side="right",
                source_position_xyz_m=(0.1, 0.2, 0.74),
                right_grasp_candidate_index=0,
                right_grasp_candidate_tuple=(0.0, -0.03, 0.70),
                place_xy_offset_m=(0.0, 0.0),
                dual_clamp_required=True,
                probe_placement_position_xyz_m=(0.0, 0.0, 0.74),
                probe_placement_gate_pass=True,
            )
        self.assertIn("level must be non-negative", str(cm.exception))

    def test_invalid_side_rejected(self) -> None:
        """Sides other than 'left' or 'right' are rejected."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlanStep(
                level=0,
                bowl="bowl1",
                assigned_side="middle",  # Invalid
                source_position_xyz_m=(0.1, 0.2, 0.74),
                right_grasp_candidate_index=None,
                right_grasp_candidate_tuple=None,
                place_xy_offset_m=(0.0, 0.0),
                dual_clamp_required=False,
                probe_placement_position_xyz_m=(0.0, 0.0, 0.74),
                probe_placement_gate_pass=True,
            )
        self.assertIn("assigned_side must be 'left' or 'right'", str(cm.exception))

    def test_right_step_requires_candidate_fields(self) -> None:
        """Right-side steps must have candidate fields."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlanStep(
                level=0,
                bowl="bowl1",
                assigned_side="right",
                source_position_xyz_m=(0.1, 0.2, 0.74),
                right_grasp_candidate_index=None,  # Missing for right
                right_grasp_candidate_tuple=None,
                place_xy_offset_m=(0.0, 0.0),
                dual_clamp_required=True,
                probe_placement_position_xyz_m=(0.0, 0.0, 0.74),
                probe_placement_gate_pass=True,
            )
        self.assertIn("right_grasp_candidate_index required for right side", str(cm.exception))

    def test_left_step_forbids_candidate_fields(self) -> None:
        """Left-side steps must not have candidate fields."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlanStep(
                level=0,
                bowl="bowl1",
                assigned_side="left",
                source_position_xyz_m=(0.1, 0.2, 0.74),
                right_grasp_candidate_index=0,  # Should be None for left
                right_grasp_candidate_tuple=(0.0, -0.03, 0.70),
                place_xy_offset_m=(0.0, 0.0),
                dual_clamp_required=False,
                probe_placement_position_xyz_m=(0.0, 0.0, 0.74),
                probe_placement_gate_pass=True,
            )
        self.assertIn("right_grasp_candidate_index must be None for left side", str(cm.exception))

    def test_offset_exceeding_max_rejected(self) -> None:
        """Offsets exceeding 0.15 m are rejected."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlanStep(
                level=0,
                bowl="bowl1",
                assigned_side="right",
                source_position_xyz_m=(0.1, 0.2, 0.74),
                right_grasp_candidate_index=0,
                right_grasp_candidate_tuple=(0.0, -0.03, 0.70),
                place_xy_offset_m=(0.2, 0.0),  # Exceeds 0.15
                dual_clamp_required=True,
                probe_placement_position_xyz_m=(0.0, 0.0, 0.74),
                probe_placement_gate_pass=True,
            )
        self.assertIn("must be <= 0.15 m", str(cm.exception))

    def test_invalid_position_tuple_rejected(self) -> None:
        """Position tuples must be 3-element sequences of finite numbers."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlanStep(
                level=0,
                bowl="bowl1",
                assigned_side="right",
                source_position_xyz_m=(0.1, 0.2),  # Only 2 elements
                right_grasp_candidate_index=0,
                right_grasp_candidate_tuple=(0.0, -0.03, 0.70),
                place_xy_offset_m=(0.0, 0.0),
                dual_clamp_required=True,
                probe_placement_position_xyz_m=(0.0, 0.0, 0.74),
                probe_placement_gate_pass=True,
            )
        self.assertIn("must be 3-element sequence", str(cm.exception))

    def test_blank_bowl_name_rejected(self) -> None:
        """Blank bowl names are rejected."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlanStep(
                level=0,
                bowl="",  # Blank
                assigned_side="right",
                source_position_xyz_m=(0.1, 0.2, 0.74),
                right_grasp_candidate_index=0,
                right_grasp_candidate_tuple=(0.0, -0.03, 0.70),
                place_xy_offset_m=(0.0, 0.0),
                dual_clamp_required=True,
                probe_placement_position_xyz_m=(0.0, 0.0, 0.74),
                probe_placement_gate_pass=True,
            )
        self.assertIn("bowl must be non-blank", str(cm.exception))

    def test_whitespace_bowl_name_rejected(self) -> None:
        """Whitespace-only bowl names are rejected."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlanStep(
                level=0,
                bowl="   ",  # Whitespace only
                assigned_side="right",
                source_position_xyz_m=(0.1, 0.2, 0.74),
                right_grasp_candidate_index=0,
                right_grasp_candidate_tuple=(0.0, -0.03, 0.70),
                place_xy_offset_m=(0.0, 0.0),
                dual_clamp_required=True,
                probe_placement_position_xyz_m=(0.0, 0.0, 0.74),
                probe_placement_gate_pass=True,
            )
        self.assertIn("bowl must be non-blank", str(cm.exception))

    def test_invalid_bool_type_rejected(self) -> None:
        """Non-boolean bool fields are rejected."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlanStep(
                level=0,
                bowl="bowl1",
                assigned_side="right",
                source_position_xyz_m=(0.1, 0.2, 0.74),
                right_grasp_candidate_index=0,
                right_grasp_candidate_tuple=(0.0, -0.03, 0.70),
                place_xy_offset_m=(0.0, 0.0),
                dual_clamp_required="yes",  # Should be bool
                probe_placement_position_xyz_m=(0.0, 0.0, 0.74),
                probe_placement_gate_pass=True,
            )
        self.assertIn("dual_clamp_required must be bool", str(cm.exception))

    def test_right_side_requires_dual_clamp(self) -> None:
        """Right-side steps require dual_clamp_required=True."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlanStep(
                level=0,
                bowl="bowl1",
                assigned_side="right",
                source_position_xyz_m=(0.1, 0.2, 0.74),
                right_grasp_candidate_index=0,
                right_grasp_candidate_tuple=(0.0, -0.03, 0.70),
                place_xy_offset_m=(0.0, 0.0),
                dual_clamp_required=False,  # Should be True for right
                probe_placement_position_xyz_m=(0.0, 0.0, 0.74),
                probe_placement_gate_pass=True,
            )
        self.assertIn("right side must have dual_clamp_required=True", str(cm.exception))

    def test_left_side_zero_offset_required(self) -> None:
        """Left-side steps require zero offset."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlanStep(
                level=0,
                bowl="bowl1",
                assigned_side="left",
                source_position_xyz_m=(0.1, 0.2, 0.74),
                right_grasp_candidate_index=None,
                right_grasp_candidate_tuple=None,
                place_xy_offset_m=(0.001, 0.0),  # Should be (0.0, 0.0)
                dual_clamp_required=False,
                probe_placement_position_xyz_m=(0.0, 0.0, 0.74),
                probe_placement_gate_pass=True,
            )
        self.assertIn("left side must have zero offset", str(cm.exception))

    def test_gate_pass_true_required(self) -> None:
        """probe_placement_gate_pass must be True."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlanStep(
                level=0,
                bowl="bowl1",
                assigned_side="right",
                source_position_xyz_m=(0.1, 0.2, 0.74),
                right_grasp_candidate_index=0,
                right_grasp_candidate_tuple=(0.0, -0.03, 0.70),
                place_xy_offset_m=(0.0, 0.0),
                dual_clamp_required=True,
                probe_placement_position_xyz_m=(0.0, 0.0, 0.74),
                probe_placement_gate_pass=False,  # Should be True
            )
        self.assertIn("probe_placement_gate_pass must be True", str(cm.exception))


class TestReplayPlanValidation(unittest.TestCase):
    """Test ReplayPlan validation and invariants."""

    def setUp(self) -> None:
        """Create valid plan data for tests."""
        self.valid_hashes = {
            "task": "a" * 64,
            "scene": "b" * 64,
            "camera": "c" * 64,
            "port": "d" * 64,
            "mantis_urdf": "e" * 64,
            "bowl_urdf": "f" * 64,
        }
        self.valid_poses = [
            {
                "name": "bowl1",
                "position_xyz_m": [0.1, 0.2, 0.74],
                "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            },
            {
                "name": "bowl2",
                "position_xyz_m": [-0.1, 0.3, 0.74],
                "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            },
            {
                "name": "bowl3",
                "position_xyz_m": [0.0, 0.4, 0.74],
                "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            },
        ]
        self.valid_steps = (
            ReplayPlanStep(
                level=0,
                bowl="bowl1",
                assigned_side="right",
                source_position_xyz_m=(0.1, 0.2, 0.74),
                right_grasp_candidate_index=0,
                right_grasp_candidate_tuple=(0.0, -0.03, 0.70),
                place_xy_offset_m=(0.001, -0.002),
                dual_clamp_required=True,
                probe_placement_position_xyz_m=(0.001, 0.0, 0.74),
                probe_placement_gate_pass=True,
            ),
            ReplayPlanStep(
                level=1,
                bowl="bowl2",
                assigned_side="left",
                source_position_xyz_m=(-0.1, 0.3, 0.74),
                right_grasp_candidate_index=None,
                right_grasp_candidate_tuple=None,
                place_xy_offset_m=(0.0, 0.0),
                dual_clamp_required=False,
                probe_placement_position_xyz_m=(0.0, -0.1, 0.77),
                probe_placement_gate_pass=True,
            ),
            ReplayPlanStep(
                level=2,
                bowl="bowl3",
                assigned_side="right",
                source_position_xyz_m=(0.0, 0.4, 0.74),
                right_grasp_candidate_index=1,
                right_grasp_candidate_tuple=(0.0, -0.025, 0.68),
                place_xy_offset_m=(-0.001, 0.001),
                dual_clamp_required=True,
                probe_placement_position_xyz_m=(-0.001, -0.1, 0.80),
                probe_placement_gate_pass=True,
            ),
        )

    def test_valid_plan_constructs(self) -> None:
        """A valid plan constructs successfully."""
        plan = ReplayPlan(
            schema_version=1,
            seed=1001,
            task_id="test_task",
            probe_source_run_id="test_run_001",
            hashes=self.valid_hashes,
            reset_bowl_poses=self.valid_poses,
            steps=self.valid_steps,
            diagnostic_only_claim_boundary="Diagnostic-only probe plan for seed 1001; does not prove episode/G1/learned/multi-seed/ROCm claims.",
        )
        self.assertEqual(plan.schema_version, 1)
        self.assertEqual(plan.seed, 1001)
        self.assertEqual(len(plan.steps), 3)

    def test_invalid_schema_version_rejected(self) -> None:
        """Schema version must be 1."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlan(
                schema_version=2,  # Invalid
                seed=1001,
                task_id="test_task",
                probe_source_run_id="test_run_001",
                hashes=self.valid_hashes,
                reset_bowl_poses=self.valid_poses,
                steps=self.valid_steps,
                diagnostic_only_claim_boundary="Schema version 2 test",
            )
        self.assertIn("schema_version must be 1", str(cm.exception))

    def test_invalid_seed_rejected(self) -> None:
        """Seed must be positive integer."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlan(
                schema_version=1,
                seed=0,  # Invalid
                task_id="test_task",
                probe_source_run_id="test_run_001",
                hashes=self.valid_hashes,
                reset_bowl_poses=self.valid_poses,
                steps=self.valid_steps,
                diagnostic_only_claim_boundary="Invalid seed test",
            )
        self.assertIn("seed must be positive integer", str(cm.exception))

    def test_missing_required_hash_rejected(self) -> None:
        """All required hashes must be present."""
        invalid_hashes = self.valid_hashes.copy()
        del invalid_hashes["task"]
        with self.assertRaises(ValueError) as cm:
            ReplayPlan(
                schema_version=1,
                seed=1001,
                task_id="test_task",
                probe_source_run_id="test_run_001",
                hashes=invalid_hashes,
                reset_bowl_poses=self.valid_poses,
                steps=self.valid_steps,
                diagnostic_only_claim_boundary="Missing hash test",
            )
        self.assertIn("missing required key: task", str(cm.exception))

    def test_invalid_hash_length_rejected(self) -> None:
        """Hashes must be 64-character hex strings."""
        invalid_hashes = self.valid_hashes.copy()
        invalid_hashes["task"] = "short"
        with self.assertRaises(ValueError) as cm:
            ReplayPlan(
                schema_version=1,
                seed=1001,
                task_id="test_task",
                probe_source_run_id="test_run_001",
                hashes=invalid_hashes,
                reset_bowl_poses=self.valid_poses,
                steps=self.valid_steps,
                diagnostic_only_claim_boundary="Invalid hash length test",
            )
        self.assertIn("must be 64-character hex string", str(cm.exception))

    def test_invalid_hash_hex_rejected(self) -> None:
        """Hashes must be valid hex strings."""
        invalid_hashes = self.valid_hashes.copy()
        invalid_hashes["task"] = "x" * 64  # 'x' is not valid hex
        with self.assertRaises(ValueError) as cm:
            ReplayPlan(
                schema_version=1,
                seed=1001,
                task_id="test_task",
                probe_source_run_id="test_run_001",
                hashes=invalid_hashes,
                reset_bowl_poses=self.valid_poses,
                steps=self.valid_steps,
                diagnostic_only_claim_boundary="Invalid hex test",
            )
        self.assertIn("must be valid hex string", str(cm.exception))

    def test_wrong_pose_count_rejected(self) -> None:
        """Exactly 3 bowl poses must be provided."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlan(
                schema_version=1,
                seed=1001,
                task_id="test_task",
                probe_source_run_id="test_run_001",
                hashes=self.valid_hashes,
                reset_bowl_poses=self.valid_poses[:2],  # Only 2
                steps=self.valid_steps,
                diagnostic_only_claim_boundary="Wrong pose count test",
            )
        self.assertIn("must have exactly 3 entries", str(cm.exception))

    def test_wrong_step_count_rejected(self) -> None:
        """Exactly 3 steps must be provided."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlan(
                schema_version=1,
                seed=1001,
                task_id="test_task",
                probe_source_run_id="test_run_001",
                hashes=self.valid_hashes,
                reset_bowl_poses=self.valid_poses,
                steps=self.valid_steps[:2],  # Only 2
                diagnostic_only_claim_boundary="Wrong step count test",
            )
        self.assertIn("must have exactly 3 entries", str(cm.exception))

    def test_step_level_mismatch_rejected(self) -> None:
        """Step levels must match their index."""
        invalid_steps = list(self.valid_steps)
        invalid_steps[0] = ReplayPlanStep(
            level=1,  # Should be 0
            bowl="bowl1",
            assigned_side="right",
            source_position_xyz_m=(0.1, 0.2, 0.74),
            right_grasp_candidate_index=0,
            right_grasp_candidate_tuple=(0.0, -0.03, 0.70),
            place_xy_offset_m=(0.0, 0.0),
            dual_clamp_required=True,
            probe_placement_position_xyz_m=(0.0, 0.0, 0.74),
            probe_placement_gate_pass=True,
        )
        with self.assertRaises(ValueError) as cm:
            ReplayPlan(
                schema_version=1,
                seed=1001,
                task_id="test_task",
                probe_source_run_id="test_run_001",
                hashes=self.valid_hashes,
                reset_bowl_poses=self.valid_poses,
                steps=tuple(invalid_steps),
                diagnostic_only_claim_boundary="Level mismatch test",
            )
        self.assertIn("level must be 0", str(cm.exception))

    def test_nonzero_claim_booleans_rejected(self) -> None:
        """All claim booleans must be False for probe plans."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlan(
                schema_version=1,
                seed=1001,
                task_id="test_task",
                probe_source_run_id="test_run_001",
                hashes=self.valid_hashes,
                reset_bowl_poses=self.valid_poses,
                steps=self.valid_steps,
                probe_plan_pass=True,  # Should be False
                diagnostic_only_claim_boundary="Nonzero claim boolean test",
            )
        self.assertIn("All claim booleans must be False", str(cm.exception))

    def test_to_dict_roundtrip(self) -> None:
        """Plan serializes to dict and back identically."""
        plan = ReplayPlan(
            schema_version=1,
            seed=1001,
            task_id="test_task",
            probe_source_run_id="test_run_001",
            hashes=self.valid_hashes,
            reset_bowl_poses=self.valid_poses,
            steps=self.valid_steps,
            diagnostic_only_claim_boundary="Diagnostic-only probe plan roundtrip test; does not prove episode/G1/learned/multi-seed/ROCm claims.",
        )
        plan_dict = plan.to_dict()
        restored = ReplayPlan.from_dict(plan_dict)
        self.assertEqual(restored.schema_version, plan.schema_version)
        self.assertEqual(restored.seed, plan.seed)
        self.assertEqual(restored.task_id, plan.task_id)
        self.assertEqual(len(restored.steps), len(plan.steps))

    def test_write_atomic_fails_if_exists(self) -> None:
        """Atomic write fails if file already exists."""
        plan = ReplayPlan(
            schema_version=1,
            seed=1001,
            task_id="test_task",
            probe_source_run_id="test_run_001",
            hashes=self.valid_hashes,
            reset_bowl_poses=self.valid_poses,
            steps=self.valid_steps,
            diagnostic_only_claim_boundary="Atomic write test; does not prove episode/G1/learned/multi-seed/ROCm claims.",
        )
        # Create temp file path without creating the file
        tmp_dir = Path(tempfile.gettempdir())
        tmp_path = tmp_dir / f"test_plan_{id(plan)}.json"
        try:
            # First write succeeds
            plan.write_atomic(tmp_path)
            # Verify file was created
            self.assertTrue(tmp_path.exists())
            # Second write fails
            with self.assertRaises(RuntimeError) as cm:
                plan.write_atomic(tmp_path)
            self.assertIn("already exists", str(cm.exception))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_write_atomic_creates_valid_file(self) -> None:
        """Atomic write creates a valid, readable JSON file."""
        plan = ReplayPlan(
            schema_version=1,
            seed=1001,
            task_id="test_task",
            probe_source_run_id="test_run_001",
            hashes=self.valid_hashes,
            reset_bowl_poses=self.valid_poses,
            steps=self.valid_steps,
            diagnostic_only_claim_boundary="Valid file test; does not prove episode/G1/learned/multi-seed/ROCm claims.",
        )
        tmp_dir = Path(tempfile.gettempdir())
        tmp_path = tmp_dir / f"test_plan_{id(plan)}.json"
        try:
            plan.write_atomic(tmp_path)
            # Verify file can be read back
            restored = ReplayPlan.read(tmp_path)
            self.assertEqual(restored.seed, plan.seed)
            self.assertEqual(len(restored.steps), len(plan.steps))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_write_atomic_no_overwrite_on_race(self) -> None:
        """Atomic write refuses to overwrite even if file appears racefully."""
        plan = ReplayPlan(
            schema_version=1,
            seed=1001,
            task_id="test_task",
            probe_source_run_id="test_run_001",
            hashes=self.valid_hashes,
            reset_bowl_poses=self.valid_poses,
            steps=self.valid_steps,
            diagnostic_only_claim_boundary="No overwrite race test; does not prove episode/G1/learned/multi-seed/ROCm claims.",
        )
        tmp_dir = Path(tempfile.gettempdir())
        tmp_path = tmp_dir / f"test_plan_race_{id(plan)}.json"

        # Create a file with different content
        tmp_path.write_text('{"different": "content"}')

        try:
            with self.assertRaises(RuntimeError) as cm:
                plan.write_atomic(tmp_path)
            self.assertIn("refusing to overwrite", str(cm.exception))
            # Verify original content was preserved
            original_content = tmp_path.read_text()
            self.assertIn("different", original_content)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_read_validates_plan(self) -> None:
        """Reading plan from file validates all invariants."""
        plan = ReplayPlan(
            schema_version=1,
            seed=1001,
            task_id="test_task",
            probe_source_run_id="test_run_001",
            hashes=self.valid_hashes,
            reset_bowl_poses=self.valid_poses,
            steps=self.valid_steps,
            diagnostic_only_claim_boundary="Read validates test; does not prove episode/G1/learned/multi-seed/ROCm claims.",
        )
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as tmp:
            tmp_path = Path(tmp.name)
            json.dump(plan.to_dict(), tmp)
        try:
            # Reading valid plan succeeds
            restored = ReplayPlan.read(tmp_path)
            self.assertEqual(restored.seed, plan.seed)
        finally:
            tmp_path.unlink()

    def test_steps_bowl_name_mismatch_rejected(self) -> None:
        """Step bowl names must match reset pose bowl names."""
        invalid_poses = [
            {
                "name": "wrong_bowl",  # Mismatch
                "position_xyz_m": [0.1, 0.2, 0.74],
                "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            },
            {
                "name": "bowl2",
                "position_xyz_m": [-0.1, 0.3, 0.74],
                "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            },
            {
                "name": "bowl3",
                "position_xyz_m": [0.0, 0.4, 0.74],
                "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            },
        ]
        with self.assertRaises(ValueError) as cm:
            ReplayPlan(
                schema_version=1,
                seed=1001,
                task_id="test_task",
                probe_source_run_id="test_run_001",
                hashes=self.valid_hashes,
                reset_bowl_poses=invalid_poses,
                steps=self.valid_steps,
                diagnostic_only_claim_boundary="Bowl name mismatch test",
            )
        self.assertIn("bowl", str(cm.exception).lower())
        self.assertIn("does not match", str(cm.exception).lower())

    def test_steps_source_position_mismatch_rejected(self) -> None:
        """Step source positions must match reset pose positions."""
        invalid_poses = [
            {
                "name": "bowl1",
                "position_xyz_m": [0.999, 0.2, 0.74],  # X differs significantly
                "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            },
            {
                "name": "bowl2",
                "position_xyz_m": [-0.1, 0.3, 0.74],
                "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            },
            {
                "name": "bowl3",
                "position_xyz_m": [0.0, 0.4, 0.74],
                "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            },
        ]
        with self.assertRaises(ValueError) as cm:
            ReplayPlan(
                schema_version=1,
                seed=1001,
                task_id="test_task",
                probe_source_run_id="test_run_001",
                hashes=self.valid_hashes,
                reset_bowl_poses=invalid_poses,
                steps=self.valid_steps,
                diagnostic_only_claim_boundary="Source position mismatch test",
            )
        self.assertIn("source_position", str(cm.exception).lower())

    def test_exact_bool_types_validated(self) -> None:
        """Claim boolean fields must be exact bool type, not truthy values."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlan(
                schema_version=1,
                seed=1001,
                task_id="test_task",
                probe_source_run_id="test_run_001",
                hashes=self.valid_hashes,
                reset_bowl_poses=self.valid_poses,
                steps=self.valid_steps,
                probe_plan_pass=1,  # int, not bool
                diagnostic_only_claim_boundary="Exact bool types test",
            )
        self.assertIn("must be bool", str(cm.exception))

    def test_seed_1_rejected_for_probe(self) -> None:
        """Seed 1 is rejected for probe plans (reserved for canonical G1)."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlan(
                schema_version=1,
                seed=1,  # Invalid for probe
                task_id="test_task",
                probe_source_run_id="test_run_001",
                hashes=self.valid_hashes,
                reset_bowl_poses=self.valid_poses,
                steps=self.valid_steps,
                diagnostic_only_claim_boundary="Seed 1 rejection test",
            )
        self.assertIn("seed must not be 1", str(cm.exception))

    def test_blank_diagnostic_boundary_rejected(self) -> None:
        """Blank diagnostic_only_claim_boundary is rejected."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlan(
                schema_version=1,
                seed=1001,
                task_id="test_task",
                probe_source_run_id="test_run_001",
                hashes=self.valid_hashes,
                reset_bowl_poses=self.valid_poses,
                steps=self.valid_steps,
                diagnostic_only_claim_boundary="",  # Blank
            )
        self.assertIn("must be non-blank string", str(cm.exception))

    def test_whitespace_diagnostic_boundary_rejected(self) -> None:
        """Whitespace-only diagnostic_only_claim_boundary is rejected."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlan(
                schema_version=1,
                seed=1001,
                task_id="test_task",
                probe_source_run_id="test_run_001",
                hashes=self.valid_hashes,
                reset_bowl_poses=self.valid_poses,
                steps=self.valid_steps,
                diagnostic_only_claim_boundary="   \t\n  ",  # Whitespace only
            )
        self.assertIn("must be non-blank string", str(cm.exception))

    def test_left_dual_clamp_true_rejected(self) -> None:
        """Left-side steps with dual_clamp_required=True are rejected."""
        with self.assertRaises(ValueError) as cm:
            ReplayPlanStep(
                level=0,
                bowl="bowl1",
                assigned_side="left",
                source_position_xyz_m=(0.1, 0.2, 0.74),
                right_grasp_candidate_index=None,
                right_grasp_candidate_tuple=None,
                place_xy_offset_m=(0.0, 0.0),
                dual_clamp_required=True,  # Invalid for left
                probe_placement_position_xyz_m=(0.0, 0.0, 0.74),
                probe_placement_gate_pass=True,
            )
        self.assertIn("left side must have dual_clamp_required=False", str(cm.exception))

    def test_unexpected_hash_key_rejected(self) -> None:
        """Unexpected hash keys are rejected."""
        invalid_hashes = self.valid_hashes.copy()
        invalid_hashes["unexpected_key"] = "g" * 64  # Extra key
        with self.assertRaises(ValueError) as cm:
            ReplayPlan(
                schema_version=1,
                seed=1001,
                task_id="test_task",
                probe_source_run_id="test_run_001",
                hashes=invalid_hashes,
                reset_bowl_poses=self.valid_poses,
                steps=self.valid_steps,
                diagnostic_only_claim_boundary="Unexpected hash key test",
            )
        self.assertIn("unexpected key", str(cm.exception))

    def test_duplicate_reset_bowl_rejected(self) -> None:
        """Duplicate bowl names in reset poses are rejected."""
        duplicate_poses = [
            {
                "name": "bowl1",  # First bowl1
                "position_xyz_m": [0.1, 0.2, 0.74],
                "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            },
            {
                "name": "bowl1",  # Duplicate bowl1
                "position_xyz_m": [-0.1, 0.3, 0.74],
                "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            },
            {
                "name": "bowl3",
                "position_xyz_m": [0.0, 0.4, 0.74],
                "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            },
        ]
        with self.assertRaises(ValueError) as cm:
            ReplayPlan(
                schema_version=1,
                seed=1001,
                task_id="test_task",
                probe_source_run_id="test_run_001",
                hashes=self.valid_hashes,
                reset_bowl_poses=duplicate_poses,
                steps=self.valid_steps,
                diagnostic_only_claim_boundary="Duplicate bowl test",
            )
        self.assertIn("duplicate name", str(cm.exception))

    def test_exact_source_equality_rejects_tiny_drift(self) -> None:
        """Exact source position equality rejects tiny nonzero drift."""
        drift_poses = [
            {
                "name": "bowl1",
                "position_xyz_m": [0.1000000001, 0.2, 0.74],  # Tiny drift
                "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            },
            {
                "name": "bowl2",
                "position_xyz_m": [-0.1, 0.3, 0.74],
                "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            },
            {
                "name": "bowl3",
                "position_xyz_m": [0.0, 0.4, 0.74],
                "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            },
        ]
        with self.assertRaises(ValueError) as cm:
            ReplayPlan(
                schema_version=1,
                seed=1001,
                task_id="test_task",
                probe_source_run_id="test_run_001",
                hashes=self.valid_hashes,
                reset_bowl_poses=drift_poses,
                steps=self.valid_steps,
                diagnostic_only_claim_boundary="Exact equality test",
            )
        self.assertIn("does not exactly match", str(cm.exception))


class TestValidationHelpers(unittest.TestCase):
    """Test pure validation helper functions."""

    def test_validate_candidate_tuple_right_side(self) -> None:
        """Right-side candidate validation passes with matching tuple."""
        candidates = [
            (0.0, -0.03, 0.70),
            (0.0, -0.025, 0.70),
            (0.0, -0.02, 0.70),
        ]
        planned_tuple = candidates[1]
        # Should not raise
        validate_candidate_tuple(planned_tuple, candidates, 1, "right")

    def test_validate_candidate_tuple_mismatch_rejected(self) -> None:
        """Candidate tuple mismatch is rejected."""
        candidates = [
            (0.0, -0.03, 0.70),
            (0.0, -0.025, 0.70),
        ]
        planned_tuple = (0.0, -0.02, 0.70)  # Not in candidates
        with self.assertRaises(ValueError) as cm:
            validate_candidate_tuple(planned_tuple, candidates, 1, "right")
        self.assertIn("does not match actual tuple", str(cm.exception))

    def test_validate_candidate_tuple_left_side_allows_none(self) -> None:
        """Left-side validation allows None values."""
        # Should not raise
        validate_candidate_tuple(None, [], None, "left")

    def test_validate_candidate_tuple_left_side_rejects_non_none(self) -> None:
        """Left-side validation rejects non-None values."""
        with self.assertRaises(ValueError) as cm:
            validate_candidate_tuple((0.0, -0.03, 0.70), [], None, "left")
        self.assertIn("must be None for left side", str(cm.exception))

    def test_validate_finite_offset_passes(self) -> None:
        """Valid finite offsets pass validation."""
        validate_finite_offset((0.01, -0.02))
        validate_finite_offset((0.0, 0.0))
        validate_finite_offset((0.15, -0.15))  # At max bound

    def test_validate_finite_offset_infinite_rejected(self) -> None:
        """Infinite or NaN offsets are rejected."""
        with self.assertRaises(ValueError) as cm:
            validate_finite_offset((float("inf"), 0.0))
        self.assertIn("must be finite", str(cm.exception))

    def test_validate_finite_offset_exceeds_max_rejected(self) -> None:
        """Offsets exceeding max bound are rejected."""
        with self.assertRaises(ValueError) as cm:
            validate_finite_offset((0.16, 0.0))
        self.assertIn("exceeds max 0.15", str(cm.exception))

    def test_validate_ordered_poses_exact_match_required(self) -> None:
        """Ordered poses must match exactly."""
        planned = [
            {"name": "bowl1", "position_xyz_m": [0.1, 0.2, 0.74], "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0]},
        ]
        actual = [
            {"name": "bowl1", "position_xyz_m": [0.1, 0.2, 0.74], "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0]},
        ]
        # Should not raise
        validate_ordered_poses(planned, actual)

    def test_validate_ordered_poses_name_mismatch_rejected(self) -> None:
        """Name mismatch is rejected."""
        planned = [
            {"name": "bowl1", "position_xyz_m": [0.1, 0.2, 0.74], "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0]},
        ]
        actual = [
            {"name": "bowl2", "position_xyz_m": [0.1, 0.2, 0.74], "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0]},
        ]
        with self.assertRaises(ValueError) as cm:
            validate_ordered_poses(planned, actual)
        self.assertIn("name mismatch", str(cm.exception))

    def test_validate_ordered_poses_position_mismatch_rejected(self) -> None:
        """Position mismatch is rejected."""
        planned = [
            {"name": "bowl1", "position_xyz_m": [0.1, 0.2, 0.74], "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0]},
        ]
        actual = [
            {"name": "bowl1", "position_xyz_m": [0.1, 0.2, 0.75], "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0]},  # Z differs
        ]
        with self.assertRaises(ValueError) as cm:
            validate_ordered_poses(planned, actual)
        self.assertIn("mismatch", str(cm.exception))

    def test_validate_ordered_poses_count_mismatch_rejected(self) -> None:
        """Count mismatch is rejected."""
        planned = [
            {"name": "bowl1", "position_xyz_m": [0.1, 0.2, 0.74], "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0]},
        ]
        actual = [
            {"name": "bowl1", "position_xyz_m": [0.1, 0.2, 0.74], "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0]},
            {"name": "bowl2", "position_xyz_m": [0.1, 0.2, 0.74], "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0]},
        ]
        with self.assertRaises(ValueError) as cm:
            validate_ordered_poses(planned, actual)
        self.assertIn("count mismatch", str(cm.exception))


class TestCandidateIsolationVersion(unittest.TestCase):
    """Test candidate_isolation_version field and plan_needs_reprobe logic."""

    def setUp(self) -> None:
        """Create valid plan data for tests."""
        self.valid_hashes = {
            "task": "a" * 64,
            "scene": "b" * 64,
            "camera": "c" * 64,
            "port": "d" * 64,
            "mantis_urdf": "e" * 64,
            "bowl_urdf": "f" * 64,
        }
        self.valid_poses = [
            {
                "name": "bowl1",
                "position_xyz_m": [0.1, 0.2, 0.74],
                "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            },
            {
                "name": "bowl2",
                "position_xyz_m": [-0.1, 0.3, 0.74],
                "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            },
            {
                "name": "bowl3",
                "position_xyz_m": [0.0, 0.4, 0.74],
                "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            },
        ]

    def test_old_json_missing_version_defaults_to_zero(self) -> None:
        """Old JSON without candidate_isolation_version deserializes to 0."""
        steps = [
            {
                "level": 0,
                "bowl": "bowl1",
                "assigned_side": "right",
                "source_position_xyz_m": [0.1, 0.2, 0.74],
                "right_grasp_candidate_index": 0,
                "right_grasp_candidate_tuple": [0.0, -0.03, 0.70],
                "place_xy_offset_m": [0.001, -0.002],
                "dual_clamp_required": True,
                "probe_placement_position_xyz_m": [0.001, 0.0, 0.74],
                "probe_placement_gate_pass": True,
            },
            {
                "level": 1,
                "bowl": "bowl2",
                "assigned_side": "left",
                "source_position_xyz_m": [-0.1, 0.3, 0.74],
                "right_grasp_candidate_index": None,
                "right_grasp_candidate_tuple": None,
                "place_xy_offset_m": [0.0, 0.0],
                "dual_clamp_required": False,
                "probe_placement_position_xyz_m": [0.0, -0.1, 0.77],
                "probe_placement_gate_pass": True,
            },
            {
                "level": 2,
                "bowl": "bowl3",
                "assigned_side": "right",
                "source_position_xyz_m": [0.0, 0.4, 0.74],
                "right_grasp_candidate_index": 1,
                "right_grasp_candidate_tuple": [0.0, -0.025, 0.68],
                "place_xy_offset_m": [-0.001, 0.001],
                "dual_clamp_required": True,
                "probe_placement_position_xyz_m": [-0.001, -0.1, 0.80],
                "probe_placement_gate_pass": True,
            },
        ]
        old_dict = {
            "schema_version": 1,
            "seed": 1001,
            "task_id": "test_task",
            "probe_source_run_id": "test_run_001",
            "hashes": self.valid_hashes,
            "reset_bowl_poses": self.valid_poses,
            "steps": steps,
            "probe_plan_pass": False,
            "scripted_g1_pass": False,
            "g1_claim": False,
            "learned_policy_claim": False,
            "rocm_claim": False,
            "multi_seed_evidence": False,
            "episode_success_claim": False,
            "diagnostic_only_claim_boundary": "Old plan test",
        }
        plan = ReplayPlan.from_dict(old_dict)
        self.assertEqual(plan.candidate_isolation_version, 0)

    def test_version0_with_candidate_gt0_needs_reprobe(self) -> None:
        """Version 0 and any right-side candidate index > 0 needs reprobe."""
        steps = (
            ReplayPlanStep(
                level=0,
                bowl="bowl1",
                assigned_side="right",
                source_position_xyz_m=(0.1, 0.2, 0.74),
                right_grasp_candidate_index=2,
                right_grasp_candidate_tuple=(0.0, -0.03, 0.70),
                place_xy_offset_m=(0.001, -0.002),
                dual_clamp_required=True,
                probe_placement_position_xyz_m=(0.001, 0.0, 0.74),
                probe_placement_gate_pass=True,
            ),
            ReplayPlanStep(
                level=1,
                bowl="bowl2",
                assigned_side="left",
                source_position_xyz_m=(-0.1, 0.3, 0.74),
                right_grasp_candidate_index=None,
                right_grasp_candidate_tuple=None,
                place_xy_offset_m=(0.0, 0.0),
                dual_clamp_required=False,
                probe_placement_position_xyz_m=(0.0, -0.1, 0.77),
                probe_placement_gate_pass=True,
            ),
            ReplayPlanStep(
                level=2,
                bowl="bowl3",
                assigned_side="right",
                source_position_xyz_m=(0.0, 0.4, 0.74),
                right_grasp_candidate_index=0,
                right_grasp_candidate_tuple=(0.0, -0.025, 0.68),
                place_xy_offset_m=(-0.001, 0.001),
                dual_clamp_required=True,
                probe_placement_position_xyz_m=(-0.001, -0.1, 0.80),
                probe_placement_gate_pass=True,
            ),
        )
        plan = ReplayPlan(
            schema_version=1,
            seed=1001,
            task_id="test_task",
            probe_source_run_id="test_run_001",
            hashes=self.valid_hashes,
            reset_bowl_poses=self.valid_poses,
            steps=steps,
            candidate_isolation_version=0,
            diagnostic_only_claim_boundary="Version 0 with candidate > 0 test",
        )
        self.assertTrue(plan_needs_reprobe(plan))

    def test_version0_all_candidates_zero_no_reprobe(self) -> None:
        """Version 0 but all right-side candidate indices == 0 needs no reprobe."""
        steps = (
            ReplayPlanStep(
                level=0,
                bowl="bowl1",
                assigned_side="right",
                source_position_xyz_m=(0.1, 0.2, 0.74),
                right_grasp_candidate_index=0,
                right_grasp_candidate_tuple=(0.0, -0.03, 0.70),
                place_xy_offset_m=(0.001, -0.002),
                dual_clamp_required=True,
                probe_placement_position_xyz_m=(0.001, 0.0, 0.74),
                probe_placement_gate_pass=True,
            ),
            ReplayPlanStep(
                level=1,
                bowl="bowl2",
                assigned_side="left",
                source_position_xyz_m=(-0.1, 0.3, 0.74),
                right_grasp_candidate_index=None,
                right_grasp_candidate_tuple=None,
                place_xy_offset_m=(0.0, 0.0),
                dual_clamp_required=False,
                probe_placement_position_xyz_m=(0.0, -0.1, 0.77),
                probe_placement_gate_pass=True,
            ),
            ReplayPlanStep(
                level=2,
                bowl="bowl3",
                assigned_side="right",
                source_position_xyz_m=(0.0, 0.4, 0.74),
                right_grasp_candidate_index=0,
                right_grasp_candidate_tuple=(0.0, -0.025, 0.68),
                place_xy_offset_m=(-0.001, 0.001),
                dual_clamp_required=True,
                probe_placement_position_xyz_m=(-0.001, -0.1, 0.80),
                probe_placement_gate_pass=True,
            ),
        )
        plan = ReplayPlan(
            schema_version=1,
            seed=1001,
            task_id="test_task",
            probe_source_run_id="test_run_001",
            hashes=self.valid_hashes,
            reset_bowl_poses=self.valid_poses,
            steps=steps,
            candidate_isolation_version=0,
            diagnostic_only_claim_boundary="Version 0 all zero test",
        )
        self.assertFalse(plan_needs_reprobe(plan))

    def test_version1_with_candidate_gt0_no_reprobe(self) -> None:
        """Version == CANDIDATE_ISOLATION_VERSION with candidate > 0 needs no reprobe."""
        steps = (
            ReplayPlanStep(
                level=0,
                bowl="bowl1",
                assigned_side="right",
                source_position_xyz_m=(0.1, 0.2, 0.74),
                right_grasp_candidate_index=5,
                right_grasp_candidate_tuple=(0.0, -0.03, 0.70),
                place_xy_offset_m=(0.001, -0.002),
                dual_clamp_required=True,
                probe_placement_position_xyz_m=(0.001, 0.0, 0.74),
                probe_placement_gate_pass=True,
            ),
            ReplayPlanStep(
                level=1,
                bowl="bowl2",
                assigned_side="left",
                source_position_xyz_m=(-0.1, 0.3, 0.74),
                right_grasp_candidate_index=None,
                right_grasp_candidate_tuple=None,
                place_xy_offset_m=(0.0, 0.0),
                dual_clamp_required=False,
                probe_placement_position_xyz_m=(0.0, -0.1, 0.77),
                probe_placement_gate_pass=True,
            ),
            ReplayPlanStep(
                level=2,
                bowl="bowl3",
                assigned_side="right",
                source_position_xyz_m=(0.0, 0.4, 0.74),
                right_grasp_candidate_index=3,
                right_grasp_candidate_tuple=(0.0, -0.025, 0.68),
                place_xy_offset_m=(-0.001, 0.001),
                dual_clamp_required=True,
                probe_placement_position_xyz_m=(-0.001, -0.1, 0.80),
                probe_placement_gate_pass=True,
            ),
        )
        plan = ReplayPlan(
            schema_version=1,
            seed=1001,
            task_id="test_task",
            probe_source_run_id="test_run_001",
            hashes=self.valid_hashes,
            reset_bowl_poses=self.valid_poses,
            steps=steps,
            candidate_isolation_version=CANDIDATE_ISOLATION_VERSION,
            diagnostic_only_claim_boundary="Version 1 with candidate > 0 test",
        )
        self.assertFalse(plan_needs_reprobe(plan))

    def test_dict_roundtrip_preserves_version(self) -> None:
        """JSON/dict roundtrip preserves candidate_isolation_version."""
        steps = (
            ReplayPlanStep(
                level=0,
                bowl="bowl1",
                assigned_side="right",
                source_position_xyz_m=(0.1, 0.2, 0.74),
                right_grasp_candidate_index=0,
                right_grasp_candidate_tuple=(0.0, -0.03, 0.70),
                place_xy_offset_m=(0.001, -0.002),
                dual_clamp_required=True,
                probe_placement_position_xyz_m=(0.001, 0.0, 0.74),
                probe_placement_gate_pass=True,
            ),
            ReplayPlanStep(
                level=1,
                bowl="bowl2",
                assigned_side="left",
                source_position_xyz_m=(-0.1, 0.3, 0.74),
                right_grasp_candidate_index=None,
                right_grasp_candidate_tuple=None,
                place_xy_offset_m=(0.0, 0.0),
                dual_clamp_required=False,
                probe_placement_position_xyz_m=(0.0, -0.1, 0.77),
                probe_placement_gate_pass=True,
            ),
            ReplayPlanStep(
                level=2,
                bowl="bowl3",
                assigned_side="right",
                source_position_xyz_m=(0.0, 0.4, 0.74),
                right_grasp_candidate_index=0,
                right_grasp_candidate_tuple=(0.0, -0.025, 0.68),
                place_xy_offset_m=(-0.001, 0.001),
                dual_clamp_required=True,
                probe_placement_position_xyz_m=(-0.001, -0.1, 0.80),
                probe_placement_gate_pass=True,
            ),
        )
        original_version = CANDIDATE_ISOLATION_VERSION
        plan = ReplayPlan(
            schema_version=1,
            seed=1001,
            task_id="test_task",
            probe_source_run_id="test_run_001",
            hashes=self.valid_hashes,
            reset_bowl_poses=self.valid_poses,
            steps=steps,
            candidate_isolation_version=original_version,
            diagnostic_only_claim_boundary="Roundtrip version test",
        )
        plan_dict = plan.to_dict()
        restored = ReplayPlan.from_dict(plan_dict)
        self.assertEqual(restored.candidate_isolation_version, original_version)

    def test_bool_version_rejected(self) -> None:
        """Boolean candidate_isolation_version is rejected."""
        steps = (
            ReplayPlanStep(
                level=0,
                bowl="bowl1",
                assigned_side="right",
                source_position_xyz_m=(0.1, 0.2, 0.74),
                right_grasp_candidate_index=0,
                right_grasp_candidate_tuple=(0.0, -0.03, 0.70),
                place_xy_offset_m=(0.001, -0.002),
                dual_clamp_required=True,
                probe_placement_position_xyz_m=(0.001, 0.0, 0.74),
                probe_placement_gate_pass=True,
            ),
            ReplayPlanStep(
                level=1,
                bowl="bowl2",
                assigned_side="left",
                source_position_xyz_m=(-0.1, 0.3, 0.74),
                right_grasp_candidate_index=None,
                right_grasp_candidate_tuple=None,
                place_xy_offset_m=(0.0, 0.0),
                dual_clamp_required=False,
                probe_placement_position_xyz_m=(0.0, -0.1, 0.77),
                probe_placement_gate_pass=True,
            ),
            ReplayPlanStep(
                level=2,
                bowl="bowl3",
                assigned_side="right",
                source_position_xyz_m=(0.0, 0.4, 0.74),
                right_grasp_candidate_index=0,
                right_grasp_candidate_tuple=(0.0, -0.025, 0.68),
                place_xy_offset_m=(-0.001, 0.001),
                dual_clamp_required=True,
                probe_placement_position_xyz_m=(-0.001, -0.1, 0.80),
                probe_placement_gate_pass=True,
            ),
        )
        with self.assertRaises(ValueError) as cm:
            ReplayPlan(
                schema_version=1,
                seed=1001,
                task_id="test_task",
                probe_source_run_id="test_run_001",
                hashes=self.valid_hashes,
                reset_bowl_poses=self.valid_poses,
                steps=steps,
                candidate_isolation_version=True,
                diagnostic_only_claim_boundary="Bool version test",
            )
        self.assertIn("must be int", str(cm.exception))

    def test_negative_version_rejected(self) -> None:
        """Negative candidate_isolation_version is rejected."""
        steps = (
            ReplayPlanStep(
                level=0,
                bowl="bowl1",
                assigned_side="right",
                source_position_xyz_m=(0.1, 0.2, 0.74),
                right_grasp_candidate_index=0,
                right_grasp_candidate_tuple=(0.0, -0.03, 0.70),
                place_xy_offset_m=(0.001, -0.002),
                dual_clamp_required=True,
                probe_placement_position_xyz_m=(0.001, 0.0, 0.74),
                probe_placement_gate_pass=True,
            ),
            ReplayPlanStep(
                level=1,
                bowl="bowl2",
                assigned_side="left",
                source_position_xyz_m=(-0.1, 0.3, 0.74),
                right_grasp_candidate_index=None,
                right_grasp_candidate_tuple=None,
                place_xy_offset_m=(0.0, 0.0),
                dual_clamp_required=False,
                probe_placement_position_xyz_m=(0.0, -0.1, 0.77),
                probe_placement_gate_pass=True,
            ),
            ReplayPlanStep(
                level=2,
                bowl="bowl3",
                assigned_side="right",
                source_position_xyz_m=(0.0, 0.4, 0.74),
                right_grasp_candidate_index=0,
                right_grasp_candidate_tuple=(0.0, -0.025, 0.68),
                place_xy_offset_m=(-0.001, 0.001),
                dual_clamp_required=True,
                probe_placement_position_xyz_m=(-0.001, -0.1, 0.80),
                probe_placement_gate_pass=True,
            ),
        )
        with self.assertRaises(ValueError) as cm:
            ReplayPlan(
                schema_version=1,
                seed=1001,
                task_id="test_task",
                probe_source_run_id="test_run_001",
                hashes=self.valid_hashes,
                reset_bowl_poses=self.valid_poses,
                steps=steps,
                candidate_isolation_version=-1,
                diagnostic_only_claim_boundary="Negative version test",
            )
        self.assertIn("must be non-negative", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
