"""Slicing: grid, components, manual, naming, tagging, and the round trip."""

from __future__ import annotations

import unittest

import numpy as np

from sprite_workshop.errors import UsageError
from sprite_workshop.model import Rect, RgbaImage, Size
from sprite_workshop.slicing import (
    ComponentsSpec,
    GridSpec,
    ManualSpec,
    NamedRect,
    SliceSpec,
    reassemble,
    slice_frames,
)


def sheet(width: int, height: int, fill: int = 0, alpha: int = 255) -> RgbaImage:
    array = np.zeros((height, width, 4), np.uint8)
    array[:, :, :3] = fill
    array[:, :, 3] = alpha
    return RgbaImage(array)


def sheet_with_blobs(cols: int = 4, rows: int = 2, cell: int = 16) -> RgbaImage:
    """A transparent sheet with one opaque blob per cell, each a unique colour."""

    array = np.zeros((rows * cell, cols * cell, 4), np.uint8)
    for r in range(rows):
        for c in range(cols):
            y, x = r * cell + 4, c * cell + 4
            array[y : y + 8, x : x + 8, :3] = (30 + r * 60, 40 + c * 40, 90)
            array[y : y + 8, x : x + 8, 3] = 255
    return RgbaImage(array)


class GridMode(unittest.TestCase):
    def test_by_count(self) -> None:
        result = slice_frames(
            sheet(64, 32), SliceSpec(grid=GridSpec(columns=4, rows=2)), set_id="walk"
        )
        self.assertEqual(len(result.frames), 8)
        for frame in result.frames.frames:
            self.assertEqual(frame.size.as_tuple(), (16, 16))

    def test_by_cell_size(self) -> None:
        result = slice_frames(
            sheet(64, 32), SliceSpec(grid=GridSpec(cell_width=16, cell_height=16))
        )
        self.assertEqual(len(result.frames), 8)

    def test_count_and_size_together_is_rejected(self) -> None:
        with self.assertRaises(UsageError):
            GridSpec(columns=4, cell_width=16)

    def test_neither_is_rejected(self) -> None:
        with self.assertRaises(UsageError):
            GridSpec()

    def test_margins_and_gaps(self) -> None:
        # 2 + 16 + 4 + 16 + 2 = 40 wide
        result = slice_frames(
            sheet(40, 16),
            SliceSpec(
                grid=GridSpec(columns=2, rows=1, margin=(2, 0, 2, 0), gap=(4, 0))
            ),
        )
        rects = [r.as_tuple() for r in result.source_rects]
        self.assertEqual(rects, [(2, 0, 16, 16), (22, 0, 16, 16)])

    def test_non_divisible_errors_by_default(self) -> None:
        with self.assertRaises(UsageError):
            slice_frames(sheet(63, 32), SliceSpec(grid=GridSpec(columns=4, rows=2)))

    def test_non_divisible_crop(self) -> None:
        result = slice_frames(
            sheet(63, 32), SliceSpec(grid=GridSpec(columns=4, rows=2, tail="crop"))
        )
        self.assertEqual(result.frames.frames[0].size.width, 15)
        self.assertTrue(any(w.code == "slice.tail_cropped" for w in result.warnings))

    def test_non_divisible_pad(self) -> None:
        result = slice_frames(
            sheet(63, 32), SliceSpec(grid=GridSpec(columns=4, rows=2, tail="pad"))
        )
        self.assertEqual(result.frames.frames[0].size.width, 16)
        self.assertTrue(any(w.code == "slice.tail_padded" for w in result.warnings))

    def test_padded_tail_cell_is_transparent_past_the_edge(self) -> None:
        result = slice_frames(
            sheet(63, 16), SliceSpec(grid=GridSpec(columns=4, rows=1, tail="pad"))
        )
        last = result.frames.frames[-1].image.array
        # The sheet ran out 1px early, so the final column is transparent.
        self.assertEqual(int(last[0, -1, 3]), 0)

    def test_empty_cells_are_skipped_by_default(self) -> None:
        array = np.zeros((16, 64, 4), np.uint8)
        array[:, 0:16, 3] = 255  # only the first cell has content
        result = slice_frames(
            RgbaImage(array), SliceSpec(grid=GridSpec(columns=4, rows=1))
        )
        self.assertEqual(len(result.frames), 1)
        self.assertTrue(any(w.code == "slice.empty_skipped" for w in result.warnings))

    def test_empty_cells_can_be_kept(self) -> None:
        array = np.zeros((16, 64, 4), np.uint8)
        array[:, 0:16, 3] = 255
        result = slice_frames(
            RgbaImage(array),
            SliceSpec(grid=GridSpec(columns=4, rows=1, keep_empty=True)),
        )
        self.assertEqual(len(result.frames), 4)

    def test_all_empty_is_an_error(self) -> None:
        with self.assertRaises(UsageError):
            slice_frames(
                sheet(32, 16, alpha=0), SliceSpec(grid=GridSpec(columns=2, rows=1))
            )

    def test_column_reading_order(self) -> None:
        by_row = slice_frames(
            sheet_with_blobs(), SliceSpec(grid=GridSpec(columns=4, rows=2, order="row"))
        )
        by_col = slice_frames(
            sheet_with_blobs(),
            SliceSpec(grid=GridSpec(columns=4, rows=2, order="column")),
        )
        self.assertEqual(
            [r.as_tuple()[:2] for r in by_row.source_rects][:4],
            [(0, 0), (16, 0), (32, 0), (48, 0)],
        )
        self.assertEqual(
            [r.as_tuple()[:2] for r in by_col.source_rects][:2], [(0, 0), (0, 16)]
        )

    def test_margins_that_eat_everything_are_rejected(self) -> None:
        with self.assertRaises(UsageError):
            slice_frames(
                sheet(16, 16),
                SliceSpec(grid=GridSpec(columns=1, rows=1, margin=(9, 0, 9, 0))),
            )


