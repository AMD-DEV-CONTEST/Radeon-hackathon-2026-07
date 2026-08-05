"""Live-model compatibility harness — fixture providers only.

Exercises the live-model interface using deterministic fixture
providers; no real model is ever invoked. The harness validates:

  * provider availability (boolean fixture)
  * timeout handling
  * malformed response handling (non-dict, non-JSON)
  * overlong response handling (size cap)
  * empty response handling
  * schema validation (required keys per schema_id)

Producers are subclasses of :class:`FixtureProvider`. Each one returns
either a dict-like payload or raises :class:`ProviderUnavailable` /
:class:`ProviderTimeout`. The harness emits a
:class:`LiveModelResponse`; the record is always marked
``trusted=False`` — downstream rungs apply trust gates.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .live_model_response_record import (
    LIVE_MODEL_RESPONSE_STATUS_TOKENS,
    LiveModelResponse,
    ResponseKind,
)

_MAX_RESPONSE_CHARS = 64_000  # 64 kB across encoded JSON
_REQUIRED_KEYS_BY_SCHEMA: dict[str, frozenset[str]] = {
    "diagnose_v1": frozenset({"summary"}),
    "patch_plan_v1": frozenset({"kind", "steps"}),
    "verifier_v1": frozenset({"status"}),
}


class ProviderUnavailable(RuntimeError):
    pass


class ProviderTimeout(RuntimeError):
    pass


class FixtureProvider:
    """Abstract fixture provider.

    Subclasses must implement :meth:`respond`. The harness times the
    call and applies the safety checks; the subclass focuses only on
    returning the canned payload.
    """

    name: str = "fixture"
    model_id: str = "fixture-model"
    available: bool = True
    timeout_ms: int = 5_000

    def respond(self, task_class: str, payload: dict[str, object]) -> object:
        raise NotImplementedError


@dataclass
class DeterministicProvider(FixtureProvider):
    name: str = "deterministic"
    model_id: str = "fixture-deterministic-v1"
    available: bool = True
    canned: dict[str, object] = field(default_factory=dict)

    def respond(self, task_class: str, payload: dict[str, object]) -> object:
        return dict(self.canned)


@dataclass
class TimeoutProvider(FixtureProvider):
    name: str = "timeout"
    model_id: str = "fixture-timeout-v1"
    available: bool = True
    timeout_ms: int = 1

    def respond(self, task_class: str, payload: dict[str, object]) -> object:
        raise ProviderTimeout("fixture provider timed out (simulated)")


@dataclass
class UnavailableProvider(FixtureProvider):
    name: str = "unavailable"
    model_id: str = "fixture-unavailable-v1"
    available: bool = False

    def respond(self, task_class: str, payload: dict[str, object]) -> object:
        raise ProviderUnavailable("fixture provider not available")


@dataclass
class MalformedProvider(FixtureProvider):
    name: str = "malformed"
    model_id: str = "fixture-malformed-v1"
    available: bool = True
    bad_value: object = "not a dict"

    def respond(self, task_class: str, payload: dict[str, object]) -> object:
        return self.bad_value


@dataclass
class OversizedProvider(FixtureProvider):
    name: str = "oversized"
    model_id: str = "fixture-oversized-v1"
    available: bool = True
    size: int = _MAX_RESPONSE_CHARS + 1_000

    def respond(self, task_class: str, payload: dict[str, object]) -> object:
        return {"summary": "x" * self.size}


@dataclass
class EmptyProvider(FixtureProvider):
    name: str = "empty"
    model_id: str = "fixture-empty-v1"
    available: bool = True

    def respond(self, task_class: str, payload: dict[str, object]) -> object:
        return {}


class LiveModelCompatHarness:
    """Exercises a fixture provider against the validation checks."""

    def __init__(self, max_response_chars: int = _MAX_RESPONSE_CHARS) -> None:
        self._max = max_response_chars

    def invoke(
        self,
        provider: FixtureProvider,
        *,
        task_class: str,
        schema_id: str,
        payload: dict[str, object] | None = None,
    ) -> LiveModelResponse:
        payload = payload or {}
        # 0. Availability.
        if not provider.available:
            return self._block(
                provider,
                task_class,
                schema_id,
                ResponseKind.PROVIDER_UNAVAILABLE,
                "provider.available is False",
            )

        # 1. Invoke with timing + exception classification.
        start = time.perf_counter()
        try:
            raw = provider.respond(task_class, payload)
        except ProviderTimeout as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return self._block(
                provider,
                task_class,
                schema_id,
                ResponseKind.TIMEOUT,
                str(exc),
                elapsed_ms=elapsed_ms,
            )
        except ProviderUnavailable as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return self._block(
                provider,
                task_class,
                schema_id,
                ResponseKind.PROVIDER_UNAVAILABLE,
                str(exc),
                elapsed_ms=elapsed_ms,
            )
        except Exception as exc:  # noqa: BLE001 — non-dict-emitting provider
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return self._block(
                provider,
                task_class,
                schema_id,
                ResponseKind.BAD_RESPONSE,
                f"{type(exc).__name__}: {exc}",
                elapsed_ms=elapsed_ms,
            )
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        # 2. Type check: must be a dict.
        if not isinstance(raw, dict):
            return self._block(
                provider,
                task_class,
                schema_id,
                ResponseKind.BAD_RESPONSE,
                f"provider returned {type(raw).__name__}, expected dict",
                elapsed_ms=elapsed_ms,
            )

        # 3. Encode and size check.
        try:
            import json as _json

            encoded = _json.dumps(raw, sort_keys=True)
        except (TypeError, ValueError) as exc:
            return self._block(
                provider,
                task_class,
                schema_id,
                ResponseKind.BAD_RESPONSE,
                f"json encode failed: {exc}",
                elapsed_ms=elapsed_ms,
            )
        response_chars = len(encoded)
        if response_chars > self._max:
            return self._block(
                provider,
                task_class,
                schema_id,
                ResponseKind.OVERSIZED,
                f"response {response_chars} > cap {self._max}",
                elapsed_ms=elapsed_ms,
                response_chars=response_chars,
            )

        # 4. Empty check.
        if not raw:
            return self._block(
                provider,
                task_class,
                schema_id,
                ResponseKind.EMPTY,
                "provider returned empty dict",
                elapsed_ms=elapsed_ms,
                response_chars=response_chars,
            )

        # 5. Schema validation.
        required = _REQUIRED_KEYS_BY_SCHEMA.get(schema_id, frozenset())
        if required:
            missing = sorted(required - set(raw.keys()))
            if missing:
                return self._block(
                    provider,
                    task_class,
                    schema_id,
                    ResponseKind.SCHEMA_INVALID,
                    f"missing required keys for schema {schema_id!r}: {missing}",
                    elapsed_ms=elapsed_ms,
                    response_chars=response_chars,
                )

        return LiveModelResponse(
            status=ResponseKind.OK.value,
            provider=provider.name,
            model_id=provider.model_id,
            task_class=task_class,
            elapsed_ms=elapsed_ms,
            response_chars=response_chars,
            schema_id=schema_id,
            payload=dict(raw),
            trusted=False,
            notes=("harness exercise — response is untrusted by default",),
        )

    @staticmethod
    def _block(
        provider: FixtureProvider,
        task_class: str,
        schema_id: str,
        kind: ResponseKind,
        reason: str,
        *,
        elapsed_ms: int = 0,
        response_chars: int = 0,
    ) -> LiveModelResponse:
        return LiveModelResponse(
            status=kind.value,
            provider=provider.name,
            model_id=provider.model_id,
            task_class=task_class,
            elapsed_ms=elapsed_ms,
            response_chars=response_chars,
            schema_id=schema_id,
            payload={},
            trusted=False,
            notes=(reason,),
        )


__all__ = [
    "LiveModelCompatHarness",
    "FixtureProvider",
    "DeterministicProvider",
    "TimeoutProvider",
    "UnavailableProvider",
    "MalformedProvider",
    "OversizedProvider",
    "EmptyProvider",
    "ProviderUnavailable",
    "ProviderTimeout",
    "LIVE_MODEL_RESPONSE_STATUS_TOKENS",
]
