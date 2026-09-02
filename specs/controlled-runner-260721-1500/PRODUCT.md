# Controlled Run Lifecycle

## Background

The Office Agent must execute a fixed, auditable workflow rather than allowing
an LLM to choose arbitrary code or shell commands.

## User-visible behavior

- A project run can be created and queried through the API.
- Every run has a stable ID, a bounded step count, and an explicit lifecycle
  state.
- The runner invokes only tools registered by the application in the fixed
  order: scan, index, retrieve, evaluate, draft.
- Each transition and tool outcome is recorded as JSONL audit data.

## Non-goals

- This change does not implement task extraction, task evaluation, or report
  rendering. Those application tools will be supplied by later Phase C work.
- This change does not allow agents to execute shell commands or arbitrary
  Python functions.
