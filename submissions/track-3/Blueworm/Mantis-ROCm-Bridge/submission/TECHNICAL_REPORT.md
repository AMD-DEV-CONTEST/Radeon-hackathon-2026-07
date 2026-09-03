# Technical Report — Mantis-ROCm Bridge Framework

> **Language note:** English is the primary official submission language. This
> report is mirrored for navigation only by `README.zh-CN.md`.
> **Product posture:** Mantis-ROCm Bridge is a contract-driven, evidence-gated
> robot adaptation and task-porting framework. Mantis is its first reference
> case, not the product definition.
> **Result posture:** the official-AMD closed loop is a verified negative
> result. Its CUDA corrective representative completed
> `COMPLETE_NOT_PROMOTABLE`; no official AMD corrective run followed. Every
> quantitative statement cites a receipt or is marked `TODO-evidence`.
> Training loss is not task success; no AMD performance advantage is claimed.
> **Release posture:** local content and integrity gates pass for this
> candidate. Clean-room reproduction, a public PR or submission, competition
> acceptance, G3 success, convergence, robustness, real-robot safety,
> raw-asset redistribution rights, and any AMD performance advantage remain
> unproven. It is ready for an authorized public PR only after independent
> `RELEASE_GO`.

Authority: `docs/G3_FAILURE_ATTRIBUTION_SUBMISSION_SPRINT.md`,
`docs/FRAMEWORK_STORY_V1.md`, and `configs/competition-resources-v1.json`.
Evidence: `receipts/`.

Participant: **Zhiwen Su**  
Team: **Blueworm**  
Application: **Mantis-ROCm Bridge**  
License: **Apache-2.0** for original material Blueworm has the right to license

---

## 1. Product and reference task

The framework makes robot-port assumptions and promotion gates explicit across
source/target embodiment, observation/action interfaces, controllers, safety,
assets, scene, data, policy runtime, evaluation, and evidence. Its schema-v1
surface contains a blocked template, a Mantis reference profile, a synthetic
validation-only fixture, and deterministic read-only `validate/plan` commands.
The synthetic fixture is not a second real robot port, and generic runtime
execution is not claimed.

- **Track 3 (Physical AI)** of the 2026 AMD AI DevMaster Hackathon, governed by
  the rules snapshot in `configs/competition-resources-v1.json` (re-check the
  official ModelScope event page and official GitHub repository immediately
  before submission).
- **Robot task:** bimanual three-bowl stacking (`stack_bowls_three`) in the
  Tron / Mantis simulation environment, with strict staged task evaluation.
- **Hardware rule:** execution must occur on a single AMD Radeon GPU under the
  ROCm software stack, across three required stages — environment execution,
  model training, and real-time inference (`competition-resources-v1.json` →
  `hardware_execution_rule`).
- **Score weights:** robot capability 30, AMD/ROCm adoption 20, innovation 20,
  application value 20, upstream open-source contribution 10
  (`competition-resources-v1.json` → `score_weights`).
- **Submission method:** fork the official repository and open a pull request
  titled `Track 3, <team name>, <application name>`
  (`competition-resources-v1.json` → `submission`).

## 2. Framework architecture

- **Declarative profile layer:** independent policy/physical state/action
  dimensions and ordered fields; controller, safety, data, policy, evaluation,
  runtime, asset, blocker, evidence, and claim-boundary sections
  (`configs/robot-port-profile-template-v1.json`).
- **Read-only planning layer:** strict structural validation, safe
  project-relative reference resolution, optional hash checks, topological
  stage planning, and deterministic JSON output (`tools/plan_robot_port.py`).
- **Mantis reference adapter:** a 16D virtual-gripper to 18D physical-gripper
  adapter, three camera roles, the exact Tron source reset distribution, and a
  250 Hz-to-30 Hz control-resampling path. These are reference-case contracts,
  not hard-coded framework universals.
- **Policy:** Action Chunking Transformer (ACT), single frozen baseline from
  `configs/act-rocm-baseline-v2.json` — 60,000 steps, batch 8, 30-step
  action chunks, 100-step logging, 5,000-step checkpoint frequency, seed
  `20260723`, `policy.device=cuda` under ROCm PyTorch, and
  `policy.push_to_hub=false`. The policy has **51,581,840 trainable
  parameters** (`receipts/amd-act-rocm-v2-live-20260726-v1/`).
