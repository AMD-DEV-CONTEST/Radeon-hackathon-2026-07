"""Design §16.2 throughput targets — exported as constants so the Cortex Console
can render target lines on the bench bar charts without hardcoding numbers."""

EMBEDS_PER_SEC_RADEON_TARGET = 350
EMBEDS_PER_SEC_CPU_TARGET = 30
QUERIES_PER_SEC_RADEON_TARGET = 50
BROKER_FANOUT_PER_SEC_TARGET = 1000

BENCH_TICK_INTERVAL_SEC = 2.0
BENCH_QUERY_COUNT = 10
BENCH_EMBED_BATCH = 16
