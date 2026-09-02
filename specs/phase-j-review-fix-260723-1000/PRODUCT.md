# Product Specification — Phase J security review repair

| Field | Value |
|---|---|
| Spec ID | `phase-j-review-fix-260723-1000` |
| Level | S3 |
| Date | 2026-07-23 |
| Status | implemented |

## Objective

Secure the Phase J production-management surface before merging it into `main`.

## Required behaviour

- All `/monitor/*` endpoints require an authenticated user.
- All `/admin/*` endpoints require a configured system administrator.
- Cache invalidation is restricted to a system administrator.
- Backup restore accepts only a validated backup directory under `backup_root`.
- Backup labels are filesystem-safe; repeated backup requests do not overwrite an existing snapshot.
- Log rotation accepts only a simple filename inside `log_root`.
- The overdue-task regression accepts `delayed` as an incomplete status.
