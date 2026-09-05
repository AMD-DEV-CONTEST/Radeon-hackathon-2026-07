# 06 — Discovery fingerprint idempotency and technical-failure retry

**What to build:** Clicking the search twice does not produce two different answers.
The same discovery input returns the same validated candidate or the same no-match
without spending another model call. A timeout or malformed response stays retryable.
When the current card, the eligible corpus, the model, the prompt, or the inference
configuration actually changes, a fresh search is permitted.

**Why idempotency is a product requirement and not an optimization:** if repeated
clicks could yield different relations, the user learns that the answer is negotiable
and clicks until they like one. That converts a precision-first system into a slot
machine, and the relation they finally confirm is selected by persistence rather than
by evidence. A stable answer for a stable input is what makes confirming it a real
decision.

**Why the fingerprint covers model, prompt, and configuration identity, not just
content:** the same graphs under a different model produce a different judgment. If the
fingerprint ignored model identity, an upgraded model would keep serving the previous
model's cached no-match, and the improvement would be invisible for exactly the assets
that were already compared.

**Why technical failures are retained but never reused:** they are auditable events
that carry no semantic claim. Reusing one as an answer would let a five-minute outage
permanently erase a relation; discarding one entirely would hide a pattern of failures
that indicates a real problem.

**Blocked by:** 01 — Contract and fixture freeze. (Under the sequential plan this
followed 05; in Wave 1 it builds against 01's attempt fixture instead — see completion
note below.)

**Wave 1, parallel.** Branch from the E5 integration branch after 01 lands.

- **Consumes:** 01's frozen attempt record and fingerprint field set, plus 01's attempt
  fixture and a fixture discovery input. Which fields the fingerprint covers is 01's
  ruling, not this ticket's — deciding it here would mean ticket 05 later computes a
  different fingerprint for the same logical input, and the cache would silently stop
  working while still appearing correct.
- **Produces:** fingerprint canonicalization, idempotent caching, reservation lease and
  expiry, crash recovery, retry budget and backoff, concurrency coalescing. Ticket 05
  writes single-search attempts into this envelope.
- **May write:** the attempt and fingerprint modules. No route module, no schema change.
- **External verification in Wave 1** is at the integration seam over the attempt
  repository: same input twice returns one cached result, two concurrent requests share
  one reservation, a killed process leaves a recoverable reservation, a technical failure
  stays retryable. None of these needs a real model call, which is why this ticket
  parallelizes cheaply.
- **Fixture debt:** built in Wave 1, `INTEGRATION_READY` once 05 lands and these
  behaviours are re-verified over real discovery attempts.

**Owns:** the durability and idempotency semantics over the attempt record ticket 01
froze and ticket 05 first writes — fingerprint canonicalization, idempotent caching,
reservation lease and expiry, crash recovery, retry budget and backoff, and concurrency
coalescing. Ticket 05 owns the single-search path and does not define these semantics;
ticket 09 triggers staleness and does not redefine attempt states.

**Why this is a separate slice rather than part of 05:** ticket 05 answers "what does
one search return"; this ticket answers "what happens when the same search runs twice,
runs twice at once, or dies halfway". Those are different observable behaviours with
different failure modes, and folding them together would produce one ticket whose
acceptance criteria span a single happy path and every concurrency edge at once.

**Not in this ticket:** invalidation caused by asset or projection changes (ticket 09),
and any change to what a single search returns (ticket 05). Staleness and idempotency
both end with "the cached result is not reused", which makes them look like one
problem — but the causes are opposite. Idempotency reuses a result because nothing
changed; invalidation discards it because something did. Implementing invalidation
here would mean two tickets writing lifecycle transitions on the same records, and the
one that commits second silently wins.

The distinguishing work that belongs here is the fingerprint: get its canonicalization
exact, and "did anything change" becomes a hash comparison instead of a judgement call
spread across two tickets.

**Verify with:** the shared command set, plus repeated-input, changed-input,
concurrent-request, timeout, malformed-response, storage-conflict, and restart tests at
the HTTP or integration seam.

**Status:** ready-for-agent

## Escalation — no failure class for an expired lease

