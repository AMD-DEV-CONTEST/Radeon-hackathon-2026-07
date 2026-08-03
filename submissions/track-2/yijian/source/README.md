# YIJIAN Public Source Snapshot

This directory contains the public-safe source required to run the YIJIAN hackathon demo. It excludes private game records, local databases, creator-derived transcripts, review annotations, model weights and credentials.

## Directory structure

```text
backend/       FastAPI agent, Go rules, KataGo adapter, evidence builder and tests
web/           Single-page YIJIAN review workspace
deploy/cloud/  Radeon W7900 install, start, smoke-test and benchmark scripts
scripts/       Local verification and SSH tunnel helpers
```

## Requirements

- Python 3.11+
- FastAPI and Uvicorn
- KataGo v1.16.5 with an OpenCL-capable Radeon configuration
- Optional Qwen3.6-27B GGUF served by an OpenAI-compatible `llama.cpp` endpoint
- AMD ROCm 7.2.1 for the demonstrated W7900 Qwen runtime

## Local UI start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app:app --host 127.0.0.1 --port 8600
```

On Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8600
```

Open `http://127.0.0.1:8600/`.

Without KataGo, the service falls back to the deterministic demo engine. Configure KataGo through the environment variables documented in `.env.example` for real analysis.

## Radeon cloud start

```bash
bash deploy/cloud/install_cloud_runtime.sh
bash deploy/cloud/install_katago_opencl.sh
bash deploy/cloud/start_cloud_stack.sh
bash deploy/cloud/smoke_test.sh
```

The scripts expect model files outside the Git repository. Update model paths through environment variables rather than editing credentials into source files.

## Tests

```bash
PYTHONPATH=backend python -m pytest backend/tests -q
bash deploy/cloud/run_cloud_acceptance.sh
```

On Windows PowerShell, set `$env:PYTHONPATH=(Resolve-Path backend).Path` before running pytest. The public-safe snapshot currently passes **86 tests**. The full private development suite contains additional fixture-dependent tests and is reported separately in the submission metrics.

Some private-fixture import tests are intentionally omitted from this public snapshot.

## Security defaults

- Model services bind to `127.0.0.1`.
- Remote access uses an authenticated SSH tunnel.
- Provider keys are read from server environment variables.
- The browser does not receive provider secrets.
- Remote KataGo is disabled unless explicitly enabled.

## License notices

See `THIRD_PARTY_NOTICES.md`. Model weights are not redistributed.
