# Pull Request — Track 3 Submission: Humanoid Robot Soccer on AMD Radeon (ROCm)

> **AMD AI DevMaster Hackathon 2026 · Track 3: Physical AI**
> This PR is the official competition submission. It contains the full source code, reproducibility
> pipeline, Docker packaging, technical report, demo video and slide deck.
> All public documents are **anonymous** — no personal names, usernames, instance addresses or
> credentials appear anywhere in this repository.

---

## What this submission is

A hierarchical robot-soccer system on **AMD Radeon GPU + ROCm** (no NVIDIA hardware):
a Booster T1 humanoid walks to the ball, swings its leg, **physically contacts the ball with its
foot**, and pushes it into the goal — entirely inside the Genesis physics engine, with all motion
produced by physics momentum (no scripted ball velocity, no falls).

**Core result (canonical run, 2026-08-06):**

| Metric | Value |
|---|---|
| Kicking chain | walk → wind-up → leg swing → **foot contacts ball** → goal |
| Contact / scored step | `contact@116` → `scored@144` |
| Peak ball speed | **4.33 m/s** (single-camera render; film multi-camera take 3.54 m/s — both `result.json` files are in-repo) |
| Falls | **0** |
| Reproducibility | 4/4 independent runs scored, 0 falls |
| Frames / resolution | 288 frames, 1920×1080 @ 30 fps |

---

## 🎬 Video (final film)

**In-repo file:** `acceptance/final_video/track3_final_20260806.mp4` (87.7 s, 1080p30, H.264)
- 6-part narrative: background → architecture → AMD GPU/ROCm → run → effect/metrics → innovation
- **English** slides + **English subtitles** + **Microsoft neural TTS narration** (en-US)
- Real kick footage only — no scripted ball, no falls

> **Submission video (hosted in this repo — this IS the official submission video):** `acceptance/final_video/track3_final_20260806.mp4`
> ▶ Direct play: https://github.com/coco12300/Radeon-hackathon-2026-07/raw/main/track3-submission/acceptance/final_video/track3_final_20260806.mp4

Extra demo videos (also mirrored in `outputs/videos/`):

| Video | Path |
|---|---|
| Real-kick render (raw, multi-camera) | `demos/exp/run4_kick_final.mp4` |
| 1v1 shoot match | `demos/exp/match_1v1_shoot_20260805.mp4` |
| 3v3 final match | `demos/exp/match_3v3_final.mp4` |
| Rule-walk baseline | `demos/exp/match_rule_walk.mp4` |
| Task-7d run | `demos/exp/match_task7d.mp4` |

Slide deck: `presentations/track3_presentation_en.pptx` (8 English slides, same visuals as the film).

---

## 🐳 Docker

**Canonical image definition:** `amd-physical-ai-soccer/Dockerfile`
(`rocm/pytorch:rocm6.2_ubuntu22.04_py3.10_pytorch_release_2.3.0`, non-root, forced `JUPYTER_TOKEN`)

- Build: `docker build -t track3-soccer:amd -f amd-physical-ai-soccer/Dockerfile amd-physical-ai-soccer`
- Run (AMD ROCm host): `--device=/dev/kfd --device=/dev/dri --group-add video` + `-v "$PWD":/workspace`
- Reproduce all three SPEC §3 entries inside the container
- Full commands: `docs/DOCKER.md`; lock file: `amd-physical-ai-soccer/requirements-lock.txt`

> **Container image:** not pushed to a public registry; the `amd-physical-ai-soccer/Dockerfile` is
> fully self-contained and builds on any ROCm 6.2+ Linux host (exact `docker build` / `docker run`
> commands in `docs/DOCKER.md`). Reviewers reproduce the environment from source.

---

## Deliverables checklist

| Official requirement | Where |
|---|---|
| Technical report | `docs/technical_report.md` |
| README with 10 required items | `README.md` (project intro, architecture, environment, install, data/model, run, evaluate, expected output, known issues, **reproduction time**) |
| Source code | repo root + `src/`, `scripts/`, `tests/` |
| Docker (priority item) | `amd-physical-ai-soccer/Dockerfile` + `docs/DOCKER.md` |
| Demo video (3–5 min) | `acceptance/final_video/track3_final_20260806.mp4` (87.7 s English) |
| AMD GPU/ROCm evidence | `rocm-smi`/`amd-smi`/`torch` HIP captures in `docs/technical_report.md` + film section 3 |
| Metrics outputs | `outputs/metrics/` (kick/match results, model hashes, GPU telemetry) |
| License | `LICENSE` (MIT) |

## Reproducibility (from clean checkout)

```bash
# on the AMD Radeon Linux instance
python render_kick_final.py                       # ~2–5 min  → contact@116 → scored@144
python run_task9_p1.py --max_iterations 240 --num_envs 2048 --phase A   # ~45–60 min
python run_task9_eval.py --ckpt runs/task9_p1/model_latest.pt --steps 300   # < 5 min
```

End-to-end: **~1.5–2 h** on a single AMD Radeon GPU (RX 7900 XTX-class, gfx1100, 96 CUs).

## Known limitations (stated honestly)

- No fine dribbling at close range (~2 m).
- ROCm Newton solver exceeds gfx1100 local-memory limits for multi-robot scenes; CG-solver
  fallback is functional but slower.

---

*Team: Track 3 (anonymous). No credentials, instance addresses or personal identifiers are included.*
