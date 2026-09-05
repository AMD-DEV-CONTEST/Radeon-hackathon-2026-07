# E1-B evidence — cross-asset relation discovery (KnowledgeCardReady / AC-30)

**Commit:** `e48dfa2` on `codex/e1-b-react-shell`, realigned onto `main` (which now
contains PR #9). **Issue #6 / PR #8.** No E1-B milestone is claimed.

## What this adds

A phase-gated cross-asset **relation discovery** surface in the E1-B status
shell, driven only by the public retrieval-phase trace contract vendored verbatim
from `main` (PR #9). It answers the Lane-B constraints from the owner's PR #8
comment:

| Constraint | How it is met | Proof |
|---|---|---|
| Expose accepted **KnowledgeCardReady** at M4 before cross-asset discovery | Panel is `LOCKED` until a `knowledge_card_ready` event with `explicit_user_acceptance` | `relationView.test.ts`, e2e `11-relation-locked` |
| Candidate UI is **summary-only** (title, relation type, reason, provenance) + valid **no-match**; no preloaded history | Candidates render only trace summary fields; the trace carries no detail body; `relation_no_match` → no-match state | e2e `12-relation-ready`, `13-relation-no-match` |
| **Explicit confirm/decline**; only a confirmed relation can request bounded detail | `detailAccess` stays `DENIED_UNTIL_CONFIRMED` until `relation_confirmation.confirmed=true`; confirm/decline shown as backend-owned actions | `relationView.test.ts`, e2e `14`/`15` |
| Editing/reopening M1–M4 **invalidates** readiness, candidates, confirmations, detail | `current_card_changed` with `mutated_current_statements` clears the surface → `INVALIDATED` | e2e `16-relation-invalidated` |
| Progress from public basis; **no invented countdowns** | Unchanged; percent stays paired with work-unit basis (AC-17) | pre-existing `RunActivityPanel` tests |
| Snapshots include ready, no-match, confirm/decline, invalidation, denied-detail | 6 chromium screenshots `11`–`16` in `e2e-results/screenshots/` | `web/e2e/relation.spec.ts` |

## Why this is contract-faithful, not invented

- The gate shape is the **backend-owned** `retrieval_phase_trace` schema, vendored
  byte-identically (`verify:contracts` → 10/10) under its own provenance manifest.
- The UI **enforces** the two RAG gates in a pure derivation and the same gates
  are independently enforced by the backend qa suite and the AC-30 checker.
- All five trace fixtures **pass `qa/scripts/check_retrieval_phase.py`**, so they
  are traces the backend would actually emit — the UI does not fabricate state.
- Live mode reports the trace as **not served** (E1-A exposes no such endpoint
  yet); only the provider changes when the backend ships it.

## Gates (all green)

verify:contracts 10/10 · typecheck · lint · **62 unit tests** (was 39) · build ·
**15 e2e** (9 status + 6 relation, real chromium) · **5/5 AC-30 checker PASS** ·
qa unittest 31 OK · `pr_gate.sh --mode contract` PASS.

## Boundaries

Frontend only; no backend/schema change, no model, no export/deletion, no
milestone promotion. The W7900/ROCm viability gate remains Lane A / Issue #5.
