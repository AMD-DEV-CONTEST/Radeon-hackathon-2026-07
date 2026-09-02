# Phase J — Verification Report

## Environment

| Item | Value |
|------|-------|
| Python | 3.12+ |
| Required Dependencies | httpx, fastapi, pydantic-settings |
| GPU Backend | ROCm (rocm-smi) / CUDA (nvidia-smi) / CPU fallback |
| Test Framework | pytest + pytest-asyncio |

## Verification Checklist

### J-1: Concurrency Control

```
$ curl http://127.0.0.1:8000/monitor/queue
```

- [ ] `active_llm_calls ≤ global_llm_capacity`
- [ ] `active_embedding_calls ≤ global_embedding_capacity`
- [ ] Queued calls increment when saturated

### J-2: Queue Timeout

- [ ] After timeout_seconds, call raises RuntimeError
- [ ] Queue stats show `total_timeouts` increment

### J-3: Cancellation

- [ ] Cancel event releases both semaphores
- [ ] Stats reflect `total_cancelled`

### J-4: Separate Embedding Model

```
$ curl http://127.0.0.1:8000/v1/embeddings   # hits embedding_base_url
```

- [ ] Embedding calls go to dedicated embedding endpoint
- [ ] Embedding `model` parameter is `bge-small-en-v1.5` or configured value

### J-5: Embedding Model Footprint

- [ ] `embedding_base_url` configured separately from `llm_base_url`
- [ ] Embedding model smaller than chat model (bge-small ~100MB vs 35B chat)

### J-6: Cache Hit Rate

```
$ curl http://127.0.0.1:8000/monitor/cache
```

- [ ] `hit_rate > 0` after repeated reads
- [ ] `size ≤ max_entries`

### J-7: Cache Invalidation

```
$ curl -X POST http://127.0.0.1:8000/monitor/cache/invalidate \
  -d '{"project_id": "demo"}'
```

- [ ] Returns `removed` count > 0 when entries exist
- [ ] Subsequent `GET /monitor/cache` shows reduced size

### J-8: Large File Stress

- [ ] Stress test runner processes large_file_size_mb without error
- [ ] Phase result shows `failed == 0`

### J-9: Batch File Stress

- [ ] Batch phase processes batch_file_count files concurrently
- [ ] Phase result shows `failed == 0`

### J-10: Long Context Stress

- [ ] LLM generates response for long_context_prompt_tokens
- [ ] No truncation or OOM errors

### J-11: Multi-Project Stress

- [ ] multi_project_count projects execute concurrently
- [ ] Per-project semaphore enforced

### J-12: GPU Metrics

```
$ curl http://127.0.0.1:8000/monitor/gpu
```

- [ ] Returns GPU device list with VRAM metrics
- [ ] Backend detected (rocm/cuda/cpu)

### J-13: Model Metadata

```
$ curl http://127.0.0.1:8000/monitor/health
```

- [ ] `model_metadata` includes quantization and backend
- [ ] `model_metadata.model_name` non-empty

### J-14: Latency Recording

- [ ] `HealthMonitor.record_llm_latency()` updates EMA values
- [ ] `record_embedding_latency()` updates throughput metric

### J-15: Benchmark Comparison

```
$ curl "http://127.0.0.1:8000/monitor/benchmark/compare?baseline=baseline&optimized=post-opt"
```

- [ ] Returns structured `first_token_latency`, `generation_speed`, etc.
- [ ] `improvement_pct` calculated correctly
- [ ] `hardware_info` shows device details

### J-16: Backup

```
$ curl -X POST http://127.0.0.1:8000/admin/backup -d '{"label": "test"}'
```

- [ ] Creates backup directory with timestamp
- [ ] Manifest contains files list
- [ ] Database, vector DB, and configs backed up

### J-17: Restore

```
$ curl -X POST http://127.0.0.1:8000/admin/backup/restore \
  -d '{"backup_dir": "...", "dry_run": true}'
```

- [ ] Dry run validates without writing
- [ ] Full restore copies all components

### J-18: Log Rotation

```
$ curl -X POST "http://127.0.0.1:8000/admin/logs/rotate?log_file=app.log"
```

- [ ] Rotates when file > log_max_size_mb
- [ ] Creates compressed archive

### J-19: Health Endpoint

```
$ curl http://127.0.0.1:8000/monitor/health
```

- [ ] Returns `status` (healthy/degraded/critical)
- [ ] Issues array populated when thresholds crossed
- [ ] All subsections populated (gpu, system, queue, cache)

### J-20: Alert Thresholds

- [ ] `degraded` when VRAM > warning threshold
- [ ] `critical` when VRAM > critical threshold
- [ ] Alert webhook triggered (if configured)

### J-21: Backup Cleanup

- [ ] Old backups removed when `backup_retention_days` exceeded
- [ ] Cleanup endpoint returns `removed` count

### J-22: Log Cleanup

- [ ] Old logs removed when `log_retention_days` exceeded
- [ ] Active log file preserved

## Unit Test Coverage

| Module | Test File | Test Count |
|--------|-----------|------------|
| `app/services/task_queue.py` | `tests/test_phase_j.py` | 6 |
| `app/llm/embedding_client.py` | `tests/test_phase_j.py` | 3 |
| `app/services/cache.py` | `tests/test_phase_j.py` | 7 |
| `app/services/monitor.py` | `tests/test_phase_j.py` | 4 |
| `app/services/benchmark.py` | `tests/test_phase_j.py` | 5 |
| `app/services/backup.py` | `tests/test_phase_j.py` | 4 |
| `app/services/log_rotation.py` | `tests/test_phase_j.py` | 3 |
| `app/services/stress_test.py` | `tests/test_phase_j.py` | 5 |

Total: 37 test cases
