---
name: 15-scheduler-seed-system
description: Guides user-confirmed scheduler seed jobs for produced agents.
metadata:
  system_id: scheduler_seed_system
  stage_order: 15
  load_when: scheduler_seed_system
---
# Scheduler Seed System

## Role
Guides user-confirmed scheduler seed jobs for produced agents.

## Baseline Package Assumption
- The workspace starts with a scaffolded empty AgentPackage: required files, required contracts, and package asset directories already exist.
- Do not compare scaffolded files against schema or capability examples just to prove they are valid. The validator owns schema correctness.
- Treat focus files as suggested edit surfaces, not write locks. Edit cross-file references when one capability requires a coherent package change.
- Use examples to learn the smallest complete shape for a capability you are adding or repairing, not as a checklist for baseline scaffold files.
- Use schema resources only when validator evidence or an example is insufficient for a concrete failed path.

## When To Use This Skill
- The user has confirmed a schedule such as time, recurrence, timezone, and target action.
- A scheduled job must trigger an existing graph/tool/script capability.
- Validator reports scheduler seed issues.

## Focus Files
- `contracts/scheduler_seed.json`

## Manufacturing Protocol
1. Inspect current focus and latest validation evidence with create_agent_stage(action="inspect") when the next action is unclear.
2. Read the current target package files before editing. Preserve unrelated valid scaffold content.
3. If the requested capability does not affect this focus, leave these files as-is and move to the next useful focus yourself.
4. When a complete capability increment is ready, update all required package surfaces coherently, then call create_agent_validate with the appropriate scope.
5. When validation fails, repair only validator-indicated target files and paths; do not start a broad schema audit.

## Capability Write Guidance
- Ask the user for missing schedule details instead of inventing time, timezone, recurrence, delivery channel, or target action.
- A schedule does not imply external push/notification capability unless that capability is confirmed elsewhere.
- Seed jobs must point to implemented package behavior; do not create jobs for nonexistent tools/nodes.
- Write scheduler seeds with create_agent_authoring(action="upsert_scheduler_seed") using a complete seed object. Do not hand-edit scheduler seed contract shape.

## Boundaries
- Do not hardcode secrets, API keys, account ids, external paths, URLs, schedules, delivery channels, or user data.
- Do not expose create-agent manufacturing tools, .factory files, traces, caches, or validation state as produced-agent runtime capability.
- Do not infer package schemas from project source code during manufacturing; use validator evidence and this skill's examples/resources.
- If required information is missing and cannot be discovered from confirmed resources, ask the user in natural language through create_agent_control.

## Validation And Focus
- Validator evidence guides repairs; successful or failed deterministic authoring, probe, validation, and publish operations synchronize focus through the manufacturing state machine.
- Use `create_agent_stage(action="set_focus", focus_id=..., reason=...)` only to correct or intentionally redirect focus.
- Finalization requires `validation_publish` and a fresh passed `full_static` validation; `create_agent_control(action="finalize")` then enters publish-ready state.

## Resource Loading
- Use a listed capability example when this skill provides one; otherwise rely on current package files and validator evidence.
- Read repair hints or validator scope only when validation evidence points here.
- Read schema only for a concrete validator failure path or when examples do not define the needed object shape.

Examples:
- `examples/scheduler_seed_system.capability.json`

Repair references:
- `references/scheduler_seed_system.repair_hints.md`
- `references/scheduler_seed_system.common_errors.md`
- `references/scheduler_seed_system.validator_scope.md`

Schema reference, last resort:
- `references/scheduler_seed_system.schema.json`
