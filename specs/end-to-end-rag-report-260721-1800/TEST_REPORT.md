# Test report

- Target branch: `fix/phase-c-contract-adaptation`
- Result: passed

## Commands

```powershell
py -m pytest -q
py scripts/validate_specs.py
```

## Evidence

- Local: `146 passed, 6 skipped`
- Specification validation: `spec validation: checked errors=0`
- Cloud: `python scripts/verify_end_to_end_rag_report_cloud.py`
  - Project: `rag-report-smoke-20260721074656`
  - Run: `7c08c819a5ff4bdc9b16a5a774d87b43`
  - Result: completed; 1 parseable source file, 1 indexed chunk, 1 evaluated
    task, and a report artifact with the retrieved `status.md` citation.
