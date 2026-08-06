---
name: 12-assembly-pattern-system
description: Guides built-in runtime assembly bindings and runtime behavior.
metadata:
  system_id: assembly_pattern_system
  stage_order: 12
  load_when: assembly_pattern_system
---
# Assembly Pattern System

## Role
Guides built-in runtime assembly bindings and runtime behavior.

## Baseline Package Assumption
- The workspace starts with a scaffolded empty AgentPackage: required files, required contracts, and package asset directories already exist.
- Do not compare scaffolded files against schema or capability examples just to prove they are valid. The validator owns schema correctness.
- Treat focus files as suggested edit surfaces, not write locks. Edit cross-file references when one capability requires a coherent package change.
- Use examples to learn the smallest complete shape for a capability you are adding or repairing, not as a checklist for baseline scaffold files.
- Use schema resources only when validator evidence or an example is insufficient for a concrete failed path.

## When To Use This Skill
- The produced agent needs its runtime prompt, model operation, tool access, bindings, or output behavior updated.
- Package tools/nodes must be connected to a supported built-in runtime.
- Validator reports assembly compile or binding schema issues.

## Focus Files
- `assembly_spec.json`

## Manufacturing Protocol
1. Inspect current focus and latest validation evidence with create_agent_stage(action="inspect") when the next action is unclear.
2. Read the current target package files before editing. Preserve unrelated valid scaffold content.
3. If the requested capability does not affect this focus, leave these files as-is and move to the next useful focus yourself.
4. When a complete capability increment is ready, update all required package surfaces coherently, then call create_agent_validate with the appropriate scope.
5. When validation fails, repair only validator-indicated target files and paths; do not start a broad schema audit.

## Capability Write Guidance
- Supported runtime patterns are `react_agent` and `plan_and_execute`.
- Use `react_agent` for direct ReAct behavior.
- Use `plan_and_execute` only when the agent should create and maintain a dynamic per-run plan before and during execution.
- Configure built-in pattern bindings with create_agent_authoring(action="configure_pattern_assembly"). Provide prompt text and allowed tool ids; the tool writes coherent prompt, tool_access, model_operation, and runtime pattern references.
- For `plan_and_execute`, also provide `activation` with `workflow_goal`, `start_when`, and `ask_when_missing`. This lets the runtime route main workflow requests to planner/executor while routing non-main-workflow requests to the casual ReAct path.
- For `plan_and_execute`, do not write concrete plan steps into AgentPackage files. Runtime creates the actual plan through `runtime_plan`.
- For `plan_and_execute`, planner prompts should require outcome-oriented plan steps with `objective`, `acceptance_criteria`, and optional `tool_hints`. Do not ask the planner to produce a list of tool calls such as "read file -> write report"; tools belong in `tool_hints`.
- For `plan_and_execute`, executor and casual ReAct inherit scanned default system/MCP tools at runtime in addition to node-bound package/domain tools. Do not manually add default MCP tool ids such as `bigopen_*` just to make them visible.
- For `plan_and_execute`, executor receives package/domain tools, `knowledge`, `scheduler`, default system/MCP tools, workspace tools (`glob`, `ls`, `read`, `write`, `edit`), and guarded platform-shell fallback (`shell`). Executor prompts should tell the model to prefer package/domain tools, use workspace write/edit tools normally for declared deliverables, and use `shell` only when the current plan step cannot be completed through available package/runtime tools.
- Runtime prompts that expose workspace inspection tools should instruct the model to call `ls` on the parent or nearby directory before retrying `read` when a file is missing or the path is uncertain.
- For `plan_and_execute`, final_answer is a delivery node. It may use package/domain delivery tools and workspace inspection/generation tools to create or verify final artifacts, but it must not expose `runtime_plan` or mutate plan state.
- The runtime system prompt belongs in assembly prompt bindings produced by create_agent_authoring.
- Do not manually rewrite the whole assembly just to compare it with examples; use create_agent_authoring unless repairing a specific validator target path.
- Use complete examples for object shape only when adding or repairing bindings.

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
- `examples/assembly_pattern_system.capability.json`

Repair references:
- `references/assembly_pattern_system.repair_hints.md`
- `references/assembly_pattern_system.common_errors.md`
- `references/assembly_pattern_system.validator_scope.md`

Schema reference, last resort:
- `references/assembly_pattern_system.schema.json`
