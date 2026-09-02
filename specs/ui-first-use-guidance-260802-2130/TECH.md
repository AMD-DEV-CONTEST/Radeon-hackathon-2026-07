# Technical specification

- Level: S1
- Status: implemented

## Design

- `DashboardPage` derives onboarding state from the selected project's source-file count, task total, and run history. It uses in-page anchors so no new API endpoint or persisted UI state is required.
- `MaterialLibrary`, `TaskWorkbench`, and `RunCenter` expose stable section IDs for the guide's next-step button.
- `TaskWorkbench` switches from the default task-list tab to import only after loading confirms there are no tasks and no pending candidate tasks. It does not alter server data.
- `RiskReportCenter` keeps its normal workspace implementation, but renders a compact deferred state while both risks and report drafts are empty. A writer can still explicitly open the report workspace.

## Risks and rollback

The change is presentation-only and does not modify task, report, or permission APIs. Reverting the UI files restores the former always-expanded panels.

## Verification

- TypeScript production build.
- Existing frontend unit tests.
- Strict specification validation.
