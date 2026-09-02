# Product specification

- Level: S1
- Status: implemented

## Goal

Make the first-use path of the project workbench understandable without prior training. A user should see what to do after creating a project, rather than several empty operational panels.

## Behaviour

- The dashboard presents the ordered path: upload project materials, import a task list, then generate a project report.
- Each step shows its current completion state and a button that scrolls to the next relevant section.
- When a writable project has no tasks or candidate tasks, the task workbench opens on the CSV/XLSX import tab rather than an empty filtered task table.
- When neither risks nor report drafts exist, the risk/report area is rendered as a compact explanatory card instead of filters and empty lists.
- Existing task, risk, report, approval, and role permissions remain available once data exists or the user explicitly opens the relevant workspace.

## Acceptance criteria

- A project with no source files guides a writer to project materials.
- A project with source files but no tasks guides a writer to task import.
- A project with tasks but no runs guides a writer to report generation.
- Empty risks and reports do not occupy a full operational dashboard by default.
- Read-only users receive explanatory state but no write actions.
