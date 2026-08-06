from __future__ import annotations

from dataclasses import dataclass
from functools import cache

import numpy as np
import PyOpenColorIO as ocio
import torch

from colorgraph.domain.grade_graph import ColorSpace
from colorgraph.grading.aces2_gpu import (
    ACES2_GPU_IMPLEMENTATION,
    apply_aces2_output_transform,
    apply_ocio_color_space_gpu,
)
from colorgraph.grading.color import (
    DJI_DLOG_DGAMUT,
    DJI_MAVIC3_DLOG_REC709,
    SONY_SLOG3_SGAMUT3CINE,
    convert_color_space,
)

OCIO_CONFIG_NAME = "studio-config-v4.0.0_aces-v2.0_ocio-v2.5"
OCIO_CONFIG_URI = f"ocio://{OCIO_CONFIG_NAME}"
OCIO_PIPELINE_SCHEMA = "colorgraph.ocio-aces-pipeline/v1"
ACES_VERSION = "2.0"

OCIO_ACES2065_1 = "ACES2065-1"
OCIO_ACESCG = "ACEScg"
OCIO_ACESCCT = "ACEScct"
OCIO_LINEAR_REC709 = "Linear Rec.709 (sRGB)"
OCIO_SRGB = "sRGB Encoded Rec.709 (sRGB)"
ACES2_SDR_VIEW = "ACES 2.0 - SDR 100 nits (Rec.709)"


class OcioPipelineError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OcioDisplayTarget:
    output_space: ColorSpace
    display: str
    view: str = ACES2_SDR_VIEW


OCIO_DISPLAY_TARGETS = {
    ColorSpace.SRGB: OcioDisplayTarget(
        output_space=ColorSpace.SRGB,
        display="sRGB - Display",
    ),
    ColorSpace.REC1886: OcioDisplayTarget(
        output_space=ColorSpace.REC1886,
        display="Rec.1886 Rec.709 - Display",
    ),
}

_DIRECT_INPUT_SPACES = {
    ColorSpace.SRGB: OCIO_SRGB,
    ColorSpace.LINEAR_REC709: OCIO_LINEAR_REC709,
    ColorSpace.ACES2065_1: OCIO_ACES2065_1,
    ColorSpace.ACESCG: OCIO_ACESCG,
    ColorSpace.ACESCCT: OCIO_ACESCCT,
}

_LOG_INPUT_SPACES = {
    SONY_SLOG3_SGAMUT3CINE: "S-Log3 S-Gamut3.Cine",
    DJI_DLOG_DGAMUT: "D-Log D-Gamut",
    # The v2 profile used DJI's display LUT. ACES projects instead use the
    # official D-Log/D-Gamut camera input transform and reserve the display
    # rendering for the ACES 2 Output Transform.
    DJI_MAVIC3_DLOG_REC709: "D-Log D-Gamut",
}


@cache
def ocio_config() -> ocio.Config:
    if not ocio.__version__.startswith("2.5."):
        raise OcioPipelineError(
            f"ColorGraph requires PyOpenColorIO 2.5.x, found {ocio.__version__}"
        )
    config = ocio.Config.CreateFromBuiltinConfig(OCIO_CONFIG_NAME)
    config.validate()
    return config


@cache
def _color_processor(source: str, destination: str) -> ocio.Processor:
    try:
        return ocio_config().getProcessor(source, destination)
    except Exception as exc:  # pragma: no cover - OCIO supplies the detailed cause
        raise OcioPipelineError(
            f"OCIO color-space processor is unavailable: {source!r} -> {destination!r}"
        ) from exc


@cache
def _display_processor(source: str, display: str, view: str) -> ocio.Processor:
    try:
        return ocio_config().getProcessor(
            source,
            display,
            view,
            ocio.TRANSFORM_DIR_FORWARD,
        )
    except Exception as exc:  # pragma: no cover - OCIO supplies the detailed cause
        raise OcioPipelineError(
            f"OCIO display processor is unavailable: {source!r} -> {display!r} / {view!r}"
        ) from exc


