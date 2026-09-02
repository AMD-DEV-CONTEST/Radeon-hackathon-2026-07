# API Bootstrap and Model Health

- Level: S2
- Status: verified

## Scope and affected components

- `app/config.py`: typed environment settings and validation.
- `app/llm/health.py`: HTTP probe of the local llama-server health endpoint.
- `app/api/health.py`: read-only FastAPI health response.
- `app/main.py`: application factory, state injection, and required runtime-directory creation.
- `pyproject.toml`: Python 3.12+ application and test dependencies.
- `.env.example` and `.gitignore`: safe configuration examples and artifact exclusions.

## Design

The configured OpenAI-compatible base URL must end in `/v1`. The model probe derives llama-server's health URL by removing `/v1` and appending `/health`; for the deployed configuration this is `http://127.0.0.1:8000/health`.

The endpoint is intentionally local-only. FastAPI listens on `127.0.0.1:9000` and llama-server listens on `127.0.0.1:8000`; browser access uses SSH port forwarding rather than public model exposure.

The app factory accepts an optional HTTPX transport so the model-health success and failure paths can be tested without a running model.

## Validation matrix

| Behavior | Verification | Evidence |
| --- | --- | --- |
| B1 | Install editable project and start Uvicorn on port 9000 | Local and cloud pytest; cloud Uvicorn listener on `127.0.0.1:9000` |
| B2 | Unit tests for invalid port and empty model; URL validator in Settings | `tests/test_config.py` |
| B3 | Unit tests for reachable/unreachable HTTPX transport; cloud curls to model and API health endpoints | `tests/test_health.py`; cloud curl output in `TEST_REPORT.md` |
| B4 | Inspect `.gitignore` and run `git status` after local install | `.gitignore`; no virtual environment or runtime artifacts staged |

## Risks and rollback

- If llama-server is stopped, the API returns `degraded`; it does not crash or silently claim success.
- This initial endpoint has no authentication because it binds to loopback only. Do not change it to a public host without a new security spec.
- Rollback is to stop the Uvicorn process and revert commits `39205bf` and `205af1b`; no schema migration or user data exists.

## Implementation record

- Base commit: `ea843e8`
- Implementation commits: `39205bf`, `205af1b`
- Verification report: `./TEST_REPORT.md`
