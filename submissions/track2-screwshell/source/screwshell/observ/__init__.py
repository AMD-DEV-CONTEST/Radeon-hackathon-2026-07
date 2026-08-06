"""ScrewShell observability layer (Layer2 Phase 1).

A thread-safe ``RequestEvent`` store that lands one record per relay-served
inference request into JSONL + SQLite, and a read API the Gradio panel polls.

Two-tier granularity (2026-08-05, session-scoped observability):
  * ``request_id``  -- one per HTTP request (single call).
  * ``operational_session_id`` -- a "cache-reuse segment": one id spans the
    multiple requests that share a warm KV prefix. Assigned by the
    ``InferenceCoordinator`` under its serial lock (single writer) using a
    controlled boundary signal (``no_reusable_prefix`` / ``explicit_reset`` /
    ``model_reload`` / ``first``).
  * ``run_id`` (= ``ui_conversation_id``) -- the browser/UI conversation
    identity, kept SEPARATE from the operational session so neither dimension
    is lost.

Health judgment is SESSION-SCOPED and percentile-based (TTFT p50/p95/p99), NOT
a global arithmetic mean. ``/v1/observ/summary`` accepts optional
``session_id`` / ``run_id`` / ``window_s`` / ``exclude_benchmark`` filters; the
UI polls the current operational session with ``exclude_benchmark=true`` so a
historical stress run (e.g. an August-4 50k-token outlier) can no longer pin
the health banner red. Benchmark traffic is tagged via ``X-Benchmark: 1`` and
excluded from interactive health.

Design constraints (Layer2_Implementation_Map.md §2/§5 Phase 1):
  * v1 reuses llama.cpp native ``timings`` + the existing ``core/metrics``
    field vocabulary. NO OpenLIT / OTel / Grafana.
  * The relay's ``InferenceCoordinator`` is the ONLY emitter -- ``RunMetrics``
    stays the single-run, non-thread-safe accumulator and is never used as a
    shared metric store (map §6.8).
  * Never fabricate a measurement (blueprint §6.2 rule 9): when the upstream
    does not send ``timings``, the prefill/decode/KV fields stay ``None``
    rather than being back-filled with wall-clock guesses. ``low_confidence``
    (too-few-sample window) is reported instead of a fake p99.
"""
from .event import RequestEvent
from .store import (
    ObservStore,
    get_store,
    record_event,
    recent_events,
    recent_events_filtered,
    record_gpu_sample,
    recent_gpu,
    summarize,
)

__all__ = [
    "RequestEvent",
    "ObservStore",
    "get_store",
    "record_event",
    "recent_events",
    "recent_events_filtered",
    "record_gpu_sample",
    "recent_gpu",
    "summarize",
]
