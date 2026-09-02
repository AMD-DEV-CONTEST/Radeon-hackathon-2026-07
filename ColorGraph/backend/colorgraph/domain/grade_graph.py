from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

LEGACY_GRADE_GRAPH_SCHEMA_VERSION = "colorgraph.grade-graph/v1"
LINEAR_REC709_GRADE_GRAPH_SCHEMA_VERSION = "colorgraph.grade-graph/v2"
CURRENT_GRADE_GRAPH_SCHEMA_VERSION = "colorgraph.grade-graph/v3"
LEGACY_RENDERER_VERSION = "colorgraph.renderer/v1"
LINEAR_REC709_RENDERER_VERSION = "colorgraph.renderer/v2"
CURRENT_RENDERER_VERSION = "colorgraph.renderer/v3"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ColorSpace(StrEnum):
    # `rec709` is retained only to deserialize v1 projects whose renderer
    # treated the value as sRGB. New graphs must use an explicit encoding.
    REC709 = "rec709"
    SRGB = "srgb"
    BT709_OETF = "bt709_oetf"
    REC1886 = "rec1886"
    LINEAR_REC709 = "linear_rec709"
    ACES2065_1 = "aces2065_1"
    ACESCG = "acescg"
    ACESCCT = "acescct"
    LOG = "log"


class MetadataSource(StrEnum):
    STREAM = "stream"
    CONTAINER = "container"
    PIXEL_FORMAT = "pixel_format"
    SIDE_DATA = "side_data"
    USER_OVERRIDE = "user_override"
    DEFAULT = "default"
    MISSING = "missing"


class MetadataConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class MetadataEvidence(StrictModel):
    source: MetadataSource = MetadataSource.MISSING
    confidence: MetadataConfidence = MetadataConfidence.UNKNOWN
    reported_values: list[str] = Field(default_factory=list)
    conflict: bool = False
    note: str | None = None


class Chromaticity(StrictModel):
    x: Annotated[float, Field(ge=0, le=1)]
    y: Annotated[float, Field(ge=0, le=1)]


class MasteringDisplayMetadata(StrictModel):
    red: Chromaticity
    green: Chromaticity
    blue: Chromaticity
    white_point: Chromaticity
    min_luminance: Annotated[float, Field(ge=0)]
    max_luminance: Annotated[float, Field(ge=0)]

    @model_validator(mode="after")
    def validate_luminance_order(self) -> MasteringDisplayMetadata:
        if self.max_luminance < self.min_luminance:
            raise ValueError("max_luminance must be greater than or equal to min_luminance")
        return self


class ContentLightMetadata(StrictModel):
    max_content_light_level: Annotated[int, Field(ge=0)]
    max_frame_average_light_level: Annotated[int, Field(ge=0)]


class HDRMetadata(StrictModel):
    format: str | None = None
    mastering_display: MasteringDisplayMetadata | None = None
    content_light: ContentLightMetadata | None = None
    side_data_types: list[str] = Field(default_factory=list)


class MediaMetadataEvidence(StrictModel):
    color_range: MetadataEvidence = Field(default_factory=MetadataEvidence)
    color_primaries: MetadataEvidence = Field(default_factory=MetadataEvidence)
    color_transfer: MetadataEvidence = Field(default_factory=MetadataEvidence)
    color_matrix: MetadataEvidence = Field(default_factory=MetadataEvidence)
    bit_depth: MetadataEvidence = Field(default_factory=MetadataEvidence)
    chroma_subsampling: MetadataEvidence = Field(default_factory=MetadataEvidence)
    chroma_location: MetadataEvidence = Field(default_factory=MetadataEvidence)
    hdr_metadata: MetadataEvidence = Field(default_factory=MetadataEvidence)
    input_color_space: MetadataEvidence = Field(
        default_factory=lambda: MetadataEvidence(
            source=MetadataSource.DEFAULT,
            confidence=MetadataConfidence.LOW,
            reported_values=[ColorSpace.BT709_OETF.value],
            note="application default; inspect stream metadata or choose an explicit input profile",
        )
    )
    source_log_profile: MetadataEvidence = Field(default_factory=MetadataEvidence)