- **Evaluation:** strict staged evaluator with explicit allowed-collision
  filtering and dual-clamp contact verification for right-side grasps
  (`docs/AMD_ACT_CLOSEDLOOP_G3_GATE.md`).
- **Provenance:** a reusable, fail-closed provenance collector performs
  per-file atomic no-clobber commits and inode-verified rollback
  (`receipts/amd-act-rocm-v2-live-20260726-v1/`).

### 2.1 URDF→ROCm compiler and ROCm-native generated port

Beyond the read-only profile/planner, the framework ships a **strict
URDF→ROCm port compiler** that inspects a source URDF and emits an executable
Genesis/LeRobot/ACT/ROCm port bundle. The compiler is deterministic and
no-overwrite: it produces an **11-file bundle** with a generated runner and
**does not modify production runtime**
(`receipts/rocm-native-robot-port-terminal-20260729-v1/terminal.json`).

The compiler was exercised end-to-end on the **official AMD Radeon Cloud
instance `u-11422-e97d3fd5`** — device `AMD Radeon Graphics`, PyTorch
`2.9.1+rocm7.2.1`, HIP `7.2.53211`, Genesis `1.3.0` (revision
`084e9a43`). The generated runtime activated the **`amdgpu` backend under
strict ROCm** (`backend_requested=amdgpu`, `backend_active=amdgpu`,
`strict_rocm=true`) for a synthetic bimanual fixture `fixture-bimanual7`:
**2 arms, 14 mapped DoF (7+7), unique indices, finite initial and final
states across 2 steps, zero controller commands** — a no-command native port
that proves the Genesis-on-ROCm execution surface, not a policy result
(`receipts/rocm-native-robot-port-amd-20260729-v1/genesis-runtime.json`).

On the **same AMD device**, bounded precision tuning (seed 42, 5 warmup + 20
measured iterations) selected **bfloat16 as the recommended precision**:
bf16 inference **12.9% faster** (speedup fraction 0.1287), bf16 training
step **26.8% faster** (0.2681), max absolute error **0.0104**, cosine
similarity **0.99999**. The product state reached `ROCM_TUNING_MEASURED`;
ACT quality was **not** promoted and the artifact is **not** claimed
AMD-deployable — honest capability boundaries
(`receipts/rocm-native-robot-port-amd-20260729-v1/benchmark.json`).

This is the project's strongest **AMD/ROCm-adoption** evidence: a
compiler-driven, ROCm-native, `gs.amdgpu`-executed port with measured bf16
tuning, all produced on the official AMD cloud and covered by 49 focused
tests (`tests.test_urdf_compiler`, `tests.test_rocm_tuning`,
`tests.test_capture_rocm_port_inventory`, `tests.test_create_source_backup_bundle`).

## 3. Data

- **Original official-AMD baseline dataset:** four-seed LeRobot dataset,
  gripper contract v2 — **4 episodes / 4,738 frames**, passing archive,
  metadata, dense, real LeRobot 0.4.4 decode, and direct-Parquet gates
  (`receipts/amd-multiseed4-gate-20260726-v1/`).
- **Single-variable correction dataset:** retains seeds
  `1001/1004/1007/1008` and adds `1012/1016` — **6 accepted episodes / 7,085
  frames**, passing source identity, strict outcomes, metadata, dense
  7,085/7,085, 18-sample LeRobot CPU decode, and 18-sample direct-Parquet
  decode (`receipts/4090-multiseed6-trajectory-correction-20260727-v1/`).
  This is CUDA-development data readiness; it has not yet been promoted to the
  official AMD runtime.
- **Canonical scripted G1 episode (seed 1):** 1,177 policy frames at 30 Hz
  with three cameras, 12 consecutive strict frames, both grippers released,
  no recorded safety failure (`configs/mantis-port-config.json`).
- **Bowl asset:** three-bowl visual/collision asset (`002_bowl` model 3) from
  `TianxingChen/RoboTwin2.0`, dataset card declares **MIT**; attribution and
  source hashes preserved (`third_party/ASSET_LICENSES.md`).
