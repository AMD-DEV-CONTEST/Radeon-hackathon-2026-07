# 07 — Confirm and decline with fail-closed bindings

**What to build:** The candidate is a proposal to the user, and only the user's explicit
decision converts it into access. Confirming creates the durable bilateral relation and
unlocks exactly one historical asset. Declining is a durable answer: the candidate stops
asking, and detail stays locked. Any request whose bindings do not match exactly fails
closed.

**Why confirmation grants access to one asset rather than to history:** a single
approval that widened retrieval to the corpus would mean the user's decision no longer
matches what they were shown. They agreed that this experience is worth comparing to
that one; they did not agree to open their archive. Scoping the grant to the confirmed
asset keeps the permission the same size as the decision.

**Why mismatched bindings are refused instead of resolved:** the tempting behavior is
to look up the user's current card and proceed. But a mismatch means the client is
acting on a state that no longer exists — a stale tab, a replayed request, a candidate
computed against an older card. Resolving it silently would grant access based on a
decision the user made about different content. Refusing turns an invisible
inconsistency into a visible one.

**Why decline is persisted rather than dismissed in the UI:** a dismissal lives in one
browser session. The next load recomputes the same fingerprint, gets the same cached
candidate, and presents it again. The user would have to decline repeatedly, and would
reasonably conclude the decision does not stick.

**Blocked by:** 05 — Explicit discovery returning zero or one validated candidate.

**Owns:** decision records, confirmation writes, durable relation creation, and
permission grants — all in one transaction. Ticket 08 only reads the confirmed relation
and never creates one.

**Not in this ticket:** rendering the evidence card or reading historical detail
(ticket 08). Confirmation and "show me the comparison" feel like one user action, so
building both here is the natural move — and it fails this way: the permission write
and the detail read end up in one code path, and no test can then prove that a request
arriving with a valid confirmation but a stale binding is refused, because the refusal
and the render share a branch. Keeping the grant separate from the read is what makes
the grant testable on its own.

The work that belongs here is the truth table: same decision repeated, opposite
decision on a settled candidate, unknown candidate, stale card version, concurrent
writes. Each needs a defined outcome, and each is a way a permission could be created
that the user never granted.

**Verify with:** the shared command set, plus GRAG-10, GRAG-11, GRAG-12 and GRAG-18 at
the HTTP seam.

**Status:** ready-for-agent

## Acceptance criteria

- [ ] A decision carries candidate identifier, related asset identifier, expected
      current card version and hash, and confirm or decline.
- [ ] Requesting historical detail before confirmation is denied by the Runtime and
      reads no historical detail. Reading it and withholding it in the response would
      already have loaded the content the gate exists to defer. (GRAG-10)
- [ ] Confirmation creates the durable bilateral relation, bound to the candidate, both
      asset versions, both projection hashes, and the current card hash, in the same
      transaction as the decision. Splitting the write across tickets or transactions
      would allow a confirmed decision with no relation record, and detail access would
      then depend on which half committed.
- [ ] Decline persists against its bound candidate, detail remains denied, and the
      declined candidate does not re-present in the same state. (GRAG-11)
- [ ] Mismatched, stale, unknown, or conflicting bindings are rejected and create no
      permission. (GRAG-12)
- [ ] Repeating the same decision is idempotent; submitting the opposite decision on a
      settled candidate is refused rather than overwriting, so the audit trail records
      what the user actually decided and when.
- [ ] Runtime authorization reads the persisted confirmation, re-projected at each
      policy evaluation. Trusting a client-supplied flag or a value cached in run state
      would let a request assert its own permission, or let a long-running session keep
      using a relation that has since been invalidated.
- [ ] Decisions are append-only; later invalidation removes access rather than erasing
      the event, and a concurrent write never overwrites a newer decision.
- [ ] `NO_MATCH` and `DECLINED` preserve the typed handoff that M5 route evaluation
      needs, so a user whose comparison found nothing is not blocked from continuing.
      (GRAG-18)
- [ ] The UI renders declined and confirmed states from backend contracts rather than
      filtering locally, because a local filter hides the candidate without removing the
      permission behind it.
