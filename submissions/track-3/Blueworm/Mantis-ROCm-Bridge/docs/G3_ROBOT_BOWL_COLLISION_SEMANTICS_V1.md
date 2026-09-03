# G3 robot-bowl collision semantics v1

Status: **local authority-neutral design; not integrated**

Work package: `WP-G3-CORR-017`

## Outcome

This design gives the scripted expert and ACT G3 one normalized vocabulary for
describing a robot-bowl contact. It faithfully models both current classifiers
and returns `unresolved` whenever they disagree. It does not choose a runtime
safety policy, and no runtime behavior was changed.

The pure-Python model is
`src/mantis_rocm_bridge/robot_bowl_collision_semantics.py`. Neither current
executor imports it.

## Why an authority-neutral result is required

`WP-G3-CORR-015` observed the exact seed-1630 target pair after release and
before retreat. `WP-G3-CORR-016` established that the scripted expert rejects
that pair during retreat while ACT G3 accepts it. The task pack requires zero
safety failures, but it does not provide an authoritative robot-bowl contact
allowlist.

Selecting either current rule here would therefore turn an implementation
detail into an unsupported competition-safety decision. The shared design
instead records three decisions:

- `allow`: both frozen classifiers allow the normalized context;
- `forbid`: both frozen classifiers forbid it;
- `unresolved`: the two classifiers disagree.

`unresolved` is evidence of a missing authority decision. It is not an
automatic allow, automatic forbid, or runtime fallback.

## Normalized context

One contact pair is described by five fields:

| Field | Values | Meaning |
| --- | --- | --- |
| stage | `place`, `release`, `retreat`, `other` | Normalized task-stage suffix |
| bowl relation | `selected`, `nonselected` | Relation to the active task bowl |
| robot geometry | `clamp`, `nonclamp` | Robot geometry participating in the pair |
| clamp relation | `active`, `inactive`, `unknown`, `not_applicable` | Relation to the active arm |
| collider class | `source_mesh_collision`, `competition_rim_support_collision`, `other` | Descriptive bowl collider |

Clamp geometry requires an active, inactive, or unknown relation. Nonclamp
geometry requires `not_applicable`. Unknown or malformed values fail
validation; they never default to allowed.

Collider class is preserved for evidence and future policy review. It has no
effect on either frozen current classifier.

## Frozen current classifiers

### Scripted expert

The selected bowl is skipped by safety sampling and is therefore effectively
allowed. A nonselected-bowl pair is allowed only when all of these are true:

- the stage is `place` or `release`;
- the robot geometry is a clamp; and
- the clamp belongs to the active side.

Every other nonselected-bowl pair is forbidden. When several pairs are returned
for a bowl, every pair must satisfy the exception.

### ACT G3

A pair is allowed when every robot geometry in it is a clamp. Stage,
selectedness, active side, and collider class do not affect the current
decision. A pair containing a nonclamp robot geometry is forbidden.

## Seed-1630 regression

The WP-015 target pair is:

`bowl2:bowl_link <> mantis:left_clamp_left_link:competition_rim_support_collision`

At retreat it normalizes to:

- stage: `retreat`;
- bowl relation: `nonselected`;
- robot geometry: `clamp`;
- clamp relation: `active`;
- collider class: `competition_rim_support_collision`.

The scripted result is `forbid`, ACT G3 is `allow`, and the authority-neutral
shared result is `unresolved`. This reproduces the WP-016 divergence without
changing either executor.

## Batch aggregation

Contact sets are nonempty. A forbidden pair dominates the set; otherwise an
unresolved pair makes the set unresolved; only an all-allow set is allowed.
This mirrors the fail-closed effect of the current pair loops while preserving
authority gaps explicitly.

## Future consistent integration design

A later, separately authorized implementation should:

1. freeze an authoritative answer for every unresolved context;
2. select one explicit versioned policy identifier;
3. add scripted and ACT adapters that produce the same normalized context;
4. call one shared classifier rather than maintaining executor-local
   exceptions;
5. fail closed when stage, selectedness, side, or geometry cannot be mapped;
6. emit normalized context, policy identifier, and decision in evidence; and
7. pass static adapter-parity tests before separately authorized dynamic
   validation.

The ACT adapter would need stage, selected-bowl, and active-side context that
its current classifier intentionally does not use. Supplying those fields is
an integration change and is not part of WP-G3-CORR-017.

## Candidate risks

- Promoting scripted semantics could preserve the observed retreat-stage false
  positive if that contact is physically expected.
- Promoting ACT semantics would broadly allow clamp contacts across stage,
  selectedness, and side without task-authority evidence.
- Adding a release grace interval, threshold, or collider-specific exception
  would create a new safety rule and require separate authorization.
- Altering the rim-support primitive would change geometry and physical
  behavior, which is also outside this phase.

## Evidence and claim boundary

The exhaustive normalized matrix contains 96 valid contexts. It is a static
semantic design and parity artifact based on hash-pinned source and the
WP-G3-CORR-015/WP-G3-CORR-016 evidence.

It does not identify the correct competition safety authority, validate a
repair, explain the unobserved 255-step release contact manifold, establish
dynamic parity, prove G3 passage, authorize collection or training, establish
AMD/ROCm behavior, validate hardware safety, or authorize publication.
