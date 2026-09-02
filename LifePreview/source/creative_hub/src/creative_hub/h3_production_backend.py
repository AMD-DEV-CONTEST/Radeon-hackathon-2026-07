"""Strict production dispatch boundary for H3 operation handlers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace

from .h3_atomic_runtime import (
    H3CoreDeferred,
    H3CoreOutput,
    H3_OPERATION_TYPES,
    implementation_manifest,
)


class H3ProductionBackendError(RuntimeError):
    """The configured H3 handler boundary violated its pinned contract."""


class H3ProductionBackend:
    """Bind one handler to the exact request and artifact gateway objects."""

    __slots__ = (
        "_artifact_gateway",
        "_handler",
        "_pinned_provider_identity",
        "_request",
    )

    def __init__(
        self,
        *,
        request: object,
        artifact_gateway: object,
        handler: object,
        pinned_provider_identity: str,
    ) -> None:
        run = getattr(handler, "run", None)
        if not callable(run):
            raise H3ProductionBackendError(
                "H3 production handler must implement run(request, gateway)"
            )
        self._request = request
        self._artifact_gateway = artifact_gateway
        self._handler = handler
        self._pinned_provider_identity = pinned_provider_identity

    def run(
        self,
        request: object,
        artifact_gateway: object,
        /,
    ) -> H3CoreOutput | H3CoreDeferred:
        if request is not self._request:
            raise H3ProductionBackendError(
                "H3 production backend request identity mismatch"
            )
        if artifact_gateway is not self._artifact_gateway:
            raise H3ProductionBackendError(
                "H3 production backend artifact gateway identity mismatch"
            )

        output = self._handler.run(request, artifact_gateway)
        if not isinstance(output, (H3CoreOutput, H3CoreDeferred)):
            raise H3ProductionBackendError(
                "H3 production handler did not return an H3 core result"
            )
        provider_identity = output.provider_identity
        if (
            provider_identity is not None
            and provider_identity != self._pinned_provider_identity
        ):
            raise H3ProductionBackendError(
                "H3 production handler provider identity mismatch"
            )
        if provider_identity is None:
            return replace(
                output,
                provider_identity=self._pinned_provider_identity,
            )
        return output


class H3ProductionBackendFactory:
    """Dispatch every registered H3 operation to an explicit handler factory."""

    __slots__ = ("_factories",)

    def __init__(
        self,
        factories: Mapping[str, Callable[..., object]],
        /,
    ) -> None:
        if not isinstance(factories, Mapping):
            raise H3ProductionBackendError(
                "H3 production factory set must be a mapping"
            )
        configured = dict(factories)
        expected = set(H3_OPERATION_TYPES)
        if set(configured) != expected or not all(
            callable(factory) for factory in configured.values()
        ):
            raise H3ProductionBackendError(
                "H3 production factory set must exactly match H3_OPERATION_TYPES"
            )
        self._factories = configured

    def __call__(
        self,
        *,
        request: object,
        artifact_gateway: object,
        credential_resolver: object | None,
    ) -> H3ProductionBackend:
        op_type = getattr(request, "op_type", None)
        if op_type not in H3_OPERATION_TYPES:
            raise H3ProductionBackendError(
                "H3 production backend request operation is not registered"
            )
        pinned_provider_identity = implementation_manifest(
            op_type
        ).provider_identity
        if not pinned_provider_identity:
            raise H3ProductionBackendError(
                "H3 production provider identity is not pinned"
            )
        handler = self._factories[op_type](
            request=request,
            artifact_gateway=artifact_gateway,
            credential_resolver=credential_resolver,
        )
        return H3ProductionBackend(
            request=request,
            artifact_gateway=artifact_gateway,
            handler=handler,
            pinned_provider_identity=pinned_provider_identity,
        )


__all__ = [
    "H3ProductionBackend",
    "H3ProductionBackendError",
    "H3ProductionBackendFactory",
]
