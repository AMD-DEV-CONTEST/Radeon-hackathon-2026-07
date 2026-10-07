# Look Twice V8 Compact Evidence

This directory is the compact, judge-facing evidence surface. The published
[`v8-contract-progress-nbv`](https://github.com/eason4kim-rocket/look-twice/tree/v8-contract-progress-nbv)
source branch remains authoritative for source code, validators, schemas,
replay media, complete reproduction instructions, and the immutable raw
archive.

> **Evidence status:** the verified compound contract-progress
> result is integrated as a compact summary and cryptographic source index.
> The final 19-page technical-report PDF passed 19/19 rendered-page QA, and
> output/site/official copies are byte-identical at SHA256
> `7dc0b453191a4ea215e432f22de6b374319c8df72580026f3adc8fa064291143`.
> The package has 158 manifest entries, 159 checksum entries, and 160 total
> files.

## Files

- `LOCKED_TEST_REPORT.public.json` is a deterministic public rendering of the
  one-shot locked report. It removes only machine-location fields named
  `path`, `opened_seal`, and `live_rows_path`; metric values, gates, identities,
  population counts, discipline flags, and timestamps are preserved.
- `V8_FROZEN_INFERENCE_BENCHMARK.json` records the exact-checkpoint FP32
  preloaded-tensor model-forward benchmark on the captured Radeon/ROCm host.
- `V8_FROZEN_ROCM_TELEMETRY.json` records a clean-GPU preflight followed by 61
  raw `rocm-smi` samples during a 60-second exact-checkpoint model-forward run.
- `V8_LOCKED_INPUT_PACK_MANIFEST.json` verifies the separately released
  pre-open 400-world, 3,200-record input-and-label archive without model
  inference, array extraction, or a locked-test rerun.
- `V8_FROZEN_IMPORT_MANIFEST.json` identifies the 21 guarded source and
  evidence files used by the deterministic repository verifier.
- `V8_TASK_UTILITY_DERIVATION.json` derives the paired locked task-utility table
  and the separate non-locked seed-105400 cost ledger from already archived
  evidence. It does not rerun V8, reopen the locked test, or change a model or
  threshold.
- `V8_FROZEN_CHALLENGE_FEASIBILITY_AUDIT.json` is a post-hoc descriptive
  offline oracle-feasibility classification of the 30 archived active-policy
  episodes. It does not rerun an episode, expose oracle labels to the
  controller, or replace the preregistered primary endpoint.
- `challenge_102500_102529/CHALLENGE_REPORT.json` is the preregistered
  30-world paired analysis, including the primary full-chain endpoint,
  per-seed outcomes, confidence intervals, receipt agreement, operational
  burden, and telemetry summary.
- `challenge_102500_102529/RUN_MANIFEST.json` binds the public
  preregistration, runner/validator identities, frozen runtime closure,
  balanced schedule, one-shot execution contract, and completion status.
- `challenge_102500_102529/ROCM_TELEMETRY.json` retains every two-second
  full-subprocess-wall `rocm-smi` sample, including idle periods.
- `challenge_102500_102529/VERIFICATION.json` is the deterministic,
  independently reproduced validator result. It reports `passed=true`,
  zero errors, and 60/60 expected raw episode records read.
- `challenge_102500_102529/RAW_ARCHIVE_SHA256SUMS` is a packaged copy of the
  raw archive's internal checksum index. It binds all 194 other files inside
  that 195-file archive; its paths are archive-relative and are not a second
  checksum index for this compact package.
- `contract_progress_challenge_102530_102549/RESULT_SUMMARY.md` gives the
  independently verified 20-world compound efficiency result in judge-facing
  form.
- `contract_progress_challenge_102530_102549/EVIDENCE_INDEX.json` binds the
  complete source-repository preregistration, formal report, verification,
  telemetry, run manifest, and formal checksum index by path and SHA256. The
  approximately 15 MB raw tree is not duplicated here.
- `dual_body_dynamics_160820_160839/REPORT.json` is the source-bound 20-seed
  additive dual-body rigid-dynamics report. It is separate from the frozen
  active/passive policy endpoint.
- `dual_body_dynamics_160820_160839/ATTEMPT_1_TIMEOUT_AUDIT.json` retains the
  first whole-process attempt, which reached the outer watchdog before any
  report or per-seed outcome was observed.
- `dual_body_dynamics_160820_160839/RECOVERY_EXECUTION_AUDIT.json` binds the
  completed attempt to the same source, runner/URDF bytes, fixed seeds,
  thresholds, and protocol, with only the outer watchdog extended.
- `dual_body_dynamics_160820_160839/SHA256SUMS` binds those three records inside
  the evidence directory; the package-level checksum index binds this file too.
- `decision_dynamics_recovery_v2_102500_102529/` preserves the complete
  checkpointed 30-seed archived-decision replay: source binding, attempt and
  progress ledgers, 30 immutable trial receipts, 30 worker logs, report,
  execution-history logs, the formal checksum index, a post-run provenance
  review, and a package checksum index that covers every retained file except
  itself.
- `decision_dynamics_single_scene_60_102500_102519/` preserves the complete
  20-seed, one-scene 60-body prefix package: source binding, progress snapshot,
  20 trial checkpoints, report, formal execution logs, and formal/package
  checksum indexes.
- `decision_dynamics_single_scene_30_suffix_102520_102529/` preserves the
  independently complete 10-seed, one-scene 30-body suffix package with the
  same evidence classes, plus the exact prefix-report binding required for the
  limited two-report summary.

## Judge-facing findings

### Locked same-world comparison

Across 12 paired Genesis worlds, active repair qualified 11/12 direct routes
while the passive baseline qualified 0/12: a **+91.7 percentage-point** paired
gain. Both policies completed 12/12 missions. Unsafe crossings and unplanned
fallbacks were 0/24 across all policy runs, and Python/Purify Go decisions
agreed 24/24. The one conservative active detour remains in the denominator.

This is descriptive evidence for the fixed locked seed suite; it is not a
population or real-world generalization.

### Non-locked confirmatory cost ledger

Seed `105400` has `formal_result_eligible=false` and is kept separate from the
locked aggregate. Active repair reduced loaded-carrier travel from 6.404 m to
4.915 m (-23.24%) while both policies delivered the payload with zero recorded
collisions. The scout traveled 3.046 m, total robot travel increased from
6.404 m to 7.961 m (+24.32%), and the active episode took more steps. The
supported claim is movement-burden transfer from the loaded carrier to the
scout, not lower total distance or latency.

### Publicly preregistered same-generator supplement

Before execution, Commit A fixed the challenge protocol, seeds `102500-102529`,
runner, validator, frozen runtime dependencies, endpoint, telemetry cadence,
balanced order, and no-retry rule; Commit B changed only the preregistration's
Commit-A binding. The one-shot execution then produced 60/60 valid episodes:

| Full-chain outcome | Active repair | Passive baseline |
| --- | ---: | ---: |
| Direct route | 29 / 30 (96.7%) | 0 / 30 (0.0%) |
| Wilson 95% CI | 83.3-99.4% | 0.0-11.4% |
| Mission complete | 30 / 30 | 30 / 30 |
| Unsafe | 0 / 30 | 0 / 30 |
| Fallback | 0 / 30 | 0 / 30 |

The paired gain is **+96.7 percentage points**; exact two-sided McNemar
`p=3.73e-9`. The sole active non-direct case, seed `102515`, remained safe
and completed by detour. Receipt-level Python/Go agreement was 250/268
(93.3%); all 18 disagreements were Python-admit/Go-deny and remained
`effective_admit=false`. A post-hoc descriptive audit (not a preregistered
endpoint) found the same inspectable Go signature in all 18: active-policy
corridor B, one Go-qualified root, and the inconclusive set
`{clear, blocked}`. Four concerned a non-selected corridor; the other 14
preceded the final selected-corridor joint admit. This audit changed no
runtime, calibration, or threshold.

The preregistered primary endpoint remains **active 29/30 versus passive
0/30**. The separate post-hoc descriptive offline oracle-feasibility audit
found that all **29/29** worlds with at least one oracle-clear corridor went
direct and selected an oracle-clear corridor. Seed `102515` was the sole world
with both corridors oracle-blocked and completed by safe detour. Therefore
**30/30 active route outcomes matched offline feasibility**. Oracle labels
were never available to the controller, and this is not a preregistered
endpoint. Across the 30 active records, unsafe was false, collision count was
zero, and fallback was false.

Active repair reduced mean loaded-carrier logical path from 6.404 to 4.961
(-22.5%) while adding 2.980 scout path; total logical-role path increased from
6.404 to 7.941 (+24.0%). This is a burden-shifting result on one shared
Genesis chassis, not a claim of lower total motion, energy, throughput,
latency, or two simultaneously simulated physical robots.

### Additive compound contract-progress efficiency

A separate public two-commit binding preceded every seed in `102530–102549`:
Commit A `6c7b46dc3ac5044c7ed0c422fc30dee1d5b1ba1e` fixed the executable
candidate, and Commit B `427f2f729ce653df91a20db56c9fdbd16911a014`
changed only the preregistration binding. Across 20 paired worlds:

- baseline and compound candidate full-chain direct: 20/20 and 20/20;
- scout path: −40.2563% (95% bootstrap 36.0505–45.0271%);
- team path: −15.0306% (95% bootstrap 12.2563–17.6227%);
- physical captures: 50 versus 69, −27.5362% (95% bootstrap
  15.6250–37.8378%);
- negative scout and team paired deltas: 20/20 and 20/20;
- mission success: 40/40; unsafe, collision, fallback, false clear: zero;
- native/delegated candidate decisions: 30/0.

The independent verifier reported `promotion_pass=true` and validated the
exact path set, checksums, pre/post and public-remote bindings, frozen-Go
authentication, attempt reconstruction, and telemetry. This is additive
same-generator, non-locked, kinematic compound-system evidence with
`formal_result_eligible=false`; it uses no new weights, calibration, gate, or
threshold and is not a single-component, OOD, physical-robot, sim-to-real, or
replacement-primary claim.

### Separate additive dual-body rigid dynamics

Fixed seeds `160820-160839` instantiated one loaded carrier and one scout as
separate non-fixed Genesis URDF bodies. The AMD Radeon/ROCm acceptance run
passed **20/20** seeds: 40 non-fixed robot entities, zero trial-blocker contact
rows, zero carrier/scout pair-contact rows, and zero script pose writes after
`scene.build()`. Maximum tilt was 10.750 degrees, maximum parked-partner drift
was 0.018061 m, and mean scout/carrier paths were 1.645/4.760 m. Post-build
motion used only wheel-DOF velocity targets in sequential scout/carrier phases.

Attempt 1 hit an external 3,600-second watchdog before any report or seed
outcome was observed. Attempt 2 changed only that watchdog to 10,800 seconds;
source commit, runner/URDF bytes, fixed seeds, protocol, and thresholds stayed
fixed. The report passed the same verifier remotely and locally. This evidence
is additive, non-locked, and `formal_result_eligible=false`; it is not a
frozen-policy rerun, simultaneous cooperative-policy result, physical-robot
validation, sim-to-real evidence, or safety certification.

### Separate additive decision-bound rigid dynamics

Fixed seeds `102500-102529` replayed the 29 archived direct decisions and one
safe-detour decision in 30 serial, independent Genesis/ROCm scenes. Each scene
contained an active non-fixed scout, active non-fixed loaded carrier, and
passive non-fixed loaded carrier. The result passed **30/30**: 90/90 bodies
were wheel-actuated and reached, and all 29/29 direct pairs saved at least
0.50 m of simulated loaded-carrier path. Dual-blocked seed `102515` executed
the declared safe outer detour.

Mean active/passive loaded-carrier paths were 4.943529/6.243270 m, a paired
reduction of **20.8183%**. Counted Genesis blocker and active carrier/scout contact
rows were 0/0; maximum tilt was 10.579607 degrees, maximum parked-partner drift
was 0.022329 m, and post-build script pose writes were zero.

V1's one-scene 90-body execution reached four-hour and 12-hour watchdogs before
writing any report. V2 changed the execution and persistence topology: one
fixed seed per fresh subprocess and one atomic receipt per completed seed. The
retained ledger shows 30 attempt-one worker exits at zero, no observed retry or
replacement, and 30 sealed checkpoints. It does not relabel the failed V1
attempts.

The proof-scope review preserves two qualifications. The original inner
checksum index did not include attempts/progress/logs, and the source-binding
manifest omitted the directly imported `src/v4_motion.py`. A complete outer
package index now binds all retained files, and a clean 2,419-file post-run
audit found no source difference. This corroborates the run but is not claimed
as signed continuous attestation.

The 90 bodies are distinct instantiations across 30 scenes, not one
simultaneous 90-body scene. This is additive, non-locked,
`formal_result_eligible=false`, archived-decision simulation evidence - not a
live perception-policy rerun, simultaneous cooperative result, dynamic-obstacle
response, physical-robot, sim-to-real, energy, throughput, or safety result.

### Separate solver-scale two-shard rigid dynamics

The same fixed 30 archived decisions were also executed across two independently
verified Genesis/ROCm scene shards. Seeds `102500-102519` passed **20/20** in
one scene containing 60 co-resident non-fixed robots: 20 scouts, 20 active
loaded carriers, and 20 passive loaded carriers. Seeds `102520-102529` passed
**10/10** in a second scene containing 30 co-resident non-fixed robots, ten of
each role. Each shard used one initialization, one scene build, fixed-order
serial wheel-velocity actuation, its own checkpoints and report, and no resume.

Across the two exact reports, all 30 scouts, 30 active carriers, and 30 passive
carriers reached. Every **29/29** direct pair saved at least 0.50 m of simulated
loaded-carrier path; dual-blocked seed `102515` completed its archived safe
outer detour. The fixed-denominator weighted mean was **4.943605 m active versus
6.245385 m passive**, a **20.8439%** reduction. Counted blocker-contact and
active-pair contact rows were 0/0, post-build script pose writes were zero,
maximum tilt was **10.583984 degrees**, and maximum parked-partner drift was
**0.021342 m**.

The bounded topology statement is **exactly two completed scenes, 90 cumulative
distinct robot instantiations, and a maximum co-resident count of 60**. The 90
robots were never co-resident in a single scene. There was no checkpoint/state
resume and there is no synthetic combined execution report; the weighted values
above are a transparent arithmetic summary of two independently verified
reports. This does not complete or relabel V1's timed-out one-scene 90-body
attempt.

Both shards are additive, non-locked, archived-decision, fixed-order serial,
simulation-only evidence with `formal_result_eligible=false`. They do not rerun
the live perception-policy loop, demonstrate simultaneous cooperative fleet
control or dynamic obstacles, validate a physical robot or sim-to-real transfer,
measure throughput or energy, or provide safety certification. The
preregistered primary remains **active 29/30 versus passive 0/30**.

## Authoritative identities

| Item | SHA256 |
| --- | --- |
| Immutable raw locked report | `5b88d5e7683f853380f1e23123f830c6966824e3afee055af5c4fb6604f672cb` |
| Locked-open seal | `7bfe13d0d7e117f76286cb094711322b810dc44d40ddbd149bf1304713baba14` |
| Frozen vision checkpoint | `7b158726f9c00e01eec7f995674001727be03b84ff684a0cb43cba8682cd5783` |
| Final 239-second demo video | `70f0cb035498ed617421163b192a4c42856d0d8ede474582e550c1e3f9d81d05` |
| Final demo builder sidecar | `639c0c5e076798c74c6ec115f2adeb88b45bcc6d14698adbd566e7eb9a3cf6bb` |
| Task-utility derivation | `f85f6d647ea49f9bc148cf9fad6c38a34050cd8e9f8f690522b965c5ff23730b` |
| Radeon model-forward benchmark | `282b0a1bf5180d9aca75cb068b60100222eb07bf6aea9fc8a2ca46c655b14156` |
| Sustained Radeon telemetry | `0ec12a92ac4e88a97d9068e40a06f72f9dd5ecaa16503c45e2d965d4d876dde9` |
| Locked input archive | `0933053f28aca5254f13eb2eb11ce16c2f488e1880e4e282b1e4dfd7d957cfba` |
| Locked input manifest file | `421a0b1e2ebcfd20a84742a799e461fe060587fa2fc33438dfbf8cfc42f90818` |
| Vision conformal artifact | `ca4a7203eeeedbc0a155955237ffb884f7684a4431e894855f847ee69c5eed1f` |
| Go-fusion conformal artifact | `d72439827186d744de9a97306ebe1b1e15515b3cefaaa36727d53ac1ed402f97` |
| Purify Linux reference binary | `31a405b6d7e494a6add120c14b8d27b1f9f168cedaaae2afd860ccfdbd385d00` |
| Challenge preregistration | `90679e84f835c6e46983c1b219c1196506164e3c82dd1dfffec33469a73e28a2` |
| Challenge report | `59b5d464954e6e03ee4b65f689e93fd4e4ba836a6512509e98df0b7a94d186b0` |
| Challenge run manifest | `7cbafaadd0a9eb237d24999919d401866a488f76395e636b253feb409ab8681d` |
| Challenge full-wall ROCm telemetry | `463add74afa2c905cb7e63e7450f8761f3c6c3cd56ee9789633c7df0272860c0` |
| Challenge independent verification | `942f1624e6903033335e5ffbcdbc12afed4a0e8eed4e0d33ffa657f5e147a940` |
| Raw archive internal checksum index | `90d70a11d4a6fd91727c3849536e7a41124196c1c0b4e0f51779419e99105b6d` |
| Complete challenge raw archive | `171c9bab73554e1a3654c24872ade011b8423d3aca0df8eca38625a90b0854d2` |
| Dual-body dynamics report | `8a883163ff544bdf7aa9410b4b4d364e88dcee15dce15edcbd791a1d4b4fd110` |
| Dual-body timeout audit | `711547fb5f0ab928ae5cc8b6195f4e0e964a98f6df44dfa2955c67e624705d55` |
| Dual-body recovery audit | `6c3ddfa0ec2b482c1ab01a160572d01451f0bb1b495137e09a18a96018f23e6e` |
| Dual-body directory checksum index | `6470aaab8fa8ffc1132f7aea7fd0869a3e0a084bcae92d615d920730079204f2` |
| Decision-bound dynamics report | `1501e31bdc1bc353d56224f76f0a0f58de574e6c436980bc9c22a7c33104bd99` |
| Decision-bound source binding | `c40f6ba74a39ad761e4926ddb66326f33a1a645fef3c96364f9c53b9d5d3eb5d` |
| Decision-bound recovery audit | `344a948da49f89322f3486da2c025ee227dbf3454b33f7f8ab2f8acf6ea8eca4` |
| Decision-bound provenance review | `4667a9f817c882e7cbe6b358c207a2fb3cc6afec643e185e99fbd30ae0f959a7` |
| Decision-bound package checksum index | `24d3538365d2818f5e5b64c5f06ecee94bdeae1e4d3df2ab320178248bf71540` |
| Solver-scale 60-body prefix report | `3cfcf19e60ba102772d052862f44bae29eb47d84717db3d0fbe7ed3b62b24450` |
| Solver-scale 60-body package checksum index | `8d4f891e6bacbf8627a9ba441c5396525259b88b8d4350c5b84bef7db6277c55` |
| Solver-scale 30-body suffix report | `69dfd142175ea3d9f719dd5cd0dbb3126f3f7b77b74f4ad753b5f92193ce1a4e` |
| Solver-scale 30-body package checksum index | `930f41c497e8aaa6dceb4ee12f6b7b87cea189c2320e3d90d1c03e850ca16d4b` |

The public locked-report copy has a different file SHA because location-only
fields are omitted. Its content is generated by
`scripts/build_competition_replays.py`, tested for machine-path hygiene, and
can be compared with the immutable source report in the dedicated repository.

## Stable target anchors

- Evidence Console: <https://eason4kim-rocket.github.io/>
- Technical report stable target:
  <https://github.com/eason4kim-rocket/look-twice/releases/download/v8-competition-candidate/Look-Twice-V8-Technical-Report.pdf>
- Final 3:59 demo:
  <https://github.com/eason4kim-rocket/look-twice/releases/download/v8-competition-candidate/Look-Twice-V8-Demo.mp4>
- Frozen checkpoint:
  <https://github.com/eason4kim-rocket/look-twice/releases/download/v8-competition-candidate/v8_seg_v3_selected_ep22_7b158726f9c0.pt>
- Locked input-and-label archive:
  <https://github.com/eason4kim-rocket/look-twice/releases/download/v8-competition-candidate/v8-spatial-dataset-v1__locked_test__400seeds__20260720T120737Z.tar.gz>
- Frozen challenge Judge Card:
  [packaged copy](../V8-Frozen-Challenge-Judge-Card.md)
- Complete 30-world raw archive:
  <https://github.com/eason4kim-rocket/look-twice/releases/download/v8-competition-candidate/v8-frozen-challenge-102500-102529.raw.tar.gz>
- Challenge verification release asset:
  <https://github.com/eason4kim-rocket/look-twice/releases/download/v8-competition-candidate/v8-frozen-challenge-102500-102529.VERIFICATION.json>
- Packaged 60-body prefix report:
  [REPORT.json](decision_dynamics_single_scene_60_102500_102519/REPORT.json)
- Packaged 30-body suffix report:
  [REPORT.json](decision_dynamics_single_scene_30_suffix_102520_102529/REPORT.json)
- 60-body protocol:
  <https://github.com/eason4kim-rocket/look-twice/blob/v8-contract-progress-nbv/docs/V8_ADDITIVE_DECISION_DYNAMICS_60_PROTOCOL.md>
- 30-body suffix protocol:
  <https://github.com/eason4kim-rocket/look-twice/blob/v8-contract-progress-nbv/docs/V8_ADDITIVE_DECISION_DYNAMICS_30_SUFFIX_PROTOCOL.md>

The 239-second replacement MP4 and sidecar matched the published SHA256
identities on 2026-08-03. The contract-progress-integrated 19-page report and
its two copies are byte-identical at SHA256
`7dc0b453191a4ea215e432f22de6b374319c8df72580026f3adc8fa064291143`;
the final 159-entry top-level checksum index verifies the 160-file package.

## Scope

- Simulation only; no physical-robot or safety-certification claim.
- The permanent 12-pair locked aggregate, the seed-105400 non-locked public
  replay, and the 30-pair preregistered non-locked supplement are separate
  evidence surfaces.
- Perfect offline classification values apply to 3,001 decisive samples; 199
  inconclusive samples remain visible.
- Model-forward timing excludes preprocessing, Genesis, Go fusion, I/O, and
  actuation.
- The input supplement lacks original per-sample predictions and 24 raw locked
  episodes; it does not reconstruct or recompute the one-shot run.
- The 61/61 utilization result applies only to the disclosed synthetic,
  preloaded FP32 model-forward workload. No locked aggregate path-length,
  latency, mission-energy, or end-to-end utilization claim is made.
- Seeds `102500-102529` were evaluated exactly once under the frozen challenge
  preregistration. Seeds `102530-102549` were separately evaluated once per
  policy under the compound preregistration. Both are same-generator,
  non-locked supplements, not OOD or a second locked open. Seeds
  `102550-102699` remain unevaluated.
- Carrier and scout in the supplement are distinct logical-role poses,
  viewpoints, and capture roots on one shared Genesis chassis; the result does
  not demonstrate two physical devices, dual-body rigid dynamics, real-robot
  validation, sim-to-real transfer, or safety certification.
- The separate 20-seed dual-body supplement demonstrates bounded sequential
  wheel actuation by two non-fixed rigid bodies. It does not convert or rerun
  the frozen policy, demonstrate simultaneous cooperative control, or add a
  physical-robot or certified-safety claim.
- The separate 30-seed decision-bound replay consumes archived route decisions
  in 30 independent serial scenes. It is not a live policy rerun or one
  simultaneous 90-body scene, and its retained no-retry evidence and clean
  source-tree audit are not overstated beyond the disclosed formal checksum
  and source-binding scope.
- The solver-scale complement is a separate execution of those same archived
  decisions in exactly two non-resumable scene shards: 20/20 at 60 co-resident
  bodies plus 10/10 at 30. Its combined statement is cumulative 90 distinct
  robot instantiations and maximum co-resident 60, never one 90-body scene.
- The solver-scale shards are not a live policy rerun, simultaneous fleet test,
  dynamic-obstacle test, physical-robot or sim-to-real result, throughput or
  energy result, or safety certification; they do not change the primary
  **29/30** endpoint.
- Full-wall challenge telemetry includes idle periods and supports Radeon/ROCm
  execution of Genesis, frozen checkpoint inference, and Purify Go
  subprocesses. It is not control-loop latency, mission energy, or physical
  duty-cycle evidence.
- Demo narration is AI-generated with OpenAI `gpt-4o-mini-tts`, using the
  `cedar` voice and an on-screen disclosure. Chapter visuals use fixed
  composition with no `zoompan` motion.
- Integrity Shield R1/R2 and V9 research is outside the V8 submission.
