# UI-1a: project dashboard and run center

## Goal

Provide the first usable project-facing Web workbench page: authenticated users
can select an accessible project, inspect its summary and run history, start a
report run, observe progress, cancel/retry a run where permitted, and download
the generated artifacts.

## Acceptance

- Project data is loaded only through authenticated APIs.
- Run history shows status, timestamps, error summary, and available artifacts.
- Starting, cancelling, and retrying a run prevents duplicate clicks and shows
  the API result or a recoverable error.
- Artifact downloads use the controlled API path, never a filesystem path.