class NodeType(StrEnum):
    INPUT_TRANSFORM = "input_transform"
    BALANCE = "balance"
    TONE = "tone"
    MASKED_GRADE = "masked_grade"
    LOOK = "look"
    POST_LOOK = "post_look"
    OUTPUT_TRANSFORM = "output_transform"


class ScopeLevel(StrEnum):
    PROJECT = "project"
    SCENE = "scene"
    SHOT = "shot"
    SUB_SHOT = "sub_shot"


class SpatialKind(StrEnum):
    GLOBAL = "global"
    GEOMETRIC = "geometric"
    COLOR_RANGE = "color_range"
    SEMANTIC = "semantic"
    PROMPTED = "prompted"
    DEPTH = "depth"
    COMPOSITE = "composite"


class Interpolation(StrEnum):
    HOLD = "hold"
    LINEAR = "linear"
    PCHIP = "pchip"
    # Retained for saved projects that explicitly requested the previous
    # uniform Catmull-Rom behavior.
    CUBIC = "cubic_spline"


class MediaInfo(StrictModel):
    path: str
    duration_seconds: Annotated[float, Field(ge=0)]
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]
    fps: Annotated[float, Field(gt=0)]
    frame_count: Annotated[int, Field(ge=0)]
    codec: str
    pixel_format: str | None = None
    color_range: str | None = None
    color_primaries: str | None = None
    color_transfer: str | None = None
    color_matrix: str | None = None
    bit_depth: Annotated[int, Field(gt=0, le=64)] | None = None
    chroma_subsampling: str | None = None
    chroma_location: str | None = None
    hdr_metadata: HDRMetadata = Field(default_factory=HDRMetadata)
    metadata_evidence: MediaMetadataEvidence = Field(default_factory=MediaMetadataEvidence)
    input_color_space: ColorSpace = ColorSpace.BT709_OETF
    source_log_profile: str | None = None

    @model_validator(mode="before")
    @classmethod
    def preserve_legacy_color_selection_evidence(cls, data: Any) -> Any:
        if not isinstance(data, dict) or "metadata_evidence" in data:
            return data
        input_value = data.get("input_color_space", ColorSpace.BT709_OETF)
        input_label = input_value.value if isinstance(input_value, ColorSpace) else str(input_value)
        evidence = MediaMetadataEvidence(
            input_color_space=MetadataEvidence(
                source=MetadataSource.DEFAULT,
                confidence=MetadataConfidence.LOW,
                reported_values=[input_label],
                note="legacy media record; value preserved without probe provenance",
            ),
            source_log_profile=(
                MetadataEvidence(
                    source=MetadataSource.DEFAULT,
                    confidence=MetadataConfidence.LOW,
                    reported_values=[str(data["source_log_profile"])],
                    note="legacy media record; profile preserved without probe provenance",
                )
                if data.get("source_log_profile") is not None
                else MetadataEvidence()
            ),
        )
        return {**data, "metadata_evidence": evidence}


class TimeRange(StrictModel):
    start_seconds: Annotated[float, Field(ge=0)]
    end_seconds: Annotated[float, Field(gt=0)]

    @model_validator(mode="after")
    def validate_order(self) -> TimeRange:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be greater than start_seconds")
        return self


class TemporalScope(StrictModel):
    level: ScopeLevel
    project_id: str
    scene_id: str | None = None
    shot_id: str | None = None
    sub_shot_id: str | None = None
    time_range: TimeRange | None = None


class SpatialScope(StrictModel):
    kind: SpatialKind = SpatialKind.GLOBAL
    target: str = "global"
    mask_asset_id: str | None = None
    expression: str | None = None

    @model_validator(mode="after")
    def validate_composite_expression(self) -> SpatialScope:
        if self.kind == SpatialKind.COMPOSITE and not self.expression:
            raise ValueError("composite spatial scopes require an expression")
        if self.expression and self.kind != SpatialKind.COMPOSITE:
            raise ValueError("mask expressions require kind=composite")
        return self


class Keyframe(StrictModel):
    time_seconds: Annotated[float, Field(ge=0)]
    value: float


