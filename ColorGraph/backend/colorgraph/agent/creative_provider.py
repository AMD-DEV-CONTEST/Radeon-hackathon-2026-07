from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

PROVIDER_RUNTIME_VERSION = "colorgraph.creative-model-provider/v5"
OLLAMA_UNLOAD_VERIFICATION_TIMEOUT_SECONDS = 15.0
OLLAMA_UNLOAD_VERIFICATION_INTERVAL_SECONDS = 0.1

OutputT = TypeVar("OutputT", bound=BaseModel)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _ollama_structural_schema(value: Any) -> Any:
    """Keep strict structure while deferring unsupported lexical bounds to Pydantic."""

    unsupported = {
        "title",
        "description",
        "maxLength",
    }
    if isinstance(value, dict):
        return {
            key: _ollama_structural_schema(item)
            for key, item in value.items()
            if key not in unsupported
        }
    if isinstance(value, list):
        return [_ollama_structural_schema(item) for item in value]
    return value


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CreativeRole(StrEnum):
    DIRECTOR = "director"
    STRATEGIST = "strategist"
    CRITIC = "critic"


class ProviderBoundary(StrEnum):
    LOCAL = "local"
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"


class ProviderFailureType(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    CANCELLED = "cancelled"
    BAD_JSON = "bad_json"
    SCHEMA_INVALID = "schema_invalid"
    REFUSAL = "refusal"
    INCOMPLETE = "incomplete"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CIRCUIT_OPEN = "circuit_open"
    OFFLINE = "offline"
    CLOUD_CONSENT_REQUIRED = "cloud_consent_required"
    CAPABILITY_MISMATCH = "capability_mismatch"
    AUTHENTICATION = "authentication"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INTERNAL = "internal"


class ProviderCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    image_input: bool
    strict_structured_output: bool
    maximum_context_tokens: int = Field(gt=0)
    maximum_images: int = Field(ge=0)
    batch_requests: bool
    audio_input: bool = False
    maximum_audio_seconds: float = Field(default=0, ge=0)


class ProviderUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0, ge=0)


class ProviderHardwareEvidence(BaseModel):
    """Provider-reported accelerator residency bound to one uncached response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["colorgraph.provider-hardware-evidence/v1"] = (
        "colorgraph.provider-hardware-evidence/v1"
    )
    measurement_source: Literal["ollama-api-ps"] = "ollama-api-ps"
    model_name: str = Field(min_length=1)
    model_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    quantization_level: str = Field(min_length=1)
    context_length: int = Field(gt=0)
    model_size_bytes: int = Field(gt=0)
    vram_size_bytes: int = Field(ge=0)
    gpu_offload_ratio: float = Field(ge=0, le=1)
    minimum_required_gpu_offload_ratio: float = Field(ge=0, le=1)
    gpu_required: bool
    gpu_verified: bool
    vram_release_verified: bool = False


class ProviderImage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str = Field(pattern=r"^image/(png|jpeg|webp|gif)$")
    content: bytes = Field(min_length=1)
    detail: str = Field(default="low", pattern=r"^(low|high|original|auto)$")

    def model_post_init(self, __context: Any) -> None:
        if _sha256(self.content) != self.sha256:
            raise ValueError("provider image content does not match its SHA-256 digest")


class ProviderAudio(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str = Field(
        pattern=r"^audio/(wav|x-wav|mpeg|mp4|webm|ogg|flac)$"
    )
    duration_seconds: float = Field(gt=0, le=86_400)
    content: bytes = Field(min_length=1)

    def model_post_init(self, __context: Any) -> None:
        if _sha256(self.content) != self.sha256:
            raise ValueError("provider audio content does not match its SHA-256 digest")


@dataclass(frozen=True, slots=True)
class CreativeModelRequest[OutputT]:
    role: CreativeRole
    prompt: str
    prompt_version: str
    schema_version: str
    output_model: type[OutputT]
    input_asset_digests: tuple[str, ...]
    images: tuple[ProviderImage, ...] = ()
    audio: tuple[ProviderAudio, ...] = ()
    max_output_tokens: int = 4_096
    estimated_input_tokens: int = 0
    cloud_upload_consent: bool = False
    request_id: str | None = None

    def __post_init__(self) -> None:
        if not self.prompt.strip():
            raise ValueError("provider prompt must not be empty")
        if not self.prompt_version or not self.schema_version:
            raise ValueError("provider prompt and schema versions are required")
        if self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if self.estimated_input_tokens < 0:
            raise ValueError("estimated_input_tokens must be non-negative")
        if not self.input_asset_digests:
            raise ValueError("at least one immutable input asset digest is required")
        if any(
            len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)
            for digest in self.input_asset_digests
        ):
            raise ValueError("input asset digests must be lowercase SHA-256 values")


@dataclass(frozen=True, slots=True)
class RawProviderResponse:
    text: str | None
    usage: ProviderUsage = field(default_factory=ProviderUsage)
    response_id: str | None = None
    model_revision: str | None = None
    refusal: str | None = None
    incomplete_reason: str | None = None
    hardware_evidence: ProviderHardwareEvidence | None = None


class ProviderError(RuntimeError):
    def __init__(
        self,
        failure_type: ProviderFailureType,
        message: str,
        *,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_type = failure_type
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.status_code = status_code


class CreativeModelProvider(ABC):
    """Provider-neutral, role-routable multimodal model interface."""

    provider_id: str
    model_id: str
    model_revision: str
    boundary: ProviderBoundary
    capabilities: ProviderCapabilities

    @abstractmethod
    async def generate(
        self,
        request: CreativeModelRequest[Any],
        *,
        strict_schema: dict[str, Any],
    ) -> RawProviderResponse:
        raise NotImplementedError

    async def release(self) -> None:
        """Release provider-owned accelerator resources when supported."""
        return None


class ProviderAuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    runtime_version: str = PROVIDER_RUNTIME_VERSION
    timestamp: datetime
    request_id: str | None = None
    request_digest: str
    cache_key: str
    role: CreativeRole
    provider_id: str
    boundary: ProviderBoundary
    model_id: str
    model_revision: str
    prompt_version: str
    schema_version: str
    attempt_count: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    cache_hit: bool
    success: bool
    failure_type: ProviderFailureType | None = None
    response_id: str | None = None
    usage: ProviderUsage
    hardware_evidence: ProviderHardwareEvidence | None = None
    structured_response: dict[str, Any] | None = None


class JsonlProviderAuditSink:
    """Append-only audit sink. Prompts, media bytes, and credentials are never recorded."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    async def write(self, record: ProviderAuditRecord) -> None:
        line = record.model_dump_json() + "\n"
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)


