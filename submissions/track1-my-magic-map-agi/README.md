# Track 1 — My Magic Map AGI

- **Participant / team:** Eimis Pacheco
- **Application:** My Magic Map AGI
- **Track:** 1 — Development of Multimodal Content Creation Tools
- **Source repository:** https://github.com/EimisPacheco/my-magic-map-agi-adm

My Magic Map AGI is a body-controlled, multimodal world-exploration and
content-creation experience. A user walks and steers through Street View with
live pose tracking, points at objects with a hand, nose, or companion paw,
asks spoken questions, and turns real places into paintings, postcards, and
virtual memories.

## Submission materials

| Official requirement | Evidence | Status |
| --- | --- | --- |
| Project background and target users | [Project profile PDF](My_Magic_Map_AGI_Track1_Project_Profile.pdf), pages 1–2 | Complete |
| System architecture | [Architecture PNG](my-magic-map-agi-architecture.png), [SVG](my-magic-map-agi-architecture.svg), and profile page 3 | Complete |
| Models and algorithms | Project profile, page 4 | Complete |
| AMD Radeon / ROCm adaptation | Project profile, pages 5 and 7; [technical record](AMD_TRACK1_SUBMISSION.md) | Complete |
| Complete source code | [`source/`](source) pinned submodule and the [public source repository](https://github.com/EimisPacheco/my-magic-map-agi-adm) | Complete |
| Environment, startup, dependencies | Source `README.md`, `.env.example`, `package-lock.json`, `amd-service/README.md`, and `amd-service/requirements.txt` | Complete |
| Supplementary material | [Project poster PDF](My_Magic_Map_AGI_Track1_Poster.pdf) | Complete |
| 3–5 minute actual-operation video | [AMD Magical Map AGI — 4:19 demo](AMD-Magical-Map-AGI.mp4) | Complete |
| Promotional artwork | [AMD Radeon / ROCm hero graphic](my-magic-map-agi-amd-ai-devmaster-track1-1200x627.png) | Complete |

## How AMD Radeon is used

| Feature | Radeon model / runtime | Output |
| --- | --- | --- |
| Paint a Place | SDXL Base 1.0 through ComfyUI on ROCm | Street View image-to-image artwork |
| Postcard Studio | The same SDXL Radeon pipeline | Downloadable styled postcard |
| Virtual Memories | The same SDXL Radeon pipeline | Creative place-memory image |
| Pointed-object vision | Qwen2.5-VL-3B-Instruct in BF16 on PyTorch/ROCm | Structured identity, category, description, confidence, and safe search query |

Latency-critical pose, face, and hand tracking remains in the browser for
privacy and responsiveness. OpenAI supplies live voice and documented
availability/identity-preserving fallbacks. Gemini is not used.

## Measured Radeon results

Measurements captured on the live Radeon workspace on August 6, 2026:

- AMD Radeon `gfx1100`, 48 GiB VRAM
- ROCm 7.2.1 / HIP 7.2.53211-e1a6bc5663
- PyTorch 2.9.1+rocm7.2.1 with GPU availability confirmed
- SDXL warm generation: 11.981 seconds average
- Qwen2.5-VL warm inference: 7.089 seconds average
- Both services resident: 24.00 GiB peak VRAM

The [technical record](AMD_TRACK1_SUBMISSION.md) contains the individual runs,
security boundary, adaptation decisions, and reproducibility notes.

## Reproduce

Clone recursively so the pinned project source is included:

```bash
git clone --recurse-submodules https://github.com/EimisPacheco/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07/submissions/track1-my-magic-map-agi/source
cp .env.example .env
npm install
npm run dev
```

The Radeon deployment steps, required model paths, authenticated FastAPI
bridge, ComfyUI startup, health checks, and smoke tests are documented in
`source/amd-service/README.md`. API keys, bearer tokens, model weights,
personal photos, and private data are intentionally excluded.

## Demo video

The submitted [4:19 actual-operation video](AMD-Magical-Map-AGI.mp4) shows
body-controlled Street View navigation, flying through the photorealistic map,
memory navigation, nose-pointed discovery and practical results, Paint a Place
creative controls, voice-guided travel, and the full system architecture. The
technical record and profile PDF provide the accompanying verified Radeon/ROCm
runtime evidence, adaptation decisions, benchmark method, and SDXL/Qwen timing
results.
