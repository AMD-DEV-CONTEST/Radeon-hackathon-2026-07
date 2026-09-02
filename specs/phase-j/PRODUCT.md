# Stage J — Production & AMD Radeon Optimization

## Acceptance Goals

| ID  | Goal | Criterion | Measurement |
|-----|------|-----------|-------------|
| J-1 | Task concurrency under control | Per-project quotas never exceeded | `monitor/queue` endpoint shows active ≤ capacity |
| J-2 | Queue timeout gates calls | Task waits timeout after configured seconds | Queue stats show timeouts when saturated |
| J-3 | Cancellation propagated | Cancelled project run releases queue slots | `active_calls` decrement verified |
| J-4 | Embedding model isolated | Embedding calls to separate endpoint | `/v1/embeddings` hits embedding_base_url |
| J-5 | Smaller model for embedding | bge-small-en-v1.5 or equivalent | Model metadata confirms small footprint |
| J-6 | Cache accelerates repeat reads | Hit rate > 50 % under normal load | `monitor/cache` shows hit rate |
| J-7 | Cache invalidated on change | Stale entries removed by prefix | `monitor/cache/invalidate` removes matching keys |
| J-8 | Stress large files succeed | 10 MB file imported without error | Stress test phase passes |
| J-9 | Batch concurrency works | 20 files processed in parallel stage | Batch test phase passes |
| J-10 | Long context tolerated | 4000-token prompt yields response | Context test phase passes |
| J-11 | Multi-project concurrent | 4 projects × 10 requests process | Multi-project phase passes |
| J-12 | GPU metadata collected | rocm-smi / nvidia-smi parsed | `monitor/gpu` returns device list |
| J-13 | Model metadata registered | quantization, backend, version | `monitor/health` includes `model_metadata` |
| J-14 | Latency recorded | first-token, tok/s, total tracked | EMA metrics in `HealthMonitor` |
| J-15 | Baseline vs optimized compared | Clear delta table | `monitor/benchmark/compare` shows pct improvements |
| J-16 | Backup creates snapshot | DB + vector + config backed up | `admin/backup` POST returns manifest |
| J-17 | Restore recovers state | DB + vector restored | `admin/backup/restore` restores files |
| J-18 | Log rotation on size | File rotated when > max_size_mb | Rotated file appears, new file started |
| J-19 | Health endpoint reports | GPU, disk, LLM errors aggregated | `monitor/health` returns status |
| J-20 | Alert on thresholds | degraded / critical status emitted | Status changes when thresholds crossed |
| J-21 | Old backups pruned | Rotation enforces retention_days | Cleanup removes expired backups |
| J-22 | Old logs pruned | Retention enforces log_retention_days | Cleanup removes old compressed logs |
