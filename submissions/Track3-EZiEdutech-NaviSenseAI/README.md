# Track 3, EZi Edutech, NaviSense AI

**Track:** 3 — Physical AI Challenge
**Team name:** EZi Edutech (solo — Zia, GitHub [@ziaac](https://github.com/ziaac))
**Application name:** NaviSense AI
**Deadline:** August 6, 2026 (UTC+8, 23:59)

NaviSense AI is an embodied SMCP (IMO Standard Marine Communication Phrases)
training environment: a cadet gives a spoken or typed bridge order, a local LLM
on an AMD Radeon GPU validates it against SMCP rules and returns pedagogical
feedback, and a real-time 3-DOF MuJoCo ship simulation executes the maneuver in
a 3D bridge view. All core inference (speech-to-text and language) runs locally
on a single AMD Radeon GPU.

## Links

| Item | URL |
|---|---|
| Source code | https://github.com/ziaac/navisenseAI |
| Live demo | https://navisense.eziedutech.dev |
| Demo video (3 min) | https://youtu.be/j2IzzsKH6QE |
| Technical report | `./TECHNICAL-REPORT.pdf` (this folder) |
| Docker image — web | `ghcr.io/ziaac/navisense-web:1.0` |
| Docker image — brain (CPU mock) | `ghcr.io/ziaac/navisense-brain-cpu:1.0` |
| Upstream contribution | https://github.com/ziaac/mujoco-ship-hydro |

## AMD Radeon GPU & ROCm

- **GPU:** AMD Radeon PRO W7900 48GB (Navi31, gfx1100), ROCm 7.2.1
- **LLM:** Qwen2.5-7B-Instruct Q6_K via llama-cpp-python (HIP/ROCm, full GPU
  offload) — **~90 tokens/s**, order evaluation 1.0–1.5 s
- **STT:** OpenAI Whisper large-v3-turbo on ROCm PyTorch (warm ~0.3–0.8 s)
- **Simulation:** MuJoCo 3-DOF ship hydrodynamics at 50 Hz (~27 ms/step)
- No remote model API is used for core functions; the GPU handles both STT and
  LLM inference locally. Full benchmarks are in the technical report (§4).

## Reproduce

See the source repo's `README.md` for step-by-step setup (GPU, CPU-mock, web,
database, Docker). A judge can run the whole pipeline without a GPU using the
CPU mock brain image:

```bash
docker pull ghcr.io/ziaac/navisense-brain-cpu:1.0
docker pull ghcr.io/ziaac/navisense-web:1.0
```

## Upstream open-source contribution

`mujoco-ship-hydro` — a standalone, reusable MuJoCo 3-DOF ship hydrodynamics
environment (MIT) extracted from this project:
https://github.com/ziaac/mujoco-ship-hydro