def _apply_cpu_processor(image: torch.Tensor, processor: ocio.Processor) -> torch.Tensor:
    if image.ndim != 4 or image.shape[1] != 3:
        raise ValueError("OCIO tensors must use NCHW layout with three RGB channels")
    if image.numel() == 0:
        return image.to(dtype=torch.float32)

    device = image.device
    height, width = image.shape[-2:]
    packed = (
        image.detach()
        .to(device="cpu", dtype=torch.float32)
        .permute(0, 2, 3, 1)
        .contiguous()
        .numpy()
    )
    pixels = np.ascontiguousarray(packed.reshape(-1, 3))
    processor.getDefaultCPUProcessor().applyRGB(pixels)
    output = (
        torch.from_numpy(pixels.reshape(image.shape[0], height, width, 3))
        .permute(0, 3, 1, 2)
        .contiguous()
    )
    return output.to(device=device, dtype=torch.float32, non_blocking=True)


def apply_ocio_color_space(
    image: torch.Tensor,
    source: str,
    destination: str,
) -> torch.Tensor:
    if image.device.type == "cuda":
        return apply_ocio_color_space_gpu(image, source, destination)
    return _apply_cpu_processor(image, _color_processor(source, destination))


def apply_ocio_display(
    image_aces2065_1: torch.Tensor,
    *,
    display: str,
    view: str,
) -> torch.Tensor:
    if image_aces2065_1.device.type == "cuda":
        encodings = {
            "sRGB - Display": "srgb",
            "Rec.1886 Rec.709 - Display": "rec1886",
        }
        try:
            encoding = encodings[display]
        except KeyError as exc:
            raise ValueError(
                f"unsupported native GPU ACES 2 display: {display!r}"
            ) from exc
        return apply_aces2_output_transform(
            image_aces2065_1,
            processor=_display_processor(OCIO_ACES2065_1, display, view),
            encoding=encoding,  # type: ignore[arg-type]
        )
    return _apply_cpu_processor(
        image_aces2065_1,
        _display_processor(OCIO_ACES2065_1, display, view),
    )


def resolve_display_target(
    output_space: ColorSpace | str,
    *,
    display: str | None = None,
    view: str | None = None,
) -> OcioDisplayTarget:
    try:
        explicit_output = (
            output_space if isinstance(output_space, ColorSpace) else ColorSpace(output_space)
        )
    except ValueError as exc:
        raise ValueError(f"unknown ACES output color space: {output_space!r}") from exc
    try:
        target = OCIO_DISPLAY_TARGETS[explicit_output]
    except KeyError as exc:
        supported = ", ".join(space.value for space in OCIO_DISPLAY_TARGETS)
        raise ValueError(
            f"ACES 2 output requires one of the display encodings: {supported}"
        ) from exc
    if display is not None and display != target.display:
        raise ValueError(
            f"output space {explicit_output.value!r} requires display {target.display!r}"
        )
    if view is not None and view != target.view:
        raise ValueError(f"output space {explicit_output.value!r} requires view {target.view!r}")
    return target


