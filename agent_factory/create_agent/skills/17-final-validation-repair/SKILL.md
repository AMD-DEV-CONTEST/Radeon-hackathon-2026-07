---
name: 17-final-validation-repair
description: Guides final validation, repair interpretation, and explicit publication readiness.
metadata:
  system_id: final_validation
  stage_order: 17
  load_when: final_validation
---
# Final Validation Repair

## Role
Guides final validation, repair interpretation, and explicit publication readiness.

## Baseline Package Assumption
- The workspace starts with a scaffolded empty AgentPackage: required files, required contracts, and package asset directories already exist.
- Do not compare scaffolded files against schema or capability examples just to prove they are valid. The validator owns schema correctness.
- Treat focus files as suggested edit surfaces, not write locks. Edit cross-file references when one capability requires a coherent package change.
- Use examples to learn the smallest complete shape for a capability you are adding or repairing, not as a checklist for baseline scaffold files.
- Use schema resources only when validator evidence or an example is insufficient for a concrete failed path.

## When To Use This Skill
- The model is in validation_publish focus and needs to interpret validation results.
- Full validation fails and repair must be routed to concrete package files.
- The package is ready for explicit Web publication approval after a successful finalize action.

## Focus Files
- `whole package readiness`

## Manufacturing Protocol
1. Inspect current focus and latest validation evidence with create_agent_stage(action="inspect") when the next action is unclear.
2. Read the current target package files before editing. Preserve unrelated valid scaffold content.
3. If the requested capability does not affect this focus, leave these files as-is and move to the next useful focus yourself.
4. When a complete capability increment is ready, update all required package surfaces coherently, then call create_agent_validate with the appropriate scope.
5. When validation fails, repair only validator-indicated target files and paths; do not start a broad schema audit.

## Capability Write Guidance
- Do not decide success by self-inspection. Use validator evidence from create_agent_validate and create_agent_stage inspect.
- If validator targets a scaffold-owned contract and no capability-specific authoring action applies, use create_agent_authoring(action="reset_contract", contract_key=...) instead of hand-writing contract JSON.
- Prefer validator fields such as target_files, schema_path, invalid_value_path, expected_shape, repair_template, and replace_strategy when present.
- If repair requires missing user information, ask the user instead of fabricating config.
- Call `create_agent_control(action="finalize")` only after `validation_publish` focus and a fresh passed `full_static` validation. Finalize ends manufacturing in publish-ready state; physical publication requires explicit approval through the Web confirmation panel.

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
- `examples/final_validation.capability.json`

Repair references:
- `references/final_validation.repair_hints.md`
- `references/final_validation.common_errors.md`
- `references/final_validation.validator_scope.md`
- `references/final_validation.repair_mappings.json`

Schema reference, last resort:
- `references/final_validation.schema.json`
