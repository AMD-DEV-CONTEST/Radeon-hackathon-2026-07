from __future__ import annotations

import json
import re
from collections.abc import Callable
from fractions import Fraction
from typing import Any

from colorgraph.domain.grade_graph import (
    Chromaticity,
    ColorSpace,
    ContentLightMetadata,
    HDRMetadata,
    MasteringDisplayMetadata,
    MediaInfo,
    MediaMetadataEvidence,
    MetadataConfidence,
    MetadataEvidence,
    MetadataSource,
)

_UNKNOWN_VALUES = {"", "n/a", "none", "reserved", "unknown", "unspecified"}
_COLOR_ALIASES = {
    "bt.709": "bt709",
    "rec.709": "bt709",
    "rec709": "bt709",
    "bt2020-ncl": "bt2020nc",
    "bt2020-non-constant": "bt2020nc",
    "bt2020-cl": "bt2020c",
    "pq": "smpte2084",
    "hlg": "arib-std-b67",
}
_RANGE_ALIASES = {
    "tv": "limited",
    "mpeg": "limited",
    "limited": "limited",
    "pc": "full",
    "jpeg": "full",
    "full": "full",
}
_TRANSFER_FAMILIES = {
    "iec61966-2-1": "srgb",
    "bt709": "bt709",
    "linear": "linear",
    "smpte2084": "pq",
    "arib-std-b67": "hlg",
}
_EXPECTED_TRANSFER_FAMILY = {
    ColorSpace.SRGB: "srgb",
    ColorSpace.BT709_OETF: "bt709",
    # Video files carrying a Rec.1886 display image normally signal the
    # corresponding BT.709 source transfer characteristic.
    ColorSpace.REC1886: "bt709",
    ColorSpace.LINEAR_REC709: "linear",
    ColorSpace.ACES2065_1: "linear",
    ColorSpace.ACESCG: "linear",
    ColorSpace.ACESCCT: "acescct",
    ColorSpace.LOG: "log",
}
_HDR_SIDE_DATA_MARKERS = (
    "mastering display",
    "content light",
    "hdr dynamic",
    "hdr10+",
    "smpte2094",
    "dolby vision",
    "dovi",
    "ambient viewing",
)


