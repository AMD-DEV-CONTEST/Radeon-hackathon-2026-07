# On-Policy Distillation Execution Contract V1

This contract implements the non-runtime mechanics for canonical TODO
0701–0750 while keeping every unobserved model result open.

## Reuse and research boundary

The method matrix reuses TRL GKD as the implementation surface and keeps
off-policy KD, on-policy KD, OPSD, SDFT, TCOD, CaOPD and no-KD as explicit,
non-interchangeable arms. THUNLP OPD supplies the teacher/student dynamics
reference. TCOD supplies the multi-turn trajectory-KL failure hypothesis and
the short-to-medium-to-long temporal curriculum. These references are design
inputs, not reproduced results.

## Executable protections

- Privileged evidence, critique and repair are training-only fields and are
  disjoint from deployment inputs.
- Student rollouts must be student-generated and teacher-evaluated; hidden
  reasoning cannot be persisted and teacher-output rights must be approved.
- Forward KL, reverse KL, JSD, top-k overlap, token advantage and normalized
  fork entropy are implemented with strict probability validation.
- Self-correction, verification and backtracking each require 98% retention.
  Style-token KL is clipped more tightly than general pointwise KL.
- The curriculum is ordered short (4 turns), medium (16), long (64), and the
  experiment has a two-hour hard stop without silent extension.
- Independent monitors detect trajectory-KL explosion, teacher mismatch,
  absent information gain, overconfidence, verification/backtracking loss and
  diversity collapse. Any failure makes a run ineligible for promotion.

## Truth boundary

The planned card keeps token efficiency, capability gain and retention,
calibration, long-trajectory success, rollout and diagnostic artifacts,
negative experiments and the selected adapter as `null`.

TODO 0713–0714, 0737–0741 and 0743–0750 remain open until approved teacher
rights, frozen revisions, actual Radeon rollouts, teacher evaluations, KD
runs, negative experiments, reports and a selected checkpoint are observed.
