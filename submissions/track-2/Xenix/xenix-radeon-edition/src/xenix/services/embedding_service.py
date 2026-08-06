"""Embedding capability service and the built-in OpenAI-compatible adapter.

This module owns generic Embedding operation semantics and the ordinary static
wire client.  Provider catalog persistence belongs to ``embedding_settings``;
optional managers contribute factories through composition without teaching this
module about their runtime, placement, or dynamic endpoint details.
"""

from __future__ import annotations

import json
import math
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Protocol, runtime_checkable

from ..exceptions import ValidationError
from .embedding_provider_factory import (
    EmbeddingOperationScope,
    EmbeddingProviderFactory,
    EmbeddingProviderFactoryRegistry,
)
from .embedding_settings import (
    DEFAULT_EMBEDDING_BATCH_SIZE,
    EMBEDDING_SETTINGS_FILE_NAME,
    MAX_EMBEDDING_DIMENSIONS,
    SETTINGS_FILE_NAME,
    EmbeddingDialect,
    EmbeddingProviderProjection,
    EmbeddingSettings,
    EmbeddingSettingsError,
    EmbeddingSettingsService,
    EmbeddingSettingsSnapshot,
    EmbeddingSettingsSource,
    ManagedEmbeddingProviderRef,
    StaticEmbeddingTarget,
    normalize_embedding_base_url,
)

TEXT_PREPARATION_VERSION = "nfkc-trim-v1"
EMBEDDING_ADAPTER_VERSION = "openai-compatible-v1"
MAX_EMBEDDING_TEXT_CHARS = 12_000

_MAX_RESPONSE_BYTES = 32 * 1024 * 1024
_PROFILE_SCHEMA = "xenix.embedding-profile/v1"
_ENCODING_FORMAT = "float"
_MANAGED_ADAPTER_VERSION = "managed-openai-compatible-v1"


class EmbeddingValidationError(ValidationError):
    """A bounded Embedding-domain failure safe to project outside an adapter."""


@dataclass(frozen=True, slots=True)
class EmbeddingProfile:
    provider_key: str
    model: str
    dimensions: int | None
    profile_fingerprint: str


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    profile: EmbeddingProfile
    vectors: tuple[tuple[float, ...], ...]

    @property
    def dimensions(self) -> int:
        """The provider's actual vector dimension for this validated batch."""

        return len(self.vectors[0])

    @property
    def embeddings(self) -> tuple[tuple[float, ...], ...]:
        """Compatibility-friendly name for consumers that use provider terminology."""

        return self.vectors

    def __len__(self) -> int:
        return len(self.vectors)


@runtime_checkable
class EmbeddingSession(Protocol):
    @property
    def profile(self) -> EmbeddingProfile: ...

    def embed_texts(self, texts: Sequence[str]) -> EmbeddingBatch: ...


@runtime_checkable
class EmbeddingService(Protocol):
    def freeze(self) -> EmbeddingSession | None: ...

    def configured_profile(self) -> EmbeddingProfile | None: ...

    def embed_texts(self, texts: Sequence[str]) -> EmbeddingBatch: ...


@dataclass(frozen=True, slots=True)
class _ConfiguredEmbeddingSession:
    _service: ConfiguredEmbeddingService
    _projection: EmbeddingProviderProjection
    profile: EmbeddingProfile

    def embed_texts(self, texts: Sequence[str]) -> EmbeddingBatch:
        return self._service._embed_texts_with_projection(self._projection, self.profile, texts)


