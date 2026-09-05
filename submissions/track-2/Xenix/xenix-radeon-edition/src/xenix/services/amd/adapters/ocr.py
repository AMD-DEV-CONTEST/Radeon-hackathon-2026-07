"""AMD-managed OCR attempt composition.

This adapter is the only bridge between an OCR-owned managed provider reference
and the private AMD runtime directory.  The spawned worker receives an ordinary
``OcrSpawnSpec`` and never imports this module.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from ...ocr.contracts import OcrAttempt, OcrFailure, OcrRuntimeDescriptor, OcrSpawnSpec
from ...ocr.settings import ManagedOcrProviderRef, OcrProviderProjection
from ..placement import AmdRuntimeKey
from ..runtime import (
    AmdRuntimeDirectory,
    AmdRuntimeError,
    AmdRuntimeRetiringError,
    AmdRuntimeScope,
    AmdRuntimeUnavailableError,
)

OcrRuntimeDescriptorResolver = Callable[
    [ManagedOcrProviderRef, OcrProviderProjection],
    OcrRuntimeDescriptor,
]


class AmdOcrAdapterError(OcrFailure):
    """Base typed failure for the AMD OCR composition edge."""


class AmdOcrProviderUnavailableError(AmdOcrAdapterError):
    """The exact managed generation has no usable runtime binding."""

    def __init__(self) -> None:
        super().__init__(
            "OCR provider is unavailable.",
            error_code="ocr_provider_unavailable",
        )


class AmdOcrProviderRetiringError(AmdOcrAdapterError):
    """The selected exact generation no longer admits new OCR attempts."""

    def __init__(self) -> None:
        super().__init__(
            "OCR provider is retiring.",
            error_code="ocr_provider_retiring",
        )


class AmdOcrDescriptorMismatchError(AmdOcrAdapterError):
    """The selected projection does not describe the exact bound generation."""

    def __init__(self) -> None:
        super().__init__(
            "OCR provider descriptor does not match the selected generation.",
            error_code="ocr_provider_descriptor_mismatch",
        )


class AmdOcrAttempt(OcrAttempt):
    """Parent-owned attempt retaining one exact generation permit until settle."""

    __slots__ = ("_close_lock", "_closed", "_scope", "_spawn_spec")

    def __init__(self, *, scope: AmdRuntimeScope, spawn_spec: OcrSpawnSpec) -> None:
        self._scope = scope
        self._spawn_spec = spawn_spec
        self._close_lock = threading.Lock()
        self._closed = False

    def __repr__(self) -> str:
        return f"{type(self).__name__}(closed={self.closed!r})"

    @property
    def spawn_spec(self) -> OcrSpawnSpec:
        return self._spawn_spec

    @property
    def closed(self) -> bool:
        with self._close_lock:
            return self._closed

    def close(self) -> None:
        """Release the generation permit once across competing settle paths."""

        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self._scope.close()


class AmdOcrAdapter:
    """Resolve one exact managed OCR projection into a parent-owned attempt.

    ``descriptor_resolver`` is deliberately supplied by composition.  Live
    runtime bindings cannot truthfully provide durable engine/model provenance,
    while the OCR capability requires that provenance in its ordinary spawn
    specification.
    """

    def __init__(
        self,
        runtime_directory: AmdRuntimeDirectory,
        descriptor_resolver: OcrRuntimeDescriptorResolver,
        *,
        timeout_seconds: int = 300,
        request_limits: tuple[tuple[str, int], ...] = (),
    ) -> None:
        if not isinstance(runtime_directory, AmdRuntimeDirectory):
            raise TypeError("AMD OCR adapter requires an AMD runtime directory.")
        if not callable(descriptor_resolver):
            raise TypeError("AMD OCR adapter requires an OCR descriptor resolver.")
        # Reuse the ordinary spawn contract as the single authority for the
        # bounded timeout/limits shape without acquiring a runtime permit.
        _validate_spawn_policy(timeout_seconds, request_limits)
        self._runtime_directory = runtime_directory
        self._descriptor_resolver = descriptor_resolver
        self._timeout_seconds = timeout_seconds
        self._request_limits = tuple(request_limits)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    def __call__(
        self,
        reference: ManagedOcrProviderRef,
        projection: OcrProviderProjection,
    ) -> OcrAttempt:
        return self.prepare(reference, projection)

    def prepare(
        self,
        reference: ManagedOcrProviderRef,
        projection: OcrProviderProjection,
    ) -> AmdOcrAttempt:
        """Acquire one permit and freeze one ordinary KServe child spec."""

        self._validate_projection(reference, projection)
        descriptor = self._resolve_descriptor(reference, projection)
        key = AmdRuntimeKey(
            installation_id=reference.installation_id,
            component_generation_id=reference.component_generation_id,
        )
        try:
            scope = self._runtime_directory.acquire(key)
        except AmdRuntimeRetiringError as exc:
            raise AmdOcrProviderRetiringError() from exc
        except AmdRuntimeUnavailableError as exc:
            raise AmdOcrProviderUnavailableError() from exc
        except AmdRuntimeError as exc:
            raise AmdOcrProviderUnavailableError() from exc

        try:
            spawn_spec = OcrSpawnSpec(
                kind="kserve_v2",
                runtime_descriptor=descriptor,
                endpoint=scope.binding.base_url,
                bearer_token=scope.binding.bearer_token,
                model_name=projection.model,
                timeout_seconds=self._timeout_seconds,
                request_limits=self._request_limits,
            )
        except Exception:
            scope.close()
            raise
        return AmdOcrAttempt(scope=scope, spawn_spec=spawn_spec)

    @staticmethod
    def _validate_projection(
        reference: ManagedOcrProviderRef,
        projection: OcrProviderProjection,
    ) -> None:
        if projection.target != reference:
            raise AmdOcrDescriptorMismatchError()
        if bool(getattr(projection, "retiring", False)):
            raise AmdOcrProviderRetiringError()

    def _resolve_descriptor(
        self,
        reference: ManagedOcrProviderRef,
        projection: OcrProviderProjection,
    ) -> OcrRuntimeDescriptor:
        try:
            descriptor = self._descriptor_resolver(reference, projection)
        except AmdOcrAdapterError:
            raise
        except Exception:
            raise AmdOcrDescriptorMismatchError() from None
        if (
            not isinstance(descriptor, OcrRuntimeDescriptor)
            or descriptor.generation_id != reference.component_generation_id
            or descriptor.model_pack_id != projection.model
            or descriptor.manifest_digest != projection.descriptor_fingerprint
        ):
            raise AmdOcrDescriptorMismatchError()
        return descriptor


def _validate_spawn_policy(
    timeout_seconds: int,
    request_limits: tuple[tuple[str, int], ...],
) -> None:
    try:
        OcrSpawnSpec(
            kind="kserve_v2",
            runtime_descriptor=OcrRuntimeDescriptor(
                generation_id="validation",
                runtime_id="validation",
                model_pack_id="validation",
                engine="validation",
                engine_version="validation",
                protocol="validation",
                manifest_digest="0" * 64,
            ),
            endpoint="http://127.0.0.1:1",
            bearer_token="x" * 24,
            model_name="validation",
            timeout_seconds=timeout_seconds,
            request_limits=tuple(request_limits),
        )
    except ValueError as exc:
        raise ValueError("AMD OCR spawn policy is invalid.") from exc


# Both names describe the registry role; keep the longer spelling available to
# make explicit composition readable without adding another implementation.
AmdOcrProviderFactory = AmdOcrAdapter
AmdOcrAttemptFactory = AmdOcrAdapter


__all__ = [
    "AmdOcrAdapter",
    "AmdOcrAdapterError",
    "AmdOcrAttempt",
    "AmdOcrAttemptFactory",
    "AmdOcrDescriptorMismatchError",
    "AmdOcrProviderFactory",
    "AmdOcrProviderRetiringError",
    "AmdOcrProviderUnavailableError",
    "OcrRuntimeDescriptorResolver",
]
