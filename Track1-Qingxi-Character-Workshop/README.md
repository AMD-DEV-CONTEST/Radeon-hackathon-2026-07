# Qingxi Rift Character Workshop

Track 1 multimodal tool for the **AMD AI DevMaster Hackathon**.

Turn a short character brief (optional reference image) into:

1. Structured lore JSON grounded in the original world **Qingxi Rift**
2. An anime-style portrait
3. A composed character-card poster (affinity radar + spirit domain)

All inference is designed for **local AMD Radeon + ROCm** (Radeon Cloud), with a full **MOCK** path for laptop development.

## Features

- Original six-affinity world config (`Form / Mind / Life / Matter / Void / Time`) - no third-party IP names
- LLM role planner -> validated `CharacterCard` JSON (Pydantic)
- Diffusers portrait path + Pillow card composer
- Gradio workbench: left inputs / right results, revise
- Device detection and VRAM profiles for ROCm/CUDA

## Quick start (MOCK)

```bash
cd character-workshop
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
# Windows PowerShell:
$env:MOCK=1
# Linux/macOS:
# export MOCK=1
python app.py
```

Open `http://127.0.0.1:7860`. Generate a card with any Chinese brief; mock mode skips heavy models.

Smoke import without launching the server:

```bash
$env:MOCK=1   # export MOCK=1 on Linux
python -c "from app import build_app; a=build_app(); print('ok', type(a))"
```

## Real inference (Radeon Cloud + ROCm)

### One-shot restore after each instance launch

Code, models and caches live on the PVC. After launching a fresh instance:

```bash
cd /persistent/qingxi-character-workshop/character-workshop   # adjust to your PVC path
bash scripts/setup_env.sh
```

`setup_env.sh` is idempotent and does everything in one command:

1. Points `PIP_CACHE_DIR` and `HF_HOME` at the PVC (`/persistent`) so installs re-run in seconds and models are never re-downloaded.
2. Verifies ROCm torch (never installs CUDA torch).
3. Installs app deps from `requirements.txt` + `accelerate --no-deps`.
4. Skips models already in `models/`, downloads only what's missing.

Then run:

```bash
export MOCK=0
python app.py
```

### Manual steps (equivalent, if you prefer step-by-step)

1. Launch a Radeon Cloud template with a **PyTorch ROCm** image and a **Persistent PVC** for models/outputs.
2. Clone or upload this repo onto the PVC-backed workspace.
3. Install app deps matching the image's ROCm torch (see `scripts/setup_rocm.sh` notes and AMD docs).
4. Download models:

   ```bash
   bash scripts/download_models.sh
   ```

5. Run real inference:

   ```bash
   export MOCK=0
   python app.py
   ```

6. Optional public preview via Radeon Cloud tunnel:

   ```bash
   rc-tunnel expose --port 7860
   ```

7. Verify device:

   ```bash
   python -c "from src.device import detect_device; print(detect_device())"
   ```

   Expect `device_type=cuda` and `rocm_hint=True` on ROCm images.

### PVC tips

- Keep `models/` and Hugging Face cache on PVC so restarts do not re-download.
- `setup_env.sh` points pip + HF caches at `/persistent` (override with `PVC_WORKSPACE` env).
- Write job artifacts under `outputs/<job_id>/` (already gitignored patterns apply).
- Destroy idle GPU instances after demos; keep PVC for weights.

## Tests

```bash
cd character-workshop
pytest -q
python scripts/run_eval_json.py
```

Eval script runs mock LLM generation over `data/eval/cases.jsonl` and asserts valid affinity + non-empty `image_prompt`.

## Project structure

```
character-workshop/
  app.py                 # Gradio workbench
  configs/
    world.yaml           # Qingxi Rift world + affinities + IP policy
    models.yaml          # LLM / image model ids
  prompts/               # system role, schema, few-shot, repair
  src/
    device.py            # ROCm/CUDA detection + VRAM profiles
    world.py             # world loader
    models_schema.py     # CharacterCard
    llm_role.py          # mock + HF character generator
    image_gen.py         # portrait (mock + Diffusers)
    card_compose.py      # poster composer
    orchestrator.py      # generate / revise jobs
    paths.py
  data/eval/cases.jsonl
  scripts/
    run_eval_json.py
    download_models.sh
    setup_rocm.sh
  tests/
  outputs/               # runtime job dirs
  models/                # optional local weights
```

## Limitations

- Real image quality depends on checkpoint choice and ROCm wheel compatibility.
- MOCK mode is for CI/dev only - not a substitute for demo-day GPU runs.
- Banned-IP substrings are filtered at config level; always write original characters.

## Licenses

- This project code: see repository license / hackathon submission terms.
- Base models (Qwen, Animagine XL, etc.): follow each model's license on Hugging Face.
- Do not ship third-party IP names, art assets, or unlicensed checkpoints in the submission package.

## Track 1 notes

- Multimodal pipeline: text (+ optional image) -> structured lore + portrait + card.
- Emphasize **local AMD ROCm** inference on Radeon Cloud, not cloud API-only demos.
- Demo checklist: UI generate -> revise; show `rocm-smi` / device badge.
- Keep world setting original (**Qingxi Rift**); document mock vs real paths in the write-up.