class RoundTrip(unittest.TestCase):
    def test_grid_slices_reassemble_exactly(self) -> None:
        """The provenance metadata has to survive a full round trip."""

        original = sheet_with_blobs(cols=4, rows=2, cell=16)
        result = slice_frames(
            original, SliceSpec(grid=GridSpec(columns=4, rows=2, keep_empty=True))
        )
        rebuilt = reassemble(result, Size(original.width, original.height))
        np.testing.assert_array_equal(rebuilt.array, original.array)

    def test_manual_slices_reassemble(self) -> None:
        original = sheet_with_blobs(cols=2, rows=1, cell=16)
        spec = SliceSpec(
            mode="manual",
            manual=ManualSpec(
                rects=(
                    NamedRect("left", Rect(0, 0, 16, 16)),
                    NamedRect("right", Rect(16, 0, 16, 16)),
                )
            ),
            name_template="{name}",
        )
        result = slice_frames(original, spec)
        rebuilt = reassemble(result, Size(original.width, original.height))
        np.testing.assert_array_equal(rebuilt.array, original.array)


class ComponentsMode(unittest.TestCase):
    def test_finds_one_box_per_blob(self) -> None:
        result = slice_frames(
            sheet_with_blobs(),
            SliceSpec(mode="components", components=ComponentsSpec()),
        )
        self.assertEqual(len(result.frames), 8)
        for frame in result.frames.frames:
            self.assertEqual(frame.size.as_tuple(), (8, 8))

    def test_min_area_drops_specks(self) -> None:
        array = np.zeros((32, 32, 4), np.uint8)
        array[4:12, 4:12, 3] = 255  # a real blob
        array[20, 20, 3] = 255  # a speck
        image = RgbaImage(array)

        kept = slice_frames(
            image, SliceSpec(mode="components", components=ComponentsSpec())
        )
        self.assertEqual(len(kept.frames), 2)

        filtered = slice_frames(
            image, SliceSpec(mode="components", components=ComponentsSpec(min_area=4))
        )
        self.assertEqual(len(filtered.frames), 1)
        self.assertTrue(
            any(w.code == "slice.specks_dropped" for w in filtered.warnings)
        )

    def test_merge_gap_joins_detached_parts(self) -> None:
        array = np.zeros((32, 32, 4), np.uint8)
        array[4:12, 4:12, 3] = 255
        array[4:12, 14:20, 3] = 255  # 2px away, a detached weapon piece
        image = RgbaImage(array)

        apart = slice_frames(
            image, SliceSpec(mode="components", components=ComponentsSpec())
        )
        self.assertEqual(len(apart.frames), 2)

        joined = slice_frames(
            image, SliceSpec(mode="components", components=ComponentsSpec(merge_gap=3))
        )
        self.assertEqual(len(joined.frames), 1)
        self.assertEqual(joined.source_rects[0].as_tuple(), (4, 4, 16, 8))

    def test_padding_expands_and_clips(self) -> None:
        array = np.zeros((32, 32, 4), np.uint8)
        array[0:8, 0:8, 3] = 255  # flush against the corner
        result = slice_frames(
            RgbaImage(array),
            SliceSpec(mode="components", components=ComponentsSpec(padding=2)),
        )
        self.assertEqual(result.source_rects[0].as_tuple(), (0, 0, 10, 10))

    def test_reading_order_groups_into_bands(self) -> None:
        """Rows that differ by a pixel must not interleave."""

        array = np.zeros((40, 40, 4), np.uint8)
        array[2:8, 20:26, 3] = 255  # top-right, slightly higher
        array[3:9, 2:8, 3] = 255  # top-left
        array[24:30, 20:26, 3] = 255  # bottom-right
        array[25:31, 2:8, 3] = 255  # bottom-left

        result = slice_frames(
            RgbaImage(array), SliceSpec(mode="components", components=ComponentsSpec())
        )
        xs = [r.x for r in result.source_rects]
        self.assertEqual(
            xs, [2, 20, 2, 20], "should read left-to-right within each band"
        )

    def test_fully_transparent_sheet_is_an_error(self) -> None:
        with self.assertRaises(UsageError):
            slice_frames(
                sheet(16, 16, alpha=0),
                SliceSpec(mode="components", components=ComponentsSpec()),
            )


