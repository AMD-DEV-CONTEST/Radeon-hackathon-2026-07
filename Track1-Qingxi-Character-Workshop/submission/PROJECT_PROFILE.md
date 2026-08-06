# Qingxi Rift Character Workshop — Project Profile

**Track:** Track 1 — Multimodal AI (Content Creation Tools)
**Event:** AMD AI DevMaster Hackathon 2026
**Submission language:** English

---

## 1. Project Background

Creating original anime-style characters usually requires separate tools for
lore writing, portrait illustration, and ability/stat visualization. Most
pipeline setups depend on cloud APIs and leave the artist juggling prompts,
tools, and formats.

Qingxi Rift Character Workshop is a **local, AMD Radeon-powered multimodal
workbench** that turns one text brief (optionally with a reference image) into
a complete, original character deliverable:

- Structured lore JSON grounded in an original fantasy world
- An anime-style portrait
- A composed character-card poster (six-affinity radar + spirit domain)

Everything runs locally on an AMD Radeon GPU through the ROCm software stack —
no third-party cloud API dependency for the core pipeline.

## 2. Target Users & Application Scenarios

| User | Scenario |
|------|----------|
| Hobbyist creators / fan artists | Fast original OC (original character) concepting without an art pipeline |
| TRPG / fiction writers | Quick visual + lore packs for NPCs and cast members |
| Content creators (video/social) | Consistent original character cards for series or worldbuilding |
| Students learning generative AI | See a full local text→image→poster pipeline on AMD hardware |

## 3. System Architecture

```
User brief (+ optional reference image)
        |
        v
[Gradio Workbench]  -- left inputs / right results / step progress
        |
        v
[Job Orchestrator]  -- state machine: planning -> imaging -> composing -> ready
        |
        +---> [LLM Role Planner]  Qwen2.5 (ROCm local)
        |        text -> validated CharacterCard JSON (Pydantic)
        |
        +---> [Image Gen]  SDXL anime checkpoint via Diffusers (ROCm local)
        |        txt2img / img2img-with-reference
        |
        +---> [Card Composer]  Pillow
                 poster = portrait + six-affinity radar + lore blocks
```

Design principles:

- **Local first:** all critical inference (LLM + diffusion) runs on the AMD
  Radeon GPU via ROCm; no core feature depends on a closed online API.
- **Sequential VRAM:** the LLM is unloaded before SDXL loads, so a 7B LLM and
  SDXL fit comfortably on a 24GB Radeon card.
- **Resilient JSON:** three decode attempts + tolerant extraction + schema
  coercion make the LLM path stable for demos.
- **MOCK mode:** full pipeline placeholders for laptop development and CI.

## 4. Model & Algorithm Introduction

| Stage | Model / Method | Notes |
|-------|----------------|-------|
| Lore planning | Qwen2.5-7B-Instruct (local, HF Transformers) | JSON-schema-driven generation; greedy + sampling retries; few-shot |
| Portrait | SDXL anime checkpoint (Animagine XL 3.1, Diffusers) | txt2img; img2img when a reference image is uploaded |
| Radar | Pillow polar polygon renderer | six affinities Form/Mind/Life/Matter/Void/Time, 0-100 |
| Card compose | Pillow layout + pixel-width text wrapping | portrait + radar + lore on one downloadable poster |
| Affinity scores | LLM-generated with schema fallback | all-zero outputs auto-replaced with a sensible spread |

All weights are open-source checkpoints (per-model licenses on Hugging Face).

## 5. AMD Radeon GPU / ROCm Adaptation

- **Runtime:** PyTorch for ROCm; `torch.version.hip` verified at startup.
- **Device detection:** `src/device.py` reports GPU name, VRAM, and ROCm hint;
  the UI badge shows the live device.
- **VRAM strategy:** profiles for 16GB/24GB; sequential model occupancy
  (unload LLM before loading SDXL); attention slicing + VAE tiling enabled.
- **Reproducibility:** `scripts/setup_env.sh` restores the whole environment
  offline from the PVC (wheels + model weights), so judges can relaunch with
  one command; demo recorded on the actual Radeon instance with `rocm-smi`.
- **No CUDA dependency:** the install scripts explicitly refuse default-PyPI
  torch wheels (`+cu*`) that would break ROCm.

## 6. Innovation & Originality

- **Original world system** (Qingxi Rift): six-affinity framework with own
  names and lore — no third-party IP names, art, or training assets.
- **One-shot multimodal deliverable:** text → structured lore + portrait +
  radar poster in a single local workflow.
- **Robust LLM→JSON engineering:** multi-attempt decoding, tolerant object
  extraction, and schema coercion turn a 7B chat model into a reliable
  character-API for demos.
- **Creator value:** a repeatable, local, cost-free OC generation loop.

## 7. Run / Reproduce (summary)

```bash
# one-time (online): download weights into models/ and pre-download wheels
bash scripts/download_models.sh

# after every instance launch (offline restore from PVC):
bash scripts/setup_env.sh

export MOCK=0
python3 app.py
```

See `README.md` and `docs/RADEON_CLOUD_CLEAN_START.md` for details.
