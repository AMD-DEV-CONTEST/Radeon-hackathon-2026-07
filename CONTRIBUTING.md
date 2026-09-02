# Contributing

## Branches and commits

Use a focused branch for one change. Commit messages use Conventional Commits:

```text
feat(agent): add retrieval source citations
fix(runtime): recover model-server health check
```

Do not use vague messages such as `update`, `fix`, or `wip`.

## Pull requests and official submission

Every pull request in this competition repository must use this fixed official English title:

```text
Track 2, PLASMA, ProjectPack Office Agent
```

This title is for the PR. Keep individual Git commits in Conventional Commits format.

## Change levels

- `S0`: a small, clear change. State the goal and verification in the PR; no spec directory.
- `S1`: a contained feature or behavior change. Add `PRODUCT.md` and `TECH.md`.
- `S2`: cross-component, API, deployment, persistence, or permission change. Add a complete spec and verification report.
- `S3`: security, data migration, production deployment, or other high-risk change. Add a complete spec, verification report, rollback plan, and human review.

Create specifications under `specs/<module>-<YYMMDD>-<HHMM>/`. Copy the templates in `specs/_template/`.

## Before opening a PR

```powershell
git diff --check
py scripts/validate_specs.py --strict
py -m unittest discover -s tests -p 'test_*.py'
```

For a title check, run:

```powershell
py scripts/validate_pr_title.py --title 'Track 2, PLASMA, ProjectPack Office Agent'
```

Do not commit model files, SSH private keys, credentials, or personal file-system paths.
