"""OCR-domain contracts with no deployment-manager or engine dependency."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from ...exceptions import ValidationError


class OcrFailure(ValidationError):
    """A typed OCR provider/protocol failure that fails the whole import attempt."""


@dataclass(frozen=True, slots=True)
class OcrRuntimeDescriptor:
    """Durable-safe provenance of a realized OCR implementation."""

    generation_id: str
    runtime_id: str
    model_pack_id: str
    engine: str
    engine_version: str
    protocol: str
    manifest_digest: str

    def __post_init__(self) -> None:
        for value in (
            self.generation_id,
            self.runtime_id,
            self.model_pack_id,
            self.engine,
            self.engine_version,
            self.protocol,
            self.manifest_digest,
        ):
            if not isinstance(value, str) or not value or len(value) > 160:
                raise ValueError("OCR runtime descriptor is invalid.")
        if len(self.manifest_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.manifest_digest
        ):
            raise ValueError("OCR runtime descriptor is invalid.")

    def to_payload(self) -> dict[str, object]:
        return {
            "generation_id": self.generation_id,
            "runtime_id": self.runtime_id,
            "model_pack_id": self.model_pack_id,
            "engine": self.engine,
            "engine_version": self.engine_version,
            "protocol": self.protocol,
            "manifest_digest": self.manifest_digest,
        }


@dataclass(frozen=True, slots=True)
class OcrSpawnSpec:
    """Pickle-safe ordinary child configuration; live values never enter results."""

    kind: Literal["paddle", "kserve_v2"]
    runtime_descriptor: OcrRuntimeDescriptor | None = None
    endpoint: str | None = field(default=None, repr=False)
    bearer_token: str | None = field(default=None, repr=False)
    model_name: str | None = None
    timeout_seconds: int = 300
    request_limits: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.timeout_seconds, int) or isinstance(self.timeout_seconds, bool):
            raise ValueError("OCR spawn timeout is invalid.")
        if not 1 <= self.timeout_seconds <= 3_600:
            raise ValueError("OCR spawn timeout is invalid.")
        if self.kind == "paddle":
            if any(value is not None for value in (self.endpoint, self.bearer_token, self.model_name)):
                raise ValueError("Paddle OCR spawn spec contains unsupported live binding data.")
            return
        if not self.endpoint or not self.bearer_token or not self.model_name:
            raise ValueError("KServe OCR spawn spec requires a complete live binding.")
        if "\r" in self.bearer_token or "\n" in self.bearer_token:
            raise ValueError("KServe OCR spawn authentication is invalid.")
        if len(self.request_limits) > 32 or any(
            not isinstance(name, str) or not name or not isinstance(value, int) or isinstance(value, bool) or value < 1
            for name, value in self.request_limits
        ):
            raise ValueError("OCR spawn request limits are invalid.")


@runtime_checkable
class OcrSession(Protocol):
    @property
    def runtime_descriptor(self) -> object: ...

    def recognize(self, image_path, *, output_path, timeout: int = 300) -> dict[str, object]: ...


@runtime_checkable
class OcrService(Protocol):
    def is_ready(self) -> bool: ...

    def runtime_descriptor(self) -> object: ...

    def open_session(self, *, allowed_root, log_path) -> OcrSession: ...

    def recognize(self, image_path, *, output_path, timeout: int = 300) -> dict[str, object]: ...


@runtime_checkable
class OcrAttempt(Protocol):
    @property
    def spawn_spec(self) -> OcrSpawnSpec: ...

    def close(self) -> None: ...


@runtime_checkable
class OcrAttemptFactory(Protocol):
    def prepare(self) -> OcrAttempt: ...


def normalize_runtime_descriptor(value: object) -> OcrRuntimeDescriptor | None:
    """Convert a provider descriptor to the narrow durable-safe OCR shape."""

    descriptor = getattr(value, "runtime_descriptor", value)
    if callable(descriptor):
        descriptor = descriptor()
    if isinstance(descriptor, OcrRuntimeDescriptor):
        return descriptor
    to_payload = getattr(descriptor, "to_payload", None)
    if callable(to_payload):
        descriptor = to_payload()
    if not isinstance(descriptor, dict):
        return None
    protocol = descriptor.get("protocol")
    if protocol is None:
        protocol = descriptor.get("protocol_version")
    manifest_digest = descriptor.get("manifest_digest")
    if manifest_digest is None:
        manifest_digest = descriptor.get("manifest_sha256")
    try:
        return OcrRuntimeDescriptor(
            generation_id=str(descriptor["generation_id"]),
            runtime_id=str(descriptor["runtime_id"]),
            model_pack_id=str(descriptor["model_pack_id"]),
            engine=str(descriptor["engine"]),
            engine_version=str(descriptor["engine_version"]),
            protocol=str(protocol),
            manifest_digest=str(manifest_digest),
        )
    except KeyError, TypeError, ValueError:
        return None


def ensure_ocr_failure(error: BaseException, *, default_code: str) -> OcrFailure:
    """Preserve a bounded typed failure without leaking provider response details."""

    if isinstance(error, OcrFailure):
        return error
    if isinstance(error, ValidationError) and error.error_code:
        return OcrFailure(
            "OCR provider failed.",
            error_code=error.error_code,
            retryable=error.retryable,
        )
    return OcrFailure("OCR provider failed.", error_code=default_code)


__all__ = [
    "OcrAttempt",
    "OcrAttemptFactory",
    "OcrFailure",
    "OcrRuntimeDescriptor",
    "OcrService",
    "OcrSession",
    "OcrSpawnSpec",
    "ensure_ocr_failure",
    "normalize_runtime_descriptor",
]
