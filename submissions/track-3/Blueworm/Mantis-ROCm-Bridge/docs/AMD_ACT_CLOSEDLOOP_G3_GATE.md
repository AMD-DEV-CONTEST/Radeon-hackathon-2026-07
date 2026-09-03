# AMD ACT learned-policy closed-loop G3 phase contract

Updated: 2026-07-26

## Phase objective

Execute the frozen 60,000-step ACT policy as a causal
perception–decision–control loop in the audited Mantis Genesis task on the
official single AMD Radeon ROCm runtime. First run seed 101 as an
infrastructure and safety smoke. If its evidence is terminal and valid, execute
the frozen G3 comparison set 101–110 and evaluate the predeclared threshold of
at least 6/10 strict task successes with zero safety failures.

This phase is the first learned-policy task-performance gate. It must not reuse
the scripted demonstration controller or any privileged scene state as policy
input.

## Entry criteria

- The official AMD ACT v2 training terminal audit is `PASS`, with the 60,000
  checkpoint and saved processors intact.
- The official AMD v7 open-loop inference receipt is `PASS`, including finite
  postprocessed actions, versioned actuator projection, one Radeon HIP device,
  and verified terminal hashes.
- The exact source reset distribution, Genesis scene, Mantis fixed-base
  topology, three camera transforms, 16D/18D semantic adapter, strict evaluator,
  and safety taxonomy are frozen.
- The single AMD device is free of unrelated KFD processes before each run.

## Dependency graph

`ACT v2 terminal audit`
→ `open-loop v3 actuator admission`
→ `G3 implementation and local regression`
→ `AMD seed 101 terminal smoke`
→ `AMD G3 seeds 101–110`
→ `closed-loop promotion decision`.

The seed-101 task outcome is not used to tune the controller. Seed 101 may
block the batch only for an infrastructure, evidence, non-finite action,
postprojection safety, or physics-integrity defect. An ordinary strict task
failure with valid safety evidence does not remove or replace seed 101 and
does not block execution of the frozen ten-seed set.

## Frozen controller semantics

At each 30 Hz policy tick:

1. acquire the 16D proprioceptive state and the environment, left-wrist, and
   right-wrist RGB observations;
2. convert images to the checkpoint CHW `[0, 1]` tensor contract;
3. apply the checkpoint's saved LeRobot 0.4.4 preprocessor;
4. call ACT under `torch.inference_mode()` and preserve its temporal action
   chunk queue across policy ticks;
5. apply the saved postprocessor;
6. enforce the open-loop v3 virtual-gripper and physical-joint actuator
   projection while retaining raw and projected telemetry;
7. apply the projected finite 18D absolute joint-position target;
8. hold that target on the 250 Hz Genesis physics loop until the next causal
   policy tick.

The Mantis physical-gripper state readback uses the contract-pinned normalized
range tolerance `0.003` before clamping to `[0, 1]`. This reuses the existing
simulation-export endpoint contract, which was frozen from a 1177-frame strict
capture whose maximum averaged endpoint excursion was `0.00240638`. For the
37.6 mm Mantis clamp travel, the admitted envelope is about 0.113 mm. The
tolerance is limited to Genesis state readback at the physical boundary. It is
not policy-action saturation, does not change the generic gripper adapter
default, and does not admit values outside the previously validated simulation
envelope; values beyond the pinned tolerance still fail closed.

Policy tick `k` maps to the first non-early physics step
`ceil((k / 30) / 0.004 - 1e-12)`, giving initial steps
`0, 9, 17, 25, 34`. Timing skew must remain below one 4 ms physics step.

The existing `topp_dense_to_mantis_30hz_v1` interpolation and uniform retiming
protocol remains the frozen rule for converting dense 250 Hz scripted
demonstrations into 30 Hz training records. It is not applied again to ACT
outputs: the learned policy already produces 30 Hz absolute targets, so live
execution uses causal zero-order hold.

ACT state resets exactly once at the start of each episode. Resetting the ACT
chunk queue on every step, querying future observations, or replacing a
predicted action with a demonstration action is a protocol violation.

## Forbidden assistance

The learned-policy runner may not invoke or reproduce:

- the scripted grasp candidate search, IK planner, weld transport, replay
  plan, object-position correction loop, or demonstration action trace;
- privileged bowl pose, velocity, contact, evaluator, or safety state as a
  policy input;
- seed-specific controller constants, action substitution, success-threshold
  relaxation, or seed replacement.

Privileged state is permitted only inside the frozen evaluator and safety
monitor after the policy action is committed.

## Work packages and deliverables

### WP-P3-CL-001 — dependency-isolated closed-loop core

Deliver:

