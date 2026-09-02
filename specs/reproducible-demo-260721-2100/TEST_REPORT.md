# Test Report

- Status: verified

## Commands

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\validate_specs.py
```

```bash
python scripts/verify_end_to_end_rag_report_cloud.py
```

## Evidence

- Local: `149 passed, 6 skipped`.
- Specification validation: `spec validation: checked errors=0`.
- Cloud verification passed on 2026-07-21 using the live chat and embedding
  endpoints.
  - Project: `rag-report-smoke-20260721120345`
  - Run: `f3bbb6c40f7d4c07b0c0ff2831751095`
  - Result: completed; 1 source file, 1 indexed chunk, 1 evaluated task, and
    report, risk CSV, next-week plan, and structured result artifacts present.
  - The report retained the `status.md` source citation.
