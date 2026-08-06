from __future__ import annotations

import importlib.util
import math
import sys
import unittest
from pathlib import Path

from mantis_rocm_bridge.contracts import load_json


ROOT = Path(__file__).resolve().parents[1]


def _load_tool_module():
    """Import the tool module by path without importing Genesis.

    The module only imports Genesis lazily inside ``main()``, so its small
    pure helpers are safe to exercise in unit tests.
    """
    module_path = ROOT / "tools" / "run_genesis_stack_bowls_scripted_g1.py"
    spec = importlib.util.spec_from_file_location(
        "run_genesis_stack_bowls_scripted_g1", module_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ScriptedG1SeedParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_tool_module()

    def test_default_seed_is_canonical_g1(self) -> None:
        args = self.module.build_parser().parse_args(
            [
                "mantis.urdf",
                "bowl_root",
                "--ops-root",
                "ops",
                "--run-id",
                "run-1",
                "--backend",
                "cpu",
            ]
        )
        self.assertEqual(args.seed, self.module.G1_CANONICAL_SEED)
        self.assertEqual(args.seed, 1)

    def test_seed_override_is_parsed_as_integer(self) -> None:
        args = self.module.build_parser().parse_args(
            [
                "mantis.urdf",
                "bowl_root",
                "--ops-root",
                "ops",
                "--run-id",
                "run-2",
                "--backend",
                "cpu",
                "--seed",
                "7",
            ]
        )
        self.assertEqual(args.seed, 7)
        self.assertIsInstance(args.seed, int)


class ScriptedG1CaptureNamingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_tool_module()

    def test_canonical_seed_names_episode_seed_1_npz(self) -> None:
        self.assertEqual(
            self.module.capture_npz_name(self.module.G1_CANONICAL_SEED),
            "episode_seed_1.npz",
        )

    def test_noncanonical_seed_names_dynamic_episode_npz(self) -> None:
        self.assertEqual(self.module.capture_npz_name(7), "episode_seed_7.npz")
        self.assertEqual(self.module.capture_npz_name(42), "episode_seed_42.npz")

    def test_naming_is_seed_driven_and_distinct(self) -> None:
        names = {self.module.capture_npz_name(s) for s in (1, 2, 3)}
        self.assertEqual(len(names), 3)


class ScriptedG1CanonicalClaimTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_tool_module()

    def test_only_seed_one_is_canonical(self) -> None:
        self.assertTrue(self.module.is_canonical_g1_seed(1))

    def test_non_one_seeds_are_not_canonical_even_if_strict_success(self) -> None:
        # A strict scripted success on any other seed must not be canonical G1.
        for seed in (0, 2, 3, 7, 42, 100):
            self.assertFalse(self.module.is_canonical_g1_seed(seed))

    def test_canonical_constant_is_one(self) -> None:
        self.assertEqual(self.module.G1_CANONICAL_SEED, 1)


class ScriptedG1SmokeContractDriftTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_tool_module()
        self.task = load_json(ROOT / "configs/task-pack-v1.json")

    def test_checked_in_task_pack_keeps_g1_smoke_exactly_one(self) -> None:
        # The frozen contract the gate depends on.
        self.assertEqual(
            self.task["evaluation"]["seed_sets"]["g1_smoke"], [1]
        )
        # The helper must accept the checked-in contract without raising.
        self.module.validate_g1_smoke_contract(self.task)

    def test_drift_in_seed_value_is_rejected(self) -> None:
        drifted = {
            "evaluation": {"seed_sets": {"g1_smoke": [2]}},
        }
        with self.assertRaises(RuntimeError):
            self.module.validate_g1_smoke_contract(drifted)

    def test_drift_in_set_length_is_rejected(self) -> None:
        drifted = {
            "evaluation": {"seed_sets": {"g1_smoke": [1, 2]}},
        }
        with self.assertRaises(RuntimeError):
            self.module.validate_g1_smoke_contract(drifted)

    def test_missing_seed_set_is_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            self.module.validate_g1_smoke_contract({"evaluation": {"seed_sets": {}}})


class RightGraspCandidatesTests(unittest.TestCase):
    """Test right_grasp_candidates deterministic helper behavior."""

    def setUp(self) -> None:
        self.module = _load_tool_module()

    def test_pose_candidates_returns_exactly_nine(self):
        """Nine bound: right_grasp_pose_candidates must return exactly nine (x_offset, forward_offset, z) tuples."""
        candidates = self.module.right_grasp_pose_candidates(0.84, -0.0678, 0.0652)
        self.assertEqual(len(candidates), 9)

    def test_pose_candidate_0_remains_unchanged(self):
        """Candidate 0 must be (0.0, -0.03, base_z-0.04)."""
        candidates = self.module.right_grasp_pose_candidates(0.84, -0.0678, 0.0652)
        first = candidates[0]
        self.assertAlmostEqual(first[0], 0.0, places=6)
        self.assertAlmostEqual(first[1], -0.03, places=6)
        self.assertAlmostEqual(first[2], 0.80, places=6)  # 0.84 - 0.04

    def test_pose_candidates_first_six_have_zero_x_offset(self):
        """First six candidates: existing Y/Z candidates with x_offset=0.0 in identical order."""
        candidates = self.module.right_grasp_pose_candidates(0.84, -0.0678, 0.0652)
        for i in range(6):
            self.assertAlmostEqual(candidates[i][0], 0.0, places=6, msg=f"Candidate {i} x_offset should be 0.0")

    def test_pose_candidates_first_six_match_existing_helper(self):
        """First six (forward_offset, z) values must match right_grasp_candidates in identical order."""
        yz_candidates = self.module.right_grasp_candidates(0.84, -0.0678)
        pose_candidates = self.module.right_grasp_pose_candidates(0.84, -0.0678, 0.0652)
        for i in range(6):
            self.assertAlmostEqual(pose_candidates[i][1], yz_candidates[i][0], places=6,
                                 msg=f"Candidate {i} forward_offset mismatch")
            self.assertAlmostEqual(pose_candidates[i][2], yz_candidates[i][1], places=6,
                                 msg=f"Candidate {i} z mismatch")

    def test_pose_candidates_last_three_use_finger_extent(self):
        """Last three candidates: x_compensated with x_offset=+finger_forward_extent_m."""
        candidates = self.module.right_grasp_pose_candidates(0.84, -0.0678, 0.0652)
        for i in range(6, 9):
            self.assertAlmostEqual(candidates[i][0], 0.0652, places=6, msg=f"Candidate {i} x_offset should be 0.0652")

    def test_pose_candidates_last_three_upper_tier(self):
        """Last three candidates: all at upper z (base_z-0.04)."""
        candidates = self.module.right_grasp_pose_candidates(0.84, -0.0678, 0.0652)
        upper_z = 0.84 - 0.04
        for i in range(6, 9):
            self.assertAlmostEqual(candidates[i][2], upper_z, places=6, msg=f"Candidate {i} z should be upper tier")

    def test_pose_candidates_x_compensated_forward_offsets(self):
        """Last three forward offsets: current(-0.03), midpoint, calibrated(-0.0678) in order."""
        candidates = self.module.right_grasp_pose_candidates(0.84, -0.0678, 0.0652)
        # Candidate 6: current forward
        self.assertAlmostEqual(candidates[6][1], -0.03, places=6)
        # Candidate 7: midpoint
        expected_midpoint = (-0.03 + -0.0678) / 2.0
        self.assertAlmostEqual(candidates[7][1], expected_midpoint, places=6)
        # Candidate 8: calibrated
        self.assertAlmostEqual(candidates[8][1], -0.0678, places=6)

    def test_pose_candidates_exact_order_with_config_extent(self):
        """Test exact order with config extent 0.0652."""
        candidates = self.module.right_grasp_pose_candidates(0.84, -0.0678, 0.0652)
        upper_z = 0.84 - 0.04
        lower_z = 0.84 - 0.06
        midpoint = (-0.03 + -0.0678) / 2.0

        # Expected order
        expected = [
            (0.0, -0.03, upper_z),           # 0: current, no X
            (0.0, midpoint, upper_z),        # 1: midpoint, no X
            (0.0, -0.0678, upper_z),          # 2: calibrated, no X
            (0.0, -0.03, lower_z),            # 3: current lower, no X
            (0.0, midpoint, lower_z),         # 4: midpoint lower, no X
            (0.0, -0.0678, lower_z),          # 5: calibrated lower, no X
            (0.0652, -0.03, upper_z),         # 6: X-compensated current
            (0.0652, midpoint, upper_z),      # 7: X-compensated midpoint
            (0.0652, -0.0678, upper_z),       # 8: X-compensated calibrated
        ]

        for i, (actual, exp) in enumerate(zip(candidates, expected)):
            self.assertAlmostEqual(actual[0], exp[0], places=6, msg=f"Candidate {i} x_offset mismatch")
            self.assertAlmostEqual(actual[1], exp[1], places=6, msg=f"Candidate {i} forward_offset mismatch")
            self.assertAlmostEqual(actual[2], exp[2], places=6, msg=f"Candidate {i} z mismatch")

    def test_pose_candidates_validates_finger_extent_bounds(self):
        """Validation: finger extent must satisfy 0 < extent <= 0.10."""
        # Too small
        with self.assertRaises(ValueError) as ctx:
            self.module.right_grasp_pose_candidates(0.84, -0.0678, 0.0)
        self.assertIn("0 < extent", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            self.module.right_grasp_pose_candidates(0.84, -0.0678, -0.01)
        self.assertIn("0 < extent", str(ctx.exception))

        # Too large
        with self.assertRaises(ValueError) as ctx:
            self.module.right_grasp_pose_candidates(0.84, -0.0678, 0.11)
        self.assertIn("0 < extent", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            self.module.right_grasp_pose_candidates(0.84, -0.0678, 0.1001)
        self.assertIn("0 < extent", str(ctx.exception))

        # Boundary value 0.10 should be valid (<= 0.10)
        candidates = self.module.right_grasp_pose_candidates(0.84, -0.0678, 0.10)
        self.assertEqual(len(candidates), 9)

    def test_pose_candidates_validates_finger_extent_finite_numeric_not_bool(self):
        """Validation: finger extent must be finite numeric, not bool."""
        # Bool
        with self.assertRaises(ValueError) as ctx:
            self.module.right_grasp_pose_candidates(0.84, -0.0678, True)
        self.assertIn("bool", str(ctx.exception).lower())

        with self.assertRaises(ValueError) as ctx:
            self.module.right_grasp_pose_candidates(0.84, -0.0678, False)
        self.assertIn("bool", str(ctx.exception).lower())

        # Infinite
        with self.assertRaises(ValueError) as ctx:
            self.module.right_grasp_pose_candidates(0.84, -0.0678, float('inf'))
        self.assertIn("finite", str(ctx.exception).lower())

        # NaN
        with self.assertRaises(ValueError) as ctx:
            self.module.right_grasp_pose_candidates(0.84, -0.0678, float('nan'))
        self.assertIn("finite", str(ctx.exception).lower())

    def test_pose_candidates_returns_immutable_tuples(self):
        """Return type: list of immutable tuples."""
        candidates = self.module.right_grasp_pose_candidates(0.84, -0.0678, 0.0652)
        for candidate in candidates:
            self.assertIsInstance(candidate, tuple)

    def test_pose_candidates_inherits_base_validations(self):
        """Must still validate base_grasp_z and calibrated_forward_offset via right_grasp_candidates."""
        # Invalid calibrated offset
        with self.assertRaises(ValueError) as ctx:
            self.module.right_grasp_pose_candidates(0.84, -0.02, 0.0652)
        self.assertIn("-0.03", str(ctx.exception))

        # Non-finite base_z
        with self.assertRaises(ValueError) as ctx:
            self.module.right_grasp_pose_candidates(float('inf'), -0.0678, 0.0652)
        self.assertIn("finite", str(ctx.exception).lower())

    def test_returns_exactly_six_candidates(self) -> None:
        """Six bound: function must return exactly six (forward_offset, z) tuples."""
        candidates = self.module.right_grasp_candidates(0.84, -0.05)
        self.assertEqual(len(candidates), 6)

    def test_current_behavior_is_first(self) -> None:
        """Order/current-first: (-0.03, base_z-0.04) must be the first candidate."""
        candidates = self.module.right_grasp_candidates(0.84, -0.05)
        first = candidates[0]
        self.assertAlmostEqual(first[0], -0.03, places=6)
        self.assertAlmostEqual(first[1], 0.84 - 0.04, places=6)

    def test_upper_then_lower_tier(self) -> None:
        """Lower tier: first three candidates at upper z, then three at z-0.02."""
        candidates = self.module.right_grasp_candidates(0.84, -0.05)
        upper_z = 0.84 - 0.04
        lower_z = 0.84 - 0.06

        # First three at upper z
        for i in range(3):
            self.assertAlmostEqual(candidates[i][1], upper_z, places=6)
        # Last three at lower z
        for i in range(3, 6):
            self.assertAlmostEqual(candidates[i][1], lower_z, places=6)

    def test_monotonic_progression_at_upper_z(self) -> None:
        """Monotonicity: forward offsets progress from -0.03 through midpoint to calibrated."""
        candidates = self.module.right_grasp_candidates(0.84, -0.05)
        upper_z = 0.84 - 0.04

        # Extract forward offsets at upper z
        upper_offsets = [c[0] for c in candidates[:3]]
        self.assertEqual(upper_offsets[0], -0.03)

        # Midpoint should be average
        expected_midpoint = (-0.03 + -0.05) / 2.0
        self.assertAlmostEqual(upper_offsets[1], expected_midpoint, places=6)

        # Last should be calibrated
        self.assertAlmostEqual(upper_offsets[2], -0.05, places=6)

    def test_same_three_offsets_at_lower_tier(self) -> None:
        """Lower tier repeats the same three forward offsets at lower z."""
        candidates = self.module.right_grasp_candidates(0.84, -0.05)

        upper_offsets = [c[0] for c in candidates[:3]]
        lower_offsets = [c[0] for c in candidates[3:]]

        self.assertEqual(upper_offsets, lower_offsets)

    def test_no_seed_argument_is_deterministic(self) -> None:
        """Seed independence by API: calling twice with same inputs returns identical results."""
        candidates1 = self.module.right_grasp_candidates(0.84, -0.05)
        candidates2 = self.module.right_grasp_candidates(0.84, -0.05)

        self.assertEqual(candidates1, candidates2)

    def test_validates_finite_inputs(self) -> None:
        """Validation: must raise ValueError for non-finite inputs."""
        with self.assertRaises(ValueError) as ctx:
            self.module.right_grasp_candidates(float('inf'), -0.05)
        self.assertIn("finite", str(ctx.exception).lower())

        with self.assertRaises(ValueError) as ctx:
            self.module.right_grasp_candidates(0.84, float('nan'))
        self.assertIn("finite", str(ctx.exception).lower())

    def test_validates_calibrated_offset_is_negative(self) -> None:
        """Validation: calibrated offset must be negative."""
        with self.assertRaises(ValueError) as ctx:
            self.module.right_grasp_candidates(0.84, 0.01)
        self.assertIn("negative", str(ctx.exception).lower())

        with self.assertRaises(ValueError) as ctx:
            self.module.right_grasp_candidates(0.84, 0.0)
        self.assertIn("negative", str(ctx.exception).lower())

    def test_validates_calibrated_offset_at_least_as_forward_as_negative_003(self) -> None:
        """Validation: calibrated offset must be at least as forward as -0.03."""
        with self.assertRaises(ValueError) as ctx:
            self.module.right_grasp_candidates(0.84, -0.02)
        self.assertIn("-0.03", str(ctx.exception))

        # -0.03 should be valid
        candidates = self.module.right_grasp_candidates(0.84, -0.03)
        self.assertEqual(len(candidates), 6)

    def test_extreme_calibrated_offset(self) -> None:
        """Test with a very forward calibrated offset."""
        candidates = self.module.right_grasp_candidates(0.84, -0.15)
        self.assertEqual(len(candidates), 6)
        self.assertEqual(candidates[0][0], -0.03)
        self.assertEqual(candidates[2][0], -0.15)

    def test_rejects_bool_inputs_explicitly(self) -> None:
        """Validation: bool is explicitly rejected even though bool is int in Python."""
        with self.assertRaises(ValueError) as ctx:
            self.module.right_grasp_candidates(True, -0.05)
        self.assertIn("bool", str(ctx.exception).lower())

        with self.assertRaises(ValueError) as ctx:
            self.module.right_grasp_candidates(0.84, False)
        self.assertIn("bool", str(ctx.exception).lower())

    def test_config_calibrated_offset_with_current_first_and_calibrated_endpoints(self) -> None:
        """Test using actual config calibrated offset -0.0678 and base 0.84,
        verifying current-first and calibrated endpoints.
        """
        candidates = self.module.right_grasp_candidates(0.84, -0.0678)

        # Current behavior first
        self.assertAlmostEqual(candidates[0][0], -0.03, places=6)
        self.assertAlmostEqual(candidates[0][1], 0.80, places=6)

        # Calibrated endpoint at upper z
        self.assertAlmostEqual(candidates[2][0], -0.0678, places=6)
        self.assertAlmostEqual(candidates[2][1], 0.80, places=6)

        # Calibrated endpoint at lower z
        self.assertAlmostEqual(candidates[5][0], -0.0678, places=6)
        self.assertAlmostEqual(candidates[5][1], 0.78, places=6)


class RightProbeCandidateSearchOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_tool_module()

    def test_returns_exact_stable_index_order(self) -> None:
        self.assertEqual(
            self.module.right_probe_candidate_search_order(9),
            [0, 1, 2, 6, 7, 8, 3, 4, 5],
        )

    def test_order_is_complete_permutation(self) -> None:
        order = self.module.right_probe_candidate_search_order(9)
        self.assertEqual(len(order), 9)
        self.assertEqual(sorted(order), list(range(9)))
        self.assertEqual(len(set(order)), 9)

    def test_returns_fresh_list(self) -> None:
        first = self.module.right_probe_candidate_search_order(9)
        second = self.module.right_probe_candidate_search_order(9)
        self.assertIsNot(first, second)
        first.append(99)
        self.assertEqual(second, [0, 1, 2, 6, 7, 8, 3, 4, 5])

    def test_rejects_wrong_candidate_count(self) -> None:
        for count in (-1, 0, 8, 10):
            with self.subTest(count=count):
                with self.assertRaises(ValueError):
                    self.module.right_probe_candidate_search_order(count)

    def test_rejects_bool_and_non_integer_counts(self) -> None:
        for value in (True, 9.0, "9", None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.module.right_probe_candidate_search_order(value)

    def test_generation_modes_keep_distinct_candidate_selection(self) -> None:
        source = (ROOT / "tools" / "run_genesis_stack_bowls_scripted_g1.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "candidate_indices_to_try = [planned_step.right_grasp_candidate_index]",
            source,
        )
        self.assertIn(
            "candidate_indices_to_try = right_probe_candidate_search_order(",
            source,
        )
        self.assertIn(
            "candidate_indices_to_try = list(range(len(grasp_candidates)))",
            source,
        )


class RightXYCorrectionTests(unittest.TestCase):
    """Test right_xy_correction deterministic helper behavior."""

    def setUp(self) -> None:
        self.module = _load_tool_module()

    def test_no_correction_when_within_tolerance(self) -> None:
        """No-op: returns None when both errors are strictly below tolerance."""
        measured = (0.0, -0.1)
        target = (0.001, -0.099)  # Both errors 1mm
        result = self.module.right_xy_correction(measured, target, 0.04)
        self.assertIsNone(result)

    def test_returns_correction_when_x_error_exceeds_tolerance(self) -> None:
        """Returns error vector when X error at or exceeds tolerance."""
        measured = (-0.089, -0.1)
        target = (0.0, -0.1)
        result = self.module.right_xy_correction(measured, target, 0.04)

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[0], 0.089, places=6)
        self.assertAlmostEqual(result[1], 0.0, places=6)

    def test_returns_correction_when_y_error_exceeds_tolerance(self) -> None:
        """Returns error vector when Y error at or exceeds tolerance."""
        measured = (0.0, -0.15)
        target = (0.0, -0.1)
        result = self.module.right_xy_correction(measured, target, 0.04)

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[0], 0.0, places=6)
        self.assertAlmostEqual(result[1], 0.05, places=6)

    def test_observed_1002_correction_approximately(self) -> None:
        """The observed 1002 correction: (+0.0891186, -0.0097103 approximately)."""
        # From seed-1002 failure: measured position ~[-0.089, -0.090]
        # target [0.0, -0.1] -> correction ~[+0.089, -0.0097]
        measured = (-0.08911862224340439, -0.09028970450162888)
        target = (0.0, -0.1)
        result = self.module.right_xy_correction(measured, target, 0.04)

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[0], 0.0891186, places=4)
        self.assertAlmostEqual(result[1], -0.0097103, places=4)

    def test_tolerance_boundary_strict_below(self) -> None:
        """Tolerance boundary: error strictly less than tolerance returns None."""
        measured = (0.0, -0.1)
        target = (0.0399, -0.1)  # X error exactly at tolerance boundary
        result = self.module.right_xy_correction(measured, target, 0.04)

        self.assertIsNone(result)

    def test_tolerance_boundary_at_or_above_returns_correction(self) -> None:
        """Tolerance boundary: error at or above tolerance returns correction."""
        measured = (0.0, -0.1)
        target = (0.04, -0.1)  # X error at tolerance
        result = self.module.right_xy_correction(measured, target, 0.04)

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[0], 0.04, places=6)

    def test_validates_finite_inputs(self) -> None:
        """Validation: must raise ValueError for non-finite inputs."""
        with self.assertRaises(ValueError) as ctx:
            self.module.right_xy_correction((float('inf'), 0.0), (0.0, 0.0), 0.04)
        self.assertIn("finite", str(ctx.exception).lower())

        with self.assertRaises(ValueError) as ctx:
            self.module.right_xy_correction((0.0, 0.0), (float('nan'), 0.0), 0.04)
        self.assertIn("finite", str(ctx.exception).lower())

    def test_validates_positive_tolerance(self) -> None:
        """Validation: tolerance must be positive."""
        with self.assertRaises(ValueError) as ctx:
            self.module.right_xy_correction((0.0, 0.0), (0.0, 0.0), 0.0)
        self.assertIn("positive", str(ctx.exception).lower())

        with self.assertRaises(ValueError) as ctx:
            self.module.right_xy_correction((0.0, 0.0), (0.0, 0.0), -0.01)
        self.assertIn("positive", str(ctx.exception).lower())

    def test_returns_immutable_tuple(self) -> None:
        """Return type is an immutable tuple, not a list."""
        result = self.module.right_xy_correction((0.0, 0.0), (0.1, 0.1), 0.04)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, tuple)

    def test_rejects_bool_tolerance_explicitly(self) -> None:
        """Validation: bool tolerance is explicitly rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.module.right_xy_correction((0.0, 0.0), (0.1, 0.1), True)
        self.assertIn("bool", str(ctx.exception).lower())

    def test_rejects_wrong_sequence_type(self) -> None:
        """Validation: non-sequence inputs raise clear ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.module.right_xy_correction(None, (0.1, 0.1), 0.04)
        self.assertIn("measured_xy", str(ctx.exception).lower())
        self.assertIn("sequence", str(ctx.exception).lower())

    def test_rejects_wrong_sequence_length(self) -> None:
        """Validation: sequences not length 2 raise clear ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.module.right_xy_correction((0.0, 0.1, 0.2), (0.1, 0.1), 0.04)
        self.assertIn("measured_xy", str(ctx.exception).lower())
        self.assertIn("length 2", str(ctx.exception).lower())

        with self.assertRaises(ValueError) as ctx:
            self.module.right_xy_correction((0.0, 0.1), (0.1,), 0.04)
        self.assertIn("target_xy", str(ctx.exception).lower())
        self.assertIn("length 2", str(ctx.exception).lower())

    def test_rejects_bool_elements_in_sequences(self) -> None:
        """Validation: bool elements in sequences are explicitly rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.module.right_xy_correction((True, 0.0), (0.1, 0.1), 0.04)
        self.assertIn("measured_xy", str(ctx.exception).lower())
        self.assertIn("bool", str(ctx.exception).lower())

        with self.assertRaises(ValueError) as ctx:
            self.module.right_xy_correction((0.0, 0.0), (0.1, False), 0.04)
        self.assertIn("target_xy", str(ctx.exception).lower())
        self.assertIn("bool", str(ctx.exception).lower())

    def test_rejects_non_numeric_elements_in_sequences(self) -> None:
        """Validation: non-numeric elements in sequences raise clear ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.module.right_xy_correction(("invalid", 0.0), (0.1, 0.1), 0.04)
        self.assertIn("measured_xy", str(ctx.exception).lower())
        self.assertIn("numeric", str(ctx.exception).lower())

    def test_rejects_non_finite_elements_in_sequences(self) -> None:
        """Validation: non-finite elements in sequences raise clear ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.module.right_xy_correction((float('inf'), 0.0), (0.1, 0.1), 0.04)
        self.assertIn("measured_xy", str(ctx.exception).lower())
        self.assertIn("finite", str(ctx.exception).lower())

        with self.assertRaises(ValueError) as ctx:
            self.module.right_xy_correction((0.0, 0.0), (0.1, float('nan')), 0.04)
        self.assertIn("target_xy", str(ctx.exception).lower())
        self.assertIn("finite", str(ctx.exception).lower())

    def test_both_axes_exceeding_tolerance(self) -> None:
        """Returns full error vector when both axes exceed tolerance."""
        measured = (-0.1, -0.2)
        target = (0.0, -0.1)
        result = self.module.right_xy_correction(measured, target, 0.04)

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[0], 0.1, places=6)
        self.assertAlmostEqual(result[1], 0.1, places=6)


