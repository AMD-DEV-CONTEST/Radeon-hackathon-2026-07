# Technical specification

- Level: S1
- Status: implemented

## Scope

- Add a role-capability summary to the React role helper.
- Thread the existing write capability into risk, report, confirmation-queue, and run-center components.
- Preserve the existing backend boundaries: project administrator for membership, project manager or administrator for risk lifecycle and report approval, and member-or-higher for normal project writes.

## Design

The browser never becomes the authorization authority. It receives role membership from the project API only to avoid presenting controls that the backend will reject. The API continues to check the authenticated user and project role for every write endpoint.

## Risks and rollback

This change can hide a control that an older deployment still expects to show, but it does not loosen backend access. Revert this change to restore the previous presentation while retaining server-side protections.

## Verification

- TypeScript production build and existing browser contract tests.
- Full Python regression suite.
- Strict specification validation.
