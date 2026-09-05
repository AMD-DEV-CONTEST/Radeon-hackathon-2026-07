from __future__ import annotations

import json
import os
import hashlib
import sys
import threading
from collections.abc import Collection
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from opentelemetry import metrics, propagate, trace
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from .build_info import APP_VERSION, BUILD_COMMIT
from .config import AppPaths
from .release_config import apply_frozen_otel_environment

INSTALL_ID_FILE_NAME = "telemetry.json"
SERVICE_NAME = "xenix-native"
LLM_USAGE_JOURNAL_FILE_NAME = "llm-usage.jsonl"
LLM_USAGE_JOURNAL_MAX_BYTES = 1_000_000
LLM_USAGE_JOURNAL_BACKUP_COUNT = 3
MAX_LLM_TOKEN_COUNT = 1_000_000_000
LLM_USAGE_OPERATIONS = frozenset({"primary", "thread_title"})
_LLM_USAGE_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")

_configured = False
_logging_instrumented = False
_tracer_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None
_counters: dict[str, Any] = {}
_histograms: dict[str, Any] = {}


@dataclass(frozen=True)
class ObservabilityContext:
    install_id: str
    otlp_enabled: bool
    trace_export_enabled: bool
    metric_export_enabled: bool
    log_export_enabled: bool


