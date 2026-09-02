# Phase J — Technical Design

- Level: S3
- Status: implemented

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      FastAPI Application                      │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  /monitor/*  │  │  /admin/*    │  │  Core Routers    │   │
│  │  health      │  │  backup      │  │  projects/files  │   │
│  │  queue       │  │  restore     │  │  runs/tasks      │   │
│  │  cache       │  │  logs        │  │  ...             │   │
│  │  benchmark   │  │  stress-test │  │                  │   │
│  │  gpu         │  │              │  │                  │   │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘   │
│         │                 │                    │             │
│  ┌──────┴─────────────────┴────────────────────┴─────────┐  │
│  │                   Service Layer                         │  │
│  │                                                        │  │
│  │  TaskQueue     TTLCache     HealthMonitor              │  │
│  │  (quotas)      (invalidate) (gpu/disk/llm)             │  │
│  │                                                        │  │
│  │  BenchmarkCollector   BackupService   LogRotation      │  │
│  │  (snapshots/compare)  (backup/restore) (rotate/clean)  │  │
│  │                                                        │  │
│  │  EmbeddingClient     StressTestRunner                  │  │
│  │  (separate endpoint) (large/batch/context/multi)       │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

## Component Registry

| Component | File | Purpose |
|-----------|------|---------|
| `TaskQueue` | `app/services/task_queue.py` | Global + per-project semaphore gating |
| `EmbeddingClient` | `app/llm/embedding_client.py` | Dedicated embedding model endpoint |
| `TTLCache` | `app/services/cache.py` | TTL cache with prefix invalidation |
| `HealthMonitor` | `app/services/monitor.py` | GPU/model/disk metrics collection |
| `BenchmarkCollector` | `app/services/benchmark.py` | Snapshot capture and comparison |
| `BackupService` | `app/services/backup.py` | DB + vector + config backup/restore |
| `LogRotationService` | `app/services/log_rotation.py` | Size-based log rotation |
| `StressTestRunner` | `app/services/stress_test.py` | 4-phase stress orchestration |

## Data Flow

### Concurrency Control
```
Request → TaskQueue.enqueue_llm(project_id) →
  Acquire per-project semaphore →
    Acquire global semaphore →
      Execute LLM call →
    Release global →
  Release per-project →
Return result
```

### Cache Flow
```
API Request → Check cache by key →
  HIT: return cached value (update LRU)
  MISS: compute → store in cache with TTL → return value
```

### Health Check Flow
```
GET /monitor/health →
  HealthMonitor.health_check() →
    collect_gpu_metrics() → rocm-smi / nvidia-smi
    collect_system_metrics() → shutil.disk_usage()
    check LLM error rate
    check LLM endpoint reachability →
  Queue status + Cache stats →
Assemble response with status (healthy/degraded/critical)
```

## Concurrency Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `global_max_concurrent_llm_calls` | 4 | Max simultaneous LLM calls across all projects |
| `per_project_max_concurrent_llm_calls` | 2 | Max per-project LLM calls |
| `global_max_concurrent_embedding_calls` | 8 | Max simultaneous embedding calls |
| `per_project_max_concurrent_embedding_calls` | 4 | Max per-project embedding calls |
| `llm_call_queue_timeout_seconds` | 120 | Queue wait timeout for LLM |
| `embedding_call_queue_timeout_seconds` | 60 | Queue wait timeout for embedding |

## Cache TTL Strategy

| Category | TTL | Rationale |
|----------|-----|-----------|
| Index | 3600s (1h) | Index changes only on file add/remove |
| Embedding | 1800s (30m) | Embeddings cache per content hash |
| Report | 900s (15m) | Reports should reflect recent state |

## Backup Components

1. **SQLite database** — `projectpack.db`
2. **Vector database** — FAISS index directory
3. **Project configurations** — `.json`, `.yaml`, `.yml`, `.toml` files

## Monitoring Metrics

### GPU (via rocm-smi / nvidia-smi)
- `vram_total_mb`, `vram_used_mb`, `vram_free_mb`
- `utilization_pct`, `temperature_c`

### Model Metadata
- `model_name`, `quantization`, `backend`
- `context_size`, `gpu_layers`, `llama_cpp_version`

### LLM Latency (EMA)
- `first_token_latency_ms`
- `generation_tokens_per_second`
- `end_to_end_latency_ms`

### Embedding
- `embedding_throughput_texts_per_second`

### System
- `disk_total_gb`, `disk_used_gb`, `disk_free_gb`, `disk_used_pct`
