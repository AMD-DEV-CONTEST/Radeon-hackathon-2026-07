# Framework product reset v1

Date: 2026-07-29  
Work package: `WP-FRAMEWORK-RESET-001`  
Contract: `configs/framework-product-reset-v1.json`

## Decision

Mantis-ROCm Bridge is a **contract-driven, evidence-gated robot adaptation and
task-porting framework**. Its purpose is to help a user preserve a source
robot task while adapting the embodiment, interfaces, simulator, dataset,
policy runtime, evaluation, and deployment evidence for a target robot.

The current Tron/RoboTwin `stack_bowls_three` to Mantis/Genesis/LeRobot/ROCm
path is the first reference port. It is not the product definition by itself.
The ACT G3 result is one framework validation result, not the sole project
outcome.

English submission one-liner:

> A contract-driven, evidence-gated toolkit for porting bimanual robot tasks
> across embodiments and running the resulting simulation, data, policy,
> evaluation, and reproducibility workflow on AMD Radeon and ROCm.

This reset supersedes older recommendations that treated the next
seed-specific collision-semantics work package as the project critical path.
Historical contracts and receipts remain immutable evidence.

## User and workflow

The intended user has:

1. a source robot task or demonstration workflow;
2. a target robot description and interface;
3. a need to reproduce the task in Genesis;
4. a need to export audited LeRobot data;
5. a need to train and evaluate a policy on AMD Radeon/ROCm; and
6. a need to package reproducibility and evidence without redistributing
   unlicensed assets.

The minimum framework journey is:

```text
source task audit
  -> source/target robot profiles
  -> interface and safety contract
  -> asset and scene materialization
  -> Genesis smoke and scripted expert
  -> strict episode admission
  -> LeRobot export and dataset audit
  -> policy training and open-loop admission
  -> closed-loop evaluation
  -> AMD/ROCm evidence, backup, and publication package
```

## Product boundaries

### Framework substrate already exercised by the Mantis port

These components have reusable behavior, although generality beyond the
Mantis reference port is not yet claimed:

- semantic vector and camera reordering:
  `src/mantis_rocm_bridge/adapters.py`;
- guarded URDF audit and fixed-base materialization:
  `src/mantis_rocm_bridge/urdf_audit.py`,
  `src/mantis_rocm_bridge/asset_builder.py`;
- policy/physics clock handling:
  `src/mantis_rocm_bridge/control_resampling.py`,
  `src/mantis_rocm_bridge/genesis_capture.py`;
- episode state, evidence summaries, promotion gates, and no-clobber run state:
  `src/mantis_rocm_bridge/episode_state.py`,
  `src/mantis_rocm_bridge/evidence.py`,
  `src/mantis_rocm_bridge/ops.py`;
- ROCm runtime, persistence, backup, and publication gates:
  `src/mantis_rocm_bridge/rocm.py`,
  `src/mantis_rocm_bridge/amd_persistence.py`,
  `src/mantis_rocm_bridge/publication.py`.

### Components that require parameterization

These work in the reference port but currently bind Mantis-specific dimensions,
names, or task contracts:

- gripper projection and target joint expansion;
- camera mounts and policy feature names;
- LeRobot adapter and episode export;
- ACT preflight, open-loop admission, and closed-loop runtime;
- simulator scene construction and safety context.

Parameterization must preserve the current Mantis behavior through parity
tests. A broad refactor before the competition deadline is forbidden.

### Reference-case-only components

The following remain in the Mantis `stack_bowls_three` case layer:

- source reset distribution and strict bowl-stacking evaluator;
- bowl asset materialization and rim-support overlay;
- scripted stacking expert and targeted right-first collection;
- bowl/contact/release diagnostics;
- G3 seed-specific failure attribution and corrective experiments.

### Deferred research

The WP-G3-CORR-017 through WP-G3-CORR-021 collision-semantics and physical
authority work is retained as a framework research case, but is not an active
runtime or submission blocker. It must not continue into WP-022 before the
framework minimum viable product and submission package are stable.

## What is missing before calling this a framework

1. One versioned, public robot-port profile schema covering source, target,
   task, observation/action, controller, cameras, clocks, safety, data,
   policy, evaluation, runtime, assets, and evidence boundaries.
2. A template plus a checked Mantis reference instance.
3. One read-only entry point that validates a profile and reports stage
   readiness and blockers without launching simulation or training.
