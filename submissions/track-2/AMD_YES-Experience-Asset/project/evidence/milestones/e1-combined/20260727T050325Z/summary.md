# E1 combined gate — model-failure terminal correction

Packet: `e1-combined-terminal-fix-20260727T050325Z-2deaad7`

## Outcome

PR #12 received a `FAIL` T06 review because the current-source smoke loop saved
`PLANNED` before local-model generation but did not convert model exceptions or
a missing required Tool Call into a durable terminal result. The failed
observation is retained here instead of being removed from the earlier green
packet.

Implementation commit
`2deaad7ad0fa268f8a0a75f6b87954aabe2ab3f0` now maps:

- local model unavailable to `MODEL_UNAVAILABLE`;
- explicit model timeout to `TIMED_OUT`;
- invalid or empty structured output to `INVALID_MODEL_OUTPUT`; and
- a proposal without the required Tool Call to `INVALID_MODEL_OUTPUT` with
  `MissingRequiredToolCall`.

Each path saves a `MODEL_FAILURE_TERMINAL` checkpoint, finishes the durable run,
records safe user/retry/recovery metadata and preserves the last valid
canonical version. Restart regressions prove the same terminal checkpoint and
run result remain readable after reopening the SQLite repository.

This packet is `FIX_READY_REVIEW_PENDING`. It does not promote T06. E2 remains
blocked until the quality owner accepts this correction and returns a new gate
decision.

## Track 2 and acceptance relevance

- Maps to AC-04, AC-11, AC-17, AC-18, AC-22, AC-24 and AC-27.
- Covers the cross-cutting E1/T06 foundation, not M1–M5 product behavior.
- Directly strengthens Persistence and resume, Local inference, Failure
  behavior, Observability and Evidence discipline.
- Makes the judge-visible Agent safe-stop behavior reproducible without
  granting the model any new execution permission.

## Reproduction results

| Gate | Result |
|---|---|
| Injected unavailable/timeout/invalid/missing-tool terminal paths | PASS — 4/4 |
| Restart and last-valid-version assertions | PASS — 4/4 |
| Backend pytest | PASS — 51/51 |
| Public QA | PASS — 31/31 |
| Repository static/contract gate and contract export | PASS |
| Ruff | PASS |
| Frontend contract provenance | PASS — 15/15 |
| Frontend typecheck/lint/build | PASS |
| Frontend Vitest | PASS — 89/89 |
| Mock Playwright | PASS — 15; one live case intentionally skipped |
| Live FastAPI + Playwright | PASS — 16/16 |
| Production dependency audit | PASS — 0 vulnerabilities |

The live service bound to `127.0.0.1:8080`, used an ephemeral local database,
and was stopped after the run.

## W7900 and serving-evidence boundary

No GPU or model server was run in this local correction packet. The comparison
from PR #12's prior head to the implementation commit shows no change to:

- the frozen model manifest or vLLM runtime identity;
- `serve_vllm.sh` or the Tool Call verification script;
- the localhost model-client request/parsing implementation; or
- model/server arguments and public structured-output contracts.

Only the Agent-loop failure boundary, terminal-result repository read path and
their public tests changed. The already accepted W7900 serving evidence at
`evidence/milestones/e1-a3-real-w7900/20260725T121500Z/` is therefore inherited
only for its unchanged frozen serving inputs. This is not a current-commit GPU
rerun and makes no performance claim.

## History and decision

- Prior packet:
  `evidence/milestones/e1-combined/20260726T220422Z/`.
- Quality review of that packet: `FAIL` for T06 due to the High terminal-state
  blocker.
- This packet supersedes the prior packet as the current T06 review candidate
  but does not overwrite its commands, outcomes or failed review.
- Current decision: `FIX_READY_REVIEW_PENDING`.
- Next action: quality-owner re-review of PR #12. Do not begin E2 before a new
  `PASS` or permitted recorded gate decision.
