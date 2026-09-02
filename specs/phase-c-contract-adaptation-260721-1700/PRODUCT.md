# Phase C Contract Adaptation

## Background

Phase C task and report logic must integrate with project-scoped RAG and the
controlled runner without exposing arbitrary local paths or private dataclasses.

## User-visible behavior

- Task lists are loaded only from the selected project's `source/` directory.
- Phase C evaluations use the shared `Task`, `Evidence`, `TaskEvaluation`, and
  `ReportDraft` contracts.
- Generated report drafts retain source links and evidence gaps.

## Non-goals

- This change does not add task-file upload or automatic task-file selection
  beyond the explicit supported filenames.
