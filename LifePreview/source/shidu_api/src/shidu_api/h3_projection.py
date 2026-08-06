"""Project frozen logical H3 authorities into a public, path-free product DTO."""

from __future__ import annotations

import ipaddress
import hashlib
import hmac
import json
import math
import re
from collections.abc import Collection, Mapping, Sequence
from typing import Any, Literal, NoReturn, Protocol, TypeVar, TypedDict
from urllib.parse import unquote, urlsplit
from uuid import UUID

from pydantic import BaseModel, ValidationError
from shared_contracts.character_reference import CharacterReferenceSetV1
from shared_contracts.h3 import (
    EpisodeGenerationIRV1,
    H3AttemptSelectionV1,
    H3DeliveryV1,
    H3_PRODUCT_CONTRACT_VERSIONS,
    H3SequenceV1,
)


PROJECTION_SCHEMA = "shidu.h3-product-projection.v1"
CONTRACT_VERSIONS = H3_PRODUCT_CONTRACT_VERSIONS
FLUX_MODEL_FAMILY = "flux2-dev"
FLUX_MODEL_ID = "flux2-dev-fp8mixed.v1"
FLUX_DIFFUSION_MODEL_SHA256 = (
    "863a82e4ff950a42a6b0e80bea824828f129eb1a8fbbdbd9e8cb29859127b486"
)
FLUX_TEXT_ENCODER_SHA256 = (
    "e3467b7d912a234fb929cdf215dc08efdb011810b44bc21081c4234cc75b370e"
)
FLUX_VAE_SHA256 = (
    "d64f3a68e1cc4f9f4e29b6e0da38a0204fe9a49f2d4053f0ec1fa1ca02f9c4b5"
)
FLUX_CHARACTER_REFERENCE_WORKFLOW_SHA256 = (
    "60a8681d63ce3c01f43047b2bb137bfc327041e271e3b38d3fa974abeb012b87"
)
H3_MODEL_FAMILY = "minimax-h3"
CANONICAL_VIEWS = ("front", "three_quarter_left", "profile_left")
QC_FIELDS = (
    "media_integrity",
    "identity_and_semantics",
    "technical_quality",
    "aesthetic_quality",
)
CAPABILITY_FIELDS = (
    "model_family",
    "model_id",
    "diffusion_model_sha256",
    "text_encoder_sha256",
    "vae_sha256",
    "workflow_sha256",
    "revision",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]*$")
_DNS_HOST = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_WINDOWS_PATH = re.compile(r"(?:^|[\s(（])[A-Za-z]:[\\/]")
_POSIX_PATH = re.compile(
    r"(?:^|[\s(（])/(?:[A-Za-z0-9._~-]+/)*[A-Za-z0-9._~-]+"
)
_URI = re.compile(r"\b(?:file|https?|s3|gs|ftp):", re.IGNORECASE)
_FORBIDDEN_TEXT_MARKERS = (
    ".safetensors",
    "/persistent",
    "/workspace",
    "comfyui",
    ".srt",
    ".vtt",
    "subtitle",
    "gpu",
)
_IPV6_GLOBAL_UNICAST = ipaddress.IPv6Network("2000::/3")
_NON_PUBLIC_IPV6_NETWORKS = (
    ipaddress.IPv6Network("2001:db8::/32"),
    ipaddress.IPv6Network("2002::/16"),
    ipaddress.IPv6Network("3fff::/20"),
)
_IPV6_PROTOCOL_ASSIGNMENTS = ipaddress.IPv6Network("2001::/23")
_PUBLIC_IPV6_PROTOCOL_EXCEPTIONS = (
    ipaddress.IPv6Network("2001:1::1/128"),
    ipaddress.IPv6Network("2001:1::2/128"),
    ipaddress.IPv6Network("2001:1::3/128"),
    ipaddress.IPv6Network("2001:3::/32"),
    ipaddress.IPv6Network("2001:4:112::/48"),
    ipaddress.IPv6Network("2001:20::/28"),
    ipaddress.IPv6Network("2001:30::/28"),
)


class AssetUrlResolver(Protocol):
    """Resolve one logical asset id to a public URL at the server boundary."""

    def __call__(self, asset_id: str, /) -> str: ...


class H3DeliveryRecordLoader(Protocol):
    """Load one trusted append-only authority anchor inside a project boundary."""

    def __call__(
        self,
        delivery_record_id: str,
        expected_project_id: str,
        /,
    ) -> Mapping[str, Any]: ...


class FluxCapabilityInput(TypedDict):
    model_family: Literal["flux2-dev"]
    model_id: Literal["flux2-dev-fp8mixed.v1"]
    diffusion_model_sha256: Literal[
        "863a82e4ff950a42a6b0e80bea824828f129eb1a8fbbdbd9e8cb29859127b486"
    ]
    text_encoder_sha256: Literal[
        "e3467b7d912a234fb929cdf215dc08efdb011810b44bc21081c4234cc75b370e"
    ]
    vae_sha256: Literal[
        "d64f3a68e1cc4f9f4e29b6e0da38a0204fe9a49f2d4053f0ec1fa1ca02f9c4b5"
    ]
    workflow_sha256: Literal[
        "60a8681d63ce3c01f43047b2bb137bfc327041e271e3b38d3fa974abeb012b87"
    ]
    revision: Literal["flux2-dev-fp8mixed.v1"]


FLUX2_DEV_FP8_MIXED_CAPABILITY_V1: FluxCapabilityInput = {
    "model_family": "flux2-dev",
    "model_id": "flux2-dev-fp8mixed.v1",
    "diffusion_model_sha256": (
        "863a82e4ff950a42a6b0e80bea824828f129eb1a8fbbdbd9e8cb29859127b486"
    ),
    "text_encoder_sha256": (
        "e3467b7d912a234fb929cdf215dc08efdb011810b44bc21081c4234cc75b370e"
    ),
    "vae_sha256": (
        "d64f3a68e1cc4f9f4e29b6e0da38a0204fe9a49f2d4053f0ec1fa1ca02f9c4b5"
    ),
    "workflow_sha256": (
        "60a8681d63ce3c01f43047b2bb137bfc327041e271e3b38d3fa974abeb012b87"
    ),
    "revision": "flux2-dev-fp8mixed.v1",
}


class H3DeliveryDigestAnchorV1(TypedDict):
    delivery_record_id: str
    project_id: str
    delivery_digest: str
    authority_digest: str


class H3ProductAuthorityInput(TypedDict):
    contract_versions: Mapping[str, str]
    episode: Mapping[str, Any]
    final_sequences: Sequence[Mapping[str, Any]]
    delivery: Mapping[str, Any]


class H3SourceGroundedDisclosureDTO(TypedDict):
    code: Literal["SOURCE_GROUNDED"]
    contentMode: Literal["source_grounded"]
    label: str
    notice: str


class H3AICompletedDisclosureDTO(TypedDict):
    code: Literal["AI_COMPLETED_NON_ORIGINAL"]
    contentMode: Literal["ai_completed"]
    label: str
    notice: str


