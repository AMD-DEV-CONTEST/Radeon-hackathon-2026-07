"""Private, owner-agnostic image-evidence validation and tensor helpers."""

from __future__ import annotations

import hashlib as _hashlib
import json as _json
import math as _math
from dataclasses import dataclass as _dataclass
from enum import Enum as _Enum
from io import BytesIO as _BytesIO
from typing import TYPE_CHECKING as _TYPE_CHECKING, Any as _Any

from PIL import Image as _Image

from specstyle.domain.identifiers import Sha256 as _Sha256
from specstyle.errors import DomainError as _DomainError
from specstyle.errors import InfrastructureError as _InfrastructureError

if _TYPE_CHECKING:
    import torch as _torch_types

__all__ = ()

_CLIP_IMAGE_MEAN = (0.48145466, 0.4578275, 0.40821073)
_CLIP_IMAGE_STD = (0.26862954, 0.26130258, 0.27577711)
_PROCESSOR_PROVENANCE_SCHEMA = "specstyle.processor_provenance.v1"
_PREPROCESSING_VERSION_PREFIX = "specstyle.clip_image_processor.v1.sha256."
_EVIDENCE_CONTRACT_ERROR = "image evidence contract violation"


def _is_safe_text(value: object) -> bool:
    return (
        type(value) is str
        and 1 <= len(value) <= 2048
        and value == value.strip()
        and all(31 < ord(character) != 127 for character in value)
    )


@_dataclass(frozen=True, slots=True)
class _ProcessorProvenance:
    transformers_version: str
    class_fqname: str
    config_sha256: _Sha256

    def __post_init__(self) -> None:
        if (
            not _is_safe_text(self.transformers_version)
            or not _is_safe_text(self.class_fqname)
            or type(self.config_sha256) is not _Sha256
        ):
            raise _InfrastructureError("invalid processor provenance")


@_dataclass(frozen=True, slots=True)
class _VerifiedImageEvidence:
    asset_sha256: _Sha256
    patch_hidden_state: _torch_types.Tensor
    projected_embedding: _torch_types.Tensor


def _normalize_processor_config(value: object) -> object:
    if isinstance(value, _Enum):
        return _normalize_processor_config(value.value)
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if _math.isfinite(value):
            return value
        raise _InfrastructureError("invalid processor config")
    if type(value) in (list, tuple):
        return [_normalize_processor_config(item) for item in value]
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise _InfrastructureError("invalid processor config")
        return {key: _normalize_processor_config(item) for key, item in value.items()}
    raise _InfrastructureError("invalid processor config")


def _canonical_json_bytes(value: object) -> bytes:
    normalized = _normalize_processor_config(value)
    return _json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _build_processor_provenance(
    transformers: _Any, processor: _Any, installed_version: object
) -> _ProcessorProvenance:
    version = getattr(transformers, "__version__", None)
    processor_type = type(processor)
    module = getattr(processor_type, "__module__", None)
    qualname = getattr(processor_type, "__qualname__", None)
    if (
        not _is_safe_text(version)
        or not _is_safe_text(installed_version)
        or version != installed_version
        or type(module) is not str
        or type(qualname) is not str
    ):
        raise _InfrastructureError("invalid processor provenance")
    fqname = f"{module}.{qualname}"
    if not _is_safe_text(fqname) or fqname.split(".", 1)[0] != "transformers":
        raise _InfrastructureError("invalid processor provenance")
    config = processor.to_dict()
    if type(config) is not dict:
        raise _InfrastructureError("invalid processor provenance")
    config_sha256 = _Sha256(_hashlib.sha256(_canonical_json_bytes(config)).hexdigest())
    return _ProcessorProvenance(version, fqname, config_sha256)


def _derive_preprocessing_version(provenance: _ProcessorProvenance) -> str:
    identity = {
        "schema": _PROCESSOR_PROVENANCE_SCHEMA,
        "transformers_version": provenance.transformers_version,
        "class_fqname": provenance.class_fqname,
        "config_sha256": provenance.config_sha256.value,
    }
    digest = _hashlib.sha256(_canonical_json_bytes(identity)).hexdigest()
    return f"{_PREPROCESSING_VERSION_PREFIX}{digest}"


def _valid_clip_statistics(value: object, expected: tuple[float, ...]) -> bool:
    return (
        type(value) in (list, tuple)
        and len(value) == 3
        and all(type(item) is float and _math.isfinite(item) for item in value)
        and tuple(value) == expected
    )