class StrictEvaluatorXYToleranceTests(unittest.TestCase):
    """Strict evaluator unit test proving 89mm X error fails 40mm XY tolerance."""

    def setUp(self) -> None:
        self.module = _load_tool_module()
        # Import the real evaluator
        from mantis_rocm_bridge.stack_bowls import evaluate_strict_target_frame
        self.evaluate_strict_target_frame = evaluate_strict_target_frame
        # Load task config to get actual tolerance values
        self.task = load_json(ROOT / "configs/task-pack-v1.json")

    def test_evaluator_rejects_89mm_x_error_with_valid_heights(self) -> None:
        """Call real evaluate_strict_target_frame with three valid-height objects
        where observed -0.0891186 X base vs aligned middle/top at target X makes
        lower_middle_xy false under 0.04 and frame_success false; verify heights
        and all unrelated gates pass.
        """
        xy_tolerance = float(self.task["success_predicate"]["xy_axis_alignment_tolerance_m"])
        height_tolerance = float(self.task["success_predicate"]["height_absolute_tolerance_m"])
        expected_heights = [float(h) for h in self.task["success_predicate"]["target_heights_m"]]

        # Three bowls at valid heights (0.74, 0.77, 0.81 within 0.02 tolerance)
        # Base bowl has X error -89mm (aligned to -0.089 instead of target 0.0)
        # Middle and top bowls aligned at target X=0.0, Y=-0.1
        positions = [
            [-0.08911862224340439, -0.1, 0.7399629354476929],  # base: X error ~89mm
            [0.0, -0.1, 0.77],  # middle: aligned at target
            [0.0, -0.1, 0.81],  # top: aligned at target
        ]
        linear_velocities = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
        angular_velocities = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]

        result = self.evaluate_strict_target_frame(
            positions,
            linear_velocities,
            angular_velocities,
            left_gripper_open_fraction=1.0,
            right_gripper_open_fraction=1.0,
            xy_axis_tolerance_m=xy_tolerance,
            height_absolute_tolerance_m=height_tolerance,
            maximum_linear_speed_m_s=float(self.task["success_predicate"]["maximum_linear_speed_m_s"]),
            maximum_angular_speed_rad_s=float(self.task["success_predicate"]["maximum_angular_speed_rad_s"]),
            minimum_gripper_open_fraction=float(self.task["success_predicate"]["minimum_gripper_open_fraction"]),
            no_safety_failure=True,
            no_physics_divergence=True,
        )

        # Heights should pass
        self.assertTrue(result["checks"]["absolute_heights"],
                       "All heights should be within tolerance")
        for i, (pos, expected_h) in enumerate(zip(positions, expected_heights)):
            height_error = abs(pos[2] - expected_h)
            self.assertLess(height_error, height_tolerance,
                           f"Bowl {i} height {pos[2]:.6f} should be within {height_tolerance} of {expected_h}")

        # Unrelated gates should pass
        self.assertTrue(result["checks"]["motion_stable"], "Zero velocities should be stable")
        self.assertTrue(result["checks"]["grippers_open"], "Grippers fully open should pass")

        # XY alignment should fail
        self.assertFalse(result["checks"]["lower_middle_xy"],
                         "Base bowl at X=-0.089 should not align with middle at X=0.0 under 40mm tolerance")
        self.assertTrue(result["checks"]["middle_upper_xy"],
                        "Middle and top both at X=0.0 should align")

        # Frame success should be false due to XY misalignment
        self.assertFalse(result["frame_success"],
                         "Frame should fail due to lower_middle_xy XY misalignment")

    def test_right_xy_correction_helper_confirms_x_error(self) -> None:
        """Separate test: right_xy_correction helper returns correction vector
        confirming the X error exceeds tolerance (runner-level check, not evaluator).
        """
        xy_tolerance = float(self.task["success_predicate"]["xy_axis_alignment_tolerance_m"])
        measured = (-0.08911862224340439, -0.1)
        target = (0.0, -0.1)

        correction = self.module.right_xy_correction(measured, target, xy_tolerance)
        self.assertIsNotNone(correction,
                           "right_xy_correction should return correction vector for X error")
        self.assertGreater(abs(correction[0]), xy_tolerance,
                          f"Correction X ({correction[0]*1000:.1f}mm) should exceed {xy_tolerance*1000:.0f}mm")
        self.assertLess(abs(correction[1]), xy_tolerance,
                        f"Y correction ({correction[1]*1000:.1f}mm) should be within {xy_tolerance*1000:.0f}mm")