4. A clear separation between framework modules and reference-case modules.
5. A public “port another robot” tutorial and architecture diagram.
6. A second synthetic profile fixture proving schema configurability. It may
   prove validation behavior only; it cannot establish a second real robot
   port.
7. Submission documents synchronized with the completed representative
   evaluation, participant identity, persistence path, and framework product
   story.

## Deadline route

### WP-FRAMEWORK-MVP-002 — profile and read-only planner

Create the smallest usable framework surface:

- generic profile schema and documented template;
- Mantis reference profile referencing existing immutable contracts;
- one synthetic validation-only profile;
- read-only `validate/plan` command that emits stage readiness, blockers, and
  claim boundaries;
- focused tests plus unchanged Mantis contract validation.

It must not refactor the simulator, controller, safety rules, data path, or
policy runtime.

### WP-FRAMEWORK-STORY-003 — public framework narrative

Synchronize the top-level README, submission README, technical report,
evidence matrix, checklist, reproducibility instructions, and video storyboard.
The narrative must lead with the configurable porting framework and use Mantis
as the evidence-backed reference case. It must preserve the official AMD G3
result as `0/10`.

### WP-FRAMEWORK-CASE-004 — reference-port parity

Demonstrate that the framework profile resolves the existing Mantis contracts
without changing their bytes or runtime behavior. Run local validation and a
bounded clean-process CPU smoke only if separately authorized. A synthetic
profile is not a second-port capability claim.

### WP-CAPABILITY-LAST-005 — one bounded capability recovery

Only after the framework surface and public story are stable, reconsider one
right-first expert collection. Keep the task predicate and per-episode
zero-safety admission unchanged. A separately frozen contract must decide
whether one rejected CPU-simulation episode invalidates the whole collection
batch. If the predeclared coverage gate fails, stop capability recovery.

### WP-AMD-FINAL-006 — conditional AMD promotion

Run corrective AMD training/evaluation only if the 4090 representative gate
strictly improves without safety regression. Use
`/workspace/persistent/mantis-track3`, and create an off-host backup after each
terminal dataset, checkpoint, and evaluation milestone.

### WP-SUBMISSION-007 — final package

Complete the safe video, final rule check, clean-room evidence proportional to
the official requirement, and release candidate. Public repository creation,
competition submission, and Pull Request still require explicit user
authorization.

## Priority and stop rules

1. Framework product definition and submission truth outrank new seed-specific
   diagnostics.
2. No WP-022, SmolVLA, G4, production collision-provider integration, or broad
   runtime refactor before the framework minimum viable product is stable.
3. A change that cannot be demonstrated in the README, framework walkthrough,
   reproducibility path, or competition evidence is deferred.
4. Mantis reference behavior must remain unchanged while generic contracts are
   introduced.
5. Do not claim general multi-robot support from one real reference port.
6. Do not weaken task success, evaluation seeds, or per-episode safety
   admission to improve a score.
7. Stop experimental capability work early enough to preserve a final
   submission freeze and user review before 2026-08-06 23:59 CST.

## WP-FRAMEWORK-RESET-001 acceptance matrix

| Check | Expected result |
|---|---|
| Product definition | Framework is the product; Mantis is the reference port |
| Layer inventory | Reusable substrate, parameterization layer, case layer, and deferred research are explicit |
| Missing surface | Profile, template, read-only planner, tutorial, and validation-only second fixture are predeclared |
| Route | Framework MVP and submission story precede optional capability work |
| Stop rules | WP-022, SmolVLA, G4, and broad refactors are paused |
| Canonical continuity | `docs/EXECUTION_PLAN.md` and `configs/mantis-port-config.json` point to this reset |
| Safety boundary | No runtime, controller, safety, threshold, geometry, data, training, inference, remote, submission, PR, or publication action |
| Validation | JSON parses, referenced local files exist, contract validator passes, and the existing full test result is unchanged |

## Terminal condition and claim boundary

`COMPLETE_FRAMEWORK_PRODUCT_DIRECTION_FROZEN` means the product definition,
architecture layers, missing framework surface, deadline route, and stop rules
are frozen and recorded in canonical project state.

It does not mean the generic profile, planner, tutorial, second real robot
port, improved policy, clean-room reproduction, video, public repository,
submission, Pull Request, or competition acceptance exists.
