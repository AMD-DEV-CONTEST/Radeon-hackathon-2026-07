"""Packing: layouts, no overlap, padding/extrusion, trim round trip, pages."""

from __future__ import annotations

import unittest

import numpy as np

from sprite_workshop.errors import UsageError
from sprite_workshop.model import Frame, FrameSet, Point, Rect, RgbaImage, Size
from sprite_workshop.packing import PackSpec, pack_frames


def make_frame(
    frame_id: str,
    size: tuple[int, int] = (8, 8),
    *,
    rect: tuple[int, int, int, int] | None = None,
    color: tuple[int, int, int, int] = (200, 60, 80, 255),
) -> Frame:
    width, height = size
    array = np.zeros((height, width, 4), np.uint8)
    x, y, w, h = rect if rect else (0, 0, width, height)
    array[y : y + h, x : x + w] = color
    image = RgbaImage(array)
    return Frame(
        id=frame_id,
        image=image,
        source_size=image.size,
        trim_rect=Rect(0, 0, width, height),
        trim_offset=Point(0, 0),
        anchor=Point(width // 2, height),
    )


def frame_set(*frames: Frame) -> FrameSet:
    return FrameSet(id="s", frames=frames)


def overlaps(a: Rect, b: Rect) -> bool:
    return not (a.right <= b.x or b.right <= a.x or a.bottom <= b.y or b.bottom <= a.y)


class Layouts(unittest.TestCase):
    def setUp(self) -> None:
        self.frames = frame_set(*[make_frame(f"f{i}") for i in range(6)])

    def test_horizontal_is_one_row(self) -> None:
        bundle = pack_frames(self.frames, PackSpec(layout="horizontal"))
        self.assertEqual({f.rect.y for f in bundle.frames}, {0})
        self.assertEqual(bundle.pages[0].size.as_tuple(), (48, 8))

    def test_vertical_is_one_column(self) -> None:
        bundle = pack_frames(self.frames, PackSpec(layout="vertical"))
        self.assertEqual({f.rect.x for f in bundle.frames}, {0})
        self.assertEqual(bundle.pages[0].size.as_tuple(), (8, 48))

    def test_grid_by_columns(self) -> None:
        bundle = pack_frames(self.frames, PackSpec(layout="grid", columns=3))
        self.assertEqual(bundle.pages[0].size.as_tuple(), (24, 16))

    def test_grid_by_rows(self) -> None:
        bundle = pack_frames(self.frames, PackSpec(layout="grid", rows=2))
        self.assertEqual(bundle.pages[0].size.as_tuple(), (24, 16))

    def test_grid_needs_a_dimension(self) -> None:
        with self.assertRaises(UsageError):
            PackSpec(layout="grid")

    def test_grid_rejects_both_dimensions(self) -> None:
        with self.assertRaises(UsageError):
            PackSpec(layout="grid", columns=2, rows=2)

    def test_compact_packs_everything(self) -> None:
        bundle = pack_frames(self.frames, PackSpec(layout="compact"))
        self.assertEqual(len(bundle.frames), 6)
        self.assertEqual(len(bundle.pages), 1)

    def test_unknown_layout(self) -> None:
        with self.assertRaises(UsageError):
            PackSpec(layout="spiral")

    def test_empty_frame_set(self) -> None:
        with self.assertRaises(UsageError):
            pack_frames(FrameSet(id="s", frames=()))


class NoOverlap(unittest.TestCase):
    def _check(self, bundle) -> None:
        by_page: dict[int, list[Rect]] = {}
        for frame in bundle.frames:
            by_page.setdefault(frame.page, []).append(frame.rect)
        for page_index, rects in by_page.items():
            page = bundle.pages[page_index]
            for i, a in enumerate(rects):
                self.assertGreaterEqual(a.x, 0)
                self.assertGreaterEqual(a.y, 0)
                self.assertLessEqual(
                    a.right, page.size.width, "rect past the page edge"
                )
                self.assertLessEqual(a.bottom, page.size.height)
                for b in rects[i + 1 :]:
                    self.assertFalse(overlaps(a, b), f"{a} overlaps {b}")

    def test_all_layouts_produce_disjoint_rects(self) -> None:
        frames = frame_set(
            *[make_frame(f"f{i}", (4 + i * 3, 6 + (i % 4) * 2)) for i in range(12)]
        )
        for layout in ("horizontal", "vertical", "grid", "compact"):
            spec = PackSpec(layout=layout, columns=4 if layout == "grid" else None)
            with self.subTest(layout=layout):
                self._check(pack_frames(frames, spec))

    def test_compact_with_padding_and_margin(self) -> None:
        frames = frame_set(*[make_frame(f"f{i}", (5 + i, 7)) for i in range(10)])
        bundle = pack_frames(frames, PackSpec(layout="compact", padding=2, margin=3))
        self._check(bundle)
        for frame in bundle.frames:
            self.assertGreaterEqual(frame.rect.x, 3)
            self.assertGreaterEqual(frame.rect.y, 3)

    def test_padding_actually_separates(self) -> None:
        frames = frame_set(make_frame("a"), make_frame("b"))
        bundle = pack_frames(frames, PackSpec(layout="horizontal", padding=4))
        rects = sorted((f.rect for f in bundle.frames), key=lambda r: r.x)
        self.assertEqual(rects[1].x - rects[0].right, 4)


class PixelContent(unittest.TestCase):
    def test_frame_pixels_land_at_their_rect(self) -> None:
        frames = frame_set(
            make_frame("a", color=(10, 20, 30, 255)),
            make_frame("b", color=(40, 50, 60, 255)),
        )
        bundle = pack_frames(frames, PackSpec(layout="horizontal"))
        page = bundle.pages[0].image.array
        for frame, colour in zip(bundle.frames, [(10, 20, 30, 255), (40, 50, 60, 255)]):
            patch = page[
                frame.rect.y : frame.rect.bottom, frame.rect.x : frame.rect.right
            ]
            self.assertEqual(set(map(tuple, patch.reshape(-1, 4).tolist())), {colour})

    def test_extrusion_repeats_the_edge(self) -> None:
        frames = frame_set(make_frame("a", (4, 4), color=(9, 9, 9, 255)))
        bundle = pack_frames(frames, PackSpec(layout="horizontal", extrude=2, margin=0))
        page = bundle.pages[0].image.array
        rect = bundle.frames[0].rect
        # One pixel outside the rect on each side carries the edge colour.
        self.assertEqual(tuple(page[rect.y - 1, rect.x].tolist()), (9, 9, 9, 255))
        self.assertEqual(tuple(page[rect.bottom, rect.x].tolist()), (9, 9, 9, 255))
        self.assertEqual(tuple(page[rect.y, rect.x - 1].tolist()), (9, 9, 9, 255))
        self.assertEqual(tuple(page[rect.y, rect.right].tolist()), (9, 9, 9, 255))

    def test_extrusion_does_not_shift_the_rect_contents(self) -> None:
        frames = frame_set(make_frame("a", (4, 4), color=(9, 9, 9, 255)))
        bundle = pack_frames(frames, PackSpec(layout="horizontal", extrude=1))
        page = bundle.pages[0].image.array
        rect = bundle.frames[0].rect
        patch = page[rect.y : rect.bottom, rect.x : rect.right]
        self.assertEqual(patch.shape[:2], (4, 4))
        self.assertTrue((patch[:, :, 3] == 255).all())

    def test_rotation_is_off(self) -> None:
        frames = frame_set(make_frame("a", (12, 4)))
        bundle = pack_frames(frames, PackSpec(layout="compact"))
        self.assertFalse(bundle.frames[0].rotated)
        self.assertEqual(bundle.frames[0].rect.width, 12)


class TrimRoundTrip(unittest.TestCase):
    def test_trim_records_offset_and_source_size(self) -> None:
        """Trimming is only safe if the original canvas can be rebuilt."""

        frames = frame_set(make_frame("a", (16, 16), rect=(3, 5, 6, 4)))
        bundle = pack_frames(frames, PackSpec(layout="horizontal", trim=True))
        packed = bundle.frames[0]

        self.assertEqual(packed.rect.width, 6)
        self.assertEqual(packed.rect.height, 4)
        self.assertEqual(packed.trim_offset.as_tuple(), (3, 5))
        self.assertEqual(packed.source_size.as_tuple(), (16, 16))

        # Rebuild the original canvas from the atlas plus the metadata.
        page = bundle.pages[0].image.array
        rebuilt = np.zeros((16, 16, 4), np.uint8)
        rebuilt[
            packed.trim_offset.y : packed.trim_offset.y + packed.rect.height,
            packed.trim_offset.x : packed.trim_offset.x + packed.rect.width,
        ] = page[packed.rect.y : packed.rect.bottom, packed.rect.x : packed.rect.right]
        np.testing.assert_array_equal(rebuilt, frames.frames[0].image.array)

    def test_untrimmed_keeps_the_full_canvas(self) -> None:
        frames = frame_set(make_frame("a", (16, 16), rect=(3, 5, 6, 4)))
        bundle = pack_frames(frames, PackSpec(layout="horizontal", trim=False))
        self.assertEqual(bundle.frames[0].rect.width, 16)
        self.assertEqual(bundle.frames[0].trim_offset.as_tuple(), (0, 0))

    def test_fully_transparent_frame_survives_trimming(self) -> None:
        blank = np.zeros((8, 8, 4), np.uint8)
        image = RgbaImage(blank)
        frame = Frame(
            id="blank",
            image=image,
            source_size=image.size,
            trim_rect=Rect(0, 0, 8, 8),
            trim_offset=Point(0, 0),
            anchor=Point(4, 8),
        )
        bundle = pack_frames(frame_set(frame), PackSpec(layout="horizontal", trim=True))
        self.assertEqual(len(bundle.frames), 1)
        self.assertEqual(bundle.frames[0].rect.width, 1)


class Pages(unittest.TestCase):
    def test_multi_page_splits_when_full(self) -> None:
        frames = frame_set(*[make_frame(f"f{i}", (20, 20)) for i in range(12)])
        bundle = pack_frames(
            frames,
            PackSpec(layout="compact", max_size=Size(48, 48), multi_page=True),
        )
        self.assertGreater(len(bundle.pages), 1)
        self.assertEqual(len(bundle.frames), 12)
        self.assertEqual({f.page for f in bundle.frames}, set(range(len(bundle.pages))))

    def test_single_page_overflow_is_an_error(self) -> None:
        frames = frame_set(*[make_frame(f"f{i}", (20, 20)) for i in range(12)])
        with self.assertRaises(UsageError):
            pack_frames(frames, PackSpec(layout="compact", max_size=Size(48, 48)))

    def test_a_frame_larger_than_the_page_is_an_error(self) -> None:
        frames = frame_set(make_frame("huge", (100, 100)))
        with self.assertRaises(UsageError):
            pack_frames(
                frames,
                PackSpec(layout="compact", max_size=Size(32, 32), multi_page=True),
            )

    def test_fixed_layout_overflow_is_an_error(self) -> None:
        frames = frame_set(*[make_frame(f"f{i}", (40, 40)) for i in range(10)])
        with self.assertRaises(UsageError):
            pack_frames(frames, PackSpec(layout="horizontal", max_size=Size(64, 64)))

    def test_page_size_limit(self) -> None:
        with self.assertRaises(UsageError):
            PackSpec(max_size=Size(20000, 100))


class Dedupe(unittest.TestCase):
    def test_identical_frames_share_one_rect(self) -> None:
        frames = frame_set(
            make_frame("a", color=(1, 2, 3, 255)),
            make_frame("b", color=(1, 2, 3, 255)),
            make_frame("c", color=(9, 9, 9, 255)),
        )
        bundle = pack_frames(frames, PackSpec(layout="compact", dedupe=True))

        self.assertEqual(len(bundle.frames), 3, "every input frame still appears")
        rects = {f.id: f.rect.as_tuple() for f in bundle.frames}
        self.assertEqual(rects["a"], rects["b"])
        self.assertNotEqual(rects["a"], rects["c"])
        self.assertTrue(any(w.code == "pack.deduped" for w in bundle.warnings))

    def test_dedupe_off_keeps_separate_rects(self) -> None:
        frames = frame_set(
            make_frame("a", color=(1, 2, 3, 255)), make_frame("b", color=(1, 2, 3, 255))
        )
        bundle = pack_frames(frames, PackSpec(layout="compact", dedupe=False))
        rects = {f.id: f.rect.as_tuple() for f in bundle.frames}
        self.assertNotEqual(rects["a"], rects["b"])


class Metadata(unittest.TestCase):
    def test_tags_and_anchor_survive(self) -> None:
        frame = make_frame("a")
        frame = Frame(
            id=frame.id,
            image=frame.image,
            source_size=frame.source_size,
            trim_rect=frame.trim_rect,
            trim_offset=frame.trim_offset,
            anchor=Point(3, 7),
            tags={"action": "walk"},
        )
        bundle = pack_frames(frame_set(frame), PackSpec(layout="horizontal"))
        packed = bundle.frames[0]
        self.assertEqual(packed.anchor.as_tuple(), (3, 7))
        self.assertEqual(dict(packed.tags), {"action": "walk"})

    def test_bundle_json_shape(self) -> None:
        frames = frame_set(make_frame("a"), make_frame("b"))
        payload = pack_frames(frames, PackSpec(layout="horizontal")).to_dict()
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(len(payload["pages"]), 1)
        self.assertEqual(len(payload["frames"]), 2)
        for key in (
            "id",
            "page",
            "rect",
            "rotated",
            "source_size",
            "trim_offset",
            "anchor",
        ):
            self.assertIn(key, payload["frames"][0])

    def test_determinism(self) -> None:
        frames = frame_set(*[make_frame(f"f{i}", (3 + i * 2, 5 + i)) for i in range(9)])
        spec = PackSpec(layout="compact", padding=1)
        first = pack_frames(frames, spec)
        second = pack_frames(frames, spec)
        self.assertEqual(
            [f.rect.as_tuple() for f in first.frames],
            [f.rect.as_tuple() for f in second.frames],
        )
        np.testing.assert_array_equal(
            first.pages[0].image.array, second.pages[0].image.array
        )

    def test_frame_order_is_preserved_in_the_report(self) -> None:
        frames = frame_set(*[make_frame(f"f{i}", (4 + i, 4)) for i in range(5)])
        bundle = pack_frames(frames, PackSpec(layout="compact"))
        self.assertEqual([f.id for f in bundle.frames], [f"f{i}" for i in range(5)])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
