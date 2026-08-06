---
name: 08-knowledge-system
description: Guides package knowledge assets for produced agents.
metadata:
  system_id: knowledge_system
  stage_order: 8
  load_when: knowledge_system
---
# Knowledge System

## Role
Guides package knowledge assets for produced agents.

## Baseline Package Assumption
- The workspace starts with a scaffolded empty AgentPackage: required files, required contracts, and package asset directories already exist.
- Do not compare scaffolded files against schema or capability examples just to prove they are valid. The validator owns schema correctness.
- Treat focus files as suggested edit surfaces, not write locks. Edit cross-file references when one capability requires a coherent package change.
- Use examples to learn the smallest complete shape for a capability you are adding or repairing, not as a checklist for baseline scaffold files.
- Use schema resources only when validator evidence or an example is insufficient for a concrete failed path.

## When To Use This Skill
- The agent explicitly needs fixed, authoritative reference material bundled with the AgentPackage and retrieved or cited at runtime.
- A package tool/node depends on knowledge assets.
- Validator reports package knowledge asset issues.

Do not use this skill merely because an Agent has an identity, persona, system prompt, tool instructions, or because the user may upload knowledge after publication.

## Focus Files
- `knowledge/`

## Manufacturing Protocol
1. Inspect current focus and latest validation evidence with create_agent_stage(action="inspect") when the next action is unclear.
2. Read the current target package files before editing. Preserve unrelated valid scaffold content.
3. If the requested capability does not affect this focus, leave these files as-is and move to the next useful focus yourself.
4. When a complete capability increment is ready, update all required package surfaces coherently, then call create_agent_validate with the appropriate scope.
5. When validation fails, repair only validator-indicated target files and paths; do not start a broad schema audit.

## Capability Write Guidance
- Default to no package knowledge. An empty knowledge/ directory is correct for chat, creative, persona, and general tool-using Agents without fixed reference material.
- Do not invent knowledge content or claim live external knowledge unless backed by confirmed resources/tools.
- Identity, persona, tone, behavior rules, system prompts, tool instructions, schemas, manufacturing guidance, secrets, and dynamic external data do not belong in knowledge/.
- Valid sources, in priority order, are user-provided material approved for bundling, project-owned reference assets, distributable Skill assets, and public sources explicitly authorized by the user.
- Use runtime resources, mounted knowledge sources, APIs, databases, or search tools for external, mutable, user-managed, or post-publication material.
- Before writing, verify that the material is authoritative, distributable, stable enough to bundle, and genuinely needs retrieval or citation rather than prompt/config placement.
- Write confirmed package knowledge with create_agent_authoring(action="upsert_knowledge_file", knowledge_path=..., knowledge_content=..., knowledge_purpose=..., knowledge_source={source_kind, reference, distributable: true}) instead of generic filesystem write.
- Remove an invalid or obsolete package knowledge file with create_agent_authoring(action="remove_knowledge_file", knowledge_path=...); this also removes its source record.
- The source registry is maintained by create_agent_authoring and must not be edited directly.
- If authoritative material is missing, ask the user for it. Do not synthesize domain facts to fill knowledge/.

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
- `references/knowledge_system.repair_hints.md`
- `references/knowledge_system.common_errors.md`
- `references/knowledge_system.validator_scope.md`
