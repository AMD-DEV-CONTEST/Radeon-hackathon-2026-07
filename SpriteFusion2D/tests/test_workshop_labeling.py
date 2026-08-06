"""Connected-component labelling: correctness, 4 vs 8, ordering, performance."""

from __future__ import annotations

import time
import unittest

import numpy as np

from sprite_workshop._labeling import border_connected, label_mask
from sprite_workshop.errors import UsageError


def mask_from_text(text: str) -> np.ndarray:
    rows = [stripped for line in text.splitlines() if (stripped := line.strip())]
    widths = {len(row) for row in rows}
    if len(widths) != 1:
        raise AssertionError(f"ragged mask literal: widths {sorted(widths)}")
    return np.array([[ch == "#" for ch in row] for row in rows], dtype=bool)


class BasicLabelling(unittest.TestCase):
    def test_empty_mask(self) -> None:
        result = label_mask(np.zeros((4, 4), dtype=bool))
        self.assertEqual(result.count, 0)
        self.assertTrue((result.labels == 0).all())

    def test_single_pixel(self) -> None:
        mask = np.zeros((3, 3), dtype=bool)
        mask[1, 1] = True
        result = label_mask(mask)
        self.assertEqual(result.count, 1)
        self.assertEqual(result.components[0].area, 1)
        self.assertEqual(result.components[0].bounds.as_tuple(), (1, 1, 1, 1))

    def test_full_mask_is_one_component(self) -> None:
        result = label_mask(np.ones((5, 7), dtype=bool))
        self.assertEqual(result.count, 1)
        self.assertEqual(result.components[0].area, 35)
        self.assertEqual(result.components[0].bounds.as_tuple(), (0, 0, 7, 5))

    def test_two_separate_blobs(self) -> None:
        mask = mask_from_text(
            """
            ##...
            ##...
            ...##
            ...##
            """
        )
        result = label_mask(mask)
        self.assertEqual(result.count, 2)
        self.assertEqual([c.area for c in result.components], [4, 4])
        self.assertEqual(result.components[0].bounds.as_tuple(), (0, 0, 2, 2))
        self.assertEqual(result.components[1].bounds.as_tuple(), (3, 2, 2, 2))

    def test_labels_cover_exactly_the_mask(self) -> None:
        rng = np.random.default_rng(11)
        mask = rng.random((40, 55)) < 0.4
        result = label_mask(mask, connectivity=8)
        np.testing.assert_array_equal(result.labels > 0, mask)

    def test_area_sums_match_mask(self) -> None:
        rng = np.random.default_rng(12)
        mask = rng.random((60, 60)) < 0.3
        for connectivity in (4, 8):
            result = label_mask(mask, connectivity=connectivity)
            self.assertEqual(sum(c.area for c in result.components), int(mask.sum()))

    def test_bounds_contain_their_pixels(self) -> None:
        rng = np.random.default_rng(13)
        mask = rng.random((50, 50)) < 0.35
        result = label_mask(mask, connectivity=8)
        for component in result.components:
            ys, xs = np.nonzero(result.labels == component.label)
            self.assertEqual(int(ys.min()), component.bounds.y)
            self.assertEqual(int(xs.min()), component.bounds.x)
            self.assertEqual(int(ys.max()), component.bounds.bottom - 1)
            self.assertEqual(int(xs.max()), component.bounds.right - 1)


class Connectivity(unittest.TestCase):
    def test_diagonal_split_under_4_joined_under_8(self) -> None:
        mask = mask_from_text(
            """
            #..
            .#.
            ..#
            """
        )
        self.assertEqual(label_mask(mask, connectivity=4).count, 3)
        self.assertEqual(label_mask(mask, connectivity=8).count, 1)

    def test_checkerboard(self) -> None:
        mask = np.indices((6, 6)).sum(axis=0) % 2 == 0
        self.assertEqual(label_mask(mask, connectivity=4).count, int(mask.sum()))
        self.assertEqual(label_mask(mask, connectivity=8).count, 1)

    def test_corner_touch_only(self) -> None:
        mask = mask_from_text(
            """
            ##..
            ##..
            ..##
            ..##
            """
        )
        self.assertEqual(label_mask(mask, connectivity=4).count, 2)
        self.assertEqual(label_mask(mask, connectivity=8).count, 1)

    def test_rejects_bad_connectivity(self) -> None:
        with self.assertRaises(UsageError):
            label_mask(np.ones((2, 2), dtype=bool), connectivity=6)

    def test_rejects_non_2d(self) -> None:
        with self.assertRaises(UsageError):
            label_mask(np.ones((2, 2, 3), dtype=bool))


