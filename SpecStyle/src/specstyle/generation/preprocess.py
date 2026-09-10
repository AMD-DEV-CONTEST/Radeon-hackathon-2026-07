"""Deterministic preprocessing for constrained input images."""

from __future__ import annotations

import math
import sys
import warnings
from dataclasses import dataclass, field
from io import BytesIO
from typing import Literal

from PIL import Image, UnidentifiedImageError

from specstyle.domain.artifacts import AssetRef
from specstyle.domain.identifiers import AssetId, Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.observability.hashing import hash_bytes
from specstyle.spec.compiled_models import ResourcePin

_FORMATS = {"PNG", "JPEG", "WEBP"}
_MODES = {"1", "L", "LA", "P", "RGB", "RGBA", "CMYK"}
_MAX_BYTES = 32 * 1024 * 1024
_MAX_EDGE = 16384
_MAX_PIXELS = 25_000_000


def _exact_tuple(value: object, name: str, length: int) -> tuple[int, ...]:
    if (
        type(value) is not tuple
        or len(value) != length
        or any(type(v) is not int for v in value)
    ):
        raise DomainError(f"{name} must contain exact ints")
    return value


def _metadata_absent(image: Image.Image) -> bool:
    return not image.info and not getattr(image, "text", {})


def _rebuild_sha256(value: object) -> Sha256:
    if type(value) is not Sha256:
        raise DomainError("invalid sha256")
    return Sha256(value.value)


def _rebuild_asset_ref(value: object) -> AssetRef:
    if type(value) is not AssetRef or type(value.asset_id) is not AssetId:
        raise DomainError("invalid asset reference")
    return AssetRef(AssetId(value.asset_id.value), _rebuild_sha256(value.sha256))


def _rebuild_resource_pin(value: object) -> ResourcePin:
    if type(value) is not ResourcePin:
        raise DomainError("invalid resource pin")
    return ResourcePin(value.id, value.revision, _rebuild_sha256(value.sha256))


def _orientation(image: Image.Image) -> int:
    raw_exif = image.info.get("exif")
    if raw_exif is None:
        return 1
    if type(raw_exif) is not bytes:
        raise DomainError("invalid EXIF orientation")
    try:
        exif = Image.Exif()
        exif.load(raw_exif)
        orientation = exif.get(274, 1)
    except (OSError, TypeError, ValueError) as error:
        raise DomainError("invalid EXIF orientation") from error
    if type(orientation) is not int or not 1 <= orientation <= 8:
        raise DomainError("invalid EXIF orientation")
    return orientation


def _check_image(image: Image.Image) -> tuple[str, str, tuple[int, int], int]:
    if (
        type(image.format) is not str
        or image.format not in _FORMATS
        or getattr(image, "n_frames", 1) != 1
    ):
        raise DomainError("input must be a single-frame PNG, JPEG, or WEBP")
    size = image.size
    if size[0] > _MAX_EDGE or size[1] > _MAX_EDGE or size[0] * size[1] > _MAX_PIXELS:
        raise DomainError("input image exceeds limits")
    if image.mode not in _MODES:
        raise DomainError("unsupported input image mode")
    if image.info.get("icc_profile"):
        raise DomainError("ICC profile is not allowed")
    return image.format, image.mode, size, _orientation(image)


def _close_images(images: list[Image.Image]) -> None:
    seen: set[int] = set()
    failure: Exception | None = None
    for image in reversed(images):
        if id(image) in seen:
            continue
        seen.add(id(image))
        try:
            image.close()
        except Exception as error:
            if failure is None:
                failure = error
    if failure is not None:
        raise InfrastructureError("image processing failed") from failure


def _close_after_primary(images: list[Image.Image]) -> None:
    if sys.exc_info()[0] is not None:
        try:
            _close_images(images)
        except InfrastructureError:
            pass
    else:
        _close_images(images)


def _verify_input(content: bytes) -> tuple[str, str, tuple[int, int], int]:
    image: Image.Image | None = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(BytesIO(content))
            details = _check_image(image)
            image.verify()
            return details
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise DomainError("invalid input image") from error
    except MemoryError as error:
        raise InfrastructureError("image processing failed") from error
    except (DomainError, InfrastructureError):
        raise
    except Exception as error:
        raise InfrastructureError("image processing failed") from error
    finally:
        _close_after_primary([image] if image is not None else [])


