"""Small, dependency-free observability primitives for Creative Hub.

The registry intentionally accepts only declared, bounded label sets.  It is
designed for in-process metrics and the Prometheus text exposition format; it
does not retain request IDs, project IDs, SQL, URLs, credentials, or prompts.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from threading import RLock
from typing import Mapping


class MetricDefinitionError(ValueError):
    """Raised when a metric is redefined with an incompatible contract."""


class UnsafeMetricLabelError(ValueError):
    """Raised when a label could disclose a secret or create high cardinality."""


class SeriesLimitExceeded(RuntimeError):
    """Raised before an unbounded label combination can enter the registry."""


_METRIC_NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_LABEL_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_UUID_LITERAL = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
)
_SECRET_VALUE = re.compile(
    r"(?i)(?:\bbearer\s+\S+|"
    r"\bsk-(?:sp-|ws-)?[a-z0-9_-]{8,}|"
    r"(?:api[_-]?key|access[_-]?token|authorization|cookie)\s*[=:])"
)
_FORBIDDEN_LABEL_PARTS = {
    "artifact_id",
    "authorization",
    "cookie",
    "credential",
    "key",
    "path",
    "project",
    "project_id",
    "prompt",
    "query",
    "request_id",
    "run_id",
    "secret",
    "sql",
    "statement",
    "token",
    "uri",
    "url",
    "user",
    "user_id",
    "workflow_id",
}
DEFAULT_HISTOGRAM_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)
NONTERMINAL_ATTEMPT_AGE_BANDS = frozenset(
    {"fresh", "over_15m", "over_1h"}
)
RESOURCE_POOLS = frozenset(
    {"cpu", "local_gpu", "cloud_image", "cloud_video", "llm"}
)
PRIORITY_CLASSES = frozenset(
    {"batch", "interactive", "urgent", "system"}
)
QUEUE_OUTCOMES = frozenset(
    {"claimed", "deferred", "quota_blocked", "waiting_human"}
)
ATTEMPT_OUTCOMES = frozenset(
    {
        "accepted",
        "cancelled",
        "completed_pending_collection",
        "failed",
        "lease_expired",
        "needs_human",
        "outcome_unknown",
        "succeeded",
    }
)
PROVIDERS = frozenset({"comfyui", "glm", "qwen", "local", "other"})
PROVIDER_OUTCOMES = frozenset(
    {
        "completed_pending_collection",
        "failed",
        "outcome_unknown",
        "running",
        "submitted",
        "succeeded",
    }
)
ARTIFACT_STATES = frozenset(
    {"staging", "pending", "published", "orphan_staging", "tombstoned"}
)
ARTIFACT_ACTIONS = frozenset({"adopt", "reconcile", "sweep"})
ARTIFACT_OUTCOMES = frozenset(
    {"deleted", "failed", "retained", "succeeded"}
)
QC_GATES = frozenset({"asset", "keyframe", "clip", "final", "delivery"})
QC_OUTCOMES = frozenset(
    {"pass", "fail", "error", "needs_human", "degraded_accepted"}
)
TABLE_FAMILIES = frozenset(
    {
        "artifacts",
        "generation",
        "learning",
        "operation_events",
        "orchestration",
        "other",
        "quality",
    }
)
QUERY_OPERATIONS = frozenset(
    {
        "alter",
        "create",
        "delete",
        "drop",
        "insert",
        "other",
        "pragma",
        "select",
        "update",
        "with",
    }
)
QUERY_OUTCOMES = frozenset({"success", "error"})
QUERY_WORKLOADS = frozenset(
    {
        "broken_lookup",
        "generation_api",
        "hub_api",
        "inner",
        "jobs_api",
        "learning_api",
        "metrics_scrape",
        "outer",
        "postgres_slo_probe",
        "settings_api",
        "strict_lookup",
        "timeline",
        "workflow_detail",
        "workflow_list",
    }
)
QUERY_BUDGET_REASONS = frozenset(
    {
        "count",
        "single_latency",
        "total_latency",
        "n_plus_one",
        "request_latency",
    }
)
COST_SCOPES = frozenset(
    {"global", "project", "workflow", "unconfigured"}
)
COST_VERDICTS = frozenset({"allow", "warn", "block"})
# P0 product-upgrade metrics (approved plan section 13).  Labels are bare,
# bounded enums; no project id, artifact id, run id, or path is ever recorded.
PRODUCT_LEGACY_410_ROUTES = frozenset(
    {"generation_runs", "visual_verdicts"}
)
PRODUCT_CONTEXT_MISMATCH_KINDS = frozenset(
    {"cross_project_object", "research_project_context"}
)
PRODUCT_PROJECTION_PROBES = frozenset(
    {"research_workspace", "shot_workspace"}
)
#: Repair scope is the bounded QC stage being repaired (plan section 13).
REPAIR_SCOPES = frozenset({"asset", "keyframe", "clip", "final"})
REPAIR_OUTCOMES = frozenset(
    {
        "not_required",
        "planned",
        "succeeded",
        "failed",
        "budget_exhausted",
    }
)
MODE_CHANGE_DECISIONS = frozenset(
    {"proposed", "approved", "rejected"}
)
#: Artifact Range outcomes are the exact HTTP status boundaries.
ARTIFACT_RANGE_STATUSES = frozenset(
    {"200", "206", "304", "404", "409", "415", "416", "5xx"}
)
PREFLIGHT_BLOCKER_KINDS = frozenset(
    {"cookie", "credential", "gpu", "input"}
)


def _bounded(
    value: object,
    *,
    field: str,
    allowed: frozenset[str],
) -> str:
    rendered = str(value).lower()
    if rendered not in allowed:
        raise UnsafeMetricLabelError(
            f"{field} must be one of the declared bounded values"
        )
    return rendered


def _validate_metric_name(name: str) -> str:
    if not _METRIC_NAME.fullmatch(name):
        raise MetricDefinitionError(f"invalid Prometheus metric name: {name!r}")
    return name


def _validate_label_name(name: str) -> str:
    lowered = name.lower()
    if not _LABEL_NAME.fullmatch(name):
        raise MetricDefinitionError(f"invalid Prometheus label name: {name!r}")
    if (
        lowered in _FORBIDDEN_LABEL_PARTS
        or lowered.endswith("_id")
        or any(part in _FORBIDDEN_LABEL_PARTS for part in lowered.split("_"))
    ):
        raise UnsafeMetricLabelError(
            f"label name is secret-bearing or high-cardinality: {name!r}"
        )
    return name


def _validate_label_value(value: object) -> str:
    rendered = str(value)
    if not rendered or len(rendered) > 128:
        raise UnsafeMetricLabelError("metric label values must be 1..128 chars")
    if any(ord(character) < 32 for character in rendered):
        raise UnsafeMetricLabelError("metric label values cannot contain controls")
    if _UUID_LITERAL.search(rendered) or _SECRET_VALUE.search(rendered):
        raise UnsafeMetricLabelError(
            "metric label value resembles an identifier or credential"
        )
    return rendered


def _finite_non_negative(value: float, *, field: str) -> float:
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return numeric


def _number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return format(value, ".15g")


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _escape_help(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n")


def _render_labels(
    label_names: tuple[str, ...],
    label_values: tuple[str, ...],
    *,
    extra: tuple[tuple[str, str], ...] = (),
) -> str:
    if not label_names and not extra:
        return ""
    pairs = sorted(zip(label_names, label_values), key=lambda pair: pair[0])
    pairs.extend(extra)
    body = ",".join(
        f'{name}="{_escape_label(value)}"' for name, value in pairs
    )
    return "{" + body + "}"


class _Metric:
    metric_type = ""

    def __init__(
        self,
        *,
        registry: MetricRegistry,
        name: str,
        help_text: str,
        label_names: tuple[str, ...],
    ) -> None:
        self.registry = registry
        self.name = name
        self.help_text = help_text
        self.label_names = label_names
        self._series: set[tuple[str, ...]] = set()

    @property
    def contract(self) -> tuple[object, ...]:
        return (self.metric_type, self.help_text, self.label_names)

    def _labels(self, labels: Mapping[str, object] | None) -> tuple[str, ...]:
        provided = dict(labels or {})
        expected = set(self.label_names)
        if set(provided) != expected:
            missing = sorted(expected - set(provided))
            extra = sorted(set(provided) - expected)
            raise ValueError(
                f"labels do not match metric contract; missing={missing}, "
                f"extra={extra}"
            )
        values = tuple(
            _validate_label_value(provided[name]) for name in self.label_names
        )
        if values not in self._series:
            if len(self._series) >= self.registry.max_series_per_metric:
                raise SeriesLimitExceeded(
                    f"metric {self.name!r} exceeded "
                    f"{self.registry.max_series_per_metric} series"
                )
            self._series.add(values)
        return values

    def _render_samples(self) -> list[str]:
        raise NotImplementedError


class Counter(_Metric):
    metric_type = "counter"

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._values: dict[tuple[str, ...], float] = {}

    def inc(
        self,
        amount: float = 1.0,
        *,
        labels: Mapping[str, object] | None = None,
    ) -> None:
        numeric = _finite_non_negative(amount, field="counter increment")
        with self.registry._lock:
            values = self._labels(labels)
            self._values[values] = self._values.get(values, 0.0) + numeric

    def _render_samples(self) -> list[str]:
        return [
            f"{self.name}{_render_labels(self.label_names, labels)} "
            f"{_number(value)}"
            for labels, value in sorted(self._values.items())
        ]


class Gauge(_Metric):
    metric_type = "gauge"

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._values: dict[tuple[str, ...], float] = {}

    def set(
        self,
        value: float,
        *,
        labels: Mapping[str, object] | None = None,
    ) -> None:
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("gauge value must be finite")
        with self.registry._lock:
            values = self._labels(labels)
            self._values[values] = numeric

    def _render_samples(self) -> list[str]:
        return [
            f"{self.name}{_render_labels(self.label_names, labels)} "
            f"{_number(value)}"
            for labels, value in sorted(self._values.items())
        ]


@dataclass
class _HistogramState:
    buckets: list[int]
    count: int = 0
    total: float = 0.0


class Histogram(_Metric):
    metric_type = "histogram"

    def __init__(self, *, buckets: tuple[float, ...], **kwargs: object) -> None:
        super().__init__(**kwargs)
        if not buckets:
            raise MetricDefinitionError("histograms need at least one bucket")
        validated = tuple(
            _finite_non_negative(value, field="histogram bucket")
            for value in buckets
        )
        if tuple(sorted(set(validated))) != validated:
            raise MetricDefinitionError(
                "histogram buckets must be strictly increasing"
            )
        self.buckets = validated
        self._values: dict[tuple[str, ...], _HistogramState] = {}

    @property
    def contract(self) -> tuple[object, ...]:
        return super().contract + (self.buckets,)

    def observe(
        self,
        value: float,
        *,
        labels: Mapping[str, object] | None = None,
    ) -> None:
        numeric = _finite_non_negative(value, field="histogram observation")
        with self.registry._lock:
            values = self._labels(labels)
            state = self._values.setdefault(
                values,
                _HistogramState(buckets=[0] * len(self.buckets)),
            )
            for index, boundary in enumerate(self.buckets):
                if numeric <= boundary:
                    state.buckets[index] += 1
            state.count += 1
            state.total += numeric

    def _render_samples(self) -> list[str]:
        lines: list[str] = []
        for labels, state in sorted(self._values.items()):
            for boundary, count in zip(self.buckets, state.buckets):
                lines.append(
                    f"{self.name}_bucket"
                    f"{_render_labels(self.label_names, labels, extra=(('le', _number(boundary)),))} "
                    f"{count}"
                )
            lines.append(
                f"{self.name}_bucket"
                f"{_render_labels(self.label_names, labels, extra=(('le', '+Inf'),))} "
                f"{state.count}"
            )
            base_labels = _render_labels(self.label_names, labels)
            lines.append(f"{self.name}_sum{base_labels} {_number(state.total)}")
            lines.append(f"{self.name}_count{base_labels} {state.count}")
        return lines


class MetricRegistry:
    """Thread-safe, bounded Prometheus text registry."""

    def __init__(self, *, max_series_per_metric: int = 200) -> None:
        if max_series_per_metric < 1:
            raise ValueError("max_series_per_metric must be positive")
        self.max_series_per_metric = max_series_per_metric
        self._lock = RLock()
        self._metrics: dict[str, _Metric] = {}

    def _register(self, metric: _Metric) -> _Metric:
        with self._lock:
            existing = self._metrics.get(metric.name)
            if existing is None:
                self._metrics[metric.name] = metric
                return metric
            if existing.contract != metric.contract:
                raise MetricDefinitionError(
                    f"metric {metric.name!r} already has another contract"
                )
            return existing

    def _definition(
        self,
        name: str,
        help_text: str,
        label_names: tuple[str, ...],
    ) -> dict[str, object]:
        _validate_metric_name(name)
        if not help_text or "\n" in help_text:
            raise MetricDefinitionError("metric help must be one non-empty line")
        checked = tuple(_validate_label_name(label) for label in label_names)
        if len(checked) != len(set(checked)):
            raise MetricDefinitionError("metric label names must be unique")
        return {
            "registry": self,
            "name": name,
            "help_text": help_text,
            "label_names": checked,
        }

    def counter(
        self,
        name: str,
        help_text: str,
        *,
        label_names: tuple[str, ...] = (),
    ) -> Counter:
        metric = Counter(**self._definition(name, help_text, label_names))
        registered = self._register(metric)
        assert isinstance(registered, Counter)
        return registered

    def gauge(
        self,
        name: str,
        help_text: str,
        *,
        label_names: tuple[str, ...] = (),
    ) -> Gauge:
        metric = Gauge(**self._definition(name, help_text, label_names))
        registered = self._register(metric)
        assert isinstance(registered, Gauge)
        return registered

    def histogram(
        self,
        name: str,
        help_text: str,
        *,
        label_names: tuple[str, ...] = (),
        buckets: tuple[float, ...] = DEFAULT_HISTOGRAM_BUCKETS,
    ) -> Histogram:
        metric = Histogram(
            **self._definition(name, help_text, label_names),
            buckets=buckets,
        )
        registered = self._register(metric)
        assert isinstance(registered, Histogram)
        return registered

    def render_prometheus(self) -> str:
        with self._lock:
            lines: list[str] = []
            for name in sorted(self._metrics):
                metric = self._metrics[name]
                lines.append(f"# HELP {name} {_escape_help(metric.help_text)}")
                lines.append(f"# TYPE {name} {metric.metric_type}")
                lines.extend(metric._render_samples())
            return "\n".join(lines) + "\n"


class DomainObservability:
    """Low-cardinality metric facade shared by API, workers, and operators."""

    def __init__(self, registry: MetricRegistry | None = None) -> None:
        self.registry = registry or MetricRegistry()
        self.http_requests = self.registry.counter(
            "creative_hub_http_requests_total",
            "Completed Creative Hub HTTP requests.",
            label_names=("method", "route", "status_class"),
        )
        self.http_duration = self.registry.histogram(
            "creative_hub_http_request_duration_seconds",
            "Creative Hub HTTP request duration.",
            label_names=("method", "route"),
        )
        self.queue_dispatch = self.registry.counter(
            "creative_hub_queue_dispatch_total",
            "Queue dispatch decisions.",
            label_names=("resource_pool", "priority_class", "outcome"),
        )
        self.queue_wait = self.registry.histogram(
            "creative_hub_queue_wait_seconds",
            "Wait time before queue dispatch.",
            label_names=("resource_pool", "priority_class"),
        )
        self.queue_oldest_wait = self.registry.gauge(
            "creative_hub_queue_oldest_wait_seconds",
            "Oldest runnable item wait time.",
            label_names=("resource_pool", "priority_class"),
        )
        self.queue_fairness = self.registry.gauge(
            "creative_hub_queue_fairness_ratio",
            "Observed to entitled dispatch ratio.",
            label_names=("resource_pool", "priority_class"),
        )
        self.queue_starvation = self.registry.counter(
            "creative_hub_queue_starvation_total",
            "Queue observations exceeding the starvation threshold.",
            label_names=("resource_pool", "priority_class"),
        )
        self.operation_attempts = self.registry.counter(
            "creative_hub_operation_attempts_total",
            "Operation attempt terminal and recovery outcomes.",
            label_names=("resource_pool", "outcome"),
        )
        self.nonterminal_attempts = self.registry.gauge(
            "creative_hub_nonterminal_attempts",
            "Non-terminal operation attempts by bounded age band.",
            label_names=("resource_pool", "age_band"),
        )
        self.provider_invocations = self.registry.counter(
            "creative_hub_provider_invocations_total",
            "Provider invocation lifecycle outcomes.",
            label_names=("provider", "outcome"),
        )
        self.provider_cost_actualized = self.registry.counter(
            "creative_hub_provider_cost_actualized_micros_total",
            "Actual provider cost committed in integer currency micros.",
            label_names=("provider", "outcome"),
        )
        self.artifacts_state = self.registry.gauge(
            "creative_hub_artifacts_state",
            "Artifacts in publication and orphan-recovery states.",
            label_names=("state",),
        )
        self.artifact_orphans = self.registry.counter(
            "creative_hub_artifact_orphans_total",
            "Artifact orphan adoption and sweep outcomes.",
            label_names=("action", "outcome"),
        )
        self.qc_cost = self.registry.counter(
            "creative_hub_qc_cost_units_total",
            "Accumulated QC provider cost units.",
            label_names=("gate", "provider"),
        )
        self.qc_evaluations = self.registry.counter(
            "creative_hub_qc_evaluations_total",
            "Machine QC evaluation outcomes.",
            label_names=("gate", "outcome"),
        )
        self.human_review_backlog = self.registry.gauge(
            "creative_hub_human_review_backlog",
            "Open human review tasks by gate and bounded age band.",
            label_names=("gate", "age_band"),
        )
        self.db_table_bytes = self.registry.gauge(
            "creative_hub_db_table_bytes",
            "Database bytes by bounded table family.",
            label_names=("table_family",),
        )
        self.db_rows = self.registry.gauge(
            "creative_hub_db_rows",
            "Estimated database rows by bounded table family.",
            label_names=("table_family",),
        )
        self.db_queries = self.registry.counter(
            "creative_hub_db_queries_total",
            "Database query outcomes by statement operation.",
            label_names=("operation", "outcome"),
        )
        self.db_query_duration = self.registry.histogram(
            "creative_hub_db_query_duration_seconds",
            "Database query duration by statement operation.",
            label_names=("operation",),
        )
        self.query_budget_exceeded = self.registry.counter(
            "creative_hub_query_budget_exceeded_total",
            "Request and query SLO budget violations.",
            label_names=("workload", "reason"),
        )
        self.cost_budget_checks = self.registry.counter(
            "creative_hub_cost_budget_checks_total",
            "Cost budget admission decisions by bounded scope and pool.",
            label_names=("scope", "resource_pool", "verdict"),
        )
        # P0 product-upgrade metrics (approved plan section 13).  All names
        # and label sets are pinned; no host absolute path, project id,
        # artifact id, run id, prompt text, cookie, key, or token is recorded.
        # ``ui_legacy_410_calls_total`` and ``project_context_mismatch_total``
        # are deliberately label-less per the bare metric contract.
        self.ui_legacy_410_calls = self.registry.counter(
            "ui_legacy_410_calls_total",
            "Calls to retired legacy Creative Hub write endpoints.",
            label_names=(),
        )
        self.project_context_mismatch = self.registry.counter(
            "project_context_mismatch_total",
            "Project context containment violations observed by the BFF.",
            label_names=(),
        )
        self.research_projection_lag = self.registry.gauge(
            "research_projection_lag_seconds",
            "Research workspace projection lag.",
            label_names=(),
        )
        self.shot_workspace_projection_lag = self.registry.gauge(
            "shot_workspace_projection_lag_seconds",
            "Shot workspace projection lag.",
            label_names=(),
        )
        self.human_review_open_age = self.registry.gauge(
            "human_review_open_age_seconds",
            "Age of the oldest open human review task.",
            label_names=(),
        )
        self.repair_attempts = self.registry.counter(
            "repair_attempts_total",
            "Repair proposal outcomes by bounded scope.",
            label_names=("scope", "outcome"),
        )
        self.mode_change_proposals = self.registry.counter(
            "mode_change_proposals_total",
            "Mode change proposal decisions.",
            label_names=("decision",),
        )
        self.artifact_range_requests = self.registry.counter(
            "artifact_range_requests_total",
            "Artifact media Range request outcomes.",
            label_names=("status",),
        )
        self.skill_snapshot_missing = self.registry.counter(
            "skill_snapshot_missing_total",
            "Workflow runs lacking a frozen skill snapshot.",
            label_names=(),
        )
        self.preflight_blockers = self.registry.counter(
            "preflight_blockers_total",
            "Project dependency preflight blockers by bounded kind.",
            label_names=("kind",),
        )

    @staticmethod
    def _route(route: str) -> str:
        if (
            not route.startswith("/")
            or "?" in route
            or "#" in route
            or _UUID_LITERAL.search(route)
            or re.search(r"/\d+(?:/|$)", route)
        ):
            raise UnsafeMetricLabelError(
                "HTTP route labels must be templated routes without parameters"
            )
        return route

    def record_http(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        checked_method = method.upper()
        if not re.fullmatch(r"[A-Z]{3,10}", checked_method):
            raise UnsafeMetricLabelError("invalid HTTP method label")
        status = int(status_code)
        status_class = f"{status // 100}xx" if 100 <= status <= 599 else "other"
        labels = {
            "method": checked_method,
            "route": self._route(route),
            "status_class": status_class,
        }
        self.http_requests.inc(labels=labels)
        self.http_duration.observe(
            duration_seconds,
            labels={"method": checked_method, "route": labels["route"]},
        )

    def record_queue_dispatch(
        self,
        *,
        resource_pool: str,
        priority_class: str,
        outcome: str,
        wait_seconds: float,
        oldest_wait_seconds: float,
        fairness_ratio: float,
        starved: bool = False,
    ) -> None:
        base = {
            "resource_pool": _bounded(
                resource_pool,
                field="resource_pool",
                allowed=RESOURCE_POOLS,
            ),
            "priority_class": _bounded(
                priority_class,
                field="priority_class",
                allowed=PRIORITY_CLASSES,
            ),
        }
        self.queue_dispatch.inc(
            labels={
                **base,
                "outcome": _bounded(
                    outcome,
                    field="queue outcome",
                    allowed=QUEUE_OUTCOMES,
                ),
            }
        )
        self.queue_wait.observe(wait_seconds, labels=base)
        self.queue_oldest_wait.set(
            _finite_non_negative(oldest_wait_seconds, field="oldest wait"),
            labels=base,
        )
        self.queue_fairness.set(
            _finite_non_negative(fairness_ratio, field="fairness ratio"),
            labels=base,
        )
        if starved:
            self.queue_starvation.inc(labels=base)

    def record_attempt(self, *, resource_pool: str, outcome: str) -> None:
        self.operation_attempts.inc(
            labels={
                "resource_pool": _bounded(
                    resource_pool,
                    field="resource_pool",
                    allowed=RESOURCE_POOLS,
                ),
                "outcome": _bounded(
                    outcome,
                    field="attempt outcome",
                    allowed=ATTEMPT_OUTCOMES,
                ),
            }
        )

    def set_nonterminal_attempts(
        self,
        *,
        resource_pool: str,
        age_band: str,
        count: float,
    ) -> None:
        self.nonterminal_attempts.set(
            _finite_non_negative(count, field="non-terminal attempt count"),
            labels={
                "resource_pool": _bounded(
                    resource_pool,
                    field="resource_pool",
                    allowed=RESOURCE_POOLS,
                ),
                "age_band": _bounded(
                    age_band,
                    field="age_band",
                    allowed=NONTERMINAL_ATTEMPT_AGE_BANDS,
                ),
            },
        )

    def record_provider(self, *, provider: str, outcome: str) -> None:
        self.provider_invocations.inc(
            labels={
                "provider": _bounded(
                    provider,
                    field="provider",
                    allowed=PROVIDERS,
                ),
                "outcome": _bounded(
                    outcome,
                    field="provider outcome",
                    allowed=PROVIDER_OUTCOMES,
                ),
            }
        )

    def record_provider_cost_actualized(
        self,
        *,
        provider: str,
        outcome: str,
        cost_micros: int,
    ) -> None:
        self.provider_cost_actualized.inc(
            _finite_non_negative(
                cost_micros,
                field="actualized provider cost",
            ),
            labels={
                "provider": _bounded(
                    provider,
                    field="provider",
                    allowed=PROVIDERS,
                ),
                "outcome": _bounded(
                    outcome,
                    field="provider outcome",
                    allowed=PROVIDER_OUTCOMES,
                ),
            },
        )

    def set_artifact_state(self, *, state: str, count: float) -> None:
        self.artifacts_state.set(
            _finite_non_negative(count, field="artifact count"),
            labels={
                "state": _bounded(
                    state,
                    field="artifact state",
                    allowed=ARTIFACT_STATES,
                )
            },
        )

    def record_artifact_orphan(self, *, action: str, outcome: str) -> None:
        self.artifact_orphans.inc(
            labels={
                "action": _bounded(
                    action,
                    field="artifact action",
                    allowed=ARTIFACT_ACTIONS,
                ),
                "outcome": _bounded(
                    outcome,
                    field="artifact outcome",
                    allowed=ARTIFACT_OUTCOMES,
                ),
            }
        )

    def record_qc(
        self,
        *,
        gate: str,
        provider: str,
        outcome: str,
        cost_units: float,
    ) -> None:
        checked_gate = _bounded(
            gate,
            field="QC gate",
            allowed=QC_GATES,
        )
        self.qc_evaluations.inc(
            labels={
                "gate": checked_gate,
                "outcome": _bounded(
                    outcome,
                    field="QC outcome",
                    allowed=QC_OUTCOMES,
                ),
            }
        )
        self.qc_cost.inc(
            _finite_non_negative(cost_units, field="QC cost"),
            labels={
                "gate": checked_gate,
                "provider": _bounded(
                    provider,
                    field="provider",
                    allowed=PROVIDERS,
                ),
            },
        )

    def set_human_review_backlog(
        self,
        *,
        gate: str,
        age_band: str,
        count: float,
    ) -> None:
        self.human_review_backlog.set(
            _finite_non_negative(count, field="review backlog"),
            labels={
                "gate": _bounded(
                    gate,
                    field="QC gate",
                    allowed=QC_GATES,
                ),
                "age_band": _bounded(
                    age_band,
                    field="age_band",
                    allowed=NONTERMINAL_ATTEMPT_AGE_BANDS,
                ),
            },
        )

    def set_db_growth(
        self,
        *,
        table_family: str,
        bytes_used: float,
        row_count: float,
    ) -> None:
        labels = {
            "table_family": _bounded(
                table_family,
                field="table_family",
                allowed=TABLE_FAMILIES,
            )
        }
        self.db_table_bytes.set(
            _finite_non_negative(bytes_used, field="database bytes"),
            labels=labels,
        )
        self.db_rows.set(
            _finite_non_negative(row_count, field="database rows"),
            labels=labels,
        )

    def record_query(
        self,
        *,
        operation: str,
        outcome: str,
        duration_seconds: float,
    ) -> None:
        labels = {
            "operation": _bounded(
                operation,
                field="query operation",
                allowed=QUERY_OPERATIONS,
            ),
            "outcome": _bounded(
                outcome,
                field="query outcome",
                allowed=QUERY_OUTCOMES,
            ),
        }
        self.db_queries.inc(labels=labels)
        self.db_query_duration.observe(
            duration_seconds,
            labels={"operation": labels["operation"]},
        )

    def record_query_budget_exceeded(
        self,
        *,
        workload: str,
        reason: str,
    ) -> None:
        self.query_budget_exceeded.inc(
            labels={
                "workload": _bounded(
                    workload,
                    field="query workload",
                    allowed=QUERY_WORKLOADS,
                ),
                "reason": _bounded(
                    reason,
                    field="query budget reason",
                    allowed=QUERY_BUDGET_REASONS,
                ),
            }
        )

    def record_cost_budget_check(
        self,
        *,
        scope: str,
        resource_pool: str,
        verdict: str,
    ) -> None:
        self.cost_budget_checks.inc(
            labels={
                "scope": _bounded(
                    scope,
                    field="cost scope",
                    allowed=COST_SCOPES,
                ),
                "resource_pool": _bounded(
                    resource_pool,
                    field="resource_pool",
                    allowed=RESOURCE_POOLS,
                ),
                "verdict": _bounded(
                    verdict,
                    field="cost verdict",
                    allowed=COST_VERDICTS,
                ),
            }
        )

    def record_legacy_410_call(self, *, route: str) -> None:
        # The metric is label-less; ``route`` is still validated so callers
        # remain honest about which retired endpoint was hit.
        _bounded(
            route,
            field="legacy 410 route",
            allowed=PRODUCT_LEGACY_410_ROUTES,
        )
        self.ui_legacy_410_calls.inc(labels=None)

    def record_project_context_mismatch(self, *, kind: str) -> None:
        # The metric is label-less; ``kind`` is still validated for honesty.
        _bounded(
            kind,
            field="project context mismatch kind",
            allowed=PRODUCT_CONTEXT_MISMATCH_KINDS,
        )
        self.project_context_mismatch.inc(labels=None)

    def record_projection_lag(self, *, probe: str, lag_seconds: float) -> None:
        bounded_probe = _bounded(
            probe,
            field="projection probe",
            allowed=PRODUCT_PROJECTION_PROBES,
        )
        value = _finite_non_negative(
            lag_seconds, field="projection lag"
        )
        if bounded_probe == "research_workspace":
            self.research_projection_lag.set(value, labels=None)
        else:
            self.shot_workspace_projection_lag.set(value, labels=None)

    def record_human_review_open_age(self, *, age_seconds: float) -> None:
        self.human_review_open_age.set(
            _finite_non_negative(
                age_seconds, field="human review open age"
            ),
            labels=None,
        )

    def record_repair_attempt(self, *, scope: str, outcome: str) -> None:
        self.repair_attempts.inc(
            labels={
                "scope": _bounded(
                    scope, field="repair scope", allowed=REPAIR_SCOPES
                ),
                "outcome": _bounded(
                    outcome,
                    field="repair outcome",
                    allowed=REPAIR_OUTCOMES,
                ),
            }
        )

    def record_mode_change_proposal(self, *, decision: str) -> None:
        self.mode_change_proposals.inc(
            labels={
                "decision": _bounded(
                    decision,
                    field="mode change decision",
                    allowed=MODE_CHANGE_DECISIONS,
                )
            }
        )

    def record_artifact_range_request(self, *, status: str) -> None:
        self.artifact_range_requests.inc(
            labels={
                "status": _bounded(
                    status,
                    field="artifact range status",
                    allowed=ARTIFACT_RANGE_STATUSES,
                )
            }
        )

    def record_skill_snapshot_missing(self) -> None:
        self.skill_snapshot_missing.inc(labels=None)

    def record_preflight_blocker(self, *, kind: str) -> None:
        self.preflight_blockers.inc(
            labels={
                "kind": _bounded(
                    kind,
                    field="preflight blocker kind",
                    allowed=PREFLIGHT_BLOCKER_KINDS,
                )
            }
        )

    def render_prometheus(self) -> str:
        return self.registry.render_prometheus()
