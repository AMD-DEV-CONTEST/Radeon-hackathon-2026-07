# Poster / PPT Content Pack

Use for the Track 1 supplementary material (poster or PPT). All English.
Suggested title: **Qingxi Rift Character Workshop — Local Multimodal OC Creation on AMD Radeon + ROCm**

---

## Slide 1 — Title

- App name: Qingxi Rift Character Workshop
- One-liner: "Turn one brief into an original character card — fully local on AMD Radeon."
- Tags: Track 1 Multimodal · ROCm · PyTorch · SDXL · Qwen2.5

## Slide 2 — Problem

- Creating an original anime character = lore + portrait + stats, usually across many tools/APIs.
- Cloud-API pipelines are slow, paid, and not private.

## Slide 3 — Solution

- One local workbench: text brief (+ optional reference image) →
  structured lore JSON → anime portrait → character-card poster with a
  six-affinity radar and spirit domain.

## Slide 4 — How it works (diagram)

```
Brief (+ref image) -> LLM (Qwen2.5-7B, ROCm) -> CharacterCard JSON
                  -> SDXL anime (Diffusers, ROCm) -> portrait
                  -> Pillow compose -> card.png
```
All inference on AMD Radeon GPU, ROCm stack, no cloud API in the core path.

## Slide 5 — AMD Radeon / ROCm highlights

- `rocm-smi` + PyTorch-for-ROCm verified live in the demo.
- Sequential VRAM: LLM unloaded before SDXL — 7B + SDXL fits 24GB.
- Offline env restore: `scripts/setup_env.sh` (wheels + weights on PVC).

## Slide 6 — Reliability engineering

- 3-attempt JSON decoding + tolerant extraction + schema coercion.
- All-zero affinity scores auto-fallback to a sensible spread.
- MOCK mode for laptop dev; real runs on Radeon.

## Slide 7 — Demo stills

- 2–3 card screenshots (portrait + radar + lore) from the Radeon Cloud run.

## Slide 8 — Impact & originality

- Original Qingxi Rift world (Form/Mind/Life/Matter/Void/Time) — no third-party IP.
- Repeatable, private, zero marginal cost OC loop for creators.

## Slide 9 — Thanks / Links

- GitHub repo (to be public before PR).
- "Demo on Radeon Cloud, Track 1."

---

## Poster alternative (single page)

Blocks: Title | Problem | Pipeline diagram | AMD highlights | 3 demo cards | Impact.
Keep text large, 3–5 images max, one strong accent color.
