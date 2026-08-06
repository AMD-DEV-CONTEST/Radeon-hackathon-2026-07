# SpriteFusion 2D

**Track 1 — Multimodal Content Creation Tools**<br>
**Owner / team:** kaggle4youAMD

SpriteFusion 2D is a Radeon-accelerated desktop workshop for turning generated or imported artwork into production-ready 2D game assets. It combines project-based asset management, background removal, outline extraction, pixel-art conversion, palette-aware grid recovery, AI image generation through ComfyUI, revision history, and an Electron creator interface.

The project addresses a common gap in generative workflows: an image model can produce an attractive picture, but game creators still need deterministic cleanup, consistent pixel grids, reusable palettes, transparent assets, and traceable revisions before the result is usable in a game.

## Current feature set

- Create, open, import, inspect, and recover SpriteFusion projects.
- Classify imported sources and organize assets and frames.
- Preview and apply transparent-background extraction.
- Generate configurable outlines for sprites.
- Convert pseudo-pixel or ordinary artwork into regular pixel art.
- Recover grids and compact palettes with deterministic processing modes.
- Submit ComfyUI image-generation jobs, monitor progress, inspect candidates, and commit a selected result to the project.
- Browse project history and perform undo/redo without duplicating state in the frontend.
- Run the workflow from both a CLI and an Electron desktop application.
- Use a mock sidecar for frontend development when the Python/ROCm stack is unavailable.

Video generation is intentionally outside this first submission version. The application keeps an extension point for a future image-to-video workflow, but the submitted and validated workflow ends with image and sprite asset creation.

## Architecture

```text
Electron renderer
    │ restricted context bridge
Electron main process
    │ JSON-RPC over stdio
Python Sprite Workshop daemon
    ├── project and revision store
    ├── background / outline / pixel processing
    ├── asynchronous job queue
    └── ComfyUI client
             │ localhost HTTP/WebSocket
        ComfyUI + ROCm PyTorch
             │
        AMD Radeon GPU
```

The renderer has no direct filesystem or child-process access. The Electron main process owns the Python sidecar and exposes only a narrow RPC bridge. Project state and history remain authoritative in the backend. Image paths are served through a restricted custom protocol with an allow-list rooted in user-selected or backend-confirmed project directories.

## AMD Radeon and ROCm

SpriteFusion 2D uses PyTorch tensor operations for palette learning, color assignment, grid recovery, and cell voting. On ROCm, PyTorch exposes AMD devices through the familiar `torch.cuda` API. The optimized algorithm keeps large image operations on the selected device and uses tiled matrix multiplication to bound memory consumption.

The integrated image-generation path connects to a local ComfyUI deployment running a ROCm-enabled PyTorch build. Models remain outside this repository and must be installed separately according to their licenses.

The current Radeon validation environment uses Ubuntu 24.04, ROCm 7.2, PyTorch 2.9.1 with HIP support, Python 3.12, and Node.js 20. The validated GPU target reports the `gfx1100` architecture.

## Requirements

- Python 3.10 or newer
- NumPy 1.26 or newer
- PyTorch 2.2 or newer; use an official ROCm build for AMD acceleration
- Pillow 10 or newer for workshop image I/O
- Node.js 20 or newer and npm for the Electron frontend
- Optional: a local ComfyUI server for AI image generation

Do not install a CUDA PyTorch wheel on the Radeon target. Follow the ROCm/PyTorch compatibility matrix for the host system.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[workshop,benchmark]"

cd frontend
npm ci
```

On Windows, activate the virtual environment with `.venv\\Scripts\\activate`.

Confirm that the AMD runtime is visible:

```bash
python -c "import torch; print(torch.cuda.is_available(), torch.version.hip, torch.cuda.get_device_name(0))"
```

A working ROCm environment prints `True`, a HIP version, and the AMD GPU name.

## Run the desktop application

From the repository root:

```bash
export SPRITE_WORKSHOP_PYTHON="$(pwd)/.venv/bin/python"
cd frontend
npm start
```

For a headless Ubuntu machine:

```bash
cd frontend
xvfb-run -a --server-args="-screen 0 1920x1080x24" \
  node_modules/.bin/electron . --no-sandbox
```

For frontend-only development:

```bash
cd frontend
SPRITE_WORKSHOP_FORCE_MOCK=1 npm start
```

## CLI examples

```bash
sprite-workshop doctor
sprite-workshop --help
```

The CLI exposes project initialization/import, inspection, recovery, background processing, sprite splitting, alignment, composition, packing, export, and history operations. Run the command-specific `--help` before modifying a project.

## ComfyUI generation

Install ComfyUI separately with a ROCm-compatible PyTorch environment and place an appropriately licensed image checkpoint in its model directory. Start ComfyUI on localhost, then launch SpriteFusion 2D without the mock-backend flag. The generation panel submits jobs, reports progress, loads generated candidates, and commits the selected candidate into the active project.

No model weights, private credentials, or cloud endpoints are included in this repository.

## Validation

```bash
python -m unittest discover -s tests

cd frontend
npm run sidecar:selftest
npm run test:rpc
```

The first submission snapshot has been exercised on an AMD Radeon `gfx1100` / ROCm 7.2 environment. The recorded project validation included 377 Python tests, 21 frontend tests, a focused V2 test set, and a real ComfyUI submit-to-candidate-to-project smoke workflow.

## Submission materials

- Source code and reproducibility README: included in this directory.
- Project profile PDF: will be added to this same pull-request branch after final layout review.
- Demo MP4: will be added after the final Radeon GUI recording is approved.
- Poster or presentation: will be added with the final media package.

These pending media items are intentionally not represented by empty or fabricated files. The pull request remains updatable, so later commits to its source branch will appear automatically.

## Licenses and credits

The repository code is provided under the MIT License. The pixel-snapper implementation builds on the MIT-licensed Sprite Fusion Pixel Snapper by Hugo Duprez and includes a PyTorch/ROCm redesign. Third-party models and ComfyUI are distributed separately under their own licenses.
