#!/usr/bin/env python3
"""determinex_otel.py — OpenTelemetry instrumentation for Determinex.

Provides:
- Tracer for spans across eval phases (compile, test, score)
- Metrics emitter for eval durations, scores
- Auto-export to OTLP endpoint (Grafana Tempo / Jaeger)

Usage in other scripts:
    from determinex_otel import tracer, eval_span

    with eval_span(instance_id="cheat", iteration=22) as span:
        span.set_attribute("test_count", 307)
        # ... do work ...
        span.set_attribute("passed", 49)
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager

OTLP_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "determinex")


def _setup():
    """Lazy setup — only imports OpenTelemetry if a script calls into instrumentation."""
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        sys.stderr.write("OpenTelemetry not installed; tracing disabled\n")
        sys.stderr.write("  pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc\n")
        return None

    resource = Resource(attributes={"service.name": SERVICE_NAME})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=OTLP_ENDPOINT, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return trace.get_tracer(__name__)


_tracer = None


def get_tracer():
    global _tracer
    if _tracer is None:
        _tracer = _setup()
    return _tracer


@contextmanager
def eval_span(instance_id: str, iteration: int | None = None, **attrs):
    tracer = get_tracer()
    if tracer is None:
        # No-op span
        class _Null:
            def set_attribute(self, *a, **k):
                pass

            def add_event(self, *a, **k):
                pass

        yield _Null()
        return

    with tracer.start_as_current_span(f"eval.{instance_id}") as span:
        span.set_attribute("instance_id", instance_id)
        if iteration is not None:
            span.set_attribute("iteration", iteration)
        for k, v in attrs.items():
            span.set_attribute(k, v)
        yield span


@contextmanager
def phase_span(phase: str, **attrs):
    """Use for sub-phases: 'compile', 'pytest', 'score-parse', etc."""
    tracer = get_tracer()
    if tracer is None:

        class _Null:
            def set_attribute(self, *a, **k):
                pass

            def add_event(self, *a, **k):
                pass

        yield _Null()
        return
    with tracer.start_as_current_span(f"phase.{phase}") as span:
        for k, v in attrs.items():
            span.set_attribute(k, v)
        yield span


if __name__ == "__main__":
    # Smoke test
    tracer = get_tracer()
    print(f"tracer={tracer}, endpoint={OTLP_ENDPOINT}")
    with eval_span("smoke_test", iteration=99, lang="rust") as span:
        span.set_attribute("test_count", 1)
        with phase_span("compile"):
            pass
        with phase_span("pytest"):
            span.set_attribute("passed", 1)
    print("OK — span emitted (visible in Grafana Tempo if running)")
