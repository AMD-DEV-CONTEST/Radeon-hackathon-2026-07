"""Strict Pydantic models for Style Spec v1.

All models use ``ConfigDict(strict=True, frozen=True, extra="forbid",
allow_inf_nan=False)``. There are no business defaults, collections are stored
as tuples, and unlisted fields are forbidden. The field set is frozen by the
master-plan Module 2 contract; ``L3Config`` fields follow spec section 4.1.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError

MODEL_CONFIG = ConfigDict(strict=True, frozen=True, extra="forbid", allow_inf_nan=False)

_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", re.ASCII)
_SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}")
_RFC3339_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|z|[+-]\d{2}:\d{2})"
)
_URL_PATTERN = re.compile(r"\Ahttps?://.+\Z")
_C0_DEL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


# --- Constrained string and numeric types ---


def _safe_text(value: str) -> str:
    if value != value.strip():
        raise ValueError("text has leading or trailing whitespace")
    if _C0_DEL_PATTERN.search(value):
        raise ValueError("text contains C0/DEL control characters")
    return value


SafeText = Annotated[
    str, StringConstraints(min_length=1, max_length=2048), AfterValidator(_safe_text)
]
NameStr = Annotated[
    str, StringConstraints(min_length=1, max_length=256), AfterValidator(_safe_text)
]
AuthorStr = NameStr


def _id_like(value: str) -> str:
    if not isinstance(value, str) or _ID_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid id-like value")
    return value


IDLike = Annotated[
    str,
    StringConstraints(
        min_length=1, max_length=128, pattern=r"[A-Za-z0-9][A-Za-z0-9_-]*"
    ),
    AfterValidator(_id_like),
]


def _rfc3339(value: str) -> str:
    if not isinstance(value, str) or _RFC3339_PATTERN.fullmatch(value) is None:
        raise ValueError("created_at must be timezone-bearing RFC3339")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("created_at not a real date-time") from exc
    if dt.tzinfo is None:
        raise ValueError("created_at missing timezone")
    return value


Rfc3339Str = Annotated[
    str, StringConstraints(min_length=1, max_length=64), AfterValidator(_rfc3339)
]


def _http_url(value: str) -> str:
    if not isinstance(value, str) or _URL_PATTERN.fullmatch(value) is None:
        raise ValueError("source_url must be http/https URL")
    return value


HttpUrlStr = Annotated[
    str, StringConstraints(min_length=1, max_length=2083), AfterValidator(_http_url)
]


def _sha256_adapter(value: str) -> str:
    # Reuse domain.Sha256 semantics: validate 64 hex characters and lowercase.
    try:
        return Sha256(value).value
    except DomainError as exc:
        raise ValueError(str(exc)) from exc


Sha256Str = Annotated[
    str,
    StringConstraints(pattern=r"[0-9a-fA-F]{64}", min_length=64, max_length=64),
    AfterValidator(_sha256_adapter),
]


def _reject_bool(value):
    if isinstance(value, bool):
        raise ValueError("boolean rejected for numeric field")
    return value


def _num_coerce(value):
    # Accept int converted to float or float, but reject bool; strict float handles others.
    # Use float instead of int | float so the schema emits standard bounds.
    if isinstance(value, bool):
        raise ValueError("boolean rejected for numeric field")
    if isinstance(value, int):
        return float(value)
    return value


# Finite number: accepts int/float, rejects bool/str/inf/nan, and emits bounds.
ScaleValue = Annotated[float, Field(ge=0, le=1), BeforeValidator(_num_coerce)]
GuidanceValue = Annotated[float, Field(ge=0, le=50), BeforeValidator(_num_coerce)]
StepsValue = Annotated[int, Field(ge=1, le=200), AfterValidator(_reject_bool)]
ResolutionMember = Annotated[
    int, Field(ge=64, le=4096, multiple_of=8), AfterValidator(_reject_bool)
]


# --- Models ---


class Metadata(BaseModel):
    model_config = MODEL_CONFIG

    spec_id: IDLike
    name: NameStr
    author: AuthorStr
    created_at: Rfc3339Str
    parent_spec: IDLike | None = None


class Runtime(BaseModel):
    model_config = MODEL_CONFIG

    backend: Literal["rocm"]
    rocm_version: SafeText
    torch_version: SafeText
    diffusers_version: SafeText
    dtype: Literal["float16", "bfloat16"]


class ModelPin(BaseModel):
    model_config = MODEL_CONFIG

    id: SafeText
    revision: SafeText
    sha256: Sha256Str


class ControlNetPin(BaseModel):
    model_config = MODEL_CONFIG

    type: Literal["canny", "depth", "pose"]
    id: SafeText
    revision: SafeText
    sha256: Sha256Str


class Models(BaseModel):
    model_config = MODEL_CONFIG

    base: ModelPin
    ip_adapter: ModelPin
    controlnet: ControlNetPin


class StyleReference(BaseModel):
    model_config = MODEL_CONFIG

    asset_sha256: Sha256Str
    source_url: HttpUrlStr
    license: SafeText
    attribution: SafeText
    consent: Literal["not_applicable", "obtained"]


class Assets(BaseModel):
    model_config = MODEL_CONFIG

    style_references: tuple[StyleReference, ...] = Field(min_length=1)


class PreviewProfile(BaseModel):
    model_config = MODEL_CONFIG

    pipeline: Literal["sdxl_turbo", "lcm"]
    resolution: tuple[ResolutionMember, ResolutionMember]
    steps: StepsValue
    guidance_scale: GuidanceValue


class ProductionProfile(BaseModel):
    model_config = MODEL_CONFIG

    pipeline: Literal["sdxl_base"]
    resolution: tuple[ResolutionMember, ResolutionMember]
    steps: StepsValue
    guidance_scale: GuidanceValue
    scheduler: SafeText


class Profiles(BaseModel):
    model_config = MODEL_CONFIG

    preview: PreviewProfile
    production: ProductionProfile


class Style(BaseModel):
    model_config = MODEL_CONFIG

    preset_id: IDLike
    user_strength: ScaleValue
    preview_ip_adapter_scale: ScaleValue
    production_ip_adapter_scale: ScaleValue


class Generation(BaseModel):
    model_config = MODEL_CONFIG

    img2img_strength: ScaleValue
    controlnet_scale: ScaleValue
    seed_policy: Literal["per_asset_deterministic"]
    batch_execution: Literal["sequential"]


class Domain(BaseModel):
    model_config = MODEL_CONFIG

    profile: Literal["product_instance", "face_identity", "structure_only"]
    verifier_version: SafeText | None = None
    fidelity_required: bool


class Outputs(BaseModel):
    model_config = MODEL_CONFIG

    profiles: tuple[
        Literal["xhs_grid", "talking_head_cover", "background_sequence"], ...
    ] = Field(min_length=1)

    @model_validator(mode="after")
    def _no_duplicates(self) -> "Outputs":
        seen: set[str] = set()
        for p in self.profiles:
            if p in seen:
                raise ValueError(f"duplicate output profile: {p}")
            seen.add(p)
        return self


class ThresholdProfileRef(BaseModel):
    model_config = MODEL_CONFIG

    id: IDLike
    revision: SafeText
    sha256: Sha256Str


class L2Config(BaseModel):
    model_config = MODEL_CONFIG

    encoder_id: SafeText
    encoder_revision: SafeText
    preprocessing_version: SafeText
    threshold_profile: ThresholdProfileRef


class L3Config(BaseModel):
    """L3 configuration.

    The master plan freezes only ``l3: L3Config | None``. Internal fields follow
    spec section 4.1 (``plugin_id``, ``plugin_revision``, and
    ``threshold_profile``) and use ``SafeText``. Section 4.1 defines
    ``l3.threshold_profile`` as a plain string, unlike L2's
    ``ThresholdProfileRef``. Pending architect and security reviewer approval.
    """

    model_config = MODEL_CONFIG

    plugin_id: SafeText
    plugin_revision: SafeText
    threshold_profile: SafeText


class GateDefaults(BaseModel):
    model_config = MODEL_CONFIG

    on_unverifiable: Literal["reject", "manual_review"]
    on_warning: Literal["reject", "manual_review", "continue"]


class Verification(BaseModel):
    model_config = MODEL_CONFIG

    ruleset_version: SafeText
    gate_defaults: GateDefaults
    l2: L2Config
    l3: L3Config | None = None


class Repair(BaseModel):
    model_config = MODEL_CONFIG

    policy_version: SafeText
    max_rounds: int = Field(ge=1, le=10)
    stop_after_no_improvement: int = Field(ge=1, le=10)

    @model_validator(mode="after")
    def _stop_le_max(self) -> "Repair":
        if self.stop_after_no_improvement > self.max_rounds:
            raise ValueError("stop_after_no_improvement must be <= max_rounds")
        return self


def _only_false(value):
    if not (type(value) is bool and value is False):
        raise ValueError("per_item_metric_equality_required must be exactly False")
    return value


OnlyFalse = Annotated[Literal[False], BeforeValidator(_only_false)]


class NewBatch(BaseModel):
    model_config = MODEL_CONFIG

    contract: Literal["same_compiled_graph_and_gate_definitions"]
    per_item_metric_equality_required: OnlyFalse


class ToleratedDelta(BaseModel):
    model_config = MODEL_CONFIG

    l2_style_fidelity: ScaleValue
    l3_fidelity: ScaleValue


class ReplayContract(BaseModel):
    model_config = MODEL_CONFIG

    mode: Literal["semantic"]
    tolerated_metric_delta: ToleratedDelta
    new_batch: NewBatch


class StyleSpecV1(BaseModel):
    model_config = MODEL_CONFIG

    schema_version: Literal["1.0"]
    schema_uri: Literal["schemas/style-spec-1.0.schema.json"]
    metadata: Metadata
    runtime: Runtime
    models: Models
    assets: Assets
    profiles: Profiles
    style: Style
    generation: Generation
    domain: Domain
    outputs: Outputs
    verification: Verification
    repair: Repair
    replay_contract: ReplayContract


# --- Style Spec 1.1 (contracts section 14) ---


class StyleV11(BaseModel):
    """Style 1.1 adds a strength_mapping_version pin to Style 1.0."""

    model_config = MODEL_CONFIG

    preset_id: IDLike
    user_strength: ScaleValue
    preview_ip_adapter_scale: ScaleValue
    production_ip_adapter_scale: ScaleValue
    strength_mapping_version: SafeText


class ReplayContractV11(BaseModel):
    """Replay 1.1 adds environment_policy."""

    model_config = MODEL_CONFIG

    mode: Literal["semantic"]
    tolerated_metric_delta: ToleratedDelta
    new_batch: NewBatch
    environment_policy: Literal["advisory", "strict"]


class StyleSpecV11(BaseModel):
    model_config = MODEL_CONFIG

    schema_version: Literal["1.1"]
    schema_uri: Literal["schemas/style-spec-1.1.schema.json"]
    metadata: Metadata
    runtime: Runtime
    models: Models
    assets: Assets
    profiles: Profiles
    style: StyleV11
    generation: Generation
    domain: Domain
    outputs: Outputs
    verification: Verification
    repair: Repair
    replay_contract: ReplayContractV11


StyleSpec = StyleSpecV1 | StyleSpecV11

LEGACY_STRENGTH_MAPPING_VERSION = "legacy-unversioned"
DEFAULT_ENVIRONMENT_POLICY_V11 = "advisory"
SCHEMA_URI_V1 = "schemas/style-spec-1.0.schema.json"
SCHEMA_URI_V11 = "schemas/style-spec-1.1.schema.json"