class ManualMode(unittest.TestCase):
    def test_names_become_ids(self) -> None:
        result = slice_frames(
            sheet_with_blobs(cols=2, rows=1),
            SliceSpec(
                mode="manual",
                manual=ManualSpec(
                    rects=(
                        NamedRect("head", Rect(0, 0, 16, 16)),
                        NamedRect("body", Rect(16, 0, 16, 16)),
                    )
                ),
                name_template="{name}",
            ),
        )
        self.assertEqual([f.id for f in result.frames.frames], ["head", "body"])

    def test_out_of_bounds_is_rejected(self) -> None:
        with self.assertRaises(UsageError):
            slice_frames(
                sheet(16, 16),
                SliceSpec(
                    mode="manual",
                    manual=ManualSpec(rects=(NamedRect("x", Rect(8, 8, 16, 16)),)),
                    name_template="{name}",
                ),
            )

    def test_overlap_warns_but_proceeds(self) -> None:
        result = slice_frames(
            sheet(32, 32),
            SliceSpec(
                mode="manual",
                manual=ManualSpec(
                    rects=(
                        NamedRect("a", Rect(0, 0, 20, 20)),
                        NamedRect("b", Rect(10, 10, 20, 20)),
                    )
                ),
                name_template="{name}",
            ),
        )
        self.assertEqual(len(result.frames), 2)
        self.assertTrue(any(w.code == "slice.overlap" for w in result.warnings))

    def test_empty_rect_list_is_rejected(self) -> None:
        with self.assertRaises(UsageError):
            ManualSpec()

    def test_edge_to_edge_neighbours_do_not_warn(self) -> None:
        """Half-open rects that merely touch share no pixel, in either axis."""

        for name, rects in (
            ("horizontal", (Rect(0, 0, 16, 16), Rect(16, 0, 16, 16))),
            ("vertical", (Rect(0, 0, 16, 16), Rect(0, 16, 16, 16))),
        ):
            with self.subTest(direction=name):
                image = sheet(32, 32)
                result = slice_frames(
                    image,
                    SliceSpec(
                        mode="manual",
                        manual=ManualSpec(
                            rects=(NamedRect("a", rects[0]), NamedRect("b", rects[1]))
                        ),
                        name_template="{name}",
                    ),
                )
                self.assertEqual(
                    [w.code for w in result.warnings],
                    [],
                    f"{name} neighbours must not warn",
                )

    def test_overlap_is_detected_in_both_axes(self) -> None:
        for name, second in (
            ("horizontal", Rect(15, 0, 16, 16)),
            ("vertical", Rect(0, 15, 16, 16)),
        ):
            with self.subTest(direction=name):
                result = slice_frames(
                    sheet(32, 32),
                    SliceSpec(
                        mode="manual",
                        manual=ManualSpec(
                            rects=(
                                NamedRect("a", Rect(0, 0, 16, 16)),
                                NamedRect("b", second),
                            )
                        ),
                        name_template="{name}",
                    ),
                )
                self.assertTrue(any(w.code == "slice.overlap" for w in result.warnings))


