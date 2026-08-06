"""Alignment: registration points, canvases, invariance, empty frames."""

from __future__ import annotations

import unittest
from dataclasses import replace

import numpy as np

from sprite_workshop.alignment import AlignmentSpec, align_frames, opaque_bounds
from sprite_workshop.errors import UsageError
from sprite_workshop.model import Frame, FrameSet, Point, Rect, RgbaImage, Size


def frame_with_blob(
    frame_id: str,
    canvas: tuple[int, int] = (16, 16),
    blob: tuple[int, int, int, int] = (4, 4, 6, 8),
    color: tuple[int, int, int] = (200, 60, 80),
) -> Frame:
    width, height = canvas
    array = np.zeros((height, width, 4), np.uint8)
    x, y, w, h = blob
    array[y : y + h, x : x + w, :3] = color
    array[y : y + h, x : x + w, 3] = 255
    image = RgbaImage(array)
    return Frame(
        id=frame_id,
        image=image,
        source_size=image.size,
        trim_rect=Rect(0, 0, width, height),
        trim_offset=Point(0, 0),
        anchor=Point(width // 2, height),
    )


def empty_frame(frame_id: str, canvas: tuple[int, int] = (16, 16)) -> Frame:
    array = np.zeros((canvas[1], canvas[0], 4), np.uint8)
    image = RgbaImage(array)
    return Frame(
        id=frame_id,
        image=image,
        source_size=image.size,
        trim_rect=Rect(0, 0, canvas[0], canvas[1]),
        trim_offset=Point(0, 0),
        anchor=Point(canvas[0] // 2, canvas[1]),
    )


def color_multiset(frames) -> dict[tuple[int, int, int, int], int]:
    """Count every visible pixel colour, ignoring position."""

    counts: dict[tuple[int, int, int, int], int] = {}
    for frame in frames:
        array = frame.image.array
        for pixel in map(tuple, array[array[:, :, 3] > 0].tolist()):
            counts[pixel] = counts.get(pixel, 0) + 1
    return counts


def bounds_in(frame: Frame) -> Rect:
    box = opaque_bounds(frame.image)
    assert box is not None
    return box


class OpaqueBounds(unittest.TestCase):
    def test_finds_the_blob(self) -> None:
        frame = frame_with_blob("a", blob=(3, 5, 4, 6))
        self.assertEqual(bounds_in(frame).as_tuple(), (3, 5, 4, 6))

    def test_empty_frame_has_none(self) -> None:
        self.assertIsNone(opaque_bounds(empty_frame("e").image))


class FeetMode(unittest.TestCase):
    def test_baselines_line_up(self) -> None:
        """The whole point of feet alignment: no bobbing while walking."""

        frames = FrameSet(
            id="walk",
            frames=(
                frame_with_blob("a", blob=(4, 2, 6, 10)),  # tall, high
                frame_with_blob("b", blob=(6, 6, 6, 6)),  # short, low
                frame_with_blob("c", blob=(2, 4, 6, 8)),
            ),
        )
        result = align_frames(frames, AlignmentSpec(mode="feet"))

        bottoms = {bounds_in(f).bottom for f in result.frames.frames}
        self.assertEqual(
            len(bottoms), 1, f"feet should share one baseline, got {bottoms}"
        )

    def test_horizontal_centres_line_up(self) -> None:
        frames = FrameSet(
            id="walk",
            frames=(
                frame_with_blob("a", blob=(1, 4, 4, 8)),
                frame_with_blob("b", blob=(9, 4, 4, 8)),
            ),
        )
        result = align_frames(frames, AlignmentSpec(mode="feet"))
        centres = {
            bounds_in(f).x + bounds_in(f).width // 2 for f in result.frames.frames
        }
        self.assertEqual(len(centres), 1)

    def test_anchor_is_shared_and_sits_on_the_baseline(self) -> None:
        frames = FrameSet(
            id="walk",
            frames=(frame_with_blob("a", blob=(4, 2, 6, 10)), frame_with_blob("b")),
        )
        result = align_frames(frames, AlignmentSpec(mode="feet"))
        self.assertEqual({f.anchor for f in result.frames.frames}, {result.anchor})
        self.assertEqual(bounds_in(result.frames.frames[0]).bottom, result.anchor.y)


class OtherModes(unittest.TestCase):
    def test_center_aligns_bounding_box_centres(self) -> None:
        frames = FrameSet(
            id="s",
            frames=(
                frame_with_blob("a", blob=(0, 0, 4, 4)),
                frame_with_blob("b", blob=(10, 10, 4, 4)),
            ),
        )
        result = align_frames(frames, AlignmentSpec(mode="center"))
        centres = {
            (
                bounds_in(f).x + bounds_in(f).width // 2,
                bounds_in(f).y + bounds_in(f).height // 2,
            )
            for f in result.frames.frames
        }
        self.assertEqual(len(centres), 1)

    def test_canvas_center_ignores_content(self) -> None:
        frames = FrameSet(
            id="s",
            frames=(
                frame_with_blob("a", blob=(0, 0, 2, 2)),
                frame_with_blob("b", blob=(12, 12, 2, 2)),
            ),
        )
        result = align_frames(frames, AlignmentSpec(mode="canvas_center"))
        # Same canvas size in, so nothing should move at all.
        self.assertEqual(result.canvas.as_tuple(), (16, 16))
        for placement in result.placements:
            self.assertEqual(placement.offset.as_tuple(), (0, 0))

    def test_anchor_mode_uses_declared_anchors(self) -> None:
        # Two identical images with different declared anchors must end up
        # offset by exactly the difference between those anchors.
        a = replace(frame_with_blob("a"), anchor=Point(4, 10))
        b = replace(frame_with_blob("b"), anchor=Point(9, 10))
        result = align_frames(
            FrameSet(id="s", frames=(a, b)), AlignmentSpec(mode="anchor")
        )

        self.assertEqual({f.anchor for f in result.frames.frames}, {result.anchor})
        dx = result.placements[0].offset.x - result.placements[1].offset.x
        self.assertEqual(dx, 5, "offset difference must equal the anchor difference")

    def test_custom_offsets(self) -> None:
        frames = FrameSet(id="s", frames=(frame_with_blob("a"), frame_with_blob("b")))
        result = align_frames(
            frames,
            AlignmentSpec(mode="custom", offsets={"a": Point(0, 0), "b": Point(4, 2)}),
        )
        self.assertEqual(result.placements[0].offset.as_tuple(), (0, 0))
        self.assertEqual(result.placements[1].offset.as_tuple(), (4, 2))
        self.assertEqual(result.canvas.as_tuple(), (20, 18))

    def test_custom_needs_every_frame(self) -> None:
        frames = FrameSet(id="s", frames=(frame_with_blob("a"), frame_with_blob("b")))
        with self.assertRaises(UsageError):
            align_frames(
                frames, AlignmentSpec(mode="custom", offsets={"a": Point(0, 0)})
            )


class Invariance(unittest.TestCase):
    def test_only_positions_change_never_colours(self) -> None:
        """Alignment moves pixels; it must not create or alter a single one."""

        frames = FrameSet(
            id="s",
            frames=(
                frame_with_blob("a", blob=(1, 1, 5, 7), color=(10, 20, 30)),
                frame_with_blob("b", blob=(8, 3, 4, 9), color=(40, 50, 60)),
            ),
        )
        before = color_multiset(frames.frames)
        result = align_frames(frames, AlignmentSpec(mode="feet"))
        self.assertEqual(color_multiset(result.frames.frames), before)

    def test_no_interpolation_only_exact_colours(self) -> None:
        frames = FrameSet(id="s", frames=(frame_with_blob("a", color=(200, 60, 80)),))
        result = align_frames(frames, AlignmentSpec(mode="center", padding=3))
        visible = result.frames.frames[0].image.array
        colours = {tuple(p) for p in visible[visible[:, :, 3] > 0].tolist()}
        self.assertEqual(colours, {(200, 60, 80, 255)})

    def test_transparent_pixels_stay_zeroed(self) -> None:
        frames = FrameSet(id="s", frames=(frame_with_blob("a"),))
        result = align_frames(frames, AlignmentSpec(mode="center", padding=2))
        self.assertFalse(result.frames.frames[0].image.has_hidden_color())

    def test_input_is_not_mutated(self) -> None:
        frames = FrameSet(id="s", frames=(frame_with_blob("a"),))
        before = frames.frames[0].image.array.copy()
        align_frames(frames, AlignmentSpec(mode="feet"))
        np.testing.assert_array_equal(frames.frames[0].image.array, before)


class Canvases(unittest.TestCase):
    def test_auto_canvas_fits_everything(self) -> None:
        frames = FrameSet(
            id="s",
            frames=(
                frame_with_blob("a", canvas=(16, 16), blob=(0, 0, 4, 4)),
                frame_with_blob("b", canvas=(16, 16), blob=(12, 12, 4, 4)),
            ),
        )
        result = align_frames(frames, AlignmentSpec(mode="center"))
        for placement in result.placements:
            self.assertGreaterEqual(placement.offset.x, 0)
            self.assertGreaterEqual(placement.offset.y, 0)
            self.assertLessEqual(placement.content.right, result.canvas.width)
            self.assertLessEqual(placement.content.bottom, result.canvas.height)

    def test_padding_grows_the_canvas_on_both_sides(self) -> None:
        frames = FrameSet(id="s", frames=(frame_with_blob("a"),))
        plain = align_frames(frames, AlignmentSpec(mode="center"))
        padded = align_frames(frames, AlignmentSpec(mode="center", padding=3))
        self.assertEqual(padded.canvas.width, plain.canvas.width + 6)
        self.assertEqual(padded.canvas.height, plain.canvas.height + 6)

    def test_fixed_canvas_is_honoured(self) -> None:
        frames = FrameSet(id="s", frames=(frame_with_blob("a"), frame_with_blob("b")))
        result = align_frames(frames, AlignmentSpec(mode="feet", canvas=Size(40, 40)))
        self.assertEqual(result.canvas.as_tuple(), (40, 40))
        for frame in result.frames.frames:
            self.assertEqual(frame.image.size.as_tuple(), (40, 40))

    def test_fixed_canvas_keeps_relative_alignment(self) -> None:
        frames = FrameSet(
            id="s",
            frames=(
                frame_with_blob("a", blob=(4, 2, 6, 10)),
                frame_with_blob("b", blob=(6, 6, 6, 6)),
            ),
        )
        result = align_frames(frames, AlignmentSpec(mode="feet", canvas=Size(48, 48)))
        bottoms = {bounds_in(f).bottom for f in result.frames.frames}
        self.assertEqual(len(bottoms), 1)

    def test_too_small_canvas_errors(self) -> None:
        frames = FrameSet(id="s", frames=(frame_with_blob("a"),))
        with self.assertRaises(UsageError):
            align_frames(frames, AlignmentSpec(mode="center", canvas=Size(4, 4)))

    def test_too_small_canvas_can_clip_with_a_warning(self) -> None:
        frames = FrameSet(id="s", frames=(frame_with_blob("a"),))
        result = align_frames(
            frames, AlignmentSpec(mode="center", canvas=Size(8, 8), overflow="clip")
        )
        self.assertEqual(result.canvas.as_tuple(), (8, 8))
        self.assertTrue(any(w.code == "align.clipped" for w in result.warnings))

    def test_trim_metadata_describes_the_new_canvas(self) -> None:
        frames = FrameSet(id="s", frames=(frame_with_blob("a"), frame_with_blob("b")))
        result = align_frames(frames, AlignmentSpec(mode="feet", padding=2))
        for frame, placement in zip(result.frames.frames, result.placements):
            self.assertEqual(frame.source_size, result.canvas)
            self.assertEqual(frame.trim_offset, placement.offset)
            self.assertEqual(frame.trim_rect.width, 16)


class EmptyFrames(unittest.TestCase):
    def test_empty_frame_errors_by_default(self) -> None:
        frames = FrameSet(id="s", frames=(frame_with_blob("a"), empty_frame("b")))
        with self.assertRaises(UsageError):
            align_frames(frames, AlignmentSpec(mode="feet"))

    def test_empty_frame_can_fall_back_to_canvas_center(self) -> None:
        frames = FrameSet(id="s", frames=(frame_with_blob("a"), empty_frame("b")))
        result = align_frames(frames, AlignmentSpec(mode="feet", empty="canvas_center"))
        self.assertTrue(any(w.code == "align.empty_frame" for w in result.warnings))

    def test_empty_frame_can_use_an_explicit_anchor(self) -> None:
        frames = FrameSet(id="s", frames=(frame_with_blob("a"), empty_frame("b")))
        result = align_frames(
            frames,
            AlignmentSpec(mode="feet", empty="fallback", fallback_anchor=Point(8, 12)),
        )
        self.assertEqual(
            result.placements[1].offset.as_tuple()[0], result.placements[1].offset.x
        )
        self.assertTrue(any(w.code == "align.empty_frame" for w in result.warnings))

    def test_fallback_without_an_anchor_is_rejected(self) -> None:
        with self.assertRaises(UsageError):
            AlignmentSpec(mode="feet", empty="fallback")


class Reporting(unittest.TestCase):
    def test_report_has_canvas_anchor_and_offsets(self) -> None:
        frames = FrameSet(id="s", frames=(frame_with_blob("a"), frame_with_blob("b")))
        payload = align_frames(frames, AlignmentSpec(mode="feet")).to_dict()
        self.assertEqual(len(payload["frames"]), 2)
        self.assertEqual(len(payload["canvas"]), 2)
        self.assertEqual(len(payload["anchor"]), 2)
        self.assertIn("offset", payload["frames"][0])

    def test_empty_frame_set_is_rejected(self) -> None:
        with self.assertRaises(UsageError):
            align_frames(FrameSet(id="s", frames=()), AlignmentSpec())

    def test_determinism(self) -> None:
        frames = FrameSet(
            id="s",
            frames=(frame_with_blob("a", blob=(2, 3, 5, 7)), frame_with_blob("b")),
        )
        spec = AlignmentSpec(mode="feet", padding=1)
        first = align_frames(frames, spec)
        second = align_frames(frames, spec)
        self.assertEqual(
            [p.offset.as_tuple() for p in first.placements],
            [p.offset.as_tuple() for p in second.placements],
        )
        np.testing.assert_array_equal(
            first.frames.frames[0].image.array, second.frames.frames[0].image.array
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
