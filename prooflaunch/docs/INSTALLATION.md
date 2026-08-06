# Installation and Reproduction

## Supported paths

| Path | Purpose | Hardware |
|---|---|---|
| Local evaluator replay | Verify workflow, approvals, receipts, and export | CPU; no GPU required |
| Web workspace | Inspect the product UI | Node.js 20+ |
| Radeon inference | Execute key multimodal inference | AMD Radeon with supported ROCm/HIP |

Python 3.10–3.12 is supported. Python 3.11 is used in continuous integration.

## Local evaluator replay

```bash
git clone <public-repository-url> prooflaunch
cd prooflaunch
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python demos/run_track1_demo.py
```

Expected terminal state:

- `status` is `local_governed_replay_passed`;
- ten run-bound deliverables are registered;
- `radeon_execution_observed` remains `false` for this replay;
- the next gate requests live Radeon capture.

The default output is `artifacts/judge-track1-replay-v1/`.

## Verification

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python scripts/validate_amd_track1_package.py
```

## Web workspace

```bash
cd web
npm ci
npm run build
npm run preview
```

Open the address printed by the preview command. The web build is static; the
governed API is served separately by the Python runtime when a live workflow is
started.

## AMD Radeon / ROCm

Install a PyTorch build compatible with the host ROCm version first. Then:

```bash
python3 -m venv .venv-radeon
. .venv-radeon/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-radeon.txt
python scripts/capture_v10_radeon_live_preflight.py \
  --output evidence/v10/radeon-live-preflight.json
```

Continue with [RADEON_SETUP.md](RADEON_SETUP.md). Model weights are not bundled;
the model card and supply-chain registry provide immutable identifiers and
rights locators.

## Secrets and data

The core replay requires no cloud credential. Copy `.env.example` only for
optional local control-plane settings. Never run competition commands with
customer, regulated, or confidential inputs.

## Troubleshooting

- Import error: confirm the virtual environment is active and run
  `python -m pip install -e .` again.
- Missing campaign media: verify the public export manifest and re-extract the
  package without changing file names.
- ROCm/HIP not detected: stop; do not treat CPU, Apple Metal, CUDA, or provider
  output as Radeon evidence.
- Hash mismatch: restore the exact exported bytes rather than editing a receipt.
