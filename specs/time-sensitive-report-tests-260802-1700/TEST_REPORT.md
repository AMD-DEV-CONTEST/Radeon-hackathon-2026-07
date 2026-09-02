# Test report

- Change ID: time-sensitive-report-tests-260802-1700
- Status: passed

## Verification results

- `python -m pytest tests/test_phase_c_contracts.py::test_phase_c_adapters_preserve_evidence_and_render_a_public_report tests/test_task_reports.py::TestEvaluateWithLLM::test_llm_explanation_applied -q`
- `python -m pytest -q`
- `python scripts/validate_specs.py --strict`

The focused regression tests passed. The complete suite passed with `528 passed, 6 skipped`.