@dataclass(frozen=True)
class LLMTokenUsage:
    """Safe normalized provider token counts; never carries provider wire data."""

    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    total_tokens: int

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> LLMTokenUsage | None:
        if not isinstance(payload, dict):
            return None
        parsed: dict[str, int] = {}
        for field in _LLM_USAGE_FIELDS:
            if field not in payload:
                continue
            count = _usage_count(payload[field])
            if count is None:
                # A present but malformed provider field makes the complete
                # observation unknown; never silently turn it into zero.
                return None
            parsed[field] = count
        if not parsed:
            return None
        normalized_input = parsed.get("input_tokens", 0)
        normalized_output = parsed.get("output_tokens", 0)
        normalized_total = parsed.get("total_tokens", normalized_input + normalized_output)
        if normalized_total > MAX_LLM_TOKEN_COUNT:
            return None
        return cls(
            input_tokens=normalized_input,
            cached_input_tokens=parsed.get("cached_input_tokens", 0),
            output_tokens=normalized_output,
            total_tokens=normalized_total,
        )

    def to_payload(self, *, request_count: int = 1) -> dict[str, int]:
        return {
            "request_count": request_count,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class LLMUsageObservation:
    """One provider response observed outside canonical conversation state."""

    operation: str
    usage: LLMTokenUsage
    thread_id: str | None = None
    root_user_message_id: str | None = None
    frontier_message_id: str | None = None
    pending_message_id: str | None = None
    fq_model_key: str | None = None
    observed_at: datetime | None = None


@dataclass(frozen=True)
class LLMUsageAggregate:
    request_count: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def add(self, usage: LLMTokenUsage) -> LLMUsageAggregate:
        return LLMUsageAggregate(
            request_count=self.request_count + 1,
            input_tokens=self.input_tokens + usage.input_tokens,
            cached_input_tokens=self.cached_input_tokens + usage.cached_input_tokens,
            output_tokens=self.output_tokens + usage.output_tokens,
            total_tokens=self.total_tokens + usage.total_tokens,
        )

    def to_payload(self) -> dict[str, int]:
        return {
            "request_count": self.request_count,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


class LLMUsageObservability(Protocol):
    """Cross-cutting write/read port; it is never Conversation authority."""

    def record_llm_usage(self, observation: LLMUsageObservation) -> None: ...

    def query_primary_usage(
        self,
        *,
        thread_id: str,
        root_user_message_ids: Collection[str],
    ) -> dict[str, LLMUsageAggregate]: ...


class NullLLMUsageObservability:
    """Safe default for narrow tests and compositions without observability."""

    def record_llm_usage(self, observation: LLMUsageObservation) -> None:
        del observation

    def query_primary_usage(
        self,
        *,
        thread_id: str,
        root_user_message_ids: Collection[str],
    ) -> dict[str, LLMUsageAggregate]:
        del thread_id, root_user_message_ids
        return {}


class LocalLLMUsageObservability:
    """Bounded local journal for safe LLM token observations.

    The journal stores only normalized counts and hashed correlation keys.  It
    is an observability read model, not a conversation/execution table: a
    missing, malformed, rotated, or unwritable journal simply yields less UI
    telemetry and never affects a canonical Message operation.
    """

    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int = LLM_USAGE_JOURNAL_MAX_BYTES,
        backup_count: int = LLM_USAGE_JOURNAL_BACKUP_COUNT,
    ) -> None:
        self._path = path
        self._max_bytes = max(1, max_bytes)
        self._backup_count = max(0, backup_count)
        self._lock = threading.RLock()

    def record_llm_usage(self, observation: LLMUsageObservation) -> None:
        if not _is_valid_usage_observation(observation):
            return
        try:
            record = self._record_payload(observation)
            encoded = (json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
            with self._lock:
                self._append_locked(encoded)
            self._record_usage_metrics(observation)
        except Exception:
            # Observability is intentionally best effort.  Do not log the
            # observation itself: its safe journal fields are enough evidence
            # when persistence succeeds, and a failed logger could recurse.
            return

    def query_primary_usage(
        self,
        *,
        thread_id: str,
        root_user_message_ids: Collection[str],
    ) -> dict[str, LLMUsageAggregate]:
        requested = {
            stable_hash(message_id): message_id
            for message_id in root_user_message_ids
            if isinstance(message_id, str) and message_id
        }
        if not requested:
            return {}
        thread_key = stable_hash(thread_id)
        aggregates: dict[str, LLMUsageAggregate] = {}
        observed_sampling_keys: set[str] = set()
        try:
            with self._lock:
                records = list(self._iter_records_locked())
        except Exception:
            return {}
        for record in records:
            if record.get("kind") != "llm_token_usage" or record.get("operation") != "primary":
                continue
            if record.get("thread_key") != thread_key:
                continue
            root_key = record.get("root_user_key")
            if not isinstance(root_key, str) or root_key not in requested:
                continue
            sampling_key = record.get("sampling_key")
            if not isinstance(sampling_key, str) or not sampling_key or sampling_key in observed_sampling_keys:
                continue
            usage = _usage_from_record(record)
            if usage is None:
                continue
            observed_sampling_keys.add(sampling_key)
            message_id = requested[root_key]
            aggregates[message_id] = aggregates.get(message_id, LLMUsageAggregate()).add(usage)
        return aggregates

    def _record_payload(self, observation: LLMUsageObservation) -> dict[str, Any]:
        if not _is_valid_usage_observation(observation):
            raise ValueError("Invalid LLM usage observation.")
        observed_at = observation.observed_at or datetime.now(timezone.utc)
        return {
            "kind": "llm_token_usage",
            "version": 1,
            "observed_at": observed_at.isoformat(),
            "operation": observation.operation,
            "thread_key": _stable_key(observation.thread_id),
            "root_user_key": _stable_key(observation.root_user_message_id),
            "frontier_key": _stable_key(observation.frontier_message_id),
            "sampling_key": _stable_key(observation.pending_message_id),
            "model_key": _stable_key(observation.fq_model_key),
            **observation.usage.to_payload(),
        }

    def _append_locked(self, encoded: bytes) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists() and self._path.stat().st_size + len(encoded) > self._max_bytes:
            self._roll_over_locked()
        with self._path.open("ab") as handle:
            handle.write(encoded)
            handle.flush()

    def _roll_over_locked(self) -> None:
        if self._backup_count <= 0:
            self._path.unlink(missing_ok=True)
            return
        oldest = self._rotated_path(self._backup_count)
        oldest.unlink(missing_ok=True)
        for index in range(self._backup_count - 1, 0, -1):
            source = self._rotated_path(index)
            if source.exists():
                source.replace(self._rotated_path(index + 1))
        if self._path.exists():
            self._path.replace(self._rotated_path(1))

    def _iter_records_locked(self):
        paths = [self._path, *(self._rotated_path(index) for index in range(1, self._backup_count + 1))]
        for path in paths:
            if not path.exists():
                continue
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(record, dict):
                            yield record
            except OSError:
                continue

    def _rotated_path(self, index: int) -> Path:
        return self._path.with_name(f"{self._path.name}.{index}")

    @staticmethod
    def _record_usage_metrics(observation: LLMUsageObservation) -> None:
        attributes: dict[str, Any] = {
            "gen_ai.operation.name": "chat" if observation.operation == "primary" else observation.operation,
            "xenix.ai.usage.operation": observation.operation,
        }
        if observation.fq_model_key:
            attributes["xenix.ai.model.hash"] = stable_hash(observation.fq_model_key)
        record_counter("xenix.llm.usage.request.count", attributes=attributes)
        for token_type, count in (
            ("input", observation.usage.input_tokens),
            ("cached_input", observation.usage.cached_input_tokens),
            ("output", observation.usage.output_tokens),
            ("total", observation.usage.total_tokens),
        ):
            if count:
                record_histogram(
                    "gen_ai.client.token.usage",
                    count,
                    attributes={**attributes, "gen_ai.token.type": token_type},
                    unit="{token}",
                )


def load_or_create_install_id(paths: AppPaths) -> str:
    path = paths.config / INSTALL_ID_FILE_NAME
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        install_id = payload.get("install_id")
        if isinstance(install_id, str) and install_id.strip():
            return install_id.strip()

    install_id = uuid4().hex
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"install_id": install_id}, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    return install_id


def setup_observability(paths: AppPaths) -> ObservabilityContext:
    global _configured, _logging_instrumented, _meter_provider, _tracer_provider

    apply_frozen_otel_environment()
    install_id = load_or_create_install_id(paths)
    trace_export_enabled = _trace_export_enabled()
    metric_export_enabled = _metric_export_enabled()
    log_export_enabled = _log_export_enabled()
    otlp_enabled = trace_export_enabled or metric_export_enabled or log_export_enabled

    if _configured or _env_truthy("OTEL_SDK_DISABLED", default=False):
        if not _logging_instrumented:
            LoggingInstrumentor().instrument(set_logging_format=True)
            _logging_instrumented = True
        return ObservabilityContext(
            install_id=install_id,
            otlp_enabled=otlp_enabled,
            trace_export_enabled=trace_export_enabled,
            metric_export_enabled=metric_export_enabled,
            log_export_enabled=log_export_enabled,
        )

    resource = Resource.create(_resource_attributes(paths, install_id))

    tracer_provider = TracerProvider(resource=resource)
    if trace_export_enabled:
        tracer_provider.add_span_processor(BatchSpanProcessor(_build_span_exporter()))
    trace.set_tracer_provider(tracer_provider)
    _tracer_provider = tracer_provider

    metric_readers = []
    if metric_export_enabled:
        metric_readers.append(PeriodicExportingMetricReader(_build_metric_exporter()))
    meter_provider = MeterProvider(resource=resource, metric_readers=metric_readers)
    metrics.set_meter_provider(meter_provider)
    _meter_provider = meter_provider

    if log_export_enabled:
        _setup_otlp_log_export(resource)

    if not _logging_instrumented:
        LoggingInstrumentor().instrument(set_logging_format=True)
        _logging_instrumented = True

    _configured = True
    return ObservabilityContext(
        install_id=install_id,
        otlp_enabled=otlp_enabled,
        trace_export_enabled=trace_export_enabled,
        metric_export_enabled=metric_export_enabled,
        log_export_enabled=log_export_enabled,
    )


def shutdown_observability() -> None:
    if _tracer_provider is not None:
        _tracer_provider.shutdown()
    if _meter_provider is not None:
        _meter_provider.shutdown()


def flush_observability() -> None:
    if _tracer_provider is not None:
        _tracer_provider.force_flush()
    if _meter_provider is not None:
        _meter_provider.force_flush()


def get_tracer(name: str):
    return trace.get_tracer(name)


def get_meter(name: str):
    return metrics.get_meter(name)


@contextmanager
def start_span(name: str, attributes: dict[str, Any] | None = None):
    with trace.get_tracer("xenix").start_as_current_span(
        name,
        attributes=safe_attributes(attributes or {}),
    ) as span:
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc, attributes=safe_attributes({"error.type": error_type(exc)}))
            span.set_status(trace.Status(trace.StatusCode.ERROR, error_type(exc)))
            raise