def _resolve_input(
    image: torch.Tensor,
    input_space: ColorSpace | str,
    source_log_profile: str | None,
) -> tuple[torch.Tensor, str, str | None]:
    try:
        explicit_input = (
            input_space if isinstance(input_space, ColorSpace) else ColorSpace(input_space)
        )
    except ValueError as exc:
        raise ValueError(f"unknown ACES input color space: {input_space!r}") from exc

    if explicit_input == ColorSpace.LOG:
        if source_log_profile not in _LOG_INPUT_SPACES:
            supported = ", ".join(sorted(_LOG_INPUT_SPACES))
            raise ValueError(
                "ACES camera input requires a supported source_log_profile; "
                f"expected one of: {supported}"
            )
        return image.to(dtype=torch.float32), _LOG_INPUT_SPACES[source_log_profile], None

    if source_log_profile is not None:
        raise ValueError("source_log_profile is only valid for log input")
    if explicit_input in {ColorSpace.BT709_OETF, ColorSpace.REC1886}:
        linear = convert_color_space(
            image,
            explicit_input,
            ColorSpace.LINEAR_REC709,
        )
        return linear, OCIO_LINEAR_REC709, f"colorgraph.{explicit_input.value}-decode/v1"
    if explicit_input == ColorSpace.REC709:
        raise ValueError(
            "ambiguous legacy color space 'rec709'; use 'bt709_oetf', 'rec1886', or 'srgb'"
        )
    try:
        return image.to(dtype=torch.float32), _DIRECT_INPUT_SPACES[explicit_input], None
    except KeyError as exc:  # pragma: no cover - enum exhaustiveness guard
        raise ValueError(f"unsupported ACES input color space: {explicit_input.value}") from exc


def input_to_acescg(
    image: torch.Tensor,
    input_space: ColorSpace | str,
    *,
    source_log_profile: str | None = None,
) -> torch.Tensor:
    prepared, ocio_input, _ = _resolve_input(image, input_space, source_log_profile)
    aces2065_1 = apply_ocio_color_space(prepared, ocio_input, OCIO_ACES2065_1)
    return apply_ocio_color_space(aces2065_1, OCIO_ACES2065_1, OCIO_ACESCG)


def acescg_to_output(
    image_acescg: torch.Tensor,
    output_space: ColorSpace | str,
    *,
    display: str | None = None,
    view: str | None = None,
) -> torch.Tensor:
    target = resolve_display_target(output_space, display=display, view=view)
    aces2065_1 = apply_ocio_color_space(
        image_acescg,
        OCIO_ACESCG,
        OCIO_ACES2065_1,
    )
    return apply_ocio_display(
        aces2065_1,
        display=target.display,
        view=target.view,
    )


def ocio_pipeline_metadata(
    input_space: ColorSpace | str,
    *,
    source_log_profile: str | None,
    output_space: ColorSpace | str,
) -> dict[str, object]:
    probe = torch.zeros((1, 3, 1, 1), dtype=torch.float32)
    _, ocio_input, predecode = _resolve_input(probe, input_space, source_log_profile)
    target = resolve_display_target(output_space)
    input_to_interchange = _color_processor(ocio_input, OCIO_ACES2065_1)
    interchange_to_working = _color_processor(OCIO_ACES2065_1, OCIO_ACESCG)
    working_to_interchange = _color_processor(OCIO_ACESCG, OCIO_ACES2065_1)
    output_processor = _display_processor(
        OCIO_ACES2065_1,
        target.display,
        target.view,
    )
    return {
        "schema": OCIO_PIPELINE_SCHEMA,
        "ocio_version": ocio.__version__,
        "config": OCIO_CONFIG_NAME,
        "config_uri": OCIO_CONFIG_URI,
        "config_cache_id": ocio_config().getCacheID(),
        "aces_version": ACES_VERSION,
        "input_color_space": ocio_input,
        "input_predecode": predecode,
        "interchange_space": OCIO_ACES2065_1,
        "scene_linear_space": OCIO_ACESCG,
        "creative_space": OCIO_ACESCCT,
        "display": target.display,
        "view": target.view,
        "processor_cache_ids": {
            "input_to_interchange": input_to_interchange.getCacheID(),
            "interchange_to_working": interchange_to_working.getCacheID(),
            "working_to_interchange": working_to_interchange.getCacheID(),
            "output": output_processor.getCacheID(),
        },
        "execution_policy": {
            "cpu": "PyOpenColorIO CPU processor",
            "accelerator": ACES2_GPU_IMPLEMENTATION,
            "per_frame_accelerator_to_cpu_roundtrip": False,
        },
    }