def _load_checked(
    content: bytes,
) -> tuple[Image.Image, tuple[str, str, tuple[int, int], int | None]]:
    image: Image.Image | None = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(BytesIO(content))
            details = _check_image(image)
            image.load()
            return image, details
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise DomainError("invalid input image") from error
    except MemoryError as error:
        raise InfrastructureError("image processing failed") from error
    except (DomainError, InfrastructureError):
        raise
    except Exception as error:
        raise InfrastructureError("image processing failed") from error
    finally:
        if image is not None and sys.exc_info()[0] is not None:
            _close_after_primary([image])


def _round(value: float) -> int:
    return math.floor(value + 0.5)


def _to_rgb(
    image: Image.Image,
    background: tuple[int, int, int],
    images: list[Image.Image],
) -> Image.Image:
    if image.mode in {"LA", "RGBA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        images.append(rgba)
        result = Image.new("RGB", rgba.size, background)
        images.append(result)
        alpha = rgba.getchannel("A")
        images.append(alpha)
        result.paste(rgba, mask=alpha)
        return result
    result = image.convert("RGB")
    images.append(result)
    return result


def _resize(
    image: Image.Image, plan: PreprocessPlan, images: list[Image.Image]
) -> Image.Image:
    width, height = image.size
    target_width, target_height = plan.target_size
    if plan.resize_mode == "contain_pad":
        scale = min(target_width / width, target_height / height)
        resized = image.resize(
            (_round(width * scale), _round(height * scale)), Image.Resampling.LANCZOS
        )
        images.append(resized)
        result = Image.new("RGB", plan.target_size, plan.background)
        images.append(result)
        result.paste(
            resized,
            (
                (target_width - resized.width) // 2,
                (target_height - resized.height) // 2,
            ),
        )
        return result
    scale = max(target_width / width, target_height / height)
    resized = image.resize(
        (_round(width * scale), _round(height * scale)), Image.Resampling.LANCZOS
    )
    images.append(resized)
    left = (resized.width - target_width) // 2
    top = (resized.height - target_height) // 2
    result = resized.crop((left, top, left + target_width, top + target_height))
    images.append(result)
    return result


def _encode_png(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=9)
    return output.getvalue()


def _apply_orientation(
    image: Image.Image, orientation: int, images: list[Image.Image]
) -> Image.Image:
    operation = {
        2: Image.Transpose.FLIP_LEFT_RIGHT,
        3: Image.Transpose.ROTATE_180,
        4: Image.Transpose.FLIP_TOP_BOTTOM,
        5: Image.Transpose.TRANSPOSE,
        6: Image.Transpose.ROTATE_270,
        7: Image.Transpose.TRANSVERSE,
        8: Image.Transpose.ROTATE_90,
    }.get(orientation)
    result = image.copy() if operation is None else image.transpose(operation)
    images.append(result)
    return result


def _validate_output_png(content: bytes, target_size: tuple[int, int]) -> None:
    image: Image.Image | None = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(BytesIO(content))
            if (
                image.format != "PNG"
                or getattr(image, "n_frames", 1) != 1
                or image.size != target_size
            ):
                raise DomainError("generated image violates contract")
            image.load()
            if image.mode != "RGB" or not _metadata_absent(image):
                raise DomainError("generated image violates contract")
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise DomainError("generated image violates contract") from error
    except MemoryError as error:
        raise InfrastructureError("image processing failed") from error
    except (DomainError, InfrastructureError):
        raise
    except Exception as error:
        raise InfrastructureError("image processing failed") from error
    finally:
        if image is not None:
            _close_after_primary([image])


@dataclass(frozen=True, slots=True)
class PreprocessPlan:
    target_size: tuple[int, int]
    resize_mode: Literal["contain_pad", "cover_center"]
    background: tuple[int, int, int]
    processor_pin: ResourcePin

    def __post_init__(self) -> None:
        size = _exact_tuple(self.target_size, "target size", 2)
        if any(not 64 <= item <= 4096 or item % 8 for item in size):
            raise DomainError("invalid target size")
        if type(self.resize_mode) is not str or self.resize_mode not in {
            "contain_pad",
            "cover_center",
        }:
            raise DomainError("invalid resize mode")
        background = _exact_tuple(self.background, "background", 3)
        if any(not 0 <= item <= 255 for item in background):
            raise DomainError("invalid background")
        object.__setattr__(
            self, "processor_pin", _rebuild_resource_pin(self.processor_pin)
        )


@dataclass(frozen=True, slots=True)
class PreprocessSnapshot:
    plan: PreprocessPlan
    input_format: Literal["PNG", "JPEG", "WEBP"]
    input_mode: Literal["1", "L", "LA", "P", "RGB", "RGBA", "CMYK"]
    input_size: tuple[int, int]
    exif_orientation: int
    pillow_version: str

    def __post_init__(self) -> None:
        if (
            type(self.plan) is not PreprocessPlan
            or type(self.input_format) is not str
            or type(self.input_mode) is not str
            or self.input_format not in _FORMATS
            or self.input_mode not in _MODES
        ):
            raise DomainError("invalid preprocess snapshot")
        plan = PreprocessPlan(
            self.plan.target_size,
            self.plan.resize_mode,
            self.plan.background,
            self.plan.processor_pin,
        )
        size = _exact_tuple(self.input_size, "input size", 2)
        if (
            any(item < 1 or item > _MAX_EDGE for item in size)
            or size[0] * size[1] > _MAX_PIXELS
        ):
            raise DomainError("invalid input size")
        if (
            type(self.exif_orientation) is not int
            or not 1 <= self.exif_orientation <= 8
        ):
            raise DomainError("invalid EXIF orientation")
        if (
            type(self.pillow_version) is not str
            or not 1 <= len(self.pillow_version) <= 2048
            or self.pillow_version != self.pillow_version.strip()
            or any(ord(char) <= 31 or ord(char) == 127 for char in self.pillow_version)
        ):
            raise DomainError("invalid Pillow version")
        object.__setattr__(self, "plan", plan)


@dataclass(frozen=True, slots=True)
class PreparedImage:
    source: AssetRef
    content: bytes
    snapshot: PreprocessSnapshot
    sha256: Sha256 = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.content) is not bytes
            or type(self.snapshot) is not PreprocessSnapshot
        ):
            raise DomainError("invalid prepared image")
        source = _rebuild_asset_ref(self.source)
        snapshot = PreprocessSnapshot(
            self.snapshot.plan,
            self.snapshot.input_format,
            self.snapshot.input_mode,
            self.snapshot.input_size,
            self.snapshot.exif_orientation,
            self.snapshot.pillow_version,
        )
        _validate_output_png(self.content, snapshot.plan.target_size)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "snapshot", snapshot)
        object.__setattr__(self, "sha256", hash_bytes(self.content))

    @property
    def width(self) -> int:
        return self.snapshot.plan.target_size[0]

    @property
    def height(self) -> int:
        return self.snapshot.plan.target_size[1]

    @property
    def mode(self) -> Literal["RGB"]:
        return "RGB"

    @property
    def format(self) -> Literal["PNG"]:
        return "PNG"


