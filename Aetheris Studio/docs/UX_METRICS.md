# UX Metrics (Blackbox Fase E)

Methodology, what's measured, and what's still needed for the full protocol.

## Where the numbers come from

Every metric here is a byproduct of the Flight Recorder (`core/audit/flight_recorder.py`, Fase A) -- no separate instrumentation was added except one thing: a `first_token` audit entry, logged once per turn the first time any token (content or reasoning) is actually yielded. Raw token deltas themselves are never logged individually (that would defeat the point of a sparse, human-reviewable audit trail) -- `first_token`'s timestamp against `turn_start`'s is what makes TTFT measurable at all.

`scripts/metrics_report.py` aggregates one or more `<DATA_DIR>/audit/<session_id>.jsonl` files into:

- **TTFT** (time-to-first-token): `first_token.ts - turn_start.ts`.
- **Turn duration**: `turn_end.ts - turn_start.ts`.
- **Tool calls per turn**.
- **Confirm-gate approval/rejection rate + decision latency**: pairs each `confirm_request` with the next `confirm_decision` for the same tool. A `confirm_decision` with no matching `confirm_request` is normal for a UI-initiated action (Time-Travel rollback logs the decision directly, there was never a model-raised request for it) and is counted in the approval/rejection tally without a decision-time figure.
- **Rollback rate**: `rollback_action` tool calls against total approved writes.
- **"Cancelled" turn duration**: turns whose `turn_end.reason == "disconnected"`. This is an **honest approximation**, not the precise cancel-click-to-stop latency the original spec asked for -- no separate `cancel_requested` marker is logged today, only the turn boundary. Documented as such rather than overstating precision (same posture as `core/audit/egress_monitor.py`'s byte-count honesty).

Run it: `python scripts/metrics_report.py <path-to-audit-dir-or-.jsonl-files>` (add `--json` for machine-readable output).

## Real-hardware validation (2026-07-22, RX 7600)

Before writing this doc, the whole Blackbox pipeline was run for real against a live RX 7600 and Qwen2.5 1.5B (not simulated, not mocked) -- a disposable git-initialized scratch project, never a real one:

- **Flight Recorder**: real turns produced a real hash chain, verified both via the live `GET /api/audit/{id}/verify` endpoint and the standalone `scripts/audit_verify.py` CLI. TTFT on a cold-loaded model measured 17.4s (matches this project's already-documented cold-start behavior); a warm turn measured 2.8-3.0s.
- **Egress Monitor**: `0` external connections throughout, `2-3` loopback -- confirmed against the real process tree, not assumed.
- **Time-Travel**: a real model-issued `write_file` call, real confirm-gate pause, real approval, real git shadow-ref commits (`pre:`/`post:`) created and verified via `git for-each-ref` -- confirmed invisible to `git branch`/`git status`. A rollback preview against the pre-write snapshot correctly diffed the file back out.
- **Cartographer**: both real files in the scratch project were mapped in the background (structural extraction + a real LLM-generated summary from the same RX 7600 model), and `search_map` returned the correct, BM25-ranked document for a real query.
- **`metrics_report.py`** itself was run against the real session logs this produced (see above) and handled real, messy data correctly, including a `confirm_decision` entry with no matching `confirm_request` (an edge case the aggregation logic is specifically written to tolerate).

This is real end-to-end evidence that every Blackbox component works against actual hardware, not just the mocked unit test suite (`Aetheris Studio/tests/`, 47 tests, run separately). It is **not** the structured 12-task protocol below -- that's a distinct, larger exercise this pass didn't attempt.

## Still needed: the structured 12-task protocol

Per the approved plan, 12 concrete tasks (the 7 from the README's "Things to try" + 5 covering Cartographer/Time-Travel specifically), each run 3x, recording: success without intervention / success with retry / failure, number of turns, total time. Published **including the failures** -- consistent with this project's documentation style elsewhere (`VTE/docs/LIMITATIONS.md`).

This wasn't executed in this pass. It's a real afternoon of deliberate, structured runs against the live app (ideally on the RX 7600, matching every other number in this project), not something to simulate or estimate. `metrics_report.py` above is ready to aggregate the result the moment those sessions exist.

## Done: the vague-prompt A/B (Cartographer, UC-04), real result on the RX 7600

The exact test the approved plan called for: the README's own documented failure case (*"what does this codebase do"*, no tool named) run twice against a real, freshly-mapped subdirectory (`core/audit/`, 4 real production files), same model (Qwen2.5 1.5B), same prompt, only the flag changed.

**D.1 only** (`AETHERIS_CARTOGRAPHER_AUTO_INJECT=false`, `search_map` available but not auto-injected): the model called `manage_memory search` (the wrong tool), then attempted a malformed `write_plan` block -- **zero real tool calls actually dispatched** (`parse_tool_call` never matched a valid closed fence). It never reached for `search_map` on its own. This reproduces the README's documented failure mode exactly, now with `search_map` as a fifth option on the table and the model still not finding it unprompted.

**D.1+D.2** (`AETHERIS_CARTOGRAPHER_AUTO_INJECT=true`), identical prompt, same session freshness: a direct, grounded, correct answer with **zero tool calls needed** -- correctly named Flight Recorder, Egress Monitor, and Time-Travel, described the hash-chained audit log and the git-based undo mechanism accurately, and cited real function names from the mapped files (`timetravel_enabled`, `_ref_name`, `_temp_index_path`, `_project_path`).

This is the decisive evidence for the judgment call made when this plan was reviewed: D.1 (the lower-risk, architecture-preserving option) alone does not fix the vague-prompt failure on a small model -- the model has to already know to ask, and the whole premise of a vague prompt is that it doesn't. D.2's automatic injection is what actually closes the gap, confirmed with a real before/after on real hardware, not argued from architecture alone.
