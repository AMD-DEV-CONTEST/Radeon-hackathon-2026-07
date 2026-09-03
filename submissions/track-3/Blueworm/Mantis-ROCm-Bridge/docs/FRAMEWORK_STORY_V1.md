# Framework story v1

Date: 2026-07-29  
Work package: `WP-FRAMEWORK-STORY-003`  
Application: Mantis-ROCm Bridge  
Participant: Zhiwen Su  
Team: Blueworm  
License: Apache-2.0 for Blueworm-owned original project material

## Product sentence

Mantis-ROCm Bridge is a contract-driven, evidence-gated robot adaptation and
task-porting framework for describing a source task, adapting it to a target
robot, validating the simulation/data/policy interfaces, running the staged
AMD Radeon + ROCm workflow, and preserving evidence without overstating
capability.

Mantis is the first evidence-backed reference port. It is not the definition
of the product and it is not evidence of multi-robot runtime generality.

## User problem

A robot task port usually hides incompatible assumptions across joint order,
state/action dimensions, gripper conventions, cameras, timing, controllers,
safety, assets, dataset schemas, normalization, policy checkpoints, and
evaluation thresholds. A training process can finish while the policy still
fails every closed-loop episode.

The framework turns those assumptions into versioned contracts and promotion
gates. It keeps structural readiness, runtime availability, optimization,
open-loop inference, closed-loop task success, robustness, and publication as
separate evidence levels.

## Framework journey

```text
source task audit
  -> source/target robot profile
  -> state/action/camera/clock/controller/safety contracts
  -> external asset and scene admission
  -> scripted expert and strict episode admission
  -> LeRobot export and dataset audit
  -> AMD/ROCm runtime and policy training
  -> open-loop admission
  -> closed-loop multi-seed evaluation
  -> evidence, backup, clean-room, and publication gates
```

Schema-v1 profiles explicitly cover controller, safety, data, policy, and
evaluation. Policy and physical state/action dimensions have four independent
ordered field lists; the framework does not assume state and action dimensions
are equal.

## Minimum usable surface

- `configs/robot-port-profile-template-v1.json`: blocked copy-and-edit profile;
- `configs/robot-port-profile-mantis-stack-bowls-v1.json`: Mantis reference;
- `tests/fixtures/robot-port-profile-synthetic-v1.json`: validation-only
  non-Mantis fixture;
- `tools/plan_robot_port.py validate|plan`: deterministic read-only audit;
- `src/mantis_rocm_bridge/port_profile.py`: strict schema and safe local
  reference validation.

The synthetic fixture proves configurability of validation and planning only.
It is not a second real robot port.

## Reference case

The reference port preserves RoboTwin's `stack_bowls_three` task from the Tron
embodiment while adapting it to Mantis, Genesis, LeRobot, and a single AMD
Radeon GPU through ROCm.

| Evidence level | Verified reference result |
|---|---|
| Profile/reference parity | `COMPLETE_FRAMEWORK_PROFILE_AND_READ_ONLY_PLANNER_VERIFIED` |
| AMD ACT optimization | 60,000 steps, natural exit 0; loss is descriptive only |
| AMD open-loop inference | 12/12 finite actions passed fixed-limit admission |
| Official AMD closed-loop G3 | **0/10**, eight `timeout`, two `collision_safety`, `FAIL` |
| CUDA corrective representative | seeds 101/107/108, 0 successes, 2 safety failures, `COMPLETE_NOT_PROMOTABLE` |
| Official AMD corrective rerun | not started because the CUDA promotion dependency failed |

This negative result is part of the framework evidence story: a completed
training run and passing open-loop actions did not silently become a
closed-loop capability claim.

## Asset and visual boundary

Rendered Mantis visuals are user-permitted only in the demonstration video.
This is not a general license or redistribution right. Raw Mantis URDF, meshes,
source assets, derived raw asset files, materializations, and asset payloads
remain externalized under `SAFE_FALLBACK_EXTERNALIZED` and excluded from the
public repository and Docker image. The owner-authorization request remains
unsent and no redistributable asset license is claimed.

Apache-2.0 covers only original project source and documentation that Blueworm
has the right to license; it does not relicense Mantis or any other third-party
asset.

## Claim boundary

The synchronized story may claim a generic declarative profile, safe reference
audit, deterministic read-only planning, and one evidence-backed Mantis
reference port. It must not claim:

- a second real robot port or generic runtime execution;
- ACT task success, G3 pass, G4 robustness, convergence, or AMD advantage;
- real-robot safety;
- redistributable Mantis assets or general visual clearance beyond the narrow
  demonstration-video permission;
- completed clean-room reproduction, target-length video, or frame-by-frame
  final video acceptance;
- public repository, submission, Pull Request, publication, competition
  acceptance, or upstream contribution.
