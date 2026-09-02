# Test report

- Target branch: `fix/phase-c-contract-adaptation`
- Environment: local Python test environment
- Result: passed

## Commands and evidence

```powershell
py -m pytest -q
py scripts/validate_specs.py
```

- Phase C and adapter regression: `84 passed`
- Full repository regression: `145 passed, 6 skipped`
- Specification validation: `spec validation: checked errors=0`
- Cloud smoke test: passed on 2026-07-21.
  - Command: `python scripts/verify_phase_c_cloud.py`
  - Chat endpoint: `http://127.0.0.1:8000/v1`
  - Result: one project-scoped task loaded; evidence citation retained; direct
    chat response received; rule-owned status remained `completed`; LLM
    explanation was applied.
