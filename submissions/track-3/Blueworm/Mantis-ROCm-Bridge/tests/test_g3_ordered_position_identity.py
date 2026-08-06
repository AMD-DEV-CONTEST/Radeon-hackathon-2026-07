from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.analyze_g3_ordered_position_identity import (
    analyze_ordered_position_rows,
    associate_ordered_positions,
    write_outputs,
)


class OrderedPositionIdentityTest(unittest.TestCase):
    def test_association_removes_list_slot_swap(self) -> None:
        frames = [
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
            [(0.01, 0.0, 0.0), (2.01, 0.0, 0.0), (1.01, 0.0, 0.0)],
        ]
        associated, assignments = associate_ordered_positions(frames)
        self.assertEqual(assignments, [(0, 1, 2), (0, 2, 1)])
        self.assertEqual(
            associated[1],
            [(0.01, 0.0, 0.0), (1.01, 0.0, 0.0), (2.01, 0.0, 0.0)],
        )

    def test_analysis_classifies_large_raw_swap_as_artifact(self) -> None:
        rows = [
            {
                "ordered_positions_xyz_m": [
                    [0.0, 0.0, 0.7],
                    [0.5, 0.0, 0.7],
                    [-0.5, 0.0, 0.7],
                ]
            },
            {
                "ordered_positions_xyz_m": [
                    [0.0, 0.0, 0.7],
                    [-0.5, 0.0, 0.7],
                    [0.5, 0.0, 0.7],
                ]
            },
        ]
        result = analyze_ordered_position_rows(rows)
        self.assertTrue(result["ordering_artifact_detected"])
        self.assertEqual(result["nonidentity_assignment_row_count"], 1)
        self.assertEqual(
            result["maximum_associated_identity_xy_displacement_m"],
            0.0,
        )
        self.assertEqual(
            result["maximum_raw_slot_xy_displacement_m"],
            1.0,
        )

    def test_output_is_non_overwriting_and_manifested(self) -> None:
        analysis = {
            "seed": 101,
            "frame_count": 2,
            "nonidentity_assignment_row_count": 1,
            "maximum_raw_slot_xy_displacement_m": 1.0,
            "maximum_associated_identity_xy_displacement_m": 0.0,
            "ordering_artifact_detected": True,
            "source_sha256": "a" * 64,
            "temporally_associated_identity_metrics": [
                {
                    "maximum_positive_z_from_initial_m": 0.0,
                    "maximum_consecutive_step_m": 0.0,
                }
                for _ in range(3)
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "new"
            write_outputs(output, [analysis])
            self.assertTrue((output / "analysis_files.SHA256SUMS").is_file())
            with self.assertRaises(FileExistsError):
                write_outputs(output, [analysis])


if __name__ == "__main__":
    unittest.main()
