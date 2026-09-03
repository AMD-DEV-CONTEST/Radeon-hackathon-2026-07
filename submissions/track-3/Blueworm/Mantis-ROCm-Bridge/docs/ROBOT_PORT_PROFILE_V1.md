# Robot port profile v1

Work package: `WP-FRAMEWORK-MVP-002`  
Implementation: `src/mantis_rocm_bridge/port_profile.py`  
Read-only entrypoint: `tools/plan_robot_port.py`

## Purpose

A robot port profile is the framework's declarative index for one source to
target task port. It binds the embodiment interfaces, task semantics, local
contract references, runtime boundary, asset strategy, blockers, and stage
status without importing or executing a simulator, policy, controller, or
training stack.

The profile does not replace the detailed source contracts. It points to them,
checks that required local references exist, and provides one compact stage
plan for users and automation.

## Profile kinds

- `template`: a structurally valid starting point with explicit placeholder
  blockers.
- `reference`: an evidence-backed real project instance, currently the
  Tron/RoboTwin `stack_bowls_three` to Mantis reference port.
- `synthetic_fixture`: a test-only profile used to falsify hard-coded Mantis
  assumptions. It proves schema configurability only.

## Required sections

Every schema-v1 profile contains:

- source and target robot/task/interface descriptions;
- adapter references for joints, state, action, gripper, cameras, and clocks;
- explicit controller, safety, data, policy, and evaluation contracts;
- task, runtime, and asset boundaries;
- local references, each constrained to a relative path below the project
  root;
- stable blocker records;
- topologically ordered stages;
- an explicit claim boundary.

Policy and physical dimensions are distinct so a target such as Mantis may
retain a 16D policy interface while controlling 18 physical joints. State and
action dimensions are also independent: each endpoint declares four ordered
field lists (`policy_state_order`, `policy_action_order`,
`physical_state_order`, and `physical_action_order`). This permits, for
example, a state vector containing positions and velocities while the action
vector contains positions only. Each order must exactly match its own declared
dimension.

The controller, safety, data, policy, and evaluation sections are descriptive
indices, not executable settings. Their contract references must resolve
inside the local project root. Recorded evaluation counts are nullable when no
evaluation exists; when present, successes cannot exceed trials. The Mantis
reference records the existing ACT G3 result as `0/10`, not as a capability
pass.

## Design corrections recorded during implementation

Two initial design assumptions were rejected before terminal validation:

1. Requiring state and action dimensions to be equal would have encoded a
   Mantis-specific coincidence as a framework rule. Schema v1 therefore keeps
   four independent dimensions and ordered fields.
2. Leaving controller, safety, data, policy, and evaluation implicit in stage
   prose would not satisfy the frozen framework product contract. Schema v1
   therefore requires all five sections and validates every referenced
   contract ID.

## Stage semantics

| State | Outcome | Meaning |
|---|---|---|
| `complete` | `pass` or `negative` | The stage ran and preserved evidence |
| `ready` | `not_run` | Dependencies permit this stage to start |
| `blocked` | `not_run` | One or more declared blockers prevents it |
| `deferred` | `not_run` or `not_applicable` | Intentionally outside the active route |

`promotion=allows_downstream` means only that downstream workflow/reporting may
continue. A `negative` outcome remains negative and must retain a claim
boundary. It does not become task success.

## Read-only commands

From the project root:

```bash
PYTHONPATH=src python3 tools/plan_robot_port.py validate \
  configs/robot-port-profile-mantis-stack-bowls-v1.json

PYTHONPATH=src python3 tools/plan_robot_port.py plan \
  configs/robot-port-profile-mantis-stack-bowls-v1.json
```

Both commands read JSON and local file metadata, then write JSON to standard
output. There is deliberately no output-file, simulator, collection,
training, inference, remote, process, or publication option.

## Artifacts

- Template: `configs/robot-port-profile-template-v1.json`
- Mantis reference:
  `configs/robot-port-profile-mantis-stack-bowls-v1.json`
- Synthetic test fixture:
  `tests/fixtures/robot-port-profile-synthetic-v1.json`

## Claim boundary

Passing profile validation establishes structural consistency, safe local
reference resolution, and deterministic stage planning only. The Mantis
profile describes one real reference port. The synthetic fixture is not a
second robot implementation and does not prove general runtime portability,
policy success, hardware safety, or AMD execution.
