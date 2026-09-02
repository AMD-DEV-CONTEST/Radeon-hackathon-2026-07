# API Bootstrap and Model Health — Test Report

- Spec ID: `api-260720-1035`
- Test date: 2026-07-20
- Acceptance branch: `feat/app-bootstrap`
- Base commit: `ea843e8`
- Application target commits: `39205bf`, `205af1b`
- Current HEAD at report creation: to be updated by the documentation commit
- Environment: Windows local Python 3.13 virtual environment; Radeon Cloud Ubuntu 24.04, Python 3.12.3, AMD gfx1100, ROCm/HIP llama.cpp
- Result: passed
- Classification: deployment-verified

## Command results

| Command | Result | Notes |
| --- | --- | --- |
| `python -m pytest -q` (local) | 12 passed | Includes governance and Day 1 tests |
| `python scripts/validate_specs.py --strict` (local) | passed | No spec validation errors before this report was added |
| `git diff --check` (local) | passed | No whitespace errors |
| `/workspace/office-agent/.venv/bin/python -m pytest -q` (cloud) | 12 passed | Executed against Python 3.12 deployment |
| `curl http://127.0.0.1:8000/health` (cloud) | `{"status":"ok"}` | llama-server loaded Qwen3.6 |
| `curl http://127.0.0.1:9000/health` (cloud) | passed | API reported reachable model service |

## Behavior coverage

| Behavior | Current conclusion | Evidence |
| --- | --- | --- |
| B1 | verified | Cloud code checked out at `/workspace/office-agent`; editable dependencies installed; Uvicorn started on loopback port 9000 |
| B2 | verified | `tests/test_config.py` covers invalid port and empty model name; Settings validates the `/v1` suffix |
| B3 | verified | Local mock-transport tests cover success/failure; cloud response was `{"status":"ok","model":"qwen3.6-office-agent","model_service":{"reachable":true,"detail":"model service reachable","status_code":200}}` |
| B4 | verified | `.gitignore` excludes `.env`, `.venv`, `data`, `outputs`, `logs`, `models`, and `*.gguf` |

## Known limitations

- Health only proves llama-server is reachable; it does not yet submit a chat completion.
- The cloud container does not automatically restore `sshd`, llama-server, or Uvicorn after an instance restart; data persists on PVC but processes must be restarted.
- The cloud Git client requires the image's GitHub proxy URL because direct GitHub certificate verification fails in this image. TLS verification was not disabled.

## Follow-up

- Add a model chat smoke test when the first LLM client endpoint is implemented.
- Add project-directory isolation and import APIs in the next spec.
