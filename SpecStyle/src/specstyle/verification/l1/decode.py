"""L1 decode hard rules: corrupt, multi-frame, wrong mode, empty bytes."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image

from specstyle.domain.enums import RuleStatus
from specstyle.domain.identifiers import ArtifactId, RuleId
from specstyle.errors import DomainError
from specstyle.verification.rule_models import RuleResult

RULE_DECODE = RuleId("L1_DECODE")


@dataclass(frozen=True, slots=True)
class DecodedImage:
    mode: str
    size: tuple[int, int]
    n_frames: int
    has_transparency: bool
    pixels_rgb: tuple[tuple[int, int, int], ...]  # flattened sample or full for small


def decode_png_bytes(data: object) -> DecodedImage:
    """Decode a clean, single-frame RGB PNG or raise a hard-contract error."""
    if type(data) is not bytes or not data:
        raise DomainError("L1_DECODE_EMPTY")
    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            n_frames = int(getattr(image, "n_frames", 1) or 1)
            if n_frames != 1:
                raise DomainError("L1_DECODE_MULTI_FRAME")
            if image.format != "PNG":
                raise DomainError("L1_DECODE_FORMAT")
            mode = image.mode
            if mode != "RGB":
                raise DomainError("L1_DECODE_MODE")
            if image.info or getattr(image, "text", {}):
                raise DomainError("L1_DECODE_METADATA")
            width, height = image.size
            if width < 1 or height < 1:
                raise DomainError("L1_DECODE_EMPTY")
            rgb = image.convert("RGB")
            # Materialize all pixels for pixel rules (CPU tests use small images).
            if hasattr(rgb, "get_flattened_data"):
                raw = rgb.get_flattened_data()
            else:
                raw = rgb.getdata()
            pix = tuple(raw)  # type: ignore[arg-type]
            has_alpha = mode in ("RGBA", "LA") or (
                mode == "P" and "transparency" in image.info
            )
            return DecodedImage(mode, (width, height), n_frames, has_alpha, pix)
    except DomainError:
        raise
    except Exception as exc:
        raise DomainError("L1_DECODE_CORRUPT") from exc


def rule_decode(artifact_id: ArtifactId, data: bytes, /) -> RuleResult:
    try:
        decode_png_bytes(data)
    except DomainError:
        return RuleResult(RULE_DECODE, RuleStatus.FAIL, (artifact_id,), None)
    return RuleResult(RULE_DECODE, RuleStatus.PASS, (artifact_id,), 1.0)
