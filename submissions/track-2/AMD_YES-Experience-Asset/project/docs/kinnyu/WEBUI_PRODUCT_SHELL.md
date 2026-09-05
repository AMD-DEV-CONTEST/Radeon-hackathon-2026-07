# WebUI Product Shell Decision

## Decision

The final user-facing shell presents the existing M1-M5 implementation as one
five-step journey. M1 is the default landing view. System status remains
available as a utility view instead of competing with the product task.

| Step | User job | Visible intermediate artifact |
|---|---|---|
| M1 | establish source, goal, and boundary | Experience Brief |
| M2 | identify turning points | Critical Moment Map |
| M3 | reconstruct choices and evidence | Decision Evidence Ledger |
| M4 | form a reusable insight with limits | Insight Boundary Map |
| M5 | choose an audience route and review privacy | Route and publish preview |

This shell does not change API schemas, persistence, readiness gates, route
semantics, approvals, or tool permissions. Completion is never inferred from a
page visit. The Runtime remains the source of truth.

## Interaction rationale

- A long task is divided into logical stages with an explicit current step.
- The progress rail and the previous/next controls are separate navigation
  mechanisms.
- Every step names the intermediate artifact so progress is concrete without
  inventing a time estimate.
- Dynamic current-step text is exposed as a status message; keyboard focus is
  visible and a skip link reaches the active workspace.
- The responsive view preserves all five stages rather than hiding them behind
  an ambiguous menu.

Primary references:

- GOV.UK, Step by step navigation:
  <https://design-system.service.gov.uk/patterns/step-by-step-navigation/>
- U.S. Web Design System, Step indicator:
  <https://designsystem.digital.gov/components/step-indicator/>
- W3C WAI, Make Each Step Clear:
  <https://www.w3.org/WAI/WCAG2/supplemental/patterns/o1p04-clear-steps/>
- W3C WAI, Multi-page forms:
  <https://www.w3.org/WAI/tutorials/forms/multi-page/>
- W3C WCAG 2.2, Status Messages:
  <https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html>

## Track 2 and evidence impact

The UI makes the reliable Agent loop legible to judges: source grounding,
editable checkpoints, runtime-controlled transitions, late cross-asset RAG,
privacy review, and a final deliverable. Screenshots and the recorded demo must
use synthetic data and must show the real service path rather than a mock claim.
