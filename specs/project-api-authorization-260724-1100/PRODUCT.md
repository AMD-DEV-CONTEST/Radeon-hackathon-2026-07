# Project API authorization boundary

## Problem

The original project, file-upload, run, and global-run APIs could be called
without a project membership check. A browser UI cannot correct that weakness.

## Outcome

Production now requires authentication and project roles for the core APIs:

- creating a project automatically makes its creator a project admin;
- project lists and global run lists contain only projects the caller can view;
- project reads and run reads require `guest+`;
- file upload and run writes require `member+`;
- file download remains authenticated and requires `member+`.

## Non-goals

- No frontend visual change or data migration.
- Existing orphan projects are not silently assigned to a user; an administrator
  must explicitly establish their membership.
