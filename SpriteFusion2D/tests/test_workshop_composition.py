"""Composition: source-over maths, matching, missing policies, canvas rules."""

from __future__ import annotations

import unittest

import numpy as np

from sprite_workshop.composition import (
    CompositionSpec,
    LayerInput,
    compose_layers,
    composite_over,
)
from sprite_workshop.errors import UsageError
from sprite_workshop.model import Frame, FrameSet, Point, Rect, RgbaImage, Size


def make_frame(
    frame_id: str,
    *,
    canvas: tuple[int, int] = (8, 8),
    rect: tuple[int, int, int, int] = (0, 0, 8, 8),
    color: tuple[int, int, int, int] = (255, 0, 0, 255),
    anchor: tuple[int, int] | None = None,
    tags: dict[str, str] | None = None,
) -> Frame:
    width, height = canvas
    array = np.zeros((height, width, 4), np.uint8)
    x, y, w, h = rect
    array[y : y + h, x : x + w] = color
    image = RgbaImage(array)
    point = Point(*(anchor if anchor is not None else (width // 2, height)))
    return Frame(
        id=frame_id,
        image=image,
        source_size=image.size,
        trim_rect=Rect(0, 0, width, height),
        trim_offset=Point(0, 0),
        anchor=point,
        tags=tags or {},
    )


def layer(name: str, *frames: Frame) -> LayerInput:
    return LayerInput(name=name, frames=FrameSet(id=name, frames=frames))


class SourceOverMaths(unittest.TestCase):
    """Per-channel golden values; this is the load-bearing arithmetic."""

    def test_opaque_over_opaque_takes_the_top(self) -> None:
        base = np.array([[[10, 20, 30, 255]]], np.uint8)
        top = np.array([[[200, 100, 50, 255]]], np.uint8)
        np.testing.assert_array_equal(
            composite_over(base, top)[0, 0], [200, 100, 50, 255]
        )

    def test_transparent_top_leaves_the_base(self) -> None:
        base = np.array([[[10, 20, 30, 255]]], np.uint8)
        top = np.zeros((1, 1, 4), np.uint8)
        np.testing.assert_array_equal(
            composite_over(base, top)[0, 0], [10, 20, 30, 255]
        )

    def test_half_alpha_over_opaque(self) -> None:
        # a=128/255; out_rgb = 200*a + 0*(1-a) = 100.39 -> 100
        base = np.array([[[0, 0, 0, 255]]], np.uint8)
        top = np.array([[[200, 200, 200, 128]]], np.uint8)
        out = composite_over(base, top)[0, 0]
        self.assertEqual(int(out[3]), 255)
        self.assertEqual(int(out[0]), 100)

    def test_alpha_accumulates_over_transparent_base(self) -> None:
        base = np.zeros((1, 1, 4), np.uint8)
        top = np.array([[[10, 20, 30, 128]]], np.uint8)
        out = composite_over(base, top)[0, 0]
        self.assertEqual(int(out[3]), 128)
        # Colour survives unweighted when there is nothing underneath.
        np.testing.assert_array_equal(out[:3], [10, 20, 30])

    def test_two_half_alphas_stack(self) -> None:
        base = np.array([[[0, 0, 0, 128]]], np.uint8)
        top = np.array([[[255, 255, 255, 128]]], np.uint8)
        out = composite_over(base, top)[0, 0]
        # 0.502 + 0.502*0.498 = 0.752 -> 192
        self.assertEqual(int(out[3]), 192)

    def test_fully_transparent_result_has_zero_rgb(self) -> None:
        base = np.zeros((1, 1, 4), np.uint8)
        top = np.zeros((1, 1, 4), np.uint8)
        np.testing.assert_array_equal(composite_over(base, top)[0, 0], [0, 0, 0, 0])


class Stacking(unittest.TestCase):
    def test_later_layers_paint_on_top(self) -> None:
        body = layer("body", make_frame("f0", color=(255, 0, 0, 255)))
        cloth = layer("cloth", make_frame("f0", color=(0, 255, 0, 255)))
        result = compose_layers([body, cloth])
        np.testing.assert_array_equal(
            result.frames.frames[0].image.array[0, 0], [0, 255, 0, 255]
        )

    def test_partial_layer_only_covers_its_own_pixels(self) -> None:
        body = layer("body", make_frame("f0", color=(255, 0, 0, 255)))
        badge = layer(
            "badge", make_frame("f0", rect=(0, 0, 2, 2), color=(0, 0, 255, 255))
        )
        out = compose_layers([body, badge]).frames.frames[0].image.array
        np.testing.assert_array_equal(out[0, 0], [0, 0, 255, 255])
        np.testing.assert_array_equal(out[4, 4], [255, 0, 0, 255])

    def test_layers_register_on_their_anchors(self) -> None:
        body = layer("body", make_frame("f0", canvas=(8, 8), anchor=(4, 8)))
        # Same picture, anchor two pixels to the right: it must land two left.
        weapon = layer(
            "weapon",
            make_frame(
                "f0",
                canvas=(4, 4),
                rect=(0, 0, 4, 4),
                color=(0, 0, 255, 255),
                anchor=(6, 4),
            ),
        )
        result = compose_layers([body, weapon], CompositionSpec(overflow="clip"))
        self.assertEqual(result.anchor.as_tuple(), (6, 8))

    def test_input_frame_sets_are_not_mutated(self) -> None:
        body_frame = make_frame("f0", color=(255, 0, 0, 255))
        before = body_frame.image.array.copy()
        compose_layers([layer("body", body_frame), layer("cloth", make_frame("f0"))])
        np.testing.assert_array_equal(body_frame.image.array, before)

    def test_single_layer_is_a_passthrough(self) -> None:
        frame = make_frame("f0", color=(12, 34, 56, 255))
        result = compose_layers([layer("only", frame)])
        np.testing.assert_array_equal(
            result.frames.frames[0].image.array, frame.image.array
        )

    def test_duplicate_layer_names_are_rejected(self) -> None:
        with self.assertRaises(UsageError):
            compose_layers(
                [layer("body", make_frame("a")), layer("body", make_frame("b"))]
            )

    def test_no_layers_is_rejected(self) -> None:
        with self.assertRaises(UsageError):
            compose_layers([])

    def test_empty_layer_is_rejected(self) -> None:
        with self.assertRaises(UsageError):
            LayerInput(name="x", frames=FrameSet(id="x", frames=()))


class Matching(unittest.TestCase):
    def test_by_index(self) -> None:
        body = layer("body", make_frame("a0"), make_frame("a1"))
        cloth = layer("cloth", make_frame("b0"), make_frame("b1"))
        result = compose_layers([body, cloth], CompositionSpec(match="by_index"))
        self.assertEqual(result.matches[0][1].frame_id, "b0")
        self.assertEqual(result.matches[1][1].frame_id, "b1")

    def test_by_id(self) -> None:
        body = layer("body", make_frame("walk_00"), make_frame("walk_01"))
        cloth = layer("cloth", make_frame("walk_01"), make_frame("walk_00"))
        result = compose_layers([body, cloth], CompositionSpec(match="by_id"))
        self.assertEqual(result.matches[0][1].frame_id, "walk_00")
        self.assertEqual(result.matches[1][1].frame_id, "walk_01")

    def test_by_tag(self) -> None:
        body = layer(
            "body",
            make_frame("a", tags={"action": "walk", "direction": "south"}),
            make_frame("b", tags={"action": "walk", "direction": "north"}),
        )
        cloth = layer(
            "cloth",
            make_frame("n", tags={"action": "walk", "direction": "north"}),
            make_frame("s", tags={"action": "walk", "direction": "south"}),
        )
        result = compose_layers([body, cloth], CompositionSpec(match="by_tag"))
        self.assertEqual(result.matches[0][1].frame_id, "s")
        self.assertEqual(result.matches[1][1].frame_id, "n")

    def test_by_tag_with_explicit_keys(self) -> None:
        body = layer("body", make_frame("a", tags={"action": "walk", "variant": "x"}))
        cloth = layer("cloth", make_frame("c", tags={"action": "walk", "variant": "y"}))
        result = compose_layers(
            [body, cloth], CompositionSpec(match="by_tag", match_keys=("action",))
        )
        self.assertEqual(result.matches[0][1].frame_id, "c")

    def test_ambiguous_tag_match_is_rejected(self) -> None:
        body = layer("body", make_frame("a", tags={"action": "walk"}))
        cloth = layer(
            "cloth",
            make_frame("c1", tags={"action": "walk"}),
            make_frame("c2", tags={"action": "walk"}),
        )
        with self.assertRaises(UsageError):
            compose_layers([body, cloth], CompositionSpec(match="by_tag"))

    def test_by_tag_without_tags_is_rejected(self) -> None:
        body = layer("body", make_frame("a"), make_frame("b"))
        cloth = layer("cloth", make_frame("c"), make_frame("d"))
        with self.assertRaises(UsageError):
            compose_layers([body, cloth], CompositionSpec(match="by_tag"))

    def test_broadcast_repeats_one_frame(self) -> None:
        body = layer("body", make_frame("a"), make_frame("b"), make_frame("c"))
        fx = layer("fx", make_frame("glow"))
        result = compose_layers([body, fx], CompositionSpec(match="broadcast"))
        self.assertEqual([m[1].frame_id for m in result.matches], ["glow"] * 3)

    def test_single_frame_layer_broadcasts_even_by_index(self) -> None:
        body = layer("body", make_frame("a"), make_frame("b"))
        fx = layer("fx", make_frame("glow"))
        result = compose_layers([body, fx], CompositionSpec(match="by_index"))
        self.assertEqual([m[1].frame_id for m in result.matches], ["glow"] * 2)


class MissingPolicies(unittest.TestCase):
    def _layers(self):
        body = layer("body", make_frame("a"), make_frame("b"), make_frame("c"))
        short = layer("cloth", make_frame("x"), make_frame("y"))
        return body, short

    def test_error_is_the_default(self) -> None:
        body, short = self._layers()
        with self.assertRaises(UsageError):
            compose_layers([body, short], CompositionSpec(match="by_index"))

    def test_skip_layer(self) -> None:
        body, short = self._layers()
        result = compose_layers(
            [body, short], CompositionSpec(match="by_index", missing="skip_layer")
        )
        self.assertIsNone(result.matches[2][1].frame_id)
        self.assertTrue(any(w.code == "compose.layer_skipped" for w in result.warnings))

    def test_hold_last(self) -> None:
        body, short = self._layers()
        result = compose_layers(
            [body, short], CompositionSpec(match="by_index", missing="hold_last")
        )
        self.assertEqual(result.matches[2][1].frame_id, "y")
        self.assertTrue(result.matches[2][1].held)

    def test_hold_last_with_nothing_seen_yet_skips(self) -> None:
        body = layer("body", make_frame("a"), make_frame("b"))
        cloth = layer("cloth", make_frame("nope"), make_frame("also_nope"))
        result = compose_layers(
            [body, cloth],
            CompositionSpec(match="by_id", missing="hold_last"),
        )
        self.assertIsNone(result.matches[0][1].frame_id)

    def test_broadcast_single_can_be_turned_off(self) -> None:
        """Auto-broadcast overrides the requested match mode, so it is a flag."""

        body = layer("body", make_frame("a"), make_frame("b"))
        prop = layer("prop", make_frame("rifle"))

        on = compose_layers([body, prop], CompositionSpec(match="by_id"))
        self.assertEqual([m[1].frame_id for m in on.matches], ["rifle", "rifle"])

        off = compose_layers(
            [body, prop],
            CompositionSpec(
                match="by_id", broadcast_single=False, missing="skip_layer"
            ),
        )
        self.assertEqual([m[1].frame_id for m in off.matches], [None, None])


class CanvasRules(unittest.TestCase):
    def test_union_covers_every_layer(self) -> None:
        body = layer("body", make_frame("f0", canvas=(8, 8), anchor=(4, 8)))
        cape = layer(
            "cape",
            make_frame("f0", canvas=(16, 16), anchor=(8, 16), color=(0, 0, 255, 255)),
        )
        result = compose_layers([body, cape])
        self.assertEqual(result.canvas.as_tuple(), (16, 16))

    def test_union_is_stable_across_different_second_layers(self) -> None:
        """Same body with different clothes must not change canvas size."""

        body = make_frame("f0", canvas=(8, 8), anchor=(4, 8))
        a = compose_layers(
            [
                layer("body", body),
                layer("c", make_frame("f0", canvas=(8, 8), anchor=(4, 8))),
            ]
        )
        b = compose_layers(
            [
                layer("body", body),
                layer(
                    "c",
                    make_frame(
                        "f0", canvas=(8, 8), anchor=(4, 8), color=(0, 255, 0, 255)
                    ),
                ),
            ]
        )
        self.assertEqual(a.canvas.as_tuple(), b.canvas.as_tuple())
        self.assertEqual(a.anchor.as_tuple(), b.anchor.as_tuple())

    def test_padding_grows_the_union(self) -> None:
        body = layer("body", make_frame("f0", canvas=(8, 8), anchor=(4, 8)))
        plain = compose_layers([body])
        padded = compose_layers([body], CompositionSpec(padding=2))
        self.assertEqual(padded.canvas.width, plain.canvas.width + 4)

    def test_fixed_canvas(self) -> None:
        body = layer("body", make_frame("f0", canvas=(8, 8), anchor=(4, 8)))
        result = compose_layers(
            [body], CompositionSpec(canvas="fixed", canvas_size=Size(32, 32))
        )
        self.assertEqual(result.canvas.as_tuple(), (32, 32))
        self.assertEqual(result.frames.frames[0].image.size.as_tuple(), (32, 32))

    def test_fixed_canvas_needs_a_size(self) -> None:
        with self.assertRaises(UsageError):
            CompositionSpec(canvas="fixed")

    def test_from_layer_canvas(self) -> None:
        body = layer("body", make_frame("f0", canvas=(8, 8), anchor=(4, 8)))
        cape = layer("cape", make_frame("f0", canvas=(16, 16), anchor=(8, 16)))
        result = compose_layers(
            [body, cape],
            CompositionSpec(canvas="from_layer", canvas_layer="body", overflow="clip"),
        )
        self.assertEqual(result.canvas.as_tuple(), (8, 8))

    def test_from_layer_with_an_unknown_name(self) -> None:
        body = layer("body", make_frame("f0"))
        with self.assertRaises(UsageError):
            compose_layers(
                [body], CompositionSpec(canvas="from_layer", canvas_layer="nope")
            )

    def test_overflow_error_is_the_default(self) -> None:
        body = layer("body", make_frame("f0", canvas=(8, 8), anchor=(4, 8)))
        big = layer("big", make_frame("f0", canvas=(16, 16), anchor=(8, 16)))
        with self.assertRaises(UsageError):
            compose_layers(
                [body, big],
                CompositionSpec(canvas="from_layer", canvas_layer="body"),
            )


class Reporting(unittest.TestCase):
    def test_report_records_every_layer_contribution(self) -> None:
        body = layer("body", make_frame("a"), make_frame("b"))
        cloth = layer("cloth", make_frame("a"), make_frame("b"))
        payload = compose_layers(
            [body, cloth], CompositionSpec(match="by_id")
        ).to_dict()
        self.assertEqual(len(payload["frames"]), 2)
        self.assertEqual(
            [entry["layer"] for entry in payload["frames"][0]["layers"]],
            ["body", "cloth"],
        )

    def test_output_keeps_base_ids_and_tags(self) -> None:
        body = layer("body", make_frame("walk_00", tags={"action": "walk"}))
        cloth = layer("cloth", make_frame("walk_00", tags={"action": "walk"}))
        result = compose_layers([body, cloth], CompositionSpec(match="by_id"))
        frame = result.frames.frames[0]
        self.assertEqual(frame.id, "walk_00")
        self.assertEqual(dict(frame.tags), {"action": "walk"})

    def test_determinism(self) -> None:
        body = layer("body", make_frame("a", color=(3, 5, 7, 200)))
        cloth = layer("cloth", make_frame("a", color=(9, 11, 13, 150)))
        first = compose_layers([body, cloth])
        second = compose_layers([body, cloth])
        np.testing.assert_array_equal(
            first.frames.frames[0].image.array, second.frames.frames[0].image.array
        )

    def test_transparent_output_pixels_are_normalised(self) -> None:
        sparse = make_frame("a", rect=(0, 0, 2, 2))
        result = compose_layers([layer("body", sparse)], CompositionSpec(padding=2))
        self.assertFalse(result.frames.frames[0].image.has_hidden_color())


class Wardrobe(unittest.TestCase):
    """The actual goal: one body, several outfits, consistent output."""

    def test_body_plus_two_outfits(self) -> None:
        body_frames = [
            make_frame(
                f"walk_{i:02d}", canvas=(8, 8), anchor=(4, 8), tags={"action": "walk"}
            )
            for i in range(4)
        ]
        outfits = {
            "miko": (200, 40, 60, 255),
            "sailor": (40, 60, 200, 255),
        }

        canvases = set()
        for name, colour in outfits.items():
            cloth = layer(
                "cloth",
                *[
                    make_frame(
                        f"walk_{i:02d}",
                        canvas=(8, 8),
                        rect=(2, 2, 4, 4),
                        color=colour,
                        anchor=(4, 8),
                    )
                    for i in range(4)
                ],
            )
            result = compose_layers(
                [layer("body", *body_frames), cloth],
                CompositionSpec(match="by_id"),
                set_id=f"chouko_{name}",
            )
            self.assertEqual(len(result.frames), 4)
            self.assertEqual(result.frames.id, f"chouko_{name}")
            np.testing.assert_array_equal(
                result.frames.frames[0].image.array[3, 3], list(colour)
            )
            canvases.add(result.canvas.as_tuple())

        self.assertEqual(len(canvases), 1, "every outfit must yield the same canvas")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
