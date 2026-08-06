# NexusAI AMD Radeon GPU Compute v0.8.0
NexusAI now has an EmbeddingProvider abstraction with a local CPU fallback and an AMD ROCm dense-embedding provider.

## Provider selection
`NEXUS_EMBEDDING_PROVIDER=auto` uses ROCm when detected, otherwise local.
`local` forces CPU. `rocm` requires the Radeon provider.

## Endpoints
- GET `/api/compute/health`
- GET `/api/worlds/{world_id}/dense-search?q=...&top_k=5`

## Benchmark
`python scripts/benchmark_embeddings.py`

Output: `benchmarks/radeon_embedding_benchmark.json`

The CPU baseline and GPU dense model use different embedding algorithms. Throughput is an execution benchmark; retrieval quality should be evaluated separately.
