# 11 — External W7900 exact-head local-inference gate

**What to build:** On the approved Radeon Cloud loopback vLLM path, at the exact commit
under review, the real production model produces one valid structured relation proposal
on the cross-topic positive fixture and one honest semantic no-match on the
hard-negative fixture. The run is recorded with exact model and runtime identity.

**Why a deterministic fake cannot stand in:** the fake was written to return what the
validator accepts, so it proves the validator and the workflow, not the model. The claim
being made here is that a real local model, on real hardware, can produce a schema-valid
structured proposal over these graphs — and the only evidence for that is the model doing
it. E4's first blocker was this exact model failing on an oversized payload, which no
fake would have surfaced.

**Why the commit must be exact:** the payload shape, prompt version, projection contract,
and validation rules all changed during E5. A gate run against an earlier head proves the
model handled a different input, and the difference is invisible in the packet unless the
commit is pinned.

**Why local inference at all:** the alternative is sending Experience Asset content — a
person's own account of their work, their decisions, and their mistakes — to a closed
remote API. The local path is what makes the privacy claim in this product true rather
than aspirational, and it is also what the Track 2 evidence requirement is asking about.

**Blocked by:** 10 — Local deterministic evidence packet.

**Environment:** requires Radeon Cloud W7900/ROCm/vLLM. This ticket cannot be run or
verified on an Apple Silicon or other non-ROCm machine. When that environment is
unavailable, the correct terminal state is `BLOCKED` with the reason recorded — not a
downgrade to a fake run, and not an inherited claim from a previous packet.

**Not in this ticket:** no product code changes, no fixture changes, no performance or
throughput claim, and no substitution when the hardware is missing. If the run fails or
the environment is unavailable, the temptation is to adjust the fixture or the prompt
until something passes. That fails because it changes what is being measured: the claim
is that the model handles *these* graphs under *this* contract, and a fixture tuned to
make it pass has quietly replaced the question. A failure recorded honestly is a real
finding — it is the same class of finding as E4's payload blocker, and it is more
useful than a pass obtained by moving the target.

Spend the effort on making the run reproducible by someone else: exact commit, model
manifest and revision, invocation, and captured identity. Then whether it passes or
fails, the result is evidence.

**Owns:** the real local-inference gate and its evidence.

**Status:** ready-for-agent

## Acceptance criteria

- [ ] The runner, owner, environment prerequisites, exact checkout commit, model
      manifest and revision, and vLLM invocation are recorded before the run.
- [ ] The approved loopback path completes one positive structured proposal on the
      cross-topic positive fixture at the exact review head.
- [ ] The same path completes one semantic hard-negative on the hard-negative fixture at
      the same head.
- [ ] Model and runtime identity, timings, token counts, and safe reason codes are
      captured; prompt and response bodies are not, since persisting them would move
      private Experience Asset content out of the local boundary this gate exists to
      demonstrate.
- [ ] A prior packet, a deterministic fake, or a run at a different commit is not
      accepted as evidence for these claims.
- [ ] If the environment is unavailable, the recorded state is `BLOCKED` with the reason,
      and E5 promotion waits rather than proceeding on an unproven claim.
- [ ] @kinnyuww records the E5 lightweight gate result before Ready or merge. Green CI
      alone does not promote E5, because CI runs the fake and therefore cannot speak to
      the claim this ticket makes.
