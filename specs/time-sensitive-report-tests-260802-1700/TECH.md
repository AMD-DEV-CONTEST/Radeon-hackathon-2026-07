# Technical specification

- Level: S1
- Status: implemented

## Scope

Replace only time-sensitive fixed dates in tests that assert a completed status.

## Implementation plan

- Build the fixture deadline from `date.today() + timedelta(days=30)`.
- Keep explicit historical deadlines in tests that intentionally verify overdue behavior.

## Risks and rollback

Low risk. This changes test fixtures only and can be reverted without affecting runtime behavior.

## Verification

- Run the two previously failing tests.
- Run the complete pytest suite.
- Run strict specification validation.
