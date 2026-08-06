<!-- SOLO-COMPANY-HARNESS:START -->
# Solo Company Harness

This project uses the solo-company-harness workflow for AI coding.

Generated/updated: 2026-07-20T03:59:11+00:00

## Operating Contract

- Treat the user as the owner, operator, and final decision maker.
- Use the project SSOT before substantial work.
- Keep changes small, reversible, and verified.
- Record non-trivial work in `.harness/runs/`.
- Create case logs for medium/high-risk work, failed verification, surprises, or reusable lessons.
- Promote repeated lessons into `docs/playbooks/`.
- Do not silently update the harness skill from one-off feedback; write proposals first.

## Project SSOT

Read and update these files as living project memory:

- `docs/company.md` - company identity, business model, operating constraints.
- `docs/product.md` - product promise, users, scope, workflows, roadmap.
- `docs/customers.md` - segments, pains, feedback, objections, success signals.
- `docs/system.md` - architecture, stack, commands, data model, integrations, deployment.
- `docs/playbooks/` - repeated workflows and fixes.
- `docs/case-log/` - significant execution records.

Do not rewrite SSOT files from scratch during normal feature work. Update only changed sections and leave unknowns as `TBD`.

## Harness Commands

Skill path:

```text
C:\Users\Administrator\.codex\skills\solo-company-harness
```

Initialize SSOT:

```bash
python <skill-dir>/scripts/init_ssot.py <project-root>
```

Start a run:

```bash
python <skill-dir>/scripts/start_run.py <project-root> --title "<title>" --goal "<goal>"
```

Update a run:

```bash
python <skill-dir>/scripts/update_run.py <project-root> --changed-file <path> --decision "<decision>"
```

Detect tests and run checks:

```bash
python <skill-dir>/scripts/detect_tests.py <project-root> --write-run
python <skill-dir>/scripts/run_checks.py <project-root> --auto
```

Finish a run:

```bash
python <skill-dir>/scripts/finish_run.py <project-root> --lesson "<lesson>"
```

Refresh this block:

```bash
python <skill-dir>/scripts/init_agents.py <project-root> --skill-path <skill-dir>
```

## Risk Rules

- `low`: local, reversible, well-understood changes.
- `medium`: user-facing behavior, shared code, APIs, data shape, integrations, project structure, or deployment config.
- `high`: auth, payments, security, production data, migrations, irreversible operations, broad architecture, or public release.

For medium/high risk, require a clear contract, verification plan, rollback or recovery story, and residual-risk report.
<!-- SOLO-COMPANY-HARNESS:END -->

