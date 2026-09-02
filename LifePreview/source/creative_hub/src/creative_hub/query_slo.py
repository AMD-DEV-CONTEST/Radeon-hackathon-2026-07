"""Per-request SQL query budgets and SQLAlchemy instrumentation.

Only a normalized statement fingerprint and its broad operation are retained.
Raw SQL, bind parameters, database errors, row values, and object identifiers
never enter alerts or metrics.
"""

from __future__ import annotations

from collections import Counter as ValueCounter
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
import hashlib
import math
import re
from threading import RLock
from time import monotonic
from typing import Callable, Protocol
from weakref import WeakKeyDictionary

from sqlalchemy import event
from sqlalchemy.engine import Engine


class QuerySLOObserver(Protocol):
    def record_query(
        self,
        *,
        operation: str,
        outcome: str,
        duration_seconds: float,
    ) -> None: ...

    def record_query_budget_exceeded(
        self,
        *,
        workload: str,
        reason: str,
    ) -> None: ...


@dataclass(frozen=True)
class BudgetLimits:
    max_queries: int = 50
    max_total_query_seconds: float = 1.0
    max_single_query_seconds: float = 0.25
    repeated_query_limit: int = 5

    def __post_init__(self) -> None:
        if self.max_queries < 0:
            raise ValueError("max_queries cannot be negative")
        if self.repeated_query_limit < 1:
            raise ValueError("repeated_query_limit must be positive")
        for name in (
            "max_total_query_seconds",
            "max_single_query_seconds",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")


@dataclass(frozen=True)
class QuerySLOAlert:
    code: str
    severity: str
    workload: str
    observed: float
    limit: float
    query_count: int
    statement_fingerprint: str | None
    operation: str | None
    safe_message: str


class QueryBudgetViolation(RuntimeError):
    def __init__(self, alerts: tuple[QuerySLOAlert, ...]) -> None:
        self.alerts = alerts
        codes = ",".join(sorted({alert.code for alert in alerts}))
        super().__init__(f"query budget violated: {codes}")


_WORKLOAD = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_LEADING_OPERATION = re.compile(r"^\s*(?:/\*.*?\*/\s*)*([a-zA-Z]+)", re.S)
_STRING_LITERAL = re.compile(r"'(?:''|[^'])*'")
_NUMBER_LITERAL = re.compile(r"\b\d+(?:\.\d+)?\b")
_WHITESPACE = re.compile(r"\s+")
_KNOWN_OPERATIONS = {
    "delete",
    "insert",
    "select",
    "update",
    "with",
    "create",
    "alter",
    "drop",
    "pragma",
}
_REASON_BY_CODE = {
    "query_count_exceeded": "count",
    "single_query_latency_exceeded": "single_latency",
    "total_query_latency_exceeded": "total_latency",
    "n_plus_one_suspected": "n_plus_one",
    "request_latency_exceeded": "request_latency",
}


def _workload(value: str) -> str:
    if not _WORKLOAD.fullmatch(value):
        raise ValueError(
            "workload must be a stable lower_snake_case query class"
        )
    return value


def _statement_operation(statement: object) -> str:
    match = _LEADING_OPERATION.match(str(statement or ""))
    if not match:
        return "other"
    operation = match.group(1).lower()
    return operation if operation in _KNOWN_OPERATIONS else "other"


def _statement_fingerprint(statement: object) -> str:
    normalized = str(statement or "")
    normalized = _STRING_LITERAL.sub("?", normalized)
    normalized = _NUMBER_LITERAL.sub("?", normalized)
    normalized = _WHITESPACE.sub(" ", normalized).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _safe_observer_call(
    observer: QuerySLOObserver | None,
    method: str,
    **kwargs: object,
) -> None:
    if observer is None:
        return
    try:
        getattr(observer, method)(**kwargs)
    except Exception:
        # Metrics must never change request success/failure semantics.
        return


@dataclass
class QueryBudgetState:
    workload: str
    limits: BudgetLimits
    alert_sink: Callable[[QuerySLOAlert], object] | None = None
    observer: QuerySLOObserver | None = None
    query_count: int = 0
    total_query_seconds: float = 0.0
    max_query_seconds: float = 0.0
    outcome_counts: dict[str, int] = field(default_factory=dict)
    alerts: list[QuerySLOAlert] = field(default_factory=list)
    _fingerprints: ValueCounter[str] = field(
        default_factory=ValueCounter,
        repr=False,
    )
    _emitted: set[tuple[str, str | None]] = field(
        default_factory=set,
        repr=False,
    )

    def _alert(
        self,
        *,
        code: str,
        observed: float,
        limit: float,
        statement_fingerprint: str | None,
        operation: str | None,
        dedupe_fingerprint: bool = False,
    ) -> None:
        dedupe_key = (
            code,
            statement_fingerprint if dedupe_fingerprint else None,
        )
        if dedupe_key in self._emitted:
            return
        self._emitted.add(dedupe_key)
        alert = QuerySLOAlert(
            code=code,
            severity="warning",
            workload=self.workload,
            observed=observed,
            limit=limit,
            query_count=self.query_count,
            statement_fingerprint=statement_fingerprint,
            operation=operation,
            safe_message=f"query SLO threshold exceeded (code={code})",
        )
        self.alerts.append(alert)
        reason = _REASON_BY_CODE[code]
        _safe_observer_call(
            self.observer,
            "record_query_budget_exceeded",
            workload=self.workload,
            reason=reason,
        )
        if self.alert_sink is not None:
            try:
                self.alert_sink(alert)
            except Exception:
                # Alert delivery is best effort; state still retains the alert.
                pass

    def record_query(
        self,
        *,
        statement: object,
        operation: str,
        outcome: str,
        duration_seconds: float,
    ) -> None:
        duration = max(0.0, float(duration_seconds))
        fingerprint = _statement_fingerprint(statement)
        self.query_count += 1
        self.total_query_seconds += duration
        self.max_query_seconds = max(self.max_query_seconds, duration)
        self.outcome_counts[outcome] = self.outcome_counts.get(outcome, 0) + 1
        self._fingerprints[fingerprint] += 1

        if self.query_count > self.limits.max_queries:
            self._alert(
                code="query_count_exceeded",
                observed=float(self.query_count),
                limit=float(self.limits.max_queries),
                statement_fingerprint=fingerprint,
                operation=operation,
            )
        if duration > self.limits.max_single_query_seconds:
            self._alert(
                code="single_query_latency_exceeded",
                observed=duration,
                limit=self.limits.max_single_query_seconds,
                statement_fingerprint=fingerprint,
                operation=operation,
                dedupe_fingerprint=True,
            )
        if self.total_query_seconds > self.limits.max_total_query_seconds:
            self._alert(
                code="total_query_latency_exceeded",
                observed=self.total_query_seconds,
                limit=self.limits.max_total_query_seconds,
                statement_fingerprint=fingerprint,
                operation=operation,
            )
        repetitions = self._fingerprints[fingerprint]
        if repetitions > self.limits.repeated_query_limit:
            self._alert(
                code="n_plus_one_suspected",
                observed=float(repetitions),
                limit=float(self.limits.repeated_query_limit),
                statement_fingerprint=fingerprint,
                operation=operation,
                dedupe_fingerprint=True,
            )


_ACTIVE_QUERY_BUDGET: ContextVar[QueryBudgetState | None] = ContextVar(
    "creative_hub_active_query_budget",
    default=None,
)


def active_query_budget() -> QueryBudgetState | None:
    return _ACTIVE_QUERY_BUDGET.get()


class _QueryBudgetContext:
    def __init__(
        self,
        *,
        workload: str,
        limits: BudgetLimits,
        alert_sink: Callable[[QuerySLOAlert], object] | None,
        observer: QuerySLOObserver | None,
        enforce: bool,
    ) -> None:
        self.state = QueryBudgetState(
            workload=_workload(workload),
            limits=limits,
            alert_sink=alert_sink,
            observer=observer,
        )
        self.enforce = enforce
        self._token: Token[QueryBudgetState | None] | None = None

    def __enter__(self) -> QueryBudgetState:
        if self._token is not None:
            raise RuntimeError("query budget contexts cannot be re-entered")
        self._token = _ACTIVE_QUERY_BUDGET.set(self.state)
        return self.state

    def __exit__(self, exc_type, exc, traceback) -> bool:
        token = self._token
        if token is None:
            raise RuntimeError("query budget context was not entered")
        self._token = None
        _ACTIVE_QUERY_BUDGET.reset(token)
        if exc_type is None and self.enforce and self.state.alerts:
            raise QueryBudgetViolation(tuple(self.state.alerts))
        return False


def query_budget(
    workload: str,
    *,
    limits: BudgetLimits | None = None,
    alert_sink: Callable[[QuerySLOAlert], object] | None = None,
    observer: QuerySLOObserver | None = None,
    enforce: bool = False,
) -> _QueryBudgetContext:
    """Create a context-local SQL query budget.

    Budgets observe by default.  ``enforce=True`` raises only after the request
    body completes, and never masks an exception already raised by application
    code.
    """

    return _QueryBudgetContext(
        workload=workload,
        limits=limits or BudgetLimits(),
        alert_sink=alert_sink,
        observer=observer,
        enforce=enforce,
    )


@dataclass
class RequestBudgetState:
    workload: str
    query: QueryBudgetState
    duration_seconds: float = 0.0
    alerts: list[QuerySLOAlert] = field(default_factory=list)


class _RequestBudgetContext:
    def __init__(
        self,
        *,
        workload: str,
        max_request_seconds: float,
        query_limits: BudgetLimits,
        alert_sink: Callable[[QuerySLOAlert], object] | None,
        observer: QuerySLOObserver | None,
        enforce: bool,
        clock: Callable[[], float],
    ) -> None:
        self.workload = _workload(workload)
        self.max_request_seconds = float(max_request_seconds)
        if (
            not math.isfinite(self.max_request_seconds)
            or self.max_request_seconds < 0
        ):
            raise ValueError(
                "max_request_seconds must be finite and non-negative"
            )
        self.alert_sink = alert_sink
        self.observer = observer
        self.enforce = enforce
        self.clock = clock
        self._query_context = query_budget(
            self.workload,
            limits=query_limits,
            alert_sink=alert_sink,
            observer=observer,
            enforce=False,
        )
        self._started: float | None = None
        self.state: RequestBudgetState | None = None

    def __enter__(self) -> RequestBudgetState:
        self._started = self.clock()
        query = self._query_context.__enter__()
        self.state = RequestBudgetState(workload=self.workload, query=query)
        return self.state

    def __exit__(self, exc_type, exc, traceback) -> bool:
        assert self.state is not None and self._started is not None
        self._query_context.__exit__(exc_type, exc, traceback)
        self.state.duration_seconds = max(0.0, self.clock() - self._started)
        self.state.alerts.extend(self.state.query.alerts)
        if self.state.duration_seconds > self.max_request_seconds:
            alert = QuerySLOAlert(
                code="request_latency_exceeded",
                severity="warning",
                workload=self.workload,
                observed=self.state.duration_seconds,
                limit=self.max_request_seconds,
                query_count=self.state.query.query_count,
                statement_fingerprint=None,
                operation=None,
                safe_message=(
                    "request SLO threshold exceeded "
                    "(code=request_latency_exceeded)"
                ),
            )
            self.state.alerts.append(alert)
            _safe_observer_call(
                self.observer,
                "record_query_budget_exceeded",
                workload=self.workload,
                reason="request_latency",
            )
            if self.alert_sink is not None:
                try:
                    self.alert_sink(alert)
                except Exception:
                    pass
        if exc_type is None and self.enforce and self.state.alerts:
            raise QueryBudgetViolation(tuple(self.state.alerts))
        return False


def request_budget(
    workload: str,
    *,
    max_request_seconds: float,
    query_limits: BudgetLimits | None = None,
    alert_sink: Callable[[QuerySLOAlert], object] | None = None,
    observer: QuerySLOObserver | None = None,
    enforce: bool = False,
    clock: Callable[[], float] = monotonic,
) -> _RequestBudgetContext:
    return _RequestBudgetContext(
        workload=workload,
        max_request_seconds=max_request_seconds,
        query_limits=query_limits or BudgetLimits(),
        alert_sink=alert_sink,
        observer=observer,
        enforce=enforce,
        clock=clock,
    )


_START_ATTRIBUTE = "_creative_hub_query_slo_started"
_FINISHED_ATTRIBUTE = "_creative_hub_query_slo_finished"
_HOOKS: WeakKeyDictionary[Engine, SQLAlchemyQuerySLOHandle] = (
    WeakKeyDictionary()
)
_HOOKS_LOCK = RLock()


class SQLAlchemyQuerySLOHandle:
    def __init__(
        self,
        engine: Engine,
        *,
        observer: QuerySLOObserver | None,
        clock: Callable[[], float],
    ) -> None:
        self.engine = engine
        self.observer = observer
        self.clock = clock
        self._removed = False

    def before_cursor_execute(
        self,
        conn,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ) -> None:
        setattr(context, _START_ATTRIBUTE, self.clock())
        setattr(context, _FINISHED_ATTRIBUTE, False)

    def _finish(
        self,
        *,
        context,
        statement: object,
        outcome: str,
    ) -> None:
        if context is None or getattr(context, _FINISHED_ATTRIBUTE, False):
            return
        started = getattr(context, _START_ATTRIBUTE, None)
        if started is None:
            return
        setattr(context, _FINISHED_ATTRIBUTE, True)
        duration = max(0.0, self.clock() - float(started))
        operation = _statement_operation(statement)
        budget = active_query_budget()
        if budget is not None:
            budget.record_query(
                statement=statement,
                operation=operation,
                outcome=outcome,
                duration_seconds=duration,
            )
        observers = []
        if self.observer is not None:
            observers.append(self.observer)
        if budget is not None and budget.observer is not None:
            if all(budget.observer is not item for item in observers):
                observers.append(budget.observer)
        for observer in observers:
            _safe_observer_call(
                observer,
                "record_query",
                operation=operation,
                outcome=outcome,
                duration_seconds=duration,
            )

    def after_cursor_execute(
        self,
        conn,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ) -> None:
        self._finish(
            context=context,
            statement=statement,
            outcome="success",
        )

    def handle_error(self, exception_context):
        context = exception_context.execution_context
        statement = getattr(context, "statement", None)
        self._finish(context=context, statement=statement, outcome="error")
        return None

    def remove(self) -> None:
        with _HOOKS_LOCK:
            if self._removed:
                return
            event.remove(
                self.engine,
                "before_cursor_execute",
                self.before_cursor_execute,
            )
            event.remove(
                self.engine,
                "after_cursor_execute",
                self.after_cursor_execute,
            )
            event.remove(self.engine, "handle_error", self.handle_error)
            self._removed = True
            if _HOOKS.get(self.engine) is self:
                del _HOOKS[self.engine]


def install_sqlalchemy_query_slo(
    engine: Engine,
    *,
    observer: QuerySLOObserver | None = None,
    clock: Callable[[], float] = monotonic,
) -> SQLAlchemyQuerySLOHandle:
    """Install one idempotent listener set on a SQLAlchemy engine."""

    with _HOOKS_LOCK:
        existing = _HOOKS.get(engine)
        if existing is not None:
            return existing
        handle = SQLAlchemyQuerySLOHandle(
            engine,
            observer=observer,
            clock=clock,
        )
        event.listen(
            engine,
            "before_cursor_execute",
            handle.before_cursor_execute,
        )
        event.listen(
            engine,
            "after_cursor_execute",
            handle.after_cursor_execute,
        )
        event.listen(engine, "handle_error", handle.handle_error)
        _HOOKS[engine] = handle
        return handle