- **Mantis robot asset:** NOT redistributable under current audit —
  externalized, hash-pinned dependency only (`third_party/ASSET_LICENSES.md`).
  The user permits rendered Mantis visual media in the demonstration video,
  but this establishes no general redistribution right or third-party license.
  Raw URDF, meshes, source assets, derived raw asset files, materializations,
  and asset payloads remain excluded from the public repository and Docker
  image. Repository identity is governed by
  `receipts/asset-license-public-audit-20260727-v2/README.md`; immutable v1
  `20260726-v1` remains historical and is superseded for identity only.
- **Dataset generation/materialization instructions** are present in
  `docs/REPRODUCIBILITY.md`; no dataset payload is published. Their independent
  clean-room execution remains `TODO-evidence`.

## 4. AMD ROCm training

- **Platform:** official Radeon Cloud instance `u-11422-e97d3fd5`; one AMD
  Radeon HIP device with `HIP_VISIBLE_DEVICES=0`, `ROCR_VISIBLE_DEVICES=0`,
  `CUDA_VISIBLE_DEVICES=0`.
- **Contract:** `configs/act-rocm-baseline-v2.json`. The unchanged v1 attempt
  is preserved as negative evidence — it failed before data loading because
  LeRobot 0.4.4 required `policy.repo_id` when `push_to_hub` resolved truthy,
  producing no loss or checkpoint.
- **Outcome:** the v2 run reached real dataset loading and completed the exact
  60,000-step optimization, exiting naturally with **`train.exit_code=0`** at
  **`2026-07-26T08:00:38Z`** (`launch.status=TRAINING_EXIT_0`).
- **Optimization curve (descriptive only, not convergence):** terminal v7
  snapshot contains all **600 records** from step 100 to step 60,000; first
  loss **9.945**, final loss **0.023**, observed minimum **0.023** at step
  **56,100**. All seven additive/final metric snapshots passed independent
  `sha256sum -c` verification.
- **Checkpoints:** all twelve 5,000-step checkpoints (5,000–60,000) verified —
  11 files each, 619,237,880/881 bytes, 206,494,976-byte model state and
  412,694,860-byte optimizer state, zero exact-error matches; the 60,000-step
  manifest hash is
  `fb93395602729584e2e63500be7f4edcdc4c32761af41fa21bb415daacd27fea`.
- **Telemetry:** ROCm SMI reported one KFD process, 3,027,484,672 bytes VRAM,
  51 °C edge / 62 °C junction / 54 °C memory, 60 W package power.
- **Boundary:** this closes the optimization-run gate only. Convergence,
  generalization, task success, and comparative AMD performance remain
  unproven.

## 5. Real-time inference (open-loop)

- **Gate:** `receipts/amd-act-openloop-inference-20260726-v1/` — **PASS**.
- **Outcome:** the frozen 60,000-step checkpoint loaded its saved LeRobot
  0.4.4 preprocessor/postprocessor, decoded **12 deterministic**
  first/midpoint/last observations from four episodes, and produced **12
  finite actions** on the official single AMD Radeon HIP device.
- **Safety projection:** all 12 postprojection targets passed the fixed
  18D joint-limit gate. Categorical normalized-gripper projection affected
  11 samples / 18 channels (max delta 0.01294165849685669); fixed-limit 18D
  physical projection affected four left-wrist-yaw targets (max delta
  0.010144191741943365).
- **Integrity:** `terminal_rc=0`, core status PASS, core and final-evidence
  `SHA256SUMS` independently verify with exit code 0; archive SHA-256
  `71a0fed4864ecf5a1cb8ccac7c181ca6d7a3c4c3975119d282398182a8249ac7`.
- **Boundary:** proves official-AMD ROCm open-loop interoperability only. No
  predicted action was sent to Genesis or robot hardware in this phase.

## 6. Closed-loop evaluation (G3) — negative result

- **Protocol:** evaluate the frozen 60,000-step ACT checkpoint in the audited
  Mantis `stack_bowls_three` closed loop on **exact seeds 101–110**, strictly
  sequential, single official AMD Radeon GPU, no seed replacement, no
  threshold change.
