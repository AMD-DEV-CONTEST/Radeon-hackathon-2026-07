# Verification Report

## Local verification

```powershell
py -m pytest -q
py scripts/validate_specs.py --strict
git diff --check
```

## Cloud verification

- Deployed branch: `feat/core-contracts` in `/workspace/office-agent`.
- API health: `GET /health` returned `status: ok`; the local llama-server was
  reachable.
- `POST /api/projects` for `cloud-contracts-1120` returned 201.
- `GET /api/projects/cloud-contracts-1120` returned 200 and contained the
  stored public metadata without an absolute host path.
- `LLMClient.generate_text()` returned exactly `CONTRACTS_READY`.
- `LLMClient.generate_json()` parsed the real model response as
  `{"answer":"cloud_verified"}`.

## Result

- Local test suite: 20 passed.
- Specification and whitespace validation passed.
- Cloud API and model integration passed on the active AMD instance.