H3DisclosureDTO = H3SourceGroundedDisclosureDTO | H3AICompletedDisclosureDTO


class H3ReferenceCardDTO(TypedDict):
    referenceSetId: str
    referenceSetRevisionId: str
    characterId: str
    ageStage: str
    viewName: Literal["front", "three_quarter_left", "profile_left"]
    attemptOrdinal: Literal[0, 1]
    imageUrl: str
    qcPassed: Literal[True]
    modelFamily: Literal["flux2-dev"]
    modelId: Literal["flux2-dev-fp8mixed.v1"]
    revision: Literal["flux2-dev-fp8mixed.v1"]


class H3QcVectorDTO(TypedDict):
    mediaIntegrity: float
    identityAndSemantics: float
    technicalQuality: float
    aestheticQuality: float


class H3AttemptDTO(TypedDict):
    attemptOrdinal: Literal[0, 1]
    qcVector: H3QcVectorDTO
    exceptionCodes: list[str]


class H3SequenceDTO(TypedDict):
    sequenceId: str
    ordinal: int
    durationSeconds: float
    status: Literal["delivered"]
    attempts: list[H3AttemptDTO]
    selectedAttemptOrdinal: Literal[0, 1]
    selectedCleanly: bool
    selectedWithQcException: bool
    exceptionCodes: list[str]
    selectionReason: str


class H3ProductProjectionDTO(TypedDict):
    schemaVersion: Literal["shidu.h3-product-projection.v1"]
    episodeRevisionId: str
    projectId: str
    status: Literal["succeeded"]
    durationSeconds: float
    referenceCards: list[H3ReferenceCardDTO]
    sequences: list[H3SequenceDTO]
    playbackUrl: str
    downloadUrl: str
    disclosure: H3DisclosureDTO


class H3ProjectionError(ValueError):
    """The logical authority cannot safely produce a public H3 DTO."""


def _fail(message: str) -> NoReturn:
    raise H3ProjectionError(message)


FrozenAuthority = TypeVar("FrozenAuthority", bound=BaseModel)


