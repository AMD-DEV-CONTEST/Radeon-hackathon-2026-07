---
name: 09-tools-system
description: Guides runtime tools contract changes and tool access declarations.
metadata:
  system_id: tools_system
  stage_order: 9
  load_when: tools_system
---
# Tools System

## Role
Guides runtime tools contract changes and tool access declarations.

## Baseline Package Assumption
- The workspace starts with a scaffolded empty AgentPackage: required files, required contracts, and package asset directories already exist.
- Do not compare scaffolded files against schema or capability examples just to prove they are valid. The validator owns schema correctness.
- Treat focus files as suggested edit surfaces, not write locks. Edit cross-file references when one capability requires a coherent package change.
- Use examples to learn the smallest complete shape for a capability you are adding or repairing, not as a checklist for baseline scaffold files.
- Use schema resources only when validator evidence or an example is insufficient for a concrete failed path.

## When To Use This Skill
- The agent needs built-in runtime tools, package tools, or changed tool access policy.
- A package tool is added and the tools contract must enable it.
- Validator reports tool contract issues.

## Focus Files
- `contracts/tools.json`

## Manufacturing Protocol
1. Inspect current focus and latest validation evidence with create_agent_stage(action="inspect") when the next action is unclear.
2. Read the current target package files before editing. Preserve unrelated valid scaffold content.
3. If the requested capability does not affect this focus, leave these files as-is and move to the next useful focus yourself.
4. When a complete capability increment is ready, update all required package surfaces coherently, then call create_agent_validate with the appropriate scope.
5. When validation fails, repair only validator-indicated target files and paths; do not start a broad schema audit.

## Capability Write Guidance
- Do not expose create-agent manufacturing tools as produced-agent runtime tools.
- Declare only tools that are available through RuntimeKernel built-ins, model tool bindings, package files, runtime skills, or inherited MCP candidates.
- Evaluate inherited MCP candidates after model selection and before SkillHub. If no inherited MCP capability is needed, skip MCP inheritance.
- To use an inherited MCP candidate, include its tool id through create_agent_authoring pattern assembly tool access, then call `create_agent_authoring(action="materialize_mcp_inheritance")` before validation.
- Run the complete `11-skillhub-system` protocol after MCP decisions and before package-tool authoring. This tool-system skill owns runtime tool declarations; the SkillHub skill owns search, installation verification, capability classification, and residual-gap decisions.
- Only registered ToolSpec entries are executable tools. Guidance, assets, templates, and unregistered scripts must remain behind the runtime `skill` gateway and cannot bypass permissions or traces.
- Keep contracts/tools.json aligned with assembly_spec tool_access bindings and package tool manifests.
- If a required runtime tool is unavailable in built-ins, package tools, or inherited MCP candidates, state the limitation or ask for confirmed integration resources.

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
- `references/tools_system.repair_hints.md`
- `references/tools_system.common_errors.md`
- `references/tools_system.validator_scope.md`

Schema reference, last resort:
- `references/tools_system.schema.json`
