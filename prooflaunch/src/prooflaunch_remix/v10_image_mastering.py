from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFont

from .v10_contracts import V10ContractError
from .v10_supply_chain import stable_sha256


UHD_LANDSCAPE = (3840, 2160)
UHD_PORTRAIT = (2160, 3840)
_HEX = frozenset("0123456789abcdef")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise V10ContractError(f"{field_name} must be a lowercase SHA-256")


def _require_unit(value: float, field_name: str) -> None:
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise V10ContractError(f"{field_name} must be in the unit interval")


@dataclass(frozen=True)
class PixelBox:
    left: int
    top: int
    right: int
    bottom: int

    def __post_init__(self) -> None:
        if min(self.left, self.top) < 0 or self.right <= self.left or self.bottom <= self.top:
            raise V10ContractError("pixel box must be positive and ordered")

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def area(self) -> int:
        return self.width * self.height

    def inside(self, other: "PixelBox") -> bool:
        return (
            self.left >= other.left
            and self.top >= other.top
            and self.right <= other.right
            and self.bottom <= other.bottom
        )

    def overlaps(self, other: "PixelBox") -> bool:
        return not (
            self.right <= other.left
            or other.right <= self.left
            or self.bottom <= other.top
            or other.bottom <= self.top
        )


class ProtectionKind(str, Enum):
    PRODUCT = "product"
    LOGO = "logo"
    TEXT = "text"


@dataclass(frozen=True)
class ProtectionMask:
    kind: ProtectionKind
    canvas_size: tuple[int, int]
    box: PixelBox
    source_sha256: str
    mask_sha256: str
    nonzero_pixels: int

    def __post_init__(self) -> None:
        _require_sha256(self.source_sha256, "source_sha256")
        _require_sha256(self.mask_sha256, "mask_sha256")
        if self.nonzero_pixels < 1:
            raise V10ContractError("protection mask cannot be empty")
        width, height = self.canvas_size
        if self.box.right > width or self.box.bottom > height:
            raise V10ContractError("protection mask box exceeds canvas")


@dataclass(frozen=True)
class BrandConstraint:
    primary_rgb: tuple[int, int, int]
    secondary_rgb: tuple[int, int, int]
    maximum_delta_e: float = 1.5

    def __post_init__(self) -> None:
        for color in (self.primary_rgb, self.secondary_rgb):
            if len(color) != 3 or any(not isinstance(value, int) or not 0 <= value <= 255 for value in color):
                raise V10ContractError("brand colors must be RGB byte triples")
        if not math.isfinite(self.maximum_delta_e) or self.maximum_delta_e <= 0:
            raise V10ContractError("brand color tolerance must be positive")


@dataclass(frozen=True)
class FontConstraint:
    family: str
    font_sha256: str
    minimum_native_px: int
    maximum_line_count: int

    def __post_init__(self) -> None:
        if not self.family.strip():
            raise V10ContractError("font family is required")
        _require_sha256(self.font_sha256, "font_sha256")
        if self.minimum_native_px < 24 or self.maximum_line_count < 1:
            raise V10ContractError("font size and line limits are invalid")


@dataclass(frozen=True)
class CompositionConstraint:
    focal_rule: str
    product_anchor: str
    logo_anchor: str
    safe_margin_ratio: float

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.focal_rule, self.product_anchor, self.logo_anchor)):
            raise V10ContractError("composition constraints are incomplete")
        if not 0.05 <= self.safe_margin_ratio <= 0.25:
            raise V10ContractError("safe margin ratio must be between 5% and 25%")


@dataclass(frozen=True)
class LightingConstraint:
    key_direction: str
    color_temperature_kelvin: int
    contrast_ratio: float
    product_shadow_allowed: bool

    def __post_init__(self) -> None:
        if self.key_direction not in {"left", "right", "top", "front", "back"}:
            raise V10ContractError("lighting direction is unsupported")
        if not 1_500 <= self.color_temperature_kelvin <= 12_000:
            raise V10ContractError("lighting color temperature is implausible")
        if not math.isfinite(self.contrast_ratio) or not 1 <= self.contrast_ratio <= 16:
            raise V10ContractError("lighting contrast ratio is invalid")