@dataclass(frozen=True, slots=True)
class RuntimeBudget:
    maximum_provider_attempts: int = 12
    maximum_input_tokens: int = 200_000
    maximum_output_tokens: int = 50_000
    maximum_cost_usd: float = 10

    def __post_init__(self) -> None:
        if (
            self.maximum_provider_attempts < 0
            or self.maximum_input_tokens < 0
            or self.maximum_output_tokens < 0
            or self.maximum_cost_usd < 0
        ):
            raise ValueError("runtime budget values must be non-negative")


@dataclass(slots=True)
class _BudgetUsage:
    provider_attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0


@dataclass(frozen=True, slots=True)
class RuntimePolicy:
    network_enabled: bool = False
    cloud_provider_enabled: bool = False
    timeout_seconds: float = 60
    maximum_retries: int = 2
    maximum_concurrency: int = 2
    requests_per_minute: int = 30
    circuit_failure_threshold: int = 3
    circuit_cooldown_seconds: float = 60
    retry_base_seconds: float = 0.25

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.maximum_retries < 0:
            raise ValueError("maximum_retries must be non-negative")
        if self.maximum_concurrency <= 0 or self.requests_per_minute <= 0:
            raise ValueError("concurrency and rate limits must be positive")
        if self.circuit_failure_threshold <= 0 or self.circuit_cooldown_seconds < 0:
            raise ValueError("circuit breaker values are invalid")


@dataclass(frozen=True, slots=True)
class CreativeModelResult[OutputT]:
    output: OutputT
    audit: ProviderAuditRecord


@dataclass(frozen=True, slots=True)
class FallbackDecision:
    route: str
    reason: ProviderFailureType
    detail: str
    request_digest: str


