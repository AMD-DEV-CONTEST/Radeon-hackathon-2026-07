"""Recovery adapter: both algorithms, alpha resampling, grid reporting.

The load-bearing assertion here is that adding alpha does not perturb a single
RGB bit, for either algorithm.  That is the extension of the legacy_exact
lossless promise (BACKEND_CLI_PLAN.md 8.1.1).
"""

from __future__ import annotations

import unittest

import numpy as np
import torch

from pixel_snapper_core import SnapConfig, snap_images, snap_images_with_grid
from sprite_workshop.errors import UsageError
from sprite_workshop.model import RgbaImage
from sprite_workshop.recovery import ALGORITHMS, RecoverySpec, recover_frames

ALL_ALGORITHMS = ALGORITHMS


def blocky_source(block: int = 8, cells_x: int = 20, cells_y: int = 16) -> np.ndarray:
    """A crisp upscaled pixel grid, the shape recovery is meant to undo.

    A small repeated palette rather than per-cell noise, because that is what
    real recovered pixel art looks like and what the detector is tuned for.
    """

    rng = np.random.default_rng(20260803)
    palette = rng.integers(0, 256, size=(12, 3), dtype=np.uint8)
    indices = rng.integers(0, len(palette), size=(cells_y, cells_x))
    cells = palette[indices]
    return np.kron(cells, np.ones((block, block, 1), dtype=np.uint8))


def to_rgba(rgb: np.ndarray, alpha: np.ndarray | None = None) -> RgbaImage:
    height, width, _ = rgb.shape
    out = np.empty((height, width, 4), dtype=np.uint8)
    out[:, :, :3] = rgb
    out[:, :, 3] = 255 if alpha is None else alpha
    return RgbaImage(out)


class CoreGridObservation(unittest.TestCase):
    """The only core change: a read-only grid alongside identical pixels."""

    def setUp(self) -> None:
        self.tensor = torch.from_numpy(
            blocky_source().astype(np.float32) / 255.0
        ).unsqueeze(0)

    def test_pixels_identical_to_snap_images(self) -> None:
        for algorithm in ALL_ALGORITHMS:
            with self.subTest(algorithm=algorithm):
                config = SnapConfig(algorithm=algorithm)
                plain = snap_images(self.tensor, config)
                with_grid = snap_images_with_grid(self.tensor, config)
                self.assertEqual(len(plain), len(with_grid))
                self.assertTrue(torch.equal(plain[0], with_grid[0][0]))

    def test_grid_matches_output_size_for_both_algorithms(self) -> None:
        for algorithm in ALL_ALGORITHMS:
            with self.subTest(algorithm=algorithm):
                frame, grid = snap_images_with_grid(
                    self.tensor, SnapConfig(algorithm=algorithm)
                )[0]
                height, width = int(frame.shape[1]), int(frame.shape[2])
                self.assertEqual(grid.output_size, (width, height))
                self.assertEqual(len(grid.column_cuts) - 1, width)
                self.assertEqual(len(grid.row_cuts) - 1, height)

    def test_cuts_are_sorted_and_span_the_input(self) -> None:
        source_h, source_w, _ = blocky_source().shape
        for algorithm in ALL_ALGORITHMS:
            with self.subTest(algorithm=algorithm):
                _frame, grid = snap_images_with_grid(
                    self.tensor, SnapConfig(algorithm=algorithm)
                )[0]
                self.assertEqual(grid.column_cuts[0], 0)
                self.assertEqual(grid.row_cuts[0], 0)
                self.assertEqual(grid.column_cuts[-1], source_w)
                self.assertEqual(grid.row_cuts[-1], source_h)
                self.assertEqual(list(grid.column_cuts), sorted(grid.column_cuts))
                self.assertEqual(list(grid.row_cuts), sorted(grid.row_cuts))


