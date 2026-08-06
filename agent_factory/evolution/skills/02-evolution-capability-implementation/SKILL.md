---
name: 02-evolution-capability-implementation
description: Guides coherent in-place capability changes using the shared manufacturing authoring surfaces.
metadata:
  system_id: capability_implementation
  stage_order: 2
  load_when: capability_implementation
---
# Evolution Capability Implementation

## Role
Apply the analyzed delta through the same model selection, MCP, SkillHub, Resource, Package Tool, dependency, knowledge, state, and scheduler authoring capabilities used by manufacturing.

## Required Flow
1. Preserve the current valid implementation outside the analyzed delta.
2. Resolve auxiliary modality needs through `model_pool_select` and `configure_model_bindings` before custom executable code.
3. Evaluate existing built-ins, inherited MCP, and SkillHub in that order; author a Package Tool only for a remaining governed action.
4. Before a Package Tool is written, materialize every required deployment resource as a descriptor and connect it through ToolSpec `resources` selectors.
5. Submit the tool, its descriptors, dependencies, and node exposure as one `upsert_package_tool` authoring increment.
6. Probe every changed Package Tool through a fresh success path.

## Resource Contract
- Accounts, credentials, API keys, mailboxes, database connections, fixed endpoints, and default destinations are Resource fields, not Tool input fields.
- Preserve `enum`, `minimum`, `maximum`, `minLength`, and other known JSON Schema constraints in `value_schema`.
- Tool source reads declared values only from `run(arguments, resources)`; it must not contain real or placeholder credentials.
- `used_by` must name each consuming package tool and ToolSpec selectors must resolve to an existing or simultaneously supplied descriptor.

## Boundaries
- Do not hand-edit managed package surfaces.
- Do not recreate model-tool, MCP, or verified SkillHub capability as Package Tool code.
- Do not reset unrelated contracts to make validation pass.