Raised by ticket 06 during Wave 1, per the integration contract §四 rule that a
branch which needs to write a file it does not own records the need instead of
changing it in place.

Criterion 8 requires a reservation that dies mid-flight to be "recovered or
safely marked retryable rather than assumed successful". Recovery works by
finding leases that expired without the holder reporting an outcome, and it has
to settle each one with a `DiscoveryFailureClass`. The frozen enum in
`domain/enums.py` offers `MODEL_UNAVAILABLE`, `MODEL_TIMED_OUT`,
`MALFORMED_MODEL_OUTPUT`, `RUNTIME_VALIDATION_REJECTED`, `STORAGE_CONFLICT` and
`STALE_BINDING` — **none of them means "the process holding this reservation
never came back"**.

`recover_expired_reservations` currently records `MODEL_TIMED_OUT`, which is the
only class that carries "in flight and never returned". It is inaccurate in a way
that matters for audit: a genuine model timeout and a killed worker are different
operational faults with different fixes, and after recovery the two are
indistinguishable in the attempt history. A retry-rate dashboard built on this
column would attribute every crash to local inference.

Ticket 06 does not resolve this: `DiscoveryFailureClass` lives in
`domain/enums.py`, which §四 marks frozen with ticket 01 as the owner. Adding a
member here would be an ownerless change to a vocabulary that tickets 05, 07 and
09 also read, and the divergence would surface only at integration.

**What 01 has to decide:** either `DiscoveryFailureClass` gains a
`LEASE_EXPIRED` member, or the reuse of `MODEL_TIMED_OUT` is ratified explicitly
so that audit consumers know the column conflates the two. The first keeps the
failure vocabulary honest; the second avoids widening an enum three other
tickets switch on.

Until that lands, recovery behaviour is verified as specified — expired leases
become retryable, never successful — and the class it records is documented at
the call site rather than silently chosen.

## Acceptance criteria

- [ ] The fingerprint covers the current card version/hash and projection hash; the
      sorted eligible historical asset, version, and projection hashes; model identity
      and frozen revision; prompt version; role and validation contract versions;
      inference parameters; and prefilter configuration version.
- [ ] Fingerprint canonicalization is specified: field order, sort keys, null and
      empty-collection representation, number and timestamp encoding, Unicode
      normalization, hash algorithm, and a fingerprint schema version. Left unspecified,
      two callers serializing the same logical input produce different fingerprints,
      and the cache silently stops working while still appearing correct.
- [ ] Repeating discovery with the same fingerprint returns the same candidate or
      no-match and makes no additional model call. (GRAG-07)
- [ ] Timeout, model unavailability, malformed structured output, storage conflict, and
      Runtime validation failure are retained as auditable attempts and are never
      reusable as semantic no-match; an explicit retry is permitted within the bounded
      budget. (GRAG-08)
- [ ] The retry budget is explicit: maximum attempts, backoff, timeout, which error
      classes are retryable, whether a retry opens a new attempt record, and the
      terminal outcome when the budget is exhausted. An unbounded retry on a validation
      rejection would hammer the model with a request that is failing for a
      deterministic reason and can never succeed.
- [ ] A changed current card, newly eligible or changed historical asset, changed
      projection, or formally versioned model/prompt/configuration change produces a new
      fingerprint. (GRAG-09)
- [ ] Concurrent requests for one fingerprint share a single reserved run, with the
      reservation state, lease, and expiry defined. Without a reservation, two
      simultaneous clicks produce two model calls and two candidate rows for one logical
      question, and whichever commits last silently becomes the answer.
- [ ] A discovery attempt is reserved durably before local inference, so a crash
      mid-flight is recovered or safely marked retryable rather than assumed successful.
- [ ] The UI attaches duplicate clicks to the running fingerprint and shows technical
      failure with an explicit retry action, visually distinct from no-match.
- [ ] Observability records safe fingerprint, projection, prompt/config,
      validation-contract, outcome, retry, timing, and model metadata. Prompt and
      response bodies are excluded, because persisting them would create a second store
      of the private content the local-inference boundary exists to contain.
