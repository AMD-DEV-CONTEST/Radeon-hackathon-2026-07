---
name: 03-evolution-experience-assembly
description: Guides assembly updates that expose an evolved capability without replacing unaffected behavior.
metadata:
  system_id: experience_assembly
  stage_order: 3
  load_when: experience_assembly
---
# Evolution Experience Assembly

## Role
Expose the completed capability delta through the package's existing runtime pattern and user experience.

## Required Flow
1. Keep the current pattern unless structured task analysis explicitly requires a pattern change.
2. Add only implemented and registered tool ids to the nodes that need them.
3. Preserve unrelated prompts, activation semantics, bindings, and tool access.
4. For `plan_and_execute`, keep planning state in `runtime_plan`; business tools belong to executor or final delivery nodes, not planner.
5. Run assembly validation before entering final validation.

## Boundaries
- Do not expose authoring, validation, SkillHub administration, or other evolution-only tools to the produced Agent.
- Do not use prompt text to simulate a missing executable capability.
