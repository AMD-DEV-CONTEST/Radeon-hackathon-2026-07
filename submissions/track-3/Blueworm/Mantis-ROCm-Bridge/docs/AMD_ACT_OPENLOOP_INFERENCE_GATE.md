# AMD ACT open-loop inference phase contract

Updated: 2026-07-26

## Phase objective

Demonstrate that the frozen 60,000-step ACT checkpoint can load its saved
LeRobot 0.4.4 preprocessing and postprocessing pipelines, consume the audited
Mantis three-camera observations, and emit finite contract-compliant Mantis
actions on the same official single AMD Radeon GPU through ROCm.

This phase is an open-loop compatibility and execution gate. It does not
execute predicted actions in Genesis and therefore cannot establish task
success.

## Entry criteria

- Official AMD ACT v2 training terminated with exit code 0.
- `final_training_audit_20260726_v1.receipt.json` has
  `terminal_audit_pass=true`.
- Checkpoint `060000/pretrained_model` contains `config.json`,
  `model.safetensors`, the policy preprocessor and postprocessor JSON files,
  and both processor safetensor files.
- The four-episode / 4738-frame dataset passed archive, metadata, dense,
  direct-parquet, and real LeRobot 0.4.4 sample-decode gates.
- The official Radeon worker exposes exactly one HIP device and is free of
  unrelated KFD processes.

## Dependency graph

`ACT v2 terminal audit`
→ `checkpoint and processor integrity`
→ `open-loop inference implementation`
→ `official AMD open-loop receipt`
→ `Genesis closed-loop G3 seeds 101–110`.

The frozen LeRobot interface, gripper contract v2, fixed joint limits, task
contract, dataset receipts, checkpoint receipt, and ROCm runtime receipt are
upstream inputs. The G3 closed-loop controller and evaluator are downstream
consumers.

## Work packages

### WP-P3-OLI-001 — deterministic open-loop inference gate

Implement a dependency-isolated core plus a LeRobot 0.4.4 runtime adapter.
Select the first, midpoint, and last frame of every dataset episode, yielding
exactly 12 distinct observations for the current four-episode dataset. Load
the saved checkpoint processors rather than recomputing statistics.

For every selected observation:

1. validate 16D state and all three CHW image tensors;
2. apply the checkpoint preprocessor;
3. run ACT under `torch.inference_mode()` on `cuda:0`, whose semantics must be
   a non-null HIP runtime and an AMD Radeon device;
4. apply the checkpoint postprocessor;
5. validate one finite 16D action;
6. expand it through gripper contract v2 to the 18D simulation target;
7. under the v1 diagnostic gate, reject gripper values outside `[0, 1]`;
8. under the versioned v2 actuator-admission gate, apply deterministic
   componentwise saturation to only virtual-gripper indices 7 and 15, record
   raw and projected actions plus projection magnitude, then reject any
   remaining physical joint-limit violation.
9. under the versioned v3 controller-admission gate, additionally project all
   18 finite physical joint-position targets componentwise to the fixed-base
   joint limits, retaining preprojection violations, raw/projected targets,
   saturated joint names and maximum projection magnitude.

Repeat bounded inference passes only to collect stable descriptive latency and
GPU-process evidence. Never change the sample set or pass criteria based on
the observed actions.

The v2 projection is an actuator-domain constraint fixed independently of the
observed checkpoint output: normalized gripper commands are defined on
`[0, 1]`, non-finite values still fail, and no arm channel is projected. It is
not an empirical tolerance and does not weaken the 18D physical joint-limit
gate. The v1 strict-rejection implementation and its failed official-AMD
receipt remain immutable diagnostic evidence.

The v3 physical projection uses the already-frozen joint limits as its exact
domain and applies uniformly to all 18 physical channels. It introduces no
observed-output tolerance. A non-finite target still fails; only the
postprojection target is eligible for the downstream simulator controller.
Preprojection violations remain descriptive policy-output diagnostics and
must be reported in later closed-loop evaluation.

### WP-P3-OLI-002 — official AMD execution and provenance

Deploy the accepted source as a fresh immutable project version. Run one
single-GPU inference job under an independent supervisor that records:

- exact command, source/config/checkpoint/dataset hashes;
- process identity and start/finish timestamps;
- pre-run, during-run, and post-run ROCm SMI state;
- PyTorch, HIP, device name, device count, LeRobot version;
- per-sample action records and descriptive latency;
- exit code, status, output inventory, and SHA-256 manifests.

### WP-P3-OLI-003 — G3 admission decision

Admit the 60K checkpoint to closed-loop G3 only when every open-loop acceptance
criterion passes. Otherwise preserve the failed receipt and classify the
defect as checkpoint loading, processor compatibility, observation contract,
action contract, ROCm execution, or evidence insufficiency.

## Deliverable manifest

Local implementation:

