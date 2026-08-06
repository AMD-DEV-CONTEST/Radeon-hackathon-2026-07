from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from PIL import Image, ImageChops

from prooflaunch_remix.files import sha256_file
from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_image_mastering import (
    BrandConstraint,
    CompositionConstraint,
    FontConstraint,
    ImageCandidate,
    ImageDirectionSpec,
    ImageRewardDimension,
    LightingConstraint,
    LocalRepairRequest,
    LoraTrainingPolicy,
    MaterialConstraint,
    NegativeSpaceConstraint,
    PixelBox,
    UHD_LANDSCAPE,
    best_of_n,
    exact_protected_product_match,
    upsample_prompt,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "evidence/v10/image-mastering-fixture"
SHA_A = "a" * 64


def _box(values: list[int]) -> PixelBox:
    return PixelBox(*values)


class ConstraintAndSelectionTests(unittest.TestCase):
    def test_prompt_upsampling_contains_every_locked_production_constraint(self) -> None:
        spec = ImageDirectionSpec(
            "d1", "product", "buyer", "review proof",
            BrandConstraint((1, 2, 3), (250, 251, 252)),
            FontConstraint("fixture", SHA_A, 72, 2),
            CompositionConstraint("asymmetric", "right", "left", 0.12),
            LightingConstraint("left", 5600, 4.0, True),
            MaterialConstraint(("paper",), ("liquid chrome",), True),
            NegativeSpaceConstraint(0.3, "left", True),
        )
        expanded = upsample_prompt(spec)
        for token in ("[intent]", "[composition]", "[lighting]", "[material]", "[negative_space]", "[brand]", "[forbidden]"):
            self.assertIn(token, expanded)
        self.assertIn("redraw product", expanded)
        self.assertIn("font_sha256=" + SHA_A, expanded)

    def test_brand_memory_lora_is_denied_while_lighting_layout_is_admitted(self) -> None:
        policy = LoraTrainingPolicy()
        self.assertTrue(policy.admit(("lighting", "layout"), ("q_proj", "v_proj")))
        self.assertFalse(policy.admit(("brand",), ("brand_embedding",)))
        self.assertFalse(policy.admit(("lighting",), ("logo_projector",)))

    def test_best_of_n_uses_five_located_hard_rewards(self) -> None:
        locators = {item: f"report#{item.value}" for item in ImageRewardDimension}
        good = ImageCandidate("good", {item: 1.0 for item in ImageRewardDimension}, locators, True, 0.1)
        lower = ImageCandidate("lower", {item: 0.995 for item in ImageRewardDimension}, locators, True, 0.0)
        bad_values = {item: 1.0 for item in ImageRewardDimension}
        bad_values[ImageRewardDimension.TYPOGRAPHY] = 0.9
        bad = ImageCandidate("bad", bad_values, locators, True, 0.0)
        self.assertEqual(best_of_n((lower, bad, good)).candidate_id, "good")
        with self.assertRaisesRegex(V10ContractError, "at least three"):
            best_of_n((good, lower))

    def test_local_repair_is_subset_of_failure_and_excludes_protected_regions(self) -> None:
        failure = PixelBox(500, 500, 900, 900)
        protected = PixelBox(2000, 1000, 2800, 1800)
        admitted = LocalRepairRequest(UHD_LANDSCAPE, PixelBox(550, 550, 700, 700), (failure,), (protected,))
        global_edit = LocalRepairRequest(UHD_LANDSCAPE, PixelBox(1, 1, 3800, 2100), (PixelBox(1, 1, 3839, 2159),), (protected,))
        protected_edit = LocalRepairRequest(UHD_LANDSCAPE, PixelBox(2100, 1100, 2200, 1200), (PixelBox(2000, 1000, 2300, 1300),), (protected,))
        self.assertTrue(admitted.admitted)
        self.assertFalse(global_edit.admitted)
        self.assertFalse(protected_edit.admitted)


class FourKFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = json.loads((FIXTURE / "report.json").read_text(encoding="utf-8"))

    def test_fixture_is_true_uhd_and_every_file_is_hash_bound(self) -> None:
        self.assertEqual(self.report["canvas_size"], [3840, 2160])
        self.assertEqual(self.report["fixture_origin"], "project_owned_mechanical_not_model_generated")
        for name, metadata in self.report["files"].items():
            path = FIXTURE / name
            self.assertEqual(sha256_file(path), metadata["sha256"])
        for name in ("master-3840x2160.png", "google-no-text-3840x2160.png", "social-safe-3840x2160.png"):
            with Image.open(FIXTURE / name) as image:
                self.assertEqual(image.size, (3840, 2160))

    def test_product_logo_and_text_masks_are_nonempty_disjoint_and_source_bound(self) -> None:
        masks = {item["kind"]: item for item in self.report["protection_masks"]}
        self.assertEqual(set(masks), {"product", "logo", "text"})
        self.assertTrue(all(item["nonzero_pixels"] > 0 for item in masks.values()))
        self.assertTrue(all(len(item["source_sha256"]) == 64 for item in masks.values()))
        product = Image.open(FIXTURE / "product-mask.png").convert("L")
        logo = Image.open(FIXTURE / "logo-mask.png").convert("L")
        text = Image.open(FIXTURE / "text-mask.png").convert("L")
        self.assertIsNone(ImageChops.multiply(product, logo).getbbox())
        self.assertIsNone(ImageChops.multiply(product, text).getbbox())

    def test_original_product_is_exactly_recomposited_in_all_three_variants(self) -> None:
        product = Image.open(FIXTURE / "product-source.png").convert("RGBA")
        product_box = _box(self.report["boxes"]["product"])
        for name in ("master-3840x2160.png", "google-no-text-3840x2160.png", "social-safe-3840x2160.png"):
            image = Image.open(FIXTURE / name)
            self.assertEqual(exact_protected_product_match(image, product, product_box), 1.0)
        self.assertEqual(self.report["product_identity_rate"], {"master": 1.0, "google_no_text": 1.0, "social_safe": 1.0})

    def test_logo_text_are_native_uhd_google_is_textless_and_social_is_safe(self) -> None:
        self.assertEqual(self.report["native_overlay_scale"], 1.0)
        self.assertEqual(self.report["google_no_text_overlay_count"], 0)
        self.assertTrue(self.report["social_safe_zone_pass"])
        safe = _box(self.report["boxes"]["social_safe_zone"])
        self.assertTrue(_box(self.report["boxes"]["social_logo"]).inside(safe))
        self.assertTrue(_box(self.report["boxes"]["social_text"]).inside(safe))
        self.assertFalse(any(self.report["model_execution"].values()))


if __name__ == "__main__":
    unittest.main()
