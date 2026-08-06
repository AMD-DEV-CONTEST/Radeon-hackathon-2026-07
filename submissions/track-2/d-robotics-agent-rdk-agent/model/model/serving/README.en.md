> Chinese version: [README.md](README.md)

# Tier 1 — Start the SFT Service on Radeon and Verify Its Identity

Judge path: one command downloads the public weights, verifies the artifact identity, starts the service, and waits until it is healthy. Approximately 20 minutes, excluding download time.

`qwen3_agentic_openai_server.py` is the **original server artifact** used for the formal evaluation (SHA-256 `95d5c139…`; it is the same hash bound by `../deployment_manifest.orig.json` and the A/B evaluator's expect set).

## 1. Deploy

```bash
bash deploy.sh
```

`deploy.sh` runs, in order: preflight (Python ≥ 3.10 and a ROCm torch that can see the GPU) → download the base (`unsloth/Qwen3-32B-bnb-4bit@7f721e74`) and the adapter (ModelScope `ming01/Qwen3-32B-Agentic-SFT-r1-v3`) → **fail-closed identity check: the adapter SHA-256 must equal `4dcee691…f20bf`, otherwise it refuses to serve** → install the pinned dependencies → start the server → poll `/health` until it reports `checkpoint-000119`. Steps that are already satisfied are skipped, so the script is safe to re-run.

```bash
DRY_RUN=1 bash deploy.sh   # verify host and artifacts only; start nothing
```

Measured environment: AMD Radeon gfx1100 (approximately 19.3GB VRAM in use), ROCm 7.2.1, Python 3.12, torch 2.9.1+rocm7.2.0. The script does not install ROCm itself; if torch cannot see a GPU it exits with the exact install command. Ready output:

```
{"status":"ok","model":"Qwen3-32B-Agentic-SFT-r1-v3","checkpoint":"checkpoint-000119"}
```

Overrides, if the defaults do not fit: `BASE_MODEL`, `ADAPTER`, `API_KEY_FILE`, `PORT`, `SKIP_DEPS=1`. Each step is a plain shell line in `deploy.sh` if you prefer to run them by hand.

## 2. Behavioral probe (optional; proves that the adapter took effect)

```bash
python3 ../ab-probe/probe.py ./api_key probe-out.json
# Compare with ../ab-probe/probe-sft-*.json. To start a base-only service (serve.sh rejects a missing ADAPTER),
# invoke the server directly with --model and without --adapter; the output should align with the probe-base-*.json side.
```

## Agent integration interface

The model service exposes only standard interfaces and neither provides nor takes over `rdk-agent` configuration:

- Base URL: `http://<radeon-host>:8000/v1`
- Endpoint: `POST /chat/completions`
- Model: `Qwen3-32B-Agentic-SFT-r1-v3`
- Authentication: `Authorization: Bearer <API_KEY>`

The API Key is supplied by `API_KEY_FILE` on the Radeon host; the real Key is never stored in the repository. The user configures the `rdk-agent` provider, Base URL, model name, and API Key on the Agent side.
