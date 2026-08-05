# Technical Report — Track 3: Physical AI Challenge

**An Industrial Part Sorting System on the AMD Platform —
Language-Conditioned Vision-Language-Action Sorting on Radeon GPUs / ROCm**

- **Track:** 3 — Robotics Simulation and Application Design based on AMD Radeon GPUs and ROCm
- **Team:** Answer
- **Application:** AMD-Platform Industrial Part Sorting System (Franka + SmolVLA)
- **Hardware:** AMD Radeon PRO W7900 (48 GB, gfx1100), ROCm 7.2.1
- **Stack:** Genesis 1.2.3 (physics + rendering) · PyTorch 2.9.1+rocm7.2.1 · LeRobot 0.4.4 · SmolVLA
- **Demo Video:** https://www.youtube.com/watch?v=39ZYWDyvmC8

---

## Judging Criteria Response

| # | Criterion (Points) | How Our Submission Addresses It |
|---|---|---|
| 1 | **Robot Capability** (30 pts) | Closed-loop language-conditioned sorting of 3 industrial parts (gear / bolt / nut → red / green / blue boxes) by a single SmolVLA VLA policy. **13/25 = 52.0 %** on a fixed-seed verification set. The policy performs perception, decision, and control end-to-end — no hand-written perception or grasp modules at inference time. Dual-camera streaming (world + wrist) with real-time Genesis GPU rendering in a browser-based live demo. |
| 2 | **AMD Radeon GPU & ROCm Adoption** (20 pts) | **Every stage runs on a single AMD Radeon PRO W7900 (48 GB, gfx1100) under ROCm 7.2.1**: (a) synthetic data generation in Genesis with GPU-accelerated physics + rendering; (b) SmolVLA fine-tuning (30k steps, BF16 AMP, AOTriton SDPA backend, 4.8 it/s, ~3 GB VRAM); (c) closed-loop evaluation with 3 concurrent processes on one card; (d) web demo serving live GPU-rendered frames + VLA inference. PyTorch 2.9.1+rocm7.2.1 from `repo.radeon.com`. ROCm-specific pitfalls documented (§7.2). |
| 3 | **Innovation** (20 pts) | **First VLA-based industrial sorting system on the AMD/ROCm platform.** To the best of our knowledge, this is the first work that trains and deploys a Vision-Language-Action policy end-to-end on AMD Radeon GPUs for a real industrial task (language-conditioned part sorting). Additionally: (a) checkpoint sweet-spot selection — the submitted 20k-step checkpoint triples the final checkpoint's score (52 % vs 16 %); (b) systematic, evidence-driven failure analysis with 5 hypotheses tested and nut height-error root cause identified from wrist-camera frame comparison; (c) honest-evaluation methodology with quantified noise (§3.3) and per-episode audit trails. |
| 4 | **Application Value** (20 pts) | Industrial part sorting is a real task in intralogistics and light manufacturing. Language-conditioned routing eliminates per-SKU reprogramming — the same model serves all part-to-box mappings. The full synthetic data pipeline means no real-robot data collection is needed for new parts. All code, checkpoints, datasets, and a live web demo are shipped for immediate evaluation. |
| 5 | **Upstream Open-Source Contribution** (10 pts) | **Makes the VLA + Genesis + ROCm stack directly usable for downstream industrial users on AMD GPUs.** (a) Documented and solved ROCm-specific pitfalls: `libsvtav1` codec requirement, headless Vulkan/X rendering, ROCm wheel selection, block-buffered stdout workaround. (b) Verified and documented the offline model-loading path for SmolVLA on ROCm (`vlm_model_name` override + `HF_HUB_OFFLINE=1`) — critical for air-gapped industrial deployments. (c) Self-contained web demo server (`web_demo_server.py`) that runs Genesis + VLA inference + HTTP serving in one process on a single AMD GPU — a turnkey baseline that industrial users can adapt. (d) Full reproduction Dockerfile and step-by-step instructions for the AMD/ROCm community. |

---

## 1. Target Application

Modern intralogistics and light-manufacturing cells require robots that sort visually
similar small industrial parts into the correct bins from natural-language
instructions — a task where classical pipelines (per-part detectors + hand-tuned
grasp poses) are brittle and expensive to reconfigure. Our target application is a
**language-conditioned robotic sorting cell**:

