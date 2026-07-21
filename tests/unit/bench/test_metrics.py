from datetime import UTC, datetime

from cortex.bench.metrics import BenchMetrics, to_dict, to_envelope
from cortex.core.envelope import EnvelopeType


def _sample():
    return BenchMetrics(
        node="did:percq:org:soc-alpha",
        embeds_per_sec_radeon=142.3,
        embeds_per_sec_cpu=18.6,
        queries_per_sec_radeon=23.1,
        queries_per_sec_cpu=2.7,
        gpu_mem_util_pct=86.0,
        p95_query_latency_ms=42.0,
        ts=datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC),
    )


def test_to_dict_matches_design_5_8_exactly():
    d = to_dict(_sample())
    assert list(d.keys()) == [
        "node",
        "embeds_per_sec_radeon",
        "embeds_per_sec_cpu",
        "queries_per_sec_radeon",
        "queries_per_sec_cpu",
        "gpu_mem_util_pct",
        "p95_query_latency_ms",
    ]
    assert d["node"] == "did:percq:org:soc-alpha"
    assert d["embeds_per_sec_radeon"] == 142.3
    assert d["embeds_per_sec_cpu"] == 18.6
    assert d["queries_per_sec_radeon"] == 23.1
    assert d["queries_per_sec_cpu"] == 2.7
    assert d["gpu_mem_util_pct"] == 86.0
    assert d["p95_query_latency_ms"] == 42.0


def test_to_envelope_uses_metrics_type_and_bench_src():
    m = _sample()
    env = to_envelope(m)
    assert env.type == EnvelopeType.METRICS
    assert env.src == "did:percq:org:soc-alpha"
    assert env.dst == "*"
    assert env.ts == m.ts
    assert env.payload == to_dict(m)
