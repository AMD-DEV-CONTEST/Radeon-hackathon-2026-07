from __future__ import annotations

import hashlib
import ipaddress
import math
import re
from typing import Literal, Protocol
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .mcp_transport import MCPResult, MCPTransport, MCPTransportError


CODING_PLAN_SEARCH_TOOL_NAME = "coding_plan.search"
CODING_PLAN_SEARCH_SCHEMA_DIGEST = (
    "6f5b772b2612821f6290ec65f784bc6b8fd9ce6fd3e6c80164cbb5eca2c54c8f"
)
CODING_PLAN_READER_TOOL_NAME = "coding_plan.read_page"
CODING_PLAN_READER_SCHEMA_DIGEST = (
    "e498bbc04216f04c3c991ed99dbd14eb16a161d4f33c3d97ff34cf943f313e13"
)
QWEN_TTS_TOOL_NAME = "qwen_tts.custom_voice"
QWEN_TTS_SCHEMA_DIGEST = (
    "99334726611ccf58a148b0814696bfa6fe08c1b2d027e946beccf5a74331c9aa"
)
QWEN_TTS_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
DEFAULT_TTS_SPEAKERS = frozenset({"Serena", "Uncle_Fu"})
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ProviderContractError(RuntimeError):
    """A fail-closed provider contract mismatch safe for callers to surface."""


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _validate_http_url(value: str) -> str:
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.netloc
        or parts.username is not None
        or parts.password is not None
    ):
        raise ValueError("must be an HTTP(S) URL without embedded credentials")
    return value


class SearchRequest(FrozenModel):
    query: str = Field(min_length=1, max_length=70)
    max_results: int = Field(default=10, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value


class SearchHit(FrozenModel):
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2048)
    snippet: str = Field(default="", max_length=5_000)

    _valid_url = field_validator("url")(_validate_http_url)


class ReaderSecurityCapabilities(FrozenModel):
    address_binding: Literal["caller-pinned-ip-v1"]
    redirect_handling: Literal["forbidden"]
    prefetch_validation: Literal["required"]

    @classmethod
    def secure_default(cls) -> ReaderSecurityCapabilities:
        return cls(
            address_binding="caller-pinned-ip-v1",
            redirect_handling="forbidden",
            prefetch_validation="required",
        )


def _validate_ip_address(value: str) -> str:
    try:
        return ipaddress.ip_address(value).compressed
    except ValueError as error:
        raise ValueError("must be an IP address") from error


class ReadPageRequest(FrozenModel):
    url: str = Field(min_length=1, max_length=2048)
    approved_resolved_addresses: tuple[str, ...] = Field(
        min_length=1, max_length=16
    )
    redirect_policy: Literal["forbid"]
    prefetch_policy: Literal["connect-approved-address-only"]

    _valid_url = field_validator("url")(_validate_http_url)

    @field_validator("approved_resolved_addresses")
    @classmethod
    def approved_addresses_are_valid_and_unique(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        addresses = tuple(_validate_ip_address(item) for item in value)
        if len(set(addresses)) != len(addresses):
            raise ValueError("approved addresses must be unique")
        return addresses


class ReaderSecurityAttestation(FrozenModel):
    resolved_address: str
    redirect_chain: tuple[str, ...] = Field(min_length=1, max_length=8)
    redirect_policy: Literal["forbid"]
    prefetch_policy: Literal["connect-approved-address-only"]

    _valid_address = field_validator("resolved_address")(_validate_ip_address)

    @field_validator("redirect_chain")
    @classmethod
    def redirect_urls_are_valid(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_validate_http_url(item) for item in value)


class SourceDocumentPayload(FrozenModel):
    url: str = Field(min_length=1, max_length=2048)
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=1_000_000)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_type: Literal["text/plain", "text/markdown"]
    security: ReaderSecurityAttestation

    _valid_url = field_validator("url")(_validate_http_url)

    @model_validator(mode="after")
    def content_digest_matches_content(self) -> SourceDocumentPayload:
        actual = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        if self.content_digest != actual:
            raise ValueError("content_digest does not match content")
        return self


