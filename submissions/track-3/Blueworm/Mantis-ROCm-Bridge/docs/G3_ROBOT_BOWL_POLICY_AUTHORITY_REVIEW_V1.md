# G3 robot-bowl policy-authority review v1

Status: **local candidate review; user decision required; not integrated**

Work package: `WP-G3-CORR-018`

## Outcome

The 42 unresolved robot-bowl contexts from WP-G3-CORR-017 are now partitioned
into five exact equivalence classes and evaluated under three policy-authority
candidates. No candidate is selected, and no runtime behavior was changed.

The review deliberately separates three questions:

1. What should each disputed context mean?
2. What counterexample does each answer create?
3. Can both current executors supply the inputs needed to apply that answer?

Implementation feasibility is not treated as safety authority.

## Exact 42-context partition

| Class | Count | Scripted | ACT G3 |
| --- | ---: | --- | --- |
| Selected bowl, nonclamp robot geometry | 12 | allow through selected-bowl skip | forbid |
| Nonselected bowl, place/release, inactive or unknown clamp | 12 | forbid | allow |
| Nonselected bowl, retreat, active clamp | 3 | forbid | allow |
| Nonselected bowl, retreat, inactive or unknown clamp | 6 | forbid | allow |
| Nonselected bowl, other stage, any clamp relation | 9 | forbid | allow |

The three collider classes occur equally: 14 source-mesh, 14 rim-support, and
14 other contexts. The remaining 54 WP-017 contexts already agree and are not
revised by this review.

## Candidate A — strict consensus fail-closed

`C018-A-STRICT-CONSENSUS`

- Preserve all 54 agreed contexts.
- Classify all 42 disputed contexts as forbidden.
- Adds no new allowed collision surface.

The cost is that seed 1630 remains a safety failure at the release-to-retreat
boundary even though the exact pair is present in the completed release cache
before retreat begins. Candidate A also needs stage, selected-bowl, and
active-side context that current ACT G3 cannot supply.

## Candidate B — ACT-equivalent clamp-only

`C018-B-CLAMP-ONLY`

- Forbid the 12 selected-bowl nonclamp contexts.
- Allow all 30 disputed nonselected-bowl clamp contexts.
- Requires only pair-label robot-geometry classification.

This is the only candidate statically implementable from the two executors'
current common input surface. It is also the broadest disputed allow rule:
inactive-side, unknown-side, retreat, and other-stage clamp contacts would all
be accepted. Static feasibility is therefore not sufficient authority to
choose it.

## Candidate C — minimum evidence-gated release continuity

`C018-C-RELEASE-CONTINUITY`

- Forbid 39 disputed contexts.
- Treat only the three nonselected active-clamp retreat cells as conditional.
- Allow a conditional cell only when the exact raw pair is proven present in
  the immediately preceding completed release cache.
- Forbid when continuity is absent or cannot be proven.

This is the smallest candidate that distinguishes the observed seed-1630
stage-boundary case from a contact first appearing during retreat. It grants no
inactive-side, unknown-side, other-stage, selected-nonclamp, numeric-grace, or
collider-name-specific exception.

Candidate C is the recommended direction for the next user decision because it
has the narrowest unsupported allow surface. That recommendation is not policy
selection. It rests on one seed and requires new shared state provenance.

## Risk and counterexample matrix

| Case | A | B | C |
| --- | --- | --- | --- |
| Seed-1630 exact pair carried from release cache | forbid | allow | conditional allow |
| Same contact first appears during retreat | forbid | allow | forbid |
| Inactive/unknown clamp touches nonselected bowl during place/release | forbid | allow | forbid |
| Nonclamp geometry touches selected bowl | forbid | forbid | forbid |
| Clamp touches nonselected bowl in other stage | forbid | allow | forbid |

Rejected shortcuts:

- A rim-support-name-only exception couples safety authority to one geometry
  label and overfits one pair.
- A numeric retreat grace interval has no authorized duration or penetration
  threshold.
- Inferring ACT stage from policy step or bowl pose would introduce a new
  undocumented privileged state estimator.

## Shared-adapter implementation gate

Every future implementation requires:

- one user-selected, versioned policy identifier;
- one deterministic raw-pair parser and pair ordering;
- one shared nonempty batch aggregator;
- identical normalized context and decision evidence from both adapters;
- fail-closed missing or malformed context;
- no executor-local exceptions; and
- 96-cell static parity plus adapter round-trip tests before runtime execution.

The scripted expert currently has stage, selected bowl, active side, pair
labels, and current cached contacts.

Current ACT G3 cannot supply authoritative task stage, selected bowl, or active
side. Its `sample_safety` interface receives only `policy_step`, and its
robot-bowl decision uses pair labels. Candidate C additionally needs a
versioned exact-pair release cache and an authoritative release-transition
event in both adapters.

Therefore:

- Candidate A is blocked by missing ACT context.
- Candidate B is statically feasible but its policy risk is not accepted.
- Candidate C is blocked by missing shared stage, role, and cache context.

No adapter implementation gate is open.

## Evidence boundary

This is a local standard-library-only review based on the task pack and
WP-G3-CORR-015 through WP-G3-CORR-017 evidence. It does not select the runtime
policy, modify either executor, validate dynamic safety, infer an ACT stage,
define a numeric grace rule, establish release-tail physical causality, prove
G3 passage, authorize collection or training, establish AMD/ROCm behavior,
validate hardware safety, or authorize publication.