def preprocess_image(
    encoded: bytes, source: AssetRef, plan: PreprocessPlan
) -> PreparedImage:
    """Inspect, normalize, and encode input with fixed PNG settings."""
    if type(encoded) is not bytes or not 1 <= len(encoded) <= _MAX_BYTES:
        raise DomainError("invalid preprocess input")
    source = _rebuild_asset_ref(source)
    plan = (
        PreprocessPlan(
            plan.target_size, plan.resize_mode, plan.background, plan.processor_pin
        )
        if type(plan) is PreprocessPlan
        else (_ for _ in ()).throw(DomainError("invalid preprocess input"))
    )
    if hash_bytes(encoded) != source.sha256:
        raise DomainError("input hash does not match source")
    verified_details = _verify_input(encoded)
    image, loaded_details = _load_checked(encoded)
    images = [image]
    try:
        if loaded_details != verified_details:
            raise DomainError("input image changed between verification and load")
        fmt, mode, size, orientation = loaded_details
        transposed = _apply_orientation(image, orientation, images)
        normalized = _to_rgb(transposed, plan.background, images)
        content = _encode_png(_resize(normalized, plan, images))
    except MemoryError as error:
        raise InfrastructureError("image processing failed") from error
    except (OSError, ValueError) as error:
        raise DomainError("invalid input image") from error
    except (DomainError, InfrastructureError):
        raise
    except Exception as error:
        raise InfrastructureError("image processing failed") from error
    finally:
        _close_after_primary(images)
    snapshot = PreprocessSnapshot(plan, fmt, mode, size, orientation, Image.__version__)  # type: ignore[arg-type]
    return PreparedImage(source, content, snapshot)