class ConfiguredEmbeddingService:
    """Resolve the active catalog entry while keeping ``freeze()`` resource-free."""

    def __init__(
        self,
        settings_source: EmbeddingSettingsSource,
        provider_factory_registry: EmbeddingProviderFactoryRegistry,
    ) -> None:
        self._settings_source = settings_source
        self._provider_factory_registry = provider_factory_registry

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    def freeze(self) -> EmbeddingSession | None:
        settings = self._settings_snapshot()
        projection = settings.active_provider()
        if projection is None:
            raise EmbeddingValidationError(
                "Embedding provider reference is stale.",
                error_code="embedding_provider_reference_stale",
            )
        if projection.retiring:
            raise EmbeddingValidationError(
                "Embedding provider is retiring.",
                error_code="embedding_provider_retiring",
            )
        target = projection.target
        if isinstance(target, StaticEmbeddingTarget):
            if not target.enabled:
                return None
            self._require_supported_dialect(target)
        self._require_factory_implementation(projection)
        return _ConfiguredEmbeddingSession(
            _service=self,
            _projection=projection,
            profile=embedding_profile_from_projection(projection),
        )

    def configured_profile(self) -> EmbeddingProfile | None:
        session = self.freeze()
        return session.profile if session is not None else None

    def embed_texts(self, texts: Sequence[str]) -> EmbeddingBatch:
        session = self.freeze()
        if session is None:
            raise EmbeddingValidationError(
                "Embedding is not enabled.",
                error_code="embedding_not_enabled",
            )
        return session.embed_texts(texts)

    def _embed_texts_with_projection(
        self,
        projection: EmbeddingProviderProjection,
        profile: EmbeddingProfile,
        texts: Sequence[str],
    ) -> EmbeddingBatch:
        prepared_texts = _prepare_texts(texts)
        resolved_dimensions = projection.dimensions
        vectors: list[tuple[float, ...]] = []
        try:
            # This scope intentionally encloses every batch.  A managed adapter
            # can pin one exact generation here, and no partial result is
            # published because the accumulated vectors are returned only after
            # every batch validates.
            with self._provider_factory_registry.provider_scope(projection) as scope:
                for start in range(0, len(prepared_texts), projection.batch_size):
                    input_batch = prepared_texts[start : start + projection.batch_size]
                    scope.mark_dispatch_may_have_happened()
                    output_batch = scope.provider.embed_batch(
                        input_batch,
                        expected_dimensions=resolved_dimensions,
                    )
                    if resolved_dimensions is None:
                        resolved_dimensions = len(output_batch[0])
                    vectors.extend(output_batch)
        except EmbeddingValidationError:
            raise
        except ValidationError as exc:
            raise _translate_provider_error(exc) from exc
        except Exception as exc:
            raise EmbeddingValidationError(
                "Embedding provider request failed.",
                error_code="embedding_provider_request_failed",
            ) from exc
        return EmbeddingBatch(profile=profile, vectors=tuple(vectors))

    def _settings_snapshot(self) -> EmbeddingSettings:
        try:
            loaded = self._settings_source.load()
            if not isinstance(loaded, EmbeddingSettings):
                raise TypeError("Embedding settings source returned an invalid value.")
            return EmbeddingSettings.model_validate(loaded).model_copy(deep=True)
        except EmbeddingValidationError:
            raise
        except Exception as exc:
            raise EmbeddingValidationError(
                "Embedding settings are unavailable.",
                error_code="embedding_settings_unavailable",
            ) from exc

    def _require_supported_dialect(self, target: StaticEmbeddingTarget) -> None:
        if target.dialect is not EmbeddingDialect.OPENAI_COMPATIBLE:
            raise EmbeddingValidationError(
                "The configured Embedding dialect is not supported.",
                error_code="embedding_dialect_unsupported",
            )

    def _require_factory_implementation(self, projection: EmbeddingProviderProjection) -> None:
        try:
            self._provider_factory_registry.require_implementation(projection)
        except ValidationError as exc:
            raise _translate_provider_error(exc) from exc


class OpenAICompatibleEmbeddingService(ConfiguredEmbeddingService):
    """Compatibility construction for the ordinary static Embedding provider.

    Callers that compose a managed registry may pass it explicitly.  Existing
    callers get a fresh registry containing only the normal static factory.
    """

    def __init__(
        self,
        settings_source: EmbeddingSettingsSource,
        provider_factory_registry: EmbeddingProviderFactoryRegistry | None = None,
    ) -> None:
        registry = provider_factory_registry or create_builtin_embedding_provider_factory_registry()
        super().__init__(settings_source, registry)


