---
name: 06-context-system
description: Guides runtime context contract changes for produced agents.
metadata:
  system_id: context_system
  stage_order: 6
  load_when: context_system
---
# Context System

## Role
Guides runtime context contract changes for produced agents.

## Baseline Package Assumption
- The workspace starts with a scaffolded empty AgentPackage: required files, required contracts, and package asset directories already exist.
- Do not compare scaffolded files against schema or capability examples just to prove they are valid. The validator owns schema correctness.
- Treat focus files as suggested edit surfaces, not write locks. Edit cross-file references when one capability requires a coherent package change.
- Use examples to learn the smallest complete shape for a capability you are adding or repairing, not as a checklist for baseline scaffold files.
- Use schema resources only when validator evidence or an example is insufficient for a concrete failed path.

## When To Use This Skill
- The agent needs structured runtime context, compression, or cross-session memory behavior beyond defaults.
- A node/tool depends on specific context namespaces or fields.
- Validator reports context contract issues.

## Focus Files
- `contracts/context.json`

## Manufacturing Protocol
1. Inspect current focus and latest validation evidence with create_agent_stage(action="inspect") when the next action is unclear.
2. Read the current target package files before editing. Preserve unrelated valid scaffold content.
3. If the requested capability does not affect this focus, leave these files as-is and move to the next useful focus yourself.
4. When a complete capability increment is ready, update all required package surfaces coherently, then call create_agent_validate with the appropriate scope.
5. When validation fails, repair only validator-indicated target files and paths; do not start a broad schema audit.

## Capability Write Guidance
- Leave the scaffolded context contract as-is unless implemented behavior consumes or writes context fields.
- Use context for runtime execution facts, not for secrets or unmanaged external resources.
- Keep context names generic and capability-driven.
- Configure cross-session memory behavior only through `config.default_policy.cross_session_memory`; storage and indexing backends are App infrastructure.
- Leave context-window and compression thresholds null to follow the selected model, or set an explicit Agent override when required.

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
- `references/context_system.repair_hints.md`
- `references/context_system.common_errors.md`
- `references/context_system.validator_scope.md`

Schema reference, last resort:
- `references/context_system.schema.json`
