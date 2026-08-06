# Track 1 Submission — Qingxi Rift Character Workshop

**Team:** Marsbler
**Track:** Track 1 — Multimodal AI (Content Creation Tools)
**App:** Qingxi Rift Character Workshop

## What this entry contains

```
Track1-Qingxi-Character-Workshop/
  app.py                       # Gradio workbench
  src/                         # device, world, schema, LLM, image, composer, orchestrator
  configs/                     # world.yaml (Qingxi Rift) + models.yaml
  prompts/                     # system role, schema, few-shot, repair
  scripts/                     # setup_env.sh, download_models.sh, install_app_deps.sh, ...
  data/eval/cases.jsonl        # 24 eval cases
  tests/                       # unit tests (pytest)
  docs/                        # local testing, Radeon Cloud guides, demo script
  README.md                    # full app README (env, run, deps)
  Qingxi_Rift_Character_Workshop.pptx   # supplementary material (PPT)
```

## Highlights

- Text brief (+ optional reference image) -> structured lore JSON + anime
  portrait + six-affinity radar poster, fully local.
- Critical inference (Qwen2.5-7B LLM + SDXL anime) runs on **AMD Radeon GPU
  via ROCm**; no core dependency on closed online APIs.
- Sequential VRAM: LLM unloaded before SDXL, fits 24GB Radeon.
- Offline env restore from PVC: `scripts/setup_env.sh`.

## Quick start

```bash
bash scripts/download_models.sh   # one-time online
bash scripts/setup_env.sh         # every launch (offline restore)
export MOCK=0
python3 app.py
```

See `Track1-Qingxi-Character-Workshop/README.md` and `docs/` for details.