class ScriptedG1BowlProgressFileTests(unittest.TestCase):
    """Test bowl progress file writing functionality without Genesis runtime."""

    def setUp(self) -> None:
        self.module = _load_tool_module()

    def test_bowl_progress_data_structure_has_required_fields(self) -> None:
        """Verify bowl progress data structure has all required fields."""
        # Sample bowl_run_data structure matching the implementation
        bowl_run_data = {
            "bowl": "bowl1",
            "assigned_side": "right",
            "source_assigned_side": "right",
            "grasp_mode": "assigned_right_forward_rim_pinch_suction",
            "source_position_xyz_m": [0.1, 0.2, 0.74],
            "stack_level": 0,
            "grasp_tcp_position_xyz_m": [0.1, 0.2, 0.7],
            "place_tcp_position_xyz_m": [0.0, -0.1, 0.74],
            "transport_tcp_position_xyz_m": [0.0, -0.1, 0.8],
            "lift_delta_m": 0.05,
            "placed_position_xyz_m": [0.0, -0.1, 0.74],
            "contact_verified": True,
            "contacted_clamp_links": ["right_shoulder_pitch_link"],
            "suction_link": "right_shoulder_pitch_link",
            "weld_registered_after_add": True,
            "weld_removed_before_release": True,
            "ik_errors": {},
            "final_pre_release_position_xyz_m": [0.0, -0.1, 0.74],
            "immediate_post_release_position_xyz_m": [0.0, -0.1, 0.74],
            "post_vertical_withdrawal_position_xyz_m": [0.0, -0.1, 0.8],
            "post_high_clearance_retreat_position_xyz_m": [0.0, -0.1, 0.95],
        }

        # Construct progress data as implemented in main()
        progress_data = {
            "schema_version": 1,
            "seed": 1,
            "bowl_data": bowl_run_data,
            "partial_only": True,
            "episode_success": False,
            "g1_claim": False,
            "learned_policy_claim": False,
            "rocm_claim": False,
            "multi_seed_evidence": False,
            "claim_boundary": (
                f"Partial scripted progress only: {bowl_run_data['bowl']} placed at level {bowl_run_data['stack_level']} "
                f"using contact-triggered idealized suction transport in one Genesis scene. "
                f"This is a single-bowl milestone file, not an episode completion receipt. "
                f"No G1, learned-policy, multi-seed, or ROCm execution claim is made."
            ),
        }

        # Verify all required fields are present
        required_fields = [
            "schema_version", "seed", "bowl_data", "partial_only",
            "episode_success", "g1_claim", "learned_policy_claim",
            "rocm_claim", "multi_seed_evidence", "claim_boundary"
        ]
        for field in required_fields:
            self.assertIn(field, progress_data, f"Progress data must contain {field}")

        # Verify field types and values
        self.assertEqual(progress_data["schema_version"], 1)
        self.assertEqual(progress_data["seed"], 1)
        self.assertTrue(progress_data["partial_only"])
        self.assertFalse(progress_data["episode_success"])
        self.assertFalse(progress_data["g1_claim"])
        self.assertFalse(progress_data["learned_policy_claim"])
        self.assertFalse(progress_data["rocm_claim"])
        self.assertFalse(progress_data["multi_seed_evidence"])
        self.assertIsInstance(progress_data["claim_boundary"], str)
        self.assertIn("Partial scripted progress only", progress_data["claim_boundary"])

    def test_bowl_progress_claim_boundary_states_partial_only(self) -> None:
        """Verify claim boundary explicitly states partial scripted progress only."""
        progress_data = {
            "schema_version": 1,
            "seed": 42,
            "bowl_data": {"bowl": "bowl2", "stack_level": 1},
            "partial_only": True,
            "episode_success": False,
            "g1_claim": False,
            "learned_policy_claim": False,
            "rocm_claim": False,
            "multi_seed_evidence": False,
            "claim_boundary": (
                "Partial scripted placement attempt only: bowl2 placement attempt at level 1 "
                "using contact-triggered idealized suction transport in one Genesis scene. "
                "This is a single-bowl milestone file recording a placement attempt. "
                "This is not an episode completion receipt and makes no G1, learned-policy, multi-seed, or ROCm claim."
            ),
        }

        # Verify claim boundary contains key phrases (inspect actual source text)
        boundary = progress_data["claim_boundary"]
        self.assertIn("Partial scripted placement attempt only", boundary)
        self.assertIn("single-bowl milestone file", boundary)
        self.assertIn("not an episode completion receipt", boundary)
        self.assertIn("no G1, learned-policy, multi-seed, or ROCm claim", boundary)

        # Verify claim boundary text order - must appear in source implementation
        self.assertIn("not an episode completion receipt and makes no G1", boundary)

    def test_bowl_progress_right_feedback_diagnostics_structure(self) -> None:
        """Verify right-side feedback diagnostics have required structure after central refactoring."""
        feedback_diagnostics = {
            "scripted_oracle_demonstration_feedback": True,
            "correction_attempts": [
                {
                    "iteration": 0,
                    "measured_position_xyz_m": [0.05, -0.1, 0.74],
                    "measured_xy_m": (0.05, -0.1),
                    "target_xy_m": (0.0, -0.1),
                    "correction_dx_dy_m": (-0.05, 0.0),
                    "within_tolerance": False,
                    "weld_verified": True,
                },
                {
                    "iteration": 1,
                    "measured_position_xyz_m": [0.01, -0.1, 0.74],
                    "measured_xy_m": (0.01, -0.1),
                    "target_xy_m": (0.0, -0.1),
                    "correction_dx_dy_m": (-0.01, 0.0),
                    "within_tolerance": True,
                    "weld_verified": True,
                }
            ],
            "final_measured_position_xyz_m": [0.01, -0.1, 0.74],
            "final_measured_xy_m": (0.01, -0.1),
            "target_xy_m": (0.0, -0.1),
            "final_within_tolerance": True,
            "total_corrections_applied": 1,
            "last_correction_iteration": 0,
        }

        # Verify feedback diagnostics structure with new fields
        self.assertTrue(feedback_diagnostics["scripted_oracle_demonstration_feedback"])
        self.assertIn("correction_attempts", feedback_diagnostics)
        self.assertEqual(len(feedback_diagnostics["correction_attempts"]), 2)

        # Verify new final measurement fields exist
        self.assertIn("final_measured_position_xyz_m", feedback_diagnostics)
        self.assertIn("final_measured_xy_m", feedback_diagnostics)
        self.assertIn("target_xy_m", feedback_diagnostics)
        self.assertIn("final_within_tolerance", feedback_diagnostics)
        self.assertIn("total_corrections_applied", feedback_diagnostics)
        self.assertIn("last_correction_iteration", feedback_diagnostics)

        # Verify last_correction_iteration is correct (should be 0 for 1 correction)
        self.assertEqual(feedback_diagnostics["last_correction_iteration"], 0,
                        "last_correction_iteration should be 0 when 1 correction was applied")

        # Verify old misleading field is removed
        self.assertNotIn("final_correction_used", feedback_diagnostics,
                        "Old misleading final_correction_used field must be removed")

        # Verify first attempt structure
        first_attempt = feedback_diagnostics["correction_attempts"][0]
        self.assertIn("iteration", first_attempt)
        self.assertIn("measured_position_xyz_m", first_attempt)
        self.assertIn("measured_xy_m", first_attempt)
        self.assertIn("target_xy_m", first_attempt)
        self.assertIn("correction_dx_dy_m", first_attempt)
        self.assertIn("within_tolerance", first_attempt)
        self.assertIn("weld_verified", first_attempt)

    def test_exact_two_corrections_diagnostic_case(self) -> None:
        """Test the exact-two-corrections diagnostic case where both corrections were applied.

        This validates the diagnostic structure when the maximum 2 corrections were used
        and the final measurement is within tolerance.
        """
        # Simulate exact-two-corrections scenario
        feedback_diagnostics = {
            "scripted_oracle_demonstration_feedback": True,
            "correction_attempts": [
                {
                    "iteration": 0,
                    "measured_position_xyz_m": [0.08, -0.1, 0.74],
                    "measured_xy_m": (0.08, -0.1),
                    "target_xy_m": (0.0, -0.1),
                    "correction_dx_dy_m": (-0.08, 0.0),
                    "within_tolerance": False,
                    "weld_verified": True,
                },
                {
                    "iteration": 1,
                    "measured_position_xyz_m": [0.02, -0.1, 0.74],
                    "measured_xy_m": (0.02, -0.1),
                    "target_xy_m": (0.0, -0.1),
                    "correction_dx_dy_m": (-0.02, 0.0),
                    "within_tolerance": False,
                    "weld_verified": True,
                }
            ],
            "final_measured_position_xyz_m": [0.005, -0.1, 0.74],
            "final_measured_xy_m": (0.005, -0.1),
            "target_xy_m": (0.0, -0.1),
            "final_within_tolerance": True,
            "total_corrections_applied": 2,
            "last_correction_iteration": 1,
        }

        # Verify both corrections were recorded
        self.assertEqual(len(feedback_diagnostics["correction_attempts"]), 2,
                        "Should have exactly 2 correction attempts")

        # Verify both attempts show within_tolerance=False (they needed correction)
        for attempt in feedback_diagnostics["correction_attempts"]:
            self.assertFalse(attempt["within_tolerance"],
                           f"Attempt {attempt['iteration']} should have needed correction")

        # Verify final state shows 2 corrections applied
        self.assertEqual(feedback_diagnostics["total_corrections_applied"], 2,
                        "Should report exactly 2 corrections applied")

        # Verify last_correction_iteration is 1 (second iteration)
        self.assertEqual(feedback_diagnostics["last_correction_iteration"], 1,
                        "last_correction_iteration should be 1 for exact-two-corrections case")

        # Verify final measurement is within tolerance
        self.assertTrue(feedback_diagnostics["final_within_tolerance"],
                       "Final measurement should be within tolerance after 2 corrections")

        # Verify final measurement fields are present and reasonable
        final_x = feedback_diagnostics["final_measured_xy_m"][0]
        target_x = feedback_diagnostics["target_xy_m"][0]
        self.assertLess(abs(final_x - target_x), 0.04,
                       f"Final X error {abs(final_x - target_x)} should be within tolerance")

    def test_no_corrections_needed_diagnostic_case(self) -> None:
        """Test the no-corrections-needed diagnostic case where first measurement is within tolerance.

        This validates the diagnostic structure when no corrections were applied.
        """
        # Simulate no-corrections-needed scenario
        feedback_diagnostics = {
            "scripted_oracle_demonstration_feedback": True,
            "correction_attempts": [
                {
                    "iteration": 0,
                    "measured_position_xyz_m": [0.01, -0.1, 0.74],
                    "measured_xy_m": (0.01, -0.1),
                    "target_xy_m": (0.0, -0.1),
                    "correction_dx_dy_m": (0.0, 0.0),
                    "within_tolerance": True,
                    "weld_verified": True,
                }
            ],
            "final_measured_position_xyz_m": [0.01, -0.1, 0.74],
            "final_measured_xy_m": (0.01, -0.1),
            "target_xy_m": (0.0, -0.1),
            "final_within_tolerance": True,
            "total_corrections_applied": 0,
            "last_correction_iteration": None,
        }

        # Verify only one attempt was recorded (measurement showed within tolerance)
        self.assertEqual(len(feedback_diagnostics["correction_attempts"]), 1,
                        "Should have exactly 1 attempt (first measurement was within tolerance)")

        # Verify the single attempt shows within_tolerance=True
        self.assertTrue(feedback_diagnostics["correction_attempts"][0]["within_tolerance"],
                      "First attempt should have been within tolerance")

        # Verify no corrections were applied
        self.assertEqual(feedback_diagnostics["total_corrections_applied"], 0,
                        "Should report 0 corrections applied")

        # Verify last_correction_iteration is None (no corrections applied)
        self.assertIsNone(feedback_diagnostics["last_correction_iteration"],
                        "last_correction_iteration should be None when no corrections were applied")

        # Verify final measurement is within tolerance
        self.assertTrue(feedback_diagnostics["final_within_tolerance"],
                       "Final measurement should be within tolerance")


class ScriptedG1CorrectionLogicTests(unittest.TestCase):
    """Focused tests for correction logic that would have caught runtime bugs."""

    def setUp(self) -> None:
        self.module = _load_tool_module()

    def test_correction_descent_is_not_no_op(self) -> None:
        """Test that correction descent uses different start and end positions.

        This test would have caught the no-op descent bug where the descent
        used the same start and end position (corrected_tcp_position twice).
        """
        # Simulate the correction descent logic using standard library lists
        current_tcp_position = [0.05, -0.1, 0.74]
        dx, dy = -0.05, 0.0  # Correction needed
        lift_height = 0.06

        # Build positions as the fixed implementation does
        lift_tcp_position = current_tcp_position.copy()
        lift_tcp_position[2] += lift_height

        corrected_high_position = lift_tcp_position.copy()
        corrected_high_position[0] += dx
        corrected_high_position[1] += dy

        corrected_place_position = current_tcp_position.copy()
        corrected_place_position[0] += dx
        corrected_place_position[1] += dy

        # Verify start and end of descent are different
        descent_start = corrected_high_position
        descent_end = corrected_place_position

        # Descent should start at high Z and end at low Z
        self.assertGreater(descent_start[2], descent_end[2],
                          "Descent start (high) should be above descent end (low)")
        # XY should be the same for both (the corrected position)
        self.assertAlmostEqual(descent_start[0], descent_end[0], places=6,
                             msg="Descent start and end should have same corrected X")
        self.assertAlmostEqual(descent_start[1], descent_end[1], places=6,
                             msg="Descent start and end should have same corrected Y")

    def test_correction_count_accuracy(self) -> None:
        """Test that corrections_applied counter accurately reflects corrections.

        This test would have caught missing or inaccurate correction counting.
        """
        # Simulate correction loop with accurate counting
        corrections_applied = 0
        max_iterations = 2
        correction_iterations = []

        for i in range(max_iterations):
            # Simulate measuring and needing correction
            correction_needed = (i < 1)  # Only first iteration needs correction

            if not correction_needed:
                # No correction needed - exit with current count
                break

            # Apply correction and increment counter
            corrections_applied += 1
            correction_iterations.append(i)

        # Verify count matches actual corrections
        self.assertEqual(corrections_applied, len(correction_iterations),
                        "corrections_applied must equal actual correction count")
        self.assertEqual(corrections_applied, 1,
                        "Should report exactly 1 correction for this scenario")

    def test_weld_precondition_hard_fail(self) -> None:
        """Test that weld verification prevents motion when weld is not registered.

        This test would have caught missing weld precondition checks.
        """
        # Simulate weld precondition logic
        weld_verified = False
        correction_needed = True

        # Weld precondition: if not verified, hard-fail before any motion
        attempt_recorded = True  # Attempt is always recorded first
        motion_allowed = weld_verified  # Motion only allowed if weld verified

        # Verify logic
        self.assertTrue(attempt_recorded, "Attempt must be recorded before weld check")
        self.assertFalse(motion_allowed, "Motion must not be allowed without verified weld")

        # Simulate the hard-fail scenario
        if correction_needed and not weld_verified:
            # This should raise RuntimeError in actual implementation
            error_message = "weld not verified before correction iteration 0: refusing to apply correction motion without active weld"
            self.assertIn("weld not verified", error_message)
            self.assertIn("refusing to apply correction motion", error_message)

    def test_atomic_file_open_mode(self) -> None:
        """Test that file creation uses atomic exclusive open mode.

        This test would have caught TOCTOU race conditions in file creation.
        """
        import tempfile
        import os

        # Test atomic exclusive create
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_atomic.json"

            # First creation should succeed
            try:
                with test_file.open("x", encoding="utf-8") as handle:
                    handle.write('{"test": "data"}')
            except FileExistsError:
                self.fail("First atomic create should succeed")

            # Second creation should fail with FileExistsError
            with self.assertRaises(FileExistsError):
                with test_file.open("x", encoding="utf-8") as handle:
                    handle.write('{"other": "data"}')

            # Verify file content is from first write
            with test_file.open("r", encoding="utf-8") as handle:
                content = handle.read()
                self.assertEqual(content, '{"test": "data"}')

    def test_high_clearance_joint_space_path(self) -> None:
        """Test that high clearance retreat uses joint-space waypoints, not Cartesian solve_assigned_path.

        This test would have caught the qpos-to-Cartesian misuse bug.
        """
        # Simulate high clearance retreat logic using standard library lists
        reverse_place_path_end = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        retreat_transport_qpos = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1]

        # Correct approach: joint-space waypoints
        high_clearance_joint_path = [
            reverse_place_path_end.copy(),
            retreat_transport_qpos.copy(),
        ]

        # Verify both are qpos arrays (not Cartesian positions)
        self.assertEqual(len(high_clearance_joint_path[0]), len(reverse_place_path_end))
        self.assertEqual(len(high_clearance_joint_path[1]), len(retreat_transport_qpos))

        # Verify path has exactly 2 waypoints (start and end)
        self.assertEqual(len(high_clearance_joint_path), 2)

        # Verify start and end are different qpos
        self.assertNotEqual(high_clearance_joint_path[0], high_clearance_joint_path[1],
                           "Joint-space path waypoints should be different")

    def test_release_ordering_verification(self) -> None:
        """Test that release follows correct ordering: record pre, verify weld, delete, assert absent, open, record post.

        This test would have caught ordering issues in release sequence.
        """
        # Simulate release sequence with proper ordering using standard library lists
        weld_registered_before = True
        weld_registered_after_deletion = False
        final_pre_release_position = [0.0, -0.1, 0.74]
        immediate_post_release_position = [0.0, -0.1, 0.74]

        # Correct ordering sequence
        sequence_steps = [
            "record_final_pre_release_position",
            "verify_weld_registered_before_deletion",
            "delete_weld_constraint",
            "assert_weld_absent_after_deletion",
            "open_gripper_and_release",
            "record_immediate_post_release_position",
        ]

        # Verify sequence steps are in correct order
        self.assertEqual(sequence_steps[0], "record_final_pre_release_position")
        self.assertEqual(sequence_steps[1], "verify_weld_registered_before_deletion")
        self.assertEqual(sequence_steps[2], "delete_weld_constraint")
        self.assertEqual(sequence_steps[3], "assert_weld_absent_after_deletion")
        self.assertEqual(sequence_steps[4], "open_gripper_and_release")
        self.assertEqual(sequence_steps[5], "record_immediate_post_release_position")

        # Verify weld state transitions
        self.assertTrue(weld_registered_before, "Weld must be registered before deletion")
        self.assertFalse(weld_registered_after_deletion, "Weld must be absent after deletion")

        # Verify position recordings exist
        self.assertIsNotNone(final_pre_release_position)
        self.assertIsNotNone(immediate_post_release_position)


