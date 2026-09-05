# 09 — Invalidation, staleness, and restart resume

**What to build:** Evidence changes, and relations built on it must not outlive it.
Correcting either asset, deleting one, or narrowing its privacy scope makes the affected
projections, candidates, confirmations, and detail access stale, and the UI explains
that an asset changed. Nothing is lost to a restart: the candidate, the decline, the
confirmation, and the terminal states all come back.

**Why staleness is a visible state rather than a silent refresh:** re-running discovery
automatically would replace an answer the user has already reasoned about with a
different one, at a moment they did not choose, and they would have no signal that it
changed. Marking it stale and requiring an explicit new search keeps the user aware that
the basis of their earlier comparison no longer exists.

**Why access is removed rather than hidden:** a UI that hides a stale relation leaves
the permission intact underneath. Any other caller — a replayed request, another tab,
a later run — still gets the detail. Revoking at the repository and policy layer makes
the removal true rather than apparent.

**Why invalidation removes access but preserves the event:** the decision the user made
is a fact about what happened, and the audit trail is how a reviewer reconstructs why the
system behaved as it did. Deleting the record would make an invalidated relation
indistinguishable from one that never existed.

**Why the reservation state is recovered rather than assumed:** a process that dies
mid-discovery leaves a reservation with no outcome. Treating it as successful would
publish a candidate nobody validated; treating it as failed without checking would
discard a completed model call. The reserved run has to be inspected and resolved.

**Blocked by:** 08 — Confirmation-bound deterministic evidence card and
non-contamination.

**Owns:** cross-artifact invalidation orchestration after readiness, and workflow
recovery. It does not define the state enums of the artifacts it invalidates — those
belong to tickets 03, 04, 06, 07 and 08 — and it does not handle pre-readiness M4
invalidation, which is ticket 02's.

**Not in this ticket:** defining or changing the state enums, schemas, or write paths of
the artifacts being invalidated — readiness belongs to 03, projections and the index to
04, attempts and fingerprints to 06, decisions and relations to 07, detail reads to 08.
This ticket touches every one of them, which makes redefining a state along the way
feel harmless. It fails because the owning ticket has already built and tested its
transitions: a second definition here means the same record has two lifecycle
descriptions, and which one applies depends on which code path ran.

What belongs here is the orchestration nobody else can own: the mutation × artifact
matrix, and the transaction that revokes across artifacts atomically. Write the matrix
first — with it, each case is a table lookup; without it, every event becomes a fresh
judgement about which of eight artifacts to touch, and the ones nobody thought of stay
live.

**Verify with:** the shared command set, plus GRAG-15 and GRAG-16 at the HTTP seam, and
a mutation × artifact matrix test covering each event below.

**Status:** ready-for-agent

## Acceptance criteria

- [ ] A mutation × artifact invalidation matrix is recorded, stating for each event —
      current-asset correction, related-asset change, deletion, privacy narrowing,
      projection schema change, model/prompt/config change — which of readiness,
      projection, index eligibility, attempt, candidate, decision, relation, and detail
      permission moves to which state.
- [ ] Correcting or reopening the current asset creates a new canonical version and
      invalidates its readiness, active projection, fingerprinted result, pending
      candidate, confirmed relation access, and evidence card.
- [ ] Changing a related asset invalidates projections and relations bound to its old
      version; the current asset stays unchanged but its affected candidate or confirmed
      detail becomes stale until a new discovery is explicitly run. (GRAG-16)
- [ ] Deletion and privacy narrowing invalidate eligibility and confirmed detail access
      immediately, retaining hashes and identifiers for audit but not the deleted private
      content — retaining the content would recreate, inside the audit trail, exactly the
      copy the deletion was meant to remove.
- [ ] A projection schema change creates a new projection version; old projections stay
      readable for audit but are not mixed with new projection contracts in one discovery
      call, because a mapping validated under one role contract has no defined meaning
      under another.
- [ ] Invalidation removes access at the repository and policy layer, not only in the
      interface.
- [ ] Decisions and attempts remain auditable after invalidation.
- [ ] Restart restores candidate, decline, confirmation, permission, and terminal
      discovery state from SQLite. (GRAG-15)
- [ ] A restart during in-flight discovery inspects the reserved attempt and resolves it
      to recovered or retryable, and never reuses a model result produced under a
      superseded fingerprint.
- [ ] The UI renders the stale state, hides candidate and detail actions, explains that
      an asset changed, and requires a new ready projection and discovery.
