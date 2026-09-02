# UI-2 task API authorization repair

## Goal

Make the UI-2 task workbench safe to merge by enforcing project membership at
the service boundary and deriving audit actors from the authenticated user.

## Acceptance

- Unauthenticated task requests receive `401`.
- A project guest can read task data but cannot mutate task, confirmation, or
  import state.
- A member can perform permitted writes.
- Request-body `changed_by` and `confirmed_by` values cannot impersonate a
  different user in task history, confirmation records, or import audit data.
