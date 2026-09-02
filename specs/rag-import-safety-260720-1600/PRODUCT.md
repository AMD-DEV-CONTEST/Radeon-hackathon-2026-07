# Phase A Import Safety and Traceability Repair

## Goal

Close the path-traversal vulnerability in the merged Phase A importer and make
every encountered source file visible in the import manifest, including
unsupported files and rejected symlinks.

## Acceptance criteria

- `project_id` follows the shared project-ID contract before any filesystem
  path is constructed.
- Importing `../../outside` fails without reading an outside source directory.
- The importer derives its root from the configured project root, not a
  hard-coded current-working-directory layout.
- Safe unsupported files are listed with `parse_status: unsupported`.
- Symlink escapes are listed with `parse_status: failed` and an explicit error,
  without hashing or reading the outside target.

## Out of scope

- Adding an HTTP import endpoint, indexing, or file-upload handling.
- File-size, page-count, and row-count limits; these are a separate resource
  control change.
