# Project API authorization technical design

- Level: S2
- Status: implemented

## Design

- Add `enforce_project_authorization=True` to runtime Settings.
- Add a shared project API guard using the existing token verification and
  project-member role hierarchy.
- Filter list endpoints instead of disclosing inaccessible project identifiers
  or run metadata.
- Use the existing membership service to create an admin membership atomically
  after a project directory has been created.
- Preserve strict authentication for file downloads.

## Compatibility

Legacy tests use an explicit `ENFORCE_PROJECT_AUTHORIZATION=false` test-only
environment setting while their API fixtures are migrated. It is not a runtime
default. New security tests explicitly enable enforcement.

## Rollback

Revert this change. No project data schema migration occurs.
