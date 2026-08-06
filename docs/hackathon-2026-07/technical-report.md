# BotverseX — Technical Report

**Track 3: Physical AI Challenge — Robotics Simulation and Application Design based on AMD Radeon GPUs and ROCm**

**Team / Author**: Ethan Yeang (杨智超) — GitHub: metahubaifei · Site: https://botversex.feispace.me
**Date**: 2026-08-06

---

## 1. Target Application

BotverseX is an **embodied-AI data-loop platform**: a single website that makes the full
「scene → data → model/skill → real-robot run → reuse & distribute」 loop short, cheap,
and the *default entry point* for robot skill development.

Instead of asking robot builders to assemble an environment (Python venvs, serial drivers,
dialout permissions, per-vendor SDKs, per-robot data formats), BotverseX lets a user:

1. **Connect** a robot runtime (SO-101, Reachy Mini, B601-RS, LeKiwi, Unitree G1, AmazingHand)
   from the browser — for SO-101 literally zero-install, through the **Web Serial API**
   (Feetech STS3215 protocol implemented in TypeScript, 1,000,000 baud);
2. **Teleoperate** it live (leader/follower mirroring, WebSocket control);
3. **Record** demonstrations into **LeRobot-format parquet datasets** (one click, 3 seconds
   to first recording);
4. **Train** visuomotor policies (MLP / Vision-MLP / SmolVLA) — locally on the user's own
   **AMD Radeon (ROCm) GPU**, or on cloud GPU nodes;
5. **Deploy** the trained policy back to the real robot and run inference.

The target users are robotics learners and builders who want "connect → record → train →
run" working the same night, instead of a shelf-queen demo they never finish.

## 2. System Architecture & Solution Design

```
User / Developer (Browser · React web app)
        │  REST /api/v1/* (JWT)        │ WebSocket /ws/teleop, /ws/robotstate
        ▼                              ▼
Cloud Business Layer · apps/api :8000        Local Realtime Layer · apps/realtime :8002
  FastAPI: users/auth, dataset metadata,      FastAPI + WebSocket: teleop, robot state,
  training jobs, model registry, skills       recording → LeRobot parquet, SafetyGate
  hub, HF Hub proxy, plans/entitlements       (joint limits), dataset/models storage
        │
        ▼
Runtime Adaptation Layer · runtimes/*
  so101 (Feetech serial + LeRobot) · reachy_mini (official daemon + SDK)
  b601_rs (CAN + Star Arm) · lekiwi · unitree_g1 · amazing_hand
        │
Contract layer · packages/botclaw-spec  (single source of truth for all
  JSON Schemas ↔ TypeScript ↔ Python: Skill · RobotState · Dataset · …)
```

Design principles:

- **Contract first**: `packages/botclaw-spec` is the single source of truth for every
  protocol schema; web (TS), api and realtime (Python) are generated/validated from it.
- **Separation by latency & trust**: training & model metadata can go to the cloud; control
  and recording stay local (low latency, sensitive data can stay on-machine).
- **Runtime adapters, not products**: adding a robot is adding an adapter under `runtimes/`,
  reusing the same website, dataset pipeline, and training stack.
- **Browser-direct zero-install**: for SO-101, the browser talks to the servos directly via
  Web Serial (Feetech STS3215 protocol layer, `apps/web/src/lib/webserial.ts`) — no agent,
  no driver, no install. A Local Agent bridge exists for robots that need one.

## 3. Datasets

- **Recording**: `POST /api/datasets/record` writes **LeRobot-format parquet** files
  (`observation.state`, `action`, `timestamp`, `episode_index`, `frame_index`, `index`)
  plus a `botclaw.json` v0.2 manifest into `datasets/recording_<id>/`.
- **Compatibility**: datasets are interchangeable with the LeRobot ecosystem; the platform
  can load SO-101 datasets from HuggingFace Hub (58,000+ LeRobot datasets, most recorded
  on SO-series arms).
- **Local-first**: recordings land on the user's machine first; metadata is synced to the
  cloud layer; nothing is uploaded without the user's intent.

## 4. AMD Radeon GPU / ROCm Utilization

BotverseX treats the **AMD Radeon (ROCm) stack as a first-class training/inference target**:

