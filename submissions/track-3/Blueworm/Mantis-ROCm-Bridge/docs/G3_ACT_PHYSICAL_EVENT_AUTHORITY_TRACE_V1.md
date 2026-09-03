# G3 ACT physical-event authority trace-only design v1

Status: **offline design frozen; raw extractors and positive ACT validation
required; no production provider selected**

Work package: `WP-G3-CORR-021`

## Verified outcome

The user selected WP-020 Candidate B for a trace-only investigation. WP-021
therefore revises one WP-019 design assumption: a passive observer may infer
semantic events from a versioned conjunction of physical evidence. The
revision is deliberately narrow. It does not change the WP-019 runtime module,
provider identity, a production executor, or a safety decision.

The resulting prototype is deterministic and fail closed. It consumes exact
episode/manipulation/bowl/side/cache identities plus qualitative predicate
booleans. It has no raw pose, velocity, force, penetration, command, action, or
elapsed-time input, and it defines no numeric threshold.

## Evidence audit

### Seed 1630 scripted boundary

The preserved five-frame boundary trace shows:

- the exact `bowl2`–left-clamp rim-support pair is absent at the final
  pre-release sample;
- it appears at the immediate post-release sample;
- the pre-retreat sample is the identical physics-step cache; and
- the pair persists through retreat steps 1 and 2.

This is valuable mechanism evidence, but not a learned-ACT authority sample.
The trace's named stages and weld deletion are scripted oracle fields. It has
no frozen Candidate B extractor verdict for open readback, post-release
support, or retreat separation. Its offline projection therefore emits no
inferred authority.

### Preserved 4090 ACT traces

- seed 101 contains 1200 diagnostic rows, no robot-bowl contact, and terminates
  by timeout;
- seed 107 contains one final forbidden right-wrist-pitch contact with bowl1
  and terminates by collision safety; and
- seed 108 contains one final forbidden right-wrist-yaw contact with bowl2 and
  terminates by collision safety.

These traces prove that command/readback, exact contacts, link and bowl
kinematics, and physics-step identity are available. They do not contain a
complete positive acquire → place → release → retreat lifecycle.

The local official-AMD evidence for the prior G3 multiseed run is an aggregate
README only, not a raw positive lifecycle trace. WP-021 did not connect to the
4090 or AMD hosts because the preserved local mirrors were sufficient for the
authorized design boundary.

## Frozen lifecycle

The observer has six states:

1. `no_authority`
2. `acquired`
3. `place`
4. `release`
5. `retreat`
6. `invalidated`

`acquired` is internal and emits no semantic authority. Only `place`,
`release`, and `retreat` can emit a trace authority record.

An acquisition requires a verified reset identity, exactly one observed bowl
and one observed side matching the prescription, verified selected-bowl grasp,
and a fresh contact cache. Place additionally requires the selected bowl to
remain held in a verified placement-support state.

A completed release requires all of:

- a prior authoritative place;
- active-gripper open verified from readback, not command alone;
- selected grasp physically verified absent;
- the selected bowl physically verified released;
- a verified post-release support state;
- a fresh cache; and
- no regrasp or ambiguity.

At that event the exact current robot-bowl pair cache is sealed with the
release transition sequence.

Retreat requires the directly prior completed release, continued released and
supported state, and physically observed separation motion. A retreat command,
stage label, action, policy step, or nominal time is insufficient. This creates
an unavoidable inference latency: the first commanded retreat sample remains
release-authoritative or has no authority until motion is observed.

## Ambiguity and ordering

Missing or nonunique bowl/side evidence, a prescription mismatch, simultaneous
arms, multiple bowls, command/readback divergence, stale cache, changed
evidence at one physics step, stage skip or regression, release without place,
retreat without adjacent release, regrasp, forbidden nonclamp collision, or a
missing extractor contract invalidates the current manipulation. The latch
cannot silently recover on a later frame.

Only one transition may occur per distinct physics observation. An identical
same-step observation is idempotent; changed evidence at the same step is
ambiguous and invalidating.

## Fixture boundary

Five fixture roles are frozen:

- one synthetic normative sequence proves the contract path only;
- the seed-1630 scripted boundary projection fails closed because physical
  extractors are not frozen;
- ACT seed 101 remains at no authority; and
- ACT seeds 107 and 108 invalidate on forbidden nonclamp collision.

The synthetic case is the only fixture that emits place, release, and retreat.
It is explicitly marked non-production and cannot be cited as learned-ACT
validation. All 12 predeclared counterexamples yield no authority or
invalidation as specified.

## Why this is not production-ready

The design still needs separately authorized, versioned raw extractors for:

- unique selected-bowl manipulation;
- unique active-side manipulation;
- selected-grasp present and absent state;
- placement support before and after release;
- gripper open readback;
- retreat physical separation;
- cache freshness and same-step identity; and
- regrasp/conflicting-contact detection.

Those extractors may require numeric thresholds. WP-011 and WP-012 already
show that small-panel post-hoc initial-state and contact thresholds are not
promotable, so WP-021 deliberately does not fit them on seed 1630 or the three
failure traces.

WP-019 also freezes an explicit shared provider identity. The inferred
trace-provider provenance is different. A later schema decision and positive
learned-ACT trace set are required before compatibility or runtime integration
can even be proposed.

## Next gate

The next safe work package should be an evidence-design gate, not a runtime
integration:

1. define raw extractor candidates and predeclare their validation criteria;
2. obtain at least one preserved positive learned-ACT lifecycle plus
   adversarial traces without fitting thresholds after seeing outcomes;
3. validate ambiguity, latency, false-positive, and false-negative behavior;
4. then decide whether to revise the WP-019 runtime schema or abandon
   Candidate B in favor of the explicit supervisor or strict fallback.

No extractor, threshold, simulation, collection, training, inference, runtime
integration, controller/safety change, submission, commit, PR, or publication
is authorized by WP-021.
