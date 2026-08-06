# G3 shared robot–bowl adapter context v1

Status: **local static contract complete only after acceptance; runtime
provider required**

Work package: `WP-G3-CORR-019`

## Outcome

The user selected `C018-C-RELEASE-CONTINUITY` as the design baseline. This
phase turns that choice into a strict shared context and pure-Python static
adapter model. It is not a runtime safety-policy integration and does not
change either production executor.

Candidate C preserves all 54 contexts on which the frozen scripted and ACT
classifiers already agree. Of the 42 former divergences, it forbids 39 and
makes only three nonselected-bowl, active-clamp, retreat contexts eligible for
an allow decision. Eligibility requires the identical exact geometry pair in
the sealed cache from the immediately preceding completed release.

## Explicit authority envelope

Every adapted contact batch carries:

- an opaque episode identity;
- a positive manipulation identity;
- an explicit transition sequence;
- an explicit normalized stage;
- the exact selected-bowl entity;
- the explicit active side;
- a current contact cache bound to its most recent physics step;
- optionally, one sealed completed-release cache.

This is privileged safety state and must never enter the ACT policy
observation. The ACT adapter may not infer stage from policy step, elapsed
time, bowl pose, action, or contact. The exact authority-provider identity is
`shared_privileged_safety_authority_v1`.

## Exact-pair identity

One raw pair must contain exactly one Mantis geometry label and one bowl
geometry label separated by ` <> `. Either raw order is accepted, but the
canonical identity is always bowl first:

```text
bowl2:bowl_link <> mantis:left_clamp_left_link:competition_rim_support_collision
```

Collections are validated, deduplicated, and sorted by canonical identity.
There are no link, bowl, collider-class, or geometry wildcards. Malformed or
ambiguous pairs are rejected.

## Completed-release continuity

A retreat pair is continuity-eligible only when all conditions hold:

1. its normalized context is one of Candidate C's three conditional cells;
2. a completed-release cache is present and sealed;
3. episode, manipulation, selected bowl, and active side match exactly;
4. the retreat transition sequence equals the release transition sequence
   plus one;
5. the current cache does not precede the release cache in physics time; and
6. the identical canonical pair occurs in the completed-release pair set.

Anything missing, stale, non-adjacent, mismatched, unsealed, or newly appearing
at retreat is forbidden. No duration, penetration threshold, grace window, or
collider-specific shortcut exists.

## Static adapter gate

The scripted adapter consumes explicit stage labels and the operation roles
already present in the scripted control flow, plus a future sealed release
record. The ACT static adapter consumes the serialized shared authority
envelope and verifies that its raw pair set exactly matches the authority
cache.

Equivalent explicit fixtures must produce identical:

- canonical exact-pair identities;
- normalized five-dimensional contexts;
- continuity outcomes and rejection reasons;
- pair decisions; and
- nonempty batch decisions.

The adapter source itself is preserved as provenance but excluded from the
parity fingerprint.

## Seed-1630 regression and counterexamples

For the exact seed-1630 pair, the release cache and retreat cache both identify
physics step 12023. With matching episode/manipulation/role identity and
adjacent release-to-retreat transitions, Candidate C returns `allow`. Removing
the pair from the release cache, changing any identity, unsealing the cache,
making the transition non-adjacent, or presenting a new retreat pair returns
`forbid`.

This is a one-seed regression fixture. It does not establish generality or
prove the physical cause of the release-tail contact.

## Remaining implementation gate

The frozen production ACT runtime exposes robot–bowl pair labels but has no
authoritative task stage, selected bowl, active side, or completed-release
transition record. Static parity therefore does not open runtime integration.
The remaining gate is:

`BLOCKED_MISSING_ACT_AUTHORITATIVE_STAGE_ROLE_PROVIDER`

A later phase must select and independently authorize a privileged,
policy-invisible provider before modifying `GenesisClosedLoopRuntime` or the
scripted executor. It must not silently promote a policy-step or pose heuristic
to authority.

## Evidence and external boundary

AMD and 4090 use are standing-authorized for in-scope project work, but neither
is needed for this static phase. No simulator, collection, export, training, or
evaluation result is created here. Competition submission, GitHub pull request,
and public release still require separate explicit user permission.

## Claim boundary

WP-G3-CORR-019 can establish explicit context identities, complete Candidate C
static decisions, lossless serialization, and scripted/ACT fixture parity. It
cannot establish a production ACT authority provider, runtime safety, dynamic
behavior, release-tail causality, multi-seed generality, G3 success, real-robot
safety, submission readiness, or publication authority.