- **Acceptance criterion:** at least 6/10 strict task successes and zero
  safety failures.
- **Exact episode outcomes:**
  - Seeds 101–106 and 109–110: `timeout` after 1,200 policy/evaluator rows,
    zero safety failures.
  - Seeds 107 and 108: `collision_safety`, one safety failure each, terminal
    at row 28.
- **Aggregate:** strict task successes **0/10** (0.0 success rate); failure
  taxonomy **eight `timeout`, two `collision_safety`**; safety failures 2;
  aggregate status **`FAIL`**; aggregate exit code **2** (expected semantic
  failure, not an infrastructure crash). Started `2026-07-26T15:34:08Z`,
  finished `2026-07-26T15:58:38Z`.
- **Integrity:** all ten episode audits and CLI/manifest/semantic contracts
  PASS; aggregate and supervisor final manifests independently verify via
  `sha256sum -c` (return code 0). G3 summary SHA-256
  `069e523cfada85bbf05bd9a96b66289f0943da856f09654469589ec5b8d5e60f`.
- **Telemetry:** during-run sampling contains 2,223 single-`GPU[0]` samples,
  803 nonzero, 569 at or above 70%, maximum 87%; post-run device state
  returned to 0 with no running KFD PID.
- **Evidence:** `receipts/amd-act-closedloop-g3-multiseed-final-20260726-v1/`.
- **Static failure attribution:** representative timeout seeds 101/106/110
  have zero successful rows, negligible vertical lift, and
  `left_wrist_yaw_joint` target clipping on 108/110/158 rows. An additive
  identity correction shows that the earlier 0.45–0.60 m ordered-list-slot
  displacement values were reordering artifacts; temporally associated
  maximum XY motion is 0.000000031/0.000171487/0.014344552 m for
  seeds 101/106/110. Seeds 107/108 terminate at step 27 on exact
  bowl-to-right-wrist source-mesh collision pairs. The ranked hypotheses and
  frozen replay matrix remain in
  `receipts/amd-act-g3-failure-attribution-static-20260727-v1/`; the corrected
  identity analysis is independently hash-verified in
  `receipts/amd-act-g3-failure-attribution-static-correction-20260727-v2/`.
  Representative observation-only CUDA replay then reproduces seed 101
  `timeout@1199` with zero robot-bowl contacts and seeds 107/108
  bowl-to-right-wrist source-mesh collisions at policy steps 28/27. Every
  recorded 250 Hz to 30 Hz hold and ACT queue transition is exact. The
  terminal replay mirror, analyzer, and independent manifests are in
  `receipts/g3-r1r2-dynamic-replay-20260727-v2/`. This excludes resampling and
  queue drift for the representatives. A commanded-target counterfactual then
  shows that the recorded ACT targets for seeds 107/108 enter the same
  bowl-to-right-wrist collision families; controller tracking error is not
  required to create those families
  (`receipts/g3-commanded-target-counterfactual-20260727-v2/`). CUDA replay and
  counterfactuals are development evidence only and are not official AMD
  results.

### 6.1 Frozen single-variable correction

- **Intervention:** change only the empirical distribution of successful ACT
  trajectories from four episodes / 4,738 frames to six episodes / 7,085
  frames (`configs/act-trajectory-distribution-correction-v1.json`).
- **CUDA development training:** a fresh one-GPU ACT run completed 60,000
  steps with exit codes `0/0`, twelve 5,000-step checkpoints, 600 metric
  records, and independently verified 132-file output and 30-file terminal
  evidence manifests
  (`receipts/4090-act-multiseed6-training-final-20260727-v1/`).
- **Representative result:** the ordered CUDA seeds 101/107/108 completed on
  one RTX 4090 with zero infrastructure failures. Seed 101 timed out; seeds
  107/108 terminated on `collision_safety`. Aggregate: 0 successes, 2 safety
  failures, safety non-regression but no strict improvement. Terminal:
  **`COMPLETE_NOT_PROMOTABLE`**
  (`receipts/4090-g3-corrective-representative-terminal-20260728-v2/`).
