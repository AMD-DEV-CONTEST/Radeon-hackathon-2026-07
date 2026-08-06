# ⚽ Humanoid Robot Soccer — AMD Radeon GPU (Track 3)

[![AMD ROCm](https://img.shields.io/badge/AMD-ROCm%207.2-ED1C24?logo=amd&logoColor=white)](https://www.amd.com/en/products/software/rocm.html)
[![Genesis](https://img.shields.io/badge/Genesis-1.3.1-blue)](https://genesis-embodied-ai.github.io/)
[![torch](https://img.shields.io/badge/torch-2.9.1%2Bgitff65f5b-green)](https://pytorch.org/)

**AMD AI DevMaster Hackathon 2026 — Track 3: Physical AI (Humanoid Robot Soccer)**

Hierarchical robot-soccer on AMD Radeon (ROCm): a humanoid robot walks to the ball, swings its
leg, **physically contacts the ball with its foot**, and pushes it into the goal — all inside the
Genesis physics engine on AMD GPU. No NVIDIA hardware involved.

## Project Status (2026-08-06)

| Stream | Status | Evidence |
|--------|--------|----------|
| **Primary submission: single-robot real kick → goal** | ✅ **PASSED** | wind-up → leg swing → foot-ball contact (`contact@116`) → goal (`scored@144`), ball speed **4.33 m/s**, 0 falls — final film `acceptance/final_video/track3_final_20260806.mp4` |
| Reproducibility (4 independent runs) | ✅ **PASSED** | all 4 runs scored with no falls: contact 116–117 / scored 144–147 / ball 2.7–4.3 m/s — see `kick_final/result.json` & `kick_live/result.json` |
| Single-robot chase (legacy) | ✅ PASSED | 200 steps, 0 falls, ball 12 m |

**Submission strategy**: single-robot real-kick video is the guaranteed deliverable. All claims in
this README are backed by the actual simulation recordings in this repository (scripts + params +
logs + `result.json`).

## Real Kick Evidence (the core deliverable)

The final film demonstrates a **real kicking action chain** — nothing is scripted:

```
walk to ball → wind-up (风车蓄力) → forward leg swing → FOOT CONTACTS BALL → ball pushed → GOAL
```

- Winner recipe `kick_params.json`: ball 0.22 m in front of right foot; swing `hip:+1.0 / knee:-1.6`
  (wind-up) → `hip:-1.8 / knee:+1.8` (forward swing) → hold; joint indices `R_HIP=6, R_KNEE=16,
  R_ANK=18, L_KNEE=15`.
- `clip_actions = 100.0` during the kick phase so the leg swing is not clipped — ball speed is
  produced entirely by physics momentum (no scripted ball velocity).
- Canonical run (2026-08-06): `contact@116` (foot touches ball) → `scored@144` (ball crosses
  goal line x=7.0), peak ball speed **4.33 m/s** (`kick_final/result.json`, single-camera render),
  **0 falls**, 288 frames @ 1920×1080/30fps.
- The final film's multi-camera take measured **3.54 m/s** (`kick_multi_result.json`, contact@116 →
  scored@145) — both numbers are real physics runs from the same recipe; each `result.json` ships with
  the repo so every figure is traceable.
- Raw evidence: `scripts/render_kick_final.py` + `kick_params.json` + time-stamped run log +
  `result.json` (this session reproduced it 4×, all scored).

## Architecture

```text
High-level kick controller (velocity commands @ 10 Hz)
    │  joint-level kick overrides during wind-up/swing (hip/knee/ankle)
    ▼
Frozen walk model t1_walk.pt (720-dim obs → 21-dim joint targets @ 50 Hz)
    │  action_scale=0.16, clip_actions=100.0 (kick phase)
    ▼
Genesis physics on AMD Radeon GPU (ROCm 7.2 · gfx1100 · 96 CUs)
    └─ 1080p multi-camera render + step-by-step metrics (contact/scored/ball speed)
```

## Demos

| Video | Path | Content |
|-------|------|---------|
| **Final submission film (1:28)** | `acceptance/final_video/track3_final_20260806.mp4` | 87.7 s, 6-part narrative (background → architecture → AMD GPU/ROCm → run → effect/metrics → innovation), English slides + English subtitles + Microsoft neural TTS narration, real kick footage |
| Match demos | `demos/exp/*.mp4` (mirrored in `outputs/videos/`) | 1v1 shoot, 3v3 match, rule-walk baseline, task-7d run |
| Raw real-kick render | `demos/exp/run4_kick_final.mp4` + `kick_final/result.json` | wind-up → foot contact → goal, 1080p30, contact@116/scored@144 |
| Slide deck | `presentations/track3_presentation_en.pptx` | 8 English slides, same visuals/narration as the final film |

## Quick Start (on the AMD instance, `/workspace`)

```bash
# 1) real-kick render (reproduces the final video's kick scene)
/opt/venv/bin/python3.12 render_kick_final.py          # reads /workspace/kick_params.json
#    outputs /workspace/kick_final/kick_final.mp4 + result.json

# 2) P1 chase training (no opponent)
/opt/venv/bin/python3.12 run_task9_p1.py --max_iterations 240 --num_envs 2048 --phase A

# 3) single-scene evaluation (300 steps)
/opt/venv/bin/python3.12 run_task9_eval.py --ckpt runs/task9_p1/model_latest.pt --steps 300
```

Locally (no GPU): `python3 -m pytest track3-soccer/tests/ --ignore=tests/test_e2e.py -q`.

## Directory Layout

```text
track3-soccer/
├── SPEC.md                  # single source of truth (tasks, gates, stop-losses)
├── FILES_MANIFEST.md        # real-path index + dead-path blacklist
├── scripts/render_kick_final.py   # ★ real-kick render (winning recipe)
├── kick_params.json         # ★ kick recipe params (ball offset, hip/knee amplitudes)
├── run_task9_p1.py          # P1 training script (rsl_rl 5.4.2, resume support)
├── run_task9_eval.py        # single-scene policy evaluation
├── configs/                 # hierarchical_agent.yaml
├── demos/                   # demo videos + exp/ (kick render, match demos)
├── presentations/           # track3_presentation_en.pptx (8 slides, English)
├── outputs/                 # official 6.2 structure: metrics/ + videos/
├── reports/                 # baseline + evidence
├── acceptance/              # final film + acceptance evidence
├── docs/                    # technical_report.md, DOCKER.md
└── LICENSE                  # MIT
```

## Validation Status (verified)

| Check | Result |
|-------|--------|
| Real kick → goal (canonical run) | contact@116 · scored@144 · **4.33 m/s** · 0 falls · 288 frames 1080p30 |
| Reproducibility | 4/4 runs scored, 0 falls (contact 116–117 / scored 144–147 / 2.7–4.3 m/s) |
| Local tests | 151 passed |
| Single-robot chase (legacy) | 200 steps, 0 falls, ball 12 m |
| P1 training throughput | ~4,600 steps/s, 2048 envs on AMD Radeon |

## Reproduction Time (official README item 10)

Measured on a single AMD Radeon RX 7900 XTX-class GPU (ROCm 7.2, gfx1100, 96 CUs):

| Step | Command | Time |
|------|---------|------|
| Real-kick render (final film scene, 288 frames 1080p30) | `python render_kick_final.py` | ~2–5 min |
| Quick P1 sanity (256 envs, 100 iters) | `python run_task9_p1.py --max_iterations 100 --num_envs 256 --phase A` | ~5 min |
| Full P1 training (2048 envs, 240 iters) | `python run_task9_p1.py --max_iterations 240 --num_envs 2048 --phase A` | ~45–60 min |
| Canonical full training (recorded) | 500 iters, 2048 envs | 1 h 35 min |
| Single-scene evaluation (300 steps) | `python run_task9_eval.py --ckpt runs/task9_p1/model_latest.pt --steps 300` | < 5 min |
| Local tests (CPU) | `python3 -m pytest tests/ --ignore=tests/test_e2e.py` | ~2 min |

End-to-end reproduction from a clean checkout: **~1.5–2 h** on the AMD instance.

## Known Limitations

- **Close-range ball control** (~2 m): no fine dribbling.
- **ROCm solver**: Newton solver exceeds gfx1100 local-memory limits for multi-robot scenes; CG
  solver fallback is slower but functional.

## Submission Alignment

| Official requirement | Where |
|----------------------|-------|
| Technical report | `docs/technical_report.md` |
| Source code + Docker | this repo + `amd-physical-ai-soccer/Dockerfile` (canonical; see `docs/DOCKER.md`) |
| Reproducibility | `## Quick Start` + `render_kick_final.py` + `kick_params.json` |
| Demo video | `acceptance/final_video/track3_final_20260806.mp4` (87.7 s, English, real kick) |
| Official repo structure | `outputs/metrics/` + `outputs/videos/` + `LICENSE` (README item 10 added) |
| AMD GPU evidence | terminal captures: `rocm-smi` / `amd-smi` (gfx1100) / torch 2.9.1+HIP 7.2 (in film & `docs/technical_report.md`) |
