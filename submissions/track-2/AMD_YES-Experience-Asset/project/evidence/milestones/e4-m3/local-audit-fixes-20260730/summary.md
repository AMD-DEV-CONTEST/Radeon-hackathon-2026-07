# E4/M3 Local Deep-Audit Fix Evidence

- Base commit: `027efe6`
- Working branch: `codex/e4-m3-audit-fixes`
- Exact commit: **UNCOMMITTED / dirty tree**
- Decision: **NOT VERIFIED** — local engineering and browser checks pass;
  W7900/ROCm/real-vLLM and quality-owner promotion remain pending.

## Corrected behavior

- M3 model context includes the current M2 moment content and exact
  moment-to-statement evidence mapping.
- Cross-moment and duplicate evidence references fail before persistence.
- Internal Runtime denial reasons map to a stable public M3 failure code.
- Policy decisions are sanitized, durable and idempotent across node replay.
- An invalidated ledger reports `NEEDS_USER_INPUT` unless a failure belongs to
  that exact regeneration target; stale failures do not leak across corrections.
- M3 run timing is derived from the durable run start instead of fixed at zero.
- Sanitized M3 proposal metadata and LangGraph node traces are durable; raw
  prompts, responses, tool arguments and observations remain excluded.
- The React workspace resolves current M2/canonical identities automatically;
  users no longer enter internal UUIDs.
- The exact-commit W7900 runner, deterministic negative-path capture,
  real-model create/regeneration capture, packet allowlist/finalizer and
  execution-only teammate handoff are prepared.

## Local verification

- Repository shell syntax, Python script compilation, 32 public QA tests,
  disclosure/credential scan and contract PR gate: **PASS**
- Ruff and complete Pytest suite: **PASS**
- React Vitest, typecheck, ESLint and production build: **PASS**
- Real loopback FastAPI/SQLite/React/Chromium M1→M2→M3 journey: **1/1 PASS**
  - current upstream identity auto-resolution;
  - ledger generation and five explicit statement confirmations;
  - ledger confirmation;
  - M2 correction causing visible M3 invalidation;
  - explicit regeneration against the new accepted M2.

The browser run used `scripts/run_e4_m3_local_evidence_server.py`, which is a
deterministic public-fixture worker. It proves local product wiring and does not
claim submitted-model quality, W7900 viability or performance.

The remaining external step is execution of
`scripts/run_e4_w7900_gate.py` by `kinnyuww` on the physical W7900. No
W7900-side coding or manual evidence assembly is delegated.