@dataclass(frozen=True)
class MaterialConstraint:
    allowed_materials: tuple[str, ...]
    forbidden_materials: tuple[str, ...]
    preserve_product_material: bool

    def __post_init__(self) -> None:
        if not self.allowed_materials or not self.forbidden_materials:
            raise V10ContractError("material allow and deny lists are required")
        if {item.lower() for item in self.allowed_materials} & {
            item.lower() for item in self.forbidden_materials
        }:
            raise V10ContractError("material allow and deny lists overlap")
        if not self.preserve_product_material:
            raise V10ContractError("product material must remain immutable")


@dataclass(frozen=True)
class NegativeSpaceConstraint:
    minimum_ratio: float
    reserved_anchor: str
    protected_from_generation: bool

    def __post_init__(self) -> None:
        if not 0.10 <= self.minimum_ratio <= 0.70 or not self.reserved_anchor.strip():
            raise V10ContractError("negative-space constraint is invalid")
        if not self.protected_from_generation:
            raise V10ContractError("negative space must be protected")


@dataclass(frozen=True)
class ImageDirectionSpec:
    direction_id: str
    subject: str
    audience: str
    desired_action: str
    brand: BrandConstraint
    font: FontConstraint
    composition: CompositionConstraint
    lighting: LightingConstraint
    material: MaterialConstraint
    negative_space: NegativeSpaceConstraint
    forbidden_changes: tuple[str, ...] = (
        "redraw product",
        "redraw logo",
        "generate typography",
        "invent claim",
    )

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.direction_id, self.subject, self.audience, self.desired_action)):
            raise V10ContractError("image direction identity is incomplete")
        if len(set(self.forbidden_changes)) != len(self.forbidden_changes):
            raise V10ContractError("forbidden changes must be unique")

    @property
    def digest(self) -> str:
        return stable_sha256(asdict(self))


def upsample_prompt(spec: ImageDirectionSpec) -> str:
    """Expand an intent into located production constraints without an online model."""

    primary = "#" + "".join(f"{value:02X}" for value in spec.brand.primary_rgb)
    secondary = "#" + "".join(f"{value:02X}" for value in spec.brand.secondary_rgb)
    return "\n".join(
        (
            f"[intent] subject={spec.subject}; audience={spec.audience}; action={spec.desired_action}",
            f"[composition] focal={spec.composition.focal_rule}; product={spec.composition.product_anchor}; logo={spec.composition.logo_anchor}; safe_margin={spec.composition.safe_margin_ratio:.3f}",
            f"[lighting] key={spec.lighting.key_direction}; kelvin={spec.lighting.color_temperature_kelvin}; contrast={spec.lighting.contrast_ratio:.2f}",
            f"[material] allowed={','.join(spec.material.allowed_materials)}; preserve_product_material=true",
            f"[negative_space] ratio>={spec.negative_space.minimum_ratio:.3f}; anchor={spec.negative_space.reserved_anchor}",
            f"[brand] primary={primary}; secondary={secondary}; delta_e<={spec.brand.maximum_delta_e:.2f}; font_sha256={spec.font.font_sha256}",
            f"[forbidden] {', '.join(spec.forbidden_changes)}; forbidden_materials={','.join(spec.material.forbidden_materials)}",
        )
    )


@dataclass(frozen=True)
class LoraTrainingPolicy:
    allowed_taxa: tuple[str, ...] = ("lighting", "layout")
    forbidden_taxa: tuple[str, ...] = (
        "brand",
        "logo",
        "product_identity",
        "typography",
        "claim",
        "color_palette",
    )

    def admit(self, training_taxa: Sequence[str], target_modules: Sequence[str]) -> bool:
        taxa = {item.strip().lower() for item in training_taxa}
        modules = {item.strip().lower() for item in target_modules}
        if not taxa or not modules or not taxa <= set(self.allowed_taxa):
            return False
        forbidden = set(self.forbidden_taxa)
        return not any(any(token in item for token in forbidden) for item in (*taxa, *modules))


