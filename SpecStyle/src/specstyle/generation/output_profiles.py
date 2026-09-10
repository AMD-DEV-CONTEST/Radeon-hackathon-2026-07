"""Three output profiles: shared post-process after main generation."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont, ImageOps

from specstyle.errors import DomainError
from specstyle.generation.output_profile_contracts import (
    production_output_profile_capabilities,
)
from specstyle.observability.hashing import hash_bytes
from specstyle.spec.compiled_models import OutputProfileCapability

OutputProfileName = str  # xhs_grid | talking_head_cover | background_sequence


@dataclass(frozen=True, slots=True)
class ProfileLayout:
    name: str
    size: tuple[int, int]
    safe_zone: tuple[float, float, float, float]  # x0,y0,x1,y1 normalized


PROFILES: dict[str, ProfileLayout] = {
    "xhs_grid": ProfileLayout("xhs_grid", (1080, 1080), (0.08, 0.08, 0.92, 0.92)),
    "talking_head_cover": ProfileLayout(
        "talking_head_cover", (1080, 1440), (0.1, 0.12, 0.9, 0.88)
    ),
    "background_sequence": ProfileLayout(
        "background_sequence", (1920, 1080), (0.05, 0.08, 0.95, 0.92)
    ),
}


def render_output_profile(
    source_png: bytes,
    profile: str,
    *,
    text: str | None = None,
    sequence_index: int | None = None,
) -> bytes:
    if type(source_png) is not bytes or not source_png:
        raise DomainError("invalid source image")
    if profile not in PROFILES:
        raise DomainError("unknown output profile")
    layout = PROFILES[profile]
    if profile == "background_sequence":
        if (
            type(sequence_index) is not int
            or isinstance(sequence_index, bool)
            or sequence_index < 0
        ):
            raise DomainError("sequence index required")
    image = Image.open(BytesIO(source_png)).convert("RGB")
    out = image.resize(layout.size)
    if text:
        draw = ImageDraw.Draw(out)
        # Deterministic default font
        font = ImageFont.load_default()
        # Anchor text in safe zone top-left
        x = int(layout.safe_zone[0] * layout.size[0])
        y = int(layout.safe_zone[1] * layout.size[1])
        draw.text((x, y), text[:64], fill=(255, 255, 255), font=font)
    if sequence_index is not None and profile == "background_sequence":
        draw = ImageDraw.Draw(out)
        draw.text((10, 10), f"seq={sequence_index}", fill=(200, 200, 200))
    buf = BytesIO()
    out.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def profile_content_hash(png: bytes) -> str:
    return hash_bytes(png).value


def _implemented_capability(value: object) -> OutputProfileCapability:
    if type(value) is not OutputProfileCapability:
        raise DomainError("invalid output renderer contract")
    matched = tuple(
        item
        for item in production_output_profile_capabilities()
        if item.profile == value.profile
    )
    if matched != (value,) or value.render_contract is None:
        raise DomainError("invalid output renderer contract")
    return matched[0]


def _decode_source(content: object) -> Image.Image:
    if type(content) is not bytes or not content:
        raise DomainError("invalid source image")
    try:
        image = Image.open(BytesIO(content))
        image.load()
    except (OSError, ValueError):
        raise DomainError("invalid source image") from None
    if image.mode != "RGB" or getattr(image, "n_frames", 1) != 1 or image.info:
        image.close()
        raise DomainError("invalid source image")
    return image


def _render_image(
    image: Image.Image, capability: OutputProfileCapability
) -> Image.Image:
    contract = capability.render_contract
    if contract is None:  # pragma: no cover - guarded by _implemented_capability
        raise DomainError("invalid output renderer contract")
    size = contract.final_resolution
    if contract.fit in {"contain_pad", "contain_pad_center"}:
        resized = ImageOps.contain(image, size, Image.Resampling.LANCZOS)
        output = Image.new("RGB", size, contract.background)
        offset = ((size[0] - resized.width) // 2, (size[1] - resized.height) // 2)
        output.paste(resized, offset)
        resized.close()
        return output
    return ImageOps.fit(image, size, Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def render_production_output(
    source_png: bytes, capability: OutputProfileCapability, /
) -> bytes:
    """Render one final Production artifact under an exact built-in contract."""
    capability = _implemented_capability(capability)
    source = _decode_source(source_png)
    output = None
    try:
        contract = capability.render_contract
        if contract is None:  # pragma: no cover - guarded by capability validation
            raise DomainError("invalid output renderer contract")
        if (
            contract.native_resolution is not None
            and source.size != contract.native_resolution
        ):
            raise DomainError("invalid native output resolution")
        output = _render_image(source, capability)
        encoded = BytesIO()
        output.save(encoded, format="PNG", optimize=False, compress_level=9)
        return encoded.getvalue()
    finally:
        if output is not None:
            output.close()
        source.close()