def record_counter(name: str, value: int = 1, attributes: dict[str, Any] | None = None) -> None:
    counter = _counters.get(name)
    if counter is None:
        counter = metrics.get_meter("xenix").create_counter(name)
        _counters[name] = counter
    counter.add(value, safe_attributes(attributes or {}))


def record_histogram(name: str, value: float, attributes: dict[str, Any] | None = None, *, unit: str | None = None) -> None:
    key = f"{name}|{unit or ''}"
    histogram = _histograms.get(key)
    if histogram is None:
        histogram = metrics.get_meter("xenix").create_histogram(name, unit=unit or "")
        _histograms[key] = histogram
    histogram.record(value, safe_attributes(attributes or {}))


def safe_attributes(values: dict[str, Any]) -> dict[str, str | bool | int | float]:
    safe: dict[str, str | bool | int | float] = {}
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, Enum):
            safe[key] = str(value.value)
        elif isinstance(value, str | bool | int | float):
            safe[key] = value
        else:
            safe[key] = str(value)
    return safe


def set_span_attributes(span: Any, attributes: dict[str, Any]) -> None:
    for key, value in safe_attributes(attributes).items():
        span.set_attribute(key, value)


def error_type(exc: BaseException) -> str:
    return exc.__class__.__name__


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def inject_context(carrier: dict[str, str]) -> dict[str, str]:
    propagate.inject(carrier)
    return carrier