- **AMD decision:** because the required strict-improvement dependency failed,
  the prepared official-AMD corrective package was not executed.
- **Boundary:** CUDA optimization and a terminal representative comparison do
  not establish correction effectiveness, task success, AMD corrective
  execution, convergence, or generalization.

## 7. Migration and engineering contributions

These are **framework and AMD/ROCm engineering contributions**, reported as
in-repository capability, not as accepted upstream contributions:

- A strict robot-port profile and read-only planner that make embodiment,
  controller, safety, data, policy, evaluation, runtime, asset, and evidence
  boundaries auditable before execution
  (`receipts/framework-mvp-terminal-20260729-v2/`).
- A strict **URDF→ROCm port compiler** emitting a deterministic 11-file
  executable bundle, verified by a synthetic bimanual 7+7 `gs.amdgpu`
  native port (strict ROCm, finite states, no-command) and same-device
  bf16 tuning (inference +12.9%, training step +26.8%) on the official AMD
  Radeon Cloud, covered by 49 focused tests
  (`receipts/rocm-native-robot-port-terminal-20260729-v1/`).
- A complete reproducible official-AMD learned-policy evaluation workflow that
  produces fail-closed per-episode, aggregate, telemetry, exit-code, and
  integrity evidence (G3 receipt).
- A reusable, fail-closed provenance collector with atomic no-clobber commits
  and inode-verified rollback; source SHA-256
  `7c8693569192e5daa63bc86f53bd822b95a1a37117b27f605fbf16e8ded618e5`,
  validated by 25 focused tests and all 532 project tests on the AMD CPU-only
  regression gate.
- The 16D virtual-gripper → 18D physical-gripper adapter, three-camera
  pipeline, 250 Hz→30 Hz resampling, and strict staged evaluator
  (`docs/MANTIS_LEROBOT_GATE.md`; `docs/AMD_ACT_CLOSEDLOOP_G3_GATE.md`).
- A causal promotion chain for robot-specific CUDA→ROCm adaptation: immutable
  AMD negative evidence, representative deterministic replay, commanded-target
  counterfactual, a one-variable data-distribution correction, and a
  fail-closed single-Radeon corrective training contract
  (`docs/AMD_ACT_CORRECTIVE_TRAINING_GATE_V1.md`).
- **Candidate upstream contributions (not yet submitted):** Genesis
  Radeon/ROCm compatibility; public allowed-collision matrix support instead
  of private collider state; LeRobot ROCm installation/runtime compatibility;
  Mantis adapter/dataset-validation improvements. Upstream PR evidence is
  **`TODO-evidence`** and is kept separate from local workaround claims.

## 8. Innovation

- A **fail-closed evidence discipline** that separates optimization metrics
  from task-success metrics and refuses to overstate robot capability — the
  project publishes a verified negative G3 rather than inferring capability
  from training loss or open-loop actions.
- An **asymmetric 16D→18D projection** with categorical normalized-gripper and
  fixed-limit physical domains, fully diagnosed per sample (open-loop receipt).
- A **configurable profile model** that rejects the Mantis-specific assumption
  that state and action dimensions must match and keeps four independent
  ordered interfaces.
- **Hash-pinned externalization** of a non-redistributable robot asset, enabling
  reproducibility without licensing exposure.

## 9. Application value

- The framework lowers the barrier to adapting bimanual tasks across robots and
  evaluating the resulting policies on AMD Radeon / ROCm, with auditable
  contracts, provenance, integrity, and promotion decisions at every stage.
- For robot manufacturers, the reusable profile model, URDF-to-ROCm compiler,
  camera and state/action contracts, LeRobot adapter, and staged evidence gates
  provide a concrete route for integrating vendor-specific robots into the AMD
  embodied-AI ecosystem instead of rebuilding each port from scratch.
- The negative result itself is operationally valuable: it enables
  statistically complete frozen comparison and targeted diagnosis of the
  timeout and collision-safety families instead of capability inference.
- **Limitation of application value:** because G3 is FAIL (0/10), the current
  checkpoint is not deployment-ready. Application value is in the
  **infrastructure and methodology**, not in demonstrated task capability.
