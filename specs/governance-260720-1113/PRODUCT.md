# Fixed Submission Identity

## Goal

Require every pull request in this competition repository to use one stable
submission identity, so team, track, and application metadata cannot drift
between routine PRs and the final submission.

## Acceptance criteria

- The title `Track 2, PLASMA, ProjectPack Office Agent` is accepted.
- Any title that differs by track, team, application, punctuation, whitespace,
  or line break is rejected with an actionable error.
- Contributors can find the required title in `CONTRIBUTING.md`.

## Out of scope

- Git commit-message formatting remains Conventional Commits.
- This change does not alter branch permissions or merge methods.
