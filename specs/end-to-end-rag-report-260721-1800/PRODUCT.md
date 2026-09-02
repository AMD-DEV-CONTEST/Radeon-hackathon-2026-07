# End-to-End RAG Report Run

## Background

The Office Agent must convert a project's source files and task list into an
auditable report through the controlled runner, rather than relying on manual
evidence fixtures.

## User-visible behavior

- A queued project run can be explicitly executed through the run API.
- The fixed pipeline parses source files, builds a project index, retrieves
  evidence per task, evaluates tasks, and writes a source-linked report draft.
- A completed run exposes only safe relative artifact paths and step summaries.

## Non-goals

- This change does not allow arbitrary tools, shell commands, or arbitrary
  document paths.
