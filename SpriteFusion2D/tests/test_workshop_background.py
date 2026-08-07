"""Background removal: the interior-colour case, modes, cleanup, masks."""

from __future__ import annotations

import unittest

import numpy as np

from sprite_workshop.background import (
    BackgroundSpec,
    analyze_background,
    apply_mask,
    color_distance,
    remove_background,
)
from sprite_workshop.errors import BackendUnavailableError, UsageError
from sprite_workshop.model import Frame, FrameSet, Point, Rect, RgbaImage

GREEN = (39, 154, 63)
SKIN = (255, 227, 203)
ROBE = (154, 48, 74)


def frame_from(
    rgb: np.ndarray, frame_id: str = "f0", alpha: np.ndarray | None = None
) -> Frame:
    height, width = rgb.shape[:2]
    rgba = np.dstack(
        [rgb, np.full((height, width), 255, np.uint8) if alpha is None else alpha]
    )
    image = RgbaImage(rgba.astype(np.uint8))
    return Frame(
        id=frame_id,
        image=image,
        source_size=image.size,
        trim_rect=Rect(0, 0, width, height),
        trim_offset=Point(0, 0),
        anchor=Point(width // 2, height),
    )


def character_on_green(width: int = 16, height: int = 16) -> np.ndarray:
    """A blob on a green field, with a green pixel *inside* the blob."""

    rgb = np.zeros((height, width, 3), np.uint8)
    rgb[:, :] = GREEN
    rgb[4:12, 4:12] = ROBE
    rgb[6:9, 6:9] = SKIN
    rgb[7, 7] = GREEN  # the interior pixel that must survive
    return rgb


class ColourDistance(unittest.TestCase):
    def test_exact_is_binary(self) -> None:
        pixels = np.array([[GREEN, SKIN]], np.uint8)
        d = color_distance(pixels, np.array(GREEN, np.uint8), "exact")
        self.assertEqual(d[0, 0], 0.0)
        self.assertGreater(d[0, 1], 1e6)

    def test_rgb_distance_is_zero_for_identical(self) -> None:
        pixels = np.array([[GREEN]], np.uint8)
        self.assertAlmostEqual(
            color_distance(pixels, np.array(GREEN, np.uint8), "rgb")[0, 0], 0.0
        )

    def test_lab_distance_is_zero_for_identical(self) -> None:
        pixels = np.array([[SKIN]], np.uint8)
        self.assertAlmostEqual(
            color_distance(pixels, np.array(SKIN, np.uint8), "lab")[0, 0], 0.0
        )

    def test_lab_ranks_perceptual_closeness(self) -> None:
        near = (44, 160, 68)
        far = (200, 60, 60)
        reference = np.array(GREEN, np.uint8)
        pixels = np.array([[near, far]], np.uint8)
        d = color_distance(pixels, reference, "lab")
        self.assertLess(d[0, 0], d[0, 1])

    def test_rembg_missing_reports_backend_unavailable(self) -> None:
        with self.assertRaises(BackendUnavailableError) as ctx:
            color_distance(
                np.zeros((1, 1, 3), np.uint8), np.zeros(3, np.uint8), "rembg"
            )
        self.assertEqual(ctx.exception.code, 5)


class InteriorColourSurvives(unittest.TestCase):
    """The single most important behaviour in this module."""

    def setUp(self) -> None:
        self.frames = FrameSet(id="hero", frames=(frame_from(character_on_green()),))

    def test_border_background_removed_interior_kept(self) -> None:
        result = remove_background(
            self.frames, BackgroundSpec(mode="exact", tolerance=0)
        )
        alpha = result.frames.frames[0].image.array[:, :, 3]
        self.assertEqual(int(alpha[0, 0]), 0, "corner background should be erased")
        self.assertEqual(int(alpha[7, 7]), 255, "interior green must survive")
        self.assertEqual(int(alpha[5, 5]), 255, "robe must survive")

    def test_disabling_border_only_eats_the_interior(self) -> None:
        """Documents exactly what border connectivity buys."""

        result = remove_background(
            self.frames, BackgroundSpec(mode="exact", tolerance=0, border_only=False)
        )
        alpha = result.frames.frames[0].image.array[:, :, 3]
        self.assertEqual(int(alpha[7, 7]), 0)


class Modes(unittest.TestCase):
    def setUp(self) -> None:
        self.frames = FrameSet(id="hero", frames=(frame_from(character_on_green()),))

    def test_exact_ignores_near_colours(self) -> None:
        rgb = character_on_green()
        rgb[0, 5] = (41, 156, 65)  # almost the background
        frames = FrameSet(id="h", frames=(frame_from(rgb),))

        exact = remove_background(frames, BackgroundSpec(mode="exact", tolerance=0))
        self.assertEqual(int(exact.frames.frames[0].image.array[0, 5, 3]), 255)

        lab = remove_background(frames, BackgroundSpec(mode="lab", tolerance=5))
        self.assertEqual(int(lab.frames.frames[0].image.array[0, 5, 3]), 0)

    def test_zero_tolerance_lab_matches_exact(self) -> None:
        a = remove_background(self.frames, BackgroundSpec(mode="exact", tolerance=0))
        b = remove_background(self.frames, BackgroundSpec(mode="lab", tolerance=0))
        np.testing.assert_array_equal(
            a.frames.frames[0].image.array, b.frames.frames[0].image.array
        )

    def test_rgb_mode_runs(self) -> None:
        result = remove_background(self.frames, BackgroundSpec(mode="rgb", tolerance=8))
        self.assertEqual(int(result.frames.frames[0].image.array[0, 0, 3]), 0)


class AlphaAndHygiene(unittest.TestCase):
    def setUp(self) -> None:
        self.frames = FrameSet(id="hero", frames=(frame_from(character_on_green()),))

    def test_hard_alpha_is_only_zero_or_255(self) -> None:
        result = remove_background(
            self.frames, BackgroundSpec(mode="lab", tolerance=10)
        )
        alpha = result.frames.frames[0].image.array[:, :, 3]
        self.assertEqual(set(np.unique(alpha).tolist()) - {0, 255}, set())

    def test_soft_alpha_produces_intermediate_values(self) -> None:
        """Soft alpha only has anything to do when the source is anti-aliased.

        Flat pixel art has no colours between background and character, which
        is exactly why hard alpha is the default.
        """

        rgb = character_on_green()
        # A quarter-blend edge pixel: Lab distance ~22 from the background.
        rgb[3, 5] = (67, 127, 65)
        frames = FrameSet(id="h", frames=(frame_from(rgb),))

        hard = remove_background(frames, BackgroundSpec(mode="lab", tolerance=6))
        hard_alpha = hard.frames.frames[0].image.array[:, :, 3]
        self.assertEqual(set(np.unique(hard_alpha).tolist()) - {0, 255}, set())

        soft = remove_background(
            frames,
            BackgroundSpec(mode="lab", tolerance=6, alpha="soft", soft_range=30),
        )
        alpha = soft.frames.frames[0].image.array[:, :, 3]
        self.assertTrue(
            0 < int(alpha[3, 5]) < 255, f"edge pixel alpha was {int(alpha[3, 5])}"
        )
        self.assertEqual(int(alpha[0, 0]), 0, "pure background is still fully erased")
        self.assertEqual(int(alpha[5, 5]), 255, "the character is still opaque")

    def test_transparent_pixels_have_zero_rgb(self) -> None:
        result = remove_background(
            self.frames, BackgroundSpec(mode="lab", tolerance=10)
        )
        self.assertFalse(result.frames.frames[0].image.has_hidden_color())

    def test_existing_transparency_is_never_undone(self) -> None:
        rgb = character_on_green()
        alpha = np.full(rgb.shape[:2], 255, np.uint8)
        alpha[5, 5] = 0  # already transparent, inside the character
        frames = FrameSet(id="h", frames=(frame_from(rgb, alpha=alpha),))
        result = remove_background(frames, BackgroundSpec(mode="exact", tolerance=0))
        self.assertEqual(int(result.frames.frames[0].image.array[5, 5, 3]), 0)

    def test_input_frames_are_not_mutated(self) -> None:
        before = self.frames.frames[0].image.array.copy()
        remove_background(self.frames, BackgroundSpec(mode="lab", tolerance=10))
        np.testing.assert_array_equal(self.frames.frames[0].image.array, before)


class Cleanup(unittest.TestCase):
    def test_min_island_area_drops_small_background_specks(self) -> None:
        rgb = np.zeros((12, 12, 3), np.uint8)
        rgb[:, :] = ROBE
        rgb[0, 0] = GREEN  # a single-pixel background speck on the border
        rgb[0, 5:11] = GREEN  # a larger real background run
        frames = FrameSet(id="h", frames=(frame_from(rgb),))
        # Explicit colour: corner sampling would pick ROBE on this fixture,
        # which is not what this test is about.
        base = dict(
            mode="exact", tolerance=0, samples="colors", colors=(GREEN,), connectivity=4
        )

        kept = remove_background(frames, BackgroundSpec(**base))
        self.assertEqual(int(kept.frames.frames[0].image.array[0, 0, 3]), 0)

        filtered = remove_background(frames, BackgroundSpec(**base, min_island_area=3))
        self.assertEqual(int(filtered.frames.frames[0].image.array[0, 0, 3]), 255)
        self.assertEqual(int(filtered.frames.frames[0].image.array[0, 6, 3]), 0)

    def test_max_hole_area_fills_enclosed_foreground_specks(self) -> None:
        """max_hole_area targets foreground regions fully enclosed by background."""

        rgb = np.zeros((16, 16, 3), np.uint8)
        rgb[:, :] = GREEN
        rgb[6:11, 6:11] = ROBE  # the character
        rgb[2, 2] = ROBE  # a stray speck floating in the background
        frames = FrameSet(id="h", frames=(frame_from(rgb),))
        base = dict(mode="exact", tolerance=0, connectivity=4)

        kept = remove_background(frames, BackgroundSpec(**base))
        self.assertEqual(int(kept.frames.frames[0].image.array[2, 2, 3]), 255)

        filled = remove_background(frames, BackgroundSpec(**base, max_hole_area=1))
        self.assertEqual(int(filled.frames.frames[0].image.array[2, 2, 3]), 0)
        self.assertEqual(
            int(filled.frames.frames[0].image.array[8, 8, 3]),
            255,
            "the character stays",
        )


class Masks(unittest.TestCase):
    def setUp(self) -> None:
        self.frames = FrameSet(id="hero", frames=(frame_from(character_on_green()),))

    def test_mask_is_a_normal_frame_set(self) -> None:
        result = remove_background(
            self.frames, BackgroundSpec(mode="exact", tolerance=0)
        )
        mask = result.masks.frames[0]
        self.assertEqual(mask.id, "f0_mask")
        self.assertEqual(mask.image.size, self.frames.frames[0].image.size)
        # Mask alpha is the shape you keep.
        self.assertEqual(int(mask.image.array[7, 7, 3]), 255)
        self.assertEqual(int(mask.image.array[0, 0, 3]), 0)

    def test_mask_round_trip_reproduces_removal(self) -> None:
        result = remove_background(
            self.frames, BackgroundSpec(mode="exact", tolerance=0)
        )
        reapplied = apply_mask(self.frames, result.masks)
        np.testing.assert_array_equal(
            reapplied.frames[0].image.array, result.frames.frames[0].image.array
        )

    def test_mask_can_be_inverted(self) -> None:
        result = remove_background(
            self.frames, BackgroundSpec(mode="exact", tolerance=0)
        )
        inverted = apply_mask(self.frames, result.masks, invert=True)
        self.assertEqual(int(inverted.frames[0].image.array[0, 0, 3]), 255)
        self.assertEqual(int(inverted.frames[0].image.array[5, 5, 3]), 0)

    def test_single_mask_broadcasts_to_many_frames(self) -> None:
        rgb = character_on_green()
        many = FrameSet(id="h", frames=(frame_from(rgb, "a"), frame_from(rgb, "b")))
        result = remove_background(
            self.frames, BackgroundSpec(mode="exact", tolerance=0)
        )
        applied = apply_mask(many, result.masks)
        self.assertEqual(len(applied), 2)

    def test_size_mismatch_is_rejected(self) -> None:
        other = FrameSet(id="m", frames=(frame_from(np.zeros((4, 4, 3), np.uint8)),))
        with self.assertRaises(UsageError):
            apply_mask(self.frames, other)

    def test_count_mismatch_is_rejected(self) -> None:
        rgb = character_on_green()
        masks = FrameSet(id="m", frames=(frame_from(rgb, "a"), frame_from(rgb, "b")))
        three = FrameSet(
            id="h",
            frames=(frame_from(rgb, "x"), frame_from(rgb, "y"), frame_from(rgb, "z")),
        )
        with self.assertRaises(UsageError):
            apply_mask(three, masks)


class SharedBackground(unittest.TestCase):
    def test_shared_sampling_keeps_frames_consistent(self) -> None:
        """Per-frame sampling is what makes an animation flicker."""

        a = character_on_green()
        b = character_on_green()
        b[0, 0] = (60, 170, 80)  # one frame's corner drifted
        frames = FrameSet(id="h", frames=(frame_from(a, "a"), frame_from(b, "b")))

        shared = remove_background(
            frames, BackgroundSpec(mode="lab", tolerance=4, shared_background=True)
        )
        chosen = shared.analysis.chosen
        self.assertIsNotNone(chosen)
        self.assertEqual(shared.warnings, ())

        per_frame = remove_background(
            frames, BackgroundSpec(mode="lab", tolerance=4, shared_background=False)
        )
        self.assertTrue(
            any(w.code == "background.per_frame_samples" for w in per_frame.warnings)
        )

    def test_determinism(self) -> None:
        frames = FrameSet(id="h", frames=(frame_from(character_on_green()),))
        spec = BackgroundSpec(mode="lab", tolerance=10)
        first = remove_background(frames, spec).frames.frames[0].image.array
        second = remove_background(frames, spec).frames.frames[0].image.array
        np.testing.assert_array_equal(first, second)


class Analysis(unittest.TestCase):
    def setUp(self) -> None:
        self.frames = FrameSet(id="hero", frames=(frame_from(character_on_green()),))

    def test_analyze_suggests_the_background_colour(self) -> None:
        analysis = analyze_background(
            self.frames, BackgroundSpec(mode="lab", tolerance=6)
        )
        self.assertEqual(analysis.chosen.color, GREEN)
        self.assertGreater(analysis.erased_pixels, 0)
        self.assertLess(analysis.erased_pixels, analysis.total_pixels)

    def test_analyze_reports_corner_colours(self) -> None:
        analysis = analyze_background(self.frames, BackgroundSpec())
        self.assertEqual(len(analysis.corner_colors), 4)
        self.assertTrue(all(c == GREEN for c in analysis.corner_colors))

    def test_analyze_is_serialisable(self) -> None:
        payload = analyze_background(self.frames, BackgroundSpec()).to_dict()
        self.assertIn("erased_ratio", payload)
        self.assertTrue(payload["chosen"]["color"].startswith("#"))

    def test_border_sampling_beats_a_stray_corner(self) -> None:
        rgb = character_on_green()
        rgb[0, 0] = ROBE  # one corner is not background at all
        frames = FrameSet(id="h", frames=(frame_from(rgb),))
        analysis = analyze_background(
            frames, BackgroundSpec(samples="border", mode="lab")
        )
        self.assertEqual(analysis.chosen.color, GREEN)

    def test_explicit_colour_overrides_sampling(self) -> None:
        frames = FrameSet(id="h", frames=(frame_from(character_on_green()),))
        result = remove_background(
            frames,
            BackgroundSpec(mode="exact", tolerance=0, samples="colors", colors=(ROBE,)),
        )
        alpha = result.frames.frames[0].image.array[:, :, 3]
        self.assertEqual(int(alpha[0, 0]), 255, "green is no longer the target")

    def test_explicit_point_samples_that_pixel(self) -> None:
        frames = FrameSet(id="h", frames=(frame_from(character_on_green()),))
        result = remove_background(
            frames,
            BackgroundSpec(
                mode="exact", tolerance=0, samples="colors", points=((0, 0),)
            ),
        )
        self.assertEqual(int(result.frames.frames[0].image.array[0, 0, 3]), 0)


class SpecValidation(unittest.TestCase):
    def test_rejects_unknown_mode(self) -> None:
        with self.assertRaises(UsageError):
            BackgroundSpec(mode="magic")  # type: ignore[arg-type]

    def test_rejects_negative_tolerance(self) -> None:
        with self.assertRaises(UsageError):
            BackgroundSpec(tolerance=-1)

    def test_rejects_bad_connectivity(self) -> None:
        with self.assertRaises(UsageError):
            BackgroundSpec(connectivity=6)

    def test_rejects_palette_despill_until_the_module_exists(self) -> None:
        with self.assertRaises(UsageError):
            BackgroundSpec(despill="palette")  # type: ignore[arg-type]

    def test_despill_with_hard_alpha_is_rejected_rather_than_ignored(self) -> None:
        with self.assertRaises(UsageError):
            BackgroundSpec(despill="nearest", alpha="hard")
        # It is fine once there are partial pixels to work on.
        BackgroundSpec(despill="nearest", alpha="soft")

    def test_despill_runs_under_soft_alpha(self) -> None:
        rgb = character_on_green()
        rgb[3, 5] = (67, 127, 65)  # anti-aliased edge pixel
        frames = FrameSet(id="h", frames=(frame_from(rgb),))

        plain = remove_background(
            frames, BackgroundSpec(mode="lab", tolerance=6, alpha="soft", soft_range=30)
        )
        despilled = remove_background(
            frames,
            BackgroundSpec(
                mode="lab", tolerance=6, alpha="soft", soft_range=30, despill="nearest"
            ),
        )
        # Same coverage, different edge colour: despill only rewrites RGB.
        np.testing.assert_array_equal(
            plain.frames.frames[0].image.array[:, :, 3],
            despilled.frames.frames[0].image.array[:, :, 3],
        )
        self.assertNotEqual(
            tuple(plain.frames.frames[0].image.array[3, 5, :3].tolist()),
            tuple(despilled.frames.frames[0].image.array[3, 5, :3].tolist()),
        )

    def test_colors_source_needs_a_colour(self) -> None:
        with self.assertRaises(UsageError):
            BackgroundSpec(samples="colors")

    def test_empty_frame_set_is_rejected(self) -> None:
        with self.assertRaises(UsageError):
            remove_background(FrameSet(id="empty", frames=()), BackgroundSpec())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