- This is an individual, deadline-bound prototype. Limited demonstration
  coverage and training time constrain policy quality, while the reusable
  integration layer remains the primary contribution.

The representative CUDA counterfactual further localizes the two collision
failures: recorded ACT target configurations for seeds 107 and 108 enter the
same bowl-to-right-wrist source-mesh collision family before or at termination.
This supports a controlled first correction to the policy trajectory
distribution rather than controller gains or collision geometry. The
correction retains the original four successful demonstrations and adds
accepted seeds 1012 and 1016 (six episodes, 7,085 frames), while all model,
controller, timing, geometry, mapping, camera, reset, and evaluation variables
remain frozen. The corrected dataset, CUDA optimization, and representative
closed-loop comparison are complete. The comparison terminated
`COMPLETE_NOT_PROMOTABLE`, so official-AMD corrective execution was not
started. No task-success claim is made.

## 10. Limitations

- **G3 is 0/10** — eight `timeout`, two `collision_safety`; aggregate FAIL.
  The current checkpoint does not complete the task.
- Training loss (0.023) is a descriptive optimization observation, **not** a
  convergence criterion and **not** task success.
- The six-seed CUDA correction completed its representative gate with
  `COMPLETE_NOT_PROMOTABLE`; it has not run on the official AMD worker.
- No G4 robustness evaluation, no real-robot transfer, and no AMD performance
  advantage are established.
- The direct `/sys/kernel/debug/kfd/proc` collector was unavailable on the
  managed worker before/after the G3 run; AMD SMI provides the authoritative
  utilization sequence (a process-attribution evidence limitation, not a
  basis to discard single-Radeon utilization).
- Mantis raw assets are not redistributable. The selected H.264 1280x720,
  168-second v4 demo with English narration and subtitles is packaged at
  `submission/Mantis_ROCm_Bridge_demo_20260806_v4.mp4`, SHA-256
  `220c54c7ca68760db53a5a9d8c80d1d8f39755a7365ee682758d6b5b50952017`,
  and is independently accepted as `VIDEO_GO` after 5,040/5,040-frame decode
  and visual review. It labels the successful scripted expert as non-policy
  output, the 50-step policy smoke as task-incomplete, and wrist cameras as
  simulation-only rather than physically calibrated. Archive clean-room source
  review remains `CLEANROOM_RUNNER_NO_GO`. No runner
  executed, so clean-room reproduction remains an unproven limitation rather
  than a local package blocker.

## 11. Individual contribution

This is registered as an individual entry. The public identity is confirmed in
`configs/submission-identity-v1.json`.

| Member | Role / area | Artifacts owned | Status |
|---|---|---|---|
| Zhiwen Su (Blueworm) | End-to-end system engineering | Framework contracts/planner, Mantis reference adapter, Genesis task, datasets, ACT training/evaluation, AMD/ROCm migration, provenance, licensing, and submission package | Identity user-confirmed; technical claims remain receipt-gated |

## 12. Reproducibility

- Original AMD contract: `configs/act-rocm-baseline-v2.json`.
- Prepared corrective AMD contract:
  `configs/act-rocm-corrective-multiseed6-v1.json`; it was not executed because
  the CUDA representative gate terminated `COMPLETE_NOT_PROMOTABLE`.
- Exact remote identity (project, dataset, checkpoint, evidence paths) is
  recorded in `receipts/amd-act-rocm-v2-live-20260726-v1/`,
  `receipts/amd-act-openloop-inference-20260726-v1/`, and
  `receipts/amd-act-closedloop-g3-multiseed-final-20260726-v1/`.
- A **clean-room reproduction** following published commands from a fresh
  checkout on the official AMD cloud is **`TODO-evidence`**. The latest runner
  source review is `CLEANROOM_RUNNER_NO_GO`, neither runner executed, and the
  result remains an explicit limitation rather than a local package blocker.

## Claim boundary

This report establishes a framework-first product narrative, configuration
readiness, and evidence traceability for one Mantis reference case. It does not
establish a second real robot port, generic runtime execution, correction
effectiveness, official-AMD corrective execution, clean-room reproduction, a
public repository, submitted pull request, submission, G3 pass,
or competition acceptance.