class ParameterTrack(StrictModel):
    parameter: str
    keyframes: list[Keyframe] = Field(min_length=1)
    interpolation: Interpolation = Interpolation.PCHIP
    max_velocity: float | None = Field(default=None, gt=0)
    max_acceleration: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_keyframe_order(self) -> ParameterTrack:
        timestamps = [keyframe.time_seconds for keyframe in self.keyframes]
        if timestamps != sorted(timestamps):
            raise ValueError("keyframes must be sorted by time_seconds")
        if len(timestamps) != len(set(timestamps)):
            raise ValueError("keyframes cannot share the same time_seconds")
        return self


class GradeNode(StrictModel):
    id: str
    type: NodeType
    label: str
    order: Annotated[int, Field(ge=0)]
    enabled: bool = True
    temporal_scope: TemporalScope
    spatial_scope: SpatialScope = Field(default_factory=SpatialScope)
    parameters: dict[str, float | int | str | bool] = Field(default_factory=dict)
    tracks: list[ParameterTrack] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Shot(StrictModel):
    id: str
    scene_id: str
    index: Annotated[int, Field(ge=0)]
    time_range: TimeRange
    representative_frame: str | None = None
    lighting_change_points: list[float] = Field(default_factory=list)


class Scene(StrictModel):
    id: str
    index: Annotated[int, Field(ge=0)]
    label: str
    shot_ids: list[str] = Field(default_factory=list)
    look_node_id: str | None = None


class MaskAsset(StrictModel):
    id: str
    kind: SpatialKind
    target: str
    path: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    frame_count: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GradeGraph(StrictModel):
    schema_version: str = CURRENT_GRADE_GRAPH_SCHEMA_VERSION
    renderer_version: str = CURRENT_RENDERER_VERSION
    id: str
    project_id: str
    project_name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    working_color_space: ColorSpace = ColorSpace.ACESCG
    output_color_space: ColorSpace = ColorSpace.REC1886
    media: MediaInfo
    scenes: list[Scene] = Field(default_factory=list)
    shots: list[Shot] = Field(default_factory=list)
    nodes: list[GradeNode] = Field(default_factory=list)
    masks: list[MaskAsset] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def apply_version_compatibility_defaults(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        schema_version = payload.get(
            "schema_version",
            CURRENT_GRADE_GRAPH_SCHEMA_VERSION,
        )
        payload.setdefault("schema_version", schema_version)
        payload.setdefault(
            "renderer_version",
            (
                LEGACY_RENDERER_VERSION
                if schema_version == LEGACY_GRADE_GRAPH_SCHEMA_VERSION
                else (
                    LINEAR_REC709_RENDERER_VERSION
                    if schema_version == LINEAR_REC709_GRADE_GRAPH_SCHEMA_VERSION
                    else CURRENT_RENDERER_VERSION
                )
            ),
        )
        return payload

    @model_validator(mode="after")
    def validate_references_and_order(self) -> GradeGraph:
        version_pair = (self.schema_version, self.renderer_version)
        supported_version_pairs = {
            (LEGACY_GRADE_GRAPH_SCHEMA_VERSION, LEGACY_RENDERER_VERSION),
            (
                LINEAR_REC709_GRADE_GRAPH_SCHEMA_VERSION,
                LINEAR_REC709_RENDERER_VERSION,
            ),
            (CURRENT_GRADE_GRAPH_SCHEMA_VERSION, CURRENT_RENDERER_VERSION),
        }
        if version_pair not in supported_version_pairs:
            raise ValueError(
                "unsupported grade graph / renderer version pair: "
                f"{self.schema_version!r} / {self.renderer_version!r}"
            )

        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("node ids must be unique")
        orders = [node.order for node in self.nodes]
        if len(orders) != len(set(orders)):
            raise ValueError("node orders must be unique")

        scene_ids = {scene.id for scene in self.scenes}
        shot_ids = {shot.id for shot in self.shots}
        for shot in self.shots:
            if shot.scene_id not in scene_ids:
                raise ValueError(f"shot {shot.id} references unknown scene {shot.scene_id}")
        for scene in self.scenes:
            unknown = set(scene.shot_ids) - shot_ids
            if unknown:
                raise ValueError(f"scene {scene.id} references unknown shots: {sorted(unknown)}")
        return self

    def ordered_nodes(self) -> list[GradeNode]:
        return sorted((node for node in self.nodes if node.enabled), key=lambda node: node.order)
