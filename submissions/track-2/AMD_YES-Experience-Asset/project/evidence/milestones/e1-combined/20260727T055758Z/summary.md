# E1 combined gate — exact-current-commit W7900 terminal regression

Packet:
`e1-combined-w7900-terminal-regression-20260727T055758Z-de72a6c`

## Outcome

PR #12's corrected E1 boundary now passes on the exact clean implementation
commit `de72a6c959d10c03c8fff42bf3b788484f5064b5` on Radeon Cloud:

- the frozen Qwen2.5-14B-Instruct snapshot passed full SHA-256 verification;
- the BF16 model loaded through ROCm/vLLM on one Radeon PRO W7900-class
  device and served only on `127.0.0.1`;
- a native structured Tool Call parsed as an inert proposal;
- deterministic Runtime validation proved allow/effect/`SUCCEEDED` and
  deny/no-effect/`POLICY_BLOCKED` paths;
- the restart checkpoint remained readable and the canonical asset stayed
  unchanged; and
- 58/58 backend tests and Ruff passed in the separate persistent Agent
  environment.

The latest parser correction is part of the tested commit. Successful HTTP
responses containing invalid JSON or malformed vLLM shapes are normalized to
`InvalidModelOutput`, converted to durable `INVALID_MODEL_OUTPUT` terminal
results, and remain terminal after reopening SQLite.

Status is `FIX_AND_W7900_READY_REVIEW_PENDING`. This packet does not promote
T06, authorize E2, or claim a performance Baseline.

## Retained failure and recovery history

The first combined packet remains retained with its High quality-review
failure: model exceptions or a missing required Tool Call could leave a run
non-terminal. Commit `2deaad7` added explicit terminal checkpoints for
unavailable, timeout, invalid/empty and missing-tool outcomes; commit
`de72a6c` closed malformed successful-response parser leaks.

The initial model-snapshot check in this W7900 run also failed because one
undeclared partial temporary shard remained beside the complete declared
snapshot. The exact partial file was moved intact into persistent quarantine,
not deleted. Full SHA-256 verification then passed for all 19 declared files
before model load.

## Track 2 task-closure proof

The current run demonstrates this bounded loop:

1. load exact local model and durable state;
2. receive one structured model Tool Call proposal;
3. keep the proposal inert until Runtime allowlist, scope and permission
   checks;
4. execute and verify one allowed local effect;
5. deny the same class of effect without permission and prove no denied
   effect occurred;
6. persist explicit terminal results and a restart-readable checkpoint.

No model output grants its own permission. No private prompt or response was
retained, and no service was exposed beyond loopback.

## Reproduction results

| Gate | Result |
|---|---|
| Remote development environment | PASS |
| ROCm/HIP/PyTorch/vLLM platform | PASS |
| Frozen model snapshot full SHA-256 | PASS — 19 files |
| Native Tool Call proposal | PASS |
| Model contract | PASS |
| Runtime allow/deny/effect/terminal/restart | PASS |
| Backend pytest on Radeon Cloud | PASS — 58/58 |
| Ruff on Radeon Cloud | PASS |
| Public QA on implementation commit | PASS — 31/31 |
| Frontend contract provenance | PASS — 15/15 |
| Frontend Vitest | PASS — 89/89 |
| Mock Playwright | PASS — 15; one expected live skip |
| Live FastAPI + Playwright | PASS — 16/16 |
| Production dependency audit | PASS — 0 vulnerabilities |

The public machine-readable artifact lists checksums for the raw retained
records under `/workspace/amd-track2-agent/evidence/`. It intentionally omits
endpoints, credentials, account identifiers, device serials and private
payloads.

The manifest's reproduction commands use the committed entry points
`scripts/verify_e1_model_contract.py` and
`scripts/verify_e1_runtime_gate.py`, with the loopback base URL and served
model name written explicitly. The original `fdfa1c1` packet commit
mistakenly used two nonexistent descriptive wrapper names; the manifest
retains that clerical correction in `history.manifest_corrections`.

## Public quality-contract metadata

- Public fixture(s) or scenario(s): N/A for an M1 product artifact; the
  bounded E1 model/runtime gate uses `e1-a-public-tool-smoke-v1`.
- Test/fixture result: 31/31 public QA, 58/58 backend, 15/15 frontend
  contract provenance, 89/89 frontend Vitest, 15 mock Playwright, 16/16 live
  FastAPI + Playwright, and the exact-current W7900 model/tool/runtime gate
  all passed.
- Artifact or trace snapshot:
  `artifacts/w7900-terminal-regression.json`.

## Claims and next decision

The two single-run elapsed observations are retained only as trace metadata.
They are not latency, throughput, VRAM, concurrency, Baseline, Candidate or
optimization evidence. OOM-specific model-server classification also remains
unverified.

This packet supersedes
`evidence/milestones/e1-combined/20260727T050325Z/` as the current PR #12
review candidate, while preserving it and the original failed packet. The
quality owner must still re-review PR #12 and explicitly promote or hold T06.
E2/M1 implementation remains blocked until that decision.
