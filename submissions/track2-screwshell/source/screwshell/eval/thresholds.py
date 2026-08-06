"""Quality bars for the evaluation gate -- the single source of truth.

Duplicating any of these numbers into a script or a doc is how a gate quietly
starts enforcing two different standards. Import from here.

`regression_tolerance` is deliberately loose (5%): a local 27B Q4 model has
real run-to-run variance, and a gate that cries wolf every morning gets
switched off within a week. Tighten it only together with `repeats >= 2`.
"""
from __future__ import annotations

from typing import Mapping

THRESHOLDS: dict[str, float] = {
    "citation_accuracy": 0.90,
    "citation_coverage": 0.70,
    "keyword_recall": 0.70,
    "leak_penalty": 1.00,        # any leak at all fails the gate
    "rag_recall_at_k": 0.60,
    "routing_accuracy": 0.80,
    "status_match": 1.00,
    "latency_score": 0.70,
    "json_ok_rate": 0.95,
    "p95_seconds": 300.0,
    "regression_tolerance": 0.05,
}

#: Metrics where a SMALLER number is better. Everything else is treated as
#: higher-is-better by the threshold check and by `report.compare()`.
LOWER_IS_BETTER: frozenset[str] = frozenset({
    "p95_seconds", "p50_seconds", "mean_seconds", "total_seconds",
    "prompt_tokens", "new_tokens", "calls", "unaccounted_s",
})


def is_lower_better(metric: str) -> bool:
    """True when a decrease in `metric` is an improvement."""
    tail = metric.rsplit(".", 1)[-1]
    return tail in LOWER_IS_BETTER


def threshold_for(metric: str) -> float | None:
    """The bar for `metric`, or None when the metric is merely observed."""
    return THRESHOLDS.get(metric.rsplit(".", 1)[-1])


def meets(metric: str, value: float) -> bool | None:
    """Does `value` clear the bar? None when there is no bar for `metric`."""
    bar = threshold_for(metric)
    if bar is None:
        return None
    return value <= bar if is_lower_better(metric) else value >= bar


def check_bars(aggregate: Mapping) -> dict:
    """Evaluate the *measurable* THRESHOLD bars against an ``aggregate()`` dict.

    Only the LLM latency / token metrics are gated here, because a run always
    produces them (every run has an LLM clock). The quality scorers that depend
    on the not-yet-built T4 citation validator (``citation_accuracy``) cannot be
    measured yet, so they are gated via regression (``report.compare``) rather
    than an absolute bar until the validator lands -- enforcing a bar we can
    never satisfy would just force the gate to be switched off.

    Returns ``{metric: {"value", "bar", "meets": False, "lower_is_better"}}``
    for every metric that (a) has a declared bar in ``THRESHOLDS`` and (b) is
    present in ``aggregate["llm"]`` and (c) does NOT clear it. A metric that is
    simply absent is skipped: unmeasured is not the same as failed.

    The caller fails the gate (``sys.exit(1)`` in ``bench/eval_e2e.py``) when
    the returned dict is non-empty.
    """
    llm = (aggregate.get("llm") or {}) if isinstance(aggregate, Mapping) else {}
    failed: dict = {}
    for metric, value in llm.items():
        if value is None:
            continue
        bar = threshold_for(metric)
        if bar is None:
            continue
        if not meets(metric, value):
            failed[metric] = {
                "value": value,
                "bar": bar,
                "meets": False,
                "lower_is_better": is_lower_better(metric),
            }
    return failed