def extract_context(carrier: dict[str, str]):
    return propagate.extract(carrier)


def _resource_attributes(paths: AppPaths, install_id: str) -> dict[str, str]:
    return {
        "service.name": SERVICE_NAME,
        "service.version": _service_version(),
        "xenix.build.commit": BUILD_COMMIT,
        "xenix.version": APP_VERSION,
        "xenix.install.id": install_id,
        "xenix.package_mode": "packaged" if getattr(sys, "frozen", False) else "source",
        "xenix.runtime.home_class": "custom" if os.getenv("XENIX_APP_HOME") else "default",
        "os.type": sys.platform,
        "python.version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    }


def _service_version() -> str:
    try:
        return version("xenix-native")
    except PackageNotFoundError:
        return "1.0.0"


def _otlp_enabled() -> bool:
    return _trace_export_enabled() or _metric_export_enabled() or _log_export_enabled()


def _trace_export_enabled() -> bool:
    return _signal_export_enabled("TRACES", "XENIX_OTEL_EXPORT_TRACES", global_default=True)


def _metric_export_enabled() -> bool:
    return _signal_export_enabled("METRICS", "XENIX_OTEL_EXPORT_METRICS", global_default=True)


def _log_export_enabled() -> bool:
    return _env_truthy("XENIX_OTEL_EXPORT_LOGS", default=False) and _signal_endpoint_configured("LOGS")


def _signal_export_enabled(signal: str, override_name: str, *, global_default: bool) -> bool:
    override = os.getenv(override_name)
    if override is not None:
        return _env_truthy(override_name, default=False) and _signal_endpoint_configured(signal)
    if _signal_endpoint_configured(signal, include_global=False):
        return True
    return global_default and bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))


def _signal_endpoint_configured(signal: str, *, include_global: bool = True) -> bool:
    signal_endpoint = os.getenv(f"OTEL_EXPORTER_OTLP_{signal}_ENDPOINT")
    return bool(signal_endpoint or (include_global and os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")))


def _otlp_protocol(signal: str | None = None) -> str:
    if signal is not None:
        signal_protocol = os.getenv(f"OTEL_EXPORTER_OTLP_{signal}_PROTOCOL")
        if signal_protocol:
            return signal_protocol.lower()
    return os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc").lower()


def _build_span_exporter():
    if _otlp_protocol("TRACES") == "http/protobuf":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    else:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter()


def _build_metric_exporter():
    if _otlp_protocol("METRICS") == "http/protobuf":
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    else:
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

    return OTLPMetricExporter()


def _setup_otlp_log_export(resource: Resource) -> None:
    import logging

    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

    if _otlp_protocol("LOGS") == "http/protobuf":
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    else:
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
    from opentelemetry._logs import set_logger_provider

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(logger_provider)
    logging.getLogger().addHandler(LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider))


def _env_truthy(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _usage_count(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= MAX_LLM_TOKEN_COUNT else None
    if isinstance(value, float) and value.is_integer():
        normalized = int(value)
        return normalized if 0 <= normalized <= MAX_LLM_TOKEN_COUNT else None
    return None


def _is_valid_usage_observation(observation: Any) -> bool:
    if not isinstance(observation, LLMUsageObservation):
        return False
    if observation.operation not in LLM_USAGE_OPERATIONS:
        return False
    usage = observation.usage
    if not isinstance(usage, LLMTokenUsage):
        return False
    return all(
        type(getattr(usage, field)) is int and 0 <= getattr(usage, field) <= MAX_LLM_TOKEN_COUNT
        for field in _LLM_USAGE_FIELDS
    )


def _stable_key(value: str | None) -> str | None:
    return stable_hash(value) if isinstance(value, str) and value else None


def _usage_from_record(record: dict[str, Any]) -> LLMTokenUsage | None:
    payload = {field: record[field] for field in _LLM_USAGE_FIELDS if field in record}
    return LLMTokenUsage.from_payload(payload)
