---
name: 02-model-system
description: Guides model and dependency contract changes for produced agents.
metadata:
  system_id: model_system
  stage_order: 2
  load_when: model_system
---
# Model System

## Role
Guides model and dependency contract changes for produced agents.

## Baseline Package Assumption
- The workspace starts with a scaffolded empty AgentPackage: required files, required contracts, and package asset directories already exist.
- Do not compare scaffolded files against schema or capability examples just to prove they are valid. The validator owns schema correctness.
- Treat focus files as suggested edit surfaces, not write locks. Edit cross-file references when one capability requires a coherent package change.
- Use examples to learn the smallest complete shape for a capability you are adding or repairing, not as a checklist for baseline scaffold files.
- Use schema resources only when validator evidence or an example is insufficient for a concrete failed path.

## When To Use This Skill
- The agent needs a non-default model role, output behavior, or dependency declaration.
- A package tool/node introduces runtime dependencies.
- Validator reports model/dependency contract issues.

## Focus Files
- `contracts/model.json`
- `contracts/dependencies.json`

## Manufacturing Protocol
1. Inspect current focus and latest validation evidence with create_agent_stage(action="inspect") when the next action is unclear.
2. Read `.factory/task_analysis.json` and identify model requirements before writing `contracts/model.json`.
3. Call `model_pool_select` with the model requirements and any auxiliary `tool_requirements` before inherited MCP evaluation, SkillHub search/install, and package tool authoring. If the result is blocked, ask the user to configure matching model pool profiles; do not silently fall back to the factory model.
4. Write model bindings and auxiliary model tool bindings only through `create_agent_authoring(action="configure_model_bindings", bindings=..., tool_bindings=...)`.
5. Read the current target package files before editing. Preserve unrelated valid scaffold content.
6. If the requested capability does not affect dependencies, leave those files as-is and move to the next useful focus yourself.
7. When a complete capability increment is ready, update all required package surfaces coherently, then call create_agent_validate with the appropriate scope.
8. When validation fails, repair only validator-indicated target files and paths; do not start a broad schema audit.

## Capability Write Guidance
- `contracts/model.json` uses `model_contract.v1`. New user AgentPackages should bind models from the local model pool; use `source: "env"` only when the package is explicitly designed to consume the host environment defaults.
- For `source: "model_pool"`, store `profile_id`, `selection_source`, `reason`, `required_capabilities`, and only the optional per-package `temperature` and `max_output_tokens` overrides. Context-window and compression overrides belong to `contracts/context.json`; provider capabilities and timeouts remain owned by the selected model-pool profile.
- Put auxiliary model tools in `config.tool_bindings` in the same `contracts/model.json`. They are system model tools exposed by runtime, not package tool source files.
- In the authoring call, `tool_bindings` is a top-level argument beside `bindings`; never nest it inside `bindings`.
- For `plan_and_execute`, auxiliary model tools are available to the executor through system tool exposure; the planner should not call business or model tools directly.
- Do not write provider `base_url`, `api_key`, account ids, or credentials into the AgentPackage.
- Leave dependency contracts as-is when the request does not require changes.
- Do not invent provider credentials, account ids, API keys, endpoints, or local paths.
- Declare dependencies and sandbox resources only for capabilities that are actually implemented in package files.
- Every non-stdlib, non-package-local, non-`agent_factory` Python import used by package tools must be represented in `contracts/dependencies.json` `config.python_requirements`.
- Inspect the current runtime with `create_agent_authoring(action="inspect_runtime_environment", system_binaries=[...])` before depending on host commands.
- Application Python/npm dependencies belong to the local shared pool. Host commands are capability declarations in `system_binaries`; the manufacturing runtime does not install operating-system packages.
- When dependencies require sandbox initialization, `config.install_timeout_seconds` must be a task-appropriate positive estimate. It is authored by the manufacturing model, not taken from a global runtime default.
- If an external resource is required but not confirmed, ask the user before writing concrete config.

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
- `references/model_system.repair_hints.md`
- `references/model_system.common_errors.md`
- `references/model_system.validator_scope.md`

Schema reference, last resort:
- `references/model_system.schema.json`
