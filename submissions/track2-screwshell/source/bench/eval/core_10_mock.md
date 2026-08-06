# Eval Report — core_10_mock

- started : 2026-08-02T23:54:17
- engine  : mock   git_sha: 0c79a1c8c604786e54241f3ab73836bda1208c80
- cases   : 10   ok: 10   failed: 0   wall: 0.838s

## Scores (mean over applicable cases)

| scorer | mean | applied |
| --- | --- | --- |
| citation_accuracy | 0.0 | 10 |
| citation_coverage | 1.0 | 7 |
| keyword_recall | 1.0 | 2 |
| leak_penalty | 1.0 | 1 |
| rag_recall_at_k | 1.0 | 1 |
| routing_accuracy | 1.0 | 10 |
| latency_score | 0.0 | 0 |
| status_match | 1.0 | 10 |
| **overall** | **0.8571** | |

## Per-case

- [ok] `C01_doc_rocm` status=ok 0.045s skills=doc
- [ok] `C02_code_orchestrator` status=ok 0.04s skills=code
- [ok] `C03_security_blueprint` status=ok 0.041s skills=security
- [ok] `C04_tool_search` status=ok 0.037s skills=tool
- [ok] `C05_agent_compare` status=ok 0.041s skills=agent,doc
- [ok] `C06_code_router_guard` status=ok 0.039s skills=code
- [ok] `C07_security_leak` status=ok 0.038s skills=security
- [ok] `C08_rag_bench` status=ok 0.041s skills=doc
- [ok] `C09_code_eval_aggregate` status=ok 0.037s skills=code
- [ok] `C10_doc_blueprint_mol` status=ok 0.038s skills=doc

## LLM accounting

- calls=42 prompt=9788tok new=639tok cached=2918tok
- kv_hit_rate=0.2981 timings_coverage=1.0
- latency : p50=8.8185s p95=12.1036s mean=9.3278s total=93.278s