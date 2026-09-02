# Verification Report

## Required verification

```powershell
py -m pytest -q
py scripts/validate_specs.py --strict
```

## Result

- Local verification: `61 passed, 6 skipped`.
- Specification validation: `spec validation: checked errors=0`.
- Cloud verification: passed against separate local endpoints on 2026-07-21.
  - Chat endpoint: `http://127.0.0.1:8000/v1`
  - Embedding endpoint: `http://127.0.0.1:8080/v1`
  - Command: `python tests/test_remote_model.py`
  - Result: `24 passed, 0 failed`; 20-question benchmark with 100% hit rate,
    100% citation rate, and 60% refusal rate.