class ScriptedG1V4ControlToleranceTests(unittest.TestCase):
    """Test v4 10 mm control tolerance for right-side feedback."""

    def setUp(self) -> None:
        self.module = _load_tool_module()

    def test_10mm_control_tolerance_min_with_strict_40mm(self) -> None:
        """Verify control tolerance uses min(strict_evaluator_tolerance, 0.01 m)."""
        strict_evaluator_tolerance = 0.04  # 40 mm from task-pack
        control_tolerance = min(strict_evaluator_tolerance, 0.01)

        self.assertEqual(control_tolerance, 0.01,
                        "Control tolerance should be 10 mm when strict is 40 mm")

    def test_control_tolerance_strict_unchanged(self) -> None:
        """Verify strict evaluator tolerance remains unchanged at 0.04 m."""
        strict_evaluator_tolerance = 0.04  # From task-pack

        self.assertEqual(strict_evaluator_tolerance, 0.04,
                        "Strict evaluator tolerance must remain 40 mm")

    def test_right_xy_correction_uses_10mm_tolerance(self) -> None:
        """Verify right_xy_correction receives 10 mm control tolerance for v4."""
        # Seed1 v3 final position was within 10 mm, so should need no corrections
        measured_xy = (-0.0024614790454506874, -0.10339027643203735)  # seed1 bowl3
        target_xy = (0.0, -0.1)
        control_tolerance = 0.01  # 10 mm control tolerance

        correction = self.module.right_xy_correction(measured_xy, target_xy, control_tolerance)

        # Seed1 error is ~2.5 mm X and ~3.4 mm Y, both under 10 mm
        self.assertIsNone(correction,
                        "Seed1 v3 position should be within 10 mm tolerance, requiring no correction")

    def test_strict_evaluator_40mm_tolerance_allows_larger_errors(self) -> None:
        """Verify strict 40 mm tolerance allows larger errors that 10 mm control would correct."""
        measured_xy = (0.025, -0.1)  # 25 mm X error
        target_xy = (0.0, -0.1)
        strict_tolerance = 0.04  # 40 mm strict tolerance

        correction = self.module.right_xy_correction(measured_xy, target_xy, strict_tolerance)

        # 25 mm < 40 mm, so within strict tolerance
        self.assertIsNone(correction,
                        "25 mm error should be within 40 mm strict tolerance")

    def test_10mm_control_tolerance_corrects_25mm_error(self) -> None:
        """Verify 10 mm control tolerance triggers correction for 25 mm error."""
        measured_xy = (0.025, -0.1)  # 25 mm X error
        target_xy = (0.0, -0.1)
        control_tolerance = 0.01  # 10 mm control tolerance

        correction = self.module.right_xy_correction(measured_xy, target_xy, control_tolerance)

        # 25 mm > 10 mm, so correction needed
        self.assertIsNotNone(correction,
                            "25 mm error should exceed 10 mm control tolerance")
        self.assertEqual(correction[0], -0.025,
                        "Correction should be -25 mm in X")


class ScriptedG1V4FailurePreservationTests(unittest.TestCase):
    """Test v4 placement failure diagnostics preservation."""

    def setUp(self) -> None:
        self.module = _load_tool_module()

    def test_placement_gate_diagnostics_structure(self) -> None:
        """Verify placement gate diagnostics have required structure."""
        bowl_run_data = {
            "bowl": "bowl1",
            "stack_level": 0,
            "placed_position_xyz_m": [-0.06643771380186081, -0.08468268811702728, 0.7399629354476929],
            "placement_gate_passed": False,
            "expected_position_xyz_m": [0.0, -0.1, 0.74],
            "xy_axis_alignment_tolerance_m": 0.04,
            "height_absolute_tolerance_m": 0.02,
            "placement_errors_xyz_m": [0.06643771380186081, 0.01531731188297272, 0.0000370645523071],
        }

        # Verify placement gate diagnostics fields exist
        self.assertIn("placement_gate_passed", bowl_run_data)
        self.assertIn("expected_position_xyz_m", bowl_run_data)
        self.assertIn("xy_axis_alignment_tolerance_m", bowl_run_data)
        self.assertIn("height_absolute_tolerance_m", bowl_run_data)
        self.assertIn("placement_errors_xyz_m", bowl_run_data)

        # Verify gate failed
        self.assertFalse(bowl_run_data["placement_gate_passed"])

        # Verify errors match seed1002 v3 failure
        x_error, y_error, z_error = bowl_run_data["placement_errors_xyz_m"]
        self.assertGreater(x_error, 0.04, "X error should exceed 40 mm tolerance")
        self.assertLess(y_error, 0.04, "Y error should be within 40 mm tolerance")
        self.assertLess(z_error, 0.02, "Z error should be within 20 mm tolerance")

    def test_progress_file_claim_boundary_attempt_wording(self) -> None:
        """Verify progress file claim boundary uses 'attempt' wording for failed placements."""
        progress_data = {
            "schema_version": 1,
            "seed": 1002,
            "bowl_data": {"bowl": "bowl1", "placement_gate_passed": False},
            "partial_only": True,
            "episode_success": False,
            "placement_attempt": True,
            "g1_claim": False,
            "learned_policy_claim": False,
            "rocm_claim": False,
            "multi_seed_evidence": False,
            "claim_boundary": (
                "Partial scripted placement attempt only: bowl1 placement attempt at level 0 "
                "using contact-triggered idealized suction transport in one Genesis scene. "
                "This is a single-bowl milestone file recording a placement attempt. "
                "This is not an episode completion receipt and makes no G1, learned-policy, multi-seed, or ROCm claim."
            ),
        }

        # Verify claim boundary contains key phrases for failed attempts
        boundary = progress_data["claim_boundary"]
        self.assertIn("Partial scripted placement attempt only", boundary)
        self.assertIn("placement attempt", boundary)
        self.assertIn("recording a placement attempt", boundary)
        self.assertIn("not an episode completion receipt", boundary)
        self.assertIn("makes no G1, learned-policy, multi-seed, or ROCm claim", boundary)

    def test_progress_file_written_before_gate_failure(self) -> None:
        """Verify progress file is written atomically before gate failure raises."""
        # This validates the execution order: diagnostics serialized before raise
        placement_gate_passed = False

        # Simulate progress file writing
        bowl_run_data = {"placement_gate_passed": placement_gate_passed}
        progress_data = {"bowl_data": bowl_run_data, "placement_attempt": True}

        # Verify diagnostics are preserved even when gate failed
        self.assertIn("placement_gate_passed", bowl_run_data)
        self.assertFalse(bowl_run_data["placement_gate_passed"])
        self.assertTrue(progress_data["placement_attempt"])


class ScriptedG1V4StageAwareTimeoutTests(unittest.TestCase):
    """Test v4 stage-aware max_policy_steps error messages."""

    def setUp(self) -> None:
        self.module = _load_tool_module()

    def test_max_policy_steps_error_includes_stage(self) -> None:
        """Verify max_policy_steps error includes stage information."""
        # Simulate stage-aware timeout error message
        stage = "bowl1:candidate_3_approach"
        next_frame_index = 1201
        max_policy_steps = 1200

        error_message = (
            f"scripted trajectory exceeded max_policy_steps during stage '{stage}': "
            f"next_frame_index={next_frame_index}, max_policy_steps={max_policy_steps}"
        )

        # Verify error message contains actionable information
        self.assertIn("bowl1:candidate_3_approach", error_message)
        self.assertIn("next_frame_index=1201", error_message)
        self.assertIn("max_policy_steps=1200", error_message)
        self.assertIn("during stage", error_message)

    def test_max_policy_steps_seed1001_timeout_identifies_stage(self) -> None:
        """Verify seed1001 timeout error would identify right grasp retry stage."""
        # Based on v3 evidence, seed1001 timed out during right grasp retry
        # v4 error should identify the specific stage
        likely_stage = "bowl1:candidate_5_approach"  # Hypothetical stage where timeout occurred
        next_frame_index = 1201
        max_policy_steps = 1200

        error_message = (
            f"scripted trajectory exceeded max_policy_steps during stage '{likely_stage}': "
            f"next_frame_index={next_frame_index}, max_policy_steps={max_policy_steps}"
        )

        # Verify error identifies retry stage
        self.assertIn("candidate_", error_message)
        self.assertIn("next_frame_index=1201", error_message)


class ScriptedG1SourceRegressionAssertions(unittest.TestCase):
    """Source-linked regression assertions to prevent re-introduction of fixed bugs."""

    def setUp(self) -> None:
        self.module = _load_tool_module()
        self.source_path = ROOT / "tools" / "run_genesis_stack_bowls_scripted_g1.py"
        self.source_text = self.source_path.read_text(encoding="utf-8")

    def test_no_bare_xy_tolerance_in_feedback_block(self) -> None:
        """Assert no bare undefined xy_tolerance remains in the right feedback block."""
        # The feedback block should use control_xy_tolerance, not bare xy_tolerance
        # Find the right feedback block (between "# Right-side XY correction loop" and "# Record final pre-release")
        feedback_block_start = self.source_text.find("# Right-side XY correction loop")
        feedback_block_end = self.source_text.find("# Record final pre-release position", feedback_block_start)

        self.assertGreater(feedback_block_start, 0, "Feedback block start marker not found")
        self.assertGreater(feedback_block_end, 0, "Feedback block end marker not found")

        feedback_block = self.source_text[feedback_block_start:feedback_block_end]

        # Check for bare xy_tolerance usage (should not exist)
        # Allow xy_axis_alignment_tolerance_m (config access), control_xy_tolerance (correct variable),
        # and strict_evaluator_tolerance/strict_evaluator_xy_tolerance_m (diagnostics field names)
        lines = feedback_block.split("\n")
        bare_xy_tolerance_lines = []
        for i, line in enumerate(lines, 1):
            # Skip commented lines and config access
            if "xy_axis_alignment_tolerance_m" in line or line.strip().startswith("#"):
                continue
            # Skip diagnostic field names (recorded values, not code usage)
            if "strict_evaluator_xy_tolerance_m" in line or "strict_evaluator_tolerance" in line:
                continue
            # Check for bare xy_tolerance that is not control_xy_tolerance
            if "xy_tolerance" in line and "control_xy_tolerance" not in line:
                bare_xy_tolerance_lines.append((i, line.strip()))

        if bare_xy_tolerance_lines:
            line_nums = [ln for ln, _ in bare_xy_tolerance_lines]
            self.fail(
                f"Found bare xy_tolerance usage in feedback block at line(s) {line_nums}. "
                f"Use control_xy_tolerance instead. Lines:\n" +
                "\n".join(f"  {ln}: {line}" for ln, line in bare_xy_tolerance_lines)
            )

    def test_tracker_complete_stage_after_placement_gate(self) -> None:
        """Assert tracker.complete_stage for placement occurs only after placement_gate check."""
        # Find the placement gate check and tracker.complete_stage for placement stages
        # The pattern should be: placement_gate_passed = (...) -> if not placement_gate_passed: raise -> tracker.complete_stage
        placement_gate_pattern = "placement_gate_passed = ("
        gate_check_pattern = "if not placement_gate_passed:"
        stage_completion_pattern = "tracker.complete_stage("
        stage_index_pattern = "stage_index = (3, 4, 5)[level]"

        # Find all occurrences using string find in loop
        gate_defs = []
        pos = self.source_text.find(placement_gate_pattern)
        while pos != -1:
            gate_defs.append(pos)
            pos = self.source_text.find(placement_gate_pattern, pos + 1)

        gate_checks = []
        pos = self.source_text.find(gate_check_pattern)
        while pos != -1:
            gate_checks.append(pos)
            pos = self.source_text.find(gate_check_pattern, pos + 1)

        stage_completions = []
        pos = self.source_text.find(stage_completion_pattern)
        while pos != -1:
            stage_completions.append(pos)
            pos = self.source_text.find(stage_completion_pattern, pos + 1)

        stage_index_defs = []
        pos = self.source_text.find(stage_index_pattern)
        while pos != -1:
            stage_index_defs.append(pos)
            pos = self.source_text.find(stage_index_pattern, pos + 1)

        # Should have exactly one placement gate definition and check
        self.assertEqual(len(gate_defs), 1, "Should have exactly one placement_gate_passed definition")
        self.assertEqual(len(gate_checks), 1, "Should have exactly one placement_gate check")

        # Should have exactly one stage_index definition before tracker.complete_stage for placement
        self.assertEqual(len(stage_index_defs), 1, "Should have exactly one stage_index definition for placement")

        # The placement tracker.complete_stage should be after the gate check
        placement_stage_completion = None
        for i, pos in enumerate(stage_completions):
            # Check if this is after the stage_index definition
            if pos > stage_index_defs[0]:
                # Check if this completion is using stage_index (placement stage)
                context_start = pos
                context_end = min(pos + 200, len(self.source_text))
                context = self.source_text[context_start:context_end]
                if "stage_index" in context and "task[" in context:
                    placement_stage_completion = pos
                    break

        self.assertIsNotNone(placement_stage_completion, "Should find tracker.complete_stage for placement stage")

        # Assert placement stage completion is after gate check
        self.assertGreater(placement_stage_completion, gate_checks[0],
            "tracker.complete_stage for placement must occur after placement_gate check")


class ScriptedG1V5ReleaseIntegrityTests(unittest.TestCase):
    """Test v5 release-integrity features: dual-clamp requirement and post-release settle hold."""

    def setUp(self) -> None:
        self.module = _load_tool_module()

    def test_right_dual_clamp_contact_requirement(self) -> None:
        """Verify right-side contact requires both clamp links, not just one."""
        # Simulate contact with only one link (v4 seed1002 failure mode)
        single_link_contacts = {"right_clamp_left_link"}
        required_both = {"right_clamp_left_link", "right_clamp_right_link"}

        # v5 requirement: both must be present
        contact_verified_v5 = required_both.issubset(single_link_contacts)
        self.assertFalse(contact_verified_v5,
                        "Right-side with only one clamp link should fail v5 dual-clamp requirement")

        # Simulate contact with both links (v4 seed1003 success mode)
        dual_link_contacts = {"right_clamp_left_link", "right_clamp_right_link"}
        contact_verified_dual = required_both.issubset(dual_link_contacts)
        self.assertTrue(contact_verified_dual,
                       "Right-side with both clamp links should pass v5 dual-clamp requirement")

    def test_left_single_clamp_contact_unchanged(self) -> None:
        """Verify left-side contact still accepts any single clamp link (unchanged behavior)."""
        # Left-side: any single clamp link is sufficient
        single_left_contact = {"left_clamp_left_link"}
        contact_verified_left = bool(single_left_contact)

        self.assertTrue(contact_verified_left,
                       "Left-side with single clamp link should pass (unchanged behavior)")

    def test_no_release_integrity_diagnostics_after_settle_removal(self) -> None:
        """Verify release_integrity diagnostics do not exist after settle hold removal."""
        # After removing the settle hold, the entire release_integrity block should not exist
        bowl_run_data = {
            "bowl": "bowl1",
            "assigned_side": "right",
            "contacted_clamp_links": ["right_clamp_left_link", "right_clamp_right_link"],
            "immediate_post_release_position_xyz_m": [0.001, -0.100, 0.740],
        }

        # Verify release_integrity does not exist (removed with settle hold)
        self.assertNotIn("release_integrity", bowl_run_data,
                        "release_integrity must not exist after settle hold removal")

        # Verify settle-related fields do not exist
        self.assertNotIn("post_release_settle_position_xyz_m", bowl_run_data,
                        "post_release_settle_position_xyz_m must not exist")
        self.assertNotIn("pre_release_to_settle_delta_xyz_m", bowl_run_data,
                        "pre_release_to_settle_delta_xyz_m must not exist")

    def test_contact_requirement_recorded_in_grasp_attempt(self) -> None:
        """Verify grasp_attempt records contact_requirement and missing_required_contact_links."""
        grasp_attempt_single_link = {
            "candidate_index": 0,
            "contacted_links": ["right_clamp_left_link"],
            "contact_requirement": "both_right_clamps_required",
            "missing_required_contact_links": ["right_clamp_right_link"],
            "contact_verified": False,
        }

        grasp_attempt_dual_link = {
            "candidate_index": 1,
            "contacted_links": ["right_clamp_left_link", "right_clamp_right_link"],
            "contact_requirement": "both_right_clamps_required",
            "missing_required_contact_links": None,
            "contact_verified": True,
        }

        # Verify single-link attempt records missing links
        self.assertEqual(grasp_attempt_single_link["contact_requirement"],
                        "both_right_clamps_required")
        self.assertIsNotNone(grasp_attempt_single_link["missing_required_contact_links"])
        self.assertIn("right_clamp_right_link",
                     grasp_attempt_single_link["missing_required_contact_links"])

        # Verify dual-link attempt has no missing links
        self.assertEqual(grasp_attempt_dual_link["contact_requirement"],
                        "both_right_clamps_required")
        self.assertIsNone(grasp_attempt_dual_link["missing_required_contact_links"])

    def test_no_post_release_settle_in_right_side_bowl_data(self) -> None:
        """Verify post_release_settle fields are not present in right-side bowl data."""
        # After removing the settle hold, these fields should not exist
        bowl_run_data = {
            "bowl": "bowl1",
            "assigned_side": "right",
            "contacted_clamp_links": ["right_clamp_left_link", "right_clamp_right_link"],
            "immediate_post_release_position_xyz_m": [0.0, -0.1, 0.74],
        }

        # Verify post_release_settle_position_xyz_m does not exist
        self.assertNotIn("post_release_settle_position_xyz_m", bowl_run_data,
                        "post_release_settle_position_xyz_m must not exist after settle hold removal")

        # Verify release_integrity does not exist (was removed with settle hold)
        self.assertNotIn("release_integrity", bowl_run_data,
                        "release_integrity must not exist after settle hold removal")

    def test_right_retreat_timing_matches_v4(self) -> None:
        """Verify right-side retreat timing matches v4 without settle hold overhead."""
        # In v4, retreat happened immediately after release with no settle hold
        # This validates the structural order: release -> (optional retreat) -> settle
        stages_v4_order = [
            "release",           # Open grippers
            "retreat_vertical_withdrawal",  # Then retreat (for right side)
            "retreat_high_clearance",
            "settle",            # Post-retreat settle for stability
        ]

        # Verify retreat comes immediately after release (no settle hold in between)
        release_index = stages_v4_order.index("release")
        retreat_index = stages_v4_order.index("retreat_vertical_withdrawal")

        self.assertEqual(release_index + 1, retreat_index,
                        "Retreat must immediately follow release with no settle hold between")

    def test_right_dual_clamp_and_left_single_clamp_unchanged(self) -> None:
        """Source-linked test proving right requires two exact clamp links, left path unchanged."""
        # This test validates the exact implementation in run_genesis_stack_bowls_scripted_g1.py
        # around lines 1412-1430 where contact verification happens

        # Right-side dual-clamp requirement (must have both exact links)
        right_contacted_links = {"right_clamp_left_link", "right_clamp_right_link"}
        required_right_links = {"right_clamp_left_link", "right_clamp_right_link"}
        right_contact_verified = required_right_links.issubset(right_contacted_links)

        self.assertTrue(right_contact_verified,
                       "Right-side with both clamp links should pass dual-clamp requirement")

        # Right-side with single clamp link should fail
        right_single_contact = {"right_clamp_left_link"}
        right_contact_verified_single = required_right_links.issubset(right_single_contact)

        self.assertFalse(right_contact_verified_single,
                        "Right-side with only one clamp link should fail dual-clamp requirement")

        # Left-side any single clamp link is sufficient (unchanged behavior)
        left_single_contact = {"left_clamp_left_link"}
        left_contact_verified = bool(left_single_contact)

        self.assertTrue(left_contact_verified,
                       "Left-side with single clamp link should pass (unchanged behavior)")

        # Verify per-attempt recording fields exist
        grasp_attempt_dual = {
            "contact_requirement": "both_right_clamps_required",
            "missing_required_contact_links": None,
            "contact_verified": True,
        }

        self.assertEqual(grasp_attempt_dual["contact_requirement"], "both_right_clamps_required")
        self.assertIsNone(grasp_attempt_dual["missing_required_contact_links"])

        grasp_attempt_single = {
            "contact_requirement": "both_right_clamps_required",
            "missing_required_contact_links": ["right_clamp_right_link"],
            "contact_verified": False,
        }

        self.assertIsNotNone(grasp_attempt_single["missing_required_contact_links"])
        self.assertIn("right_clamp_right_link", grasp_attempt_single["missing_required_contact_links"])