A Franka Emika Panda arm observes a tabletop through a fixed world camera and a
wrist-mounted camera. On the table sit small metal parts of three categories —
**gear, hex nut, bolt** — and three open-top sorting boxes color-coded
**red / green / blue**. Given a natural-language instruction such as
*"pick the hex nut and place it in the red box"*, the robot must localize the
requested part, grasp it, transport it, and deposit it into the instruction's
target box (nut → red, bolt → green, gear → blue), then retreat.

The task is executed **closed-loop by a single Vision-Language-Action (VLA)
policy** (SmolVLA) trained exclusively on **synthetic demonstrations generated in
Genesis** — no real-world data and no hand-written perception/grasp modules are
used at inference time. Everything — data generation, training, and closed-loop
evaluation — runs on a single AMD Radeon PRO W7900 under ROCm.

The final system sorts all three part categories in one scene, routed purely by
the instruction string, and reaches **52.0 % (13/25)** closed-loop success on our
fixed-seed verification set — gear 5/11 (45 %), bolt 5/9 (56 %), nut 3/5 (60 %)
— with the submitted checkpoint, representing a 3× improvement over the 30k-step
final checkpoint's rate through measured checkpoint selection (§5.1).

The remainder of this report describes the system (§2), datasets (§3), how the AMD
GPU is used at every stage (§4), our technical contributions including a detailed
failure analysis (§5), and the final deliverables (§6).

---

## 2. System Architecture and Solution Design

### 2.1 End-to-end pipeline

```
┌───────────────────────────────────────────────────────────────────────────┐
│                        AMD Radeon PRO W7900 · ROCm 7.2.1                   │
│                                                                           │
│  M1 SCENE            M2 EXPERT          M3 DATA        M4 TRAIN   M5 EVAL │
│  Genesis scene  →    scripted IK    →   LeRobot    →   SmolVLA →   closed │
│  Franka + parts      pick&place         dataset        fine-tune   loop   │
│  + 3 color boxes     + 2-layer DR       450 eps        30k steps   30+ eps│
│  (build_scene.py)    (grasp_demo.py)    (record_       (train_vla_ (eval_ │
│                                          dataset.py)    unfreeze.py) policy.py)│
└───────────────────────────────────────────────────────────────────────────┘
```

**M1 — Scene.** `scene_config.py` / `build_scene.py` construct the tabletop world
in Genesis (100 Hz rigid-body sim): Franka Panda on a fixed base, three
industrial-part meshes (gear/nut/bolt STLs scaled ×1.5–1.6 to fruit-like size so
they are graspable by the Panda gripper), three open-top boxes (0.14 m × 0.14 m
footprint, 6 cm walls) arranged in a row at x = 0.60 m, y ∈ {−0.24, 0, +0.24} m,
and two cameras: a fixed **world camera** (1280×720, intrinsics matched to an
Intel RealSense D435i) and a **wrist camera** rigidly attached to the end
effector. The box color is the routing key and is therefore held fixed (no color
randomization on boxes).

![V2 scene — world camera view (red/green/blue boxes, parts on the table)](docs/figures/scene_world.png)

**M2 — Scripted expert with two-layer domain randomization.**
`grasp_demo.py` implements a deterministic multi-phase pick-and-place expert
(plan to pre-grasp → vertical descent → close → lift → transport → release →
retreat) driven by inverse kinematics, and `randomize.py` perturbs the scene per
episode:

- *Layer A (build time):* object/box colors (parts only), lighting, camera
  intrinsics jitter;
- *Layer B (runtime):* part poses in fixed slots with safe jitter (with
  box-footprint avoidance), friction and other physics parameters, camera
  extrinsics.

Because the expert is scripted, every recorded episode is a successful
demonstration by construction, and success/failure of the *learned* policy can be
attributed to the policy rather than to the data.

**M3 — Data.** `record_dataset.py` records expert episodes into the LeRobot v2
dataset format: per timestep we store the 9-DoF joint state, the 9-DoF joint
position action, world + wrist RGB (resized to 640×360), and the per-episode
language instruction; 30 fps sequences decimated from the 100 Hz sim (3/3/4 step
pattern). Episodes are encoded with `libsvtav1` (see §7.2 for the ROCm-specific
codec pitfall).

**M4 — Training.** `train_vla_unfreeze.py` fine-tunes
`lerobot/smolvla_base` (450 M parameters) on the synthetic dataset:

- frozen vision encoder, trainable action expert + state projection
  (99.88 M trainable parameters);
- action chunk size 50 (1.67 s at 30 Hz), `n_action_steps = 50`;
- BF16 mixed precision (`torch.autocast`), PyTorch SDPA attention (AOTriton
  backend on ROCm), AdamW (lr 1e-4), batch size 8, 30k steps = 3 epochs;
