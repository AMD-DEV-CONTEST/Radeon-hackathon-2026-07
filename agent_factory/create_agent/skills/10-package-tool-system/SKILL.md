---
name: 10-package-tool-system
description: Guides adding executable package tools and their ToolSpec declarations.
metadata:
  system_id: package_tool_system
  stage_order: 10
  load_when: package_tool_system
---
# Package Tool System

## Role
Guides adding executable package tools and their ToolSpec declarations.

## Baseline Package Assumption
- The workspace starts with a scaffolded empty AgentPackage: required files, required contracts, and package asset directories already exist.
- Do not compare scaffolded files against schema or capability examples just to prove they are valid. The validator owns schema correctness.
- Treat focus files as suggested edit surfaces, not write locks. Edit cross-file references when one capability requires a coherent package change.
- Use examples to learn the smallest complete shape for a capability you are adding or repairing, not as a checklist for baseline scaffold files.
- Use schema resources only when validator evidence or an example is insufficient for a concrete failed path.

## When To Use This Skill
- The requested capability needs package-owned executable logic rather than existing built-in tools.
- The agent needs user-facing actions such as list management, transformation, lookup through confirmed resources, or package state updates.
- Validator reports ToolSpec, entrypoint, syntax, or binding issues.

## Focus Files
- `contracts/tools.json`
- `assembly_spec.json`
- `agent_package.json`
- `tools/<tool_id>/manifest.json`
- `tools/<tool_id>/tool.py`

## Manufacturing Protocol
1. Inspect current focus and latest validation evidence with create_agent_stage(action="inspect") when the next action is unclear.
2. Read the current target package files before editing. Preserve unrelated valid scaffold content.
3. If the requested capability does not affect this focus, leave these files as-is and move to the next useful focus yourself.
4. Before authoring, classify stable accounts, credentials, endpoints, mailboxes, database connections, and default destinations as Resources rather than Tool inputs.
5. Inspect the current platform and every required host command with create_agent_authoring(action="inspect_runtime_environment", system_binaries=[...]) before choosing dependencies.
6. When a package tool capability is ready, pass the package tool business fields, tool source, dependency list, exposure targets, and any Resource Descriptors to create_agent_authoring(action="upsert_package_tool"), then call create_agent_validate with the appropriate scope.
7. When validation fails, repair only validator-indicated target files and paths; do not start a broad schema audit.

## Capability Write Guidance
- Add the complete package tool through create_agent_authoring(action="upsert_package_tool"); do not manually scatter writes across tool.py, manifest ToolSpec, agent_package.json tools index, contracts/tools.json, dependencies, and assembly tool access.
- Remove stale package tools through create_agent_authoring(action="remove_package_tool", tool_id=...); do not manually delete tool directories or manifest index entries.
- ToolSpec payloads must be objects, not string references.
- For `create_agent_authoring(action="upsert_package_tool")`, `tool_spec` contains only business-controlled fields: `id`, `description`, `input_schema`, `output_schema`, `resources`, `risk_level`, `concurrent`, and optional `output_compression`.
- If the tool needs deployment-time configuration, include `resource_descriptors` in the same upsert call. Every non-system ToolSpec resource selector must resolve to a current or supplied descriptor, and each descriptor `used_by` must include this tool id.
- Preserve known JSON Schema constraints such as `enum`, `minimum`, `maximum`, and `minLength` in each descriptor `value_schema`; tool source reads the configured values from `resources`, never from ordinary arguments or source constants.
- Do not provide `entrypoint`, `risk_evaluator`, `permission_scope`, or `permission_tags` in `tool_spec`; create_agent_authoring generates those system-controlled fields.
- Generated package tools are written to `tools/<tool_id>/tool.py`; create_agent_authoring generates `entrypoint=python:tools/<tool_id>/tool.py:run`, and `tool_source` must define a top-level synchronous `run(arguments, resources)` function. Do not use `main`, `tool:main`, or `python-import` entrypoints for generated package tools.
- `input_schema` only describes the runtime call arguments. Never put `output_schema`, `resources`, `risk_level`, `concurrent`, or `output_compression` inside `input_schema`.
- Add `tool_spec.output_compression.actions` when the tool output contains long lists, search candidates, external ids/slugs/paths, logs, reports, or other machine fields that must remain usable after compression. A single-link tool uses one action config; a multi-action tool sets `action_argument` and one config per action. Tools without an action config use the system default compression.
- Package tool entrypoints may return either a plain dict matching `output_schema` or `tool_envelope(...)`. Plain dict outputs are wrapped by the package-tool adapter. Use `tool_envelope` only when the tool needs explicit evidence or a custom summary.
- Package tool code must use the `resources` argument for declared runtime selectors such as `workspace_root`, `workdir_root`, or `runtime_root`; do not rely on `os.getcwd()` as the main resource contract. Generated user-facing files belong below `workspace_root`, which resolves to the active session workspace. `artifacts_root` is a compatibility alias for that same active workspace during a tool call, not a separate delivery location.
- When tool.py imports non-stdlib Python modules that are not package-local and not `agent_factory`, pass installable distributions as `python_requirements` to create_agent_authoring.
- create_agent_authoring rejects package tool writes before any files are changed when third-party imports exist but `python_requirements` is empty.
- Use installable Python distribution names in `python_requirements`; if an import name differs from the distribution name, determine the correct distribution from package documentation or validator evidence instead of guessing.
- Python requirements are normalized by distribution name and environment marker. Submit one intentional constraint per distribution and marker; a later declaration for the same identity replaces the earlier one.
- Python and npm requirements are installed into application-managed local dependency pools. Provide `install_timeout_seconds` as the maximum acceptable interval without observable builder output. It is a stall guard, not an installation ETA or total deadline.
- Do not declare Linux distribution packages or attempt `apt`, `dnf`, `yum`, `brew`, or `winget` installation. The manufacturing runtime never mutates the host package manager.
- Declare unavoidable host commands through `system_binaries`. If inspection reports a required command unavailable, ask the user or choose a portable implementation instead of repeatedly probing.
- Do not implement a tool that only tells the model to call another tool unless that other tool is visible in tool_access.
- Create package tools only after model selection, inherited MCP decisions, and the complete `11-skillhub-system` protocol have established a concrete remaining execution gap.
- The remaining gap must describe the missing governed runtime action; do not recreate SkillHub guidance, assets, templates, scripts, or registered skill-derived tools as package-owned code.
- After writing or changing a package tool, use create_agent_probe_tool inspect/call with realistic package tool arguments. Call starts an asynchronous probe job and returns a job id. Use status to observe dependency preparation and tool execution, then report the terminal result. `timeout_seconds` limits the target tool runner only; dependency preparation has its own observable stall guard. Include prompt and tool_goal as human-readable probe context.
- Do not create tools that require unconfirmed secrets, accounts, URLs, files, or external services.

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
- `examples/package_tool_system.capability.json`

Repair references:
- `references/package_tool_system.repair_hints.md`
- `references/package_tool_system.common_errors.md`
- `references/package_tool_system.validator_scope.md`

Schema reference, last resort:
- `references/package_tool_system.schema.json`