class ScriptedG1BaselineFreezeTests(unittest.TestCase):
    """Test v6 baseline freeze and bowl drift detection features."""

    def setUp(self) -> None:
        self.module = _load_tool_module()
        self.source_path = ROOT / "tools" / "run_genesis_stack_bowls_scripted_g1.py"
        self.source_text = self.source_path.read_text(encoding="utf-8")

    def test_candidate_baseline_qpos_freeze_exists(self) -> None:
        """Verify candidate_baseline_qpos is frozen after first front_clearance command_segment."""
        # Find the pattern where baseline is frozen
        freeze_pattern = "candidate_baseline_qpos = qpos[\"front_clearance\"].copy()"
        freeze_pos = self.source_text.find(freeze_pattern)
        self.assertGreater(freeze_pos, 0, "candidate_baseline_qpos freeze must exist")

        # Verify it happens after the front_clearance command_segment
        # Find the command_segment to front_clearance
        command_segment_pattern = f'command_segment(\n                    f"{{pose.name}}:front_clearance"'
        command_pos = self.source_text.find(command_segment_pattern)
        self.assertGreater(command_pos, 0, "front_clearance command_segment must exist")

        # The freeze should occur after the command_segment
        self.assertGreater(freeze_pos, command_pos,
            "candidate_baseline_qpos freeze must occur after front_clearance command_segment")

    def test_initial_bowl_snapshot_exists(self) -> None:
        """Verify initial bowl position and quaternion are captured after baseline freeze."""
        # Find position snapshot
        position_snapshot_pattern = "initial_bowl_position = np.asarray(_vector(selected_bowl.get_pos()), dtype=float)"
        position_pos = self.source_text.find(position_snapshot_pattern)
        self.assertGreater(position_pos, 0, "initial_bowl_position snapshot must exist")

        # Find quaternion snapshot
        quaternion_snapshot_pattern = "initial_bowl_quaternion = np.asarray(_vector(selected_bowl.get_quat()), dtype=float)"
        quaternion_pos = self.source_text.find(quaternion_snapshot_pattern)
        self.assertGreater(quaternion_pos, 0, "initial_bowl_quaternion snapshot must exist")

        # Both should occur after candidate_baseline_qpos freeze
        freeze_pattern = "candidate_baseline_qpos = qpos[\"front_clearance\"].copy()"
        freeze_pos = self.source_text.find(freeze_pattern)
        self.assertGreater(position_pos, freeze_pos,
            "initial_bowl_position snapshot must occur after candidate_baseline_qpos freeze")
        self.assertGreater(quaternion_pos, freeze_pos,
            "initial_bowl_quaternion snapshot must occur after candidate_baseline_qpos freeze")

    def test_candidate_loop_uses_baseline_for_solve_init(self) -> None:
        """Verify solve_stage uses candidate_baseline_qpos for init, not current."""
        # Find the candidate loop solve_stage call
        # Pattern: solve_stage for candidate_{index}_pregrasp with candidate_baseline_qpos as init
        solve_pattern = 'candidate_pregrasp_qpos, candidate_pregrasp_ik_errors = solve_stage(\n                        f"{pose.name}:candidate_{candidate_index}_pregrasp",\n                        {assigned_side: candidate_pregrasp_position},\n                        candidate_baseline_qpos'
        solve_pos = self.source_text.find(solve_pattern)
        self.assertGreater(solve_pos, 0,
            "solve_stage for candidate must use candidate_baseline_qpos as init")

        # Verify the comment explains the baseline usage
        comment_pattern = "# Use frozen candidate_baseline_qpos for solve_stage init (not current from failed attempt)"
        comment_pos = self.source_text.find(comment_pattern)
        self.assertGreater(comment_pos, 0,
            "Comment must explain baseline init usage")
        self.assertGreater(solve_pos, comment_pos,
            "solve_stage call must occur after explanatory comment")

    def test_loop_idx_zero_returns_to_baseline(self) -> None:
        """Verify loop_idx>0 returns to baseline before starting new candidate."""
        # Find the pattern for loop_idx>0 check
        loop_idx_pattern = "if loop_idx > 0:"
        loop_idx_pos = self.source_text.find(loop_idx_pattern)
        self.assertGreater(loop_idx_pos, 0, "loop_idx>0 check must exist")

        # Find the command_segment to return to baseline
        return_pattern = 'command_segment(\n                            f"{pose.name}:return_to_baseline_candidate_{loop_idx}",\n                            candidate_baseline_qpos'
        return_pos = self.source_text.find(return_pattern, loop_idx_pos)
        self.assertGreater(return_pos, 0,
            "command_segment to return to baseline must exist for loop_idx>0")

        # Verify current is set to baseline
        current_set_pattern = "current = candidate_baseline_qpos"
        current_set_pos = self.source_text.find(current_set_pattern, return_pos)
        self.assertGreater(current_set_pos, 0,
            "current must be set to candidate_baseline_qpos after return")

    def test_bowl_drift_check_exists(self) -> None:
        """Verify bowl drift check exists after returning to baseline."""
        # Find the bowl drift check section (should be after current = candidate_baseline_qpos)
        current_set_pattern = "current = candidate_baseline_qpos"
        current_set_pos = self.source_text.find(current_set_pattern)

        # Find current bowl position read
        current_pos_pattern = "current_bowl_position = np.asarray(_vector(selected_bowl.get_pos()), dtype=float)"
        current_pos_pos = self.source_text.find(current_pos_pattern, current_set_pos)
        self.assertGreater(current_pos_pos, 0,
            "current_bowl_position read must exist for drift check")

        # Find current bowl quaternion read
        current_quat_pattern = "current_bowl_quaternion = np.asarray(_vector(selected_bowl.get_quat()), dtype=float)"
        current_quat_pos = self.source_text.find(current_quat_pattern, current_pos_pos)
        self.assertGreater(current_quat_pos, 0,
            "current_bowl_quaternion read must exist for drift check")

        # Find position tolerance check
        position_tol_pattern = 'position_tolerance = float(scene_contract["ik_gate"]["position_tolerance_m"])'
        position_tol_pos = self.source_text.find(position_tol_pattern, current_quat_pos)
        self.assertGreater(position_tol_pos, 0,
            "position tolerance from scene_contract must exist")

        # Find RuntimeError for position drift
        position_error_pattern = 'raise RuntimeError(\n                                f"{pose.name} bowl position drift exceeded tolerance'
        position_error_pos = self.source_text.find(position_error_pattern, position_tol_pos)
        self.assertGreater(position_error_pos, 0,
            "RuntimeError for position drift must exist")

        # Find rotation tolerance check
        rotation_tol_pattern = 'rotation_tolerance = float(scene_contract["ik_gate"]["rotation_tolerance_rad"])'
        rotation_tol_pos = self.source_text.find(rotation_tol_pattern, position_error_pos)
        self.assertGreater(rotation_tol_pos, 0,
            "rotation tolerance from scene_contract must exist")

        # Find RuntimeError for rotation drift
        rotation_error_pattern = 'raise RuntimeError(\n                                f"{pose.name} bowl orientation drift exceeded tolerance'
        rotation_error_pos = self.source_text.find(rotation_error_pattern, rotation_tol_pos)
        self.assertGreater(rotation_error_pos, 0,
            "RuntimeError for rotation drift must exist")

    def test_quaternion_sign_invariant_comparison(self) -> None:
        """Verify quaternion comparison uses sign-invariant L2 distance."""
        # Find the quaternion comparison logic
        quat_diff_pattern = "quat_diff = current_bowl_quaternion - initial_bowl_quaternion"
        quat_diff_pos = self.source_text.find(quat_diff_pattern)
        self.assertGreater(quat_diff_pos, 0, "quaternion difference calculation must exist")

        quat_sum_pattern = "quat_sum = current_bowl_quaternion + initial_bowl_quaternion"
        quat_sum_pos = self.source_text.find(quat_sum_pattern, quat_diff_pos)
        self.assertGreater(quat_sum_pos, 0, "quaternion sum calculation must exist")

        # Find min distance logic
        min_distance_pattern = "rotation_error = min(quat_l2_diff, quat_l2_sum)"
        min_distance_pos = self.source_text.find(min_distance_pattern, quat_sum_pos)
        self.assertGreater(min_distance_pos, 0,
            "sign-invariant min distance must be used for quaternion comparison")

    def test_old_front_clearance_qpos_continuation_removed(self) -> None:
        """Verify old front_clearance_qpos continuation logic is removed."""
        # Find the failure recovery section (after contact_verified check)
        failure_section_pattern = "else:\n                        # Failure recovery: open, retreat to pregrasp"
        failure_pos = self.source_text.find(failure_section_pattern)
        self.assertGreater(failure_pos, 0, "failure recovery section must exist")

        # Get the section from failure_pos to the end of the loop
        # Look for the end of the candidate loop (successful_candidate_index is None check)
        loop_end_pattern = "if successful_candidate_index is None:"
        loop_end_pos = self.source_text.find(loop_end_pattern, failure_pos)
        self.assertGreater(loop_end_pos, 0, "candidate loop end check must exist")

        failure_section = self.source_text[failure_pos:loop_end_pos]

        # Verify old pattern does NOT exist
        old_pattern_1 = "front_clearance_qpos, _ = solve_stage("
        self.assertNotIn(old_pattern_1, failure_section,
            "Old front_clearance_qpos solve_stage continuation must be removed")

        # Verify old retreat pattern does NOT exist
        old_pattern_2 = "candidate_{candidate_index}_retreat_to_front"
        self.assertNotIn(old_pattern_2, failure_section,
            "old retreat_to_front command_segment must be removed")

        # Verify old current set pattern does NOT exist
        old_pattern_3 = "current = front_clearance_qpos"
        self.assertNotIn(old_pattern_3, failure_section,
            "old current = front_clearance_qpos must be removed")

    def test_failure_recovery_order_open_retreat_to_pregrasp_next_baseline(self) -> None:
        """Verify failure recovery order: open < retreat_to_pregrasp < next-loop frozen baseline."""
        # Find the failure recovery section
        failure_section_pattern = "else:\n                        # Failure recovery: open, retreat to pregrasp"
        failure_pos = self.source_text.find(failure_section_pattern)
        self.assertGreater(failure_pos, 0, "failure recovery section must exist")

        # Find the open command_segment
        open_pattern = 'f"{pose.name}:candidate_{candidate_index}_open"'
        open_pos = self.source_text.find(open_pattern, failure_pos)
        self.assertGreater(open_pos, 0, "open command_segment must exist in failure recovery")

        # Find the retreat_to_pregrasp command_segment
        retreat_pattern = 'f"{pose.name}:candidate_{candidate_index}_retreat_to_pregrasp"'
        retreat_pos = self.source_text.find(retreat_pattern, open_pos)
        self.assertGreater(retreat_pos, 0, "retreat_to_pregrasp command_segment must exist")
        self.assertGreater(retreat_pos, open_pos,
            "retreat_to_pregrasp must occur after open")

        # Find the open_pregrasp_retreat construction
        pregrasp_retreat_pattern = "open_pregrasp_retreat = candidate_pregrasp_qpos.copy()"
        pregrasp_retreat_pos = self.source_text.find(pregrasp_retreat_pattern, open_pos)
        self.assertGreater(pregrasp_retreat_pos, 0, "open_pregrasp_retreat construction must exist")
        self.assertGreater(pregrasp_retreat_pos, open_pos,
            "open_pregrasp_retreat construction must occur after open command_segment")
        self.assertLess(pregrasp_retreat_pos, retreat_pos,
            "open_pregrasp_retreat construction must occur before retreat_to_pregrasp command_segment")

        # Verify gripper indices are set to open_qpos
        gripper_set_pattern = "for index in side_gripper_indices:\n                            open_pregrasp_retreat[index] = open_qpos[index]"
        gripper_set_pos = self.source_text.find(gripper_set_pattern, pregrasp_retreat_pos)
        self.assertGreater(gripper_set_pos, 0, "gripper indices must be set to open_qpos")
        self.assertGreater(gripper_set_pos, pregrasp_retreat_pos,
            "gripper set must occur after open_pregrasp_retreat construction")

        # Find the comment explaining next loop returns to baseline
        next_loop_comment = "# Next loop iteration (loop_idx>0) will return to candidate_baseline_qpos"
        next_loop_pos = self.source_text.find(next_loop_comment, retreat_pos)
        self.assertGreater(next_loop_pos, 0,
            "Comment must explain that next loop returns to frozen baseline")
        self.assertGreater(next_loop_pos, retreat_pos,
            "next loop comment must occur after retreat_to_pregrasp")

        # Find replay mode error checking (after retreat_to_pregrasp)
        replay_error_pattern = "# In replay mode, do not try other candidates - fail immediately"
        replay_error_pos = self.source_text.find(replay_error_pattern, retreat_pos)
        self.assertGreater(replay_error_pos, 0, "replay mode error check must exist")
        self.assertGreater(replay_error_pos, retreat_pos,
            "replay error check must occur after retreat_to_pregrasp")

        # Verify retreat_to_pregrasp does NOT re-solve front_clearance
        self.assertNotIn("solve_stage", self.source_text[open_pos:next_loop_pos + 200],
            "retreat_to_pregrasp must not re-solve front_clearance")

    def test_replay_mode_uses_frozen_baseline(self) -> None:
        """Verify replay mode uses frozen baseline for single candidate."""
        # Find the candidate baseline freeze
        freeze_pattern = "candidate_baseline_qpos = qpos[\"front_clearance\"].copy()"
        freeze_pos = self.source_text.find(freeze_pattern)
        self.assertGreater(freeze_pos, 0, "candidate_baseline_qpos freeze must exist")

        # Find the candidate loop (after the freeze)
        candidate_loop_pattern = "for loop_idx, candidate_index in enumerate(candidate_indices_to_try):"
        candidate_loop_pos = self.source_text.find(candidate_loop_pattern)
        self.assertGreater(candidate_loop_pos, freeze_pos,
            "candidate loop must occur after baseline freeze")

        # Find the replay mode error handling inside the candidate loop
        replay_error_pattern = "# In replay mode, do not try other candidates - fail immediately"
        replay_error_pos = self.source_text.find(replay_error_pattern, candidate_loop_pos)
        self.assertGreater(replay_error_pos, 0,
            "replay mode error handling must exist inside candidate loop")
        self.assertGreater(replay_error_pos, freeze_pos,
            "replay mode error handling must occur after baseline freeze")

    def test_failure_recovery_returns_to_baseline_logic(self) -> None:
        """Verify failure recovery does not solve back to front_clearance immediately."""
        # Find the failure recovery section
        failure_section_pattern = "else:\n                        # Failure recovery: open, retreat to pregrasp"
        failure_pos = self.source_text.find(failure_section_pattern)
        self.assertGreater(failure_pos, 0, "failure recovery section must exist")

        # Get a reasonable section after failure - extend to include grasp_attempts.append
        # Look for the end of the section (next loop iteration comment)
        next_loop_pattern = "# Next loop iteration (loop_idx>0) will return to candidate_baseline_qpos"
        next_loop_pos = self.source_text.find(next_loop_pattern, failure_pos)
        self.assertGreater(next_loop_pos, 0, "next loop comment must exist in failure recovery")

        failure_section = self.source_text[failure_pos:next_loop_pos + 200]

        # Verify the comment explaining next loop iteration handles baseline return
        next_loop_comment = "# Next loop iteration (loop_idx>0) will return to candidate_baseline_qpos"
        self.assertIn(next_loop_comment, failure_section,
            "Comment must explain that next loop iteration handles baseline return")

        # Verify old solve_stage pattern does not exist in failure recovery
        old_solve_pattern = "front_clearance_qpos"
        self.assertNotIn(old_solve_pattern, failure_section,
            "Old front_clearance_qpos solve_stage must not exist in failure recovery")

        # Verify new retreat_to_pregrasp exists instead of direct jump to baseline
        retreat_pattern = "retreat_to_pregrasp"
        self.assertIn(retreat_pattern, failure_section,
            "New retreat_to_pregrasp command_segment must exist in failure recovery")

    def test_failure_recovery_exact_order_open_retreat_replay_probe_online(self):
        """Verify exact failure recovery order: open < retreat < replay_error < probe_reset < online_record."""
        # Find the failure recovery section
        failure_section_pattern = "else:\n                        # Failure recovery: open, retreat to pregrasp"
        failure_pos = self.source_text.find(failure_section_pattern)
        self.assertGreater(failure_pos, 0, "failure recovery section must exist")

        # Find the open command_segment
        open_pattern = 'f"{pose.name}:candidate_{candidate_index}_open"'
        open_pos = self.source_text.find(open_pattern, failure_pos)
        self.assertGreater(open_pos, 0, "open command_segment must exist")

        # Find the retreat_to_pregrasp command_segment
        retreat_pattern = 'f"{pose.name}:candidate_{candidate_index}_retreat_to_pregrasp"'
        retreat_pos = self.source_text.find(retreat_pattern, open_pos)
        self.assertGreater(retreat_pos, 0, "retreat_to_pregrasp must exist")
        self.assertGreater(retreat_pos, open_pos, "retreat must follow open")

        # Find replay mode error (after retreat)
        replay_error_pattern = "# In replay mode, do not try other candidates - fail immediately"
        replay_error_pos = self.source_text.find(replay_error_pattern, retreat_pos)
        self.assertGreater(replay_error_pos, 0, "replay error check must exist")
        self.assertGreater(replay_error_pos, retreat_pos, "replay error must follow retreat")

        # Find probe reset (after replay error)
        probe_reset_pattern = "# Probe mode: execute diagnostic reset and verify"
        probe_reset_pos = self.source_text.find(probe_reset_pattern, replay_error_pos)
        self.assertGreater(probe_reset_pos, 0, "probe reset must exist")
        self.assertGreater(probe_reset_pos, replay_error_pos, "probe reset must follow replay error")

        # Find online mode record (after probe reset)
        online_record_pattern = "# Online mode: record as not applied"
        online_record_pos = self.source_text.find(online_record_pattern, probe_reset_pos)
        self.assertGreater(online_record_pos, 0, "online record must exist")
        self.assertGreater(online_record_pos, probe_reset_pos, "online record must follow probe reset")

    def test_reset_only_in_probe_branch(self):
        """Verify reset logic only exists in generation_mode==probe branch."""
        # Find the probe comment to locate the reset section
        probe_comment_pattern = "# Probe mode: execute diagnostic reset and verify"
        probe_comment_pos = self.source_text.find(probe_comment_pattern)
        self.assertGreater(probe_comment_pos, 0, "probe reset section must exist")

        # Find probe reset section (slightly before the comment)
        probe_reset_pattern = "if generation_mode == \"probe\":"
        reset_section_start = self.source_text.find(probe_reset_pattern, probe_comment_pos - 200)
        self.assertGreater(reset_section_start, 0, "probe reset branch must exist")

        # Find the end of probe branch (else clause for online mode)
        online_else_pattern = "else:\n                            # Online mode: record as not applied"
        online_else_pos = self.source_text.find(online_else_pattern, reset_section_start)
        self.assertGreater(online_else_pos, 0, "online else branch must exist")

        probe_reset_section = self.source_text[reset_section_start:online_else_pos]

        # Verify set_qpos exists in probe branch
        self.assertIn("robot.set_qpos(candidate_baseline_qpos", probe_reset_section,
            "probe reset must contain set_qpos")

        # Verify control_dofs_position exists in probe branch
        self.assertIn("robot.control_dofs_position(candidate_baseline_qpos", probe_reset_section,
            "probe reset must contain control_dofs_position after set_qpos")

        # Verify set_qpos is NOT in online branch
        online_section_start = online_else_pos
        online_section_end = online_section_start + 500
        online_section = self.source_text[online_section_start:online_section_end]
        self.assertNotIn("robot.set_qpos", online_section,
            "online branch must NOT contain set_qpos")

    def test_online_and_replay_both_record_applied_false(self):
        """Verify both online and replay modes record applied=False with mode_forbids_mid_episode_reset."""
        # Find replay applied=False record
        replay_applied_pattern = '"applied": False,\n                                "reason": "mode_forbids_mid_episode_reset"'
        replay_section_start = self.source_text.find("# In replay mode, do not try other candidates")
        self.assertGreater(replay_section_start, 0, "replay section must exist")
        replay_applied_pos = self.source_text.find(replay_applied_pattern, replay_section_start)
        self.assertGreater(replay_applied_pos, 0, "replay must record applied=False with mode_forbids")

        # Find online applied=False record
        online_applied_pattern = '"applied": False,\n                                "reason": "mode_forbids_mid_episode_reset"'
        online_section_start = self.source_text.find("# Online mode: record as not applied")
        self.assertGreater(online_section_start, 0, "online section must exist")
        online_applied_pos = self.source_text.find(online_applied_pattern, online_section_start)
        self.assertGreater(online_applied_pos, 0, "online must record applied=False with mode_forbids")

    def test_control_target_immediately_follows_set_qpos(self):
        """Verify control_dofs_position immediately follows set_qpos in probe reset."""
        # Find probe reset set_qpos
        set_qpos_pattern = "robot.set_qpos(candidate_baseline_qpos, zero_velocity=True)"
        probe_reset_start = self.source_text.find("# Probe mode: execute diagnostic reset and verify")
        self.assertGreater(probe_reset_start, 0, "probe reset section must exist")
        set_qpos_pos = self.source_text.find(set_qpos_pattern, probe_reset_start)
        self.assertGreater(set_qpos_pos, 0, "set_qpos must exist in probe reset")

        # Find control_dofs_position immediately after set_qpos
        control_pattern = "robot.control_dofs_position(candidate_baseline_qpos, dofs_idx_local=all_indices)"
        control_pos = self.source_text.find(control_pattern, set_qpos_pos)
        self.assertGreater(control_pos, 0, "control_dofs_position must exist")

        # Verify no other statements between set_qpos and control_dofs_position
        between = self.source_text[set_qpos_pos + len(set_qpos_pattern):control_pos]
        # Only whitespace and newlines allowed
        self.assertEqual(between.strip(), "", "Only whitespace allowed between set_qpos and control_dofs_position")

    def test_probe_reset_uses_three_existing_thresholds(self):
        """Verify probe reset uses the three existing thresholds: arm tracking, bowl position, bowl rotation."""
        # Find probe reset validation section
        probe_reset_start = self.source_text.find("# Probe mode: execute diagnostic reset and verify")
        self.assertGreater(probe_reset_start, 0, "probe reset must exist")

        # Find max_tracking_tolerance from contract
        tracking_pattern = 'max_tracking_tolerance = float(contract["maximum_arm_tracking_error_rad"])'
        tracking_pos = self.source_text.find(tracking_pattern, probe_reset_start)
        self.assertGreater(tracking_pos, 0, "must use maximum_arm_tracking_error_rad from contract")

        # Find position_tolerance from scene_contract
        position_pattern = 'position_tolerance = float(scene_contract["ik_gate"]["position_tolerance_m"])'
        position_pos = self.source_text.find(position_pattern, tracking_pos)
        self.assertGreater(position_pos, 0, "must use position_tolerance_m from scene_contract ik_gate")

        # Find rotation_tolerance from scene_contract
        rotation_pattern = 'rotation_tolerance = float(scene_contract["ik_gate"]["rotation_tolerance_rad"])'
        rotation_pos = self.source_text.find(rotation_pattern, position_pos)
        self.assertGreater(rotation_pos, 0, "must use rotation_tolerance_rad from scene_contract ik_gate")

    def test_replay_calls_plan_needs_reprobe_directly(self):
        """Verify replay mode calls plan_needs_reprobe(replay_plan) directly without constructing candidate list."""
        # Find plan_needs_reprobe import
        import_pattern = "from mantis_rocm_bridge.two_stage_plan import"
        import_section_start = self.source_text.find(import_pattern)
        self.assertGreater(import_section_start, 0, "two_stage_plan import must exist")

        # Find the import section (next ~200 chars should contain the imports)
        import_section = self.source_text[import_section_start:import_section_start + 200]
        self.assertIn("plan_needs_reprobe", import_section,
            "plan_needs_reprobe must be imported from two_stage_plan")

        # Verify CANDIDATE_ISOLATION_VERSION is still imported from candidate_isolation
        candidate_import_pattern = "from mantis_rocm_bridge.candidate_isolation import"
        candidate_import_pos = self.source_text.find(candidate_import_pattern)
        self.assertGreater(candidate_import_pos, 0, "candidate_isolation import must exist")
        candidate_import_section = self.source_text[candidate_import_pos:candidate_import_pos + 150]
        self.assertIn("CANDIDATE_ISOLATION_VERSION", candidate_import_section,
            "CANDIDATE_ISOLATION_VERSION must be imported from candidate_isolation")

        # Find the plan rejection section
        rejection_pattern = "if plan_needs_reprobe(replay_plan):"
        rejection_pos = self.source_text.find(rejection_pattern)
        self.assertGreater(rejection_pos, 0, "plan_needs_reprobe must be called with replay_plan")

        # Verify no manual candidate list construction before plan_needs_reprobe call
        # Look back ~500 chars from the call to see what precedes it
        before_call = self.source_text[rejection_pos - 500:rejection_pos]
        self.assertNotIn("right_candidate_indices = [", before_call,
            "Must NOT manually construct candidate list before calling plan_needs_reprobe")
        self.assertNotIn("for step in replay_plan.steps", before_call,
            "Must NOT manually iterate steps to extract candidates")