def _frozen_authority(
    model: type[FrozenAuthority],
    value: Any,
    field: str,
) -> FrozenAuthority:
    try:
        return model.model_validate(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise H3ProjectionError(
            f"{field} failed frozen authority validation: {exc}"
        ) from exc


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{field} must be an object")
    return value


def _array(value: Any, field: str) -> Sequence[Any]:
    if not isinstance(value, (list, tuple)):
        _fail(f"{field} must be an array")
    return value


def _exact_keys(value: Mapping[str, Any], expected: Collection[str], field: str) -> None:
    expected_set = set(expected)
    if any(not isinstance(key, str) for key in value):
        _fail(f"{field} must use string field names")
    actual_set = set(value)
    if actual_set != expected_set:
        missing = sorted(expected_set - actual_set)
        extra = sorted(actual_set - expected_set)
        _fail(f"{field} fields mismatch; missing={missing}, extra={extra}")


def _string(value: Any, field: str, *, max_length: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        _fail(f"{field} must be a non-empty string")
    return value


def _identifier(value: Any, field: str) -> str:
    identifier = _string(value, field, max_length=160)
    if _IDENTIFIER.fullmatch(identifier) is None:
        _fail(f"{field} must be a stable logical identifier")
    return identifier


def _uuid(value: Any, field: str) -> str:
    text = _string(value, field, max_length=36)
    try:
        parsed = UUID(text)
    except (TypeError, ValueError) as exc:
        raise H3ProjectionError(f"{field} must be a UUID") from exc
    canonical = str(parsed)
    if text.casefold() != canonical:
        _fail(f"{field} must use canonical UUID form")
    return canonical


def _sha256(value: Any, field: str) -> str:
    digest = _string(value, field, max_length=64)
    if _SHA256.fullmatch(digest) is None:
        _fail(f"{field} must be a lowercase SHA-256 digest")
    return digest


def _load_delivery_anchor(
    delivery_record_id: Any,
    expected_project_id: Any,
    delivery_record_loader: H3DeliveryRecordLoader,
) -> H3DeliveryDigestAnchorV1:
    record_id = _uuid(delivery_record_id, "delivery_record_id")
    authenticated_project_id = _uuid(
        expected_project_id,
        "expected_project_id",
    )
    if not callable(delivery_record_loader):
        _fail("delivery_record_loader must be callable")
    try:
        raw_anchor = delivery_record_loader(record_id, authenticated_project_id)
    except Exception as exc:
        raise H3ProjectionError("persisted delivery record loader failed") from exc
    anchor = _mapping(raw_anchor, "persisted delivery record")
    _exact_keys(
        anchor,
        {
            "delivery_record_id",
            "project_id",
            "delivery_digest",
            "authority_digest",
        },
        "persisted delivery record",
    )
    persisted_record_id = _uuid(
        anchor.get("delivery_record_id"),
        "persisted delivery record.delivery_record_id",
    )
    if persisted_record_id != record_id:
        _fail("persisted delivery record id does not match requested record id")
    persisted_project_id = _uuid(
        anchor.get("project_id"),
        "persisted delivery record.project_id",
    )
    if persisted_project_id != authenticated_project_id:
        _fail("persisted delivery record project does not match authenticated project")
    return {
        "delivery_record_id": persisted_record_id,
        "project_id": persisted_project_id,
        "delivery_digest": _sha256(
            anchor.get("delivery_digest"),
            "persisted delivery record.delivery_digest",
        ),
        "authority_digest": _sha256(
            anchor.get("authority_digest"),
            "persisted delivery record.authority_digest",
        ),
    }


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(f"{field} must be an integer")
    return value


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{field} must be a number")
    number = float(value)
    if not math.isfinite(number):
        _fail(f"{field} must be finite")
    return number


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        _fail(f"{field} must be a boolean")
    return value


def _literal(value: Any, expected: str, field: str) -> str:
    if value != expected:
        _fail(f"{field} must equal {expected}")
    return expected


def _identifiers(value: Any, field: str, *, non_empty: bool = False) -> list[str]:
    items = [_identifier(item, f"{field}[]") for item in _array(value, field)]
    if non_empty and not items:
        _fail(f"{field} must not be empty")
    if len(items) != len(set(items)):
        _fail(f"{field} must contain unique identifiers")
    return items


def _decode_repeated(value: str) -> str:
    decoded = value
    for _ in range(4):
        next_value = unquote(decoded)
        if next_value == decoded:
            return decoded
        decoded = next_value
    _fail("URL or text contains excessive nested encoding")


def _public_text(value: Any, field: str) -> str:
    text = _string(value, field)
    decoded = _decode_repeated(text)
    lowered = decoded.casefold()
    if (
        "\\" in decoded
        or _WINDOWS_PATH.search(decoded)
        or _POSIX_PATH.search(decoded)
        or _URI.search(decoded)
        or any(marker in lowered for marker in _FORBIDDEN_TEXT_MARKERS)
    ):
        _fail(f"{field} public text contains a file path or URI")
    return text


def _normalize_allowlist(values: Collection[str]) -> frozenset[str]:
    if isinstance(values, str):
        _fail("https_host_allowlist must be a collection of hostnames")
    hosts: set[str] = set()
    for value in values:
        raw_host = _string(value, "https_host_allowlist[]", max_length=253)
        if raw_host != raw_host.strip() or any(
            marker in raw_host for marker in ("/", "\\", "@", "#", "?")
        ):
            _fail("HTTPS allowlist entries must be hostnames without URL syntax")
        host = _canonical_host(raw_host, "https_host_allowlist[]")
        if ":" not in host and "." not in host:
            _fail("HTTPS allowlist entry must be a public DNS name or IP address")
        hosts.add(host)
    return frozenset(hosts)


def _canonical_host(value: str, field: str) -> str:
    host = value.casefold()
    if host.endswith("."):
        host = host[:-1]
    if host.startswith("[") or host.endswith("]"):
        if not (host.startswith("[") and host.endswith("]")):
            _fail(f"{field} hostname is malformed")
        host = host[1:-1]
    if not host:
        _fail(f"{field} hostname is malformed")
    try:
        address = ipaddress.ip_address(host)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            mapped = int(address.ipv4_mapped)
            return f"::ffff:{mapped >> 16:x}:{mapped & 0xffff:x}"
        return str(address)
    except ValueError:
        if ":" in host or _DNS_HOST.fullmatch(host) is None:
            _fail(f"{field} hostname is malformed")
        numeric_parts = host.split(".")
        if len(numeric_parts) == 4 and all(part.isdigit() for part in numeric_parts):
            _fail(f"{field} hostname is malformed")
        return host


def _host_is_private(host: str) -> bool:
    lowered = host.casefold().rstrip(".")
    if lowered == "localhost" or lowered.endswith(
        (".localhost", ".local", ".internal", ".lan")
    ):
        return True
    numeric_parts = lowered.split(".")
    if len(numeric_parts) == 4 and all(part.isdigit() for part in numeric_parts):
        if any(len(part) > 1 and part.startswith("0") for part in numeric_parts):
            return True
    if lowered.startswith("0x") or any(part.startswith("0x") for part in numeric_parts):
        return True
    try:
        address = ipaddress.ip_address(lowered)
        if isinstance(address, ipaddress.IPv6Address):
            if address.ipv4_mapped is not None:
                address = address.ipv4_mapped
            else:
                if address not in _IPV6_GLOBAL_UNICAST or any(
                    address in network for network in _NON_PUBLIC_IPV6_NETWORKS
                ):
                    return True
                if address in _IPV6_PROTOCOL_ASSIGNMENTS:
                    return not any(
                        address in network
                        for network in _PUBLIC_IPV6_PROTOCOL_EXCEPTIONS
                    )
                return False
        return (
            not address.is_global
            or address.is_multicast
            or getattr(address, "is_site_local", False)
        )
    except ValueError:
        if lowered.isdigit():
            try:
                return not ipaddress.IPv4Address(int(lowered)).is_global
            except ValueError:
                return True
        return False


def _validate_path(path: str, field: str, *, artifacts_only: bool) -> str:
    if not path.startswith("/") or "//" in path:
        _fail(f"{field} URL path is not canonical")
    segments = path.split("/")[1:]
    if artifacts_only:
        if not segments or segments[0] != "artifacts":
            _fail(f"{field} URL must use /artifacts/<safe segments>")
        segments = segments[1:]
    if not segments or any(
        segment in ("", ".", "..") or _SAFE_SEGMENT.fullmatch(segment) is None
        for segment in segments
    ):
        _fail(f"{field} URL contains an unsafe path segment")
    return path


def _public_url(value: Any, field: str, allowlist: frozenset[str]) -> str:
    url = _string(value, field, max_length=2048)
    if url != url.strip() or any(ord(char) < 32 for char in url):
        _fail(f"{field} URL contains whitespace or control characters")
    decoded = _decode_repeated(url)
    if decoded != url or "\\" in decoded:
        _fail(f"{field} URL is not canonically encoded")
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise H3ProjectionError(f"{field} URL is malformed") from exc
    if parts.query or parts.fragment:
        _fail(f"{field} URL cannot contain query or fragment secrets")

    if not parts.scheme:
        if parts.netloc or parts.username or parts.password:
            _fail(f"{field} URL cannot be UNC or credential-bearing")
        return _validate_path(parts.path, field, artifacts_only=True)

    if parts.scheme.casefold() != "https":
        _fail(f"{field} URL must be relative /artifacts or HTTPS")
    if parts.username is not None or parts.password is not None:
        _fail(f"{field} URL cannot contain credentials")
    raw_host = parts.hostname or ""
    host = _canonical_host(raw_host, field)
    if not host or host not in allowlist:
        _fail(f"{field} URL hostname is not explicitly allowlisted")
    if _host_is_private(host):
        _fail(f"{field} URL hostname cannot be loopback, private, or non-public")
    try:
        port = parts.port
    except ValueError as exc:
        raise H3ProjectionError(f"{field} URL port is invalid") from exc
    if port not in (None, 443):
        _fail(f"{field} URL must use the default HTTPS port")
    if ":" not in host and not re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
        if _DNS_HOST.fullmatch(host) is None or "." not in host:
            _fail(f"{field} URL hostname is malformed or not public")
    path = _validate_path(parts.path, field, artifacts_only=False)
    authority = f"[{host}]" if ":" in host else host
    return f"https://{authority}{path}"


def _reject_raw_authority_fields(value: Any, field: str = "authority") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized = key.casefold().replace("_", "")
            if "url" in normalized:
                _fail(f"{field}.{key} is a raw URL field; use asset_id resolver")
            if "subtitle" in normalized:
                _fail(f"{field}.{key} is a forbidden subtitle field")
            if normalized in {
                "path",
                "filepath",
                "physicalpath",
                "modelfilename",
                "gpu",
                "gpuid",
                "gpuarchitecture",
                "comfyui",
                "nodeid",
            }:
                _fail(f"{field}.{key} is a forbidden physical binding field")
            if normalized == "workflow":
                _fail(f"{field}.{key} cannot expose a workflow object")
            _reject_raw_authority_fields(child, f"{field}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_raw_authority_fields(child, f"{field}[{index}]")


def _capability(value: Any) -> dict[str, str]:
    capability = _mapping(value, "flux_capability")
    _exact_keys(capability, CAPABILITY_FIELDS, "flux_capability")
    result = {
        "model_family": _literal(
            capability.get("model_family"), FLUX_MODEL_FAMILY, "flux_capability.model_family"
        ),
        "model_id": _literal(
            capability.get("model_id"), FLUX_MODEL_ID, "flux_capability.model_id"
        ),
        "diffusion_model_sha256": _sha256(
            capability.get("diffusion_model_sha256"),
            "flux_capability.diffusion_model_sha256",
        ),
        "text_encoder_sha256": _sha256(
            capability.get("text_encoder_sha256"),
            "flux_capability.text_encoder_sha256",
        ),
        "vae_sha256": _sha256(
            capability.get("vae_sha256"), "flux_capability.vae_sha256"
        ),
        "workflow_sha256": _sha256(
            capability.get("workflow_sha256"), "flux_capability.workflow_sha256"
        ),
        "revision": _literal(
            capability.get("revision"), FLUX_MODEL_ID, "flux_capability.revision"
        ),
    }
    expected_hashes = {
        "diffusion_model_sha256": FLUX_DIFFUSION_MODEL_SHA256,
        "text_encoder_sha256": FLUX_TEXT_ENCODER_SHA256,
        "vae_sha256": FLUX_VAE_SHA256,
        "workflow_sha256": FLUX_CHARACTER_REFERENCE_WORKFLOW_SHA256,
    }
    for field, expected in expected_hashes.items():
        if not hmac.compare_digest(result[field], expected):
            _fail(f"flux_capability.{field} does not match the frozen AMD SHA-256")
    return result


def _model_revision(
    value: Any,
    capability: Mapping[str, str],
    field: str,
) -> None:
    revision = _mapping(value, field)
    _exact_keys(revision, CAPABILITY_FIELDS, field)
    for name in CAPABILITY_FIELDS:
        if name.endswith("sha256"):
            actual = _sha256(revision.get(name), f"{field}.{name}")
        else:
            actual = _string(revision.get(name), f"{field}.{name}", max_length=160)
        if actual != capability[name]:
            _fail(f"{field}.{name} does not match frozen FLUX capability")


def _reference_set(
    value: Any,
    capability: Mapping[str, str],
    field: str,
    asset_templates: list[dict[str, Any]],
) -> tuple[str, str, str, str]:
    reference_model = _frozen_authority(CharacterReferenceSetV1, value, field)
    reference = _mapping(reference_model.model_dump(mode="json"), field)
    _exact_keys(
        reference,
        {
            "reference_set_id",
            "reference_set_revision_id",
            "character_id",
            "age_stage",
            "source_asset",
            "model_revision",
            "views",
            "cross_view_qc",
            "state",
            "reference_set_digest",
        },
        field,
    )
    reference_set_id = _uuid(reference.get("reference_set_id"), f"{field}.reference_set_id")
    revision_id = _uuid(
        reference.get("reference_set_revision_id"),
        f"{field}.reference_set_revision_id",
    )
    character_id = _identifier(reference.get("character_id"), f"{field}.character_id")
    age_stage = _identifier(reference.get("age_stage"), f"{field}.age_stage")
    _literal(reference.get("state"), "frozen", f"{field}.state")
    _sha256(reference.get("reference_set_digest"), f"{field}.reference_set_digest")
    _model_revision(reference.get("model_revision"), capability, f"{field}.model_revision")

    source = _mapping(reference.get("source_asset"), f"{field}.source_asset")
    _exact_keys(
        source,
        {
            "asset_id",
            "content_digest",
            "verified",
            "historical",
            "ai_derived",
            "uploaded_by",
            "uploaded_at",
        },
        f"{field}.source_asset",
    )
    _uuid(source.get("asset_id"), f"{field}.source_asset.asset_id")
    _sha256(source.get("content_digest"), f"{field}.source_asset.content_digest")
    if not _boolean(source.get("verified"), f"{field}.source_asset.verified"):
        _fail(f"{field}.source_asset must be verified")
    if not _boolean(source.get("historical"), f"{field}.source_asset.historical"):
        _fail(f"{field}.source_asset must be historical")
    if _boolean(source.get("ai_derived"), f"{field}.source_asset.ai_derived"):
        _fail(f"{field}.source_asset cannot be AI-derived")
    _identifier(source.get("uploaded_by"), f"{field}.source_asset.uploaded_by")
    _string(source.get("uploaded_at"), f"{field}.source_asset.uploaded_at")

    cross_qc = _mapping(reference.get("cross_view_qc"), f"{field}.cross_view_qc")
    for name in (
        "identity_consistent",
        "age_consistent",
        "attire_consistent",
        "angle_correct",
        "no_artifact",
    ):
        if not _boolean(cross_qc.get(name), f"{field}.cross_view_qc.{name}"):
            _fail(f"{field}.cross_view_qc must pass every gate")

    views = _array(reference.get("views"), f"{field}.views")
    if len(views) != 3:
        _fail(f"{field}.views must contain the three canonical views")
    asset_ids: set[str] = set()
    image_digests: set[str] = set()
    for index, expected_view in enumerate(CANONICAL_VIEWS):
        view_field = f"{field}.views[{index}]"
        view = _mapping(views[index], view_field)
        _exact_keys(
            view,
            {
                "asset_id",
                "view_name",
                "attempt_ordinal",
                "image_digest",
                "ai_derived",
                "historical",
                "identity_control",
                "model_revision",
                "single_view_qc_passed",
                "generated_at",
            },
            view_field,
        )
        _literal(view.get("view_name"), expected_view, f"{view_field}.view_name")
        asset_id = _uuid(view.get("asset_id"), f"{view_field}.asset_id")
        image_digest = _sha256(view.get("image_digest"), f"{view_field}.image_digest")
        if asset_id in asset_ids or image_digest in image_digests:
            _fail(f"{field}.views must use unique asset ids and image digests")
        asset_ids.add(asset_id)
        image_digests.add(image_digest)
        attempt_ordinal = _integer(view.get("attempt_ordinal"), f"{view_field}.attempt_ordinal")
        if attempt_ordinal not in (0, 1):
            _fail(f"{view_field}.attempt_ordinal must be 0 or 1")
        if not _boolean(view.get("ai_derived"), f"{view_field}.ai_derived"):
            _fail(f"{view_field} must be AI-derived")
        if _boolean(view.get("historical"), f"{view_field}.historical"):
            _fail(f"{view_field} cannot be historical")
        if not _boolean(view.get("identity_control"), f"{view_field}.identity_control"):
            _fail(f"{view_field} must be identity control")
        if not _boolean(
            view.get("single_view_qc_passed"),
            f"{view_field}.single_view_qc_passed",
        ):
            _fail(f"{view_field} must pass QC")
        _model_revision(view.get("model_revision"), capability, f"{view_field}.model_revision")
        asset_templates.append(
            {
                "assetId": asset_id,
                "referenceSetId": reference_set_id,
                "referenceSetRevisionId": revision_id,
                "characterId": character_id,
                "ageStage": age_stage,
                "viewName": expected_view,
                "attemptOrdinal": attempt_ordinal,
                "qcPassed": True,
                "modelFamily": FLUX_MODEL_FAMILY,
                "modelId": FLUX_MODEL_ID,
                "revision": FLUX_MODEL_ID,
            }
        )
    return revision_id, reference_set_id, character_id, age_stage


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise H3ProjectionError("authority must contain only finite JSON values") from exc


def _candidate(value: Any, sequence_id: str, field: str) -> dict[str, Any]:
    candidate = _mapping(value, field)
    _exact_keys(
        candidate,
        {
            "sequence_id",
            "attempt_ordinal",
            "media_integrity",
            "identity_and_semantics",
            "technical_quality",
            "aesthetic_quality",
            "exception_codes",
        },
        field,
    )
    if _uuid(candidate.get("sequence_id"), f"{field}.sequence_id") != sequence_id:
        _fail(f"{field}.sequence_id does not match the final sequence")
    ordinal = _integer(candidate.get("attempt_ordinal"), f"{field}.attempt_ordinal")
    if ordinal not in (0, 1):
        _fail(f"{field}.attempt_ordinal must be 0 or 1")
    vector: dict[str, float] = {}
    for name in QC_FIELDS:
        score = _number(candidate.get(name), f"{field}.{name}")
        if not 0.0 <= score <= 1.0:
            _fail(f"{field}.{name} must be between 0 and 1")
        vector[name] = score
    raw_exceptions = _identifiers(candidate.get("exception_codes"), f"{field}.exception_codes")
    return {
        "attempt_ordinal": ordinal,
        "vector": vector,
        "raw_exceptions": raw_exceptions,
        "exception_codes": sorted(raw_exceptions),
    }


def _candidate_rank(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        not candidate["exception_codes"],
        *(candidate["vector"][name] for name in QC_FIELDS),
        -candidate["attempt_ordinal"],
    )


def _lineage(value: Any, expected_ordinal: int, field: str) -> dict[str, Any]:
    lineage = _mapping(value, field)
    _exact_keys(
        lineage,
        {
            "attempt_ordinal",
            "artifact_digest",
            "qc_evidence_ids",
            "repair_trigger_codes",
            "generated_at",
        },
        field,
    )
    if _integer(lineage.get("attempt_ordinal"), f"{field}.attempt_ordinal") != expected_ordinal:
        _fail(f"{field}.attempt_ordinal must equal {expected_ordinal}")
    result = {
        "attempt_ordinal": expected_ordinal,
        "artifact_digest": _sha256(
            lineage.get("artifact_digest"), f"{field}.artifact_digest"
        ),
        "qc_evidence_ids": _identifiers(
            lineage.get("qc_evidence_ids"), f"{field}.qc_evidence_ids", non_empty=True
        ),
        "repair_trigger_codes": _identifiers(
            lineage.get("repair_trigger_codes"), f"{field}.repair_trigger_codes"
        ),
    }
    _string(lineage.get("generated_at"), f"{field}.generated_at")
    return result


def _selection(
    value: Any,
    sequence_id: str,
    initial: Mapping[str, Any],
    repair: Mapping[str, Any] | None,
    field: str,
) -> tuple[dict[str, Any], Mapping[str, Any]]:
    selection_model = _frozen_authority(H3AttemptSelectionV1, value, field)
    selection = _mapping(selection_model.model_dump(mode="json"), field)
    _exact_keys(
        selection,
        {
            "sequence_id",
            "candidates",
            "selected_attempt_ordinal",
            "selected_cleanly",
            "selected_with_qc_exception",
            "exception_codes",
            "qc_policy_revision",
            "selected_at",
            "selection_reason",
            "selection_digest",
        },
        field,
    )
    if _uuid(selection.get("sequence_id"), f"{field}.sequence_id") != sequence_id:
        _fail(f"{field}.sequence_id does not match the sequence plan")
    _literal(
        selection.get("qc_policy_revision"),
        "h3.selection.v1",
        f"{field}.qc_policy_revision",
    )
    _string(selection.get("selected_at"), f"{field}.selected_at")
    _sha256(selection.get("selection_digest"), f"{field}.selection_digest")
    reason = _public_text(selection.get("selection_reason"), f"{field}.selection_reason")

    raw_candidates = _array(selection.get("candidates"), f"{field}.candidates")
    expected_ordinals = (0,) if repair is None else (0, 1)
    if len(raw_candidates) != len(expected_ordinals):
        _fail(f"{field}.candidates must exactly match available attempts")
    candidates = [
        _candidate(candidate, sequence_id, f"{field}.candidates[{index}]")
        for index, candidate in enumerate(raw_candidates)
    ]
    by_ordinal = {candidate["attempt_ordinal"]: candidate for candidate in candidates}
    if tuple(sorted(by_ordinal)) != expected_ordinals or len(by_ordinal) != len(candidates):
        _fail(f"{field}.candidates must contain exactly attempts {expected_ordinals}")

    initial_candidate = by_ordinal[0]
    if repair is not None:
        if not initial_candidate["exception_codes"]:
            _fail("a clean initial attempt forbids a repair attempt")
        trigger_codes = set(repair["repair_trigger_codes"])
        if not trigger_codes:
            _fail("repair_attempt.repair_trigger_codes must not be empty")
        if not trigger_codes.issubset(set(initial_candidate["raw_exceptions"])):
            _fail("repair trigger codes must come from initial QC exceptions")

    winner = max(candidates, key=_candidate_rank)
    selected_ordinal = _integer(
        selection.get("selected_attempt_ordinal"),
        f"{field}.selected_attempt_ordinal",
    )
    if selected_ordinal != winner["attempt_ordinal"]:
        _fail(f"{field}.selected_attempt_ordinal violates deterministic ranking")
    selected = by_ordinal[selected_ordinal]
    clean = not selected["exception_codes"]
    if _boolean(selection.get("selected_cleanly"), f"{field}.selected_cleanly") != clean:
        _fail(f"{field}.selected_cleanly disagrees with selected QC")
    if _boolean(
        selection.get("selected_with_qc_exception"),
        f"{field}.selected_with_qc_exception",
    ) != (not clean):
        _fail(f"{field}.selected_with_qc_exception disagrees with selected QC")
    declared = _identifiers(selection.get("exception_codes"), f"{field}.exception_codes")
    if declared != selected["raw_exceptions"]:
        _fail(f"{field}.exception_codes must exactly match the selected candidate")

    projected_attempts = []
    for ordinal in expected_ordinals:
        candidate = by_ordinal[ordinal]
        projected_attempts.append(
            {
                "attemptOrdinal": ordinal,
                "qcVector": {
                    "mediaIntegrity": candidate["vector"]["media_integrity"],
                    "identityAndSemantics": candidate["vector"][
                        "identity_and_semantics"
                    ],
                    "technicalQuality": candidate["vector"]["technical_quality"],
                    "aestheticQuality": candidate["vector"]["aesthetic_quality"],
                },
                "exceptionCodes": candidate["exception_codes"],
            }
        )
    return (
        {
            "attempts": projected_attempts,
            "selectedAttemptOrdinal": selected_ordinal,
            "selectedCleanly": clean,
            "selectedWithQcException": not clean,
            "exceptionCodes": selected["exception_codes"],
            "selectionReason": reason,
        },
        selected,
    )


def _validate_sequence_plan(
    plan: Mapping[str, Any],
    project_subjects: Mapping[str, tuple[str, str]],
    declared_revisions: set[str],
    capability: Mapping[str, str],
    field: str,
    asset_templates: list[dict[str, Any]],
    reference_authorities: dict[str, str],
) -> tuple[str, int, float]:
    _exact_keys(
        plan,
        {
            "sequence_id",
            "ordinal",
            "mode",
            "frame_count",
            "fps",
            "duration_seconds",
            "requested_duration_seconds",
            "reference_bindings",
            "shots",
            "audio_plan",
            "evidence_ids",
        },
        field,
    )
    sequence_id = _uuid(plan.get("sequence_id"), f"{field}.sequence_id")
    ordinal = _integer(plan.get("ordinal"), f"{field}.ordinal")
    if ordinal < 1:
        _fail(f"{field}.ordinal must be positive")
    _literal(plan.get("mode"), "ref2va", f"{field}.mode")
    if _integer(plan.get("fps"), f"{field}.fps") != 24:
        _fail(f"{field}.fps must equal 24")
    frame_count = _integer(plan.get("frame_count"), f"{field}.frame_count")
    if not 73 <= frame_count <= 362 or frame_count % 17 != 5:
        _fail(f"{field}.frame_count is outside the H3 17n+5 grid")
    duration = _number(plan.get("duration_seconds"), f"{field}.duration_seconds")
    if not math.isclose(duration, frame_count / 24, rel_tol=0.0, abs_tol=1e-9):
        _fail(f"{field}.duration_seconds must equal frame_count / 24")
    requested = _number(
        plan.get("requested_duration_seconds"),
        f"{field}.requested_duration_seconds",
    )
    if not 3.0 <= requested <= 15.0:
        _fail(f"{field}.requested_duration_seconds must be between 3 and 15")
    required_frames = math.ceil(requested * 24 - 1e-12)
    if frame_count != required_frames + ((5 - required_frames) % 17):
        _fail(f"{field}.frame_count is not the upward H3 grid snap")

    bindings = _array(plan.get("reference_bindings"), f"{field}.reference_bindings")
    if not bindings:
        _fail(f"{field}.reference_bindings must not be empty")
    binding_subjects: set[str] = set()
    for index, raw_binding in enumerate(bindings):
        binding_field = f"{field}.reference_bindings[{index}]"
        binding = _mapping(raw_binding, binding_field)
        _exact_keys(binding, {"subject_id", "reference_set"}, binding_field)
        subject_id = _identifier(binding.get("subject_id"), f"{binding_field}.subject_id")
        if subject_id in binding_subjects or subject_id not in project_subjects:
            _fail(f"{binding_field}.subject_id is duplicate or undeclared")
        binding_subjects.add(subject_id)
        before_templates = len(asset_templates)
        revision_id, _, character_id, age_stage = _reference_set(
            binding.get("reference_set"),
            capability,
            f"{binding_field}.reference_set",
            asset_templates,
        )
        if revision_id not in declared_revisions:
            _fail(f"{binding_field} uses an undeclared reference_set_revision_id")
        if project_subjects[subject_id] != (character_id, age_stage):
            _fail(f"{binding_field} reference does not match project subject")
        canonical_reference = _canonical(
            _mapping(binding.get("reference_set"), f"{binding_field}.reference_set")
        )
        previous = reference_authorities.setdefault(revision_id, canonical_reference)
        if previous != canonical_reference:
            _fail("the same reference_set_revision_id has conflicting authorities")
        if previous == canonical_reference and revision_id in reference_authorities:
            if any(
                template["referenceSetRevisionId"] == revision_id
                for template in asset_templates[:before_templates]
            ):
                del asset_templates[before_templates:]

    audio = _mapping(plan.get("audio_plan"), f"{field}.audio_plan")
    _literal(audio.get("voice_source"), "h3_native", f"{field}.audio_plan.voice_source")
    _array(plan.get("shots"), f"{field}.shots")
    _identifiers(plan.get("evidence_ids"), f"{field}.evidence_ids", non_empty=True)
    return sequence_id, ordinal, duration


def project_h3_product(
    authority: H3ProductAuthorityInput,
    *,
    expected_project_id: str,
    delivery_record_id: str,
    delivery_record_loader: H3DeliveryRecordLoader,
    asset_url_resolver: AssetUrlResolver,
    flux_capability: FluxCapabilityInput,
    https_host_allowlist: Collection[str] = (),
) -> H3ProductProjectionDTO:
    """Validate a project-bound persisted H3 authority and expose public URLs."""

    delivery_anchor = _load_delivery_anchor(
        delivery_record_id,
        expected_project_id,
        delivery_record_loader,
    )
    root = _mapping(authority, "authority")
    _exact_keys(
        root,
        {"contract_versions", "episode", "final_sequences", "delivery"},
        "authority",
    )
    payload_authority_digest = hashlib.sha256(
        _canonical(root).encode("utf-8")
    ).hexdigest()
    if not hmac.compare_digest(
        payload_authority_digest,
        delivery_anchor["authority_digest"],
    ):
        _fail("authority digest does not match persisted authority digest anchor")
    raw_delivery = _mapping(root.get("delivery"), "delivery")
    _exact_keys(
        raw_delivery,
        {
            "episode_revision_id",
            "status",
            "assembly_manifest",
            "disclosure",
            "delivery_digest",
        },
        "delivery",
    )
    payload_delivery_digest = _sha256(
        raw_delivery.get("delivery_digest"),
        "delivery.delivery_digest",
    )
    if not hmac.compare_digest(
        payload_delivery_digest,
        delivery_anchor["delivery_digest"],
    ):
        _fail("delivery digest does not match persisted delivery digest anchor")
    _reject_raw_authority_fields(root)
    versions = _mapping(root.get("contract_versions"), "contract_versions")
    _exact_keys(versions, CONTRACT_VERSIONS, "contract_versions")
    for name, expected in CONTRACT_VERSIONS.items():
        _literal(versions.get(name), expected, f"contract_versions.{name}")
    if not callable(asset_url_resolver):
        _fail("asset_url_resolver must be callable")
    allowlist = _normalize_allowlist(https_host_allowlist)
    capability = _capability(flux_capability)

    raw_episode = _mapping(root.get("episode"), "episode")
    _exact_keys(
        raw_episode,
        {
            "episode_revision_id",
            "project_ir_id",
            "project_ir_revision_digest",
            "project_ir",
            "reference_set_revision_ids",
            "model_family",
            "sequence_plans",
            "duration_allocation_digest",
            "model_trace",
            "revision_digest",
        },
        "episode",
    )
    raw_project_id = _uuid(
        raw_episode.get("project_ir_id"),
        "episode.project_ir_id",
    )
    if raw_project_id != delivery_anchor["project_id"]:
        _fail("persisted delivery record project does not match Episode project")
    episode_model = _frozen_authority(
        EpisodeGenerationIRV1,
        raw_episode,
        "episode",
    )
    episode = _mapping(episode_model.model_dump(mode="json"), "episode")
    episode_revision_id = _uuid(
        episode.get("episode_revision_id"), "episode.episode_revision_id"
    )
    project_id = _uuid(episode.get("project_ir_id"), "episode.project_ir_id")
    project_digest = _sha256(
        episode.get("project_ir_revision_digest"),
        "episode.project_ir_revision_digest",
    )
    _literal(episode.get("model_family"), H3_MODEL_FAMILY, "episode.model_family")
    _sha256(
        episode.get("duration_allocation_digest"),
        "episode.duration_allocation_digest",
    )
    _sha256(episode.get("revision_digest"), "episode.revision_digest")

    project = _mapping(episode.get("project_ir"), "episode.project_ir")
    _exact_keys(
        project,
        {
            "project_id",
            "source_document_revision_ids",
            "evidence_pack_revision_id",
            "selected_resonance",
            "trial_script_revision_id",
            "narrator_lock",
            "subjects",
            "character_reference_requirements",
            "scene_plans",
            "target_duration_seconds",
            "aspect_ratio",
            "narrative_point_of_view",
            "creative_model_trace",
            "revision_digest",
        },
        "episode.project_ir",
    )
    if _uuid(project.get("project_id"), "episode.project_ir.project_id") != project_id:
        _fail("episode project_ir_id does not match embedded project_ir")
    if _sha256(
        project.get("revision_digest"), "episode.project_ir.revision_digest"
    ) != project_digest:
        _fail("episode project_ir_revision_digest does not match embedded project_ir")
    narrator = _mapping(project.get("narrator_lock"), "episode.project_ir.narrator_lock")
    _literal(
        narrator.get("voice_source"),
        "h3_native",
        "episode.project_ir.narrator_lock.voice_source",
    )
    subjects: dict[str, tuple[str, str]] = {}
    for index, raw_subject in enumerate(_array(project.get("subjects"), "episode.project_ir.subjects")):
        subject = _mapping(raw_subject, f"episode.project_ir.subjects[{index}]")
        subject_id = _identifier(subject.get("subject_id"), f"subjects[{index}].subject_id")
        if subject_id in subjects:
            _fail("project subject ids must be unique")
        subjects[subject_id] = (
            _identifier(subject.get("character_id"), f"subjects[{index}].character_id"),
            _identifier(subject.get("age_stage"), f"subjects[{index}].age_stage"),
        )
    if not subjects:
        _fail("episode.project_ir.subjects must not be empty")

    declared_revision_values = [
        _uuid(value, "episode.reference_set_revision_ids[]")
        for value in _array(
            episode.get("reference_set_revision_ids"),
            "episode.reference_set_revision_ids",
        )
    ]
    if not declared_revision_values or len(declared_revision_values) != len(
        set(declared_revision_values)
    ):
        _fail("episode reference_set_revision_ids must be non-empty and unique")
    declared_revisions = set(declared_revision_values)

    plans = _array(episode.get("sequence_plans"), "episode.sequence_plans")
    raw_finals = _array(root.get("final_sequences"), "final_sequences")
    if not plans or len(plans) != len(raw_finals):
        _fail("final_sequences must exactly match episode sequence_plans")
    final_by_id: dict[str, Mapping[str, Any]] = {}
    for index, raw_final_value in enumerate(raw_finals):
        field = f"final_sequences[{index}]"
        raw_final = _mapping(raw_final_value, field)
        _exact_keys(
            raw_final,
            {
                "plan",
                "prompt_digest",
                "workflow_digest",
                "initial_attempt",
                "repair_attempt",
                "selection_policy_revision",
                "selection",
                "state",
            },
            field,
        )
        final_model = _frozen_authority(H3SequenceV1, raw_final, field)
        final = _mapping(final_model.model_dump(mode="json"), field)
        plan = _mapping(final.get("plan"), f"final_sequences[{index}].plan")
        sequence_id = _uuid(plan.get("sequence_id"), f"final_sequences[{index}].plan.sequence_id")
        if sequence_id in final_by_id:
            _fail("final sequence ids must be unique")
        final_by_id[sequence_id] = final

    asset_templates: list[dict[str, Any]] = []
    reference_authorities: dict[str, str] = {}
    projected_sequences: list[dict[str, Any]] = []
    selected_lineages: dict[str, tuple[int, str]] = {}
    seen_sequence_ids: set[str] = set()
    seen_ordinals: set[int] = set()
    used_revision_order: list[str] = []

    for index, raw_plan in enumerate(plans):
        plan_field = f"episode.sequence_plans[{index}]"
        plan = _mapping(raw_plan, plan_field)
        sequence_id = _uuid(plan.get("sequence_id"), f"{plan_field}.sequence_id")
        final = final_by_id.get(sequence_id)
        if final is None:
            _fail("every episode sequence_plan requires a final H3SequenceV1")
        _exact_keys(
            final,
            {
                "plan",
                "prompt_digest",
                "workflow_digest",
                "initial_attempt",
                "repair_attempt",
                "selection_policy_revision",
                "selection",
                "state",
            },
            f"final_sequence[{sequence_id}]",
        )
        final_plan = _mapping(final.get("plan"), f"final_sequence[{sequence_id}].plan")
        if _canonical(plan) != _canonical(final_plan):
            _fail("final.sequence.plan must exactly equal its Episode sequence_plan")

        before_templates = len(asset_templates)
        validated_id, ordinal, duration = _validate_sequence_plan(
            plan,
            subjects,
            declared_revisions,
            capability,
            plan_field,
            asset_templates,
            reference_authorities,
        )
        if validated_id in seen_sequence_ids or ordinal in seen_ordinals:
            _fail("episode sequence ids and ordinals must be unique")
        seen_sequence_ids.add(validated_id)
        seen_ordinals.add(ordinal)
        for template in asset_templates[before_templates:]:
            revision_id = template["referenceSetRevisionId"]
            if revision_id not in used_revision_order:
                used_revision_order.append(revision_id)

        _sha256(final.get("prompt_digest"), f"final_sequence[{sequence_id}].prompt_digest")
        _sha256(final.get("workflow_digest"), f"final_sequence[{sequence_id}].workflow_digest")
        _literal(
            final.get("selection_policy_revision"),
            "h3.selection.v1",
            f"final_sequence[{sequence_id}].selection_policy_revision",
        )
        _literal(final.get("state"), "delivered", f"final_sequence[{sequence_id}].state")
        initial = _lineage(
            final.get("initial_attempt"),
            0,
            f"final_sequence[{sequence_id}].initial_attempt",
        )
        if initial["repair_trigger_codes"]:
            _fail("initial_attempt.repair_trigger_codes must be empty")
        repair_value = final.get("repair_attempt")
        repair = (
            None
            if repair_value is None
            else _lineage(
                repair_value,
                1,
                f"final_sequence[{sequence_id}].repair_attempt",
            )
        )
        if repair is not None and not repair["repair_trigger_codes"]:
            _fail("repair_attempt.repair_trigger_codes must not be empty")
        if final.get("selection") is None:
            _fail("delivered final sequence requires an embedded selection")
        selection_projection, selected_candidate = _selection(
            final.get("selection"),
            sequence_id,
            initial,
            repair,
            f"final_sequence[{sequence_id}].selection",
        )
        selected_ordinal = selected_candidate["attempt_ordinal"]
        selected_lineage = initial if selected_ordinal == 0 else repair
        assert selected_lineage is not None
        selected_lineages[sequence_id] = (
            selected_ordinal,
            selected_lineage["artifact_digest"],
        )
        projected_sequences.append(
            {
                "sequenceId": sequence_id,
                "ordinal": ordinal,
                "durationSeconds": duration,
                "status": "delivered",
                **selection_projection,
            }
        )

    if seen_ordinals != set(range(1, len(seen_ordinals) + 1)):
        _fail("episode sequence ordinals must be contiguous from 1")
    if set(final_by_id) != seen_sequence_ids:
        _fail("final_sequences contains a sequence absent from Episode")
    if used_revision_order != declared_revision_values:
        _fail("episode reference_set_revision_ids must exactly match bound revisions")
    projected_sequences.sort(key=lambda item: (item["ordinal"], item["sequenceId"]))

    delivery_model = _frozen_authority(H3DeliveryV1, raw_delivery, "delivery")
    delivery = _mapping(delivery_model.model_dump(mode="json"), "delivery")
    if _uuid(delivery.get("episode_revision_id"), "delivery.episode_revision_id") != episode_revision_id:
        _fail("delivery episode_revision_id does not match Episode")
    _literal(delivery.get("status"), "succeeded", "delivery.status")
    manifest = _mapping(delivery.get("assembly_manifest"), "delivery.assembly_manifest")
    _exact_keys(
        manifest,
        {"sequence_sources", "playback_asset_id", "download_asset_id"},
        "delivery.assembly_manifest",
    )
    sources = _array(
        manifest.get("sequence_sources"),
        "delivery.assembly_manifest.sequence_sources",
    )
    if len(sources) != len(selected_lineages):
        _fail("assembly manifest must contain one source per sequence")
    source_sequence_order = [
        _uuid(
            _mapping(source, f"delivery.assembly_manifest.sequence_sources[{index}]").get(
                "sequence_id"
            ),
            f"delivery.assembly_manifest.sequence_sources[{index}].sequence_id",
        )
        for index, source in enumerate(sources)
    ]
    expected_sequence_order = [
        sequence["sequenceId"] for sequence in projected_sequences
    ]
    if source_sequence_order != expected_sequence_order:
        _fail("assembly manifest sequence source order must match Episode ordinals")
    seen_sources: set[str] = set()
    for index, raw_source in enumerate(sources):
        field = f"delivery.assembly_manifest.sequence_sources[{index}]"
        source = _mapping(raw_source, field)
        _exact_keys(
            source,
            {"sequence_id", "selected_attempt_ordinal", "source_artifact_digest"},
            field,
        )
        sequence_id = _uuid(source.get("sequence_id"), f"{field}.sequence_id")
        if sequence_id in seen_sources or sequence_id not in selected_lineages:
            _fail("assembly manifest contains a duplicate or unknown sequence")
        seen_sources.add(sequence_id)
        expected_ordinal, expected_digest = selected_lineages[sequence_id]
        actual_ordinal = _integer(
            source.get("selected_attempt_ordinal"),
            f"{field}.selected_attempt_ordinal",
        )
        actual_digest = _sha256(
            source.get("source_artifact_digest"),
            f"{field}.source_artifact_digest",
        )
        if actual_ordinal != expected_ordinal or actual_digest != expected_digest:
            _fail("assembly manifest does not match selected source lineage")
    if seen_sources != set(selected_lineages):
        _fail("assembly manifest is missing a selected sequence source")

    playback_asset_id = _uuid(
        manifest.get("playback_asset_id"),
        "delivery.assembly_manifest.playback_asset_id",
    )
    download_asset_id = _uuid(
        manifest.get("download_asset_id"),
        "delivery.assembly_manifest.download_asset_id",
    )
    disclosure = _mapping(delivery.get("disclosure"), "delivery.disclosure")
    _exact_keys(disclosure, {"code", "content_mode", "label", "notice"}, "delivery.disclosure")
    content_mode = _string(
        disclosure.get("content_mode"),
        "delivery.disclosure.content_mode",
        max_length=32,
    )
    label = _public_text(disclosure.get("label"), "delivery.disclosure.label")
    notice = _public_text(disclosure.get("notice"), "delivery.disclosure.notice")
    if content_mode == "ai_completed":
        code = _literal(
            disclosure.get("code"),
            "AI_COMPLETED_NON_ORIGINAL",
            "delivery.disclosure.code",
        )
        combined = f"{label}{notice}"
        if "ai" not in combined.casefold() or "补全" not in combined or "非原文" not in combined:
            _fail("AI-completed disclosure must identify AI 补全 and 非原文 content")
    elif content_mode == "source_grounded":
        code = _literal(
            disclosure.get("code"),
            "SOURCE_GROUNDED",
            "delivery.disclosure.code",
        )
    else:
        _fail("delivery.disclosure.content_mode must be source_grounded or ai_completed")
    public_disclosure: H3DisclosureDTO = {
        "code": code,
        "contentMode": content_mode,
        "label": label,
        "notice": notice,
    }

    asset_templates.sort(
        key=lambda item: (
            item["characterId"],
            item["ageStage"],
            item["referenceSetRevisionId"],
            CANONICAL_VIEWS.index(item["viewName"]),
        )
    )

    def resolve(asset_id: str, field: str) -> str:
        try:
            result = asset_url_resolver(asset_id)
        except Exception as exc:
            raise H3ProjectionError(f"{field} asset URL resolver failed") from exc
        return _public_url(result, f"{field} resolved URL", allowlist)

    reference_cards: list[dict[str, Any]] = []
    for index, template in enumerate(asset_templates):
        card = {key: value for key, value in template.items() if key != "assetId"}
        card["imageUrl"] = resolve(
            template["assetId"], f"referenceCards[{index}].imageUrl"
        )
        reference_cards.append(card)

    duration = sum(sequence["durationSeconds"] for sequence in projected_sequences)
    return {
        "schemaVersion": PROJECTION_SCHEMA,
        "episodeRevisionId": episode_revision_id,
        "projectId": project_id,
        "status": "succeeded",
        "durationSeconds": duration,
        "referenceCards": reference_cards,
        "sequences": projected_sequences,
        "playbackUrl": resolve(playback_asset_id, "delivery.playbackUrl"),
        "downloadUrl": resolve(download_asset_id, "delivery.downloadUrl"),
        "disclosure": public_disclosure,
    }


__all__ = [
    "AssetUrlResolver",
    "FLUX2_DEV_FP8_MIXED_CAPABILITY_V1",
    "FluxCapabilityInput",
    "H3AICompletedDisclosureDTO",
    "H3AttemptDTO",
    "H3DeliveryDigestAnchorV1",
    "H3DeliveryRecordLoader",
    "H3DisclosureDTO",
    "H3ProductAuthorityInput",
    "H3ProductProjectionDTO",
    "H3ProjectionError",
    "H3QcVectorDTO",
    "H3ReferenceCardDTO",
    "H3SequenceDTO",
    "H3SourceGroundedDisclosureDTO",
    "project_h3_product",
]