class OpenAICompatibleEmbeddingProviderFactory(EmbeddingProviderFactory):
    """Built-in static OpenAI-compatible wire-client construction."""

    def provider_scope(self, projection: EmbeddingProviderProjection) -> EmbeddingOperationScope:
        target = projection.target
        if not isinstance(target, StaticEmbeddingTarget):
            raise TypeError("Static Embedding factory received a non-static provider target.")
        if target.dialect is not EmbeddingDialect.OPENAI_COMPATIBLE:
            raise EmbeddingValidationError(
                "The configured Embedding dialect is not supported.",
                error_code="embedding_dialect_unsupported",
            )
        return EmbeddingOperationScope(OpenAICompatibleEmbeddingBackend.from_static_target(target))


def create_builtin_embedding_provider_factory_registry() -> EmbeddingProviderFactoryRegistry:
    """Create a fresh registry with only the explicit normal static factory."""

    registry = EmbeddingProviderFactoryRegistry()
    registry.register_static_factory(OpenAICompatibleEmbeddingProviderFactory())
    return registry


def register_builtin_embedding_provider_factories(
    registry: EmbeddingProviderFactoryRegistry,
) -> None:
    """Explicit composition helper; never invoked through import side effects."""

    registry.register_static_factory(OpenAICompatibleEmbeddingProviderFactory())