- `configs/act-openloop-inference-v1.json`
- `configs/act-openloop-inference-v2.json`
- `configs/act-openloop-inference-v3.json`
- `src/mantis_rocm_bridge/act_openloop_inference.py`
- `tools/run_act_openloop_inference.py`
- `tests/test_act_openloop_inference.py`
- this phase contract

Expected remote run directory:

`/workspace/mantis_act_openloop_inference_20260726_v1`

Required remote artifacts:

- `started.json`
- `command.txt`
- `environment.json`
- `gpu_before.txt`
- `gpu_during.txt`
- `gpu_after.txt`
- `actions.jsonl`
- `receipt.json`
- `stdout.log`
- `stderr.log`
- `exit_code.txt`
- `finished_at_utc.txt`
- `status`
- `SHA256SUMS`
- `final_evidence.SHA256SUMS`

No artifact may overwrite an existing file or directory.

## Acceptance matrix

| Acceptance criterion | Procedure | Expected result | Evidence |
|---|---|---|---|
| Static contract | JSON parse and implementation validation | schema, paths, sample rule, dimensions and claim boundary accepted | test log |
| Focused regression | `PYTHONPATH=src python3 -m unittest tests.test_act_openloop_inference` | all focused tests pass | local test log |
| Full regression | `PYTHONPATH=src python3 -m unittest discover -s tests` | no regression | local and AMD logs |
| Checkpoint integrity | verify the frozen 60K checkpoint manifest | zero failed entries | remote manifest log |
| Dataset sampling | enumerate first/midpoint/last per episode | 12 distinct samples from 4 episodes | receipt and actions JSONL |
| Processor provenance | load pre/post processors from the checkpoint directory | saved processor files used and hashed | receipt |
| Tensor contract | validate state, camera and action shapes and finite values | 16D state/action; 3×240×320 env; two 3×240×424 wrist images | per-sample records |
| Simulation action safety | apply gripper contract v2 and fixed joint limits | all 12 actions expand to finite 18D targets within limits | receipt |
| Projection provenance | compare raw and projected 16D actions | only indices 7/15 may saturate to `[0,1]`; channel count and maximum delta recorded | per-sample records and receipt |
| Physical actuator projection | compare raw/projected 18D targets to fixed joint limits | projected target is finite and in bounds; every saturated joint and delta recorded | per-sample records and receipt |
| ROCm attribution | strict PyTorch/HIP/device checks plus during-run KFD capture | one AMD Radeon HIP device and inference PID visible | environment and GPU logs |
| Terminal integrity | independent output and final-evidence hash verification | exit code 0, status `PASS`, zero hash failures | terminal audit |

Latency, action-to-demonstration error, utilization, temperature, power, and
memory are descriptive measurements, not pass thresholds or comparative
performance claims.

## Terminal condition

- **Complete:** all acceptance criteria pass and the versioned official-AMD
  receipt independently verifies its hashes.
- **Failed:** the inference job reaches a terminal failure and preserves its
  exact compatibility or action-safety defect.
- **Blocked:** an entry criterion is unavailable without altering frozen
  evidence or requiring new user authority.

## Claim boundary

A passing phase proves only that the frozen ACT checkpoint, its saved
processors, the audited Mantis observation contract, the 16D-to-18D simulation
action adapter, and the official AMD ROCm runtime interoperate in open loop.
It does not prove policy convergence, closed-loop control, grasping, stacking,
task success, generalization, robustness, real-robot safety, or an AMD
performance advantage.

## Official AMD diagnostic history

- `v1`: negative environment receipt; the system Python lacked PyTorch.
- `v2`: incomplete supervisor staging; a versioned source path was invalid.
- `v3`: negative compatibility receipt; the processor factory import path was
  incompatible with LeRobot 0.4.4.
- `v4`: first complete ROCm model-inference execution. All 12 observations
  decoded and ACT executed on the AMD Radeon HIP device, but the v1 strict
  gate terminated `FAIL` because 11 raw samples contained at least one
  normalized gripper value outside `[0,1]`. This receipt is retained as the
  motivation and regression boundary for the independent v2 actuator-domain
  projection; it is not relabeled as a pass.
- `v5`: supervisor parameter-contract failure before model loading because
  the versioned gate path was relative; the staging directory is retained.
- `v6`: complete v2 ROCm inference and evidence finalization. The gripper
  projection behaved as specified (11 saturated samples, 18 saturated
  channels), after which four episode-final samples exceeded the same
  left-wrist-yaw upper joint limit by roughly 0.009–0.010 rad. The v6 failed
  receipt motivates the uniform v3 physical actuator projection and remains
  immutable.
- `v7`: complete v3 official-AMD run and terminal `PASS`. All 12 deterministic
  samples produced finite actions and postprojection-safe 18D targets. The
  supervisor and a separate read-only audit both verified the core and final
  manifests with exit code 0; no inference process remained. The versioned
  receipt is mirrored at
  `receipts/amd-act-openloop-inference-20260726-v1/`.
