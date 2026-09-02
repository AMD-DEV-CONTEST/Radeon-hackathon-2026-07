# Technical Specification — Stage I security review repair

- Level: S3
- Status: implemented

## Changes

1. Replace the former one-shot integration endpoints with `/email/preview`, `/email/execute`, `/scm/preview`, and `/scm/execute`.
2. Persist one-time email confirmations and verify the submitted payload before SMTP execution. SCM executes the persisted preview only.
3. Apply current-user and project-role checks to both Stage I routers. Resolve an automation task to its owning project before authorizing mutation.
4. Persist webhook `project_id`; sanitize response DTOs; validate URL scheme, credentials, localhost, and literal non-global IP addresses; remove registration-time dispatch.
5. Derive AES-GCM keys with SHA-256 from a stable secret and fail closed if it is missing. Replace millisecond IDs with UUIDs.

## Configuration

`PROJECTPACK_INTEGRATION_KEY` must be set to a stable secret of at least 32 characters before any encrypted third-party token is stored.

## Verification

- `python -m pytest tests/test_stage_i_integrations.py -q`
- `python -m pytest tests/test_stage_i_automation.py -q`
- `python scripts/validate_specs.py --strict`
- `git diff --check`

## Rollback

Revert this review-fix commit. Do not restore one-step write endpoints in a production deployment.
