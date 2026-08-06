"""Read-only discovery and deterministic selection of AI runtime providers."""

from __future__ import annotations

import http.client
import json
import os
import re
import socket
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlsplit

from .provider_config import (
    AIRuntimeConfig,
    ProviderKind,
    ProviderSettings,
)

_READ_CHUNK_BYTES = 64 * 1024
_OLLAMA_DIGEST = re.compile(r"(?:sha256:)?([a-fA-F0-9]{64})")


class DiscoveryStatus(StrEnum):
    """Safe, user-facing result of one non-mutating provider probe."""

    AVAILABLE = "AVAILABLE"
    DISABLED = "DISABLED"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    CREDENTIAL_MISSING = "CREDENTIAL_MISSING"
    CREDENTIAL_REJECTED = "CREDENTIAL_REJECTED"
    MODEL_MISSING = "MODEL_MISSING"
    MODEL_DIGEST_MISMATCH = "MODEL_DIGEST_MISMATCH"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID_RESPONSE = "INVALID_RESPONSE"


@dataclass(frozen=True, slots=True)
class ProviderDiscoveryResult:
    """One provider probe result without credentials or response contents."""

    kind: ProviderKind
    status: DiscoveryStatus
    configured_model: str = ""
    available_models: tuple[str, ...] = ()
    endpoint: str = ""
    detail: str = ""
    configured_model_digest: str | None = None
    discovered_model_digest: str | None = None

    @property
    def available(self) -> bool:
        return self.status is DiscoveryStatus.AVAILABLE


class DiscoveryTransport(Protocol):
    """Small injectable read-only HTTP boundary used by discovery tests."""

    def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> Any:
        """GET one bounded JSON document without following redirects."""


class StandardLibraryDiscoveryTransport:
    """Bounded HTTP(S) GET transport with deliberately generic failures."""

    def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> Any:
        parsed = urlsplit(url)
        connection_type = (
            http.client.HTTPSConnection
            if parsed.scheme == "https"
            else http.client.HTTPConnection
        )
        connection = connection_type(
            parsed.hostname,
            parsed.port,
            timeout=timeout_seconds,
        )
        path = parsed.path or "/"
        try:
            connection.request("GET", path, headers=dict(headers))
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                raise DiscoveryHTTPError(response.status)
            declared = response.getheader("Content-Length")
            if declared is not None:
                try:
                    if int(declared) > max_response_bytes:
                        raise ValueError("provider response is too large")
                except ValueError as exc:
                    if str(exc) == "provider response is too large":
                        raise
            chunks: list[bytes] = []
            received = 0
            while True:
                chunk = response.read(
                    min(
                        _READ_CHUNK_BYTES,
                        max_response_bytes - received + 1,
                    )
                )
                if not chunk:
                    break
                chunks.append(chunk)
                received += len(chunk)
                if received > max_response_bytes:
                    raise ValueError("provider response is too large")
            return json.loads(b"".join(chunks).decode("utf-8"))
        finally:
            connection.close()


class DiscoveryHTTPError(OSError):
    """HTTP failure whose body is deliberately discarded."""

    def __init__(self, status: int):
        super().__init__("provider health request failed")
        self.status = status


