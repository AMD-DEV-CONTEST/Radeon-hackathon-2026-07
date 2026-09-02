# Test Report

- Status: verified

## Commands

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\validate_specs.py
```

## Evidence

- Full local suite: `149 passed, 6 skipped`.
- Specification validation: `spec validation: checked errors=0`.
- API tests cover project listing, project-scoped uploads, upload traversal/type
  rejection, and named run-artifact download.
- The Gradio workbench construction test does not require a live API or model.
