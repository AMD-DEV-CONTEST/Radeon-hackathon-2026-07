# Phase A Import Safety and Traceability Repair — Technical Record

- Level: S2
- Status: verified

## Design

- Reuse `app.security.paths.validate_project_id()` and
  `ensure_project_path()` so RAG and Project API enforce the same boundary.
- Add a detailed scanner result for the importer. The legacy simple scanner
  continues to expose only safe supported files for compatibility.
- An unsafe symlink is inspected with `lstat()` only; it is never opened,
  hashed, or parsed. Its manifest hash and modification time are `null`.
- A safe unsupported file is hashed and recorded as `unsupported`, allowing a
  UI and audit log to explain why it was skipped.

## Risk and rollback

- Consumers that assumed every manifest record had a SHA-256 string must now
  handle `null` for rejected unsafe paths.
- Rollback is to revert this change; no document content or persistent index is
  written by the scanner.
