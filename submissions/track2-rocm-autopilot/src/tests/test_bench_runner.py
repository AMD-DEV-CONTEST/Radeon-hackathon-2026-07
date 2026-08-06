import pytest

from autopilot.bench_runner import parse_bench_output

SAMPLE = """
============ Serving Benchmark Result ============
Successful requests:                     30
Benchmark duration (s):                  84.31
Total input tokens:                      14520
Total generated tokens:                  15360
Request throughput (req/s):              0.36
Output token throughput (tok/s):         182.19
Total Token throughput (tok/s):          354.41
---------------Time to First Token----------------
Mean TTFT (ms):                          311.45
Median TTFT (ms):                        289.12
P99 TTFT (ms):                           612.33
-----Time per Output Token (excl. 1st token)------
Mean TPOT (ms):                          41.02
---------------Inter-token Latency----------------
Mean ITL (ms):                           40.88
==================================================
"""


def test_parse_extracts_metrics():
    m = parse_bench_output(SAMPLE)
    assert m["tokens_per_s"] == 182.19
    assert m["ttft_ms"] == 311.45
    assert m["itl_ms"] == 40.88
    assert m["total_output_tokens"] == 15360


def test_parse_raises_on_garbage():
    with pytest.raises(ValueError):
        parse_bench_output("no metrics here")
