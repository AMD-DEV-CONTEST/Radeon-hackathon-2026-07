# E5-T01 to E6 Compatibility Preflight

## Status and authority

- **Status:** preflight observation only; not a shared-contract amendment and
  not an implementation authorization.
- **Inspected E5 draft head:** `a9f2f29141c12d9461a427f0a5d1ef8d74ea4dea`
  from Draft PR #35.
- **E6 base authority:** PR #28 at
  `a0b042d812d1358814b3f7743a58541e653acff0` and
  `E6_M5_ROUTE_PRIVACY_APPROVAL_SPEC.md`.

PR #35 is marked `W0 only` / `NO-GO`. It freezes Ticket 01 contracts and does
not provide the runnable M4 map or the durable ready-state behaviour required
from E5 Tickets 02 and 03. This document records the exact E6 consumer risks
visible at that draft head so they can be resolved before formal E5-to-E6
integration. It does not permit E6 to change shared domain types, migrations,
repositories, API startup, or the production graph.

## Verified compatibility delta

| E6 isolated assumption | E5-T01 draft shape | Required E6 integration treatment |
| --- | --- | --- |
| `domain.models.KnowledgeCardReadiness` exists and carries `version_id` plus `content_hash`. | The type is removed from `domain.models.py`. E5 adds sidecar `domain.relation.KnowledgeCardReadinessRecordV1`, with `asset_id`, `version_id`, `m4_artifact_id`, `knowledge_card_hash`, `milestone_state`, acceptance data, and `lifecycle`. | Do not make a private alias or copy E5 state. After E5 merges, the E6-owned read-only composer must consume the reviewed sidecar record. |
| `M5ContextProjectionV1.content_hash` is the exact immutable Experience Asset content binding. | `knowledge_card_hash` identifies the accepted M4 card, not necessarily the asset snapshot content. | Preserve both identities. A composer must obtain the current asset content hash separately and must never substitute the card hash for it. |
| Readiness presence alone means usable input. | E5 readiness has an explicit lifecycle, including stale/invalidated states and invalidation evidence. | Only an exact current, accepted, active record may pass M5 input readiness. Any absent, stale, invalidated, mismatched, or otherwise inconsistent record maps fail-closed to `M5_INPUT_NOT_READY` or `M5_INPUT_STALE`. |
| `M5RelationProjectionV1` represents one of `NO_MATCH`, `DECLINED`, `CONFIRMED_RELATION`, or `STALE`. | E5 composes `RelationWorkspaceV1` from sidecar readiness, discovery outcome, candidate/decision records, and confirmed relations. | The E5-to-E6 composer must derive the four frozen M5 outcomes from the reviewed workspace; E6 must not read E5 ledger tables or use candidate detail directly. |
| A confirmed relation can contribute only E5-authorized historical statement IDs. | E5 owns confirmed relation and permission state in the sidecar relation ledger. | The composer must expose only the current exact-bound relation identity and Runtime-authorized references. `NO_MATCH`, `DECLINED`, or `STALE` must expose no historical detail. |

## Integration checks that must exist later

The formal E5-to-E6 integration change must prove all of the following against
merged E5 code, not contract-equivalent mocks:

1. an active `KnowledgeCardReadinessRecordV1` plus a current canonical asset
   produces a current M5 context with distinct asset-content and card hashes;
2. no readiness, a stale readiness record, or a version/hash mismatch blocks
   evaluation before route, privacy, approval, or historical retrieval occurs;
3. `NO_MATCH` and `DECLINED` continue without history, while one exact confirmed
   relation exposes only its authorized references;
4. a relation or readiness invalidation turns the M5 context stale and makes
   prior route, privacy, draft, and approval state ineligible for reuse;
5. the composed view contains no raw historical text, ledger write authority,
   browser approval boolean, or second canonical copy of the Experience Asset.

## Deliberate non-actions before E5 merge

Until the E5 draft is reviewed, finalized, and merged, E6 does **not**:

- replace its isolated fixture import with the draft E5 type;
- add a compatibility alias, shared schema edit, or migration;
- compile a production M5 LangGraph or wire repositories/API/App entry points;
- claim E5-to-E6 integration, restart persistence, or W7900 evidence.

The current E6 isolated contracts, mocks, policy tests, feature-local UI, and
non-production workflow fake remain valid only as `ISOLATED_READY` work. They
are intentionally not evidence of the live E5 handoff.

## Handoff trigger

This preflight becomes implementation work only when all conditions below are
true:

1. the E5 shared contract has one reviewed controlling head;
2. E5 Tickets 02 and 03 provide the real M4 artifact and exact readiness
   transition expected by the composed view;
3. E5 has completed its own integration and merged according to the formal
   E5 -> E6 -> E7 order; and
4. the E5 owner documents the read-only composer input and invalidation
   behaviour needed by the E6 consumer.

At that point E6 synchronizes `main`, replaces mocks with the real composed
view, then adds the minimum adapter, persistence, production graph, API, and
UI work with the affected integration tests.