class ProviderDiscovery:
    """Discover configured providers without installation or mutation."""

    def __init__(
        self,
        *,
        transport: DiscoveryTransport | None = None,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: float = 2.0,
        max_response_bytes: int = 262_144,
    ):
        if not 0 < float(timeout_seconds) <= 30:
            raise ValueError("discovery timeout must be between 0 and 30 seconds")
        if not 1_024 <= max_response_bytes <= 4 * 1024 * 1024:
            raise ValueError(
                "discovery response limit must be between 1024 and 4194304"
            )
        self._transport = transport or StandardLibraryDiscoveryTransport()
        self._environment = os.environ if environment is None else environment
        self.timeout_seconds = float(timeout_seconds)
        self.max_response_bytes = max_response_bytes

    def discover(
        self,
        config: AIRuntimeConfig,
    ) -> tuple[ProviderDiscoveryResult, ...]:
        """Probe every configured provider in stable identity order."""

        return tuple(self.probe(settings) for settings in config.providers)

    def probe(self, settings: ProviderSettings) -> ProviderDiscoveryResult:
        if not settings.enabled:
            return self._result(
                settings,
                DiscoveryStatus.DISABLED,
                "Provider is disabled.",
            )
        if settings.kind is ProviderKind.FAKE:
            return self._result(
                settings,
                DiscoveryStatus.AVAILABLE,
                "Offline synthetic provider is available.",
            )
        if not settings.endpoint:
            return self._result(
                settings,
                DiscoveryStatus.NOT_CONFIGURED,
                "An endpoint is required.",
            )
        headers = {"Accept": "application/json"}
        if settings.api_key_env:
            api_key = self._environment.get(settings.api_key_env)
            if not api_key:
                return self._result(
                    settings,
                    DiscoveryStatus.CREDENTIAL_MISSING,
                    "Configured credential environment variable is absent.",
                )
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            discovered_model_digest: str | None = None
            if settings.kind is ProviderKind.OLLAMA:
                payload = self._transport.get_json(
                    self._join_url(settings.endpoint, "/api/tags"),
                    headers=headers,
                    timeout_seconds=self.timeout_seconds,
                    max_response_bytes=self.max_response_bytes,
                )
                models, model_digests = self._ollama_models(payload)
                discovered_model_digest = model_digests.get(settings.model)
            else:
                payload = self._transport.get_json(
                    self._join_url(settings.endpoint, "/models"),
                    headers=headers,
                    timeout_seconds=self.timeout_seconds,
                    max_response_bytes=self.max_response_bytes,
                )
                models = self._openai_models(payload)
        except DiscoveryHTTPError as exc:
            return self._result(
                settings,
                (
                    DiscoveryStatus.CREDENTIAL_REJECTED
                    if exc.status in {401, 403}
                    else DiscoveryStatus.UNAVAILABLE
                ),
                (
                    "Provider rejected the configured credential."
                    if exc.status in {401, 403}
                    else "Provider health endpoint returned an error."
                ),
            )
        except (
            ConnectionError,
            OSError,
            TimeoutError,
            socket.timeout,
            http.client.HTTPException,
        ):
            return self._result(
                settings,
                DiscoveryStatus.UNAVAILABLE,
                "Provider health endpoint was unavailable.",
            )
        except (
            TypeError,
            ValueError,
            KeyError,
            UnicodeError,
            json.JSONDecodeError,
            RecursionError,
        ):
            return self._result(
                settings,
                DiscoveryStatus.INVALID_RESPONSE,
                "Provider health response did not match the expected contract.",
            )
        if not settings.model:
            return ProviderDiscoveryResult(
                kind=settings.kind,
                status=DiscoveryStatus.NOT_CONFIGURED,
                available_models=models,
                endpoint=settings.endpoint,
                detail=(
                    "Provider responded, but an explicit model must be "
                    "configured before selection."
                ),
                configured_model_digest=settings.model_digest,
            )
        if settings.model not in models:
            return ProviderDiscoveryResult(
                kind=settings.kind,
                status=DiscoveryStatus.MODEL_MISSING,
                configured_model=settings.model,
                available_models=models,
                endpoint=settings.endpoint,
                detail="Configured model was not reported by the provider.",
                configured_model_digest=settings.model_digest,
            )
        if (
            settings.model_digest is not None
            and discovered_model_digest != settings.model_digest
        ):
            return ProviderDiscoveryResult(
                kind=settings.kind,
                status=DiscoveryStatus.MODEL_DIGEST_MISMATCH,
                configured_model=settings.model,
                available_models=models,
                endpoint=settings.endpoint,
                detail=(
                    "Configured model digest did not match provider metadata."
                ),
                configured_model_digest=settings.model_digest,
                discovered_model_digest=discovered_model_digest,
            )
        return ProviderDiscoveryResult(
            kind=settings.kind,
            status=DiscoveryStatus.AVAILABLE,
            configured_model=settings.model,
            available_models=models,
            endpoint=settings.endpoint,
            detail="Configured model is available.",
            configured_model_digest=settings.model_digest,
            discovered_model_digest=discovered_model_digest,
        )

    @staticmethod
    def _join_url(endpoint: str, suffix: str) -> str:
        parsed = urlsplit(endpoint)
        base_path = parsed.path.rstrip("/")
        if suffix == "/models" and base_path.endswith("/v1"):
            path = base_path + suffix
        elif suffix == "/api/tags":
            path = base_path + suffix
        else:
            path = base_path + suffix
        return f"{parsed.scheme}://{parsed.netloc}{path}"

    @staticmethod
    def _ollama_models(
        payload: object,
    ) -> tuple[tuple[str, ...], dict[str, str | None]]:
        if not isinstance(payload, Mapping):
            raise ValueError("invalid Ollama tags response")
        raw_models = payload.get("models")
        if not isinstance(raw_models, list):
            raise ValueError("invalid Ollama tags response")
        model_digests: dict[str, str | None] = {}
        for item in raw_models:
            if not isinstance(item, Mapping):
                raise ValueError("invalid Ollama model entry")
            identity = item.get("model", item.get("name"))
            if not isinstance(identity, str) or not identity:
                raise ValueError("invalid Ollama model identity")
            raw_digest = item.get("digest")
            digest = (
                None
                if raw_digest is None
                else ProviderDiscovery._normalize_ollama_digest(raw_digest)
            )
            if (
                identity in model_digests
                and model_digests[identity] != digest
            ):
                raise ValueError("conflicting Ollama model metadata")
            model_digests[identity] = digest
        return tuple(sorted(model_digests)), model_digests

    @staticmethod
    def _normalize_ollama_digest(value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("invalid Ollama model digest")
        matched = _OLLAMA_DIGEST.fullmatch(value)
        if matched is None:
            raise ValueError("invalid Ollama model digest")
        return matched.group(1).lower()

    @staticmethod
    def _openai_models(payload: object) -> tuple[str, ...]:
        if not isinstance(payload, Mapping):
            raise ValueError("invalid models response")
        raw_models = payload.get("data")
        if not isinstance(raw_models, list):
            raise ValueError("invalid models response")
        models: set[str] = set()
        for item in raw_models:
            if not isinstance(item, Mapping):
                raise ValueError("invalid model entry")
            identity = item.get("id")
            if not isinstance(identity, str) or not identity:
                raise ValueError("invalid model identity")
            models.add(identity)
        return tuple(sorted(models))

    @staticmethod
    def _result(
        settings: ProviderSettings,
        status: DiscoveryStatus,
        detail: str,
    ) -> ProviderDiscoveryResult:
        return ProviderDiscoveryResult(
            kind=settings.kind,
            status=status,
            configured_model=settings.model,
            endpoint=settings.endpoint,
            detail=detail,
            configured_model_digest=settings.model_digest,
        )


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    """Selection decision with an explicit, auditable source."""

    kind: ProviderKind
    source: str
    discovery: ProviderDiscoveryResult


class ProviderSelectionError(RuntimeError):
    """Raised when a requested/saved provider is not usable."""


class ProviderSelector:
    """Select exactly one provider without hidden fallback."""

    def select(
        self,
        config: AIRuntimeConfig,
        results: Sequence[ProviderDiscoveryResult],
        *,
        explicit: ProviderKind | str | None = None,
    ) -> ProviderSelection:
        by_kind = {result.kind: result for result in results}
        if explicit is not None:
            return self._required(by_kind, ProviderKind(explicit), "explicit")
        if config.selected is not None:
            return self._required(by_kind, config.selected, "saved")
        raise ProviderSelectionError(
            "Provider selection must be explicit or saved; discovery does not "
            "select a provider automatically."
        )

    @staticmethod
    def _required(
        by_kind: Mapping[ProviderKind, ProviderDiscoveryResult],
        kind: ProviderKind,
        source: str,
    ) -> ProviderSelection:
        result = by_kind.get(kind)
        if result is None:
            raise ProviderSelectionError(
                f"{source.capitalize()} provider has no discovery result."
            )
        if not result.available:
            raise ProviderSelectionError(
                f"{source.capitalize()} provider {kind.value} is "
                f"{result.status.value}; no fallback was attempted."
            )
        return ProviderSelection(kind=kind, source=source, discovery=result)