class TTSServiceCapabilities(FrozenModel):
    service_version: str = Field(min_length=1, max_length=100)
    model_id: Literal["Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"]
    tool_name: str = Field(min_length=1, max_length=200)
    schema_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    speakers: tuple[str, ...] = Field(min_length=1, max_length=100)

    @field_validator("speakers")
    @classmethod
    def speakers_are_unique_and_named(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not speaker.strip() for speaker in value):
            raise ValueError("speaker names must not be blank")
        if len(set(value)) != len(value):
            raise ValueError("speaker names must be unique")
        return value


class _SearchPayload(FrozenModel):
    hits: tuple[SearchHit, ...] = Field(max_length=20)


class SearchProvider(Protocol):
    def search(self, request: SearchRequest) -> tuple[SearchHit, ...]: ...


class PageReaderProvider(Protocol):
    @property
    def security_capabilities(self) -> ReaderSecurityCapabilities: ...

    def read(self, request: ReadPageRequest) -> SourceDocumentPayload: ...


class TTSDiscoveryProvider(Protocol):
    def discover(self) -> TTSServiceCapabilities: ...


class _MCPProvider:
    def __init__(
        self,
        transport: MCPTransport,
        *,
        tool_name: str,
        expected_schema_digest: str,
        timeout_seconds: float,
    ) -> None:
        if not isinstance(tool_name, str) or not tool_name:
            raise ValueError("tool_name must not be empty")
        if _DIGEST_PATTERN.fullmatch(expected_schema_digest) is None:
            raise ValueError("expected_schema_digest must be a lowercase SHA-256 digest")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be positive and finite")
        self._transport = transport
        self._tool_name = tool_name
        self._expected_schema_digest = expected_schema_digest
        self._timeout_seconds = float(timeout_seconds)

    def _call(self, arguments: dict[str, object]) -> MCPResult:
        try:
            result = self._transport.call(
                self._tool_name,
                arguments,
                self._timeout_seconds,
            )
        except MCPTransportError as error:
            raise ProviderContractError("MCP provider is unavailable") from error
        except Exception as error:
            raise ProviderContractError("MCP provider call failed") from error
        if not isinstance(result, MCPResult):
            raise ProviderContractError("MCP provider returned an invalid result")
        if result.tool_name != self._tool_name:
            raise ProviderContractError("MCP tool contract mismatch")
        if result.schema_digest != self._expected_schema_digest:
            raise ProviderContractError("MCP schema contract mismatch")
        return result


class CodingPlanSearchMCPProvider(_MCPProvider):
    def __init__(
        self,
        transport: MCPTransport,
        *,
        tool_name: str = CODING_PLAN_SEARCH_TOOL_NAME,
        expected_schema_digest: str = CODING_PLAN_SEARCH_SCHEMA_DIGEST,
        timeout_seconds: float = 10.0,
    ) -> None:
        super().__init__(
            transport,
            tool_name=tool_name,
            expected_schema_digest=expected_schema_digest,
            timeout_seconds=timeout_seconds,
        )

    def search(self, request: SearchRequest) -> tuple[SearchHit, ...]:
        if not isinstance(request, SearchRequest):
            raise TypeError("request must be a SearchRequest")
        result = self._call(
            {"query": request.query, "max_results": request.max_results}
        )
        try:
            parsed = _SearchPayload.model_validate(dict(result.payload))
        except ValidationError as error:
            raise ProviderContractError("search payload contract is invalid") from error
        if len(parsed.hits) > request.max_results:
            raise ProviderContractError("search payload exceeded the requested result limit")
        return parsed.hits


