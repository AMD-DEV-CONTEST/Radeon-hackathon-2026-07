# Evidence packet: `e1-a3-w7900-20260725T121500Z-5209101`

## Outcome and scope

- Technical result: the frozen Qwen2.5-14B-Instruct BF16 model loaded on the
  Radeon Cloud W7900 through ROCm/vLLM and produced an inert structured
  current-source tool proposal.
- The same immutable real-model proposal passed through deterministic Runtime
  allow and deny decisions. The allowed path produced one bounded fake local
  retrieval effect and `SUCCEEDED`; the denied path produced no observation
  and `POLICY_BLOCKED`.
- Restart restored the terminal checkpoint and the canonical version remained
  unchanged.
- This packet was produced from the exact clean PR #7 review-fix commit
  `520910183783c9bec8a0810a34b49dcc7856f360`.
- Explicit non-goals: production cross-asset index, M1-M5 behavior, frontend,
  export/deletion, public exposure, performance Baseline or optimization claim.

## Review findings resolved

- Knowledge Card readiness now requires exact `base_version_id` equality.
  Proposals and cross-asset arguments bind the same card version/hash; stale
  readiness, candidates, confirmations and detail access fail closed.
- All seven reviewed model-visible tools have strict typed argument schemas.
  Only the three E1-A retrieval operations have dispatchers; the four deferred
  tools return `TOOL_NOT_EXECUTABLE_IN_E1_A` and never reach execution.
- Confirmed historical detail requires an exact relation-to-asset pair and a
  `CROSS_ASSET_DETAIL` run-state scope; mixing two independently confirmed IDs
  is denied.
- Even a test-forced `ALLOW` with malformed executable arguments becomes an
  auditable `FAILED` execution and durable `INTERNAL_ERROR` terminal state
  rather than an uncaught exception.
- Public tests cover allow, permission denial and invalid arguments for each
  E1-A dispatcher, fail-closed behavior for every deferred tool, stale card
  bindings and M1-M4 version-change invalidation.

## Reproduction and result

- Public fixture: `e1-a-public-tool-smoke-v1`.
- Raw storage:
  `/workspace/amd-track2-agent/evidence/e1-a3-w7900-20260725T121500Z-5209101/raw/`.
- Sanitized commands:
  - `bash scripts/verify_remote_dev.sh` — PASS
  - `bash scripts/verify_rocm_env.sh` — PASS
  - `python3 scripts/verify_model_snapshot.py ...` — 19 files, full SHA-256 PASS
  - `python scripts/verify_e1_model_contract.py ...` — PASS
  - `python scripts/verify_e1_runtime_gate.py ...` — PASS
  - `pytest -q` — 46 passed
  - `ruff check .` — PASS
- Structured proposal: 434 prompt tokens, 155 completion tokens, 6287 ms.
- Final Runtime gate: one real model call, two policy evaluations, 6974 ms,
  with no rejected proposal attempt in the frozen run.
- No raw prompt, raw response, model weight, endpoint credential, network
  address, device serial or private user material is present in Git evidence.

## Failed attempts and decision

- Three failed attempts are retained in
  `artifacts/failed-attempts.json`; none weakened the permission or quality
  contract.
- Result class: `PASS_REVIEW_PENDING`.
- The evidence satisfies the engineering E1-A3 gate on the exact commit;
  milestone acceptance and merging remain with the quality/integration owner.
- Supersedes the `NOT_VERIFIED` model/service portion of
  `e1a3-remote-20260724T093311Z-f7ebbbc`; it does not overwrite that historical
  access/device packet.
