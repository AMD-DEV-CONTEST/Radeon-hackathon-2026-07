# Test Report

Test date: 2026-08-03 (UTC+8)
Local candidate: `ui/aug2-e2e@5cd5ba3`
Radeon performance evidence source: `0ce3564`

## 1. Summary

| Category | Result | Decision |
|---|---|---|
| Unit/integration/functional | `164 passed, 1 skipped` | PASS |
| Ruff | `app tests benchmarks experiments scripts` | PASS |
| mypy application layer | 82 source files | PASS |
| Golden E2E mock | 6.167 s; 0 failures; `pass_with_warnings` | PASS |
| Fresh install mock | Python 3.12; UI HTTP 200; Golden 4.609 s, 0 failures | PASS |
| Radeon local-vLLM Golden | 61.951 s; 0 failures; loopback endpoint/UI | PASS |
| AMD concurrency | 1/2/4: 20/20 each; Verifier 100%; OOM 0 | PASS |
| 30-minute stability | 298/298; OOM 0; services/SQLite stable | PASS |
| Security scan | public endpoint matches 0; localhost verified | PASS |
| Privacy scan | unredacted real-name/phone/ID matches 0 | PASS |

## 2. Unit and Functional Tests

Coverage includes Case Workspace, Evidence Graph, document/image/video
parsing, Fact extraction, local endpoint policy, RAG corpus/index/retrieval,
dynamic memory and ProtectedField, deterministic dates and deadlines, rule
versions, vehicle classification, liability, Verifier, UI view models, report
export, compact diagnostic rendering, fresh fixture session state, AMD
benchmark tools, and experiment evaluators.

Final local release-candidate rerun:

```text
164 passed, 1 skipped, 2 warnings in 64.22s
```

The warnings are the LangChain Pydantic V1 compatibility warning on Python
3.14 and a FastAPI TestClient deprecation warning. The supported release range
is Python 3.10-3.13; Radeon uses Python 3.10.12.

## 3. Integration Tests

Integration coverage includes:

1. Evidence Graph -> Legal RAG -> Vehicle Nature -> Liability;
2. Rights Workflow -> Verifier -> Policy Gate -> Human Approval;
3. SQLite checkpoint interruption and resume;
4. preservation and targeted retry after model, JSON/schema, document, or
   video failure;
5. UI services reading the same CaseState instead of duplicating business
   rules;
6. Fact/Evidence/Law traceability and draft status in exported reports.

## 4. End-to-End Tests

Mock E2E commands:

```bash
bash scripts/doctor.sh --mode mock --prepare
.venv/bin/python scripts/run_golden_e2e.py --mode mock
```

The existing development runtime completed in 6.167 seconds with 0 failures,
one warning, document `draft`, approval `pending`, Policy Gate
`pass_with_warnings`, and checkpoint cache hit. Mock E2E proves workflow, data,
and UI behavior; it does not prove Radeon model speed or accident-recognition
accuracy.

REL-02 was also executed in a new Python 3.12.13 virtual environment with empty
case, index, and checkpoint directories. The launcher built a local
SQLite/Qdrant index from 15 legal documents and 59 audited excerpts; UI returned
HTTP 200. The clean Golden fixture contains 12 sources, 18 facts, three timeline
events, and nine valid PDFs. Golden completed in 4.609 seconds with 0 failures,
one warning, and generated Markdown/HTML reports.

On Radeon Cloud, the real `local_vllm` Golden Case used the same clean fixture
and completed in 61.951 seconds with 0 failures and one warning. The document
remained `draft`, approval remained `pending`, and the Policy Gate returned
`pass_with_warnings`. Vehicle, Liability, Rights, and Verifier node times were
18.361, 15.942, 13.516, and 4.997 seconds. The UI and `/v1/models` returned HTTP
200, with vLLM and UI bound only to `127.0.0.1:8000` and
`127.0.0.1:7860`.

## 5. Performance Tests

The fair comparison keeps GPU, model, case, request, temperature, and output
limit constant:

- input tokens: 11,808 -> 5,795 (-50.9%);
- TTFT p50: 9.003 s -> 0.113 s (-98.8%);
- latency p95: 23.407 s -> 15.228 s;
- output throughput: 15.417 -> 25.689 tok/s;
- peak VRAM: 44,246 -> 43,984 MB;
- ProtectedField: 100% -> 100%;
- success: 100%, OOM 0.

Full-semantic concurrency results:

| Concurrency | Requests | Success | TTFT p50/p95 | Throughput | Verifier | OOM |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 20 | 20 | 0.111/0.112 s | 25.667 tok/s | 100% | 0 |
| 2 | 20 | 20 | 0.113/0.116 s | 49.323 tok/s | 100% | 0 |
| 4 | 20 | 20 | 0.120/0.121 s | 89.478 tok/s | 100% | 0 |

## 6. Stability Test

Final configuration: 0.95 GPU memory utilization, 8,192 batch tokens, 16K
context, Prefix Cache enabled.

- duration: 1,809.493 seconds;
- requests: 298/298, OOM 0;
- unchanged vLLM PID;
- UI/API HTTP 200 before and after;
- SQLite `quick_check=ok` before and after;
- mean GPU utilization: 99.626%;
- peak VRAM: 46,744 MB;
- peak power: 224 W; peak hotspot: 61 C.

The stability runner uses a fixed short output and does not contain the full
business ID list. Its `verifier_pass_rate=0` is not a business-quality claim;
business quality is demonstrated by the full semantic concurrency test.

## 7. Security Tests

- SEC-01: public model endpoint/API-key pattern matches 0;
- SEC-02: real requests use loopback and vLLM listens on 127.0.0.1:8000;
- SEC-03: unredacted real-name, telephone, and identity-card matches 0;
- local-only unit tests reject non-loopback hosts, wrong ports, credentials,
  query strings, fragments, and invalid paths.

## 8. Static Analysis and Known Warning

Ruff passes the full selected scope. `mypy app` passes all 82 application source
files. The extended `mypy app benchmarks experiments` run has one pre-existing
type-inference warning at `benchmarks/legal_retrieval.py:116` (`float <=
object`). Runtime tests and benchmarks pass; the frozen release does not change
this non-blocking benchmark annotation.

## 9. Evidence Index

- `benchmarks/results/baseline/baseline.json`
- `benchmarks/results/optimized/optimized.json`
- `benchmarks/results/concurrency/amd_concurrency_results.json`
- `benchmarks/results/stability/stability_report.json`
- `benchmarks/results/security/security_checks.json`
- `experiments/results/execution_report.json`
- `docs/ui_e2e_execution_report.md`
- `release_check/fresh_install_test.md`