class ShapeStress(unittest.TestCase):
    def test_u_shape_is_one_component(self) -> None:
        mask = mask_from_text(
            """
            #...#
            #...#
            #...#
            #####
            """
        )
        result = label_mask(mask)
        self.assertEqual(result.count, 1)
        # Two 3-pixel uprights plus the 5-pixel base; the corners belong to the base.
        self.assertEqual(result.components[0].area, 11)

    def test_ring_encloses_a_separate_hole(self) -> None:
        mask = mask_from_text(
            """
            #####
            #...#
            #.#.#
            #...#
            #####
            """
        )
        outer = label_mask(mask)
        self.assertEqual(outer.count, 2)  # ring plus the isolated inner pixel

        hole = label_mask(~mask, connectivity=4)
        self.assertEqual(hole.count, 1)  # the enclosed background ring

    def test_long_snake_is_one_component(self) -> None:
        """Serpentine shapes are the case naive propagation handles worst."""

        height, width = 101, 201
        mask = np.zeros((height, width), dtype=bool)
        for index, row in enumerate(range(0, height, 2)):
            mask[row, :] = True
            if row + 1 < height:
                column = width - 1 if index % 2 == 0 else 0
                mask[row + 1, column] = True
        result = label_mask(mask)
        self.assertEqual(result.count, 1)


class Ordering(unittest.TestCase):
    def test_components_sorted_by_top_left_height_width(self) -> None:
        mask = mask_from_text(
            """
            ..##..#
            ..##..#
            #.....#
            #......
            """
        )
        result = label_mask(mask)
        keys = [c.sort_key for c in result.components]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(
            [c.label for c in result.components], list(range(1, len(keys) + 1))
        )

    def test_ordering_is_stable_across_runs(self) -> None:
        rng = np.random.default_rng(99)
        mask = rng.random((70, 70)) < 0.25
        first = label_mask(mask, connectivity=8)
        second = label_mask(mask, connectivity=8)
        np.testing.assert_array_equal(first.labels, second.labels)
        self.assertEqual(
            [c.bounds.as_tuple() for c in first.components],
            [c.bounds.as_tuple() for c in second.components],
        )


class BorderConnectivity(unittest.TestCase):
    def test_interior_region_is_preserved(self) -> None:
        """The whole point: same-coloured pixels inside a character stay."""

        mask = np.zeros((7, 7), dtype=bool)
        mask[0, :] = True  # background touching the border
        mask[3, 3] = True  # an interior island of the same colour
        selected = border_connected(mask)
        self.assertTrue(selected[0, 0])
        self.assertFalse(selected[3, 3])

    def test_no_border_contact_selects_nothing(self) -> None:
        mask = np.zeros((6, 6), dtype=bool)
        mask[2:4, 2:4] = True
        self.assertFalse(border_connected(mask).any())

    def test_empty_mask(self) -> None:
        self.assertFalse(border_connected(np.zeros((5, 5), dtype=bool)).any())

    def test_eight_connectivity_reaches_diagonally(self) -> None:
        mask = mask_from_text(
            """
            #....
            .#...
            ..#..
            .....
            .....
            """
        )
        self.assertEqual(int(border_connected(mask, connectivity=4).sum()), 1)
        self.assertEqual(int(border_connected(mask, connectivity=8).sum()), 3)


class Performance(unittest.TestCase):
    """Guard rail for the 150 ms / 1024x1024 target (BACKEND_CLI_PLAN.md 12)."""

    def test_sprite_sheet_sized_mask(self) -> None:
        rng = np.random.default_rng(5)
        mask = np.zeros((1024, 1024), dtype=bool)
        # A grid of blobs, roughly what a real effects sheet looks like.
        for row in range(0, 1024, 64):
            for col in range(0, 1024, 64):
                h = int(rng.integers(20, 56))
                w = int(rng.integers(20, 56))
                mask[row : row + h, col : col + w] = True

        best = min(_timed(lambda: label_mask(mask, connectivity=8)) for _ in range(3))
        self.assertLess(best, 0.150, f"1024x1024 labelling took {best * 1000:.1f} ms")

    def test_pathological_stripes(self) -> None:
        """Many thin runs is the worst case for a run-based approach."""

        mask = np.zeros((1024, 1024), dtype=bool)
        mask[:, ::2] = True  # 512 runs per row, 524288 runs total
        best = min(_timed(lambda: label_mask(mask, connectivity=4)) for _ in range(2))
        # Deliberately loose: this input is adversarial and is recorded to
        # document the ceiling rather than to promise it.
        self.assertLess(best, 2.0, f"striped 1024x1024 took {best * 1000:.1f} ms")


def _timed(fn) -> float:
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