def _clean_string(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if cleaned.casefold() in _UNKNOWN_VALUES:
        return None
    return cleaned


def _normalize_color_value(value: object) -> str | None:
    cleaned = _clean_string(value)
    if cleaned is None:
        return None
    normalized = cleaned.casefold().replace("_", "-")
    return _COLOR_ALIASES.get(normalized, normalized)


def _normalize_range(value: object) -> str | None:
    cleaned = _clean_string(value)
    if cleaned is None:
        return None
    return _RANGE_ALIASES.get(cleaned.casefold())


def _metadata_tags(
    video_stream: dict[str, Any],
    format_info: dict[str, Any],
) -> list[tuple[str, object]]:
    tagged: list[tuple[str, object]] = []
    for label, owner in (("stream.tags", video_stream), ("format.tags", format_info)):
        tags = owner.get("tags")
        if not isinstance(tags, dict):
            continue
        tagged.extend((f"{label}.{key}", value) for key, value in tags.items())
    return tagged


def _declared_string(
    video_stream: dict[str, Any],
    format_info: dict[str, Any],
    *,
    field: str,
    tag_aliases: set[str],
    normalizer: Callable[[object], str | None] = _normalize_color_value,
) -> tuple[str | None, MetadataEvidence]:
    observations: list[tuple[MetadataSource, str, object, str | None]] = []
    if field in video_stream:
        raw = video_stream.get(field)
        observations.append(
            (MetadataSource.STREAM, f"stream.{field}", raw, normalizer(raw))
        )
    folded_aliases = {alias.casefold() for alias in tag_aliases}
    for label, raw in _metadata_tags(video_stream, format_info):
        if label.rsplit(".", 1)[-1].casefold() in folded_aliases:
            observations.append((MetadataSource.CONTAINER, label, raw, normalizer(raw)))

    valid = [observation for observation in observations if observation[3] is not None]
    direct = next(
        (observation for observation in valid if observation[0] == MetadataSource.STREAM),
        None,
    )
    chosen = direct or (valid[0] if valid else None)
    reported = [
        f"{label}={raw}"
        for _, label, raw, _ in observations
        if _clean_string(raw) is not None
    ]
    normalized_values = {str(observation[3]) for observation in valid}
    conflict = len(normalized_values) > 1
    if chosen is None:
        return None, MetadataEvidence(
            reported_values=reported,
            note="ffprobe did not report a usable value",
        )

    source = chosen[0]
    note = (
        "conflicting declarations; the video stream value was retained"
        if conflict and source == MetadataSource.STREAM
        else "conflicting container declarations; the first usable value was retained"
        if conflict
        else None
    )
    return str(chosen[3]), MetadataEvidence(
        source=source,
        confidence=(
            MetadataConfidence.HIGH
            if source == MetadataSource.STREAM
            else MetadataConfidence.MEDIUM
        ),
        reported_values=reported,
        conflict=conflict,
        note=note,
    )


def _positive_int(value: object) -> int | None:
    cleaned = _clean_string(value)
    if cleaned is None:
        return None
    try:
        parsed = int(cleaned)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _nonnegative_int(value: object) -> int | None:
    cleaned = _clean_string(value)
    if cleaned is None:
        return None
    try:
        parsed = int(cleaned)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _infer_bit_depth(pixel_format: str | None) -> int | None:
    if pixel_format is None:
        return None
    value = pixel_format.casefold()
    explicit = re.search(r"(?:p|gray)(9|10|12|14|16)(?:le|be)?$", value)
    if explicit:
        return int(explicit.group(1))
    packed_planar = re.match(r"^p[012](10|12|16)(?:le|be)?$", value)
    if packed_planar:
        return int(packed_planar.group(1))
    if value in {"v210", "x2rgb10le", "x2bgr10le"} or value.startswith("y210"):
        return 10
    if value.startswith(("rgb48", "bgr48", "rgba64", "bgra64", "ya16", "xyz12")):
        return 12 if value.startswith("xyz12") else 16
    if value.startswith(
        (
            "yuv",
            "yuva",
            "gbr",
            "rgb",
            "bgr",
            "nv12",
            "nv21",
            "gray",
            "mono",
        )
    ):
        return 8
    return None


def _bit_depth(
    video_stream: dict[str, Any],
    pixel_format: str | None,
) -> tuple[int | None, MetadataEvidence]:
    observations: list[tuple[str, int]] = []
    for field in ("bits_per_raw_sample", "bits_per_component"):
        parsed = _positive_int(video_stream.get(field))
        if parsed is not None and parsed <= 64:
            observations.append((f"stream.{field}", parsed))
    inferred = _infer_bit_depth(pixel_format)
    reported = [f"{label}={value}" for label, value in observations]
    if inferred is not None and pixel_format is not None:
        reported.append(f"stream.pix_fmt={pixel_format} -> {inferred}")

    if observations:
        chosen = observations[0][1]
        values = {value for _, value in observations}
        if inferred is not None:
            values.add(inferred)
        conflict = len(values) > 1
        return chosen, MetadataEvidence(
            source=MetadataSource.STREAM,
            confidence=MetadataConfidence.HIGH,
            reported_values=reported,
            conflict=conflict,
            note=(
                "declared sample depth conflicts with the decoded pixel format"
                if conflict
                else None
            ),
        )
    if inferred is not None:
        return inferred, MetadataEvidence(
            source=MetadataSource.PIXEL_FORMAT,
            confidence=MetadataConfidence.MEDIUM,
            reported_values=reported,
            note="inferred from ffprobe pixel format",
        )
    return None, MetadataEvidence(note="sample depth is unavailable")


def _infer_chroma_subsampling(pixel_format: str | None) -> str | None:
    if pixel_format is None:
        return None
    value = pixel_format.casefold()
    planar = re.search(r"(?:yuvj?|yuva)(420|422|444|440|411|410)", value)
    if planar:
        return {
            "420": "4:2:0",
            "422": "4:2:2",
            "444": "4:4:4",
            "440": "4:4:0",
            "411": "4:1:1",
            "410": "4:1:0",
        }[planar.group(1)]
    if value.startswith(("nv12", "nv21", "p010", "p012", "p016")):
        return "4:2:0"
    if value.startswith(("nv16", "nv20", "p210", "p212", "p216", "y210", "v210")):
        return "4:2:2"
    if value.startswith(("gbr", "rgb", "bgr", "xyz", "ayuv")):
        return "4:4:4"
    if value.startswith(("gray", "mono")):
        return "4:0:0"
    return None


def _chroma_subsampling(
    pixel_format: str | None,
) -> tuple[str | None, MetadataEvidence]:
    inferred = _infer_chroma_subsampling(pixel_format)
    if inferred is None:
        return None, MetadataEvidence(note="chroma subsampling is unavailable")
    return inferred, MetadataEvidence(
        source=MetadataSource.PIXEL_FORMAT,
        confidence=MetadataConfidence.MEDIUM,
        reported_values=[f"stream.pix_fmt={pixel_format} -> {inferred}"],
        note="inferred from ffprobe pixel format",
    )


def _fraction(value: object) -> float | None:
    cleaned = _clean_string(value)
    if cleaned is None:
        return None
    try:
        return float(Fraction(cleaned))
    except (ValueError, ZeroDivisionError):
        return None


def _mastering_display(item: dict[str, Any]) -> MasteringDisplayMetadata | None:
    values = {
        key: _fraction(item.get(key))
        for key in (
            "red_x",
            "red_y",
            "green_x",
            "green_y",
            "blue_x",
            "blue_y",
            "white_point_x",
            "white_point_y",
            "min_luminance",
            "max_luminance",
        )
    }
    if any(value is None for value in values.values()):
        return None
    try:
        return MasteringDisplayMetadata(
            red=Chromaticity(x=values["red_x"], y=values["red_y"]),
            green=Chromaticity(x=values["green_x"], y=values["green_y"]),
            blue=Chromaticity(x=values["blue_x"], y=values["blue_y"]),
            white_point=Chromaticity(
                x=values["white_point_x"],
                y=values["white_point_y"],
            ),
            min_luminance=values["min_luminance"],
            max_luminance=values["max_luminance"],
        )
    except ValueError:
        return None


def _content_light(item: dict[str, Any]) -> ContentLightMetadata | None:
    max_content = _nonnegative_int(
        item.get("max_content", item.get("max_cll", item.get("max_content_light_level")))
    )
    max_average = _nonnegative_int(
        item.get(
            "max_average",
            item.get("max_fall", item.get("max_frame_average_light_level")),
        )
    )
    if max_content is None or max_average is None:
        return None
    return ContentLightMetadata(
        max_content_light_level=max_content,
        max_frame_average_light_level=max_average,
    )


def _side_data_items(
    video_stream: dict[str, Any],
    frames: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    owners: list[dict[str, Any]] = [video_stream, *frames]
    for owner in owners:
        side_data = owner.get("side_data_list")
        if not isinstance(side_data, list):
            continue
        items.extend(item for item in side_data if isinstance(item, dict))
    return items


def _unique_models(values: list[Any]) -> list[Any]:
    unique: dict[str, Any] = {}
    for value in values:
        if value is None:
            continue
        key = value.model_dump_json() if hasattr(value, "model_dump_json") else json.dumps(value)
        unique.setdefault(key, value)
    return list(unique.values())


def _hdr_metadata(
    video_stream: dict[str, Any],
    frames: list[dict[str, Any]],
    color_transfer: str | None,
) -> tuple[HDRMetadata, MetadataEvidence]:
    items = _side_data_items(video_stream, frames)
    hdr_items: list[dict[str, Any]] = []
    for item in items:
        side_data_type = str(item.get("side_data_type") or "")
        folded = side_data_type.casefold()
        if any(marker in folded for marker in _HDR_SIDE_DATA_MARKERS):
            hdr_items.append(item)

    side_data_types = list(
        dict.fromkeys(str(item.get("side_data_type") or "unknown") for item in hdr_items)
    )
    mastering_values = _unique_models(
        [
            _mastering_display(item)
            for item in hdr_items
            if "mastering display" in str(item.get("side_data_type") or "").casefold()
        ]
    )
    content_values = _unique_models(
        [
            _content_light(item)
            for item in hdr_items
            if "content light" in str(item.get("side_data_type") or "").casefold()
        ]
    )
    folded_types = " ".join(side_data_types).casefold()
    if "dolby vision" in folded_types or "dovi" in folded_types:
        format_name = "dolby_vision"
    elif "hdr10+" in folded_types or "smpte2094" in folded_types:
        format_name = "hdr10_plus"
    elif color_transfer == "arib-std-b67":
        format_name = "hlg"
    elif color_transfer == "smpte2084" and (mastering_values or content_values):
        format_name = "hdr10"
    elif color_transfer == "smpte2084":
        format_name = "pq"
    elif mastering_values or content_values:
        format_name = "hdr"
    else:
        format_name = None

    conflict = len(mastering_values) > 1 or len(content_values) > 1
    metadata = HDRMetadata(
        format=format_name,
        mastering_display=mastering_values[0] if mastering_values else None,
        content_light=content_values[0] if content_values else None,
        side_data_types=side_data_types,
    )
    if hdr_items:
        incomplete = (
            any("mastering display" in value.casefold() for value in side_data_types)
            and metadata.mastering_display is None
        ) or (
            any("content light" in value.casefold() for value in side_data_types)
            and metadata.content_light is None
        )
        notes: list[str] = []
        if conflict:
            notes.append(
                "conflicting HDR side data was found; the first complete value was retained"
            )
        if incomplete:
            notes.append("some HDR side data was incomplete or invalid")
        return metadata, MetadataEvidence(
            source=MetadataSource.SIDE_DATA,
            confidence=MetadataConfidence.HIGH,
            reported_values=side_data_types,
            conflict=conflict,
            note="; ".join(notes) or None,
        )
    if format_name is not None:
        return metadata, MetadataEvidence(
            source=MetadataSource.STREAM,
            confidence=MetadataConfidence.MEDIUM,
            reported_values=[f"stream.color_transfer={color_transfer}"],
            note="HDR family inferred from transfer characteristics; no static side data reported",
        )
    return metadata, MetadataEvidence(note="no HDR transfer or side data reported")


def _input_space_from_transfer(
    color_transfer: str | None,
    transfer_evidence: MetadataEvidence,
) -> tuple[ColorSpace, MetadataEvidence]:
    inferred = {
        "iec61966-2-1": ColorSpace.SRGB,
        "bt709": ColorSpace.BT709_OETF,
        "linear": ColorSpace.LINEAR_REC709,
    }.get(color_transfer)
    if inferred is not None:
        return inferred, MetadataEvidence(
            source=transfer_evidence.source,
            confidence=transfer_evidence.confidence,
            reported_values=[f"color_transfer={color_transfer}", inferred.value],
            conflict=transfer_evidence.conflict,
            note="input encoding inferred from declared transfer characteristics",
        )

    unsupported_hdr = color_transfer in {"smpte2084", "arib-std-b67"}
    return ColorSpace.BT709_OETF, MetadataEvidence(
        source=MetadataSource.DEFAULT,
        confidence=MetadataConfidence.LOW,
        reported_values=(
            [ColorSpace.BT709_OETF.value, f"color_transfer={color_transfer}"]
            if color_transfer is not None
            else [ColorSpace.BT709_OETF.value]
        ),
        conflict=unsupported_hdr,
        note=(
            "stream declares an HDR transfer unsupported by the current renderer; "
            "an explicit input workflow is required"
            if unsupported_hdr
            else "stream transfer is missing or cannot be mapped; application default retained"
        ),
    )


def probe_color_metadata(
    video_stream: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    format_info = payload.get("format")
    if not isinstance(format_info, dict):
        format_info = {}
    frames = [frame for frame in payload.get("frames", []) if isinstance(frame, dict)]
    pixel_format = _clean_string(video_stream.get("pix_fmt"))

    color_range, range_evidence = _declared_string(
        video_stream,
        format_info,
        field="color_range",
        tag_aliases={"color_range", "range"},
        normalizer=_normalize_range,
    )
    color_primaries, primaries_evidence = _declared_string(
        video_stream,
        format_info,
        field="color_primaries",
        tag_aliases={"color_primaries", "colour_primaries", "primaries"},
    )
    color_transfer, transfer_evidence = _declared_string(
        video_stream,
        format_info,
        field="color_transfer",
        tag_aliases={
            "color_transfer",
            "colour_transfer",
            "color_trc",
            "transfer_characteristics",
        },
    )
    color_matrix, matrix_evidence = _declared_string(
        video_stream,
        format_info,
        field="color_space",
        tag_aliases={
            "color_space",
            "colorspace",
            "matrix",
            "matrix_coefficients",
        },
    )
    bit_depth, bit_depth_evidence = _bit_depth(video_stream, pixel_format)
    chroma_subsampling, chroma_evidence = _chroma_subsampling(pixel_format)
    chroma_location, chroma_location_evidence = _declared_string(
        video_stream,
        format_info,
        field="chroma_location",
        tag_aliases={"chroma_location", "chroma_sample_location"},
    )
    hdr_metadata, hdr_evidence = _hdr_metadata(video_stream, frames, color_transfer)
    input_color_space, input_evidence = _input_space_from_transfer(
        color_transfer,
        transfer_evidence,
    )

    evidence = MediaMetadataEvidence(
        color_range=range_evidence,
        color_primaries=primaries_evidence,
        color_transfer=transfer_evidence,
        color_matrix=matrix_evidence,
        bit_depth=bit_depth_evidence,
        chroma_subsampling=chroma_evidence,
        chroma_location=chroma_location_evidence,
        hdr_metadata=hdr_evidence,
        input_color_space=input_evidence,
    )
    return {
        "pixel_format": pixel_format,
        "color_range": color_range,
        "color_primaries": color_primaries,
        "color_transfer": color_transfer,
        "color_matrix": color_matrix,
        "bit_depth": bit_depth,
        "chroma_subsampling": chroma_subsampling,
        "chroma_location": chroma_location,
        "hdr_metadata": hdr_metadata,
        "metadata_evidence": evidence,
        "input_color_space": input_color_space,
    }


def apply_color_management_override(
    media: MediaInfo,
    input_color_space: ColorSpace,
    source_log_profile: str | None,
) -> MediaInfo:
    if input_color_space == ColorSpace.LOG and source_log_profile is None:
        raise ValueError("log input requires source_log_profile")
    if input_color_space != ColorSpace.LOG and source_log_profile is not None:
        raise ValueError("source_log_profile is only valid for log input")

    evidence = media.metadata_evidence.model_copy(deep=True)
    actual_family = _TRANSFER_FAMILIES.get(media.color_transfer or "")
    expected_family = _EXPECTED_TRANSFER_FAMILY.get(input_color_space)
    conflict = actual_family is not None and actual_family != expected_family
    reported_values = [f"user.input_color_space={input_color_space.value}"]
    if media.color_transfer is not None:
        reported_values.append(f"stream.color_transfer={media.color_transfer}")
    evidence.input_color_space = MetadataEvidence(
        source=MetadataSource.USER_OVERRIDE,
        confidence=MetadataConfidence.HIGH,
        reported_values=reported_values,
        conflict=conflict,
        note=(
            "user-selected input profile overrides incompatible stream transfer metadata"
            if conflict
            else "user-selected input profile"
        ),
    )
    evidence.source_log_profile = (
        MetadataEvidence(
            source=MetadataSource.USER_OVERRIDE,
            confidence=MetadataConfidence.HIGH,
            reported_values=[source_log_profile],
            note="user-selected camera log profile",
        )
        if source_log_profile is not None
        else MetadataEvidence(note="no camera log profile selected")
    )
    return media.model_copy(
        update={
            "input_color_space": input_color_space,
            "source_log_profile": source_log_profile,
            "metadata_evidence": evidence,
        }
    )
