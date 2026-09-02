# UI-5 Test Report

## Automated checks

Run from repository root:

```powershell
python -m pytest -q tests/test_phase_j.py
cd web
npm test
npm run build
```

## Acceptance mapping

| Requirement | Evidence |
| --- | --- |
| No write before confirmation | Preview and execute are separate client/API calls; server issues one-time ID. |
| Duplicate confirmation does not duplicate | Existing SCM connector consumes confirmation ID. |
| Regular user cannot access operations API | `test_monitor_endpoint_requires_system_admin`. |
| No secret/token shown in UI | UI has no secret field and safe admin DTO omits model path. |