class CodingPlanPageReaderMCPProvider(_MCPProvider):
    def __init__(
        self,
        transport: MCPTransport,
        *,
        tool_name: str = CODING_PLAN_READER_TOOL_NAME,
        expected_schema_digest: str = CODING_PLAN_READER_SCHEMA_DIGEST,
        timeout_seconds: float = 10.0,
    ) -> None:
        super().__init__(
            transport,
            tool_name=tool_name,
            expected_schema_digest=expected_schema_digest,
            timeout_seconds=timeout_seconds,
        )

    @property
    def security_capabilities(self) -> ReaderSecurityCapabilities:
        return ReaderSecurityCapabilities.secure_default()

    def read(self, request: ReadPageRequest) -> SourceDocumentPayload:
        if not isinstance(request, ReadPageRequest):
            raise TypeError("request must be a ReadPageRequest")
        result = self._call(
            {
                "url": request.url,
                "approved_resolved_addresses": request.approved_resolved_addresses,
                "redirect_policy": request.redirect_policy,
                "prefetch_policy": request.prefetch_policy,
            }
        )
        try:
            document = SourceDocumentPayload.model_validate(dict(result.payload))
        except ValidationError as error:
            raise ProviderContractError("reader payload contract is invalid") from error
        if document.url != request.url:
            raise ProviderContractError("reader payload URL contract mismatch")
        if (
            document.security.resolved_address
            not in request.approved_resolved_addresses
            or document.security.redirect_chain != (request.url,)
            or document.security.redirect_policy != request.redirect_policy
            or document.security.prefetch_policy != request.prefetch_policy
        ):
            raise ProviderContractError("reader security contract mismatch")
        return document


# Keep the shorter adapter name available for callers that describe this as the
# Coding Plan Reader rather than the page-reader operation.
CodingPlanReaderMCPProvider = CodingPlanPageReaderMCPProvider


class QwenTTSDiscoveryProvider(_MCPProvider):
    def __init__(
        self,
        transport: MCPTransport,
        *,
        tool_name: str = QWEN_TTS_TOOL_NAME,
        expected_schema_digest: str = QWEN_TTS_SCHEMA_DIGEST,
        timeout_seconds: float = 10.0,
    ) -> None:
        super().__init__(
            transport,
            tool_name=tool_name,
            expected_schema_digest=expected_schema_digest,
            timeout_seconds=timeout_seconds,
        )

    def discover(self) -> TTSServiceCapabilities:
        result = self._call({})
        try:
            capabilities = TTSServiceCapabilities.model_validate(dict(result.payload))
        except ValidationError as error:
            raise ProviderContractError("TTS discovery payload contract is invalid") from error
        if capabilities.tool_name != self._tool_name:
            raise ProviderContractError("TTS discovery tool contract mismatch")
        if capabilities.schema_digest != self._expected_schema_digest:
            raise ProviderContractError("TTS discovery schema contract mismatch")
        if not DEFAULT_TTS_SPEAKERS.issubset(capabilities.speakers):
            raise ProviderContractError("TTS discovery required speaker contract mismatch")
        return capabilities


__all__ = [
    "CODING_PLAN_READER_SCHEMA_DIGEST",
    "CODING_PLAN_READER_TOOL_NAME",
    "CODING_PLAN_SEARCH_SCHEMA_DIGEST",
    "CODING_PLAN_SEARCH_TOOL_NAME",
    "CodingPlanPageReaderMCPProvider",
    "CodingPlanReaderMCPProvider",
    "CodingPlanSearchMCPProvider",
    "DEFAULT_TTS_SPEAKERS",
    "FrozenModel",
    "PageReaderProvider",
    "ProviderContractError",
    "QWEN_TTS_MODEL_ID",
    "QWEN_TTS_SCHEMA_DIGEST",
    "QWEN_TTS_TOOL_NAME",
    "QwenTTSDiscoveryProvider",
    "ReadPageRequest",
    "ReaderSecurityAttestation",
    "ReaderSecurityCapabilities",
    "SearchHit",
    "SearchProvider",
    "SearchRequest",
    "SourceDocumentPayload",
    "TTSDiscoveryProvider",
    "TTSServiceCapabilities",
]