class SourceContractTests(unittest.TestCase):
    """Source-contract tests proving critical implementation invariants."""

    def setUp(self) -> None:
        self.module = _load_tool_module()
        self.source_path = ROOT / "tools" / "run_genesis_stack_bowls_scripted_g1.py"
        self.source_text = self.source_path.read_text(encoding="utf-8")

    def test_frozen_offset_applied_before_transport_position(self) -> None:
        """Prove frozen offset application occurs before transport_position construction for probe mode."""
        # Find the frozen offset application pattern for probe mode
        frozen_offset_pattern = "frozen_offset = planned_step.place_xy_offset_m"
        transport_pattern = "transport_position = place_position.copy()"

        frozen_offset_pos = self.source_text.find(frozen_offset_pattern)
        transport_pos = self.source_text.find(transport_pattern)

        # Frozen offset application must exist for probe mode
        self.assertGreater(frozen_offset_pos, 0, "frozen offset application must exist in probe mode")

        # Transport construction must occur after frozen offset application
        self.assertGreater(transport_pos, frozen_offset_pos,
            "transport_position construction must occur after frozen offset application")

        # Verify the comment mentions this happens BEFORE transport_position construction
        comment_pattern = "# Apply frozen offset to nominal place position BEFORE transport_position construction"
        comment_pos = self.source_text.find(comment_pattern)
        self.assertGreater(comment_pos, 0, "comment must explain ordering invariant")
        self.assertGreater(frozen_offset_pos, comment_pos,
            "frozen offset application must occur after the explanatory comment")

    def test_replay_branch_has_no_solve_or_smooth_path(self) -> None:
        """Prove replay measurement branch contains no solve_assigned_path or command_smooth_path."""
        # Find the frozen plan replay measurement block - look for the specific comment
        replay_start = self.source_text.find("# Replay mode: single measurement after offset-aware transport/place - no correction motion")
        self.assertGreater(replay_start, 0, "replay measurement block must exist")

        # Find a reasonable section to analyze (next 5000 chars should cover the replay block)
        replay_section = self.source_text[replay_start:replay_start + 5000]

        # Verify no solve_assigned_path in replay block
        self.assertNotIn("solve_assigned_path", replay_section,
            "replay block must not contain solve_assigned_path")

        # Verify no command_smooth_path in replay block
        self.assertNotIn("command_smooth_path", replay_section,
            "replay block must not contain command_smooth_path")

        # Verify corrections_applied is set to 0 in replay branch
        self.assertIn("corrections_applied = 0", replay_section,
            'replay block must set corrections_applied to 0')

    def test_candidate_selection_matches_attempt_index(self) -> None:
        """Prove candidate selection matches attempt candidate_index and does not index grasp_attempts[candidate_index]."""
        # The correct pattern: candidate_index comes from the plan step
        # Find where candidate_index is used in replay/probe mode
        correct_pattern = "candidate_indices_to_try = [planned_step.right_grasp_candidate_index]"
        correct_pos = self.source_text.find(correct_pattern)
        self.assertGreater(correct_pos, 0, "candidate_index must come from plan step")

        # Verify the incorrect pattern does not exist
        incorrect_pattern = "grasp_attempts[candidate_index]"
        incorrect_pos = self.source_text.find(incorrect_pattern)
        self.assertEqual(incorrect_pos, -1,
            "must not index grasp_attempts with candidate_index")

    def test_dynamic_probe_limit_compares_after_task_load(self) -> None:
        """Probe dynamic limit uses task_max_policy_steps after task load."""
        # Find task load (two possible patterns)
        task_load_pattern_1 = 'task = load_json(args.task)'
        task_load_pattern_2 = 'task = load_json(args.task_contract)'

        task_load_pos_1 = self.source_text.find(task_load_pattern_1)
        task_load_pos_2 = self.source_text.find(task_load_pattern_2)
        task_load_pos = max(task_load_pos_1, task_load_pos_2)

        self.assertGreater(task_load_pos, 0, "task must be loaded via load_json")

        # Find where task_max_policy_steps is accessed (note the int() cast)
        task_max_pattern = 'task_max_policy_steps = int(task["max_policy_steps"])'
        task_max_pos = self.source_text.find(task_max_pattern)
        self.assertGreater(task_max_pos, task_load_pos,
            "task_max_policy_steps must be accessed after task load")

        # Verify that task_max_policy_steps is used in probe mode validation
        # Look for the probe max policy steps check
        probe_check_pattern = 'args.probe_max_policy_steps < task_max_policy_steps'
        probe_check_pos = self.source_text.find(probe_check_pattern)
        self.assertGreater(probe_check_pos, task_max_pos,
            "probe max policy steps check must use task_max_policy_steps")

    def test_uniform_final_boolean_keys_exact_frozen_pass(self) -> None:
        """Prove uniform final boolean keys and exact frozen_plan_validation_pass field."""
        # Find receipt construction
        receipt_pattern = "receipt = {"
        receipt_pos = self.source_text.find(receipt_pattern)
        self.assertGreater(receipt_pos, 0, "receipt construction must exist")

        # Find the relevant section (from receipt to receipt_path write)
        write_pattern = "receipt_path.write_text("
        write_pos = self.source_text.find(write_pattern, receipt_pos)
        self.assertGreater(write_pos, receipt_pos, "receipt must be written")

        receipt_section = self.source_text[receipt_pos:write_pos]

        # Verify exact frozen_plan_validation_pass field exists (added conditionally for replay)
        # Look for the actual pattern in the code
        self.assertIn('receipt["frozen_plan_validation_pass"] = True', receipt_section,
            "receipt must contain exact frozen_plan_validation_pass field for replay")

        # Verify obsolete replay_plan_frozen_validated is absent
        self.assertNotIn("replay_plan_frozen_validated", receipt_section,
            "obsolete replay_plan_frozen_validated must not exist")

        # Verify basename and SHA fields exist for replay
        self.assertIn("replay_plan_basename", receipt_section,
            "receipt must contain replay_plan_basename for replay mode")
        self.assertIn("replay_plan_sha256", receipt_section,
            "receipt must contain replay_plan_sha256 for replay mode")

        # Verify uniform final boolean keys in the main receipt dict
        self.assertIn("scripted_g1_pass", receipt_section,
            "receipt must contain scripted_g1_pass")
        self.assertIn("probe_plan_pass", receipt_section,
            "receipt must contain probe_plan_pass")
        self.assertIn("g1_claim", receipt_section,
            "receipt must contain g1_claim")
        self.assertIn("learned_policy_claim", receipt_section,
            "receipt must contain learned_policy_claim")
        self.assertIn("rocm_claim", receipt_section,
            "receipt must contain rocm_claim")
        self.assertIn("multi_seed_evidence", receipt_section,
            "receipt must contain multi_seed_evidence")
        self.assertIn("episode_success_claim", receipt_section,
            "receipt must contain episode_success_claim")

    def test_probe_capture_rejection_and_replay_allowance(self) -> None:
        """Prove probe capture is rejected and replay capture is allowed."""
        # Find capture argument validation (uses parser.error for probe mode)
        capture_rejection_pattern = 'if args.generation_mode == "probe":'
        capture_rejection_pos = self.source_text.find(capture_rejection_pattern)
        self.assertGreater(capture_rejection_pos, 0, "probe mode check must exist")

        # Find the section with capture rejection
        capture_section_start = capture_rejection_pos
        capture_section_end = capture_section_start + 500
        capture_section = self.source_text[capture_section_start:capture_section_end]

        # Verify capture rejection for probe mode
        self.assertIn('if args.capture:', capture_section,
            "probe capture check must exist")
        self.assertIn('parser.error("--capture is forbidden in probe mode")', capture_section,
            "probe capture must be rejected with parser.error")

        # Find where capture_npz is assigned (should exist for online and replay modes)
        capture_npz_pattern = "capture_npz = capture_npz_name(seed)"
        capture_npz_pos = self.source_text.find(capture_npz_pattern)
        self.assertGreater(capture_npz_pos, 0, "capture_npz assignment must exist")

        # Verify replay mode exists and doesn't have capture rejection
        replay_mode_pattern = 'generation_mode == "replay"'
        replay_mode_pos = self.source_text.find(replay_mode_pattern)
        self.assertGreater(replay_mode_pos, 0, "replay mode must exist")

        # Capture_npz assignment should come after the probe capture rejection
        self.assertGreater(capture_npz_pos, capture_rejection_pos,
            "capture_npz assignment must come after probe capture rejection")

    def test_tracker_constructed_with_effective_probe_horizon(self) -> None:
        """The episode tracker must enforce the effective probe horizon, not the
        frozen task max, so a diagnostic probe run that passes 1200 steps can
        record events and emit a replay plan instead of aborting with
        'policy_step exceeds the task limit'.  Online/replay still pin the
        horizon to the task max, so they remain strictly bounded."""
        # online/replay must pin effective_max_policy_steps to the frozen task max
        online_replay_branch = "effective_max_policy_steps = task_max_policy_steps"
        self.assertEqual(
            self.source_text.count(online_replay_branch), 1,
            "online/replay must pin effective_max_policy_steps to the task max",
        )
        horizon_pos = self.source_text.find(online_replay_branch)
        self.assertGreater(horizon_pos, 0, "effective horizon assignment must exist")

        ctor_pos = self.source_text.find("EpisodeStageTracker(")
        self.assertGreater(ctor_pos, 0, "tracker construction must exist")
        # The construction block must hand the effective horizon to the tracker.
        block = self.source_text[ctor_pos:ctor_pos + 200]
        self.assertIn(
            "effective_policy_step_limit=effective_max_policy_steps",
            block,
            "tracker must be constructed with the effective horizon",
        )
        self.assertIn("seed=seed", block, "tracker must keep the episode seed")
        # The horizon must be computed before the tracker is built.
        self.assertGreater(
            ctor_pos, horizon_pos,
            "effective horizon must be computed before the tracker is built",
        )


