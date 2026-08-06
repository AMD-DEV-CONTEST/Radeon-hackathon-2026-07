---
name: 01-evolution-requirement-focus
description: Guides semantic scoping of an evolution request while preserving unaffected package systems.
metadata:
  system_id: requirement_focus
  stage_order: 1
  load_when: requirement_focus
---
# Evolution Requirement Focus

## Role
Turn the structured evolution task analysis into a bounded package delta. The existing published package is the baseline; evolution does not scaffold or replace it.

## Required Flow
1. Inspect the active stage and task-analysis digest with `create_agent_stage(action="inspect")`.
2. Read the current manifest and assembly, then only the contracts named by `affected_systems`.
3. Preserve every system listed by `preserved_systems` and every unrelated valid package field.
4. Resolve model and model-tool needs before deciding a package tool is necessary.
5. For each `resource_requirement`, distinguish deployment configuration from per-call business input and carry the descriptor into capability implementation.

## Boundaries
- Do not translate a broad user goal into one keyword-selected file or tool.
- Do not use a failed trace as the main goal unless task analysis marks it relevant.
- Do not ask for resource values during evolution authoring; declare descriptors for post-publication configuration.
- Move to capability implementation only when affected, preserved, model, tool-source, and resource surfaces are explicit.
