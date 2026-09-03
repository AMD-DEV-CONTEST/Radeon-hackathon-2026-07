# G3 dynamic failure-attribution gate — R1/R2

Date: 2026-07-27  
Phase status: **WP-G3-R1R2-001/002/003/004 complete**  
Phase ID: `mantis_act_g3_dynamic_replay_r1r2_v1`

## Phase objective

Reproduce the representative official-AMD ACT G3 timeout and collision
families on the 4090 Genesis development runtime while adding diagnostic
observability only. Produce sufficient evidence to falsify competing
mechanisms before selecting one versioned correction.

## Entry criteria

- Official-AMD ACT checkpoint 060000 optimization and open-loop admission are
  terminal and hash-verified.
- Official G3 remains 0/10: eight `timeout`, two `collision_safety`.
- Static attribution receipt
  `receipts/amd-act-g3-failure-attribution-static-20260727-v1/` passes.
- Diagnostic archive SHA-256 is
  `1003c92535398890ad26f43a32e6da767c2dadb3ed96416e650a6c43aec7aa9f`.
- 4090 GPU occupancy is inspected immediately before replay.

## Dependency graph

```text
verified local diagnostic archive
              |
              v
recoverable 4090 transfer + full SHA-256
              |
              v
fresh extraction + input/path audit
              |
              +--> R1 seed101 timeout baseline
              |
              +--> R2 seed107/108 collision baselines
                              |
                              v
                 falsification decision record
                              |
                              v
                  one versioned correction only
```

## Frozen invariants

- Checkpoint: official training step 060000.
- Seeds: R1 = 101; R2 = 107 and 108; no replacement.
- Policy rate: 30 Hz.
- Physics rate: 250 Hz, `dt=0.004 s`.
- ACT chunk and action-step count: 30.
- Policy reset: once at episode start.
- Strict evaluator, thresholds, source reset distribution, camera contract,
  scene hashes, joint limits, gripper projection, and allowed-collision filter
  remain unchanged.
- Replays are single-GPU and sequential.
- Added diagnostics must not alter controller commands or simulator state.

## Work packages

### `WP-G3-R1R2-001` — recoverable transfer and extraction

Deliverables:

- local retry supervisor and status/log files;
- remote full archive with exact size and SHA-256;
- fresh extracted root;
- extraction inventory and integrity receipt.

Terminal condition: exact remote archive hash passes and the extraction is
complete, or a fail-closed blocker records the last verified prefix and error.

### `WP-G3-R1R2-002` — diagnostic-only instrumentation

Status: **COMPLETE (2026-07-27).** Five-path scope, frozen config hashes,
109 focused tests, 700 full-project tests, non-interference, exact LeRobot
0.4.4 / Genesis 1.2.3 identity, offline checkpoint load, and single-GPU CUDA
processor admission pass. Receipt:
`receipts/g3-r1r2-wp002-codegate-runtime-20260727-v1/`.

Deliverables:

- fresh versioned diagnostic project;
- instrumentation for wrist/link pose, pad/bowl contacts, gripper
  command/target/readback, action-queue index, and contact
  point/distance/penetration where supported by Genesis;
- focused tests proving observation-only behavior;
- frozen-command and source/config hash manifests.

Terminal condition: instrumentation tests pass and replay commands differ from
the frozen baseline only by output path and diagnostic enablement.

### `WP-G3-R1R2-003` — R1/R2 sequential replay

Status: **COMPLETE (v2, 2026-07-27).** The preserved v1 batch terminated before scene
construction with three infrastructure failures and zero policy ticks:
Quadrants 1.1.1 unconditionally resolved the CUDA 12.4+
`cuGraphConditionalHandleCreate` symbol absent from NVIDIA driver 535.247.01.
Its supervisor manifest verifies; its batch manifest has a separately
classified self-reference defect. The exact negative result and compatibility
probes are in
`receipts/g3-r1r2-replay-infrastructure-blocker-20260727-v1/`.

