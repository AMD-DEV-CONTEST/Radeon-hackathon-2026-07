# Track 3: AMD ROCm Humanoid Soccer — Presentation Summary

## Slide 1: Title
**AMD ROCm-Driven Humanoid Soccer: Failure Recovery & OOD Evaluation Platform**

Track 3 — Physical AI | AMD AI DevMaster Hackathon 2026  
Team: Track 3

---

## Slide 2: Problem
- Booster Robotics' official RL training requires **NVIDIA Isaac Gym**
- No AMD ROCm alternative existed for humanoid robot training
- Need: Demonstrate T1 humanoid soccer on AMD Radeon GPU

---

## Slide 3: Solution
**Hierarchical RL Policy on AMD ROCm**

```
High-Level (chase_v8 ONNX): 19-dim → 3-dim velocity command
    ↓
Low-Level (t1_walk.pt): 720-dim → 21 joint targets
    ↓
Genesis Physics Engine (AMD Radeon GPU, 50Hz)
```

- PPO training: 7.37M steps, 300 iterations, 3056 steps/sec
- GPU utilization: 93-100% during training
- Framework: Genesis 1.3.1 + PyTorch 2.9.1 + ROCm 7.2

---

## Slide 4: AMD GPU Evidence
- **GPU:** AMD Radeon Graphics (gfx1100, RDNA3)
- **ROCm:** 7.2.53211, Driver 6.16.13
- **PyTorch:** 2.9.1+gitff65f5b (HIP backend)
- **Training:** 93-100% GPU utilization, 3,056 steps/sec
- **Evidence:** gpu_samples.csv (244K), rocm-smi output, TensorBoard logs

---

## Slide 5: Match Results (18 Clean Matches)

| Group | Matches | Duration | Goals | Recovery Rate | Abnormal |
|-------|---------|----------|-------|---------------|----------|
| RL+kick (25s) | 7 | 25s | 0-0 | 83.0% | 0 |
| RL+kick (60s) | 7 | 60s | 0-1 | 93.0% | 0 |
| Rule vs Rule | 4 | 25s | 0-0 | 85.0% | 0 |

**Key: 0 abnormal exits in 18 matches = 100% stability**

---

## Slide 6: Failure Recovery

| Scenario | Recovery Rate |
|----------|---------------|
| Rule vs Rule (single-process, no t1_walk) | 51.9% |
| Rule vs Rule (6-worker, with t1_walk) | 85.0% |
| RL vs Rule (6-worker, 25s) | 83.0% |
| RL vs Rule (6-worker, 60s) | 93.0% |
| RL + Disturbance (push 5N) | 87.8% |

**t1_walk.pt improves recovery from 52% → 85% (+33pp)**

---

## Slide 7: Sim2Sim Preparation
- **Booster Studio 1.9.4** installed on AMD GPU instance
- **Agent:** RLChaseAgent with chase_v8_policy.onnx deployed
- **Architecture:** ONNX inference for chaser + rule-based for other roles
- **VNC/noVNC** running for GUI access
- Agent code at `src/booster_agent/src/main.py`
- Sim2Sim match not executed — requires manual GUI operation

---

## Slide 8: Innovation
1. **First AMD ROCm T1 humanoid RL training** (Isaac Gym alternative)
2. **Hierarchical policy** (walk + chase) trained end-to-end on ROCm
3. **Failure recovery platform** — 87% recovery, 0 crashes in 18 matches
4. **Disturbance framework** — random push + ball randomization
5. **Open-source** Genesis soccer environment with reward functions

---

## Slide 9: Honest Limitations
- 0 RL goals scored (ball max X = 5.9m, goal at 7.0m)
- 25s matches too short for ball progression
- ONNX Runtime uses CPU only (no ROCm EP)
- Sim2Sim match requires manual GUI operation
- Recovery rate comparable between RL and Rule (83% vs 85%)

---

## Slide 10: Deliverables
- ✅ Technical Report (docs/TECHNICAL_REPORT.md)
- ✅ Source Code (src/ + scripts/)
- ✅ Trained Models (6 files with SHA256)
- ✅ Demo Video (hierarchical_chase_hl.mp4)
- ✅ Match Results (18 clean matches, CSV + JSON)
- ✅ Recovery Report (recovery_ood_report.md)
- ✅ GPU Evidence (rocm-smi, gpu_samples.csv)
- ✅ Presentation (this file)
