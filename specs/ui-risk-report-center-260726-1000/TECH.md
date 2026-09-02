# UI-3 risk and report center — Technical Record

- Spec ID: `ui-risk-report-center-260726-1000`
- Level: S2
- Status: implemented

## Design

- `RiskReportCenter` is mounted only inside the selected project dashboard.
- Typed `ApiClient` methods and `API_PATHS` constants map one-to-one to the
  existing risks, reports, members, and comments routes.
- Risk actions use the server's PM role guard; report approval likewise uses
  its existing PM guard. UI role visibility is advisory only.
- The active project member list supplies the safe assignment selector.
- Report exports use blob responses and browser download URLs; no output path
  is exposed to the browser.
- DTO annotations are extended so the existing contract validator verifies
  every mapped Pydantic field and every added API route.

## Rollback

Revert this branch. Existing UI-0/1/2 views remain functional without the
UI-3 panel and no data migration is introduced.