An isolated diagnostic-only compatibility shim passed Genesis 1.2.3 CUDA
initialization, primitive scene construction, two physics steps, and a
terminal zero-invocation receipt on GPU 0. It does not change any package,
scene, policy, controller, or evaluator input and is prohibited from the
official AMD path. The fresh v2 supervisor used one visible RTX 4090 and the
immutable order 101 → 107 → 108. It reached `COMPLETE` with zero
infrastructure failures, complete per-tick diagnostic alignment, and zero shim
invocations.

Seed 101 reproduced `timeout@1199` with 1,200 diagnostic rows and zero
robot-bowl contacts. Seed 107 reproduced the right-wrist-pitch source-mesh
collision family at policy step 28, one tick later than the official AMD
record. Seed 108 reproduced the right-wrist-yaw source-mesh collision family
at policy step 27. The 250 Hz to 30 Hz hold schedule and ACT queue chronology
are exact in all three replays. Receipt:
`receipts/g3-r1r2-dynamic-replay-20260727-v2/`.

Deliverables:

- R1 seed101 terminal receipt;
- R2 seed107 and seed108 terminal receipts;
- pre/during/post GPU evidence;
- per-run command, environment, stdout/stderr, trajectory diagnostics, exit
  code, and SHA-256 manifests;
- cross-run falsification table.

Terminal condition: all three seeds reach a terminal semantic outcome with
complete evidence, or a versioned infrastructure blocker is recorded.

### `WP-G3-R1R2-004` — commanded-target collision counterfactual

Status: **COMPLETE (v2, 2026-07-27).**

The observed executed configurations contain measurable joint target/readback
error, especially on right shoulder pitch and right wrist roll at both
collision terminals. The v2 counterfactual evaluated the recorded ACT target
configurations with Genesis real-time collision detection, without advancing
physics or changing the frozen scene.

Seed 107 target configurations entered the bowl1/right-wrist/source-mesh
collision family at steps 27 and 28. Seed 108 entered the
bowl2/right-wrist/source-mesh family at steps 25, 26, and 27. All pose
admissions passed. The diagnostic-only CUDA compatibility shim remained at
zero invocations. The preserved v1 run failed closed because it incorrectly
required a static post-step readback to retain physics-step contact state and
used an over-tight universal pose tolerance; it is retained as method-negative
evidence and is not used for the causal decision.

The discriminative result establishes that controller tracking error is not
required to create the diagnosed collision family. The single selected
correction variable is therefore the successful ACT training-trajectory
distribution. Its frozen contract is
`configs/act-trajectory-distribution-correction-v1.json`; evidence is in
`receipts/g3-commanded-target-counterfactual-20260727-v2/`.

Deliverables:

- fresh development-only, non-overwriting counterfactual evidence for seeds
  107 and 108;
- frozen reset pose and recorded terminal target identity;
- unchanged collision labels and classifier;
- exact pre/post GPU process evidence and compatibility-shim zero-use receipt;
- one causal decision record that either selects one correction variable or
  preserves the ambiguity and blocks correction.

Terminal condition: the commanded terminal configurations are independently
evaluated without changing the official G3 protocol, and exactly one
correction variable is frozen only if the result is discriminative.

## Acceptance matrix

| Gate | Expected result |
|---|---|
| Partial-transfer prefix | remote prefix SHA-256 equals local prefix |
| Full archive | 194,583,158 bytes and exact expected SHA-256 |
| Extraction | fresh root; no overwrite; substantive manifest passes |
| Source identity | frozen project/config/checkpoint hashes match transfer |
| Instrumentation | no action/controller/state mutation; focused tests pass |
| GPU allocation | one selected idle GPU; no more than one replay at a time |
| R1 | seed 101 reproduced or explicit infrastructure failure |
| R2 | seeds 107 and 108 reproduced or explicit infrastructure failure |
| Evidence | commands, telemetry, exit codes, inventories, hashes complete |
| Counterfactual | commanded-target collision state is measured without an official-result claim |

## Claim boundary

This phase establishes replay-verified failure families, excludes clock or ACT
queue drift for the selected representatives, and shows that the ACT target
configurations themselves enter the diagnosed collision family. It supports
selection of one data-distribution correction, but cannot establish that the
correction works. It cannot establish a corrected G3 pass, generalization, G4
robustness, real-robot safety, AMD performance advantage, or competition
outcome. CUDA replay evidence is not AMD evidence.