class ImageRewardDimension(str, Enum):
    REGION = "region"
    PRODUCT = "product"
    LOGO = "logo"
    TYPOGRAPHY = "typography"
    SAFE_ZONE = "safe_zone"


@dataclass(frozen=True)
class ImageCandidate:
    candidate_id: str
    rewards: Mapping[ImageRewardDimension, float]
    evidence_locators: Mapping[ImageRewardDimension, str]
    observed: bool
    repair_cost: float

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or set(self.rewards) != set(ImageRewardDimension):
            raise V10ContractError("image candidate requires every reward dimension")
        if set(self.evidence_locators) != set(ImageRewardDimension):
            raise V10ContractError("every image reward needs an evidence locator")
        for dimension, value in self.rewards.items():
            _require_unit(value, dimension.value)
            if not self.evidence_locators[dimension].strip():
                raise V10ContractError("image reward evidence locator is empty")
        if not math.isfinite(self.repair_cost) or self.repair_cost < 0:
            raise V10ContractError("repair cost must be finite and nonnegative")


IMAGE_REWARD_FLOORS = {
    ImageRewardDimension.REGION: 0.95,
    ImageRewardDimension.PRODUCT: 0.99,
    ImageRewardDimension.LOGO: 0.99,
    ImageRewardDimension.TYPOGRAPHY: 0.999,
    ImageRewardDimension.SAFE_ZONE: 0.99,
}


def best_of_n(candidates: Sequence[ImageCandidate], *, minimum_n: int = 3) -> ImageCandidate:
    if len(candidates) < minimum_n:
        raise V10ContractError("Best-of-N requires at least three candidates")
    identifiers = [item.candidate_id for item in candidates]
    if len(identifiers) != len(set(identifiers)):
        raise V10ContractError("Best-of-N candidate identities must be unique")
    eligible = tuple(
        item
        for item in candidates
        if item.observed
        and all(item.rewards[key] >= floor for key, floor in IMAGE_REWARD_FLOORS.items())
    )
    if not eligible:
        raise V10ContractError("no candidate clears every hard image reward floor")
    dimensions = tuple(ImageRewardDimension)
    return sorted(
        eligible,
        key=lambda item: (
            -min(item.rewards.values()),
            *(-item.rewards[key] for key in dimensions),
            item.repair_cost,
            item.candidate_id,
        ),
    )[0]


def _mask_sha256(mask: Image.Image) -> str:
    return hashlib.sha256(mask.convert("L").tobytes()).hexdigest()


def _image_sha256(image: Image.Image) -> str:
    return hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()


def _nonzero(mask: Image.Image) -> int:
    histogram = mask.convert("L").histogram()
    return mask.width * mask.height - histogram[0]


def safe_zone(canvas_size: tuple[int, int], margin_ratio: float) -> PixelBox:
    width, height = canvas_size
    margin_x = round(width * margin_ratio)
    margin_y = round(height * margin_ratio)
    return PixelBox(margin_x, margin_y, width - margin_x, height - margin_y)


@dataclass(frozen=True)
class FourKMasterResult:
    master: Image.Image
    google_no_text: Image.Image
    social_safe: Image.Image
    product_mask: Image.Image
    logo_mask: Image.Image
    text_mask: Image.Image
    product_box: PixelBox
    logo_box: PixelBox
    text_box: PixelBox
    social_logo_box: PixelBox
    social_text_box: PixelBox
    social_safe_zone: PixelBox
    product_source_sha256: str
    font_sha256: str
    native_overlay_scale: float