class NamingAndTagging(unittest.TestCase):
    def test_default_template(self) -> None:
        result = slice_frames(
            sheet(64, 16), SliceSpec(grid=GridSpec(columns=4, rows=1)), set_id="walk"
        )
        self.assertEqual(
            [f.id for f in result.frames.frames], [f"walk_0{i}" for i in range(4)]
        )

    def test_grid_placeholders(self) -> None:
        result = slice_frames(
            sheet(32, 32),
            SliceSpec(
                grid=GridSpec(columns=2, rows=2), name_template="{set}_r{row}c{col}"
            ),
            set_id="hero",
        )
        self.assertEqual(
            [f.id for f in result.frames.frames],
            ["hero_r0c0", "hero_r0c1", "hero_r1c0", "hero_r1c1"],
        )

    def test_row_tagging(self) -> None:
        """This is what makes by-tag selection and clips possible at all."""

        result = slice_frames(
            sheet(64, 32),
            SliceSpec(
                grid=GridSpec(columns=4, rows=2),
                tags={"action": "walk"},
                tag_rows={0: {"direction": "south"}, 1: {"direction": "north"}},
                name_template="{tag:action}_{tag:direction}_{index:02d}",
            ),
        )
        ids = [f.id for f in result.frames.frames]
        self.assertEqual(ids[0], "walk_south_00")
        self.assertEqual(ids[4], "walk_north_04")
        self.assertEqual(
            dict(result.frames.frames[0].tags), {"action": "walk", "direction": "south"}
        )
        self.assertEqual(
            dict(result.frames.frames[7].tags), {"action": "walk", "direction": "north"}
        )

    def test_column_tagging(self) -> None:
        result = slice_frames(
            sheet(32, 16),
            SliceSpec(
                grid=GridSpec(columns=2, rows=1),
                tag_cols={0: {"variant": "a"}, 1: {"variant": "b"}},
            ),
        )
        self.assertEqual(result.frames.frames[0].tags["variant"], "a")
        self.assertEqual(result.frames.frames[1].tags["variant"], "b")

    def test_id_collisions_are_deduped_with_a_warning(self) -> None:
        result = slice_frames(
            sheet(64, 16),
            SliceSpec(grid=GridSpec(columns=4, rows=1), name_template="{set}"),
            set_id="same",
        )
        self.assertEqual(
            [f.id for f in result.frames.frames], ["same", "same_2", "same_3", "same_4"]
        )
        self.assertTrue(any(w.code == "slice.id_collision" for w in result.warnings))

    def test_invalid_tag_is_rejected(self) -> None:
        with self.assertRaises(UsageError):
            SliceSpec(grid=GridSpec(columns=1, rows=1), tags={"Action": "walk"})


class Reporting(unittest.TestCase):
    def test_dry_run_report_has_boxes_order_and_tags(self) -> None:
        result = slice_frames(
            sheet(64, 32),
            SliceSpec(
                grid=GridSpec(columns=4, rows=2), tag_rows={0: {"direction": "south"}}
            ),
            set_id="walk",
        )
        payload = result.to_dict()
        self.assertEqual(payload["count"], 8)
        first = payload["frames"][0]
        self.assertEqual(first["rect"], [0, 0, 16, 16])
        self.assertEqual(first["index"], 0)
        self.assertEqual(first["tags"], {"direction": "south"})

    def test_transparent_pixels_are_normalised(self) -> None:
        array = np.zeros((16, 32, 4), np.uint8)
        array[:, :, :3] = 200  # hidden colour under full transparency
        array[0:8, 0:8, 3] = 255
        result = slice_frames(
            RgbaImage(array),
            SliceSpec(grid=GridSpec(columns=2, rows=1, keep_empty=True)),
        )
        for frame in result.frames.frames:
            self.assertFalse(frame.image.has_hidden_color())

    def test_determinism(self) -> None:
        image = sheet_with_blobs()
        spec = SliceSpec(mode="components", components=ComponentsSpec())
        first = slice_frames(image, spec)
        second = slice_frames(image, spec)
        self.assertEqual(
            [r.as_tuple() for r in first.source_rects],
            [r.as_tuple() for r in second.source_rects],
        )
        self.assertEqual(
            [f.id for f in first.frames.frames], [f.id for f in second.frames.frames]
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
