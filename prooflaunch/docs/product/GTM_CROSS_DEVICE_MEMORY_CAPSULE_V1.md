# Cross-device GTM memory capsule contract

Date: 2026-08-02

## Product outcome

ProofLaunch can move approved aggregate project learnings between local devices without moving raw creative, audience identifiers, browser credentials, connector authority, or publishing permission. The transfer is a portable JSON capsule signed server-side with HMAC-SHA256, bound to one tenant and project, content-addressed, nonce-protected, and time-limited.

Import is deliberately two-phase:

1. The receiving server verifies the exact schema, context digest, capsule digest, signature, tenant, optional project, issuance time, and expiry, then stages the capsule as `pending_review`.
2. A named server-configured operator must approve or reject the immutable capsule using the local approval credential. Only `approved` capsules are merged into the next run's frozen learning-context artifact.

Pending and rejected imports never enter a run. Approval does not mutate an existing strategy, trigger a model call, publish content, spend money, or call a connector.

## API

- `POST /v1/memory-capsules/export` — authenticated tenant; body contains `project_id` and bounded `ttl_seconds`.
- `POST /v1/memory-capsules/import` — authenticated tenant; body contains the capsule and optional expected `project_id`.
- `GET /v1/memory-capsules?project_id=...` — authenticated, tenant-scoped import ledger.
- `POST /v1/memory-capsules/{capsule_id}/reviews` — authenticated tenant plus `X-ProofLaunch-Approval-Token`; immutable approve/reject decision.

For cross-device verification, configure the same secret on both local servers via `PROOFLAUNCH_MEMORY_CAPSULE_SECRET`. It must contain at least 32 UTF-8 bytes. If it is absent, the server creates an unprinted ephemeral secret: this is safe for a single session but intentionally prevents import on another server. The bearer and approval credentials remain separate and are never included in the capsule.

## Security and truth boundaries

- Tenant identity is derived only from the server-side bearer-token map.
- A valid signature from another tenant or project is insufficient; scope must also match.
- Client attempts to set mutation or external-action authority fail verification.
- Identical imports are idempotent; a reused capsule identity with different content fails closed.
- Review decisions are immutable and tenant scoped.
- Imported memories are aggregate experiment learnings, not audience truth, causal revenue proof, or a training corpus.
- The current implementation is a single-node SQLite vertical slice. Production still requires KMS-backed key rotation, audited IdP, database RLS, device enrollment/revocation, distributed worker isolation, and recovery drills.

## Reproduction

```bash
PYTHONPATH=src:. .venv/bin/python -m unittest \
  tests.test_gtm_memory_capsule \
  tests.test_v10_submission_store \
  tests.test_v10_submission_runtime \
  tests.test_v10_submission_production_api
```

The HTTP test binds only to `127.0.0.1` on an ephemeral port. It verifies cross-tenant rejection, tamper rejection, pending-not-applied behavior, named review authority, immutable decisions, and admission into a later frozen run snapshot.
