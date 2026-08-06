# GTM Executive Cockpit V1

Date: 2026-08-02

## Product decision

The GTM employee now exposes one tenant-scoped lifecycle cockpit at
`/control/gtm-cockpit`. It is not a second workflow or a presentation-only
dashboard. The server derives it from one immutable run request, the validated
Campaign Workspace, the content-bound human decision, aggregate effect
observations, reconciled unit economics, and human-promoted project memory.
It also reports operator-attested manual publication receipts separately from
observations; a receipt is never treated as platform-delivery or effect proof.

This is an L2 deterministic workflow with bounded L3 generation inside known
nodes. The Graph owns lifecycle transitions, each node may use a capped
evaluator-optimizer Loop, and the Harness owns schemas, tenant authorization,
digests, approval boundaries, persistence, and claim eligibility.

## Lifecycle joined by the cockpit

1. **Operating context** — industry, B2B/B2C model, lifecycle, budget, market,
   audience, goal, and offer come from the immutable launch request. The same
   line also shows the separately sealed real public-signal pilot: 28 public
   metadata signals across YouTube and Vimeo and three source-bound hypotheses.
   These signals are planning inputs, not copied creative, training rows, or
   evidence of effect.
2. **Goal diagnosis** — zero-spend and high-regulation constraints remain
   explicit; a blocked or terminal run is never represented as progress.
3. **Strategy and channels** — primary, secondary, focus, and test channels
   come from the validated strategy object rather than UI defaults.
4. **Production workspace** — the cockpit reports availability of the big
   idea, channel copy, landing page, lifecycle email, SEO/GEO, video, audio,
   analytics, and the seven-slot content calendar.
   A separate 11-capability effect matrix prevents availability from being
   misread as outcome. It covers cross-device memory, data strategy, scheduling,
   video, audio, text, analytics, GEO, SEO, employee-Agent execution and
   advertising. Each row reports its current evidence stage and next gate.
   In the current run-bound demonstration, video and audio are `brief_only`,
   advertising is `plan_only_activation_disabled`, and generated, named-human
   quality and capability-attributed effect counts remain zero.
5. **Human boundary** — approval is read from the durable server record.
   Publishing, sending, spending, and automatic strategy mutation remain
   disabled even after delivery.
6. **Effect and revenue** — only source-bound aggregate observations and
   reconciled economics are counted. Pipeline is never counted as revenue and
   no causal revenue claim is enabled.
7. **Learning** — only named-human-promoted aggregate learning records count
   as project memory. The cockpit separately reports memories promoted by the
   current run and the immutable approved context inherited when this run was
   created. Inherited memories are then scored against industry, B2B/B2C,
   lifecycle, budget, regulation, market, and selected channels. Paid learning
   cannot flow into zero-budget work, standard-risk learning cannot flow into
   high-regulation work, and conflicting channel directives fail closed for
   named-human arbitration. The cockpit cannot silently mutate the next run.
8. **Next best action** — deterministic state-dependent actions name the
   owner, priority, action, and reason. The browser cannot execute them.

## State-dependent decisions

| Run state | Cockpit action |
|---|---|
| queued / running / auditing / repairing | monitor the observable governed trajectory |
| awaiting release | review all nine artifacts, then approve or reject the exact preview |
| delivered, no publication receipt | use a separately authorized human channel workflow and record the exact asset/tag/URL receipt |
| publication receipt, no outcome | record the preregistered aggregate outcome |
| outcome, no economics | reconcile closed revenue and all variable costs |
| positive economics, no memory | human-review and promote the aggregate learning record |
| complete evidence loop | continue, repair, stop, or design the next bounded experiment |
| failed / blocked / rejected / cancelled | inspect the hash-chained trace before a new run |

## Integrity and permission model

- API: `GET /v1/runs/{run_id}/gtm-cockpit`
- Real-signal pilot API: `GET /v1/public-signal-pilot`. It exposes only aggregate
  platform counts, hypothesis IDs, evidence hashes and authority flags; file
  paths and input-artifact identities are not returned.
- Authentication: bearer token maps to an immutable tenant principal.
- Object authorization: a mismatched tenant receives no cockpit data.
- Integrity: the server signs the canonical cockpit payload with SHA-256; the
  browser recomputes and compares the digest before rendering. The real-signal
  projection has an independent server-computed digest and an independent
  browser check; a stale or tampered pilot fails closed.
- Required false flags: 4A-effect eligibility, Top-1 eligibility, causal
  revenue, paid-channel activation, publish, send, spend, and automatic
  strategy mutation.
- Capability-effect integrity: exactly 11 rows are required. Every row carries
  separate `generated_deliverable_observed`, `named_human_quality_observed` and
  `production_effect_attributed` booleans. The browser rejects the entire
  cockpit if row-derived aggregate counts or a false authority boundary is
  inconsistent. Video/audio move from `brief_only` to `generated_unreviewed`
  only after a tenant-owned WAV/MP4, run/campaign binding, immutable execution
  receipt and rights locator verify. A separate named review can move the row to
  `generated_human_review_passed`; production effect and 4A eligibility remain
  false until their own evidence gates are satisfied.
- Cross-device memory: the cockpit exposes the frozen context and decision
  SHA-256 values, inherited count, context-eligible count, conflict count,
  application status, recommended directives, and explicit false flags for
  automatic strategy, schedule, and budget mutation. Later memories cannot
  rewrite an already-created run. See
  [`CONTEXTUAL_STRATEGY_MEMORY_ARBITRATION_V1.md`](CONTEXTUAL_STRATEGY_MEMORY_ARBITRATION_V1.md).
- Rendering: all content enters the DOM via `textContent`; no model-supplied
  HTML is executed.

## Verification

The production API test drives one run through queued, awaiting release, and
delivered states. It asserts tenant isolation, stable digests for unchanged
state, digest change after lifecycle progress, nine workspace artifacts,
seven scheduled slots, correct next actions, and zero effect/quality upgrade.
The revenue-memory demonstration additionally seals a delivered device-A
cockpit and a device-B next-cycle cockpit. Device B reaches review with nine
workspace artifacts and exactly one previously reviewed inherited memory.

The browser exposes this pair as a read-only one-control demonstration. With
no live run loaded, activate the Cockpit status control once for the delivered
device-A loop and again for the inherited device-B cycle. The server first
re-hashes the lifecycle receipt, all nine bound artifacts and both Cockpit
documents; the browser then verifies the envelope SHA-256 and each Cockpit
SHA-256 independently. No tenant run is created and no publish, send, spend,
training, strategy mutation, production-effect or 4A authority is introduced.
The UI contract test asserts the route, lifecycle fields, both browser digest
checks, authority flags, and DOM budget. The product-critical suite seals the
current exact test count in `evidence/v10/aug3-product-readiness.json`; this
document intentionally avoids a hand-maintained count that can become stale.

## Truth boundary

The cockpit makes the implemented lifecycle visible and operable. It does not
prove external publication, incremental lift, causal revenue, annual breakout,
4A preference, Top-1 standing, or Radeon execution. Those remain separate
evidence gates.
