---
name: 04-evolution-validation-publish
description: Guides evidence-based validation and publication of an evolved AgentPackage.
metadata:
  system_id: validation_publish
  stage_order: 4
  load_when: validation_publish
---
# Evolution Validation And Publish

## Role
Validate the complete evolved package, repair only evidence-backed defects, and finalize the in-place publication.

## Required Flow
1. Confirm changed Package Tools have fresh successful probe evidence.
2. Run `create_agent_validate(scope="full_static")` after the final package mutation.
3. Repair validator-indicated paths through their owning authoring action and repeat validation.
4. Confirm preserved systems remain present and Resource selectors/descriptors are aligned.
5. Call `create_agent_control(action="finalize")` exactly once after validation passes.

## Completion Summary
State the user-visible capability delta, preserved behavior, Resource fields requiring configuration, and validation result. Do not claim that a Resource value was configured when only its descriptor was published.