@dataclass(frozen=True, slots=True)
class OpenAICompatibleEmbeddingBackend:
    """Ordinary OpenAI-compatible wire client with no manager dependency.

    Static configuration and optional manager adapters both use this one client.
    The caller supplies an already-authorized transient binding; this type owns
    only protocol validation and deliberately stores no selection or lifecycle
    state.  Its secret field is excluded from representations.
    """

    base_url: str
    api_key: str = field(repr=False)
    model: str
    timeout_seconds: int
    request_dimensions: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", normalize_embedding_base_url(self.base_url))
        if not isinstance(self.model, str) or not self.model.strip():
            raise EmbeddingValidationError(
                "Embedding model is invalid.",
                error_code="embedding_request_invalid",
            )
        if (
            not isinstance(self.timeout_seconds, int)
            or isinstance(self.timeout_seconds, bool)
            or not 1 <= self.timeout_seconds <= 3_600
        ):
            raise EmbeddingValidationError(
                "Embedding request timeout is invalid.",
                error_code="embedding_request_invalid",
            )
        if self.request_dimensions is not None and (
            not isinstance(self.request_dimensions, int)
            or isinstance(self.request_dimensions, bool)
            or not 1 <= self.request_dimensions <= MAX_EMBEDDING_DIMENSIONS
        ):
            raise EmbeddingValidationError(
                "Embedding request dimensions are invalid.",
                error_code="embedding_request_invalid",
            )

    @classmethod
    def from_static_target(cls, target: StaticEmbeddingTarget) -> "OpenAICompatibleEmbeddingBackend":
        return cls(
            base_url=target.base_url,
            api_key=target.api_key,
            model=target.model,
            timeout_seconds=target.timeout_seconds,
            request_dimensions=target.dimensions,
        )

    def embed_batch(
        self,
        texts: Sequence[str],
        *,
        expected_dimensions: int | None,
    ) -> list[tuple[float, ...]]:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": list(texts),
            "encoding_format": _ENCODING_FORMAT,
        }
        if self.request_dimensions is not None:
            payload["dimensions"] = self.request_dimensions
        request_body = _encode_request_payload(payload)
        headers = _request_headers(self.api_key)
        try:
            request = urllib.request.Request(
                _embeddings_endpoint(self.base_url),
                data=request_body,
                headers=headers,
                method="POST",
            )
        except Exception as exc:
            raise EmbeddingValidationError(
                "Embedding request could not be constructed safely.",
                error_code="embedding_request_invalid",
            ) from exc
        response_payload = self._post_json(request, timeout_seconds=self.timeout_seconds)
        return _parse_embeddings_response(
            response_payload,
            expected_count=len(texts),
            expected_dimensions=expected_dimensions,
        )

    def _post_json(self, request: urllib.request.Request, *, timeout_seconds: int) -> Any:
        raw_body: bytes | None = None
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = _read_bounded_response(response)
                if isinstance(body, bytes):
                    raw_body = body
                elif isinstance(body, bytearray):
                    raw_body = bytes(body)
                else:
                    raise EmbeddingValidationError(
                        "Embedding provider returned an invalid response.",
                        error_code="embedding_response_invalid_type",
                    )
        except EmbeddingValidationError:
            raise
        except urllib.error.HTTPError as exc:
            status_code = exc.code if isinstance(exc.code, int) and not isinstance(exc.code, bool) else None
            try:
                exc.close()
            except Exception:
                pass
            raise EmbeddingValidationError(
                "Embedding provider rejected the request.",
                error_code="embedding_provider_http_error",
                error_details={"status_code": status_code} if status_code is not None else None,
                retryable=status_code in {408, 409, 425, 429, 500, 502, 503, 504},
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise EmbeddingValidationError(
                "Embedding provider is unavailable.",
                error_code="embedding_provider_unavailable",
                retryable=True,
            ) from exc
        except Exception as exc:
            raise EmbeddingValidationError(
                "Embedding provider request failed.",
                error_code="embedding_provider_request_failed",
            ) from exc
        if raw_body is None or len(raw_body) > _MAX_RESPONSE_BYTES:
            raise EmbeddingValidationError(
                "Embedding provider returned an invalid response.",
                error_code="embedding_response_invalid_size",
            )
        try:
            return json.loads(raw_body.decode("utf-8"))
        except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise EmbeddingValidationError(
                "Embedding provider returned invalid JSON.",
                error_code="embedding_response_invalid_json",
            ) from exc


def embedding_profile_from_settings(settings: EmbeddingSettings) -> EmbeddingProfile:
    """Return the non-secret vector-space identity for the active provider."""

    validated = EmbeddingSettings.model_validate(settings)
    projection = validated.active_provider()
    if projection is None:
        raise EmbeddingValidationError(
            "Embedding provider reference is stale.",
            error_code="embedding_provider_reference_stale",
        )
    return embedding_profile_from_projection(projection)


def embedding_profile_from_projection(projection: EmbeddingProviderProjection) -> EmbeddingProfile:
    """Calculate a stable vector-space identity without live connection facts."""

    target = projection.target
    if isinstance(target, StaticEmbeddingTarget):
        payload = {
            "schema": _PROFILE_SCHEMA,
            "adapter_version": EMBEDDING_ADAPTER_VERSION,
            "provider_key": unicodedata.normalize("NFKC", target.provider_key).strip(),
            "dialect": target.dialect.value,
            "base_url": normalize_embedding_base_url(target.base_url),
            "model": unicodedata.normalize("NFKC", target.model).strip(),
            "dimensions": target.dimensions,
            "encoding_format": _ENCODING_FORMAT,
            "text_preparation_version": TEXT_PREPARATION_VERSION,
        }
        return _profile_from_payload(
            payload,
            provider_key=target.provider_key,
            model=target.model,
            dimensions=target.dimensions,
        )
    if not isinstance(target, ManagedEmbeddingProviderRef):
        raise TypeError("Embedding provider target is unsupported.")
    payload = {
        "schema": _PROFILE_SCHEMA,
        "adapter_version": _MANAGED_ADAPTER_VERSION,
        "owner": "embedding",
        "manager_id": target.manager_id,
        "installation_id": target.installation_id,
        "component_generation_id": target.component_generation_id,
        "model": projection.model,
        "tokenizer_identity": projection.tokenizer_identity,
        "manifest_digest": projection.manifest_digest,
        "dimensions": projection.dimensions,
        "encoding_format": _ENCODING_FORMAT,
        "text_preparation_version": TEXT_PREPARATION_VERSION,
    }
    return _profile_from_payload(
        payload,
        provider_key=projection.id,
        model=projection.model,
        dimensions=projection.dimensions,
    )


def _profile_from_payload(
    payload: dict[str, Any],
    *,
    provider_key: str,
    model: str,
    dimensions: int | None,
) -> EmbeddingProfile:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return EmbeddingProfile(
        provider_key=provider_key,
        model=model,
        dimensions=dimensions,
        profile_fingerprint=sha256(encoded).hexdigest(),
    )


def _prepare_texts(texts: Sequence[str]) -> list[str]:
    if isinstance(texts, (str, bytes, bytearray)) or not isinstance(texts, Sequence):
        raise EmbeddingValidationError(
            "Embedding input must be a sequence of text values.",
            error_code="embedding_input_invalid_type",
        )
    if not texts:
        raise EmbeddingValidationError(
            "Embedding input cannot be empty.",
            error_code="embedding_input_empty",
        )
    prepared: list[str] = []
    for index, text in enumerate(texts):
        if not isinstance(text, str):
            raise EmbeddingValidationError(
                "Every embedding input must be text.",
                error_code="embedding_text_invalid_type",
                error_details={"text_index": index},
            )
        normalized = unicodedata.normalize("NFKC", text).strip()
        if not normalized:
            raise EmbeddingValidationError(
                "Embedding text cannot be empty after preparation.",
                error_code="embedding_text_empty",
                error_details={"text_index": index},
            )
        if len(normalized) > MAX_EMBEDDING_TEXT_CHARS:
            raise EmbeddingValidationError(
                "Embedding text exceeds the supported length.",
                error_code="embedding_text_too_long",
                error_details={"text_index": index, "max_characters": MAX_EMBEDDING_TEXT_CHARS},
            )
        prepared.append(normalized)
    return prepared


def _encode_request_payload(payload: dict[str, Any]) -> bytes:
    try:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise EmbeddingValidationError(
            "Embedding input could not be encoded safely.",
            error_code="embedding_request_invalid_input",
        ) from exc


def _request_headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    key = api_key.strip()
    if not key:
        return headers
    try:
        valid = "\r" not in key and "\n" not in key
        key.encode("latin-1")
    except UnicodeError:
        valid = False
    if not valid:
        raise EmbeddingValidationError(
            "Embedding API key cannot be used as an HTTP credential.",
            error_code="embedding_api_key_invalid",
        )
    headers["Authorization"] = f"Bearer {key}"
    return headers


def _read_bounded_response(response: Any) -> Any:
    """Read at most one byte beyond the accepted provider response size."""

    return response.read(_MAX_RESPONSE_BYTES + 1)


def _parse_embeddings_response(
    payload: Any,
    *,
    expected_count: int,
    expected_dimensions: int | None,
) -> list[tuple[float, ...]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise EmbeddingValidationError(
            "Embedding provider returned an invalid response shape.",
            error_code="embedding_response_invalid_shape",
        )
    data = payload["data"]
    if len(data) != expected_count:
        raise EmbeddingValidationError(
            "Embedding provider returned an unexpected result count.",
            error_code="embedding_response_count_mismatch",
            error_details={"expected_count": expected_count, "actual_count": len(data)},
        )
    by_index: dict[int, tuple[float, ...]] = {}
    dimensions_seen: set[int] = set()
    for item in data:
        if not isinstance(item, dict):
            raise EmbeddingValidationError(
                "Embedding provider returned an invalid result item.",
                error_code="embedding_response_invalid_item",
            )
        index = item.get("index")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or index >= expected_count
            or index in by_index
        ):
            raise EmbeddingValidationError(
                "Embedding provider returned an invalid result index.",
                error_code="embedding_response_invalid_index",
            )
        raw_vector = item.get("embedding")
        if not isinstance(raw_vector, list) or not raw_vector:
            raise EmbeddingValidationError(
                "Embedding provider returned an invalid vector.",
                error_code="embedding_response_invalid_vector",
            )
        vector: list[float] = []
        for coordinate in raw_vector:
            if not isinstance(coordinate, (int, float)) or isinstance(coordinate, bool):
                raise EmbeddingValidationError(
                    "Embedding provider returned a non-numeric vector.",
                    error_code="embedding_response_invalid_vector_type",
                )
            try:
                numeric = float(coordinate)
            except (OverflowError, TypeError, ValueError) as exc:
                raise EmbeddingValidationError(
                    "Embedding provider returned a non-numeric vector.",
                    error_code="embedding_response_invalid_vector_type",
                ) from exc
            if not math.isfinite(numeric):
                raise EmbeddingValidationError(
                    "Embedding provider returned a non-finite vector.",
                    error_code="embedding_response_non_finite",
                )
            vector.append(numeric)
        normalized = tuple(vector)
        by_index[index] = normalized
        dimensions_seen.add(len(normalized))
    if len(dimensions_seen) != 1:
        raise EmbeddingValidationError(
            "Embedding provider returned mixed vector dimensions.",
            error_code="embedding_response_mixed_dimensions",
        )
    actual_dimensions = next(iter(dimensions_seen))
    if actual_dimensions > MAX_EMBEDDING_DIMENSIONS:
        raise EmbeddingValidationError(
            "Embedding provider returned an oversized vector.",
            error_code="embedding_response_dimension_too_large",
            error_details={"maximum_dimensions": MAX_EMBEDDING_DIMENSIONS},
        )
    if expected_dimensions is not None and actual_dimensions != expected_dimensions:
        raise EmbeddingValidationError(
            "Embedding provider returned an unexpected vector dimension.",
            error_code="embedding_response_dimension_mismatch",
            error_details={
                "expected_dimensions": expected_dimensions,
                "actual_dimensions": actual_dimensions,
            },
        )
    return [by_index[index] for index in range(expected_count)]


def _embeddings_endpoint(base_url: str) -> str:
    normalized = normalize_embedding_base_url(base_url)
    if normalized.endswith("/v1"):
        return f"{normalized}/embeddings"
    return f"{normalized}/v1/embeddings"


def _translate_provider_error(exc: ValidationError) -> EmbeddingValidationError:
    code = exc.error_code or "embedding_provider_unavailable"
    safe_message = (
        str(exc)
        if code == "provider_implementation_unavailable" or code.startswith("embedding_")
        else "Embedding provider is unavailable."
    )
    safe_code = (
        code
        if code == "provider_implementation_unavailable" or code.startswith("embedding_")
        else "embedding_provider_unavailable"
    )
    return EmbeddingValidationError(
        safe_message,
        error_code=safe_code,
        retryable=exc.retryable,
    )


__all__ = [
    "ConfiguredEmbeddingService",
    "DEFAULT_EMBEDDING_BATCH_SIZE",
    "EMBEDDING_ADAPTER_VERSION",
    "EMBEDDING_SETTINGS_FILE_NAME",
    "EmbeddingBatch",
    "EmbeddingDialect",
    "EmbeddingProfile",
    "EmbeddingService",
    "EmbeddingSession",
    "EmbeddingSettings",
    "EmbeddingSettingsError",
    "EmbeddingSettingsService",
    "EmbeddingSettingsSnapshot",
    "EmbeddingSettingsSource",
    "EmbeddingValidationError",
    "MAX_EMBEDDING_DIMENSIONS",
    "MAX_EMBEDDING_TEXT_CHARS",
    "ManagedEmbeddingProviderRef",
    "OpenAICompatibleEmbeddingProviderFactory",
    "OpenAICompatibleEmbeddingBackend",
    "OpenAICompatibleEmbeddingService",
    "SETTINGS_FILE_NAME",
    "TEXT_PREPARATION_VERSION",
    "create_builtin_embedding_provider_factory_registry",
    "embedding_profile_from_projection",
    "embedding_profile_from_settings",
    "register_builtin_embedding_provider_factories",
]
