# Phase A Reproducible Parser Dependencies — Technical Record

- Level: S2
- Status: verified

## Change

- Add `pypdf`, `python-docx`, and `openpyxl` as runtime dependencies because
  Phase A advertises PDF, DOCX, and XLSX parsing as supported behavior.
- Add `reportlab` only to the `dev` extra. It creates synthetic PDF fixtures in
  `scripts/verify_phase_a.py` and is not imported by the production parser.
- Test the declared dependency contract by reading `pyproject.toml` with
  Python's standard-library `tomllib`.

## Risk and rollback

- Installation size and time increase due to document parser packages and
  their transitive dependencies.
- Rollback is to revert this dependency-only change; no source documents,
  indices, or project metadata is migrated.
