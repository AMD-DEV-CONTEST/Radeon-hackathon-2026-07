# Controlled Report Artifact Bundle

- Level: S2
- Status: implemented

## Design

- Extend the public task-evaluation contract with the risk fields already
  produced by Phase C's rule and LLM evaluation.
- Adapt public evaluations back to Phase C's report generator input so the
  weekly report, risk CSV, and next-week plan retain a single generation
  implementation.
- The fixed `draft` runner tool writes:
  - `outputs/<project_id>/reports/<run_id>.md`
  - `outputs/<project_id>/risks/<run_id>.csv`
  - `outputs/<project_id>/plans/<run_id>.md`
- `RunState.artifacts` contains only the three safe relative paths.

## Risks and rollback

- If artifact rendering or a controlled write fails, the runner records the
  failure rather than reporting a completed run with missing output.
- Rollback removes the additional writes while retaining the existing Markdown
  report artifact.

## Verification

- Unit/integration test executes the complete controlled workflow with a mock
  embedder and verifies all artifact paths, content, and audit completion.
- Full repository tests and specification validation run before merge.
