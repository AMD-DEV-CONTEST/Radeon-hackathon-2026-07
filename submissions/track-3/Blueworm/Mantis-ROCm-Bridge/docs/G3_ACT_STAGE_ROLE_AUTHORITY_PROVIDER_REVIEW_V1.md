# G3 ACT privileged stage/role authority provider review v1

Status: **local provider feasibility review; user decision required; no
provider selected or integrated**

Work package: `WP-G3-CORR-020`

## Verified outcome

Current ACT G3 has no production source for the four privileged fields required
by Candidate C:

- `stage`;
- `selected_bowl`;
- `active_side`; and
- `release_transition`.

This is not merely an omitted adapter. The learned ACT loop directly produces
autonomous 16D joint actions. It receives no high-level manipulation
transaction whose owner could authoritatively announce place, release, and
retreat.

The runtime does know the reset bowl identities and source positions. Those can
prescribe the intended bowl order and source arm under the source-task rule,
but they do not prove which bowl or arm the learned policy actually manipulates.
The strict evaluator sees bowl poses, derived velocities, gripper readback, and
terminal stack success; it does not own a live manipulation lifecycle.
`EpisodeStateTracker` validates stage events supplied by its caller for a
receipt and is not a live ACT stage provider.

Therefore a real design choice is required:

- explicit semantic authority requires a transaction owner and changes the
  current execution architecture; or
- retaining autonomous ACT requires a passive physical-event observer whose
  outputs are conservative inferences and would revise WP-019's no-inference
  rule.

## Candidate A — explicit transaction supervisor

`P020-A-EXPLICIT-TRANSACTION-SUPERVISOR`

A privileged task supervisor owns one ordered bowl manipulation, prescribes the
active side, and emits explicit place → release → retreat transitions. ACT is
then the low-level action source within the owned transaction.

Advantages:

- highest semantic authority;
- compatible with WP-019's requirement for explicit events;
- can seal a completed-release cache at a well-defined event boundary.

Risks and blockers:

- the current ACT runner has no transaction input;
- making the supervisor authoritative may require it to gate or constrain ACT
  execution;
- that hybridizes the current learned-policy architecture and may affect
  evaluation comparability;
- it is not authorized or production-ready.

## Candidate B — fail-closed physical-event observer

`P020-B-FAIL-CLOSED-PHYSICAL-EVENT-OBSERVER`

A passive privileged automaton observes reset identity, exact contacts, gripper
readback, object/support state, and motion. It emits an authority envelope only
when a single bowl, single side, validated stage event, adjacent completed
release, and fresh sealed cache are unique. Any ambiguity emits no authority.

Advantages:

- preserves the current autonomous ACT action architecture;
- offers a possible route to seed-1630 exact-pair release continuity;
- can be evaluated first against existing and adversarial traces without
  changing runtime decisions.

Risks and blockers:

- it is a safety-critical semantic estimator, not native semantic authority;
- physical predicates and any thresholds are not yet frozen;
- bimanual overlap, multiple bowl contacts, regrasp, stale cache, and
  prescription/behavior mismatch must fail closed;
- it conflicts with WP-019's current prohibition on inferring stage from pose,
  contact, action, time, or related physical observations;
- a later trace-only design needs an explicit user decision before that
  contract can be revised.

The included pure-Python prototype does not calculate any physical predicate.
It accepts only pre-adjudicated booleans and checks completeness, uniqueness,
freshness, adjacency, and ambiguity. It is an interface proof, not an event
detector.

## Candidate C — no-provider strict fallback

`P020-C-NO-PROVIDER-STRICT-FALLBACK`

No stage/role provider is created. Missing authority keeps every Candidate C
continuity-dependent context forbidden.

Advantages:

- no inferred semantic authority;
- compatible with the WP-019 fail-closed boundary;
- smallest new authority surface.

Costs and blockers:

- seed 1630 remains forbidden;
- scripted/ACT Candidate C parity cannot be established;
- the current ACT safety implementation is still unchanged, so a separate
  runtime-integration design would be required even for this fallback.

## Counterexample matrix

| ID | Counterexample | Explicit supervisor | Passive observer | No-provider fallback |
| --- | --- | --- | --- | --- |
| X020-01 | Learned timing reaches a nominal window early or late | require explicit event | no authority from time | forbid |
| X020-02 | Wrong bowl reaches a target-like pose by push or drop | transaction identity rejects | require unique identity | forbid |
| X020-03 | Open command is clipped, delayed, or blocked | require completed event | require validated readback event | forbid |
| X020-04 | One arm contacts selected and nonselected bowls | reject out-of-transaction contact | no authority for nonunique bowl | forbid |
| X020-05 | Both arms act on different bowls concurrently | requires an explicitly owned single transaction | no authority for nonunique side | forbid |
| X020-06 | Gripper opens, then recontacts or regrasps | require a new explicit sequence | require unique adjacent release | forbid |
| X020-07 | Exact pair persists from release to retreat | sealed explicit cache can qualify | require sealed validated continuity | forbid |
| X020-08 | Reset prescribes one role but ACT performs another | transaction violation | require observed unique match | forbid |
| X020-09 | Learned policy self-declares an inconsistent stage | not authority | not evidence | forbid |
| X020-10 | Release cache is absent, stale, unsealed, or non-adjacent | reject | no authority | forbid |

Rejected shortcuts are policy-step/time scheduling, pose-only progress,
action/gripper-command-only classification, contact-only classification,
policy-emitted stage heads, and per-seed replay oracles. Each fails at least
one predeclared counterexample above.

## User decision gate

No candidate is selected by WP-020 and no runtime implementation gate is open.

The recommended next *investigation* is
`P020-B-FAIL-CLOSED-PHYSICAL-EVENT-OBSERVER`, limited to a trace-only predicate
and ambiguity contract. This recommendation is pragmatic rather than an
authority claim: it is the only path that preserves the current autonomous ACT
action architecture while potentially supplying Candidate C continuity.

The alternatives are:

- choose Candidate A if explicit semantic authority is more important than
  preserving the present autonomous ACT execution architecture; or
- choose Candidate C if minimizing new semantic authority is more important
  than resolving seed 1630.

Any choice requires a new, separately authorized work package. Candidate B
also requires an explicit decision to revise the WP-019 no-inference rule
before raw physical predicates are designed.

## Evidence boundary

WP-020 is a local, standard-library-only review. It does not select or validate
a production provider, revise WP-019, implement physical predicates, define a
threshold, import code into either executor, change a safety decision, run a
simulator, establish release-tail causality, prove G3 success, or authorize a
submission, pull request, or publication.
