# ProofLaunch Brand Genome Memory V1

Brand Genome V1 turns the earlier flat `MemoryFact` cache into a typed,
versioned and rights-aware graph. This milestone implements TODO 0351–0374 as
a local mechanical runtime and policy-supervision seed. It does not claim that
a neural memory policy has been trained.

## Memory and entity schema

`MemoryAtom` binds a stable atom ID, memory kind, subject, visible payload,
source locator/revision/digest, rights profile, validity, confidence, utility,
approval, privacy class and version. Hidden chain-of-thought fields fail
closed. Four memory kinds are explicit: entity, episodic, semantic and
permanent symbolic rule.

Entity memory covers the seven canonical Brand Genome nodes: product, brand,
audience, Claim, channel, asset and creative concept. Claims and brand records
require approval before storage; symbolic rules always live in the permanent
layer and also require approval.

## Graph semantics

Five typed edges prevent an undifferentiated vector-memory blend:

- `evidence`: a Claim points to its supporting atom;
- `conflict`: both unresolved endpoints enter quarantine;
- `supersede`: an older same-subject/same-kind version points to a newer one;
- `applies_to`: knowledge or rules are scoped to their target entity;
- `prohibited`: an approved symbolic rule forbids an action or target.

Active retrieval excludes tombstoned, quarantined, superseded, expired,
unapproved and below-confidence atoms before applying subject, entity and
memory-kind filters.

## Policy supervision

The runtime implements eight explicit decisions: store, retrieve, update,
merge, discard, summarize, what-to-remember and when-to-forget. Each decision
returns `accept`, `reject` or `human_review` with machine-readable reason codes.
Updates are append-only. Conflicting records cannot be silently averaged.
Discard writes a recoverable tombstone. Summaries must cite every member by
content digest. Permanent rules and evidence referenced by Claims receive an
approval boundary.

The seed corpus contains one positive and one negative supervision example for
each policy. Every example is project-owned synthetic data, contains only
deployment-visible state and explicitly records `model_training_observed=false`.

## Evidence and reproduction

Run:

```bash
PYTHONPATH=src python scripts/build_v10_brand_memory_seed.py
PYTHONPATH=src python scripts/build_v10_brand_memory_runtime.py
PYTHONPATH=src python -m unittest -v tests.test_v10_brand_memory
```

The builder writes `data/v10_brand_memory/` with content-addressed atom, edge,
policy and event records, plus
`evidence/v10/brand-memory-seed-audit.json`. The current bounded seed has 13
atoms, all four memory kinds, all seven entity kinds, exactly five typed edges,
16 balanced policy examples and a 17-event verified hash chain.

## Retrieval and isolated evaluation

Four first-class paths are available: entity-centric filtering, permanent-rule
symbolic retrieval, a revisioned dense-embedding adapter and frozen hybrid rank
fusion. Privacy ceiling and role ACL checks happen before ranking. Utility,
confidence and token cost control the bounded context. The dense adapter records
whether neural inference was actually observed; the bundled fixture correctly
sets this to `false`.

The 12-case memory-only benchmark denies the answerer access to raw inputs and
runs six modes: entity, symbolic, dense, hybrid, vector-only and no-memory. A
separate streaming benchmark executes revision replacement, expiry, conflict
arbitration and rollback. On the controlled project-owned fixtures, hybrid
precision is 1.0, stale recall is 0, mean context saving is 0.667,
cross-Campaign brand-rule transfer is 1.0 and cross-brand contamination is 0.
These values characterize the fixtures and deterministic runtime only.

## Reuse-or-Justify record

- [SAGE graph memory](https://arxiv.org/abs/2605.12061v1): adopts typed evolving
  graph structure and a writer/reader feedback boundary; no Graph Foundation
  Model reproduction is claimed.
- [TaskMem](https://arxiv.org/abs/2605.31075v1): adopts memory-only and streaming
  evaluation isolation; no RL memorization adapter or published gain is
  claimed.
- [Hybrid fusion analysis](https://arxiv.org/abs/2210.11934v2): motivates
  freezing fusion parameters and preserving explicit ablations because fusion
  is parameter-sensitive; the fixtures do not establish production-optimal
  weights.

## Truth boundary

This milestone proves only local schema validation, deterministic policy and
retrieval behavior, synthetic supervision records and mechanical tests. It is
not a trained memory adapter, observed neural-embedding run, learned
retrieval-quality result, scaled 4A corpus, Radeon execution receipt, human
preference result or production reliability claim. Workstream 08 TODO 0351–0400
can close at this mechanical evidence level; later cross-workstream model,
Radeon and Top-3 gates remain independently blocked.
