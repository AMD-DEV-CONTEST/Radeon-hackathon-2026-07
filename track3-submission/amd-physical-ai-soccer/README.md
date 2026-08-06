# AMD Physical AI — Humanoid Soccer (Booster T1)

Track 3 (Physical AI) submission for the **2026 AMD AI DevMaster Hackathon**.
A **Booster T1 humanoid robot** (23-DOF) trained and simulated on **AMD Radeon GPU + ROCm**
via Genesis: the robot walks to the ball, swings its leg, **physically contacts the ball with
its foot**, and pushes it into the goal. No NVIDIA hardware involved.

## Why this project

Booster's official RL training stack requires NVIDIA Isaac Gym / Isaac Lab. We demonstrate
the **first-known AMD ROCm alternative** for humanoid robot learning — same T1 robot,
same PPO algorithm, different GPU ecosystem.

## Final deliverable (2026-08-06)

A **real kicking action chain** produced purely by physics — no scripted ball velocity:

| Item | Value |
|---|---|
| Kicking chain | wind-up → forward leg swing → foot contacts ball → ball pushed → GOAL |
| Canonical run | contact @ step 116 → scored @ step 144, peak ball speed **4.33 m/s**, **0 falls** |
| Reproducibility | 4/4 independent runs scored (contact 116–117 / scored 144–147 / ball 2.7–4.3 m/s) |
| Winner recipe | `kick_params.json`: ball 0.22 m ahead of right foot; joint overrides R_HIP=6, R_KNEE=16, R_ANK=18, L_KNEE=15 |
| Physics honesty | `clip_actions=100.0` during the kick phase — ball speed comes purely from leg momentum |
| Final film | `acceptance/final_video/track3_final_20260806.mp4` (87.7 s, 1080p30, multi-part narrative, English narration) |
| Slide deck | `presentations/track3_presentation_en.pptx` (8 slides, English, same visuals as the final film) |

## Training & GPU evidence

| Metric | Value |
|---|---|
| GPU | AMD Radeon Graphics (gfx1100, RDNA3, ROCm 7.2) |
| PyTorch | 2.9.1+gitff65f5b (HIP backend) |
| Genesis | 1.3.1 (gs.gpu backend) |
| Training iterations | 300 (chase_v7) |
| Total training steps | 7,372,800 |
| Training throughput | 3,056 steps/sec |
| GPU utilization | 93-100% (per-10s telemetry, 244K samples) |
| Multi-robot stability | 0 abnormal exits / 18 clean matches (robustness evaluation) |
| Multi-robot recovery | 83–93% recovery with t1_walk.pt |
| Robot | Booster T1 23-DOF (official booster_assets) |

## Judging-criteria mapping (Track 3, 100 pts)

| Criterion | Pts | How this project earns it |
|---|---|---|
| Robot capability | 30 | Real kick → goal on physics; walk policy stable; reproducible 4/4 |
| AMD Radeon GPU + ROCm | 20 | Full simulation + inference + rendering on ROCm; GPU util 93-100% |
| Innovation & originality | 20 | First AMD ROCm T1 humanoid training; joint-level real-kick recipe |
| Real-world application value | 20 | Sim-to-real path; disturbance framework; full logging + reproducibility |
| Upstream open-source contribution | 10 | Genesis soccer env wrapper, kick controller, analyze scripts |

## Docker image (reproducibility)

The submission image (canonical Dockerfile in this directory) runs JupyterLab on
`0.0.0.0:8888` as a **non-root** user. A token is **always required** — set
`JUPYTER_TOKEN` when starting the container. Build context is this directory:

```bash
docker build -t track3-soccer:amd -f Dockerfile .
docker run -it --rm \
  --device=/dev/kfd --device=/dev/dri --group-add video \
  --security-opt seccomp=unconfined --cap-add=SYS_PTRACE \
  -p 8888:8888 -e JUPYTER_TOKEN='<set-a-strong-token>' \
  -v "$PWD":/workspace track3-soccer:amd
```

If `JUPYTER_TOKEN` is not set, a strong random token is generated on start and printed in the container log (look for `?token=...`). Do not expose port 8888 without a token.

> `--gpus all` is NVIDIA-only; on AMD ROCm hosts use the `--device=/dev/kfd --device=/dev/dri --group-add video` flags above. Full build / run / SPEC §3 reproduction commands (including the bind mount that exposes `render_kick_final.py`, `run_task9_p1.py`, `run_task9_eval.py`, and `kick_params.json` at `/workspace`) are in the project's `docs/DOCKER.md`. Inside the container use the base image's `python3` (py3.10); `/opt/venv/bin/python3.12` below is the cloud instance path only.

## Quick start (on AMD Radeon Linux cloud)

```bash
# 1. Verify environment
rocm-smi | head -5
/opt/venv/bin/python3 -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.version.hip)"
# Expected: 2.9.1+gitff65f5b True 7.2.53211-e1a6bc5663

# 2. Reproduce the final real-kick render (reads /workspace/kick_params.json)
/opt/venv/bin/python3.12 render_kick_final.py
#    outputs /workspace/kick_final/kick_final.mp4 + result.json
#    expected: contact@116 -> scored@144, ball speed ~4.3 m/s, 0 falls

# 3. P1 chase training (no opponent)
/opt/venv/bin/python3.12 run_task9_p1.py --max_iterations 240 --num_envs 2048 --phase A

# 4. Single-scene policy evaluation (300 steps)
/opt/venv/bin/python3.12 run_task9_eval.py --ckpt runs/task9_p1/model_latest.pt --steps 300
```

## Key findings

1. **Real kick → goal:** contact@116, scored@144, 4.33 m/s ball speed, 0 falls (4/4 reproducible)
2. **Platform stability:** 0 abnormal exits in 18 clean multi-robot matches
3. **Recovery:** 83–93% recovery rate with t1_walk.pt (vs 52% without)
4. **Disturbance robustness:** 87.8% recovery under 5N random push forces
5. **Honest positioning:** real physics kick as the core deliverable; multi-robot robustness as supporting evidence
