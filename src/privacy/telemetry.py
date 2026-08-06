"""Inference telemetry for Bunker.

Routes every model inference (DSPy LM calls and the legacy ``ModelManager``
fallback chain) through the :class:`AuditLogger` and :class:`DataFlowMonitor`
so the privacy dashboard reports real local vs external traffic instead of
hardcoded assumptions.

Backend taxonomy (the only backend identifiers the system records):

- ``vllm``            — primary local vLLM server (localhost).
- ``ollama``          — local Ollama server (localhost).
- ``local_secondary`` — secondary local vLLM fallback server (localhost).
- ``radeon_api``      — Radeon Cloud API (external; data leaves the machine).
- ``failed``          — no backend produced a response.

``vllm``/``ollama``/``local_secondary`` are treated as fully local. The Radeon
Cloud API is treated as external (an AMD bonus tier only when explicitly
configured). A ``failed`` inference can never count toward the "100% local"
claim.
"""

from __future__ import annotations  # defer AuditLogger/DataFlowMonitor annotations (circular import)

import logging
import time
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from .audit_logger import AuditLogger
    from .data_flow_monitor import DataFlowMonitor

logger = logging.getLogger(__name__)

# Canonical backend identifiers.
BACKEND_VLLM = "vllm"
BACKEND_OLLAMA = "ollama"
BACKEND_LOCAL_SECONDARY = "local_secondary"
BACKEND_RADEON_API = "radeon_api"
BACKEND_FAILED = "failed"

# Backends that never send data off the machine.
LOCAL_BACKENDS = frozenset(
    {BACKEND_VLLM, BACKEND_OLLAMA, BACKEND_LOCAL_SECONDARY}
)
# Backends that send data off the machine.
EXTERNAL_BACKENDS = frozenset({BACKEND_RADEON_API})

# Estimated bytes per token when a backend does not report token usage.
_BYTES_PER_TOKEN = 4.0


def is_local_backend(backend: Optional[str]) -> bool:
    """Return True when the backend never sends data off the machine.

    ``failed`` is explicitly not local: when an inference fails we cannot
    prove nothing left the machine, so it must never feed a "100% local"
    claim. Unknown backends default to local to match the historical
    ``AuditLogger`` behaviour.
    """
    if not backend:
        return True
    normalized = str(backend).lower()
    if normalized == BACKEND_FAILED:
        return False
    return normalized in LOCAL_BACKENDS


def estimate_bytes(prompt_tokens: int = 0, completion_tokens: int = 0) -> int:
    """Rough byte estimate for a single inference (tokens -> chars)."""
    return int((prompt_tokens + completion_tokens) * _BYTES_PER_TOKEN)


class InferenceTelemetry:
    """Routes inference events to the AuditLogger and DataFlowMonitor.

    A module-level :data:`telemetry` singleton is configured by
    ``src.dspy_runtime.configure_telemetry`` at application startup; the DSPy
    LM wrapper and ``ModelManager`` both emit through it. When no sinks are
    configured the object is a safe no-op, so imports and unit tests never
    touch disk.
    """

    def __init__(self) -> None:
        self._audit_logger: Optional[AuditLogger] = None
        self._data_flow_monitor: Optional[DataFlowMonitor] = None
        self._backend: str = BACKEND_VLLM
        self._model_label: str = "bunker-lm"

    def configure(
        self,
        audit_logger: Optional[AuditLogger] = None,
        data_flow_monitor: Optional[DataFlowMonitor] = None,
        backend: Optional[str] = None,
        model_label: Optional[str] = None,
    ) -> None:
        """Attach (or detach) telemetry sinks and defaults.

        Only arguments that are not ``None`` are updated, so calling
        ``configure(audit_logger=...)`` keeps a previously configured backend.
        Pass ``backend=""`` or ``model_label=""`` to clear a default.
        """
        if audit_logger is not None:
            self._audit_logger = audit_logger
        if data_flow_monitor is not None:
            self._data_flow_monitor = data_flow_monitor
        if backend is not None:
            self._backend = backend
        if model_label is not None:
            self._model_label = model_label

    @property
    def backend(self) -> str:
        """The currently configured default backend."""
        return self._backend

    @property
    def enabled(self) -> bool:
        """True when at least one sink is attached."""
        return self._audit_logger is not None or self._data_flow_monitor is not None

    def reset(self) -> None:
        """Detach all sinks (used by tests and on shutdown)."""
        self._audit_logger = None
        self._data_flow_monitor = None

    def record_inference(
        self,
        model: Optional[str] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        backend: Optional[str] = None,
        latency_ms: float = 0.0,
        session_id: Optional[str] = None,
        error: Optional[Exception] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record one inference to every attached sink.

        Args:
            model: Model identifier used for the call.
            prompt_tokens: Prompt token count (0 when unknown).
            completion_tokens: Completion token count (0 when unknown).
            backend: Backend identifier; defaults to the configured backend.
            latency_ms: Wall-clock latency of the call in milliseconds.
            session_id: Optional session identifier for the audit log.
            error: Exception when the inference failed (backend becomes
                ``failed``).
            extra_metadata: Additional metadata merged into the flow event.
        """
        if not self.enabled:
            return

        effective_backend = backend
        if error is not None:
            effective_backend = BACKEND_FAILED
        if not effective_backend:
            effective_backend = self._backend or BACKEND_FAILED

        is_local = is_local_backend(effective_backend)
        tokens = estimate_bytes(prompt_tokens, completion_tokens)
        model_name = model or self._model_label

        if self._audit_logger is not None:
            try:
                self._audit_logger.log_inference(
                    model=model_name,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    backend=effective_backend,
                    session_id=session_id,
                    latency_ms=latency_ms,
                )
            except Exception as exc:  # telemetry must never break inference
                logger.warning("Failed to audit-log inference: %s", exc)

        if self._data_flow_monitor is not None:
            metadata: Dict[str, Any] = {
                "backend": effective_backend,
                "model": model_name,
                "outcome": "failed" if error is not None else "success",
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "latency_ms": latency_ms,
                **({"error": str(error)} if error is not None else {}),
            }
            if extra_metadata:
                metadata.update(extra_metadata)
            try:
                self._data_flow_monitor.record_event(
                    event_type="inference",
                    source=effective_backend,
                    destination="local" if is_local else "external",
                    bytes_count=tokens,
                    is_local=is_local,
                    metadata=metadata,
                )
            except Exception as exc:  # telemetry must never break inference
                logger.warning("Failed to record data flow inference: %s", exc)


telemetry = InferenceTelemetry()
