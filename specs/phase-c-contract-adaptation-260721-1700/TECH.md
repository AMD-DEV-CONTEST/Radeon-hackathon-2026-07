# Phase C Contract Adaptation

- Level: S2
- Status: implemented

## Scope

- Add project-scoped `load_tasks`, `evaluate_tasks`, and `render_reports`
  adapters in `app.services.phase_c`.
- Convert Phase C's internal dataclasses to the application's public Pydantic
  schemas at the integration boundary.
- Enforce that task input remains under `projects/<project_id>/source/`.

## Risks and rollback

- Risk: a project may contain no default task file or more than one default
  filename; the adapter fails explicitly rather than choosing arbitrarily.
- Rollback: remove the adapter and continue using Phase C's internal helpers
  outside the controlled runner.

## Verification

- Test project-scoped loading, traversal rejection, public-schema evaluation,
  and evidence-linked report drafting.
- Use `scripts/verify_phase_c_cloud.py` for a non-destructive cloud smoke test
  with the real chat model. The script creates a timestamped test project and
  never overwrites an existing project or task file.