- `configs/act-closedloop-g3-v1.json`;
- `src/mantis_rocm_bridge/act_closedloop_g3.py`;
- `tools/run_genesis_act_closedloop_g3.py`;
- `tests/test_act_closedloop_g3.py`.

The core must validate the phase contract, generate the exact seed set, map the
30 Hz clock to 250 Hz physics, project actions through the admitted v3 adapter,
track strict consecutive success, classify failures, and build receipts
without importing Genesis, PyTorch, or LeRobot at module import time.

The executable adapter owns Genesis scene construction, checkpoint loading,
camera rendering, policy execution, safety sampling, and non-overwriting
artifact finalization.

### WP-P3-CL-002 — local and AMD seed-101 preflight

Run JSON validation, focused unit tests, and the complete local regression
suite. Deploy only the accepted source snapshot to a fresh AMD directory.
Before seed 101, verify exact source/config/checkpoint hashes, LeRobot 0.4.4,
one Radeon HIP device, and no unrelated KFD process.

Seed 101 must produce a terminal receipt even when the task fails. A missing or
ambiguous receipt is an infrastructure failure, never an episode failure.

### WP-P3-CL-003 — frozen G3 comparison

After seed-101 infrastructure admission, run exactly seeds 101–110. Reuse the
already-completed seed-101 receipt only when its source, config, checkpoint,
runtime, reset distribution, and artifact hashes are identical to the batch
contract. Otherwise rerun seed 101 in the fresh batch; do not mix protocols.

Aggregate success count, safety failures, timeout and task-failure taxonomy,
projection telemetry, policy latency, GPU evidence, and artifact hashes.
Latency, utilization, temperature, power, and saturation magnitude are
descriptive and are not success thresholds.

## Acceptance matrix

| Criterion | Procedure | Required result | Evidence |
|---|---|---|---|
| Static contract | parse and validate the versioned JSON | exact seed, clock, observation, action, evaluator, evidence and claim contracts | focused test log |
| Dependency isolation | import core without Genesis, PyTorch, LeRobot | import succeeds | focused test |
| Clock schedule | test 30 Hz ticks against 4 ms physics | initial steps `0,9,17,25,34`; skew `<0.004 s` | focused test |
| Policy state | instrument reset and action calls | one reset per episode; no per-step reset | focused/integration log |
| Observation causality | record timestamps and feature shapes | one current observation per action; no evaluator state in policy input | policy JSONL |
| Action admission | retain raw/projected 16D and 18D targets; record the frozen `0.003` simulation-readback endpoint tolerance | finite postprojection target inside all fixed limits; values beyond the validated readback envelope fail closed | policy JSONL and receipt |
| No scripted fallback | static and runtime provenance audit | no planner, IK, weld, replay, correction, or demo-action call path | source inventory and receipt |
| Strict evaluator | replay pure evaluator fixtures and online rows | unchanged tolerances and 12 consecutive frames | evaluator JSONL |
| Seed-101 terminal smoke | official AMD single-GPU run | terminal receipt, valid hashes, zero safety failures; ordinary task failure is admissible to batch | episode directory |
| Exact G3 set | aggregate immutable episode receipts | exactly seeds 101–110, no replacements or omissions | G3 summary |
| G3 task threshold | compute from strict receipts | at least 6/10 successes | G3 summary |
| G3 safety threshold | aggregate safety taxonomy | zero safety failures | failure taxonomy |
| ROCm attribution | environment and KFD process capture | exactly one Radeon HIP device and evaluated PID visible | GPU logs |
| Terminal integrity | independent hash verification | all episode and aggregate manifests verify | final audit |

## Terminal conditions

- **Implementation ready:** local static, focused, and full regression gates
  pass. This authorizes deployment, not a closed-loop claim.
- **Seed-101 admitted:** its terminal infrastructure, action-safety, physics,
  ROCm, and hash evidence passes. Task failure alone does not prevent the full
  batch.
- **G3 pass:** exactly ten frozen receipts yield at least six strict successes
  and zero safety failures.
- **G3 fail:** the complete frozen set terminates below six strict successes or
  with any safety failure; evidence is preserved and is not relabeled.
- **Blocked:** an immutable entry artifact is missing, the runtime is
  unavailable, or continuing would require changing the frozen protocol.

## Claim boundary

Seed 101 alone is an infrastructure smoke and never establishes G3. A passing
G3 establishes only exact-distribution learned-policy closed-loop performance
for the frozen checkpoint, simulator, task, evaluator, seeds, and official AMD
ROCm runtime. It does not establish optimization convergence, G4 statistical
confirmation, domain-randomization robustness, unseen-scene generalization,
real-robot safety, or an AMD performance advantage.
