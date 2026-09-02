# Product Specification — Stage I security review repair

| Field | Value |
|---|---|
| Spec ID | `stage-i-review-fix-260722-0100` |
| Level | S3 |
| Date | 2026-07-22 |
| Status | implemented |

## Objective

Close the security and integrity gaps found while reviewing the Stage I external-integration branch before it is merged.

## Accepted behaviour

- Email and SCM writes use two requests: preview creates a one-time confirmation ID; execute accepts only the exact previewed payload.
- Integration and automation APIs require an authenticated project member. Automation writes require `member`; webhook registration requires `pm`; reads require `guest`.
- Webhook registration requires a project ID, never dispatches on registration, never returns its secret, and rejects localhost/private/reserved IP targets.
- Credential encryption requires a stable deployment secret (`PROJECTPACK_INTEGRATION_KEY` or an explicit injected secret). A missing secret fails closed.
- Generated token, webhook, SCM-confirmation, and automation IDs are collision-resistant UUIDs.

## Non-goals

- This repair does not enable real GitHub/Jira or outbound webhook delivery.
- DNS resolution and outbound network egress policy remain deployment responsibilities; literal private/internal targets are rejected in application code.

## Acceptance criteria

- Anonymous automation access returns 401.
- A mismatched or reused email/SCM confirmation cannot execute a write.
- Webhook registration cannot disclose the supplied shared secret.
- Stage I connector and automation tests pass.