def _validate_image_processor(processor: _Any, encoder: _Any) -> None:
    image_size = getattr(getattr(encoder, "config", None), "image_size", None)
    if type(image_size) is not int or image_size <= 0:
        raise _InfrastructureError("pipeline loading failed")
    if (
        type(getattr(processor, "size", None)) is not dict
        or processor.size != {"shortest_edge": image_size}
        or type(getattr(processor, "crop_size", None)) is not dict
        or processor.crop_size != {"height": image_size, "width": image_size}
        or getattr(processor, "do_resize", None) is not True
        or getattr(processor, "do_center_crop", None) is not True
        or getattr(processor, "do_rescale", None) is not True
        or getattr(processor, "do_normalize", None) is not True
        or getattr(processor, "do_convert_rgb", None) is not True
        or getattr(processor, "resample", None) != _Image.Resampling.BICUBIC
        or type(getattr(processor, "rescale_factor", None)) is not float
        or processor.rescale_factor != 1 / 255
        or not _valid_clip_statistics(
            getattr(processor, "image_mean", None), _CLIP_IMAGE_MEAN
        )
        or not _valid_clip_statistics(
            getattr(processor, "image_std", None), _CLIP_IMAGE_STD
        )
    ):
        raise _InfrastructureError("pipeline loading failed")


def _encoder_placement(encoder: _Any, torch: _Any) -> tuple[_Any, _Any]:
    try:
        parameters = encoder.parameters()
        first = next(parameters)
        device, dtype = first.device, first.dtype
        valid = (
            type(device) is torch.device
            and device == torch.device("cuda:0")
            and dtype is torch.float16
        )
        for parameter in parameters:
            valid = valid and (
                type(parameter.device) is torch.device
                and parameter.device == device
                and parameter.dtype is dtype
            )
        for buffer in encoder.buffers():
            floating = buffer.is_floating_point()
            valid = valid and (
                type(buffer.device) is torch.device
                and buffer.device == device
                and type(floating) is bool
                and (floating is False or buffer.dtype is dtype)
            )
    except Exception:
        valid = False
    if not valid:
        raise _InfrastructureError(_EVIDENCE_CONTRACT_ERROR)
    return device, dtype


def _validate_frozen_encoder_placement(
    encoder: _Any, torch: _Any, frozen_device: _Any, frozen_dtype: _Any
) -> None:
    device, dtype = _encoder_placement(encoder, torch)
    if (
        type(frozen_device) is not torch.device
        or device != frozen_device
        or dtype is not frozen_dtype
    ):
        raise _InfrastructureError(_EVIDENCE_CONTRACT_ERROR)


def _decode_image_evidence_input(
    image_bytes: object, asset_sha256: object
) -> _Image.Image:
    if (
        type(image_bytes) is not bytes
        or type(asset_sha256) is not _Sha256
        or _Sha256(_hashlib.sha256(image_bytes).hexdigest()) != asset_sha256
    ):
        raise _DomainError("invalid image evidence input")
    image = None
    invalid = False
    try:
        image = _Image.open(_BytesIO(image_bytes))
        if getattr(image, "n_frames", None) != 1 or image.mode != "RGB":
            invalid = True
        else:
            image.load()
    except Exception:
        invalid = True
    if invalid:
        if image is not None:
            _close_image_quietly(image)
        raise _DomainError("invalid image evidence input")
    return image


def _close_image_quietly(image: _Image.Image) -> None:
    try:
        image.close()
    except Exception:
        pass


def _tensor_shape(value: object) -> tuple[int, ...] | None:
    try:
        shape = tuple(value.shape)
        return shape if all(type(item) is int and item >= 0 for item in shape) else None
    except Exception:
        return None


def _tensor_is_finite(torch: _Any, value: _Any) -> bool:
    try:
        return torch.isfinite(value).all().item() is True
    except Exception:
        return False


def _tensor_has_contract(
    value: _Any,
    torch: _Any,
    shape: tuple[int, ...],
    device: _Any,
    dtype: _Any,
    *,
    values: bool,
) -> bool:
    try:
        return (
            type(value) is torch.Tensor
            and _tensor_shape(value) == shape
            and type(value.device) is torch.device
            and value.device == device
            and value.dtype is dtype
            and (not values or value.is_contiguous() is True)
            and (not values or value.requires_grad is False)
            and (not values or _tensor_is_finite(torch, value))
        )
    except Exception:
        return False


def _processor_pixel_values(result: object, image_size: int, torch: _Any) -> _Any:
    pixel_values = getattr(result, "pixel_values", None)
    expected_shape = (1, 3, image_size, image_size)
    if not _tensor_has_contract(
        pixel_values,
        torch,
        expected_shape,
        torch.device("cpu"),
        torch.float32,
        values=True,
    ):
        raise _InfrastructureError(_EVIDENCE_CONTRACT_ERROR)
    return pixel_values