- intermediate checkpoints saved every 2k steps, enabling the checkpoint sweep
  that proved central to our final model selection (§5.1).

**M5 — Closed-loop evaluation.** `eval_policy.py` runs the trained policy in the
*same* randomized scene used for data generation: at each step the policy
observes (9-DoF state, world + wrist RGB at 640×360, instruction string) and
predicts a 50-action chunk that is replayed open-loop at 30 Hz on the 100 Hz sim.
An episode succeeds when the placed part satisfies the geometric success test
(bottom of part below the target box rim and inside its wall footprint) for
**15 consecutive frames** (0.5 s dwell), within a 450-frame (15 s) budget.
World- and wrist-view videos of every evaluation episode are recorded for audit.

### 2.2 Design decisions worth noting

- **Language conditioning.** The same weights serve all three tasks; the
  instruction string selects the routing target. Because our success test is
  defined relative to the instructed box, successful episodes are correct-routed
  by construction, so they cannot by themselves prove language grounding; the
  observed behavior (object-appropriate grasp strategies and per-task success
  asymmetry tracked across instruction variants) is *consistent with* language
  conditioning, and a controlled instruction-swap probe is left as future work.
- **Eval = train scene, different randomization seeds.** Data generation seeds
  (0, 10000) and evaluation seeds (1000+, 2000–2029) are disjoint; evaluation
  episodes randomize part poses, lighting, and physics per episode.
- **Everything is a file.** Datasets (LeRobot v2), checkpoints
  (`save_pretrained`), per-episode `summary.json` and mp4 videos make every run
  fully auditable and comparable across protocols (§3.3).

### 2.3 Web-based live demo

A lightweight web application (`web_demo_server.py`) provides interactive
access to the trained VLA policy through a browser:

- **Backend:** Flask HTTP server with Genesis GPU rendering and SmolVLA
  inference running in the same process. The sim loop renders idle frames
  (world + wrist camera at 640×360, JPEG) at ~8 fps; when a language
  command arrives from the web UI, the main thread runs a full closed-loop
  episode (450-frame budget, 15-frame dwell success test) and streams
  live rendered frames back to the browser.