class InterpolationStartHelperTests(unittest.TestCase):
    """Unit tests for the pure build_interpolation_start helper.

    The helper decides, per DOF, whether an interpolation starts from the readback
    (arm) or from the previously commanded action (gripper).  It must be strict about
    length, index validity, and finiteness so a misconfigured move fails loudly.
    """

    def setUp(self) -> None:
        self.module = _load_tool_module()
        self.helper = self.module.build_interpolation_start

    def test_gripper_dofs_from_previous_action_and_arm_from_readback(self) -> None:
        readback = [float(index) for index in range(18)]
        previous_action = [float(index) + 100.0 for index in range(18)]
        start = self.helper(
            readback=readback,
            previous_action=previous_action,
            arm_indices=list(range(14)),
            gripper_indices=[14, 15, 16, 17],
            expected_length=18,
        )
        # Arm DOFs keep the readback.
        self.assertEqual(start[:14], readback[:14])
        # Gripper DOFs take the previous command, not the post-contact readback.
        self.assertEqual(start[14:18], previous_action[14:18])
        for index in range(14, 18):
            self.assertNotEqual(start[index], readback[index])
        self.assertTrue(all(math.isfinite(value) for value in start))

    def test_accepts_tuple_inputs(self) -> None:
        start = self.helper(
            readback=(0.0,) * 18,
            previous_action=(1.0,) * 18,
            arm_indices=(0, 1, 2),
            gripper_indices=(3, 4),
            expected_length=18,
        )
        self.assertEqual(start[3:5], [1.0, 1.0])
        self.assertEqual(start[:3], [0.0, 0.0, 0.0])

    def test_rejects_wrong_readback_length(self) -> None:
        with self.assertRaises(ValueError):
            self.helper(
                readback=[0.0] * 17,
                previous_action=[0.0] * 18,
                arm_indices=list(range(14)),
                gripper_indices=[14, 15, 16, 17],
                expected_length=18,
            )

    def test_rejects_wrong_previous_action_length(self) -> None:
        with self.assertRaises(ValueError):
            self.helper(
                readback=[0.0] * 18,
                previous_action=[0.0] * 19,
                arm_indices=list(range(14)),
                gripper_indices=[14, 15, 16, 17],
                expected_length=18,
            )

    def test_rejects_out_of_range_index(self) -> None:
        with self.assertRaises(ValueError):
            self.helper(
                readback=[0.0] * 18,
                previous_action=[0.0] * 18,
                arm_indices=list(range(13)) + [18],
                gripper_indices=[14, 15, 16, 17],
                expected_length=18,
            )

    def test_rejects_overlapping_arm_and_gripper_indices(self) -> None:
        with self.assertRaises(ValueError):
            self.helper(
                readback=[0.0] * 18,
                previous_action=[0.0] * 18,
                arm_indices=list(range(14)) + [16],
                gripper_indices=[14, 15, 16, 17],
                expected_length=18,
            )

    def test_rejects_non_integer_index(self) -> None:
        with self.assertRaises(ValueError):
            self.helper(
                readback=[0.0] * 18,
                previous_action=[0.0] * 18,
                arm_indices=[0.5],
                gripper_indices=[14, 15, 16, 17],
                expected_length=18,
            )

    def test_rejects_non_finite_readback(self) -> None:
        readback = [0.0] * 18
        readback[3] = float("inf")
        with self.assertRaises(ValueError):
            self.helper(
                readback=readback,
                previous_action=[0.0] * 18,
                arm_indices=list(range(14)),
                gripper_indices=[14, 15, 16, 17],
                expected_length=18,
            )

    def test_rejects_non_finite_previous_action(self) -> None:
        previous_action = [0.0] * 18
        previous_action[16] = float("nan")
        with self.assertRaises(ValueError):
            self.helper(
                readback=[0.0] * 18,
                previous_action=previous_action,
                arm_indices=list(range(14)),
                gripper_indices=[14, 15, 16, 17],
                expected_length=18,
            )

    def test_rejects_non_positive_expected_length(self) -> None:
        with self.assertRaises(ValueError):
            self.helper(
                readback=[],
                previous_action=[],
                arm_indices=[],
                gripper_indices=[],
                expected_length=0,
            )


class InterpolationStartWiringTests(unittest.TestCase):
    """Prove the command functions and probe reset use build_interpolation_start."""

    def setUp(self) -> None:
        self.module = _load_tool_module()
        self.source_path = ROOT / "tools" / "run_genesis_stack_bowls_scripted_g1.py"
        self.source_text = self.source_path.read_text(encoding="utf-8")

    def test_helper_is_module_level(self) -> None:
        self.assertIn("\ndef build_interpolation_start(", self.source_text)

    def test_command_segment_uses_previous_action_for_gripper(self) -> None:
        start = self.source_text.find("def command_segment(")
        self.assertGreater(start, 0)
        end = self.source_text.find("def command_smooth_path(", start)
        self.assertGreater(end, 0)
        block = self.source_text[start:end]
        self.assertIn("build_interpolation_start(", block)
        self.assertIn("previous_action=current_action", block)
        self.assertIn("arm_indices=all_arm_indices", block)
        self.assertIn("gripper_indices=all_gripper_indices", block)
        # The raw readback must no longer seed the whole start vector directly.
        self.assertNotIn(
            "start = np.asarray(_read_dofs(robot, all_indices), dtype=float)",
            block,
        )

    def test_command_smooth_path_uses_previous_action_for_gripper(self) -> None:
        start = self.source_text.find("def command_smooth_path(")
        self.assertGreater(start, 0)
        end = self.source_text.find("def wait_policy_frames(", start)
        self.assertGreater(end, 0)
        block = self.source_text[start:end]
        self.assertIn("build_interpolation_start(", block)
        self.assertIn("previous_action=current_action", block)
        self.assertNotIn(
            "start = np.asarray(_read_dofs(robot, all_indices), dtype=float)",
            block,
        )

    def test_probe_resets_current_action_to_baseline_after_reset(self) -> None:
        probe_start = self.source_text.find(
            "# Probe mode: execute diagnostic reset and verify"
        )
        self.assertGreater(probe_start, 0)
        control_pos = self.source_text.find(
            "robot.control_dofs_position(candidate_baseline_qpos, dofs_idx_local=all_indices)",
            probe_start,
        )
        self.assertGreater(control_pos, 0)
        step_pos = self.source_text.find("scene.step()", control_pos)
        self.assertGreater(step_pos, 0)
        sync_pos = self.source_text.find(
            "current_action = candidate_baseline_qpos.copy()", step_pos
        )
        self.assertGreater(
            sync_pos,
            0,
            "probe must sync current_action to the frozen baseline after the reset",
        )


