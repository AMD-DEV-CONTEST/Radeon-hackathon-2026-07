# Test Report

- Status: verified

## Commands

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\validate_specs.py
```

## Evidence

- Full local suite: `146 passed, 6 skipped`.
- Specification validation: `spec validation: checked errors=0`.
- The controlled workflow test verifies that a completed run exposes report,
  risk CSV, and next-week plan relative paths.
- All three files remain within the project's configured output directory.
- The Markdown report retains a retrieved `status.md` citation.
