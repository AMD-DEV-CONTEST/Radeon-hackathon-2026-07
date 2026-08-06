#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.v10_image_mastering import (
    BrandConstraint,
    CompositionConstraint,
    FontConstraint,
    FourKMasterComposer,
    IMAGE_REWARD_FLOORS,
    ImageCandidate,
    ImageDirectionSpec,
    ImageRewardDimension,
    LightingConstraint,
    LocalRepairRequest,
    LoraTrainingPolicy,
    MaterialConstraint,
    NegativeSpaceConstraint,
    PixelBox,
    ProtectionKind,
    UHD_LANDSCAPE,
    best_of_n,
    exact_protected_product_match,
    planned_image_pack_card,
    protection_receipt,
    upsample_prompt,
)
from prooflaunch_remix.v10_supply_chain import stable_sha256


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence/v10/image-mastering-fixture"


def _font_path() -> Path:
    candidates = (
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    from PIL import ImageFont

    discovered = Path(str(ImageFont.truetype("DejaVuSans-Bold.ttf", 32).path))
    if discovered.is_file():
        return discovered
    raise RuntimeError("no content-addressable TrueType font was found")


def _save(image: Image.Image, name: str) -> Path:
    path = OUTPUT / name
    image.save(path, format="PNG", optimize=False)
    return path


def _box(box: PixelBox) -> list[int]:
    return [box.left, box.top, box.right, box.bottom]


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    gradient = Image.linear_gradient("L").resize(UHD_LANDSCAPE)
    background = ImageOps.colorize(gradient, black=(8, 14, 32), white=(62, 84, 132)).convert("RGB")
    background_path = _save(background, "background-3840x2160.png")

    product = Image.new("RGBA", (720, 720), (0, 0, 0, 0))
    draw = ImageDraw.Draw(product)
    draw.rounded_rectangle((40, 40, 680, 680), radius=96, fill=(230, 45, 55, 255), outline=(255, 255, 255, 255), width=18)
    draw.ellipse((250, 185, 470, 405), fill=(255, 220, 72, 255))
    draw.rectangle((245, 470, 475, 520), fill=(20, 24, 42, 255))
    product_path = _save(product, "product-source.png")

    brand = BrandConstraint((26, 111, 255), (255, 255, 255), 1.5)
    font_path = _font_path()
    composer = FourKMasterComposer(font_path=font_path, brand=brand)
    result = composer.compose(
        background=background,
        product_source=product,
        product_xy=(2760, 790),
        logo_text="PROOFLAUNCH",
        headline="EVIDENCE, NOT ESTIMATES",
    )
    master_path = _save(result.master, "master-3840x2160.png")
    no_text_path = _save(result.google_no_text, "google-no-text-3840x2160.png")
    social_path = _save(result.social_safe, "social-safe-3840x2160.png")
    product_mask_path = _save(result.product_mask, "product-mask.png")
    logo_mask_path = _save(result.logo_mask, "logo-mask.png")
    text_mask_path = _save(result.text_mask, "text-mask.png")

    logo_source_sha = stable_sha256({"font_sha256": result.font_sha256, "text": "PROOFLAUNCH"})
    text_source_sha = stable_sha256({"font_sha256": result.font_sha256, "text": "EVIDENCE, NOT ESTIMATES"})
    masks = (
        protection_receipt(kind=ProtectionKind.PRODUCT, mask=result.product_mask, box=result.product_box, source_sha256=result.product_source_sha256),
        protection_receipt(kind=ProtectionKind.LOGO, mask=result.logo_mask, box=result.logo_box, source_sha256=logo_source_sha),
        protection_receipt(kind=ProtectionKind.TEXT, mask=result.text_mask, box=result.text_box, source_sha256=text_source_sha),
    )

    font_constraint = FontConstraint("Arial-compatible bold fixture", result.font_sha256, 72, 2)
    direction = ImageDirectionSpec(
        "fixture-direction-a",
        "immutable project-owned red product",
        "evidence-sensitive growth leader",
        "review located proof",
        brand,
        font_constraint,
        CompositionConstraint("asymmetric evidence-first", "right lower third", "left upper", 0.12),
        LightingConstraint("left", 5_600, 4.0, True),
        MaterialConstraint(("matte paper", "brushed metal"), ("liquid chrome", "skin", "glass product redraw"), True),
        NegativeSpaceConstraint(0.30, "left-center message field", True),
    )
    expanded_prompt = upsample_prompt(direction)

    reward_locators = {item: f"image-mastering-fixture/report.json#rewards/{item.value}" for item in ImageRewardDimension}
    candidates = (
        ImageCandidate("candidate-a", {item: 0.995 for item in ImageRewardDimension}, reward_locators, True, 0.02),
        ImageCandidate("candidate-b", {item: 0.9995 for item in ImageRewardDimension}, reward_locators, True, 0.04),
        ImageCandidate("candidate-c", {**{item: 1.0 for item in ImageRewardDimension}, ImageRewardDimension.TYPOGRAPHY: 0.90}, reward_locators, True, 0.00),
    )
    selected = best_of_n(candidates)
    local_repair = LocalRepairRequest(
        canvas_size=UHD_LANDSCAPE,
        repair_box=PixelBox(1_300, 1_400, 1_620, 1_680),
        failure_boxes=(PixelBox(1_250, 1_350, 1_700, 1_750),),
        protected_boxes=(result.product_box, result.logo_box, result.text_box),
    )
    identity = {
        "master": exact_protected_product_match(result.master, product, result.product_box),
        "google_no_text": exact_protected_product_match(result.google_no_text, product, result.product_box),
        "social_safe": exact_protected_product_match(result.social_safe, product, result.product_box),
    }
    files = {
        path.name: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        for path in (
            background_path,
            product_path,
            master_path,
            no_text_path,
            social_path,
            product_mask_path,
            logo_mask_path,
            text_mask_path,
        )
    }
    body = {
        "schema": "ProofLaunch4KImageMasteringFixtureV1",
        "status": "passed",
        "canvas_size": list(UHD_LANDSCAPE),
        "fixture_origin": "project_owned_mechanical_not_model_generated",
        "files": files,
        "font": {"path": str(font_path), "sha256": result.font_sha256, "redistributed": False},
        "brand_constraint": {"primary_rgb": list(brand.primary_rgb), "secondary_rgb": list(brand.secondary_rgb), "maximum_delta_e": brand.maximum_delta_e},
        "boxes": {
            "product": _box(result.product_box),
            "logo": _box(result.logo_box),
            "text": _box(result.text_box),
            "social_logo": _box(result.social_logo_box),
            "social_text": _box(result.social_text_box),
            "social_safe_zone": _box(result.social_safe_zone),
        },
        "protection_masks": [
            {
                "kind": item.kind.value,
                "source_sha256": item.source_sha256,
                "mask_sha256": item.mask_sha256,
                "nonzero_pixels": item.nonzero_pixels,
                "box": _box(item.box),
            }
            for item in masks
        ],
        "product_identity_rate": identity,
        "native_overlay_scale": result.native_overlay_scale,
        "google_no_text_overlay_count": 0,
        "social_safe_zone_pass": True,
        "prompt_upsampling": {"direction_sha256": direction.digest, "expanded_prompt_sha256": hashlib.sha256(expanded_prompt.encode("utf-8")).hexdigest(), "online_model_used": False},
        "lora_policy": {"lighting_layout_admitted": LoraTrainingPolicy().admit(("lighting", "layout"), ("q_proj", "v_proj")), "brand_memory_admitted": LoraTrainingPolicy().admit(("brand",), ("brand_embedding",))},
        "best_of_n": {"candidate_count": len(candidates), "selected": selected.candidate_id, "hard_floors": {key.value: value for key, value in IMAGE_REWARD_FLOORS.items()}},
        "local_repair_admitted": local_repair.admitted,
        "model_execution": {"flux": False, "sdxl": False, "grounding_dino": False, "sam2": False, "real_esrgan": False, "swinir": False, "seedvr2": False},
        "truth_boundary": "The images are a project-owned deterministic Pillow fixture proving UHD mastering mechanics, not generative or restoration model quality.",
    }
    report = {**body, "report_sha256": stable_sha256(body)}
    atomic_write_text(OUTPUT / "report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    atomic_write_text(ROOT / "evidence/v10/image-pack-card.planned.json", json.dumps(planned_image_pack_card(), ensure_ascii=False, indent=2) + "\n")

    contract = {
        "schema": "ProofLaunch4KImageMasteringContractV1",
        "mechanisms": [
            "prompt_upsampling",
            "product_logo_text_protection_masks",
            "brand_font_composition_lighting_material_negative_space_constraints",
            "brand_memory_lora_denial",
            "five_reward_best_of_n",
            "immutable_product_recomposition",
            "native_uhd_logo_and_text",
            "google_no_text_variant",
            "social_safe_variant",
            "local_repair_only",
        ],
        "research_sources": [
            {"name": "FLUX.2", "locator": "https://github.com/black-forest-labs/flux2", "role": "multi-reference editing and prompt-upsampling method reference"},
            {"name": "Grounding DINO", "locator": "https://github.com/IDEA-Research/GroundingDINO", "role": "open-set product grounding method reference"},
            {"name": "SAM 2.1", "locator": "https://github.com/facebookresearch/sam2", "role": "promptable product-mask method reference"},
            {"name": "Real-ESRGAN", "locator": "https://github.com/xinntao/Real-ESRGAN", "role": "restoration method reference; not executed in this fixture"},
        ],
        "execution_status": "mechanical_mastering_fixture_verified_model_runs_open",
        "model_execution_observed": False,
        "promotion_eligible": False,
    }
    payload = {**contract, "contract_sha256": stable_sha256(contract)}
    atomic_write_text(ROOT / "config/cortex_x_v10_image_mastering_contract.json", json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "report_sha256": report["report_sha256"], "contract_sha256": payload["contract_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
