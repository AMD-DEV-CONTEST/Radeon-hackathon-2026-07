---
name: 11-skillhub-system
description: Guides SkillHub capability discovery, installation verification, runtime wiring, and residual-gap decisions during AgentPackage manufacturing.
metadata:
  system_id: skillhub_system
  stage_order: 11
  load_when: skillhub_system
---
# SkillHub System

## Role
Guides the complete SkillHub reuse phase between model/MCP assembly and package-owned tool authoring.

## Baseline Package Assumption
- Model selection and model bindings are complete.
- Required factory MCP capabilities have been materialized or intentionally excluded.
- No package tool has been authored for a capability that may already exist as a reusable skill.
- Final pattern assembly is deferred until the reusable-skill and package-tool capability set is stable.

## When To Use This Skill
- The requested Agent needs reusable domain guidance, document conventions, workflows, templates, assets, scripts, or skill-derived tools.
- The model is deciding whether an execution gap requires a package-owned tool.
- A SkillHub installation must be verified and connected to runtime tool access.

## Focus Files
- `extensions/extension_bindings.json`
- `assembly_spec.json`
- `contracts/tools.json`

## Manufacturing Protocol
1. State the concrete capability gap in terms of input, expected output, runtime action, and evidence needed. Do not search from the entire user request verbatim.
2. Call `skillhub(action="status")`. If the CLI is unavailable, report the infrastructure blocker; do not replace the phase with an invented package tool.
3. Search with one to three high-signal keywords or one exact skill name. Use separate searches for distinct concepts and compare returned purpose, assets, execution surface, and install name.
4. Install only a selected result using its exact `install_name`: `skillhub(action="install", skill=<install_name>)`. Never concatenate title, version, summary, punctuation, or multiple candidates.
5. Verify the installed registration with `skill(action="describe", name=<installed skill_id>, current_system="capability_implementation")`. Load SKILL.md only when its guidance is needed; read only listed resources or script source required by the capability.
6. Classify what the installed skill actually provides: guidance, template/asset, non-executable script source, or registered ToolSpec execution entry. File presence alone is not runtime capability.
7. Include the runtime `skill` tool or registered skill-derived tool in the final pattern assembly. `react_agent` uses `answer`; `plan_and_execute` uses `executor` and `casual_react`, with `final_answer` only when delivery needs the skill. The planner does not call business tools.
8. Record the remaining execution gap. Create a package tool only when the installed skill and existing runtime/MCP/model tools cannot perform that action through the governed tool system.
9. Validate the resulting capability increment before moving to package-tool authoring or final assembly.

## Capability Write Guidance
- Treat SkillHub as capability reuse, not a source-code copying service.
- Installed scripts are inspectable source assets until registered as ToolSpec entries. Do not execute them through shell or copy them into a package tool to bypass permissions, traces, or output validation.
- Use skill guidance and templates through the runtime `skill` tool when the produced Agent needs them at run time.
- Keep the global Skill registry and `extensions/extension_bindings.json` managed by `skillhub`; do not hand-edit them.
- Do not install speculative skills that are unrelated to a confirmed capability gap.
- Do not claim a skill is integrated until install, Skill Gateway describe, runtime tool access, and validation evidence all agree.

## Boundaries
- Do not hardcode secrets, accounts, external paths, endpoints, schedules, delivery channels, or user data into a skill installation.
- Do not treat a SkillHub description as proof of executable behavior.
- Do not duplicate an installed skill as package knowledge or a package tool.
- Ask the user only when the remaining gap requires non-inferable resources or a product decision.

## Validation And Focus
- SkillHub work belongs to `capability_implementation`; it does not create a separate user-interaction interrupt.
- Deterministic authoring, installation, probe, and validation results may synchronize manufacturing focus; use `create_agent_stage(action="inspect")` when the active focus is unclear.
- Finalization requires `validation_publish`, a fresh passed `full_static` validation, and publish-ready finalization by `create_agent_control(action="finalize")`.

## Resource Loading
- Use `skillhub` for marketplace status, search, install, and remove.
- Use `skill` for installed-skill metadata, SKILL.md guidance, resources, templates, assets, and script-source inspection.
- Prefer `describe` before `load` or `read_resource`; use progressive disclosure and read only capability-relevant material.
