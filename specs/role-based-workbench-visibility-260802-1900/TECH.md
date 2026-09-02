# Technical specification

- Level: S1
- Status: implemented

## Scope

- Expose a safe `is_system_admin` flag in authenticated profile responses.
- Enforce project creation as a system-administrator operation when project authorization is enabled.
- Resolve the signed-in user's project role from the project member list and render read-only UI states for guests.

## Risks and rollback

Project creation is intentionally more restrictive. Add the intended username to `system_admin_usernames` before deployment when using a non-default administrator account. Revert this change to restore the previous creation policy.

## Verification

- Backend authorization tests verify that a member cannot create a project in production mode.
- Web build and unit tests verify the updated auth DTO contract.
- Full Python test suite and strict specification validation are run before merge.
