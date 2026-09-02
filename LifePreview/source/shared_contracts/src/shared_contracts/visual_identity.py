"""Fail-closed visual-identity authority contracts.

This module contains data contracts only.  It performs no network access and
does not treat generic Search/Reader/text transports as image capabilities.
Image search, byte fetch, and GLM Vision are represented by separate,
digest-bound evidence records.
"""

from __future__ import annotations

import ipaddress
import re
from datetime import date
from enum import Enum, StrEnum
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    StrictStr,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_core import to_jsonable_python

from .models import StrictFrozenModel as SharedStrictFrozenModel
from .models import stable_json_sha256


def _reject_binary_primitives(value: Any, path: str = "$input") -> None:
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise ValueError(
            f"binary primitive is forbidden before validation at {path}"
        )
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_binary_primitives(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple, set, frozenset)):
        for index, item in enumerate(value):
            _reject_binary_primitives(item, f"{path}[{index}]")


class StrictFrozenModel(SharedStrictFrozenModel):
    """Module-local strict base: immutable, extra-forbid, and no coercion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="before")
    @classmethod
    def reject_binary_primitives(cls, value: Any) -> Any:
        _reject_binary_primitives(value)
        return value


AI_SYNTHETIC_IDENTITY_DISCLOSURE = "AI还原形象，非历史照片"
CANONICAL_VISUAL_IDENTITY_VIEWS = (
    "front",
    "three_quarter_left",
    "profile_left",
)

Identifier = Annotated[
    StrictStr,
    Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_.-]*$"),
]


def _safe_public_text(value: str) -> str:
    inspected = value.strip()
    if (
        re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", inspected)
        or inspected.startswith(("/", "\\\\"))
        or re.match(r"^[A-Za-z]:[\\/]", inspected)
        or "../" in inspected
        or "..\\" in inspected
    ):
        raise ValueError("public text must not contain a URI, path, or traversal locator")
    return value


RevisionName = Annotated[
    StrictStr,
    Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/@-]*$"),
]
Sha256Digest = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
BoundedText = Annotated[
    StrictStr,
    Field(min_length=1, max_length=1_000),
    AfterValidator(_safe_public_text),
]
EvidenceRef = Annotated[
    StrictStr,
    Field(min_length=1, max_length=240, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/@-]*$"),
]
SafeHttpsUrl = Annotated[StrictStr, Field(min_length=9, max_length=2_048)]
IpAddressText = Annotated[StrictStr, Field(min_length=3, max_length=45)]
RejectionCode = Annotated[
    StrictStr,
    Field(min_length=1, max_length=80, pattern=r"^[A-Z][A-Z0-9_]*$"),
]
StrictBoolean = Annotated[bool, Field(strict=True)]
ControlledQueryText = Annotated[StrictStr, Field(min_length=1, max_length=240)]


class VisualIdentityMode(StrEnum):
    HISTORICAL_IMAGE_GROUNDED = "historical_image_grounded"
    SCRIPT_SYNTHESIZED = "script_synthesized"


class DiscoveryStatus(StrEnum):
    COMPLETED_WITH_ELIGIBLE = "completed_with_eligible"
    COMPLETED_ZERO_ELIGIBLE = "completed_zero_eligible"


class VisualIdentityDecisionState(StrEnum):
    SOURCE_SELECTED = "source_selected"
    AI_GENERATION_AUTHORIZED = "ai_generation_authorized"
    RETRYABLE_FAILED = "retryable_failed"
    SECURITY_BLOCKED = "security_blocked"
    CONTRACT_BLOCKED = "contract_blocked"
    BUDGET_EXHAUSTED = "budget_exhausted"


class LicenseStatus(StrEnum):
    PUBLIC_DOMAIN = "public_domain"
    LICENSED_REUSE = "licensed_reuse"
    UNKNOWN = "unknown"
    RESTRICTED = "restricted"


class CandidateFetchOutcome(StrEnum):
    ACCEPTED = "accepted"
    POLICY_REJECTED = "policy_rejected"


class GLMOutcome(StrEnum):
    PASSED = "passed"
    REJECTED = "rejected"
    NOT_RUN = "not_run"


class AppearanceBasis(StrEnum):
    HISTORICAL_STAGE_GROUNDED = "historical_stage_grounded"
    CROSS_AGE_DERIVED = "cross_age_derived"
    SCRIPT_SYNTHESIZED = "script_synthesized"


class VisualIdentityViewName(StrEnum):
    FRONT = "front"
    THREE_QUARTER_LEFT = "three_quarter_left"
    PROFILE_LEFT = "profile_left"


class GenerationMethod(StrEnum):
    FLUX_T2I = "flux_t2i"
    FLUX_REFERENCE_EDIT = "flux_reference_edit"


RepairMutableField = Literal[
    "prompt_sha256",
    "seed",
    "guidance_scale",
    "steps",
]


def visual_identity_digest(value: Any) -> str:
    """Return the canonical SHA-256 for a JSON-compatible contract payload."""

    return stable_json_sha256(to_jsonable_python(value))


def _verify_digest(model: BaseModel, field_name: str) -> None:
    expected = visual_identity_digest(
        model.model_dump(mode="json", exclude={field_name})
    )
    if getattr(model, field_name) != expected:
        raise ValueError(f"{field_name} digest does not match content")


def _unique(values: tuple[Any, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")


def _public_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError("approved peer must be an IP address") from exc
    if not address.is_global:
        raise ValueError("approved peer IP must be globally routable")
    return address


def _safe_https(value: str) -> str:
    if value != value.strip() or "\\" in value or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise ValueError("image locator contains unsafe characters")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("image locator is invalid") from exc
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or not host
        or host != host.lower()
        or host.endswith(".")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port not in (None, 443)
    ):
        raise ValueError("image locator must be canonical credential-free HTTPS")
    try:
        _public_ip(host)
    except ValueError:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if (
                host == "localhost"
                or "." not in host
                or ".." in host
                or not re.fullmatch(
                    r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?",
                    host,
                )
            ):
                raise ValueError("image locator host is not a public host")
        else:
            raise
    return value


_CONTROLLED_QUERY_FORBIDDEN = re.compile(
    r"(?:^[a-z][a-z0-9+.-]*:|^/|^\\\\|^[a-z]:[\\/]|"
    r"\.\.[\\/]|www\.|"
    r"\b(?:curl|wget|invoke-webrequest)\b|"
    r"\b(?:api[_-]?key|authorization|bearer|password|credential)\b|"
    r"\b(?:network[_-]?policy|allow-all|proxy)\b)",
    re.IGNORECASE,
)


def _controlled_query(value: str) -> str:
    if (
        value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or _CONTROLLED_QUERY_FORBIDDEN.search(value)
    ):
        raise ValueError(
            "controlled query cannot contain URLs, paths, tools, credentials, or network policy"
        )
    return value


class ControlledQueryPlanV1(StrictFrozenModel):
    schema_version: Literal["visual-identity.query-plan.v1"]
    plan_id: Identifier
    creative_ir_revision_id: Identifier
    creative_ir_sha256: Sha256Digest
    character_id: Identifier
    age_stage: Identifier
    planner_provider: Identifier
    planner_model: RevisionName
    planner_model_revision: RevisionName
    planner_prompt_revision: RevisionName
    planner_prompt_sha256: Sha256Digest
    search_provider: Identifier
    queries: tuple[ControlledQueryText, ...] = Field(
        min_length=1,
        max_length=4,
    )
    plan_sha256: Sha256Digest

    @field_validator("queries")
    @classmethod
    def validate_queries(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(_controlled_query(value) for value in values)
        _unique(checked, "controlled queries")
        return checked

    @model_validator(mode="after")
    def validate_plan(self):
        _verify_digest(self, "plan_sha256")
        return self


class SearchExecutionReceiptV1(StrictFrozenModel):
    schema_version: Literal["visual-identity.search-execution.v1"]
    receipt_id: Identifier
    plan_id: Identifier
    plan_sha256: Sha256Digest
    query_ordinal: PositiveInt = Field(le=4, strict=True)
    query_text: ControlledQueryText
    provider: Identifier
    search_service: Identifier
    search_tool: Literal["dedicated-image-search"]
    search_schema_revision: RevisionName
    status: Literal["terminal_succeeded"]
    result_count: NonNegativeInt = Field(le=400, strict=True)
    request_sha256: Sha256Digest
    response_sha256: Sha256Digest
    completed_at: AwareDatetime
    receipt_sha256: Sha256Digest

    @field_validator("query_text")
    @classmethod
    def validate_query_text(cls, value: str) -> str:
        return _controlled_query(value)

    @model_validator(mode="after")
    def validate_receipt(self):
        _verify_digest(self, "receipt_sha256")
        return self


class SearchCompletionAttestationV1(StrictFrozenModel):
    schema_version: Literal["visual-identity.search-completion.v1"]
    attestation_id: Identifier
    plan_id: Identifier
    plan_sha256: Sha256Digest
    query_plan: ControlledQueryPlanV1
    status: Literal["completed"]
    execution_receipts: tuple[SearchExecutionReceiptV1, ...] = Field(
        min_length=1,
        max_length=4,
    )
    terminal_success_count: PositiveInt = Field(le=4, strict=True)
    unresolved_count: int = Field(ge=0, le=0, strict=True)
    completed_at: AwareDatetime
    completion_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_completion(self):
        if (
            self.plan_id != self.query_plan.plan_id
            or self.plan_sha256 != self.query_plan.plan_sha256
        ):
            raise ValueError("search completion does not match controlled query plan")
        if len(self.execution_receipts) != len(self.query_plan.queries):
            raise ValueError("search completion requires every controlled query")
        ordinals = tuple(item.query_ordinal for item in self.execution_receipts)
        if ordinals != tuple(range(1, len(self.query_plan.queries) + 1)):
            raise ValueError("search receipts must follow controlled query ordinals")
        _unique(
            tuple(item.receipt_id for item in self.execution_receipts),
            "search execution receipt ids",
        )
        for receipt, query in zip(
            self.execution_receipts,
            self.query_plan.queries,
        ):
            if (
                receipt.plan_id != self.query_plan.plan_id
                or receipt.plan_sha256 != self.query_plan.plan_sha256
                or receipt.query_text != query
                or receipt.provider != self.query_plan.search_provider
            ):
                raise ValueError(
                    "search receipt plan_sha256, query, or provider binding is invalid"
                )
        if self.terminal_success_count != len(self.execution_receipts):
            raise ValueError("search completion terminal success count is invalid")
        _verify_digest(self, "completion_sha256")
        return self


class CandidateProvenanceV1(StrictFrozenModel):
    query_ordinal: PositiveInt = Field(le=4, strict=True)
    search_rank: PositiveInt = Field(le=400, strict=True)
    search_receipt_id: Identifier
    search_receipt_sha256: Sha256Digest
    search_service: Identifier
    search_tool: Literal["dedicated-image-search"]
    search_schema_revision: RevisionName
    source_page_url: SafeHttpsUrl
    image_url: SafeHttpsUrl
    source_domain: Annotated[
        StrictStr,
        Field(
            min_length=3,
            max_length=253,
            pattern=r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$",
        ),
    ]
    creator: BoundedText | None = None
    publication_date: date | None = None
    license_status: LicenseStatus
    license_reference: BoundedText | None = None
    attribution: BoundedText | None = None
    search_request_sha256: Sha256Digest
    search_response_sha256: Sha256Digest
    locator_sha256: Sha256Digest

    @field_validator("source_page_url", "image_url")
    @classmethod
    def validate_urls(cls, value: str) -> str:
        return _safe_https(value)

    @model_validator(mode="after")
    def validate_provenance(self):
        if urlsplit(self.source_page_url).hostname != self.source_domain:
            raise ValueError("source domain does not match source page locator")
        reusable = self.license_status in {
            LicenseStatus.PUBLIC_DOMAIN,
            LicenseStatus.LICENSED_REUSE,
        }
        if reusable and (
            not self.license_reference
            or not self.license_reference.strip()
            or not self.attribution
            or not self.attribution.strip()
        ):
            raise ValueError("reusable source requires license reference and attribution")
        if not reusable and (self.license_reference is not None or self.attribution is not None):
            raise ValueError("unknown or restricted source cannot claim reuse metadata")
        locator_identity = {
            "source_page_url": self.source_page_url,
            "image_url": self.image_url,
            "source_domain": self.source_domain,
        }
        if self.locator_sha256 != visual_identity_digest(locator_identity):
            raise ValueError("locator_sha256 digest does not match source locator identity")
        return self


class RedirectSecurityReceiptV1(StrictFrozenModel):
    schema_version: Literal["visual-identity.redirect-security.v1"]
    receipt_id: Identifier
    candidate_id: Identifier
    canonical_url: SafeHttpsUrl
    canonical_locator_sha256: Sha256Digest
    redirects_observed: int = Field(ge=0, le=0, strict=True)
    redirect_chain: tuple[SafeHttpsUrl, ...] = Field(default=(), max_length=0)
    policy_action: Literal["forbidden"]
    receipt_sha256: Sha256Digest

    @field_validator("canonical_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _safe_https(value)

    @model_validator(mode="after")
    def validate_receipt(self):
        _verify_digest(self, "receipt_sha256")
        return self


class FetchSecurityAttestationV1(StrictFrozenModel):
    schema_version: Literal["visual-identity.fetch-security.v1"]
    attestation_id: Identifier
    candidate_id: Identifier
    canonical_url: SafeHttpsUrl
    canonical_locator_sha256: Sha256Digest
    approved_ip_addresses: tuple[IpAddressText, ...] = Field(min_length=1, max_length=16)
    resolved_peer_ip: IpAddressText
    redirect_receipt: RedirectSecurityReceiptV1
    redirects_forbidden: StrictBoolean
    connect_approved_only: StrictBoolean
    credentials_forbidden: StrictBoolean
    network_policy_revision: RevisionName
    network_policy_sha256: Sha256Digest
    http_status: int = Field(ge=200, le=200, strict=True)
    declared_mime_type: Literal["image/jpeg", "image/png", "image/webp"]
    magic_mime_type: Literal["image/jpeg", "image/png", "image/webp"]
    raw_byte_size: PositiveInt = Field(le=20_000_000, strict=True)
    raw_sha256: Sha256Digest
    fully_decoded: StrictBoolean
    width_px: PositiveInt = Field(le=8_192, strict=True)
    height_px: PositiveInt = Field(le=8_192, strict=True)
    decoded_pixels: PositiveInt = Field(le=40_000_000, strict=True)
    frame_count: int = Field(ge=1, le=1, strict=True)
    sanitized_sha256: Sha256Digest
    artifact_id: Identifier
    artifact_sha256: Sha256Digest
    fetch_request_sha256: Sha256Digest
    fetch_response_sha256: Sha256Digest
    fetch_sha256: Sha256Digest
    attestation_sha256: Sha256Digest

    @field_validator("canonical_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _safe_https(value)

    @field_validator("approved_ip_addresses")
    @classmethod
    def validate_approved_ips(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        _unique(values, "approved IP addresses")
        for value in values:
            _public_ip(value)
        return values

    @field_validator("resolved_peer_ip")
    @classmethod
    def validate_peer(cls, value: str) -> str:
        _public_ip(value)
        return value

    @model_validator(mode="after")
    def validate_attestation(self):
        if not (
            self.redirects_forbidden
            and self.connect_approved_only
            and self.credentials_forbidden
            and self.fully_decoded
        ):
            raise ValueError("fetch security controls must be explicitly true")
        if (
            self.redirect_receipt.candidate_id != self.candidate_id
            or self.redirect_receipt.canonical_url != self.canonical_url
            or self.redirect_receipt.canonical_locator_sha256
            != self.canonical_locator_sha256
        ):
            raise ValueError(
                "redirect receipt does not match fetched candidate canonical locator"
            )
        if self.resolved_peer_ip not in self.approved_ip_addresses:
            raise ValueError("resolved peer must be in the approved IP set")
        if self.declared_mime_type != self.magic_mime_type:
            raise ValueError("declared and magic MIME types must match")
        if self.decoded_pixels != self.width_px * self.height_px:
            raise ValueError("decoded pixel count must match complete image dimensions")
        _verify_digest(self, "attestation_sha256")
        return self


class GLMVisionAttestationV1(StrictFrozenModel):
    schema_version: Literal["visual-identity.glm-vision.v1"]
    attestation_id: Identifier
    candidate_id: Identifier
    raw_sha256: Sha256Digest
    sanitized_sha256: Sha256Digest
    glm_provider: Literal["zhipu"]
    glm_model: Literal["glm-4v-plus"]
    glm_model_revision: RevisionName
    glm_prompt_revision: RevisionName
    glm_prompt_sha256: Sha256Digest
    qualification_policy_revision: RevisionName
    qualification_policy_sha256: Sha256Digest
    request_sha256: Sha256Digest
    response_sha256: Sha256Digest
    single_person: StrictBoolean
    face_visible: StrictBoolean
    identity_match: StrictBoolean
    age_match: StrictBoolean
    historical_source_match: StrictBoolean
    watermark_or_text_absent: StrictBoolean
    quality_passed: StrictBoolean
    vision_verdict: Literal["passed", "rejected"]
    license_policy_passed: StrictBoolean
    license_determination: Literal["not_evaluated_by_glm"]
    historical_fact_determination: Literal["not_evaluated_by_glm"]
    qualified: StrictBoolean
    rejection_codes: tuple[RejectionCode, ...] = Field(default=(), max_length=32)
    attestation_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_attestation(self):
        _unique(self.rejection_codes, "GLM rejection codes")
        expected_rejection_codes: list[str] = []
        if not self.single_person:
            expected_rejection_codes.append("MULTIPLE_PERSONS")
        if not self.face_visible:
            expected_rejection_codes.append("FACE_NOT_VISIBLE")
        if not self.identity_match:
            expected_rejection_codes.append("IDENTITY_DRIFT")
        if not self.age_match:
            expected_rejection_codes.append("AGE_MISMATCH")
        if not self.historical_source_match:
            expected_rejection_codes.append("SOURCE_MISMATCH")
        if not self.watermark_or_text_absent:
            expected_rejection_codes.append("WATERMARK_OR_TEXT_PRESENT")
        if not self.quality_passed:
            expected_rejection_codes.append("QUALITY_TOO_LOW")
        if not self.license_policy_passed:
            expected_rejection_codes.append("LICENSE_NOT_REUSABLE")
        if self.rejection_codes != tuple(expected_rejection_codes):
            raise ValueError(
                "GLM rejection codes must exactly match canonical failed gates"
            )
        gates = (
            self.single_person,
            self.face_visible,
            self.identity_match,
            self.age_match,
            self.historical_source_match,
            self.watermark_or_text_absent,
            self.quality_passed,
        )
        vision_passed = all(gates)
        if (self.vision_verdict == "passed") != vision_passed:
            raise ValueError("GLM vision verdict does not match vision gates")
        expected_qualified = vision_passed and self.license_policy_passed
        if self.qualified != expected_qualified:
            raise ValueError("qualified must combine license policy and all vision gates")
        _verify_digest(self, "attestation_sha256")
        return self


class HistoricalImageCandidateV1(StrictFrozenModel):
    candidate_id: Identifier
    search_rank: PositiveInt = Field(le=400, strict=True)
    locator_sha256: Sha256Digest
    provenance: CandidateProvenanceV1
    fetch_outcome: CandidateFetchOutcome
    fetch_attestation: FetchSecurityAttestationV1 | None = None
    artifact_id: Identifier | None = None
    artifact_sha256: Sha256Digest | None = None
    content_sha256: Sha256Digest | None = None
    mime_type: Literal["image/jpeg", "image/png", "image/webp"] | None = None
    glm_outcome: GLMOutcome
    glm_attestation: GLMVisionAttestationV1 | None = None
    evaluation_sha256: Sha256Digest | None = None
    qualification_policy_sha256: Sha256Digest
    rejection_codes: tuple[RejectionCode, ...] = Field(default=(), max_length=32)
    eligible: StrictBoolean
    candidate_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_candidate(self):
        _unique(self.rejection_codes, "candidate rejection codes")
        if self.search_rank != self.provenance.search_rank:
            raise ValueError("candidate rank does not match provenance")
        if self.locator_sha256 != self.provenance.locator_sha256:
            raise ValueError("candidate locator digest does not match provenance")
        reusable = self.provenance.license_status in {
            LicenseStatus.PUBLIC_DOMAIN,
            LicenseStatus.LICENSED_REUSE,
        }
        if self.fetch_outcome is CandidateFetchOutcome.POLICY_REJECTED:
            forbidden = (
                self.fetch_attestation,
                self.artifact_id,
                self.artifact_sha256,
                self.content_sha256,
                self.mime_type,
                self.glm_attestation,
                self.evaluation_sha256,
            )
            if reusable or any(item is not None for item in forbidden):
                raise ValueError("policy_rejected candidate cannot contain fetched artifacts")
            expected_policy_codes = {
                LicenseStatus.UNKNOWN: ("LICENSE_STATUS_UNKNOWN",),
                LicenseStatus.RESTRICTED: ("LICENSE_RESTRICTED",),
            }[self.provenance.license_status]
            if self.rejection_codes != expected_policy_codes:
                raise ValueError(
                    "policy rejection codes must exactly match canonical license status"
                )
            if self.glm_outcome is not GLMOutcome.NOT_RUN or self.eligible:
                raise ValueError("policy_rejected candidate must be terminal and GLM not_run")
        else:
            if not reusable or self.fetch_attestation is None or self.glm_attestation is None:
                raise ValueError("accepted fetch requires reusable provenance and both attestations")
            fetch = self.fetch_attestation
            glm = self.glm_attestation
            if (
                fetch.candidate_id != self.candidate_id
                or fetch.canonical_url != self.provenance.image_url
                or fetch.canonical_locator_sha256
                != self.provenance.locator_sha256
                or glm.candidate_id != self.candidate_id
                or glm.raw_sha256 != fetch.raw_sha256
                or glm.sanitized_sha256 != fetch.sanitized_sha256
                or self.artifact_id != fetch.artifact_id
                or self.artifact_sha256 != fetch.artifact_sha256
                or self.content_sha256 != fetch.sanitized_sha256
                or self.mime_type != fetch.magic_mime_type
                or self.glm_outcome.value != glm.vision_verdict
                or self.evaluation_sha256 != glm.attestation_sha256
                or self.qualification_policy_sha256
                != glm.qualification_policy_sha256
                or self.rejection_codes != glm.rejection_codes
            ):
                raise ValueError("candidate fetch/GLM/artifact lineage is inconsistent")
            expected_eligible = glm.qualified and not self.rejection_codes
            if self.eligible != expected_eligible:
                raise ValueError("candidate eligibility does not match terminal attestations")
        _verify_digest(self, "candidate_sha256")
        return self


class HistoricalSearchDiscoveryV1(StrictFrozenModel):
    schema_version: Literal["visual-identity.discovery.v1"]
    discovery_id: Identifier
    query_plan: ControlledQueryPlanV1
    search_completion: SearchCompletionAttestationV1
    search_capability: Literal["dedicated_image_search"]
    fetch_capability: Literal["dedicated_image_fetch"]
    vision_capability: Literal["glm_vision"]
    status: Literal["completed_with_eligible", "completed_zero_eligible"]
    mode: VisualIdentityMode
    decision_state: Literal["source_selected", "ai_generation_authorized"]
    candidates: tuple[HistoricalImageCandidateV1, ...] = Field(default=(), max_length=400)
    discovered_count: NonNegativeInt = Field(strict=True)
    eligible_count: NonNegativeInt = Field(strict=True)
    terminal_rejection_count: NonNegativeInt = Field(strict=True)
    unresolved_count: NonNegativeInt = Field(strict=True)
    infrastructure_failure_count: NonNegativeInt = Field(strict=True)
    security_failure_count: NonNegativeInt = Field(strict=True)
    contract_failure_count: NonNegativeInt = Field(strict=True)
    budget_failure_count: NonNegativeInt = Field(strict=True)
    selected_candidate_id: Identifier | None = None
    selected_candidate_sha256: Sha256Digest | None = None
    discovery_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_discovery(self):
        if any(
            (
                self.unresolved_count,
                self.infrastructure_failure_count,
                self.security_failure_count,
                self.contract_failure_count,
                self.budget_failure_count,
            )
        ):
            raise ValueError("successful discovery cannot contain unresolved or failure counts")
        if (
            self.search_completion.plan_id != self.query_plan.plan_id
            or self.search_completion.plan_sha256 != self.query_plan.plan_sha256
            or self.search_completion.query_plan != self.query_plan
        ):
            raise ValueError("discovery search completion does not match query plan")
        receipts_by_ordinal = {
            item.query_ordinal: item
            for item in self.search_completion.execution_receipts
        }
        if self.discovered_count != len(self.candidates):
            raise ValueError("discovered count does not match candidates")
        ranks = tuple(candidate.search_rank for candidate in self.candidates)
        if ranks != tuple(range(1, len(self.candidates) + 1)):
            raise ValueError("candidate search ranks must be contiguous from 1")
        _unique(tuple(item.candidate_id for item in self.candidates), "candidate ids")
        _unique(tuple(item.locator_sha256 for item in self.candidates), "candidate locators")
        fetched_contents = tuple(
            item.content_sha256
            for item in self.candidates
            if item.content_sha256 is not None
        )
        _unique(fetched_contents, "candidate content digests")
        if any(
            candidate.provenance.query_ordinal > len(self.query_plan.queries)
            for candidate in self.candidates
        ):
            raise ValueError("candidate query ordinal is outside the controlled plan")
        result_counts = {ordinal: 0 for ordinal in receipts_by_ordinal}
        for candidate in self.candidates:
            receipt = receipts_by_ordinal.get(candidate.provenance.query_ordinal)
            if (
                receipt is None
                or candidate.provenance.search_receipt_id != receipt.receipt_id
                or candidate.provenance.search_receipt_sha256
                != receipt.receipt_sha256
                or candidate.provenance.search_service != receipt.search_service
                or candidate.provenance.search_tool != receipt.search_tool
                or candidate.provenance.search_schema_revision
                != receipt.search_schema_revision
                or candidate.provenance.search_request_sha256
                != receipt.request_sha256
                or candidate.provenance.search_response_sha256
                != receipt.response_sha256
            ):
                raise ValueError("candidate search execution receipt lineage is invalid")
            result_counts[receipt.query_ordinal] += 1
        if any(
            result_counts[item.query_ordinal] != item.result_count
            for item in self.search_completion.execution_receipts
        ):
            raise ValueError("search receipt result counts do not match candidates")
        eligible = tuple(item for item in self.candidates if item.eligible)
        rejected = tuple(item for item in self.candidates if not item.eligible and item.rejection_codes)
        if self.eligible_count != len(eligible):
            raise ValueError("eligible count does not match candidates")
        if self.terminal_rejection_count != len(rejected):
            raise ValueError("terminal rejection count does not match candidates")

        if self.status == DiscoveryStatus.COMPLETED_WITH_ELIGIBLE:
            selected = next(
                (
                    item
                    for item in eligible
                    if item.candidate_id == self.selected_candidate_id
                ),
                None,
            )
            if (
                not eligible
                or self.mode is not VisualIdentityMode.HISTORICAL_IMAGE_GROUNDED
                or self.decision_state != "source_selected"
                or selected is None
                or self.selected_candidate_sha256 != selected.candidate_sha256
            ):
                raise ValueError("completed_with_eligible requires an exact selected source")
        else:
            if (
                eligible
                or self.mode is not VisualIdentityMode.SCRIPT_SYNTHESIZED
                or self.decision_state != "ai_generation_authorized"
                or self.selected_candidate_id is not None
                or self.selected_candidate_sha256 is not None
                or len(rejected) != len(self.candidates)
            ):
                raise ValueError(
                    "AI generation requires complete success and terminal rejection of every candidate"
                )
        _verify_digest(self, "discovery_sha256")
        return self


class VisualIdentityRetryableFailure(StrictFrozenModel):
    schema_version: Literal["visual-identity.failure.v1"]
    failure_id: Identifier
    query_plan_id: Identifier
    query_plan_sha256: Sha256Digest
    status: Literal["retryable_failed"]
    mode: Literal[None]
    decision_state: Literal["retryable_failed"]
    failed_stage: Literal["search", "fetch", "glm_validation"]
    safe_error_code: Identifier
    locator_sha256: Sha256Digest | None = None
    failure_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_failure(self):
        needs_locator = self.failed_stage in {"fetch", "glm_validation"}
        if needs_locator != (self.locator_sha256 is not None):
            raise ValueError("candidate-specific failure stage requires exactly one locator digest")
        _verify_digest(self, "failure_sha256")
        return self


VisualIdentityRetryableFailureV1 = VisualIdentityRetryableFailure


class VisualIdentityBlockedFailureV1(StrictFrozenModel):
    schema_version: Literal["visual-identity.failure.v1"]
    failure_id: Identifier
    query_plan_id: Identifier
    query_plan_sha256: Sha256Digest
    status: Literal["security_blocked", "contract_blocked", "budget_exhausted"]
    mode: Literal[None]
    decision_state: Literal["security_blocked", "contract_blocked", "budget_exhausted"]
    failed_stage: Literal["search", "fetch", "glm_validation", "contract", "budget"]
    safe_error_code: Identifier
    locator_sha256: Sha256Digest | None = None
    failure_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_failure(self):
        if self.status != self.decision_state:
            raise ValueError("blocked status and decision state must match")
        expected_stages = {
            "security_blocked": {"search", "fetch", "glm_validation"},
            "contract_blocked": {"contract"},
            "budget_exhausted": {"budget"},
        }
        if self.failed_stage not in expected_stages[self.status]:
            raise ValueError("blocked status does not match failure stage")
        needs_locator = self.failed_stage in {"fetch", "glm_validation"}
        if needs_locator != (self.locator_sha256 is not None):
            raise ValueError("candidate-specific blocked stage requires exactly one locator digest")
        _verify_digest(self, "failure_sha256")
        return self


VisualIdentityDiscoveryResultV1 = Annotated[
    HistoricalSearchDiscoveryV1
    | VisualIdentityRetryableFailure
    | VisualIdentityBlockedFailureV1,
    Field(discriminator="status"),
]


class SearchedHistoricalIdentityBasisV1(StrictFrozenModel):
    kind: Literal["searched_historical"]
    basis_id: Identifier
    character_id: Identifier
    discovery: HistoricalSearchDiscoveryV1
    selected_candidate_id: Identifier
    selected_candidate_sha256: Sha256Digest
    selected_artifact_id: Identifier
    selected_artifact_sha256: Sha256Digest
    selected_content_sha256: Sha256Digest
    selected_locator_sha256: Sha256Digest
    discovery_sha256: Sha256Digest
    source_artifact_fence_sha256: Sha256Digest
    source_verified: StrictBoolean
    historical_identity_basis: StrictBoolean
    ai_generated: StrictBoolean
    basis_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_basis(self):
        if not self.source_verified or not self.historical_identity_basis or self.ai_generated:
            raise ValueError("historical basis must be verified, historical, and non-AI")
        if (
            self.discovery.status != DiscoveryStatus.COMPLETED_WITH_ELIGIBLE
            or self.discovery.eligible_count < 1
        ):
            raise ValueError("historical basis requires completed discovery with eligible source")
        if self.character_id != self.discovery.query_plan.character_id:
            raise ValueError("historical basis character does not match discovery")
        selected = next(
            (
                candidate
                for candidate in self.discovery.candidates
                if candidate.candidate_id == self.discovery.selected_candidate_id
            ),
            None,
        )
        if selected is None or not selected.eligible:
            raise ValueError("historical basis selected source is missing")
        expected = (
            selected.candidate_id,
            selected.candidate_sha256,
            selected.artifact_id,
            selected.artifact_sha256,
            selected.content_sha256,
            selected.locator_sha256,
            self.discovery.discovery_sha256,
        )
        actual = (
            self.selected_candidate_id,
            self.selected_candidate_sha256,
            self.selected_artifact_id,
            self.selected_artifact_sha256,
            self.selected_content_sha256,
            self.selected_locator_sha256,
            self.discovery_sha256,
        )
        if actual != expected:
            raise ValueError("historical basis selected fields do not match discovery")
        source_fence = {
            "selected_candidate_id": self.selected_candidate_id,
            "selected_candidate_sha256": self.selected_candidate_sha256,
            "selected_artifact_id": self.selected_artifact_id,
            "selected_artifact_sha256": self.selected_artifact_sha256,
            "selected_content_sha256": self.selected_content_sha256,
            "selected_locator_sha256": self.selected_locator_sha256,
            "discovery_sha256": self.discovery_sha256,
        }
        if self.source_artifact_fence_sha256 != visual_identity_digest(
            source_fence
        ):
            raise ValueError(
                "historical source artifact fence does not match selected source"
            )
        _verify_digest(self, "basis_sha256")
        return self


class ScriptSynthesizedIdentityBasisV1(StrictFrozenModel):
    kind: Literal["script_synthesized"]
    basis_id: Identifier
    character_id: Identifier
    discovery: HistoricalSearchDiscoveryV1
    project_ir_revision_id: Identifier
    project_ir_sha256: Sha256Digest
    trial_script_revision_id: Identifier
    trial_script_sha256: Sha256Digest
    evidence_pack_revision_id: Identifier
    evidence_pack_sha256: Sha256Digest
    identity_evidence_kind: Literal["script_evidence_claims"]
    technical_canvas_identity_evidence: Literal[False]
    visual_brief_revision_id: Identifier
    visual_brief_sha256: Sha256Digest
    synthesis_policy_revision_id: Identifier
    synthesis_policy_sha256: Sha256Digest
    basis_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_basis(self):
        if (
            self.discovery.status != DiscoveryStatus.COMPLETED_ZERO_ELIGIBLE
            or self.discovery.eligible_count != 0
            or self.discovery.decision_state != "ai_generation_authorized"
        ):
            raise ValueError("script basis requires successful zero-eligible discovery")
        if self.character_id != self.discovery.query_plan.character_id:
            raise ValueError("script basis character does not match discovery")
        _verify_digest(self, "basis_sha256")
        return self


VisualIdentityBasisV1 = Annotated[
    SearchedHistoricalIdentityBasisV1 | ScriptSynthesizedIdentityBasisV1,
    Field(discriminator="kind"),
]


class CharacterIdentitySpecV1(StrictFrozenModel):
    schema_version: Literal["character.identity-spec.v1"]
    identity_spec_id: Identifier
    revision_id: Identifier
    character_id: Identifier
    invariant_face_structure: BoundedText
    invariant_identity_traits: tuple[BoundedText, ...] = Field(min_length=1, max_length=24)
    identity_basis_kind: Literal["searched_historical", "script_synthesized"]
    identity_basis_sha256: Sha256Digest
    evidence_pack_sha256: Sha256Digest
    appearance_evidence_claim_ids: tuple[Identifier, ...] = Field(
        min_length=1,
        max_length=64,
    )
    identity_spec_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_spec(self):
        _unique(self.invariant_identity_traits, "invariant identity traits")
        _unique(
            self.appearance_evidence_claim_ids,
            "appearance evidence claim ids",
        )
        _verify_digest(self, "identity_spec_sha256")
        return self


class AgeStageAppearanceSpecV1(StrictFrozenModel):
    schema_version: Literal["character.age-stage-appearance.v1"]
    age_stage: Identifier
    ordinal: NonNegativeInt = Field(le=31, strict=True)
    minimum_age: NonNegativeInt = Field(le=150, strict=True)
    maximum_age: NonNegativeInt = Field(le=150, strict=True)
    age_cues: BoundedText
    hair: BoundedText
    attire: BoundedText
    body_shape: BoundedText
    character_identity_spec_sha256: Sha256Digest
    appearance_basis: AppearanceBasis
    historical_locator_sha256: Sha256Digest | None = None
    historical_content_sha256: Sha256Digest | None = None
    cross_age_parent_stage: Identifier | None = None
    cross_age_parent_sha256: Sha256Digest | None = None
    script_basis_sha256: Sha256Digest | None = None
    appearance_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_spec(self):
        if self.minimum_age > self.maximum_age:
            raise ValueError("age-stage minimum age cannot exceed maximum age")
        historical = (self.historical_locator_sha256, self.historical_content_sha256)
        cross_age = (self.cross_age_parent_stage, self.cross_age_parent_sha256)
        if self.appearance_basis is AppearanceBasis.HISTORICAL_STAGE_GROUNDED:
            valid = all(item is not None for item in historical) and not any(cross_age) and self.script_basis_sha256 is None
        elif self.appearance_basis is AppearanceBasis.CROSS_AGE_DERIVED:
            valid = all(item is not None for item in cross_age) and not any(historical) and self.script_basis_sha256 is None
        else:
            valid = self.script_basis_sha256 is not None and not any(historical) and not any(cross_age)
        if not valid:
            raise ValueError("appearance basis fields are not an exact one-of")
        _verify_digest(self, "appearance_sha256")
        return self


class GLMQCEvidenceV1(StrictFrozenModel):
    schema_version: Literal["visual-identity.glm-qc-evidence.v1"]
    evidence_id: Identifier
    glm_provider: Literal["zhipu"]
    glm_model: Literal["glm-4v-plus"]
    glm_model_revision: RevisionName
    glm_prompt_revision: RevisionName
    glm_prompt_sha256: Sha256Digest
    qc_policy_revision: RevisionName
    qc_policy_sha256: Sha256Digest
    input_manifest_sha256: Sha256Digest
    request_sha256: Sha256Digest
    response_sha256: Sha256Digest
    evidence_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_evidence(self):
        _verify_digest(self, "evidence_sha256")
        return self


def _view_qc_input_manifest(qc: BaseModel) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "manifest_kind": "single_visual_identity_artifact",
        "evaluated_artifact_id": qc.evaluated_artifact_id,
        "evaluated_artifact_sha256": qc.evaluated_artifact_sha256,
        "parent_artifact_id": qc.parent_artifact_id,
        "parent_artifact_sha256": qc.parent_artifact_sha256,
        "character_identity_spec_sha256": qc.character_identity_spec_sha256,
        "age_stage": qc.age_stage,
        "age_stage_appearance_sha256": qc.age_stage_appearance_sha256,
        "view_name": qc.view_name.value,
        "attempt_ordinal": qc.attempt_ordinal,
    }
    if qc.kind == "source_fidelity":
        payload.update(
            {
                "source_kind": "searched_historical",
                "source_candidate_id": qc.source_candidate_id,
                "source_artifact_id": qc.source_artifact_id,
                "source_artifact_sha256": qc.source_artifact_sha256,
                "source_content_sha256": qc.source_content_sha256,
                "source_artifact_fence_sha256": qc.source_artifact_fence_sha256,
            }
        )
    else:
        payload.update(
            {
                "source_kind": "script_synthesized",
                "script_basis_sha256": qc.script_basis_sha256,
            }
        )
    return payload


def _visual_qc_failure_codes(qc: BaseModel) -> tuple[str, ...]:
    failures: list[str] = []
    if qc.fidelity_score < 0.8:
        failures.append("FIDELITY_LOW")
    if not qc.angle_correct:
        failures.append("ANGLE_MISMATCH")
    if not qc.artifact_free:
        failures.append("ARTIFACT_PRESENT")
    if not qc.single_subject:
        failures.append("MULTIPLE_SUBJECTS")
    if not qc.clean_background:
        failures.append("BACKGROUND_NOT_CLEAN")
    if not qc.no_text_or_collage:
        failures.append("TEXT_OR_COLLAGE_PRESENT")
    if not qc.identity_match:
        failures.append("IDENTITY_DRIFT")
    if not qc.age_adherence:
        failures.append("AGE_MISMATCH")
    if not qc.attire_adherence:
        failures.append("ATTIRE_MISMATCH")
    return tuple(failures)


class SourceFidelityQCV1(StrictFrozenModel):
    kind: Literal["source_fidelity"]
    evaluated_artifact_id: Identifier
    evaluated_artifact_sha256: Sha256Digest
    parent_artifact_id: Identifier | None = None
    parent_artifact_sha256: Sha256Digest | None = None
    character_identity_spec_sha256: Sha256Digest
    age_stage: Identifier
    age_stage_appearance_sha256: Sha256Digest
    view_name: VisualIdentityViewName
    attempt_ordinal: int = Field(ge=0, le=1, strict=True)
    glm_evidence: GLMQCEvidenceV1
    source_candidate_id: Identifier
    source_artifact_id: Identifier
    source_artifact_sha256: Sha256Digest
    source_content_sha256: Sha256Digest
    source_artifact_fence_sha256: Sha256Digest
    fidelity_score: float = Field(ge=0, le=1, strict=True)
    angle_correct: StrictBoolean
    artifact_free: StrictBoolean
    single_subject: StrictBoolean
    clean_background: StrictBoolean
    no_text_or_collage: StrictBoolean
    identity_match: StrictBoolean
    age_adherence: StrictBoolean
    attire_adherence: StrictBoolean
    failure_codes: tuple[RejectionCode, ...] = Field(default=(), max_length=16)
    passed: StrictBoolean
    evidence_refs: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=64)
    qc_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_qc(self):
        _unique(self.evidence_refs, "source QC evidence references")
        _unique(self.failure_codes, "source QC failure codes")
        parent = (self.parent_artifact_id, self.parent_artifact_sha256)
        if any(item is None for item in parent) and any(item is not None for item in parent):
            raise ValueError("source QC parent artifact lineage must be complete")
        expected_failures = _visual_qc_failure_codes(self)
        if self.failure_codes != expected_failures:
            raise ValueError("source fidelity QC failure codes do not match gates")
        if self.passed != (not expected_failures):
            raise ValueError("source fidelity QC result does not match gates")
        if self.glm_evidence.input_manifest_sha256 != visual_identity_digest(
            _view_qc_input_manifest(self)
        ):
            raise ValueError("source fidelity GLM input manifest does not match artifact lineage")
        _verify_digest(self, "qc_sha256")
        return self


class AppearanceSpecFidelityQCV1(StrictFrozenModel):
    kind: Literal["appearance_spec_fidelity"]
    evaluated_artifact_id: Identifier
    evaluated_artifact_sha256: Sha256Digest
    parent_artifact_id: Identifier | None = None
    parent_artifact_sha256: Sha256Digest | None = None
    character_identity_spec_sha256: Sha256Digest
    age_stage: Identifier
    age_stage_appearance_sha256: Sha256Digest
    view_name: VisualIdentityViewName
    attempt_ordinal: int = Field(ge=0, le=1, strict=True)
    glm_evidence: GLMQCEvidenceV1
    script_basis_sha256: Sha256Digest
    fidelity_score: float = Field(ge=0, le=1, strict=True)
    angle_correct: StrictBoolean
    artifact_free: StrictBoolean
    single_subject: StrictBoolean
    clean_background: StrictBoolean
    no_text_or_collage: StrictBoolean
    identity_match: StrictBoolean
    age_adherence: StrictBoolean
    attire_adherence: StrictBoolean
    failure_codes: tuple[RejectionCode, ...] = Field(default=(), max_length=16)
    passed: StrictBoolean
    evidence_refs: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=64)
    qc_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_qc(self):
        _unique(self.evidence_refs, "appearance QC evidence references")
        _unique(self.failure_codes, "appearance QC failure codes")
        parent = (self.parent_artifact_id, self.parent_artifact_sha256)
        if any(item is None for item in parent) and any(item is not None for item in parent):
            raise ValueError("appearance QC parent artifact lineage must be complete")
        expected_failures = _visual_qc_failure_codes(self)
        if self.failure_codes != expected_failures:
            raise ValueError("appearance fidelity QC failure codes do not match gates")
        if self.passed != (not expected_failures):
            raise ValueError("appearance fidelity QC result does not match gates")
        if self.glm_evidence.input_manifest_sha256 != visual_identity_digest(
            _view_qc_input_manifest(self)
        ):
            raise ValueError(
                "appearance fidelity GLM input manifest does not match artifact lineage"
            )
        _verify_digest(self, "qc_sha256")
        return self


VisualIdentityQCV1 = Annotated[
    SourceFidelityQCV1 | AppearanceSpecFidelityQCV1,
    Field(discriminator="kind"),
]


class Flux2DevCapabilityV1(StrictFrozenModel):
    """Deployment/persistence authority for the frozen AMD FLUX2 runtime."""

    schema_version: Literal["flux2-dev-capability.v1"]
    capability_id: Identifier
    capability_revision_id: Identifier
    flux_model_family: Literal["flux2-dev"]
    flux_runtime_profile: Literal["flux2-dev-fp8mixed.v1"]
    diffusion_model_sha256: Sha256Digest
    text_encoder_sha256: Sha256Digest
    vae_sha256: Sha256Digest
    workflow_sha256: Sha256Digest
    capability_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_capability(self):
        _verify_digest(self, "capability_sha256")
        return self


class VisualIdentityViewAttemptV1(StrictFrozenModel):
    attempt_ordinal: int = Field(ge=0, le=1, strict=True)
    artifact_id: Identifier
    artifact_sha256: Sha256Digest
    generation_method: GenerationMethod
    flux_model_family: Literal["flux2-dev"]
    flux_runtime_profile: Literal["flux2-dev-fp8mixed.v1"]
    flux2_capability_sha256: Sha256Digest
    diffusion_model_sha256: Sha256Digest
    text_encoder_sha256: Sha256Digest
    vae_sha256: Sha256Digest
    workflow_sha256: Sha256Digest
    prompt_sha256: Sha256Digest
    seed: NonNegativeInt = Field(le=2_147_483_647, strict=True)
    guidance_scale: float = Field(ge=0, le=20, strict=True)
    steps: PositiveInt = Field(le=100, strict=True)
    parent_artifact_id: Identifier | None = None
    parent_artifact_sha256: Sha256Digest | None = None
    qc: VisualIdentityQCV1
    repair_trigger_codes: tuple[RejectionCode, ...] = Field(default=(), max_length=16)
    repair_of_attempt_sha256: Sha256Digest | None = None
    failed_qc_sha256: Sha256Digest | None = None
    repair_mutated_fields: tuple[RepairMutableField, ...] = Field(
        default=(),
        max_length=4,
    )
    generated_at: AwareDatetime
    attempt_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_attempt(self):
        _unique(self.repair_trigger_codes, "repair trigger codes")
        _unique(self.repair_mutated_fields, "repair mutated fields")
        repair_bindings = (
            self.repair_of_attempt_sha256,
            self.failed_qc_sha256,
        )
        if self.attempt_ordinal == 0:
            if self.repair_trigger_codes or any(repair_bindings) or self.repair_mutated_fields:
                raise ValueError("initial generation cannot contain repair metadata")
        elif (
            not self.repair_trigger_codes
            or not all(repair_bindings)
            or not self.repair_mutated_fields
        ):
            raise ValueError(
                "repair generation requires a repair trigger, failed QC, and allowed fields"
            )
        parent = (self.parent_artifact_id, self.parent_artifact_sha256)
        if self.generation_method is GenerationMethod.FLUX_T2I:
            if any(parent):
                raise ValueError("FLUX T2I root cannot contain a parent")
        elif not all(item is not None for item in parent):
            raise ValueError("FLUX reference edit requires complete parent lineage")
        if (
            self.qc.attempt_ordinal != self.attempt_ordinal
            or self.qc.parent_artifact_id != self.parent_artifact_id
            or self.qc.parent_artifact_sha256 != self.parent_artifact_sha256
        ):
            raise ValueError("attempt QC must bind attempt ordinal and parent artifact lineage")
        _verify_digest(self, "attempt_sha256")
        return self


class VisualIdentityViewV1(StrictFrozenModel):
    age_stage: Identifier
    view_name: VisualIdentityViewName
    attempts: tuple[VisualIdentityViewAttemptV1, ...] = Field(min_length=1, max_length=2)
    selected_attempt_ordinal: int = Field(ge=0, le=1, strict=True)
    view_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_view(self):
        ordinals = tuple(item.attempt_ordinal for item in self.attempts)
        if ordinals != tuple(range(len(self.attempts))):
            raise ValueError("view attempts must be contiguous 0 then optional repair 1")
        _unique(tuple(item.artifact_id for item in self.attempts), "attempt artifacts")
        if self.selected_attempt_ordinal >= len(self.attempts):
            raise ValueError("selected attempt ordinal is out of bounds")
        selected = self.attempts[self.selected_attempt_ordinal]
        if not selected.qc.passed:
            raise ValueError("selected view attempt must pass QC")
        for attempt in self.attempts:
            if (
                attempt.qc.evaluated_artifact_id != attempt.artifact_id
                or attempt.qc.evaluated_artifact_sha256 != attempt.artifact_sha256
                or attempt.qc.age_stage != self.age_stage
                or attempt.qc.view_name is not self.view_name
            ):
                raise ValueError(
                    "attempt QC must bind its artifact, age stage, and view"
                )
        if len(self.attempts) == 1:
            if self.selected_attempt_ordinal != 0:
                raise ValueError("single-attempt view must select attempt zero")
        else:
            initial, repair = self.attempts
            if initial.qc.passed or not repair.qc.passed:
                raise ValueError("repair is allowed only after failed initial QC")
            if (
                self.selected_attempt_ordinal != 1
                or repair.repair_of_attempt_sha256 != initial.attempt_sha256
                or repair.failed_qc_sha256 != initial.qc.qc_sha256
                or repair.repair_trigger_codes != initial.qc.failure_codes
            ):
                raise ValueError(
                    "repair trigger codes must exactly bind failed QC and initial attempt"
                )
            invariant_fields = (
                "flux_model_family",
                "flux_runtime_profile",
                "flux2_capability_sha256",
                "diffusion_model_sha256",
                "text_encoder_sha256",
                "vae_sha256",
                "workflow_sha256",
            )
            if any(
                getattr(initial, field) != getattr(repair, field)
                for field in invariant_fields
            ):
                raise ValueError("repair must preserve invariant lineage")
            if initial.generation_method is GenerationMethod.FLUX_T2I:
                if (
                    repair.generation_method
                    is not GenerationMethod.FLUX_REFERENCE_EDIT
                    or repair.parent_artifact_id != initial.artifact_id
                    or repair.parent_artifact_sha256 != initial.artifact_sha256
                ):
                    raise ValueError(
                        "FLUX T2I root repair must reference-edit attempt zero artifact"
                    )
            elif (
                repair.generation_method is not initial.generation_method
                or repair.parent_artifact_id != initial.parent_artifact_id
                or repair.parent_artifact_sha256
                != initial.parent_artifact_sha256
            ):
                raise ValueError("reference-edit repair must preserve parent lineage")
            mutable_fields = (
                "prompt_sha256",
                "seed",
                "guidance_scale",
                "steps",
            )
            actual_mutations = {
                field
                for field in mutable_fields
                if getattr(initial, field) != getattr(repair, field)
            }
            if actual_mutations != set(repair.repair_mutated_fields):
                raise ValueError("repair mutated fields must exactly match allowed changes")
        _verify_digest(self, "view_sha256")
        return self

    @property
    def selected_attempt(self) -> VisualIdentityViewAttemptV1:
        return self.attempts[self.selected_attempt_ordinal]


class CrossViewVisualIdentityQCV1(StrictFrozenModel):
    glm_evidence: GLMQCEvidenceV1
    character_identity_spec_sha256: Sha256Digest
    age_stage_appearance_sha256s: tuple[Sha256Digest, ...] = Field(
        min_length=1,
        max_length=12,
    )
    selected_artifact_matrix_sha256: Sha256Digest
    identity_consistent: StrictBoolean
    age_progression_consistent: StrictBoolean
    attire_consistent: StrictBoolean
    angles_complete: StrictBoolean
    artifact_free: StrictBoolean
    evidence_refs: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=64)
    evaluated_at: AwareDatetime
    qc_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_qc(self):
        _unique(self.evidence_refs, "cross-view QC evidence references")
        _unique(
            self.age_stage_appearance_sha256s,
            "cross-view age-stage appearance digests",
        )
        input_manifest = {
            "manifest_kind": "ordered_selected_visual_identity_matrix",
            "character_identity_spec_sha256": self.character_identity_spec_sha256,
            "age_stage_appearance_sha256s": self.age_stage_appearance_sha256s,
            "selected_artifact_matrix_sha256": self.selected_artifact_matrix_sha256,
        }
        if self.glm_evidence.input_manifest_sha256 != visual_identity_digest(
            input_manifest
        ):
            raise ValueError(
                "cross-view GLM input manifest does not match selected artifact matrix"
            )
        _verify_digest(self, "qc_sha256")
        return self


class VisualIdentityReferenceSetV1(StrictFrozenModel):
    schema_version: Literal["visual-identity.reference-set.v1"]
    reference_set_id: Identifier
    character_id: Identifier
    visual_identity_mode: VisualIdentityMode
    identity_basis: VisualIdentityBasisV1
    character_identity_spec: CharacterIdentitySpecV1
    flux2_capability: Flux2DevCapabilityV1
    age_stage_specs: tuple[AgeStageAppearanceSpecV1, ...] = Field(min_length=1, max_length=12)
    views: tuple[VisualIdentityViewV1, ...] = Field(min_length=3, max_length=36)
    cross_view_qc: CrossViewVisualIdentityQCV1
    synthetic_disclosure: Literal["AI还原形象，非历史照片"] | None = None
    state: Literal["frozen"]
    reference_set_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_reference_set(self, info: ValidationInfo):
        expected_capability = (info.context or {}).get(
            "expected_flux2_capability"
        )
        if not isinstance(expected_capability, Flux2DevCapabilityV1):
            raise ValueError(
                "expected frozen FLUX2 capability authority must be injected"
            )
        if self.flux2_capability != expected_capability:
            raise ValueError(
                "payload FLUX2 capability does not match injected authority"
            )
        if (
            self.character_identity_spec.character_id != self.character_id
            or self.identity_basis.character_id != self.character_id
        ):
            raise ValueError("reference-set character lineage is inconsistent")
        if (
            self.character_identity_spec.identity_basis_kind
            != self.identity_basis.kind
            or self.character_identity_spec.identity_basis_sha256
            != self.identity_basis.basis_sha256
        ):
            raise ValueError("character identity spec does not match identity basis")
        expected_evidence_pack_sha256 = (
            self.identity_basis.discovery_sha256
            if isinstance(self.identity_basis, SearchedHistoricalIdentityBasisV1)
            else self.identity_basis.evidence_pack_sha256
        )
        if (
            self.character_identity_spec.evidence_pack_sha256
            != expected_evidence_pack_sha256
        ):
            raise ValueError(
                "character identity evidence pack does not match identity basis"
            )
        stage_names = tuple(item.age_stage for item in self.age_stage_specs)
        ordinals = tuple(item.ordinal for item in self.age_stage_specs)
        _unique(stage_names, "age stages")
        if ordinals != tuple(range(len(self.age_stage_specs))):
            raise ValueError("age stages must have contiguous ordinals from zero")
        if any(
            item.character_identity_spec_sha256
            != self.character_identity_spec.identity_spec_sha256
            for item in self.age_stage_specs
        ):
            raise ValueError("age-stage spec does not match character identity spec")
        for previous, current in zip(self.age_stage_specs, self.age_stage_specs[1:]):
            if current.minimum_age <= previous.maximum_age:
                raise ValueError("age-stage ranges must be ordered and non-overlapping")

        view_keys = tuple((view.age_stage, view.view_name.value) for view in self.views)
        _unique(view_keys, "age-stage views")
        expected_views = {
            (stage, view_name)
            for stage in stage_names
            for view_name in CANONICAL_VISUAL_IDENTITY_VIEWS
        }
        if set(view_keys) != expected_views:
            raise ValueError("views must contain every canonical angle for every age stage")
        expected_view_order = tuple(
            (stage, view_name)
            for stage in stage_names
            for view_name in CANONICAL_VISUAL_IDENTITY_VIEWS
        )
        if view_keys != expected_view_order:
            raise ValueError("views must use canonical age and angle order")
        artifact_matrix = tuple(
            {
                "age_stage": view.age_stage,
                "view_name": view.view_name.value,
                "artifact_id": view.selected_attempt.artifact_id,
                "artifact_sha256": view.selected_attempt.artifact_sha256,
            }
            for view in self.views
        )
        if (
            self.cross_view_qc.character_identity_spec_sha256
            != self.character_identity_spec.identity_spec_sha256
            or self.cross_view_qc.age_stage_appearance_sha256s
            != tuple(item.appearance_sha256 for item in self.age_stage_specs)
            or self.cross_view_qc.selected_artifact_matrix_sha256
            != visual_identity_digest(artifact_matrix)
        ):
            raise ValueError("cross-view QC does not match selected cross-age matrix")
        if not all(
            (
                self.cross_view_qc.identity_consistent,
                self.cross_view_qc.age_progression_consistent,
                self.cross_view_qc.attire_consistent,
                self.cross_view_qc.angles_complete,
                self.cross_view_qc.artifact_free,
            )
        ):
            raise ValueError("frozen reference set requires every cross-view QC gate")

        if isinstance(self.identity_basis, SearchedHistoricalIdentityBasisV1):
            if (
                self.visual_identity_mode is not VisualIdentityMode.HISTORICAL_IMAGE_GROUNDED
                or self.synthetic_disclosure is not None
            ):
                raise ValueError("historical basis requires historical public mode and no disclosure")
            grounded = tuple(
                item
                for item in self.age_stage_specs
                if item.appearance_basis is AppearanceBasis.HISTORICAL_STAGE_GROUNDED
            )
            if len(grounded) != 1:
                raise ValueError("single historical discovery requires exactly one grounded age stage")
            root_stage = grounded[0]
            if (
                root_stage.ordinal != 0
                or root_stage.age_stage != self.identity_basis.discovery.query_plan.age_stage
                or root_stage.historical_locator_sha256
                != self.identity_basis.selected_locator_sha256
                or root_stage.historical_content_sha256
                != self.identity_basis.selected_content_sha256
            ):
                raise ValueError("historical age-stage basis does not match selected source")
            for item in self.age_stage_specs:
                if item is root_stage:
                    continue
                if (
                    item.appearance_basis is not AppearanceBasis.CROSS_AGE_DERIVED
                    or item.cross_age_parent_stage != root_stage.age_stage
                    or item.cross_age_parent_sha256 != root_stage.appearance_sha256
                ):
                    raise ValueError("other historical ages must derive from the grounded age stage")
        else:
            if (
                self.visual_identity_mode is not VisualIdentityMode.SCRIPT_SYNTHESIZED
                or self.synthetic_disclosure != AI_SYNTHETIC_IDENTITY_DISCLOSURE
            ):
                raise ValueError("script basis requires script public mode and fixed disclosure")
            if any(
                item.appearance_basis is not AppearanceBasis.SCRIPT_SYNTHESIZED
                or item.script_basis_sha256 != self.identity_basis.basis_sha256
                for item in self.age_stage_specs
            ):
                raise ValueError("script age stages must bind the script basis digest")

        root_view = next(
            view
            for view in self.views
            if view.age_stage == stage_names[0]
            and view.view_name is VisualIdentityViewName.FRONT
        )
        root = root_view.selected_attempt
        flux_identity_fields = (
            "flux_model_family",
            "flux_runtime_profile",
            "flux2_capability_sha256",
            "diffusion_model_sha256",
            "text_encoder_sha256",
            "vae_sha256",
            "workflow_sha256",
        )
        capability_identity = (
            self.flux2_capability.flux_model_family,
            self.flux2_capability.flux_runtime_profile,
            self.flux2_capability.capability_sha256,
            self.flux2_capability.diffusion_model_sha256,
            self.flux2_capability.text_encoder_sha256,
            self.flux2_capability.vae_sha256,
            self.flux2_capability.workflow_sha256,
        )
        if any(
            tuple(getattr(attempt, field) for field in flux_identity_fields)
            != capability_identity
            for view in self.views
            for attempt in view.attempts
        ):
            raise ValueError(
                "all views must match the injected FLUX2 capability components and workflow"
            )
        if isinstance(self.identity_basis, SearchedHistoricalIdentityBasisV1):
            if any(
                attempt.generation_method is not GenerationMethod.FLUX_REFERENCE_EDIT
                or attempt.parent_artifact_id
                != self.identity_basis.selected_artifact_id
                or attempt.parent_artifact_sha256
                != self.identity_basis.selected_artifact_sha256
                for attempt in root_view.attempts
            ):
                raise ValueError(
                    "historical identity root must reference-edit the selected source artifact"
                )
        else:
            if root_view.attempts[0].generation_method is not GenerationMethod.FLUX_T2I:
                raise ValueError("script identity root attempt zero must be FLUX T2I")
            if any(
                attempt.generation_method is GenerationMethod.FLUX_T2I
                for view in self.views
                for attempt in view.attempts
                if attempt is not root_view.attempts[0]
            ):
                raise ValueError("script identity root permits exactly one actual FLUX T2I")

        views_by_key = {
            (view.age_stage, view.view_name.value): view
            for view in self.views
        }
        age_specs_by_stage = {
            item.age_stage: item
            for item in self.age_stage_specs
        }
        for view in self.views:
            if view is root_view:
                expected_parent_id = None
                expected_parent_sha256 = None
                expected_method = None
            elif view.view_name is VisualIdentityViewName.FRONT:
                expected_parent_id = root.artifact_id
                expected_parent_sha256 = root.artifact_sha256
                expected_method = GenerationMethod.FLUX_REFERENCE_EDIT
            else:
                stage_front = views_by_key[(view.age_stage, "front")].selected_attempt
                expected_parent_id = stage_front.artifact_id
                expected_parent_sha256 = stage_front.artifact_sha256
                expected_method = GenerationMethod.FLUX_REFERENCE_EDIT
            for attempt in view.attempts:
                age_spec = age_specs_by_stage[view.age_stage]
                if (
                    attempt.qc.character_identity_spec_sha256
                    != self.character_identity_spec.identity_spec_sha256
                    or attempt.qc.age_stage_appearance_sha256
                    != age_spec.appearance_sha256
                ):
                    raise ValueError("view QC does not match identity and age specs")
                if isinstance(self.identity_basis, SearchedHistoricalIdentityBasisV1):
                    if (
                        not isinstance(attempt.qc, SourceFidelityQCV1)
                        or attempt.qc.source_candidate_id
                        != self.identity_basis.selected_candidate_id
                        or attempt.qc.source_artifact_id
                        != self.identity_basis.selected_artifact_id
                        or attempt.qc.source_artifact_sha256
                        != self.identity_basis.selected_artifact_sha256
                        or attempt.qc.source_content_sha256
                        != self.identity_basis.selected_content_sha256
                        or attempt.qc.source_artifact_fence_sha256
                        != self.identity_basis.source_artifact_fence_sha256
                    ):
                        raise ValueError("historical generation requires matching source_fidelity QC")
                elif (
                    not isinstance(attempt.qc, AppearanceSpecFidelityQCV1)
                    or attempt.qc.script_basis_sha256 != self.identity_basis.basis_sha256
                ):
                    raise ValueError("script generation requires matching appearance_spec_fidelity QC")
                if view is not root_view and (
                    attempt.generation_method is not expected_method
                    or attempt.parent_artifact_id != expected_parent_id
                    or attempt.parent_artifact_sha256 != expected_parent_sha256
                ):
                    raise ValueError(
                        "generation lineage must follow identity root and age-front DAG"
                    )
        _verify_digest(self, "reference_set_sha256")
        return self

    @classmethod
    def validate_with_capability(
        cls,
        value: Any,
        *,
        expected_flux2_capability: Flux2DevCapabilityV1,
    ) -> "VisualIdentityReferenceSetV1":
        """Validate a payload against deployment/persistence-owned capability."""

        return cls.model_validate(
            value,
            context={
                "expected_flux2_capability": expected_flux2_capability,
            },
        )


__all__ = [
    "AI_SYNTHETIC_IDENTITY_DISCLOSURE",
    "CANONICAL_VISUAL_IDENTITY_VIEWS",
    "AgeStageAppearanceSpecV1",
    "AppearanceBasis",
    "AppearanceSpecFidelityQCV1",
    "CandidateFetchOutcome",
    "CandidateProvenanceV1",
    "CharacterIdentitySpecV1",
    "ControlledQueryPlanV1",
    "CrossViewVisualIdentityQCV1",
    "DiscoveryStatus",
    "FetchSecurityAttestationV1",
    "Flux2DevCapabilityV1",
    "GLMQCEvidenceV1",
    "GLMOutcome",
    "GLMVisionAttestationV1",
    "GenerationMethod",
    "HistoricalImageCandidateV1",
    "HistoricalSearchDiscoveryV1",
    "LicenseStatus",
    "RedirectSecurityReceiptV1",
    "ScriptSynthesizedIdentityBasisV1",
    "SearchCompletionAttestationV1",
    "SearchExecutionReceiptV1",
    "SearchedHistoricalIdentityBasisV1",
    "SourceFidelityQCV1",
    "VisualIdentityBasisV1",
    "VisualIdentityBlockedFailureV1",
    "VisualIdentityDecisionState",
    "VisualIdentityDiscoveryResultV1",
    "VisualIdentityMode",
    "VisualIdentityQCV1",
    "VisualIdentityReferenceSetV1",
    "VisualIdentityRetryableFailure",
    "VisualIdentityRetryableFailureV1",
    "VisualIdentityViewAttemptV1",
    "VisualIdentityViewName",
    "VisualIdentityViewV1",
    "visual_identity_digest",
]