class FourKMasterComposer:
    """Builds a UHD master by compositing immutable identity and native overlays."""

    def __init__(self, *, font_path: str | Path, brand: BrandConstraint) -> None:
        self.font_path = Path(font_path)
        if not self.font_path.is_file():
            raise V10ContractError("native overlay font file is missing")
        self.font_sha256 = hashlib.sha256(self.font_path.read_bytes()).hexdigest()
        self.brand = brand

    @staticmethod
    def _validate_uhd(size: tuple[int, int]) -> None:
        if size not in {UHD_LANDSCAPE, UHD_PORTRAIT}:
            raise V10ContractError("master canvas must be exact UHD landscape or portrait")

    def compose(
        self,
        *,
        background: Image.Image,
        product_source: Image.Image,
        product_xy: tuple[int, int],
        logo_text: str,
        headline: str,
    ) -> FourKMasterResult:
        canvas = background.convert("RGBA")
        self._validate_uhd(canvas.size)
        product = product_source.convert("RGBA")
        product_sha = _image_sha256(product)
        product_box = PixelBox(
            product_xy[0],
            product_xy[1],
            product_xy[0] + product.width,
            product_xy[1] + product.height,
        )
        frame = PixelBox(0, 0, canvas.width, canvas.height)
        if not product_box.inside(frame):
            raise V10ContractError("native product layer exceeds the UHD canvas")
        product_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        product_layer.alpha_composite(product, product_xy)
        product_mask = Image.new("L", canvas.size, 0)
        product_mask.paste(product.getchannel("A"), product_xy)
        no_text = Image.alpha_composite(canvas, product_layer)

        master, logo_mask, text_mask, logo_box, text_box = self._native_overlays(
            no_text, logo_text, headline, safe_margin=0.055
        )
        social, social_logo_mask, social_text_mask, social_logo_box, social_text_box = self._native_overlays(
            no_text, logo_text, headline, safe_margin=0.12
        )
        social_zone = safe_zone(canvas.size, 0.12)
        if not social_logo_box.inside(social_zone) or not social_text_box.inside(social_zone):
            raise V10ContractError("social overlays escaped the safe zone")
        if _nonzero(ImageChops.multiply(product_mask, logo_mask)) or _nonzero(
            ImageChops.multiply(product_mask, text_mask)
        ):
            raise V10ContractError("identity and generated overlay masks overlap")
        if _nonzero(ImageChops.multiply(product_mask, social_logo_mask)) or _nonzero(
            ImageChops.multiply(product_mask, social_text_mask)
        ):
            raise V10ContractError("social overlays overlap the product identity")
        return FourKMasterResult(
            master=master.convert("RGB"),
            google_no_text=no_text.convert("RGB"),
            social_safe=social.convert("RGB"),
            product_mask=product_mask,
            logo_mask=logo_mask,
            text_mask=text_mask,
            product_box=product_box,
            logo_box=logo_box,
            text_box=text_box,
            social_logo_box=social_logo_box,
            social_text_box=social_text_box,
            social_safe_zone=social_zone,
            product_source_sha256=product_sha,
            font_sha256=self.font_sha256,
            native_overlay_scale=1.0,
        )

    def _native_overlays(
        self,
        base: Image.Image,
        logo_text: str,
        headline: str,
        *,
        safe_margin: float,
    ) -> tuple[Image.Image, Image.Image, Image.Image, PixelBox, PixelBox]:
        width, height = base.size
        zone = safe_zone(base.size, safe_margin)
        logo_font = ImageFont.truetype(str(self.font_path), size=max(72, width // 28))
        text_font = ImageFont.truetype(str(self.font_path), size=max(96, width // 20))
        logo_xy = (zone.left, zone.top)
        text_xy = (zone.left, zone.top + round(height * 0.17))
        probe = ImageDraw.Draw(Image.new("L", base.size, 0))
        logo_raw = probe.textbbox(logo_xy, logo_text, font=logo_font, stroke_width=0)
        text_raw = probe.textbbox(text_xy, headline, font=text_font, stroke_width=0)
        logo_box = PixelBox(*logo_raw)
        text_box = PixelBox(*text_raw)
        if not logo_box.inside(zone) or not text_box.inside(zone):
            raise V10ContractError("native logo or text does not fit safe zone")
        logo_mask = Image.new("L", base.size, 0)
        text_mask = Image.new("L", base.size, 0)
        ImageDraw.Draw(logo_mask).text(logo_xy, logo_text, font=logo_font, fill=255)
        ImageDraw.Draw(text_mask).text(text_xy, headline, font=text_font, fill=255)
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        draw.text(logo_xy, logo_text, font=logo_font, fill=(*self.brand.primary_rgb, 255))
        draw.text(text_xy, headline, font=text_font, fill=(*self.brand.secondary_rgb, 255))
        return Image.alpha_composite(base, overlay), logo_mask, text_mask, logo_box, text_box


def exact_protected_product_match(
    final_image: Image.Image,
    product_source: Image.Image,
    product_box: PixelBox,
) -> float:
    expected = product_source.convert("RGBA")
    actual = final_image.convert("RGBA").crop(
        (product_box.left, product_box.top, product_box.right, product_box.bottom)
    )
    if actual.size != expected.size:
        return 0.0
    mask = expected.getchannel("A")
    difference = ImageChops.difference(actual.convert("RGB"), expected.convert("RGB"))
    difference_mask = difference.convert("L").point(lambda value: 255 if value else 0)
    mismatch = _nonzero(ImageChops.multiply(difference_mask, mask))
    opaque = _nonzero(mask)
    if opaque == 0:
        raise V10ContractError("product identity source has no opaque pixels")
    return 1 - mismatch / opaque


@dataclass(frozen=True)
class LocalRepairRequest:
    canvas_size: tuple[int, int]
    repair_box: PixelBox
    failure_boxes: tuple[PixelBox, ...]
    protected_boxes: tuple[PixelBox, ...]
    maximum_area_ratio: float = 0.15

    def __post_init__(self) -> None:
        if not self.failure_boxes or not self.protected_boxes:
            raise V10ContractError("local repair needs failure and protection regions")
        if not 0 < self.maximum_area_ratio <= 0.20:
            raise V10ContractError("local repair area ceiling must be at most 20%")

    @property
    def admitted(self) -> bool:
        width, height = self.canvas_size
        canvas = PixelBox(0, 0, width, height)
        if not self.repair_box.inside(canvas):
            return False
        if self.repair_box.area / (width * height) > self.maximum_area_ratio:
            return False
        if any(self.repair_box.overlaps(item) for item in self.protected_boxes):
            return False
        return any(self.repair_box.inside(item) for item in self.failure_boxes)


def protection_receipt(
    *,
    kind: ProtectionKind,
    mask: Image.Image,
    box: PixelBox,
    source_sha256: str,
) -> ProtectionMask:
    return ProtectionMask(
        kind=kind,
        canvas_size=mask.size,
        box=box,
        source_sha256=source_sha256,
        mask_sha256=_mask_sha256(mask),
        nonzero_pixels=_nonzero(mask),
    )


def planned_image_pack_card() -> Mapping[str, object]:
    body = {
        "schema": "ProofLaunch4KImagePackCardV1",
        "execution_status": "mechanical_mastering_fixture_verified_model_runs_open",
        "model_runs": {
            "flux2_klein": None,
            "flux2_base": None,
            "sdxl_fallback": None,
            "grounding_dino": None,
            "sam2_1": None,
            "real_esrgan": None,
            "swinir": None,
            "seedvr2": None,
        },
        "trained_loras": {"lighting": None, "layout": None},
        "generated_directions": None,
        "concept_board": None,
        "key_visual": None,
        "aspect_ratio_packs": None,
        "neural_quality_metrics": {
            "ocr_accuracy": None,
            "brand_delta_e": None,
            "product_identity": None,
            "logo_identity": None,
            "claim_coverage": None,
        },
        "baseline_comparisons": {"direct_flux": None, "comfy_workflow": None},
        "frozen_pack": None,
        "promotion_eligible": False,
        "truth_boundary": (
            "A project-owned mechanical UHD fixture verifies masks, native overlays, "
            "immutable recomposition, safe zones, selection and local-repair controls. "
            "It is not a FLUX/SDXL/restoration run or a 4A image-quality result."
        ),
    }
    return {**body, "card_sha256": stable_sha256(body)}
