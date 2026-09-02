# Product Specification — Phase J runtime queue integration

| Field | Value |
|---|---|
| Spec ID | `phase-j-queue-runtime-260723-1100` |
| Level | S2 |
| Date | 2026-07-23 |
| Status | implemented |

## Objective

Apply Phase J concurrency limits to real Office Agent model operations instead of monitoring an unused queue.

## User-visible behaviour

- A project report's LLM explanation requests are limited by the global and per-project LLM quotas.
- RAG indexing and query embedding requests are limited by the embedding quotas.
- Queue status reflects these real model operations and releases slots after success, cancellation, timeout, or error.
- Different background-run worker threads share the same quota.

## Non-goals

- This change does not claim a measured AMD throughput improvement; cloud ROCm validation remains required.