def _owned_cpu_float32(value: _Any, torch: _Any, shape: tuple[int, ...]) -> _Any:
    detached = value.detach()
    transferred = detached.to(device=torch.device("cpu"), dtype=torch.float32)
    contiguous = transferred.contiguous()
    result = contiguous.clone()
    try:
        valid = (
            result is not contiguous
            and result.data_ptr() != contiguous.data_ptr()
            and _tensor_has_contract(
                result,
                torch,
                shape,
                torch.device("cpu"),
                torch.float32,
                values=True,
            )
        )
    except Exception:
        valid = False
    if not valid:
        raise _InfrastructureError(_EVIDENCE_CONTRACT_ERROR)
    return result


def _validated_encoder_tensors(
    result: object, torch: _Any, frozen_device: _Any, frozen_dtype: _Any
) -> tuple[_Any, _Any]:
    hidden_states = getattr(result, "hidden_states", None)
    projected = getattr(result, "image_embeds", None)
    if type(hidden_states) is not tuple or len(hidden_states) < 2:
        raise _InfrastructureError(_EVIDENCE_CONTRACT_ERROR)
    hidden = hidden_states[-2]
    hidden_shape = _tensor_shape(hidden)
    projected_shape = _tensor_shape(projected)
    if (
        type(hidden) is not torch.Tensor
        or type(projected) is not torch.Tensor
        or type(hidden.device) is not torch.device
        or hidden.device != frozen_device
        or hidden.dtype is not frozen_dtype
        or type(projected.device) is not torch.device
        or projected.device != frozen_device
        or projected.dtype is not frozen_dtype
        or hidden_shape is None
        or len(hidden_shape) != 3
        or hidden_shape[0] != 1
        or hidden_shape[1] < 2
        or hidden_shape[2] < 1
        or projected_shape is None
        or len(projected_shape) != 2
        or projected_shape[0] != 1
        or projected_shape[1] < 1
    ):
        raise _InfrastructureError(_EVIDENCE_CONTRACT_ERROR)
    patch = _owned_cpu_float32(
        hidden[0, 1:, :], torch, (hidden_shape[1] - 1, hidden_shape[2])
    )
    projected = _owned_cpu_float32(projected[0], torch, (projected_shape[1],))
    return patch, projected


def _validate_evidence_tensor_values(patch: _Any, projected: _Any, torch: _Any) -> None:
    try:
        patch_valid = (
            _tensor_is_finite(torch, patch)
            and torch.linalg.vector_norm(patch).item() > 0
        )
        projected_valid = (
            _tensor_is_finite(torch, projected)
            and torch.linalg.vector_norm(projected).item() > 0
        )
    except Exception:
        patch_valid = projected_valid = False
    if not patch_valid or not projected_valid:
        raise _InfrastructureError(_EVIDENCE_CONTRACT_ERROR)


def _run_image_evidence_encoder(
    processor: _Any,
    encoder: _Any,
    torch: _Any,
    frozen_device: _Any,
    frozen_dtype: _Any,
    image: _Image.Image,
) -> tuple[_Any, _Any]:
    processed = processor(images=image, return_tensors="pt")
    image_size = encoder.config.image_size
    pixel_values = _processor_pixel_values(processed, image_size, torch)
    with torch.inference_mode():
        _validate_frozen_encoder_placement(encoder, torch, frozen_device, frozen_dtype)
        encoder_pixels = pixel_values.to(device=frozen_device, dtype=frozen_dtype)
        if not _tensor_has_contract(
            encoder_pixels,
            torch,
            (1, 3, image_size, image_size),
            frozen_device,
            frozen_dtype,
            values=True,
        ):
            raise _InfrastructureError(_EVIDENCE_CONTRACT_ERROR)
        result = encoder(encoder_pixels, output_hidden_states=True, return_dict=True)
    patch, projected = _validated_encoder_tensors(
        result, torch, frozen_device, frozen_dtype
    )
    _validate_evidence_tensor_values(patch, projected, torch)
    return patch, projected


def _is_torch_oom(error: BaseException, torch: _Any) -> bool:
    candidates = (
        getattr(torch, "OutOfMemoryError", None),
        getattr(getattr(torch, "cuda", None), "OutOfMemoryError", None),
    )
    classes = tuple(item for item in candidates if isinstance(item, type))
    return bool(classes) and isinstance(error, classes)


def _classify_encoding_failure(error: BaseException, torch: _Any) -> str:
    if _is_torch_oom(error, torch):
        return "oom"
    if type(error) is _InfrastructureError and str(error) == _EVIDENCE_CONTRACT_ERROR:
        return "contract"
    return "runtime"
