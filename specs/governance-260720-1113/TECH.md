# Fixed Submission Identity — Technical Record

- Level: S2
- Status: verified

## Implementation

- `scripts/validate_pr_title.py` exports the canonical `OFFICIAL_PR_TITLE`
  constant and requires byte-for-byte title equality after the single-line
  check.
- `tests/test_validate_pr_title.py` covers the canonical title and rejects a
  changed team name.
- `CONTRIBUTING.md` documents the one accepted PR title and keeps commit
  messages separate from PR-title policy.

## Risk and rollback

- Risk: a typo or trailing space blocks a PR title check.
- Mitigation: the failure output prints the exact accepted title.
- Rollback: revert commit `c902858` to restore the generic Track/Team/App
  title rule. No data, database, or deployment change is involved.