class RecoverBothAlgorithms(unittest.TestCase):
    def setUp(self) -> None:
        self.rgb = blocky_source()

    def test_recovers_to_a_smaller_grid(self) -> None:
        for algorithm in ALL_ALGORITHMS:
            with self.subTest(algorithm=algorithm):
                result = recover_frames(
                    [to_rgba(self.rgb)], RecoverySpec(algorithm=algorithm, device="cpu")
                )
                frame = result.frames.frames[0]
                self.assertLess(frame.size.width, self.rgb.shape[1])
                self.assertLess(frame.size.height, self.rgb.shape[0])
                self.assertEqual(result.algorithm, algorithm)

    def test_reported_grid_matches_output(self) -> None:
        for algorithm in ALL_ALGORITHMS:
            with self.subTest(algorithm=algorithm):
                result = recover_frames(
                    [to_rgba(self.rgb)], RecoverySpec(algorithm=algorithm, device="cpu")
                )
                frame = result.frames.frames[0]
                grid = result.grids[0]
                self.assertEqual((grid.columns, grid.rows), frame.size.as_tuple())

    def test_alpha_never_perturbs_rgb(self) -> None:
        """The whole point of 8.1.1: alpha rides alongside, it does not interfere."""

        alpha = np.full(self.rgb.shape[:2], 255, dtype=np.uint8)
        alpha[: self.rgb.shape[0] // 2, :] = 0

        for algorithm in ALL_ALGORITHMS:
            with self.subTest(algorithm=algorithm):
                spec = RecoverySpec(algorithm=algorithm, device="cpu")
                opaque = recover_frames([to_rgba(self.rgb)], spec).frames.frames[0]
                masked = recover_frames([to_rgba(self.rgb, alpha)], spec).frames.frames[
                    0
                ]

                # Compare only where the masked result kept its pixels; the
                # transparent half is zeroed by the 5.1 persistence rule.
                keep = masked.image.array[:, :, 3] > 0
                self.assertTrue(keep.any(), "expected some opaque output")
                np.testing.assert_array_equal(
                    opaque.image.array[:, :, :3][keep],
                    masked.image.array[:, :, :3][keep],
                )

    def test_fully_opaque_input_stays_opaque(self) -> None:
        for algorithm in ALL_ALGORITHMS:
            with self.subTest(algorithm=algorithm):
                result = recover_frames(
                    [to_rgba(self.rgb)], RecoverySpec(algorithm=algorithm, device="cpu")
                )
                self.assertTrue(
                    (result.frames.frames[0].image.array[:, :, 3] == 255).all()
                )

    def test_alpha_is_resampled_through_the_same_grid(self) -> None:
        alpha = np.full(self.rgb.shape[:2], 255, dtype=np.uint8)
        alpha[: self.rgb.shape[0] // 2, :] = 0

        for algorithm in ALL_ALGORITHMS:
            with self.subTest(algorithm=algorithm):
                result = recover_frames(
                    [to_rgba(self.rgb, alpha)],
                    RecoverySpec(algorithm=algorithm, device="cpu"),
                )
                out_alpha = result.frames.frames[0].image.array[:, :, 3]
                self.assertTrue(
                    (out_alpha[0] == 0).all(), "top rows should be transparent"
                )
                self.assertTrue(
                    (out_alpha[-1] == 255).all(), "bottom rows should be opaque"
                )
                # Hard alpha only: never a partial value.
                self.assertEqual(set(np.unique(out_alpha).tolist()) - {0, 255}, set())

    def test_ignore_alpha_forces_opaque(self) -> None:
        alpha = np.zeros(self.rgb.shape[:2], dtype=np.uint8)
        result = recover_frames(
            [to_rgba(self.rgb, alpha)],
            RecoverySpec(algorithm="optimized", device="cpu", ignore_alpha=True),
        )
        self.assertTrue((result.frames.frames[0].image.array[:, :, 3] == 255).all())

    def test_transparent_pixels_have_zero_rgb(self) -> None:
        alpha = np.full(self.rgb.shape[:2], 255, dtype=np.uint8)
        alpha[:12, :] = 0
        for algorithm in ALL_ALGORITHMS:
            with self.subTest(algorithm=algorithm):
                result = recover_frames(
                    [to_rgba(self.rgb, alpha)],
                    RecoverySpec(algorithm=algorithm, device="cpu"),
                )
                self.assertFalse(result.frames.frames[0].image.has_hidden_color())

    def test_determinism_on_cpu(self) -> None:
        for algorithm in ALL_ALGORITHMS:
            with self.subTest(algorithm=algorithm):
                spec = RecoverySpec(algorithm=algorithm, device="cpu")
                first = recover_frames([to_rgba(self.rgb)], spec).frames.frames[0]
                second = recover_frames([to_rgba(self.rgb)], spec).frames.frames[0]
                np.testing.assert_array_equal(first.image.array, second.image.array)


class RecoverySpecValidation(unittest.TestCase):
    def test_rejects_unknown_algorithm(self) -> None:
        with self.assertRaises(UsageError):
            RecoverySpec(algorithm="magic")  # type: ignore[arg-type]

    def test_rejects_output_scale_for_stored_assets(self) -> None:
        with self.assertRaises(UsageError):
            RecoverySpec(output_scale=4)

    def test_rejects_empty_input(self) -> None:
        with self.assertRaises(UsageError):
            recover_frames([], RecoverySpec(device="cpu"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
