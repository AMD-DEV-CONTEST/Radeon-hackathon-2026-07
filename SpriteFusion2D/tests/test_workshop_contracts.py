"""Stage 0 contracts: image/coordinate invariants, frame ids, tags, schema."""

from __future__ import annotations

import unittest

import numpy as np

from sprite_workshop.errors import UsageError
from sprite_workshop.ids import (
    DEFAULT_NAME_TEMPLATE,
    normalize_tags,
    render_name,
    render_names,
    select_frames,
    tags_from_id,
    validate_id,
)
from sprite_workshop.model import Frame, FrameSet, Point, Rect, RgbaImage, Size


def make_image(width: int = 4, height: int = 3, fill: int = 255) -> RgbaImage:
    array = np.zeros((height, width, 4), dtype=np.uint8)
    array[:, :, 3] = fill
    return RgbaImage(array)


def make_frame(frame_id: str, **tags: str) -> Frame:
    image = make_image()
    return Frame(
        id=frame_id,
        image=image,
        source_size=image.size,
        trim_rect=Rect(0, 0, image.width, image.height),
        trim_offset=Point(0, 0),
        anchor=Point(image.width // 2, image.height),
        tags=dict(tags),
    )


class RgbaImageContract(unittest.TestCase):
    def test_rejects_wrong_shape(self) -> None:
        with self.assertRaises(UsageError):
            RgbaImage(np.zeros((3, 4, 3), dtype=np.uint8))

    def test_rejects_wrong_dtype(self) -> None:
        with self.assertRaises(UsageError):
            RgbaImage(np.zeros((3, 4, 4), dtype=np.float32))

    def test_array_is_not_writeable(self) -> None:
        image = make_image()
        self.assertFalse(image.array.flags.writeable)
        with self.assertRaises(ValueError):
            image.array[0, 0, 0] = 1

    def test_does_not_alias_caller_buffer(self) -> None:
        source = np.zeros((2, 2, 4), dtype=np.uint8)
        image = RgbaImage(source)
        source[0, 0] = 255
        self.assertEqual(int(image.array[0, 0, 0]), 0)

    def test_normalized_zeroes_transparent_rgb(self) -> None:
        array = np.zeros((2, 2, 4), dtype=np.uint8)
        array[:, :, :3] = 200
        array[0, 0, 3] = 0
        array[0, 1, 3] = 255
        image = RgbaImage(array)
        self.assertTrue(image.has_hidden_color())

        normalized = image.normalized()
        self.assertFalse(normalized.has_hidden_color())
        self.assertEqual(list(normalized.array[0, 0]), [0, 0, 0, 0])
        # Opaque pixels are untouched.
        self.assertEqual(list(normalized.array[0, 1]), [200, 200, 200, 255])


class RectContract(unittest.TestCase):
    def test_rect_is_half_open(self) -> None:
        rect = Rect(2, 3, 4, 5)
        self.assertEqual(rect.right, 6)
        self.assertEqual(rect.bottom, 8)

    def test_containment_uses_exclusive_edges(self) -> None:
        outer = Rect(0, 0, 10, 10)
        self.assertTrue(outer.contains_rect(Rect(0, 0, 10, 10)))
        self.assertFalse(outer.contains_rect(Rect(0, 0, 11, 10)))

    def test_negative_size_rejected(self) -> None:
        with self.assertRaises(UsageError):
            Rect(0, 0, -1, 4)
        with self.assertRaises(UsageError):
            Size(-1, 2)


class FrameIdContract(unittest.TestCase):
    def test_valid_and_invalid_ids(self) -> None:
        self.assertEqual(validate_id("walk_s_00"), "walk_s_00")
        for bad in ("Walk", "walk-00", "walk 00", "蝶子", ""):
            with self.assertRaises(UsageError, msg=bad):
                validate_id(bad)

    def test_default_template(self) -> None:
        self.assertEqual(
            render_name(DEFAULT_NAME_TEMPLATE, frame_set="hero", index=7), "hero_07"
        )

    def test_grid_placeholders(self) -> None:
        name = render_name(
            "{set}_r{row}c{col}", frame_set="hero", index=0, row=1, col=2
        )
        self.assertEqual(name, "hero_r1c2")

    def test_tag_placeholder(self) -> None:
        name = render_name(
            "{tag:action}_{tag:direction}_{index:02d}",
            frame_set="hero",
            index=3,
            tags={"action": "walk", "direction": "south"},
        )
        self.assertEqual(name, "walk_south_03")

    def test_missing_placeholder_is_a_usage_error(self) -> None:
        with self.assertRaises(UsageError):
            render_name("{set}_{row}", frame_set="hero", index=0)

    def test_missing_tag_is_a_usage_error(self) -> None:
        with self.assertRaises(UsageError):
            render_name("{tag:action}", frame_set="hero", index=0, tags={})

    def test_collisions_are_deduped_with_a_warning(self) -> None:
        ids, warnings = render_names(
            "{set}_{tag:action}",
            frame_set="hero",
            count=3,
            tags=[{"action": "walk"}] * 3,
        )
        self.assertEqual(ids, ["hero_walk", "hero_walk_2", "hero_walk_3"])
        self.assertEqual(len(warnings), 2)

    def test_tags_from_id(self) -> None:
        frame = make_frame("walk_south_00")
        self.assertEqual(
            tags_from_id(frame, "{action}_{direction}_{index}"),
            {"action": "walk", "direction": "south"},
        )


class TagContract(unittest.TestCase):
    def test_normalize_rejects_bad_keys_and_values(self) -> None:
        self.assertEqual(normalize_tags({"action": "walk"}), {"action": "walk"})
        with self.assertRaises(UsageError):
            normalize_tags({"Action": "walk"})
        with self.assertRaises(UsageError):
            normalize_tags({"action": "Walk"})


class SelectorContract(unittest.TestCase):
    def setUp(self) -> None:
        self.frame_set = FrameSet(
            id="hero",
            frames=(
                make_frame("a0", action="walk", direction="south"),
                make_frame("a1", action="walk", direction="north"),
                make_frame("a2", action="idle", direction="south"),
            ),
        )

    def test_all(self) -> None:
        self.assertEqual(select_frames(self.frame_set, "all"), (0, 1, 2))
        self.assertEqual(select_frames(self.frame_set, None), (0, 1, 2))

    def test_ids(self) -> None:
        self.assertEqual(select_frames(self.frame_set, "id:a2,a0"), (0, 2))

    def test_index_range(self) -> None:
        self.assertEqual(select_frames(self.frame_set, "index:0-1"), (0, 1))
        self.assertEqual(select_frames(self.frame_set, "index:0,2"), (0, 2))
        with self.assertRaises(UsageError):
            select_frames(self.frame_set, "index:5")

    def test_tag_key_value(self) -> None:
        self.assertEqual(select_frames(self.frame_set, "tag:action=walk"), (0, 1))
        self.assertEqual(select_frames(self.frame_set, "tag:direction=south"), (0, 2))

    def test_tag_shorthand(self) -> None:
        self.assertEqual(select_frames(self.frame_set, "tag:idle"), (2,))

    def test_ambiguous_shorthand_errors_instead_of_guessing(self) -> None:
        ambiguous = FrameSet(
            id="x",
            frames=(make_frame("f0", action="walk", variant="walk"),),
        )
        with self.assertRaises(UsageError):
            select_frames(ambiguous, "tag:walk")

    def test_unknown_selector(self) -> None:
        with self.assertRaises(UsageError):
            select_frames(self.frame_set, "nope:1")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