- **Local training on AMD hardware (milestone M10)**: the local training environment is
  fully unblocked on an **AMD Strix Halo APU (Radeon 8060S, gfx1151, 64 GB unified memory)**:
  - `torch 2.10.0+rocm7.0` + `torchvision 0.25.0+rocm7.0` + `pytorch-triton-rocm 3.5.1`
  - `apps/realtime/rocm_env.sh` — one-command environment bring-up (ROCm env vars + venv).
  - Training scripts (MLP / Vision-MLP / SmolVLA) run directly on the GPU with CUDA-equivalent
    code paths (`torch.cuda`), thanks to ROCm's CUDA-compatibility layer.
- **GPU capability probe (M48)**: the training page probes the local compute device in an
  **isolated subprocess** (crash-safe — touching `torch.cuda` in-process on some ROCm
  stacks can SIGSEGV the interpreter) and reports accelerator type
  (ROCm / CUDA / CPU), device name, and a kernel-launch sanity test, so users pick the
  right node instead of silently training on CPU.
- **Cloud GPU nodes**: training jobs can target remote ROCm/CUDA nodes through a
  remote-compute node registry; the same checkpoint/model artifacts are reused for
  local inference on the AMD machine.
- **Why ROCm matters here**: the platform's target user is an individual builder —
  exactly the segment AMD's consumer APUs (Strix Halo) serve: unified-memory, GPU training
  and real-robot control on one affordable machine, no separate workstation needed.

## 5. Innovations & Key Technical Contributions

1. **Zero-install robot control via Web Serial** — the Feetech STS3215 protocol
   (1 Mbps half-duplex, checksummed packets, sync read/write, broadcast-ID protection)
   implemented in TypeScript in the browser: scan servos, read/write positions, set torque,
   emergency-stop — 34 protocol-level assertions in the smoke test suite.
2. **One website, many runtimes** — runtime adapters (SO-101, Reachy Mini, B601-RS, LeKiwi,
   Unitree G1, AmazingHand) share one record/train/deploy pipeline instead of one product
   per robot.
3. **3-second first-record ceremony** — first-time users go from a blank page to a saved
   LeRobot-format recording with guided steps and a 3D digital twin following the real
   joints (URDF joint names mapped to servo IDs).
4. **Contract-first monorepo** — one schema source (`botclaw-spec`) validated across
   TypeScript and Python, keeping 3 services + adapters consistent.
5. **Browser 3D twin + diagnostics** — serial diagnostics (port enumeration, baud probing,
   ID scan, log export) and a URDF-based 3D twin make debugging a robot over the web
   feel like debugging a web app.

## 6. Final Deliverables & Output Forms

- **Web application** live at https://botversex.feispace.me (web / api / realtime services).
- **Full source code** in this repository (monorepo: `apps/web`, `apps/api`, `apps/realtime`,
  `packages/botclaw-spec`, `infra/docker`).
- **Docker deployment**: `infra/docker/docker-compose.prod.yml` builds and runs
  `web` (nginx + vite build), `api` (FastAPI), `realtime` (FastAPI + WebSocket + torch)
  containers — a production-grade stack reproducible with one command (see
  `docs/hackathon-2026-07/reproducibility.md`).
- **Demo video & slides**: supplementary materials accompany this report.
- **Documentation**: architecture, how-to-use, milestone journal (30+ milestones,
  `progress/`), community resource guides for every supported runtime.

## 7. Additional Strengths

- **Real-hardware pedigree**: every layer has been exercised against real robots
  (SO-101 arms, Reachy Mini) with the platform's own recording/training pipeline; the
  WebSerial protocol layer is verified by a 34-assertion smoke suite and a production
  bug-fix history (pending-read deadlock, sync-write packet layout, GOAL_TIME clobber).
- **Honest by design**: where a runtime's community has no public channel (e.g. Unitree G1),
  the platform says so instead of fabricating links; hardware capability probes report
  truth (CPU-only servers return "CPU only").
- **Built on open ecosystems**: LeRobot dataset format, HuggingFace Hub, URDF/3D assets —
  no lock-in; datasets and models leave and enter the platform freely.

## 8. Team

- **Ethan Yeang (杨智超)** — founder & solo builder: full-stack (React/TypeScript, FastAPI,
  robotics adapters, Docker deployment), platform strategy, and on-hardware verification.