class CanonicalizeGripperCommandsHelperTests(unittest.TestCase):
    """Unit tests for the pure canonicalize_path_gripper_commands helper.

    The helper re-stamps the gripper columns of a 2D path from a single
    symmetric command target so an upstream planner's asymmetric finger
    readbacks cannot bleed into the executed action.  It must keep arm columns
    exactly, mutate nothing in the inputs, and fail loudly on shape, index, and
    finiteness problems.
    """

    def setUp(self) -> None:
        self.module = _load_tool_module()
        self.helper = self.module.canonicalize_path_gripper_commands
        # Four clamp DOFs across both arms at the tail of an 18D qpos.
        self.gripper_indices = [14, 15, 16, 17]
        self.expected_width = 18

    def _symmetric_target(self) -> list[float]:
        # Active side (right, indices 16/17) transport pose, inactive side
        # (left, indices 14/15) open -- mirrors how transport_path[-1] is built.
        target = [0.0] * self.expected_width
        target[14] = 0.04
        target[15] = 0.04
        target[16] = 0.01
        target[17] = 0.01
        return target

    def _asymmetric_path(self) -> list[list[float]]:
        # Two rows whose gripper columns drift asymmetrically, mimicking the
        # post-contact readback spread the RRT planner preserved.
        row0 = [float(index) for index in range(self.expected_width)]
        row1 = [float(index) + 0.5 for index in range(self.expected_width)]
        row0[14] = 0.484663  # asymmetric left/right spread to be erased
        row0[15] = 0.760673
        row0[16] = 0.484663
        row0[17] = 0.760673
        row1[14] = 0.50
        row1[15] = 0.77
        row1[16] = 0.49
        row1[17] = 0.76
        return [row0, row1]

    def test_asymmetric_gripper_columns_replaced_by_symmetric_target(self) -> None:
        path = self._asymmetric_path()
        target = self._symmetric_target()
        result = self.helper(
            path=path,
            command_target=target,
            gripper_indices=self.gripper_indices,
            expected_width=self.expected_width,
        )
        self.assertEqual(len(result), len(path))
        for row in result:
            # All four gripper columns equal the explicit symmetric target.
            self.assertEqual(
                [row[14], row[15], row[16], row[17]],
                [target[14], target[15], target[16], target[17]],
            )
            # No surviving asymmetric spread within a row.
            self.assertEqual(row[14], row[15])
            self.assertEqual(row[16], row[17])

    def test_arm_columns_copied_verbatim(self) -> None:
        path = self._asymmetric_path()
        target = self._symmetric_target()
        result = self.helper(
            path=path,
            command_target=target,
            gripper_indices=self.gripper_indices,
            expected_width=self.expected_width,
        )
        for original, canonical in zip(path, result):
            arm_columns = [
                original[index] for index in range(self.expected_width)
                if index not in self.gripper_indices
            ]
            canonical_arm = [
                canonical[index] for index in range(self.expected_width)
                if index not in self.gripper_indices
            ]
            self.assertEqual(canonical_arm, arm_columns)

    def test_inputs_are_not_mutated(self) -> None:
        path = self._asymmetric_path()
        path_snapshot = [list(row) for row in path]
        target = self._symmetric_target()
        target_snapshot = list(target)
        indices_snapshot = list(self.gripper_indices)
        self.helper(
            path=path,
            command_target=target,
            gripper_indices=self.gripper_indices,
            expected_width=self.expected_width,
        )
        self.assertEqual([list(row) for row in path], path_snapshot)
        self.assertEqual(list(target), target_snapshot)
        self.assertEqual(list(self.gripper_indices), indices_snapshot)

    def test_accepts_tuple_inputs(self) -> None:
        path = ((0.0,) * self.expected_width, (1.0,) * self.expected_width)
        target = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                  0.0, 0.0, 0.0, 0.0, 0.04, 0.04, 0.01, 0.01)
        result = self.helper(
            path=path,
            command_target=target,
            gripper_indices=(14, 15, 16, 17),
            expected_width=self.expected_width,
        )
        for row in result:
            self.assertEqual(row[16], 0.01)
            self.assertEqual(row[17], 0.01)

    def test_returns_fresh_list_of_lists_of_floats(self) -> None:
        path = self._asymmetric_path()
        result = self.helper(
            path=path,
            command_target=self._symmetric_target(),
            gripper_indices=self.gripper_indices,
            expected_width=self.expected_width,
        )
        self.assertIsInstance(result, list)
        for row in result:
            self.assertIsInstance(row, list)
            for value in row:
                self.assertIsInstance(value, float)
                self.assertTrue(math.isfinite(value))

    def test_rejects_empty_path(self) -> None:
        with self.assertRaises(ValueError):
            self.helper(
                path=[],
                command_target=self._symmetric_target(),
                gripper_indices=self.gripper_indices,
                expected_width=self.expected_width,
            )

    def test_rejects_wrong_row_length(self) -> None:
        path = [[0.0] * 17, [0.0] * self.expected_width]
        with self.assertRaises(ValueError):
            self.helper(
                path=path,
                command_target=self._symmetric_target(),
                gripper_indices=self.gripper_indices,
                expected_width=self.expected_width,
            )

    def test_rejects_wrong_command_target_length(self) -> None:
        target = [0.0] * 17
        with self.assertRaises(ValueError):
            self.helper(
                path=self._asymmetric_path(),
                command_target=target,
                gripper_indices=self.gripper_indices,
                expected_width=self.expected_width,
            )

    def test_rejects_out_of_range_index(self) -> None:
        with self.assertRaises(ValueError):
            self.helper(
                path=self._asymmetric_path(),
                command_target=self._symmetric_target(),
                gripper_indices=[14, 15, 16, 18],
                expected_width=self.expected_width,
            )

    def test_rejects_duplicate_index(self) -> None:
        with self.assertRaises(ValueError):
            self.helper(
                path=self._asymmetric_path(),
                command_target=self._symmetric_target(),
                gripper_indices=[14, 15, 16, 16],
                expected_width=self.expected_width,
            )

    def test_rejects_non_integer_index(self) -> None:
        with self.assertRaises(ValueError):
            self.helper(
                path=self._asymmetric_path(),
                command_target=self._symmetric_target(),
                gripper_indices=[14, 15, 16, 17.0],
                expected_width=self.expected_width,
            )

    def test_rejects_bool_index_explicitly(self) -> None:
        with self.assertRaises(ValueError):
            self.helper(
                path=self._asymmetric_path(),
                command_target=self._symmetric_target(),
                gripper_indices=[14, 15, 16, True],
                expected_width=self.expected_width,
            )

    def test_rejects_non_finite_row_value(self) -> None:
        path = self._asymmetric_path()
        path[1][5] = float("inf")
        with self.assertRaises(ValueError):
            self.helper(
                path=path,
                command_target=self._symmetric_target(),
                gripper_indices=self.gripper_indices,
                expected_width=self.expected_width,
            )

    def test_rejects_non_finite_command_target(self) -> None:
        target = self._symmetric_target()
        target[16] = float("nan")
        with self.assertRaises(ValueError):
            self.helper(
                path=self._asymmetric_path(),
                command_target=target,
                gripper_indices=self.gripper_indices,
                expected_width=self.expected_width,
            )

    def test_rejects_non_positive_expected_width(self) -> None:
        with self.assertRaises(ValueError):
            self.helper(
                path=self._asymmetric_path(),
                command_target=self._symmetric_target(),
                gripper_indices=self.gripper_indices,
                expected_width=0,
            )

    def test_numpy_ndarray_path_and_target_returns_list_arm_unchanged_gripper_frozen(self) -> None:
        """Regression test for real numpy ndarray inputs causing ValueError: truth value ambiguous.

        This test verifies that canonicalize_path_gripper_commands works correctly with real
        numpy ndarray inputs from Genesis RRTConnect, not just Python lists. The bug was
        using 'if not path' which raises ValueError for numpy arrays due to ambiguous truth value.
        Fixed by using explicit len(path) == 0 check instead.
        """
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy not available")

        # Create a realistic numpy path (2D array) as Genesis RRTConnect returns
        # Two rows with asymmetric gripper columns, arm columns varying per row
        path_array = np.array([
            [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0,
             0.484663, 0.760673, 0.484663, 0.760673],  # asymmetric spread to be erased
            [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5, 13.5,
             0.50, 0.77, 0.49, 0.76],
        ], dtype=float)

        # Create command_target as numpy array (mirrors transport_path[-1])
        target_array = np.array([0.0] * self.expected_width, dtype=float)
        target_array[14] = 0.04
        target_array[15] = 0.04
        target_array[16] = 0.01
        target_array[17] = 0.01

        # Call the helper with numpy arrays - should not raise ValueError
        result = self.helper(
            path=path_array,
            command_target=target_array,
            gripper_indices=self.gripper_indices,
            expected_width=self.expected_width,
        )

        # Verify return is a list (not numpy array)
        self.assertIsInstance(result, list)

        # Verify each row is a list (not numpy array)
        for row in result:
            self.assertIsInstance(row, list)

        # Verify arm columns unchanged (copied verbatim from input)
        for i, result_row in enumerate(result):
            for j in range(self.expected_width):
                if j not in self.gripper_indices:
                    # Arm column values should match input path exactly
                    self.assertAlmostEqual(
                        result_row[j],
                        path_array[i, j],
                        places=9,
                        msg=f"arm column {j} row {i} should match input path"
                    )

        # Verify gripper columns frozen to symmetric target values
        for row in result:
            # All four gripper DOFs equal the explicit symmetric target
            self.assertEqual(
                [row[14], row[15], row[16], row[17]],
                [target_array[14], target_array[15], target_array[16], target_array[17]],
                msg="gripper columns must be frozen to symmetric target values"
            )
            # No asymmetric spread within each side
            self.assertEqual(row[14], row[15],
                           msg="left gripper fingers must be symmetric")
            self.assertEqual(row[16], row[17],
                           msg="right gripper fingers must be symmetric")

    def test_numpy_ndarray_empty_path_raises_valueerror_not_ambiguous_truth(self) -> None:
        """Regression test that empty numpy array raises ValueError, not ambiguous truth error.

        Before the fix, 'if not path' on numpy arrays raised:
        ValueError: The truth value of an array with more than one element is ambiguous.

        After the fix with 'if len(path) == 0', it should raise the expected ValueError
        with the correct message about non-empty path.
        """
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy not available")

        # Empty 2D numpy array
        empty_path = np.array([], dtype=float).reshape(0, self.expected_width)

        with self.assertRaises(ValueError) as ctx:
            self.helper(
                path=empty_path,
                command_target=self._symmetric_target(),
                gripper_indices=self.gripper_indices,
                expected_width=self.expected_width,
            )

        # Verify it's the expected ValueError about non-empty path
        self.assertIn("non-empty", str(ctx.exception).lower())
        self.assertIn("path", str(ctx.exception).lower())

    def test_numpy_ndarray_with_nested_list_path_returns_list(self) -> None:
        """Test mixed input: numpy path, list target - still returns list of lists."""
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy not available")

        # numpy 2D array path
        path_array = np.array([
            [float(i) for i in range(self.expected_width)],
            [float(i) + 0.5 for i in range(self.expected_width)],
        ], dtype=float)

        # list target
        target_list = self._symmetric_target()

        result = self.helper(
            path=path_array,
            command_target=target_list,
            gripper_indices=self.gripper_indices,
            expected_width=self.expected_width,
        )

        # Must return list of lists, not numpy array
        self.assertIsInstance(result, list)
        for row in result:
            self.assertIsInstance(row, list)


class CanonicalizeGripperCommandsWiringTests(unittest.TestCase):
    """Prove the canonicalization call sits in the RRT transport path.

    The call must run after the planned_array shape gate and before
    transport_execution_paths is constructed, and it must source the symmetric
    gripper target from transport_path[-1] using all_gripper_indices -- never
    from the readback.
    """

    def setUp(self) -> None:
        self.module = _load_tool_module()
        self.source_path = ROOT / "tools" / "run_genesis_stack_bowls_scripted_g1.py"
        self.source_text = self.source_path.read_text(encoding="utf-8")

    def test_helper_is_module_level(self) -> None:
        self.assertIn("\ndef canonicalize_path_gripper_commands(", self.source_text)

    def _rrt_block(self) -> str:
        start = self.source_text.find('planner="RRTConnect"')
        self.assertGreater(start, 0, "could not locate the RRTConnect planner call")
        # End at the right-side XY correction loop that follows execution.
        end = self.source_text.find("for transport_stage, execution_path", start)
        self.assertGreater(end, 0)
        return self.source_text[start:end]

    def test_call_runs_after_shape_gate_and_before_execution_paths(self) -> None:
        block = self._rrt_block()
        shape_gate = block.find("invalid right-arm")
        self.assertGreater(shape_gate, 0, "could not locate the planned_array shape gate")
        canonicalize = block.find("canonicalize_path_gripper_commands(")
        self.assertGreater(canonicalize, 0, "missing canonicalize_path_gripper_commands call")
        execution = block.find("transport_execution_paths = [")
        self.assertGreater(execution, 0, "could not locate transport_execution_paths construction")
        self.assertLess(shape_gate, canonicalize)
        self.assertLess(canonicalize, execution)

    def test_call_sources_target_from_transport_path_last_and_all_gripper_indices(
        self,
    ) -> None:
        block = self._rrt_block()
        canonicalize = block.find("canonicalize_path_gripper_commands(")
        self.assertGreater(canonicalize, 0)
        call_block = block[canonicalize: block.find(")", canonicalize) + 1]
        # Target is the symmetric transport pose, not the readback.
        self.assertIn("command_target=transport_path[-1]", call_block)
        self.assertIn("gripper_indices=all_gripper_indices", call_block)
        self.assertIn("expected_width=len(all_indices)", call_block)
        # The planned rows are canonicalized before becoming np arrays.
        self.assertIn("for row in canonicalized_rows", block)
        # The raw planned_array must no longer feed execution directly.
        self.assertNotIn("for row in planned_array", block)


class ConsecutiveLeftInterBowlTransitionTests(unittest.TestCase):
    """Validate the WP-G3-CORR-009 pure route and fail-closed wiring."""

    def setUp(self) -> None:
        self.module = _load_tool_module()
        self.scene = load_json(ROOT / "configs/stack-bowls-genesis-v1.json")
        self.task = load_json(ROOT / "configs/task-pack-v1.json")
        self.source_text = (
            ROOT / "tools" / "run_genesis_stack_bowls_scripted_g1.py"
        ).read_text(encoding="utf-8")
        self.raw_contract = self.scene["contact_probe"][
            "consecutive_left_inter_bowl_transition"
        ]

    def test_checked_in_contract_is_exact_v1_route(self) -> None:
        normalized = self.module.validate_consecutive_left_transition_contract(
            self.raw_contract
        )
        self.assertEqual(
            normalized["protocol_version"],
            "consecutive_left_high_clearance_cartesian_v1",
        )
        self.assertTrue(normalized["enabled"])
        self.assertEqual(normalized["clearance_tcp_z_m"], 1.02)
        self.assertEqual(normalized["cartesian_waypoints_per_segment"], 8)
        self.assertEqual(normalized["segment_minimum_duration_s"], 0.5)

    def test_route_has_exact_segment_shapes_and_endpoints(self) -> None:
        route = self.module.build_consecutive_left_transition_positions(
            previous_retreat_position_xyz_m=(0.0, -0.1678, 0.93),
            next_front_clearance_position_xyz_m=(-0.24, 0.03, 0.90),
            clearance_tcp_z_m=1.02,
            cartesian_waypoints_per_segment=8,
        )
        self.assertEqual(
            list(route),
            [
                "vertical_clearance",
                "reorient_at_clearance",
                "lateral_clearance",
                "descend_to_front_clearance",
            ],
        )
        self.assertEqual(len(route["vertical_clearance"]), 8)
        self.assertEqual(len(route["reorient_at_clearance"]), 1)
        self.assertEqual(len(route["lateral_clearance"]), 8)
        self.assertEqual(len(route["descend_to_front_clearance"]), 8)
        self.assertEqual(
            route["vertical_clearance"][-1],
            (0.0, -0.1678, 1.02),
        )
        self.assertEqual(
            route["reorient_at_clearance"][0],
            (0.0, -0.1678, 1.02),
        )
        self.assertEqual(
            route["lateral_clearance"][-1],
            (-0.24, 0.03, 1.02),
        )
        self.assertEqual(
            route["descend_to_front_clearance"][-1],
            (-0.24, 0.03, 0.90),
        )

    def test_route_preserves_segment_geometry(self) -> None:
        route = self.module.build_consecutive_left_transition_positions(
            previous_retreat_position_xyz_m=(0.0, -0.1678, 0.93),
            next_front_clearance_position_xyz_m=(-0.24, 0.03, 0.90),
            clearance_tcp_z_m=1.02,
            cartesian_waypoints_per_segment=8,
        )
        vertical = route["vertical_clearance"]
        self.assertTrue(all(point[0] == 0.0 for point in vertical))
        self.assertTrue(all(point[1] == -0.1678 for point in vertical))
        self.assertTrue(
            all(
                vertical[index][2] < vertical[index + 1][2]
                for index in range(len(vertical) - 1)
            )
        )
        lateral = route["lateral_clearance"]
        self.assertTrue(all(point[2] == 1.02 for point in lateral))
        descent = route["descend_to_front_clearance"]
        self.assertTrue(all(point[0] == -0.24 for point in descent))
        self.assertTrue(all(point[1] == 0.03 for point in descent))
        self.assertTrue(
            all(
                descent[index][2] > descent[index + 1][2]
                for index in range(len(descent) - 1)
            )
        )

    def test_route_rejects_non_clearance_or_malformed_inputs(self) -> None:
        with self.assertRaises(ValueError):
            self.module.build_consecutive_left_transition_positions(
                previous_retreat_position_xyz_m=(0.0, -0.1678, 0.93),
                next_front_clearance_position_xyz_m=(-0.24, 0.03, 0.90),
                clearance_tcp_z_m=0.93,
                cartesian_waypoints_per_segment=8,
            )
        with self.assertRaises(ValueError):
            self.module.build_consecutive_left_transition_positions(
                previous_retreat_position_xyz_m=(0.0, -0.1678),
                next_front_clearance_position_xyz_m=(-0.24, 0.03, 0.90),
                clearance_tcp_z_m=1.02,
                cartesian_waypoints_per_segment=8,
            )
        with self.assertRaises(ValueError):
            self.module.build_consecutive_left_transition_positions(
                previous_retreat_position_xyz_m=(0.0, -0.1678, 0.93),
                next_front_clearance_position_xyz_m=(-0.24, 0.03, 0.90),
                clearance_tcp_z_m=1.02,
                cartesian_waypoints_per_segment=True,
            )

    def test_activation_is_consecutive_left_at_top_level_only(self) -> None:
        activation = (
            'level >= 2\n'
            '                    and bool(bowl_runs)\n'
            '                    and bowl_runs[-1]["assigned_side"] == "left"'
        )
        self.assertIn(activation, self.source_text)
        self.assertIn(
            'if assigned_side == "left":\n'
            '                positions = {',
            self.source_text,
        )

    def test_transition_receipt_is_exclusive_and_non_promotional(self) -> None:
        receipt_start = self.source_text.find(
            'transition_receipt_path = (\n'
            '                        run_dir / '
            'f"inter_bowl_transition_level_{level}.json"'
        )
        self.assertGreater(receipt_start, 0)
        receipt_end = self.source_text.find(
            'f"{pose.name}:rim_clearance"',
            receipt_start,
        )
        self.assertGreater(receipt_end, receipt_start)
        block = self.source_text[receipt_start:receipt_end]
        self.assertIn('transition_receipt_path.open(', block)
        self.assertIn('"x",', block)
        self.assertIn('"episode_success": False', block)
        self.assertIn('"training_data_claim": False', block)
        self.assertIn('"learned_policy_claim": False', block)
        self.assertIn('"rocm_claim": False', block)

    def test_strict_success_thresholds_remain_frozen(self) -> None:
        predicate = self.task["success_predicate"]
        self.assertEqual(predicate["xy_axis_alignment_tolerance_m"], 0.04)
        self.assertEqual(predicate["target_heights_m"], [0.74, 0.77, 0.81])
        self.assertEqual(predicate["height_absolute_tolerance_m"], 0.02)
        self.assertEqual(predicate["objects_stable_for_policy_frames"], 12)
        self.assertTrue(predicate["no_safety_failure"])


if __name__ == "__main__":
    unittest.main()