class ProviderResponseCache:
    """Content-addressed local cache for validated structured responses."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root
        self._memory: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        cached = self._memory.get(key)
        if cached is not None:
            return json.loads(json.dumps(cached))
        if self.root is None:
            return None
        path = self.root / f"{key}.json"
        if not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        self._memory[key] = value
        return json.loads(json.dumps(value))

    def put(self, key: str, value: dict[str, Any]) -> None:
        stable = json.loads(json.dumps(value))
        self._memory[key] = stable
        if self.root is None:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{key}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != stable:
                raise RuntimeError("provider cache key collision")
            return
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(stable, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(path)


def strict_output_schema(output_model: type[BaseModel]) -> dict[str, Any]:
    """Normalize Pydantic JSON Schema for the Responses strict-output subset."""

    schema = output_model.model_json_schema(mode="validation")

    def normalize(value: Any) -> None:
        if isinstance(value, dict):
            value.pop("default", None)
            if value.get("type") == "object" or "properties" in value:
                properties = value.get("properties", {})
                value["additionalProperties"] = False
                value["required"] = list(properties)
            for nested in value.values():
                normalize(nested)
        elif isinstance(value, list):
            for nested in value:
                normalize(nested)

    normalize(schema)
    if schema.get("type") != "object":
        raise ValueError("strict provider output schema root must be an object")
    return schema


def request_digest(request: CreativeModelRequest[Any]) -> str:
    return _sha256(
        _canonical_json(
            {
                "role": request.role,
                "prompt_sha256": _sha256(request.prompt.encode("utf-8")),
                "prompt_version": request.prompt_version,
                "schema_version": request.schema_version,
                "input_asset_digests": request.input_asset_digests,
                "image_digests": [image.sha256 for image in request.images],
                "audio_digests": [audio.sha256 for audio in request.audio],
                "max_output_tokens": request.max_output_tokens,
            }
        )
    )


def response_cache_key(
    request: CreativeModelRequest[Any],
    provider: CreativeModelProvider,
) -> str:
    return _sha256(
        _canonical_json(
            {
                "runtime": PROVIDER_RUNTIME_VERSION,
                "role": request.role,
                "prompt_version": request.prompt_version,
                "prompt_sha256": _sha256(request.prompt.encode("utf-8")),
                "schema_version": request.schema_version,
                "schema_sha256": _sha256(
                    _canonical_json(strict_output_schema(request.output_model))
                ),
                "provider": provider.provider_id,
                "boundary": provider.boundary,
                "model": provider.model_id,
                "model_revision": provider.model_revision,
                "input_asset_digests": request.input_asset_digests,
                "image_digests": [image.sha256 for image in request.images],
                "audio_digests": [audio.sha256 for audio in request.audio],
                "max_output_tokens": request.max_output_tokens,
            }
        )
    )


class CreativeProviderRuntime:
    def __init__(
        self,
        providers: Mapping[CreativeRole, CreativeModelProvider],
        *,
        policy: RuntimePolicy | None = None,
        budget: RuntimeBudget | None = None,
        cache: ProviderResponseCache | None = None,
        audit_sink: JsonlProviderAuditSink | None = None,
    ) -> None:
        missing = set(CreativeRole) - set(providers)
        if missing:
            raise ValueError(f"missing role providers: {sorted(item.value for item in missing)}")
        self.providers = dict(providers)
        self.policy = policy or RuntimePolicy()
        self.budget = budget or RuntimeBudget()
        self.cache = cache or ProviderResponseCache()
        self.audit_sink = audit_sink
        self.audit_records: list[ProviderAuditRecord] = []
        self._semaphore = asyncio.Semaphore(self.policy.maximum_concurrency)
        self._rate_lock = asyncio.Lock()
        self._budget_lock = asyncio.Lock()
        self._request_times: deque[float] = deque()
        self._budget_usage = _BudgetUsage()
        self._consecutive_failures: dict[str, int] = {}
        self._circuit_opened_at: dict[str, float] = {}

    @property
    def budget_usage(self) -> ProviderUsage:
        return ProviderUsage(
            input_tokens=self._budget_usage.input_tokens,
            output_tokens=self._budget_usage.output_tokens,
            total_tokens=self._budget_usage.input_tokens + self._budget_usage.output_tokens,
            estimated_cost_usd=self._budget_usage.cost_usd,
        )

    async def release(self) -> None:
        """Release each distinct provider once so later GPU stages can reclaim VRAM."""

        released: set[int] = set()
        for provider in self.providers.values():
            identity = id(provider)
            if identity in released:
                continue
            await provider.release()
            released.add(identity)

    @property
    def provider_attempts(self) -> int:
        return self._budget_usage.provider_attempts

    async def _record(self, record: ProviderAuditRecord) -> None:
        self.audit_records.append(record)
        if self.audit_sink is not None:
            await self.audit_sink.write(record)

    def _validate_boundary(
        self,
        provider: CreativeModelProvider,
        request: CreativeModelRequest[Any],
    ) -> None:
        if request.images and not provider.capabilities.image_input:
            raise ProviderError(
                ProviderFailureType.CAPABILITY_MISMATCH,
                f"{provider.provider_id} does not support image input",
            )
        if len(request.images) > provider.capabilities.maximum_images:
            raise ProviderError(
                ProviderFailureType.CAPABILITY_MISMATCH,
                "request exceeds the provider image limit",
            )
        if request.audio and not provider.capabilities.audio_input:
            raise ProviderError(
                ProviderFailureType.CAPABILITY_MISMATCH,
                f"{provider.provider_id} does not support audio input",
            )
        audio_seconds = sum(item.duration_seconds for item in request.audio)
        if audio_seconds > provider.capabilities.maximum_audio_seconds:
            raise ProviderError(
                ProviderFailureType.CAPABILITY_MISMATCH,
                "request exceeds the provider audio-duration limit",
            )
        if not provider.capabilities.strict_structured_output:
            raise ProviderError(
                ProviderFailureType.CAPABILITY_MISMATCH,
                f"{provider.provider_id} does not support strict structured output",
            )
        if (
            request.estimated_input_tokens + request.max_output_tokens
            > provider.capabilities.maximum_context_tokens
        ):
            raise ProviderError(
                ProviderFailureType.CAPABILITY_MISMATCH,
                "request exceeds the provider context window",
            )
        if provider.boundary != ProviderBoundary.LOCAL:
            if not self.policy.network_enabled:
                raise ProviderError(
                    ProviderFailureType.OFFLINE,
                    "network access is disabled for creative providers",
                )
            if not self.policy.cloud_provider_enabled:
                raise ProviderError(
                    ProviderFailureType.OFFLINE,
                    "cloud creative providers are disabled by feature flag",
                )
            if (request.images or request.audio) and not request.cloud_upload_consent:
                raise ProviderError(
                    ProviderFailureType.CLOUD_CONSENT_REQUIRED,
                    "explicit consent is required before representative frames or audio "
                    "leave the device",
                )

    def _check_circuit(self, provider: CreativeModelProvider) -> None:
        opened_at = self._circuit_opened_at.get(provider.provider_id)
        if opened_at is None:
            return
        if time.monotonic() - opened_at >= self.policy.circuit_cooldown_seconds:
            self._circuit_opened_at.pop(provider.provider_id, None)
            self._consecutive_failures[provider.provider_id] = 0
            return
        raise ProviderError(
            ProviderFailureType.CIRCUIT_OPEN,
            f"provider circuit is open for {provider.provider_id}",
        )

    async def _take_rate_slot(self) -> None:
        async with self._rate_lock:
            now = time.monotonic()
            while self._request_times and now - self._request_times[0] >= 60:
                self._request_times.popleft()
            if len(self._request_times) >= self.policy.requests_per_minute:
                wait_seconds = 60 - (now - self._request_times[0])
                raise ProviderError(
                    ProviderFailureType.RATE_LIMITED,
                    "local provider rate limit reached",
                    retryable=True,
                    retry_after_seconds=max(0, wait_seconds),
                )
            self._request_times.append(now)

    async def _reserve_attempt(self, request: CreativeModelRequest[Any]) -> None:
        async with self._budget_lock:
            if self._budget_usage.provider_attempts >= self.budget.maximum_provider_attempts:
                raise ProviderError(
                    ProviderFailureType.BUDGET_EXHAUSTED,
                    "provider attempt budget exhausted",
                )
            if (
                self._budget_usage.output_tokens + request.max_output_tokens
                > self.budget.maximum_output_tokens
            ):
                raise ProviderError(
                    ProviderFailureType.BUDGET_EXHAUSTED,
                    "requested output would exceed the output-token budget",
                )
            self._budget_usage.provider_attempts += 1

    async def _charge_usage(self, usage: ProviderUsage) -> None:
        async with self._budget_lock:
            projected_input = self._budget_usage.input_tokens + usage.input_tokens
            projected_output = self._budget_usage.output_tokens + usage.output_tokens
            projected_cost = self._budget_usage.cost_usd + usage.estimated_cost_usd
            self._budget_usage.input_tokens = projected_input
            self._budget_usage.output_tokens = projected_output
            self._budget_usage.cost_usd = projected_cost
            if (
                projected_input > self.budget.maximum_input_tokens
                or projected_output > self.budget.maximum_output_tokens
                or projected_cost > self.budget.maximum_cost_usd
            ):
                raise ProviderError(
                    ProviderFailureType.BUDGET_EXHAUSTED,
                    "provider response exceeded the configured token or cost budget",
                )

    async def run(
        self,
        request: CreativeModelRequest[OutputT],
    ) -> CreativeModelResult[OutputT]:
        provider = self.providers[request.role]
        digest = request_digest(request)
        cache_key = response_cache_key(request, provider)
        started = time.perf_counter()
        attempts = 0
        last_usage = ProviderUsage()
        try:
            self._validate_boundary(provider, request)
            self._check_circuit(provider)
            try:
                cached = self.cache.get(cache_key)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise ProviderError(
                    ProviderFailureType.INTERNAL,
                    "provider response cache is unreadable",
                ) from exc
            if cached is not None:
                try:
                    parsed = request.output_model.model_validate_json(
                        _canonical_json(cached),
                        strict=True,
                    )
                except ValidationError as exc:
                    raise ProviderError(
                        ProviderFailureType.INTERNAL,
                        "provider response cache does not satisfy the requested schema",
                    ) from exc
                record = ProviderAuditRecord(
                    timestamp=_utc_now(),
                    request_id=request.request_id,
                    request_digest=digest,
                    cache_key=cache_key,
                    role=request.role,
                    provider_id=provider.provider_id,
                    boundary=provider.boundary,
                    model_id=provider.model_id,
                    model_revision=provider.model_revision,
                    prompt_version=request.prompt_version,
                    schema_version=request.schema_version,
                    attempt_count=0,
                    latency_ms=(time.perf_counter() - started) * 1_000,
                    cache_hit=True,
                    success=True,
                    usage=ProviderUsage(),
                    structured_response=parsed.model_dump(mode="json"),
                )
                await self._record(record)
                return CreativeModelResult(output=parsed, audit=record)

            strict_schema = strict_output_schema(request.output_model)
            async with self._semaphore:
                for attempt in range(self.policy.maximum_retries + 1):
                    retry_error: ProviderError | None = None
                    try:
                        await self._take_rate_slot()
                        await self._reserve_attempt(request)
                        attempts += 1
                        raw = await asyncio.wait_for(
                            provider.generate(request, strict_schema=strict_schema),
                            timeout=self.policy.timeout_seconds,
                        )
                        last_usage = raw.usage
                        await self._charge_usage(raw.usage)
                        if raw.refusal is not None:
                            raise ProviderError(
                                ProviderFailureType.REFUSAL,
                                "provider returned an explicit model refusal",
                            )
                        if raw.incomplete_reason is not None:
                            raise ProviderError(
                                ProviderFailureType.INCOMPLETE,
                                f"provider response was incomplete: {raw.incomplete_reason}",
                            )
                        if raw.text is None:
                            raise ProviderError(
                                ProviderFailureType.BAD_JSON,
                                "provider response did not contain output text",
                            )
                        try:
                            json.loads(raw.text)
                        except json.JSONDecodeError as exc:
                            raise ProviderError(
                                ProviderFailureType.BAD_JSON,
                                "provider output was not valid JSON",
                            ) from exc
                        try:
                            parsed = request.output_model.model_validate_json(
                                raw.text,
                                strict=True,
                            )
                        except ValidationError as exc:
                            raise ProviderError(
                                ProviderFailureType.SCHEMA_INVALID,
                                "provider JSON did not satisfy the requested schema",
                            ) from exc
                        self.cache.put(cache_key, parsed.model_dump(mode="json"))
                        self._consecutive_failures[provider.provider_id] = 0
                        record = ProviderAuditRecord(
                            timestamp=_utc_now(),
                            request_id=request.request_id,
                            request_digest=digest,
                            cache_key=cache_key,
                            role=request.role,
                            provider_id=provider.provider_id,
                            boundary=provider.boundary,
                            model_id=provider.model_id,
                            model_revision=raw.model_revision or provider.model_revision,
                            prompt_version=request.prompt_version,
                            schema_version=request.schema_version,
                            attempt_count=attempts,
                            latency_ms=(time.perf_counter() - started) * 1_000,
                            cache_hit=False,
                            success=True,
                            response_id=raw.response_id,
                            usage=raw.usage,
                            hardware_evidence=raw.hardware_evidence,
                            structured_response=parsed.model_dump(mode="json"),
                        )
                        await self._record(record)
                        return CreativeModelResult(output=parsed, audit=record)
                    except TimeoutError as exc:
                        retry_error = ProviderError(
                            ProviderFailureType.TIMEOUT,
                            "provider request timed out",
                            retryable=True,
                        )
                        if attempt >= self.policy.maximum_retries:
                            raise retry_error from exc
                    except ProviderError as error:
                        if not error.retryable or attempt >= self.policy.maximum_retries:
                            raise
                        retry_error = error
                    assert retry_error is not None
                    delay = (
                        retry_error.retry_after_seconds
                        if retry_error.retry_after_seconds is not None
                        else self.policy.retry_base_seconds * (2**attempt)
                    )
                    if delay > 0:
                        await asyncio.sleep(delay)
            raise AssertionError("provider retry loop exited without a result")
        except asyncio.CancelledError:
            record = self._failure_record(
                request=request,
                provider=provider,
                digest=digest,
                cache_key=cache_key,
                started=started,
                attempts=attempts,
                usage=last_usage,
                failure_type=ProviderFailureType.CANCELLED,
            )
            await asyncio.shield(self._record(record))
            raise
        except ProviderError as exc:
            circuit_failures = {
                ProviderFailureType.TIMEOUT,
                ProviderFailureType.RATE_LIMITED,
                ProviderFailureType.BAD_JSON,
                ProviderFailureType.SCHEMA_INVALID,
                ProviderFailureType.PROVIDER_UNAVAILABLE,
                ProviderFailureType.INTERNAL,
            }
            provider_rate_limit = (
                exc.failure_type == ProviderFailureType.RATE_LIMITED
                and exc.status_code is not None
            )
            if exc.failure_type in circuit_failures and (
                exc.failure_type != ProviderFailureType.RATE_LIMITED
                or provider_rate_limit
            ):
                failures = self._consecutive_failures.get(provider.provider_id, 0) + 1
                self._consecutive_failures[provider.provider_id] = failures
                if failures >= self.policy.circuit_failure_threshold:
                    self._circuit_opened_at[provider.provider_id] = time.monotonic()
            record = self._failure_record(
                request=request,
                provider=provider,
                digest=digest,
                cache_key=cache_key,
                started=started,
                attempts=attempts,
                usage=last_usage,
                failure_type=exc.failure_type,
            )
            await self._record(record)
            raise

    def _failure_record(
        self,
        *,
        request: CreativeModelRequest[Any],
        provider: CreativeModelProvider,
        digest: str,
        cache_key: str,
        started: float,
        attempts: int,
        usage: ProviderUsage,
        failure_type: ProviderFailureType,
    ) -> ProviderAuditRecord:
        return ProviderAuditRecord(
            timestamp=_utc_now(),
            request_id=request.request_id,
            request_digest=digest,
            cache_key=cache_key,
            role=request.role,
            provider_id=provider.provider_id,
            boundary=provider.boundary,
            model_id=provider.model_id,
            model_revision=provider.model_revision,
            prompt_version=request.prompt_version,
            schema_version=request.schema_version,
            attempt_count=attempts,
            latency_ms=(time.perf_counter() - started) * 1_000,
            cache_hit=False,
            success=False,
            failure_type=failure_type,
            usage=usage,
        )

    async def run_or_fallback(
        self,
        request: CreativeModelRequest[OutputT],
        *,
        fallback_route: str = "local-clip-rule-planner",
    ) -> CreativeModelResult[OutputT] | FallbackDecision:
        try:
            return await self.run(request)
        except ProviderError as exc:
            return FallbackDecision(
                route=fallback_route,
                reason=exc.failure_type,
                detail=str(exc),
                request_digest=request_digest(request),
            )

    async def shadow_replay(
        self,
        requests: Sequence[CreativeModelRequest[OutputT]],
    ) -> list[CreativeModelResult[OutputT] | FallbackDecision]:
        """Replay frozen requests without applying any response to project state."""

        return list(
            await asyncio.gather(
                *(self.run_or_fallback(request) for request in requests)
            )
        )


def provider_runtime_configuration_digest(runtime: CreativeProviderRuntime) -> str:
    """Bind a run to provider identities, capabilities, policy, and budget."""

    return _sha256(
        _canonical_json(
            {
                "runtime_version": PROVIDER_RUNTIME_VERSION,
                "providers": {
                    role.value: {
                        "provider_id": provider.provider_id,
                        "boundary": provider.boundary,
                        "model_id": provider.model_id,
                        "model_revision": provider.model_revision,
                        "capabilities": provider.capabilities.model_dump(mode="json"),
                        "hardware_policy": {
                            "expected_quantization_level": getattr(
                                provider,
                                "expected_quantization_level",
                                None,
                            ),
                            "require_gpu": getattr(provider, "require_gpu", None),
                            "minimum_gpu_offload_ratio": getattr(
                                provider,
                                "minimum_gpu_offload_ratio",
                                None,
                            ),
                        },
                    }
                    for role, provider in sorted(
                        runtime.providers.items(),
                        key=lambda item: item[0].value,
                    )
                },
                "policy": asdict(runtime.policy),
                "budget": asdict(runtime.budget),
            }
        )
    )


class FakeCreativeModelProvider(CreativeModelProvider):
    def __init__(
        self,
        *,
        responses: Sequence[RawProviderResponse | Exception | Callable[[], Awaitable[Any]]],
        provider_id: str = "fake",
        model_id: str = "fake-multimodal",
        model_revision: str = "test",
        boundary: ProviderBoundary = ProviderBoundary.LOCAL,
        capabilities: ProviderCapabilities | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.model_id = model_id
        self.model_revision = model_revision
        self.boundary = boundary
        self.capabilities = capabilities or ProviderCapabilities(
            image_input=True,
            strict_structured_output=True,
            maximum_context_tokens=32_768,
            maximum_images=32,
            batch_requests=False,
        )
        self._responses = deque(responses)
        self.calls = 0
        self.schemas: list[dict[str, Any]] = []
        self.requests: list[CreativeModelRequest[Any]] = []

    async def generate(
        self,
        request: CreativeModelRequest[Any],
        *,
        strict_schema: dict[str, Any],
    ) -> RawProviderResponse:
        self.calls += 1
        self.schemas.append(strict_schema)
        self.requests.append(request)
        if not self._responses:
            raise ProviderError(
                ProviderFailureType.PROVIDER_UNAVAILABLE,
                "fake provider has no queued response",
            )
        response = self._responses.popleft()
        if isinstance(response, Exception):
            raise response
        if callable(response):
            response = await response()
        if not isinstance(response, RawProviderResponse):
            raise TypeError("fake provider callback must return RawProviderResponse")
        return response


class OpenAIResponsesProvider(CreativeModelProvider):
    """Real OpenAI Responses API adapter, disabled unless explicitly feature-gated."""

    def __init__(
        self,
        *,
        model_id: str,
        model_revision: str,
        api_key_getter: Callable[[], str | None],
        enabled: bool = False,
        base_url: str = "https://api.openai.com/v1",
        provider_id: str = "openai-responses",
        capabilities: ProviderCapabilities,
        input_cost_per_million_tokens: float,
        output_cost_per_million_tokens: float,
        reasoning_effort: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("creative provider endpoints must use HTTPS unless they are local")
        official = parsed.hostname == "api.openai.com"
        self.provider_id = provider_id
        self.model_id = model_id
        self.model_revision = model_revision
        self.api_key_getter = api_key_getter
        self.enabled = enabled
        self.base_url = base_url.rstrip("/")
        self.boundary = (
            ProviderBoundary.OPENAI if official else ProviderBoundary.OPENAI_COMPATIBLE
        )
        if capabilities.audio_input:
            raise ValueError(
                "the OpenAI Responses adapter does not declare audio input support"
            )
        self.capabilities = capabilities
        if input_cost_per_million_tokens < 0 or output_cost_per_million_tokens < 0:
            raise ValueError("configured provider token prices must be non-negative")
        self.input_cost_per_million_tokens = input_cost_per_million_tokens
        self.output_cost_per_million_tokens = output_cost_per_million_tokens
        if reasoning_effort not in {None, "none", "low", "medium", "high", "max"}:
            raise ValueError("unsupported provider reasoning effort")
        self.reasoning_effort = reasoning_effort
        self._client = client

    async def generate(
        self,
        request: CreativeModelRequest[Any],
        *,
        strict_schema: dict[str, Any],
    ) -> RawProviderResponse:
        if not self.enabled:
            raise ProviderError(
                ProviderFailureType.OFFLINE,
                "OpenAI Responses provider feature flag is disabled",
            )
        api_key = self.api_key_getter()
        if not api_key:
            raise ProviderError(
                ProviderFailureType.AUTHENTICATION,
                "OpenAI API credential is unavailable",
            )
        content: list[dict[str, Any]] = [{"type": "input_text", "text": request.prompt}]
        for image in request.images:
            encoded = base64.b64encode(image.content).decode("ascii")
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{image.media_type};base64,{encoded}",
                    "detail": image.detail,
                }
            )
        schema_name = request.output_model.__name__.lower()[:64]
        payload = {
            "model": self.model_id,
            "input": [{"role": "user", "content": content}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": strict_schema,
                    "strict": True,
                }
            },
            "max_output_tokens": request.max_output_tokens,
            "store": False,
        }
        if self.reasoning_effort is not None:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=None)
        try:
            response = await client.post(
                f"{self.base_url}/responses",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                ProviderFailureType.TIMEOUT,
                "OpenAI Responses request timed out",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                ProviderFailureType.PROVIDER_UNAVAILABLE,
                "OpenAI Responses request failed",
                retryable=True,
            ) from exc
        finally:
            if owns_client:
                with suppress(TimeoutError):
                    await asyncio.wait_for(client.aclose(), timeout=5)
        if response.status_code >= 400:
            retryable = response.status_code in {408, 409, 429, 500, 502, 503, 504}
            failure_type = (
                ProviderFailureType.RATE_LIMITED
                if response.status_code == 429
                else (
                    ProviderFailureType.AUTHENTICATION
                    if response.status_code in {401, 403}
                    else ProviderFailureType.PROVIDER_UNAVAILABLE
                )
            )
            retry_after = response.headers.get("retry-after")
            try:
                retry_after_seconds = float(retry_after) if retry_after else None
            except ValueError:
                retry_after_seconds = None
            raise ProviderError(
                failure_type,
                f"OpenAI Responses returned HTTP {response.status_code}",
                retryable=retryable,
                retry_after_seconds=retry_after_seconds,
                status_code=response.status_code,
            )
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderError(
                ProviderFailureType.BAD_JSON,
                "OpenAI Responses returned a non-JSON response body",
            ) from exc
        usage_body = body.get("usage") or {}
        input_tokens = int(usage_body.get("input_tokens", 0))
        output_tokens = int(usage_body.get("output_tokens", 0))
        usage = ProviderUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=int(usage_body.get("total_tokens", 0)),
            estimated_cost_usd=(
                input_tokens * self.input_cost_per_million_tokens
                + output_tokens * self.output_cost_per_million_tokens
            )
            / 1_000_000,
        )
        refusal: str | None = None
        output_text: str | None = body.get("output_text")
        if output_text is None:
            for item in body.get("output", []):
                if item.get("type") != "message":
                    continue
                for part in item.get("content", []):
                    if part.get("type") == "refusal":
                        refusal = str(part.get("refusal", "model refused the request"))
                    elif part.get("type") == "output_text":
                        output_text = part.get("text")
        status = body.get("status")
        incomplete_reason = None
        if status == "incomplete":
            incomplete_reason = str(
                (body.get("incomplete_details") or {}).get("reason", "unknown")
            )
        elif status != "completed":
            error = body.get("error") or {}
            error_code = error.get("code") if isinstance(error, dict) else None
            incomplete_reason = (
                f"{status}:{error_code}" if error_code else str(status or "unknown")
            )
        return RawProviderResponse(
            text=output_text,
            usage=usage,
            response_id=body.get("id"),
            model_revision=body.get("model") or self.model_revision,
            refusal=refusal,
            incomplete_reason=incomplete_reason,
        )


@dataclass(frozen=True, slots=True)
class _OllamaModelIdentity:
    quantization_level: str


class OllamaResponsesProvider(CreativeModelProvider):
    """Pinned native Ollama Generate adapter with structural grammar and validation."""

    provider_id = "ollama-generate-structural-local"

    def __init__(
        self,
        *,
        model_id: str,
        expected_model_digest: str,
        expected_runtime_version: str,
        expected_quantization_level: str = "Q4_K_M",
        require_gpu: bool = True,
        minimum_gpu_offload_ratio: float = 0.99,
        unload_after_request: bool = True,
        enabled: bool = False,
        base_url: str = "http://127.0.0.1:11434",
        capabilities: ProviderCapabilities,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed = urlparse(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError(
                "the local Ollama creative provider must use a loopback endpoint"
            )
        if (
            len(expected_model_digest) != 64
            or expected_model_digest.lower() != expected_model_digest
            or any(char not in "0123456789abcdef" for char in expected_model_digest)
        ):
            raise ValueError(
                "COLORGRAPH_OLLAMA_CREATIVE_MODEL_DIGEST must be a lowercase "
                "SHA-256 value"
            )
        if not expected_runtime_version.strip():
            raise ValueError(
                "COLORGRAPH_OLLAMA_CREATIVE_RUNTIME_VERSION must be configured"
            )
        if not expected_quantization_level.strip():
            raise ValueError(
                "COLORGRAPH_OLLAMA_CREATIVE_QUANTIZATION must be configured"
            )
        if not 0 <= minimum_gpu_offload_ratio <= 1:
            raise ValueError(
                "COLORGRAPH_OLLAMA_CREATIVE_MIN_GPU_OFFLOAD_RATIO must be within [0, 1]"
            )
        if require_gpu and minimum_gpu_offload_ratio <= 0:
            raise ValueError(
                "GPU-required Ollama providers need a positive minimum offload ratio"
            )
        if not capabilities.image_input:
            raise ValueError("the Ollama provider must explicitly declare image input")
        if not capabilities.strict_structured_output:
            raise ValueError(
                "the Ollama provider must explicitly declare strict structured output"
            )
        if capabilities.audio_input:
            raise ValueError("the Ollama Responses adapter does not support audio")
        self.provider_id = type(self).provider_id
        self.model_id = model_id
        self.model_revision = (
            f"ollama-{expected_runtime_version}/sha256:{expected_model_digest}"
        )
        self.boundary = ProviderBoundary.LOCAL
        self.capabilities = capabilities
        self.enabled = enabled
        self.expected_model_digest = expected_model_digest
        self.expected_runtime_version = expected_runtime_version
        self.expected_quantization_level = expected_quantization_level
        self.require_gpu = require_gpu
        self.minimum_gpu_offload_ratio = minimum_gpu_offload_ratio
        self.unload_after_request = unload_after_request
        native_root = base_url.rstrip("/")
        if native_root.endswith("/v1"):
            native_root = native_root[:-3]
        self.native_root = native_root.rstrip("/")
        self._client = client

    async def _preflight(self, client: httpx.AsyncClient) -> _OllamaModelIdentity:
        try:
            version_response = await client.get(f"{self.native_root}/api/version")
            tags_response = await client.get(f"{self.native_root}/api/tags")
            show_response = await client.post(
                f"{self.native_root}/api/show",
                json={"model": self.model_id, "verbose": False},
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                ProviderFailureType.TIMEOUT,
                "local Ollama capability preflight timed out",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                ProviderFailureType.PROVIDER_UNAVAILABLE,
                "local Ollama capability preflight failed",
                retryable=True,
            ) from exc

        responses = (version_response, tags_response, show_response)
        if any(response.status_code >= 400 for response in responses):
            status_codes = ",".join(str(response.status_code) for response in responses)
            raise ProviderError(
                ProviderFailureType.PROVIDER_UNAVAILABLE,
                f"local Ollama capability preflight returned HTTP {status_codes}",
                retryable=True,
            )
        try:
            version_body = version_response.json()
            tags_body = tags_response.json()
            show_body = show_response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderError(
                ProviderFailureType.BAD_JSON,
                "local Ollama capability preflight returned invalid JSON",
            ) from exc

        observed_version = str(version_body.get("version", ""))
        if observed_version != self.expected_runtime_version:
            raise ProviderError(
                ProviderFailureType.CAPABILITY_MISMATCH,
                "local Ollama runtime version differs from the pinned version",
            )
        matching_models = [
            model
            for model in tags_body.get("models", [])
            if isinstance(model, dict)
            and str(model.get("name") or model.get("model")) == self.model_id
        ]
        if len(matching_models) != 1:
            raise ProviderError(
                ProviderFailureType.CAPABILITY_MISMATCH,
                "the pinned local Ollama model name was not found exactly once",
            )
        observed_digest = str(matching_models[0].get("digest", "")).removeprefix(
            "sha256:"
        )
        if observed_digest != self.expected_model_digest:
            raise ProviderError(
                ProviderFailureType.CAPABILITY_MISMATCH,
                "local Ollama model digest differs from the pinned digest",
            )
        tag_details = matching_models[0].get("details")
        show_details = show_body.get("details")
        quantization_candidates = [
            details.get("quantization_level")
            for details in (tag_details, show_details)
            if isinstance(details, dict)
        ]
        observed_quantization = next(
            (
                str(value)
                for value in quantization_candidates
                if isinstance(value, str) and value.strip()
            ),
            "",
        )
        if observed_quantization != self.expected_quantization_level:
            raise ProviderError(
                ProviderFailureType.CAPABILITY_MISMATCH,
                "local Ollama model quantization differs from the pinned level",
            )

        observed_capabilities = {
            str(value) for value in show_body.get("capabilities", [])
        }
        if not {"completion", "vision"}.issubset(observed_capabilities):
            raise ProviderError(
                ProviderFailureType.CAPABILITY_MISMATCH,
                "local Ollama model does not report completion and vision capabilities",
            )
        model_info = show_body.get("model_info")
        context_values = (
            [
                int(value)
                for key, value in model_info.items()
                if str(key).endswith(".context_length")
                and isinstance(value, (int, float))
            ]
            if isinstance(model_info, dict)
            else []
        )
        if (
            not context_values
            or max(context_values) < self.capabilities.maximum_context_tokens
        ):
            raise ProviderError(
                ProviderFailureType.CAPABILITY_MISMATCH,
                "local Ollama model context is below the declared capability",
            )
        return _OllamaModelIdentity(
            quantization_level=observed_quantization,
        )

    async def _verify_loaded_context(
        self,
        client: httpx.AsyncClient,
        identity: _OllamaModelIdentity,
    ) -> ProviderHardwareEvidence:
        try:
            response = await client.get(f"{self.native_root}/api/ps")
        except httpx.HTTPError as exc:
            raise ProviderError(
                ProviderFailureType.PROVIDER_UNAVAILABLE,
                "local Ollama loaded-context verification failed",
                retryable=True,
            ) from exc
        if response.status_code >= 400:
            raise ProviderError(
                ProviderFailureType.PROVIDER_UNAVAILABLE,
                "local Ollama loaded-context verification returned "
                f"HTTP {response.status_code}",
                retryable=True,
            )
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderError(
                ProviderFailureType.BAD_JSON,
                "local Ollama loaded-context verification returned invalid JSON",
            ) from exc
        matches = [
            model
            for model in body.get("models", [])
            if isinstance(model, dict)
            and str(model.get("name") or model.get("model")) == self.model_id
        ]
        if len(matches) != 1:
            raise ProviderError(
                ProviderFailureType.CAPABILITY_MISMATCH,
                "the generated Ollama model is not present exactly once in /api/ps",
            )
        digest = str(matches[0].get("digest", "")).removeprefix("sha256:")
        context_length = matches[0].get("context_length")
        if (
            digest != self.expected_model_digest
            or not isinstance(context_length, int)
            or context_length < self.capabilities.maximum_context_tokens
        ):
            raise ProviderError(
                ProviderFailureType.CAPABILITY_MISMATCH,
                "local Ollama loaded model digest or actual context allocation "
                "differs from the pinned capability",
            )
        model_size = matches[0].get("size")
        vram_size = matches[0].get("size_vram")
        if (
            not isinstance(model_size, int)
            or isinstance(model_size, bool)
            or model_size <= 0
            or not isinstance(vram_size, int)
            or isinstance(vram_size, bool)
            or vram_size < 0
        ):
            raise ProviderError(
                ProviderFailureType.CAPABILITY_MISMATCH,
                "local Ollama process report lacks valid model and VRAM sizes",
            )
        offload_ratio = min(vram_size / model_size, 1.0)
        gpu_verified = (
            vram_size > 0
            and offload_ratio >= self.minimum_gpu_offload_ratio
        )
        if self.require_gpu and not gpu_verified:
            raise ProviderError(
                ProviderFailureType.CAPABILITY_MISMATCH,
                "local Ollama model is not sufficiently resident on the GPU",
            )
        return ProviderHardwareEvidence(
            model_name=self.model_id,
            model_digest=digest,
            quantization_level=identity.quantization_level,
            context_length=context_length,
            model_size_bytes=model_size,
            vram_size_bytes=vram_size,
            gpu_offload_ratio=offload_ratio,
            minimum_required_gpu_offload_ratio=self.minimum_gpu_offload_ratio,
            gpu_required=self.require_gpu,
            gpu_verified=gpu_verified,
        )

    async def _unload(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            f"{self.native_root}/api/generate",
            json={"model": self.model_id, "keep_alive": 0},
        )
        if response.status_code >= 400:
            raise ProviderError(
                ProviderFailureType.PROVIDER_UNAVAILABLE,
                f"local Ollama unload returned HTTP {response.status_code}",
                retryable=True,
            )
        deadline = time.monotonic() + OLLAMA_UNLOAD_VERIFICATION_TIMEOUT_SECONDS
        while True:
            processes = await client.get(f"{self.native_root}/api/ps")
            if processes.status_code >= 400:
                raise ProviderError(
                    ProviderFailureType.PROVIDER_UNAVAILABLE,
                    "local Ollama unload verification returned "
                    f"HTTP {processes.status_code}",
                    retryable=True,
                )
            try:
                body = processes.json()
            except (json.JSONDecodeError, ValueError) as exc:
                raise ProviderError(
                    ProviderFailureType.BAD_JSON,
                    "local Ollama unload verification returned invalid JSON",
                ) from exc
            still_loaded = any(
                isinstance(model, dict)
                and str(model.get("name") or model.get("model")) == self.model_id
                for model in body.get("models", [])
            )
            if not still_loaded:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderError(
                    ProviderFailureType.CAPABILITY_MISMATCH,
                    "local Ollama model remained loaded after the release request",
                )
            await asyncio.sleep(
                min(OLLAMA_UNLOAD_VERIFICATION_INTERVAL_SECONDS, remaining)
            )

    async def release(self) -> None:
        """Unload the pinned runner and verify that Ollama released its VRAM."""

        if not self.enabled:
            return
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=None, trust_env=False)
        try:
            await self._unload(client)
        except httpx.HTTPError as exc:
            raise ProviderError(
                ProviderFailureType.PROVIDER_UNAVAILABLE,
                "local Ollama unload request failed",
                retryable=True,
            ) from exc
        finally:
            if owns_client:
                with suppress(TimeoutError):
                    await asyncio.wait_for(client.aclose(), timeout=5)

    async def generate(
        self,
        request: CreativeModelRequest[Any],
        *,
        strict_schema: dict[str, Any],
    ) -> RawProviderResponse:
        if not self.enabled:
            raise ProviderError(
                ProviderFailureType.OFFLINE,
                "local Ollama creative provider feature flag is disabled",
            )
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=None,
            trust_env=False,
        )
        try:
            model_identity = await self._preflight(client)
            payload: dict[str, Any] = {
                "model": self.model_id,
                "prompt": request.prompt,
                "stream": False,
                "think": False,
                "format": _ollama_structural_schema(strict_schema),
                "options": {
                    "num_ctx": self.capabilities.maximum_context_tokens,
                    "num_predict": request.max_output_tokens,
                    "seed": 0,
                    "temperature": 0,
                },
                "keep_alive": "10m",
            }
            if request.images:
                payload["images"] = [
                    base64.b64encode(image.content).decode("ascii")
                    for image in request.images
                ]
            response = await client.post(
                f"{self.native_root}/api/generate",
                json=payload,
            )
            if response.status_code >= 400:
                retryable = response.status_code in {
                    408,
                    409,
                    429,
                    500,
                    502,
                    503,
                    504,
                }
                failure_type = (
                    ProviderFailureType.RATE_LIMITED
                    if response.status_code == 429
                    else ProviderFailureType.PROVIDER_UNAVAILABLE
                )
                raise ProviderError(
                    failure_type,
                    f"local Ollama Generate returned HTTP {response.status_code}",
                    retryable=retryable,
                    status_code=response.status_code,
                )
            try:
                body = response.json()
            except (json.JSONDecodeError, ValueError) as exc:
                raise ProviderError(
                    ProviderFailureType.BAD_JSON,
                    "local Ollama Generate returned an invalid JSON response body",
                ) from exc

            output_text = (
                body.get("response")
                if isinstance(body.get("response"), str)
                else None
            )
            thinking = body.get("thinking")
            done = body.get("done")
            done_reason = str(body.get("done_reason") or "")
            incomplete_reason = None
            if done is not True:
                incomplete_reason = f"done:{done!r}"
            elif done_reason != "stop":
                incomplete_reason = f"done_reason:{done_reason or 'missing'}"
            elif isinstance(thinking, str) and thinking.strip():
                incomplete_reason = "thinking_not_disabled"

            input_tokens = int(body.get("prompt_eval_count", 0))
            output_tokens = int(body.get("eval_count", 0))
            usage = ProviderUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                estimated_cost_usd=0,
            )
            hardware_evidence = await self._verify_loaded_context(
                client,
                model_identity,
            )
            if self.unload_after_request:
                await self._unload(client)
                hardware_evidence = hardware_evidence.model_copy(
                    update={"vram_release_verified": True}
                )
            receipt_payload = {
                "provider_id": self.provider_id,
                "model_id": self.model_id,
                "request_digest": request_digest(request),
                "created_at": body.get("created_at"),
                "response": output_text,
                "thinking": thinking,
                "done": done,
                "done_reason": body.get("done_reason"),
                "prompt_eval_count": input_tokens,
                "eval_count": output_tokens,
                "hardware_evidence": hardware_evidence.model_dump(mode="json"),
            }
            response_id = (
                "ollama_local_"
                f"{_sha256(_canonical_json(receipt_payload))[:24]}"
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                ProviderFailureType.TIMEOUT,
                "local Ollama Generate request timed out",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                ProviderFailureType.PROVIDER_UNAVAILABLE,
                "local Ollama Generate request failed",
                retryable=True,
            ) from exc
        finally:
            if owns_client:
                with suppress(TimeoutError):
                    await asyncio.wait_for(client.aclose(), timeout=5)

        return RawProviderResponse(
            text=output_text,
            usage=usage,
            response_id=response_id,
            model_revision=self.model_revision,
            incomplete_reason=incomplete_reason,
            hardware_evidence=hardware_evidence,
        )


class OpenAIProviderSettings(Protocol):
    enable_openai_creative_provider: bool
    openai_creative_model: str
    openai_creative_model_revision: str
    openai_creative_base_url: str
    openai_creative_input_cost_per_million: float
    openai_creative_output_cost_per_million: float


class OllamaProviderSettings(Protocol):
    enable_ollama_creative_provider: bool
    ollama_creative_model: str
    ollama_creative_model_digest: str
    ollama_creative_runtime_version: str
    ollama_creative_quantization: str
    ollama_creative_require_gpu: bool
    ollama_creative_min_gpu_offload_ratio: float
    ollama_creative_unload_after_request: bool
    ollama_creative_base_url: str
    ollama_creative_image_input: bool
    ollama_creative_strict_structured_output: bool
    ollama_creative_max_context_tokens: int
    ollama_creative_max_images: int


def configured_openai_provider(
    provider_settings: OpenAIProviderSettings,
    *,
    capabilities: ProviderCapabilities,
    api_key_getter: Callable[[], str | None],
    client: httpx.AsyncClient | None = None,
) -> OpenAIResponsesProvider:
    """Build the real adapter from explicit settings without reading or retaining a secret."""

    if not provider_settings.openai_creative_model:
        raise ValueError("COLORGRAPH_OPENAI_CREATIVE_MODEL must be explicitly configured")
    return OpenAIResponsesProvider(
        model_id=provider_settings.openai_creative_model,
        model_revision=provider_settings.openai_creative_model_revision,
        api_key_getter=api_key_getter,
        enabled=provider_settings.enable_openai_creative_provider,
        base_url=provider_settings.openai_creative_base_url,
        capabilities=capabilities,
        input_cost_per_million_tokens=(
            provider_settings.openai_creative_input_cost_per_million
        ),
        output_cost_per_million_tokens=(
            provider_settings.openai_creative_output_cost_per_million
        ),
        client=client,
    )


def configured_ollama_provider(
    provider_settings: OllamaProviderSettings,
    *,
    capabilities: ProviderCapabilities,
    client: httpx.AsyncClient | None = None,
) -> OllamaResponsesProvider:
    """Build a digest-pinned local adapter without retaining any credential."""

    if not provider_settings.ollama_creative_model.strip():
        raise ValueError("COLORGRAPH_OLLAMA_CREATIVE_MODEL must be configured")
    return OllamaResponsesProvider(
        model_id=provider_settings.ollama_creative_model,
        expected_model_digest=provider_settings.ollama_creative_model_digest,
        expected_runtime_version=provider_settings.ollama_creative_runtime_version,
        expected_quantization_level=provider_settings.ollama_creative_quantization,
        require_gpu=provider_settings.ollama_creative_require_gpu,
        minimum_gpu_offload_ratio=(
            provider_settings.ollama_creative_min_gpu_offload_ratio
        ),
        unload_after_request=(
            provider_settings.ollama_creative_unload_after_request
        ),
        enabled=provider_settings.enable_ollama_creative_provider,
        base_url=provider_settings.ollama_creative_base_url,
        capabilities=capabilities,
        client=client,
    )


def configured_creative_provider(
    provider_settings: OpenAIProviderSettings | OllamaProviderSettings,
    *,
    api_key_getter: Callable[[], str | None],
    client: httpx.AsyncClient | None = None,
) -> CreativeModelProvider:
    """Select exactly one feature-gated real provider and declare its capabilities."""

    openai_enabled = bool(
        getattr(provider_settings, "enable_openai_creative_provider", False)
    )
    ollama_enabled = bool(
        getattr(provider_settings, "enable_ollama_creative_provider", False)
    )
    if openai_enabled and ollama_enabled:
        raise ValueError(
            "OpenAI and Ollama creative providers cannot be enabled simultaneously"
        )
    if ollama_enabled:
        capabilities = ProviderCapabilities(
            image_input=bool(provider_settings.ollama_creative_image_input),
            strict_structured_output=bool(
                provider_settings.ollama_creative_strict_structured_output
            ),
            maximum_context_tokens=int(
                provider_settings.ollama_creative_max_context_tokens
            ),
            maximum_images=int(provider_settings.ollama_creative_max_images),
            batch_requests=False,
            audio_input=False,
        )
        return configured_ollama_provider(
            provider_settings,
            capabilities=capabilities,
            client=client,
        )

    capabilities = ProviderCapabilities(
        image_input=bool(provider_settings.openai_creative_image_input),
        strict_structured_output=bool(
            provider_settings.openai_creative_strict_structured_output
        ),
        maximum_context_tokens=int(
            provider_settings.openai_creative_max_context_tokens
        ),
        maximum_images=int(provider_settings.openai_creative_max_images),
        batch_requests=False,
        audio_input=False,
    )
    return configured_openai_provider(
        provider_settings,
        capabilities=capabilities,
        api_key_getter=api_key_getter,
        client=client,
    )
