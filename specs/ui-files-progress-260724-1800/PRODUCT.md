# UI-1b: files and progress

## Goal

Extend the authenticated project workbench with a project-scoped material
library. A member can upload reference material or a task CSV/XLSX, inspect
the server-reported material state, and understand that indexing happens only
when a controlled run processes the material.

## Acceptance

- Only project members can upload or download a source file.
- A project guest can see only the metadata of that project's material list.
- The UI never reads a filesystem path or scans a server directory.
- Upload errors are shown as recoverable API errors.
- Every file row clearly distinguishes `uploaded` from `indexed`; the UI does
  not claim a file is parsed/indexed unless the backend has recorded it.
- Existing run-center progress and error presentation remains usable after an
  upload.
