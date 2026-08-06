---
name: 00-manufacturing-control
description: Guides create-agent focus control, user questions, and manufacturing action boundaries.
metadata:
  system_id: manufacturing_control
  stage_order: 0
  load_when: manufacturing_control
---
# Manufacturing Control

## Role
Guides create-agent focus control, user questions, and manufacturing action boundaries.

## Baseline Package Assumption
- The workspace starts with a scaffolded empty AgentPackage: required files, required contracts, and package asset directories already exist.
- Do not compare scaffolded files against schema or capability examples just to prove they are valid. The validator owns schema correctness.
- Treat focus files as suggested edit surfaces, not write locks. Edit cross-file references when one capability requires a coherent package change.
- Use examples to learn the smallest complete shape for a capability you are adding or repairing, not as a checklist for baseline scaffold files.
- Use schema resources only when validator evidence or an example is insufficient for a concrete failed path.

## When To Use This Skill
- You need to inspect or change the active manufacturing focus through create_agent_stage.
- You need to ask the user for missing non-inferable information through create_agent_control.
- You need to decide whether to continue, wait for user input, or finalize into publish-ready state after validation evidence.

## Focus Files
- `.factory/system_state.json`
- `.factory/action.json`

## Manufacturing Protocol
1. Inspect current focus and latest validation evidence with create_agent_stage(action="inspect") when the next action is unclear.
2. Read the current target package files before editing. Preserve unrelated valid scaffold content.
3. If the requested capability does not affect this focus, leave these files as-is and move to the next useful focus yourself.
4. When a complete capability increment is ready, update all required package surfaces coherently, then call create_agent_validate with the appropriate scope.
5. When validation fails, repair only validator-indicated target files and paths; do not start a broad schema audit.

## Capability Write Guidance
- Use create_agent_stage(action="inspect") instead of reading managed .factory files directly.
- Only the model changes focus by explicitly calling create_agent_stage(action="set_focus", focus_id=..., reason=...).
- Capability assembly order is model selection first, pattern assembly tool access plus inherited MCP materialization second, the complete `11-skillhub-system` reuse phase third, and package tool authoring fourth. Do not write package tools before the preceding phases have produced evidence.
- Ask the user only for missing secrets, accounts, external resources, delivery channels, schedules, or ambiguous product decisions.
- After a complete capability increment, call create_agent_validate with the appropriate scope.

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

Repair references:
- `references/manufacturing_control.repair_hints.md`
- `references/manufacturing_control.common_errors.md`
- `references/manufacturing_control.validator_scope.md`

Schema reference, last resort:
- `references/manufacturing_control.schema.json`
