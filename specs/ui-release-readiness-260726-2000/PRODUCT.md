# UI-6 Release Readiness Product Specification

- Level: S1
- Status: implemented

## Goal

Make the unified workbench build identifiable and locally releasable before
the final cloud-model validation. Operators must be able to identify the UI
version, verify exactly which frontend assets were produced, and roll back to
the previous known-good revision without relying on browser-local state.

## Scope

- Show a non-sensitive UI version in the authenticated application shell.
- Provide a repeatable release-artifact verification command.
- Document local checks, deployment order, rollback, and the cloud-only test
  boundary.

## Non-goals

- This change does not start a model service or claim that real RAG was run.
- This change does not add telemetry, external credentials, or real GitHub/Jira
  writes.
