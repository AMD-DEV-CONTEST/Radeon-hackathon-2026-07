# WP-FRAMEWORK-MVP-002 terminal receipt

Date: 2026-07-29  
Work package: `WP-FRAMEWORK-MVP-002`  
Terminal: `COMPLETE_FRAMEWORK_PROFILE_AND_READ_ONLY_PLANNER_VERIFIED`

## Verified outcome

The project now has a schema-v1 robot-port profile validator and deterministic
read-only stage planner, a blocked copy-and-edit template, an evidence-bounded
Mantis `stack_bowls_three` reference profile, and a synthetic validation-only
fixture.

The Mantis profile resolves all required local references and preserves the
existing negative ACT G3 result as `0/10`. It does not promote learned-policy
capability, Mantis asset redistribution, clean-room reproduction, public
submission, a Pull Request, or publication.

## Implementation corrections

Two initial assumptions were rejected before terminal promotion:

1. State and action dimensions cannot be required to match in a generic
   framework. Schema v1 uses independent policy/physical state/action
   dimensions and ordered fields.
2. Controller, safety, data, policy, and evaluation cannot be left implicit in
   stage prose. They are required, reference-checked profile sections.

These corrections are implemented in the final source and covered by negative
and positive tests.

## Verification boundary

- Focused profile/planner tests: 22/22 passed after parity promotion.
- Original contract validator: `valid=true`; pre-existing blockers remain
  explicit.
- Full regression after parity promotion: 1085 discovered, 1083 functional
  passes, and exactly two historical immutable source-pin sentinel failures.
- Existing Mantis runtime/controller/data/ACT/safety runner files remained
  byte-identical to the hashes frozen in `configs/framework-mvp-v2.json`.
- No simulator, remote host, data collection/export, training, inference,
  process stop, commit, submission, Pull Request, or publication action was
  performed.

Final post-promotion counts and artifact hashes are recorded in
`terminal.json` and `RECEIPT.SHA256SUMS`.

## Claim boundary

This receipt proves a generic declarative profile surface, safe local reference
validation, deterministic read-only planning, and parity of one existing
Mantis reference profile. It does not prove a second real robot port, generic
runtime execution, ACT task success, changed Mantis behavior, or competition
acceptance.
