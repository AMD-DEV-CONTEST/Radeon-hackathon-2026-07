# 05 — Explicit discovery returning zero or one validated candidate

**What to build:** The user clicks "find related experiences" and gets back either
exactly one fully explainable candidate or an honest no-match. One local-model call
compares the current card's role graph against the eligible historical graphs in a
single batch. The model's answer is a proposal; the Runtime checks every node
identifier against the stored projections, enforces the relation's role rule, requires
a source-grounded transfer boundary, and requires provenance from both sides.

**Why one candidate rather than a ranked list:** showing a weak relation is more
expensive than missing a plausible one. A false relation spends the user's attention,
makes an otherwise explainable asset feel less trustworthy, and can redirect their
later reasoning toward an experience that was never relevant. A missed relation leaves
the current asset exactly as it was. Returning more candidates does not repair the
first harm — it multiplies it, because the user must now evaluate several weak claims
instead of one strong one.

**Why a validation failure is not reported as no-match:** no-match is a semantic claim
— "we compared these and found nothing defensible" — and the system caches it. A
malformed model response supports no such claim. Filing it as no-match would cache a
transport accident as a proven absence, and the relation would stay invisible until
something unrelated changed the fingerprint.

**Why the model gets a closed set and no tools:** its useful contribution is judging
structural correspondence among graphs it has been handed. Letting it choose its own
scope spends its finite attention on deciding what to look at, and makes the resulting
proposal impossible to validate — the Runtime cannot check node identifiers against
projections it never supplied.

**Real-model probe (included here):** once the compact role-graph payload is stable,
run it once against the production local model to confirm a schema-valid structured
proposal is achievable at all. Record the outcome; attach no evidence, performance, or
W7900 claim — the formal gate is ticket 11. This exists because E4's first blocker was
the same model failing on an oversized payload; discovering that during ticket 10 would
invalidate tickets 05 through 09 at once, whereas discovering it here costs one ticket.

**Blocked by:** 04 — Role-graph projection and FTS5 summary index.

**Owns:** "search once and get an answer" — reserving one attempt against the record
shape ticket 01 froze, making one batch call, validating, and persisting a candidate or
a semantic no-match, plus mapping technical failures to typed outcomes. Ticket 06 owns
"search twice, search concurrently, or crash mid-search and still get one coherent
answer": fingerprint canonicalization, idempotent caching, leases, crash recovery,
retry budget, and concurrency coalescing. Neither ticket defines the other's schema —
both implement interfaces frozen in ticket 01. Ticket 07 consumes the persisted
candidate.

**Not in this ticket:** no confidence score, no ranking model, no weak fallback relation
when validation fails, no second candidate, and no idempotency or retry semantics
(ticket 06). A score is the natural way to express "how sure are we", and it fails
this way: `0.73` reads to the user as quantified confidence about the relation, while
the number is actually derived from nothing that was validated — a candidate can score
high and still have one-sided provenance. The score makes an unverified association
look measured.

The admission rule that replaces it is a complete validated evidence package: fixed
relation type, bilateral mapping, source-grounded boundary, bilateral provenance. It
is binary and every part of it is checkable. When the package is incomplete, spend the
attention on abstaining cleanly rather than on ranking what could not be verified.

**Verify with:** the shared command set, plus GRAG-03, GRAG-04, GRAG-05, GRAG-06 and
GRAG-17 at the HTTP seam using the deterministic model fake.

**Status:** ready-for-agent

## AC-13 ownership — BLOCKED_ON the #44 runtime, not unowned

Recorded 2026-08-05. The real-model probe was previously carried as
`NOT_RUN (no environment)`, which is accurate and ownerless — nothing said who
would run it or when it stopped being blocked.

**Owner split:** E5 supplies the inputs; the W7900 side executes. The probe rides
the PR #44 20K capability runtime, which is `PLAN IMPLEMENTED / RUNTIME NOT
EXECUTED` at the time of writing.

**What E5 supplies**, generated from `inference/models.py` as canonical JSON with
sorted keys:

| Schema | Size | SHA-256 (first 16) |
|---|---|---|
| `relation_discovery_proposal_v1` | 2,204 chars | `aaac910fb70e1e82…` |
| `m4_map_proposal_v1` | 2,620 chars | `bfc02558419dce9d…` |
| `m3_ledger_proposal_v1` | 2,404 chars | `a9b3cd18a70ae27b…` |

**Scope grew by one question.** The original criterion asked only whether a
schema-valid structured proposal is achievable at all. It now also asks whether
the object-level `anyOf` rewrite in `workflow/m3_graph.py:79-108` and
`workflow/m4_graph.py:95-119` is still required on vLLM 0.26. That rewrite exists
because an older backend compiled `anyOf` alternatives independently instead of
merging each with the surrounding object; if 0.26 merges them, the rewrite is
redundant, and if it does not, the rewrite stays. Both variants are supplied so
the run needs no E5 code.

The question was raised after PR #39 measured truncated structured output at
8K. That evidence does **not** implicate guided decoding — those workloads used
plain Chat Completion with post-hoc validation, never `response_format` — so the
probe is the only way to answer it, and the earlier association between the two
is retracted.

## Acceptance criteria

- [ ] Discovery starts only from an explicit user action on an exact ready card,
      carrying asset identifier, expected version, expected card hash, the Runtime-owned
      discovery-intent version, and the fixed summary scope.
- [ ] One request compares the current asset against the eligible historical assets as
      compact summary-role graphs, in one batch. One call per asset would make prompt
      cost grow linearly with the corpus and would prevent the model from ranking the
      alternatives against each other, which is the comparison being asked for.
- [ ] The model receives only Runtime-supplied compact graphs and has no tools.
- [ ] The service returns zero or one candidate; a bounded `top_k` never pads the
      result. (GRAG-05)
- [ ] A valid candidate carries one fixed relation type, readable bilateral role
      mapping, a source-grounded transfer or non-applicability boundary, and bilateral
      canonical statement/evidence/source provenance — and no historical detail.
      (GRAG-03)
- [ ] The required current-side boundary resolves through a limitation, applicability,
      or counterexample role. A card with no source-grounded boundary abstains, because
      a relation shown without a boundary invites the user to treat structural
      similarity as permission to transfer the lesson wholesale.
- [ ] Relation reason, mapping, boundary, and provenance are rendered by the Runtime
      from validated canonical content. Model prose promoted into a durable candidate
      would become a claim the user attributes to their own evidence, with nothing
      backing it.
- [ ] Only summary-role data reaches the model, not detailed evidence. The discovery
      decision does not require the details, and sending them would put historical
      content into a prompt before the user has agreed to look at that history at all.
- [ ] The hard-negative corpus completes as semantic `NO_MATCH` with zero candidates,
      presented as a finished search. Presenting abstention as an error would train the
      user to retry until something appears. (GRAG-04)
- [ ] Forbidden labels, wrong-side or nonexistent nodes, missing boundary, one-sided
      provenance, inadmissible role pairs, extra fields, tool calls, and prompt-injection
      attempts through canonical summary text all expose no candidate and remain
      technical or validation failures. (GRAG-06, GRAG-17)
- [ ] No partial candidate is exposed: all bindings are rechecked inside the same write
      transaction that persists it, so a projection invalidated mid-validation cannot
      produce a candidate that was valid only at the start.
- [ ] The UI renders running, candidate, no-match, and technical-failure states from
      backend contracts.
- [ ] The real-model probe is run and its outcome recorded, with no evidence or
      performance claim attached.