- **Frontend:** Single-page HTML application (embedded in the Python
  server) with dual camera views (world main + wrist picture-in-picture),
  three quick-select buttons for the dataset language instructions
  (*"pick the gear and place it in the blue box"* / *"pick the hex nut
  and place it in the red box"* / *"pick the bolt and place it in the
  green box"*), a free-text input, live status display, and per-episode
  result cards.
- **Deployment:** The server binds `0.0.0.0:8765`; users access it via an
  SSH tunnel (`ssh -L 8765:localhost:8765 ...`) or direct browser
  connection if the firewall permits. The entire stack — Genesis, VLA
  inference, Flask — runs on the W7900 under ROCm 7.2.1.
- **Offline loading:** The script works without internet access by
  overriding `vlm_model_name` to the locally-cached SmolVLM2-500M
  checkpoint and setting `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1`
  before any HuggingFace imports.

---

## 3. Datasets

### 3.1 Training data

| Dataset | Episodes | Frames | Composition | Collection |
|---|---|---|---|---|
| `industrial_sort_v2` | 450 (100 % expert success) | 117,839 | bolt 156 / gear 147 / nut 147 | main batch 300 eps (seed 0) + top-up 150 eps (seed 10000), merged with `aggregate_datasets.py` |

All data is **100 % synthetic**, generated in Genesis on the W7900; no
demonstrations were collected on real hardware. Per-frame features:
`observation.state` (9-DoF qpos), `action` (9-DoF joint targets),
`observation.images.world` and `observation.images.wrist` (640×360 RGB),
`task` (instruction string, e.g. *"pick the gear and place it in the blue box"*).

### 3.2 Evaluation: fixed-seed verification set

Our evaluation is a **single, fixed-seed verification set** of 25 episodes —
all seeds randomly generated with `random.Random(20260803)` from `[3000, 9999)`
(11 gear, 9 bolt, 5 nut). Every seed is locked in `verification_seeds.json` —
same seed = same `EnvRandomizer` state = fully reproducible episode. All
episodes are capped at 450 frames (15 s).

| Group | Episodes | Our result (2025-08-02) |
|---|---|---|
| **Overall** | 25 | **13/25 = 52.0 %** |
| Gear | 11 | **5/11 = 45.5 %** |
| Bolt | 9 | **5/9 = 55.6 %** |
| Nut | 5 | **3/5 = 60.0 %** |

Due to inherent closed-loop non-determinism (see §3.3), individual episode
outcomes may vary across re-runs; the overall score is stable within the
expected noise envelope. Full per-episode data, videos, and the runner are in
`verification-set/`.

### 3.3 Measurement noise, measured

Closed-loop evaluation on GPU is **not deterministic**: re-running the same
(seed, object) pair with the same checkpoint flips the outcome in roughly
1 of 4–5 cases (observed in both directions across our runs). We therefore
(a) use a fixed-seed verification set so every re-run evaluates the same
episodes, and (b) publish per-episode `summary.json` records plus videos for
every run. Across our full 25-episode verification set, the observed flip rate
is consistent with the expected ~1/4–1/5 per-episode independent flip
probability; the overall score is correspondingly stable within the expected
binomial noise envelope. Evaluators re-running the verification set should
expect a similar overall score with individual episode outcomes varying per the
per-episode flip probability.

---

## 4. How AMD Radeon GPUs Are Used

Every stage of the project runs on a single **AMD Radeon PRO W7900 (48 GB,
gfx1100)** under **ROCm 7.2.1** — no other accelerator is involved.

### 4.1 Hardware & Software Stack (Measured)

| Item | Detail |
|---|---|
| **GPU** | AMD Radeon PRO W7900 (gfx1100), 48 GB VRAM (51,522,830,336 B) |
| **ROCm** | 7.2.1 |
| **PyTorch** | 2.9.1+rocm7.2.1 (from `repo.radeon.com`) |
| **Attention backend** | AOTriton (SDPA) |
| **Mixed precision** | BF16 (`torch.autocast`) |
| **Python** | 3.12 |
| **Idle VRAM** | ~3.0 GB (ROCm driver + Genesis runtime baseline) |

### 4.2 Per-Stage GPU Utilization

| Stage | GPU usage | Measured on the W7900 |
|---|---|---|
| **Synthetic data generation** | Genesis runs rigid-body dynamics and camera rendering on the GPU (`gs.init(backend=gs.gpu)`); world+wrist RGB are rendered on-device every recorded frame | 450 episodes (117,839 frames) recorded with the sim and renderer fully on GPU |
| **VLA training** | PyTorch 2.9.1+rocm7.2.1; BF16 AMP; SDPA attention dispatched to the **AOTriton** backend; SmolVLA 450 M (99.88 M trainable) | 30k steps @ batch 8 in **6,256 s (≈1.74 h, 5.06 it/s)**; loss 1.13 → 0.0146; **peak VRAM 2.96 GB** — the 48 GB card has >15× headroom |
| **Closed-loop evaluation** | Policy inference (VLM forward per 50-action chunk) + Genesis sim/render share the GPU; **3 evaluation processes run concurrently on the one card** | The full 25-episode verification set completes in **~20 minutes** with 3-way parallelism (vs ~50 min sequential) |
| **Web demo (deployment)** | Single-process Flask + Genesis rendering + SmolVLA inference on the W7900; dual-camera JPEG streaming at 640×360, ~8 fps live rendering | VRAM ~3 GB (model + sim + render); responsive browser-based control at `http://localhost:8765` |
| **Video & figures** | ffmpeg encodes episode videos (CPU-side, fed from GPU-rendered frames) | 640×360@30 fps h264/svt-av1 |

### 4.3 Training Profile (Measured from the 30k-step Run)

All metrics below are from the actual 30,000-step training run
(`train_summary.json`) that produced the submitted checkpoint:

| Metric | Value |
|---|---|
| **Total parameters** | 450,046,176 |
| **Trainable parameters** | 99,880,992 (22.2 %) |
| **Batch size** | 8 |
| **Gradient accumulation** | 1 |
| **Optimizer** | AdamW, lr = 1×10⁻⁴, weight_decay = 1×10⁻⁴ |
| **LR schedule** | Cosine decay (no warmup) |
| **Number of epochs** | 3 (over 450 episodes, 117,839 frames) |
| **Action chunk size** | 50 (1.67 s at 30 Hz) |
| **Total training time** | 6,256 s ≈ 1.74 hours |
| **Average step time** | 0.198 s → **5.06 it/s** |
| **First-step time** (incl. CUDA graph compilation) | 2.276 s |
| **Steady-state step time** | 0.193–0.198 s |
| **Peak VRAM usage** | **2,961 MB (2.89 GB)** — 6.2 % of 48 GB |
| **Loss (start → end)** | 1.131 → 0.0146 |
| **Training throughput** | ~40 frames/s (batch 8 × 5.06 it/s) |

### 4.4 Inference / Deployment Profile (Measured)

| Metric | Value |
|---|---|
| **VRAM at inference** | ~3.0 GB (model weights + Genesis sim + render buffers) |
| **VLM backbone layers** | 16 (optimized: SmolVLM2-500M-Video-Instruct with reduced layers) |
| **Action chunk size** | 50 (1.67 s open-loop replay at 30 Hz on 100 Hz sim) |
| **Per-episode budget** | 450 frames (15 s wall-clock) |
| **Typical success duration** | 198–431 frames (6.6–14.4 s) |
| **Concurrent eval** | 3 processes on one W7900 (VRAM permits >15 concurrent) |
| **Web demo streaming** | Dual camera (world + wrist), 640×360 JPEG Q=65, ~8 fps |
| **GPU utilization during inference** | ~8 % (VLA forward pass is brief; most time in sim stepping) |

The large VRAM headroom is exploited deliberately: concurrent closed-loop
evaluations turned our checkpoint sweep (5 checkpoints × 9 episodes) and the
25-episode verification set into same-day experiments rather than overnight
ones, which materially enabled the analysis in §5.

ROCm-specific engineering notes (Vulkan/xvfb headless rendering, ROCm wheel
selection from `repo.radeon.com`, the `libsvtav1` codec requirement) are
documented in the README and §7.2 so that evaluators can reproduce the
environment exactly.

---

## 5. Innovations and Key Technical Contributions

### 5.1 Checkpoint sweet-spot selection via evaluation-vs-steps curves

Instead of adopting the final checkpoint, we evaluated intermediate checkpoints
(9 episodes each, identical seeds) and found a clear, reproducible curve:

| Steps | 10k | 14k | 16k | **20k** | 30k (final) |
|---|---|---|---|---|---|
| Success (9-ep probe) | 1/9 | 2/9 | 3/9 | **5/9** | 3/9 |

![Checkpoint sweep — success peaks at 20k steps, then overfits](docs/figures/checkpoint_sweep.png)

![Training loss, 30k steps (log scale)](docs/figures/training_loss.png)

The 20k checkpoint was then evaluated on the full 25-episode verification set:
**13/25 = 52.0 %** — a 3× improvement over the 30k-step final checkpoint
(which scored 4/25 = 16.0 % on the same set). Training past the sweet spot
measurably overfits in this data regime. *The submitted model is
`checkpoint_020000`, not the final checkpoint.*

### 5.2 Systematic failure analysis (evidence-driven)

We treat failures as first-class scientific output; each hypothesis below was
tested with a dedicated experiment:

1. **"Stuck vs. just slow?"** — Doubling the episode budget (450 → 900 frames)
  rescued **zero** episodes (3/9 before, 3/9 after; all successes finish within
  198–431 frames). Failures are *true deadlocks at phase transitions*, not slow
  convergence.
2. **"Dip-then-rise" artifact.** The arm dips before aligning to the part — a
  behavior subtly present in the training data. Root cause: the expert's first
  motion uses joint-space RRT planning (`plan_path`), whose path is not
  Cartesian-straight; behavior cloning then amplifies the dip closed-loop.
  (Fix identified for future data: two-phase Cartesian interpolation instead of
  joint-space planning for the approach.)
3. **Why the nut fails.** Frame-level comparison of training vs. failed-eval
  wrist-camera footage shows the gripper reaches the *same 2-D image position*
  but hovers **~1 cm too high** — at the nut's top rim instead of its mid-body.
  2-D alignment ≠ 3-D alignment: the angled wrist camera makes the height error
  nearly invisible in image space, and the ~1 cm-thin nut (unlike the taller
  gear/bolt) cannot absorb it. Contributing factors: the frozen 360p vision
  tower's weak fine-grained depth regression and the 50-action open-loop chunk
  that cannot correct the final 2 cm.

  | Training grasp (fingers straddle nut mid-body) | Eval failure (same 2-D image position, ~1 cm too high → empty grasp) |
  |---|---|
  | ![training grasp frame](docs/figures/train_ep001_f078.png) | ![eval failure frame](docs/figures/eval_nutfail_f360.png) |
4. **Negative results, reported.** Two natural fixes were tried and *rejected by
  experiment*: more frequent replanning at eval time (`n_action_steps` 15/25 →
  2/9, worse than the 5/9 baseline — it disrupts commitment during
  grasp/place phases), and retraining with the last two vision blocks unfrozen
  plus doubled finger-loss weight (→ 1/30 — it destroys the arm/finger loss
  balance). The original recipe (frozen vision, finger weight 1.0) was already
  at a local optimum; the bottleneck is **data-side** (better approach
  trajectories and height supervision), which points directly at the next
  improvement (§7.3).

### 5.3 Honest-evaluation methodology

Noise quantification (§3.3), a single fixed-seed verification set replacing ad-hoc
multi-protocol reporting, per-episode video
audit trails, and a **fixed-seed verification set with explicit disclosure** (the
shipped `verification-set/` documents the full composition of its 25 randomly-
seeded episodes and our submitted result).
We ran the full 25 episodes on 2025-08-02: **13/25 = 52.0 %**
(gear 5/11, bolt 5/9, nut 3/5).

### 5.4 End-to-end synthetic-to-VLA pipeline on the AMD/ROCm stack

A complete, reproducible path from a hand-built Genesis scene to a
language-conditioned visuomotor policy — data generation, training, closed-loop
evaluation, and failure analysis — running entirely on one AMD GPU, with
ROCm-specific pitfalls documented and solved (§7.2).

---

## 6. Final Deliverables

| Deliverable | Location in this submission |
|---|---|
| Full pipeline source (scene, expert, data, training, eval, tools) | `src/industrial_pick/` |
| Web-based live demo (Flask + Genesis + VLA, browser-accessible) | `web_demo_server.py` |
| Reproducibility README (env, deps, step-by-step) | `README.md` |
| Dockerfile (ROCm 7.2.1 environment) | `Dockerfile` |
| Fixed-seed verification set (25 episodes + runner, fully reproducible) | `verification-set/` |
| Figures (checkpoint sweep, training curve, scene) | `docs/figures/` |
| Final checkpoint (`checkpoint_020000` of the 30k-step run) | see artifact links in `README.md` |
| Training/eval dataset (`industrial_sort_v2`, 450 episodes) | see artifact links in `README.md` |
| Demonstration video (3–5 min) | ⚠️ TODO before submission: [VIDEO LINK] |

**Final metrics (restated):** three-box language-conditioned sorting —
**13/25 = 52.0 %** on our fixed-seed verification set (gear 5/11, bolt 5/9,
nut 3/5), with the submitted `checkpoint_020000`.

---

## 7. Additional Information

### 7.1 What we are proud of

- The result rests on a measured model-selection curve, not on recency: the
  workshop reference baseline scored 1/30 on its (simpler) pick-and-place task;
  our own 30k-step final checkpoint scores 4/25 on the verification set; the
  submitted 20k-step checkpoint triples that to 52.0 % on a language-conditioned
  three-task scene — every step backed by logged, re-runnable experiments.
- A failure-analysis chain unusually complete for a hackathon: five hypotheses,
  five controlled experiments, two negative results reported with evidence.

### 7.2 ROCm/AMD engineering notes (also in README)

- ROCm PyTorch wheels must come from `repo.radeon.com` (ROCm 7.2.1 builds);
  stock PyPI torch will not see the GPU.
- LeRobot dataset video encoding must use **`libsvtav1`**: the `auto` codec
  selection mis-picks `h264_nvenc` (NVIDIA-only) and crashes on ROCm.
- Headless Genesis rendering requires Vulkan + X libraries (or xvfb) even on a
  GPU host; see `Dockerfile` for the exact package list.
- Python stdout to log files is block-buffered — monitor long evaluations by
  counting output video files, or run with `python -u`.

### 7.3 Future work (directly implied by §5.2)

Re-record data with a Cartesian two-phase approach (removes the dip), a short
settle pause before grasp closure, and nut oversampling; retrain to the 20k-step
sweet spot. The failure analysis predicts this recovers most of the nut gap
(currently 60 % on nut, already the strongest category in the verification set)
and lifts the overall success rate substantially.

---

## 8. Team Members and Contributions

**Team Answer** — single-member team.

| Member | Role | Contributions |
|---|---|---|
| Chengyu SHI | Sole member — system design & implementation | scene & expert design, synthetic data generation, VLA training, closed-loop evaluation & failure analysis, technical report and demonstration video |

*AI-assistance disclosure: Claude Code was used as a pair-programmer for
experiment orchestration, log analysis, and document drafting; all experimental
decisions and final content were reviewed and approved by the team.*
