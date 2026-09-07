# FruitGrip-CoDesign

*Solo developer: **Chanikya Nelapatla*** — AMD AI DevMaster Hackathon, Track 3: Physical AI.

![Composite dashboard: every headline result at a glance — confirmation bar, YCB generalization split, ROCm throughput, attribution reliability, force margin, grasp planner comparison](docs/images/dashboard.png)

**Gripper geometry is a free variable manipulation research has held constant — jointly searching geometry and control finds task-adaptive hardware no policy-only optimization can reach, and it works by resisting rotation, not squeezing harder.**

[![Success rate](https://img.shields.io/badge/success%20rate-93.3%25%20vs%2026.7%25-brightgreen)]()
[![CI](https://img.shields.io/badge/95%25%20CI-non--overlapping-blue)]()
[![Geometry attribution](https://img.shields.io/badge/geometry%20attribution-80.3%25%20%C2%B1%2017.7%25-brightgreen)]()
[![Force margin](https://img.shields.io/badge/force%20margin-20--37x-blue)]()
[![ROCm batched speedup](https://img.shields.io/badge/ROCm%20batched%20speedup-16x-red)]()
[![ROCm throughput ceiling](https://img.shields.io/badge/ROCm%20peak%20throughput-29.4x-red)]()
[![Objects tested](https://img.shields.io/badge/generalization-36%20YCB%20objects-orange)]()
[![Grasp planner](https://img.shields.io/badge/grasp%20planner-38%20objects%2C%20real%20geometry-orange)]()
[![Engines](https://img.shields.io/badge/cross--validated-Genesis%20%2B%20MuJoCo-purple)]()
[![Team](https://img.shields.io/badge/team-solo%20developer-lightgrey)]()

**[▶ Watch the demo video](https://drive.google.com/drive/folders/1hEso_WAGyrSZeIq-kZmOnrUcMgNMCHYu?usp=sharing)** — end-to-end walkthrough of the co-design search, the confirmation eval, and both live demos below.

## Live demos — two separate pages, different purposes

| | What it shows | Link |
|---|---|---|
| **1. Trajectory replay** | Scrubbable playback of 3 real *recorded* Genesis physics episodes (baseline failing, the winning design succeeding, and its one honest failure mode). Fixed set of 3 trials, no object picker. | **[▶ Open](https://chanikkyasaai.github.io/Radeon-hackathon-2026-07/fruitgrip-codesign/demo/interactive_3d/index_artifact.html)** |
| **2. Antipodal grasp planner** | Pick any of **38 real object meshes** and either frozen design from a dropdown, watch an animated descend/close/lift, and see the exact chosen cross-section, contact points, and surface normals — live output of `grasp_planner.plan_grasp_with_geometry`, the same function the controller calls, not a hand-tuned illustration. | **[▶ Open](https://chanikkyasaai.github.io/Radeon-hackathon-2026-07/fruitgrip-codesign/demo/grasp_planner_viz/index.html)** |

Both are hosted via GitHub Pages, no clone needed. (GitHub can't render `.html` live from its own blob viewer, only as source text — these are real hosted pages. To run locally instead: clone the repo and open [`demo/interactive_3d/index.html`](demo/interactive_3d/index.html) or [`demo/grasp_planner_viz/index.html`](demo/grasp_planner_viz/index.html).)

## What this is

A task-adaptive Franka Panda end-effector, co-designed jointly with its scripted controller on the [Genesis](https://github.com/Genesis-Embodied-AI/Genesis) physics engine (ROCm/AMD GPU-accelerated), picking fruit off a table and placing it in a bowl. AMD AI DevMaster Hackathon, Track 3: Physical AI. **Every claim below is backed by a statistically-powered evaluation, a raw JSON file in `results/`, and an exact reproduction command in [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md).**

## Key findings

| # | Finding | Number |
|---|---|---|
| 1 | Pick-and-place success, n=30 paired trials, non-overlapping 95% Wilson CIs | **93.3%** vs **26.7%** |
| 2 | Mechanism: force headroom on both designs — the gap is geometry, not squeeze | **20–37x** margin |
| 3 | Geometry's share of the total gain (5-seed attribution) | **80.3% ± 17.7%** |
| 4 | Generalization across 36 held-out YCB objects | Category-specific, both-fail on 56% |
| 5 | ROCm batched-GPU speedup, correctness-validated | **16x**, peak **29.4x** CPU |
| 6 | Cross-simulator (MuJoCo) replication | Reversal, mechanistically explained |
| 7 | Geometry-driven grasp planner vs. fixed lookup table | Real wins + one real regression |

**1 — Core result.** A CMA-ES-searched 3-finger gripper beats a stock-equivalent 2-finger baseline **93.3%** [78.7%, 98.2%] vs **26.7%** [14.2%, 44.4%] (n=30 paired trials, 95% Wilson CIs — non-overlapping, statistically distinguishable). → [core confirmation](results/01_core_confirmation/findings.md)

![Bar chart: 93.3% winner success rate vs 26.7% baseline, with 95% Wilson confidence interval error bars, n=30 paired trials](docs/images/confirmation_bar.png)

**2 — The mechanism is geometry, not force.** Both designs carry **20–37x** more grip force than physically required to hold the object — the success gap is explained by 3 distributed contact points resisting rotation/slip, not a harder squeeze.

**3 — Geometry drives the gain, and it's reliable.** **80.3% ± 17.7%** of the total gain is attributable to geometry, not the controller (5-seed attribution experiment) — the winning design holds **100%** success across every seed; the baseline swings 0–66.7%. → [attribution](results/02_attribution_multiseed/)

![Line chart: winner holds 100% success across 5 seed groups while baseline swings from 0% to 66.7%](docs/images/attribution_reliability.png)

**4 — Generalization is real but precisely bounded — stated with the same confidence as the wins.** Tested on **36 diverse YCB objects**, not just more fruit: the advantage is category-specific (round/curved objects favor the winner, flat-faced objects favor the baseline), and this project directly instrumented *why* via contact-normal alignment rather than leaving it as an observation. → [generalization](results/03_generalization/) · [contact-geometry mechanism](results/07_contact_geometry/contact_geometry_findings.md)

![Diverging bar chart of 16 YCB objects where the two designs' success rates differ, colored by which design is favored](docs/images/ycb_category_split.png)

**5 — ROCm/AMD GPU, the full honest arc.** Naive single-environment GPU is **2.5–3.6x slower** than CPU (diagnosed why, not hidden) → properly batched GPU is up to **16x faster** (correctness-validated against CPU) → raw physics-step throughput ceiling is **29.4x** CPU's peak (148,419 vs 5,052 env-steps/sec) → and a further engineering finding: GPU batching accelerates *re-validating known candidates* (17x) far more than it accelerates *searching* for new ones, because scene-build cost — not step throughput — dominates search-loop wall time. → [ROCm benchmark](results/04_rocm_benchmark/rocm_findings.md) · [GPU-corrected search](results/06_fruit_archive_qd/gpu_corrected_findings.md)

![Log-log line chart: ROCm GPU vs CPU throughput in env-steps/sec across n_envs from 1 to 4096, crossing over and reaching a 29.4x peak](docs/images/rocm_throughput.png)

**6 — Independently cross-validated across two physics engines, not just internally reliable.** Replicated the full protocol in MuJoCo, found the result direction reverses there, then explained why with a controlled friction dose-response sweep run in both engines — **the reversal is mechanistically understood, not an unexplained artifact.** → [cross-simulator replication](results/05_cross_simulator/)

![Line chart: success rate vs friction ratio for baseline and winner designs, overlaid for Genesis and MuJoCo, showing the crossover that explains the reversal](docs/images/friction_doseresponse.png)

**7 — A real antipodal/radial grasp planner replaces the old fixed 7-object lookup table.** Same rigor as every other claim (n=15, 72 object×design evaluations, 6685s wall-clock): real wins (apple 20%→40%, rubik's cube 0%→60%, golf ball 0%→40%) **and** one real regression (hammer 60%→0%, reported with equal weight) — a reshuffle, not a uniform fix, stated exactly as measured. → [grasp planner findings](results/08_grasp_planner/grasp_planner_findings.md)

![Grouped bar chart: before/after success rates for 6 representative objects under the grasp planner, showing real wins and one real regression](docs/images/grasp_planner_comparison.png)

## Architecture

![Box-and-arrow architecture diagram: parametric gripper geometry to CMA-ES+QD search to co-adapted controller (plus grasp planner) to domain-randomized physics trial to frozen designs to cross-simulator replication to statistically powered comparison](docs/images/architecture_diagram.png)

Franka Panda + parametric gripper → co-adapted scripted controller (now optionally routed through the geometry-driven grasp planner) → domain-randomized physics trial (friction, mass, pose) → aggregated success/force/slip → statistically powered comparison, replicated across engines and hardware backends.

## Quickstart

Reproduce the headline result (Genesis, CPU, a few minutes):

```bash
uv sync --extra codesign
uv pip install torch --index-url https://download.pytorch.org/whl/cpu
uv run python franka_fruit_pick/codesign/confirmation_eval.py --n-trials 30
```

(Run from this repo's root — where `pyproject.toml`/`uv.lock` live. `torch` is deliberately not a plain dependency since the right wheel depends on your backend — CPU here; see [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md) for the ROCm one.)

Expected output: a table matching `results/01_core_confirmation/findings.md`'s headline numbers, written to `results/01_core_confirmation/confirmation_eval.json`.

→ Full setup (including ROCm GPU wheels) and one exact command per result table: [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md)
→ Full write-up — methodology, every result, limitations stated plainly: [`docs/TECHNICAL_REPORT.md`](docs/TECHNICAL_REPORT.md)
→ Frozen design parameters (the exact two `GripperParams` every table above measures): [`configs/frozen_designs.py`](configs/frozen_designs.py)

### Run via Docker

A ROCm 7.2.1 dev image is provided at [`docker/Dockerfile`](docker/Dockerfile) (Ubuntu 24.04, matched ROCm torch/vision/audio/triton wheels, `genesis-world` + `lerobot[smolvla]`):

```bash
docker build -f docker/Dockerfile -t franka-fruit-pick:rocm7.2.1 .
docker run --rm -it --network=host \
    --device=/dev/kfd --device=/dev/dri \
    --group-add video --group-add render \
    --security-opt seccomp=unconfined --cap-add=SYS_PTRACE \
    --ipc=host --shm-size=8g \
    -v "$PWD":/workspace/franka_fruit_pick_demo \
    franka-fruit-pick:rocm7.2.1
```

**Honesty note**: this session started the build and watched it pull cleanly (the ROCm base image alone is ~7.4GB and took ~4 minutes on this session's network), but did not let it run to completion — the full build also downloads 4 large ROCm-specific wheels and `lerobot[smolvla]`'s dependency tree, which would run well past a quick check. The commands above are transcribed from the Dockerfile's own header (written and used during earlier development), not fabricated, but the end-to-end build was **not re-verified in this session** — budget 20-40+ minutes on a fast connection if you run it yourself.

## Repository layout

```
├── README.md                 you are here
├── docs/
│   ├── TECHNICAL_REPORT.md   full methodology, results, limitations
│   ├── REPRODUCIBILITY.md    one exact command per result table
│   └── images/
├── configs/
│   └── frozen_designs.py     the winner + baseline GripperParams, checked in
├── franka_fruit_pick/        the package (kept at repo root — see note below)
│   └── codesign/             all co-design, search, cross-simulator, QD, grasp-planner code
│       └── mujoco_repl/      the MuJoCo replication port
├── results/                  every finding, organized by topic, raw JSON + .md
│   ├── 01_core_confirmation/  02_attribution_multiseed/  03_generalization/
│   ├── 04_rocm_benchmark/     05_cross_simulator/         06_fruit_archive_qd/
│   └── 07_contact_geometry/   08_grasp_planner/
├── demo/
│   ├── interactive_3d/       scrubbable replay of real recorded trajectories
│   └── grasp_planner_viz/    live antipodal grasp planner, 38-object dropdown
├── docker/
│   └── Dockerfile            ROCm 7.2.1 dev environment (see "Run via Docker" above)
├── scripts/
│   ├── run_all_confirmation_evals.sh
│   └── generate_charts.py    regenerates every docs/images/*.png from results/*.json
└── assets/, datasets/        bundled meshes / robot model (see credits below)
```

*Note: `franka_fruit_pick/` stays at the repo root rather than moving under `src/` — every module in `codesign/` locates `results/`, `assets/`, and its sibling modules via paths relative to its own location, and this project prioritized not risking that working, statistically-validated code over a cosmetic move under a hard deadline.*

## Foundation

This project's controller, scene, and domain-randomization layers are built on top of a scripted-to-learned Franka fruit-pick reference pipeline (Genesis + LeRobot). That base pipeline's own M1–M5 walkthrough (scene → scripted policy → dataset recording → domain randomization → policy training/eval) is preserved under `franka_fruit_pick/` for reference; this README and `docs/TECHNICAL_REPORT.md` document what this project adds on top of it — the co-design search, statistical validation, cross-simulator replication, ROCm benchmarking, and the geometry-driven grasp planner.

## Credits & asset sources

Assets under `assets/` are not original to this repo:
- **Franka Panda robot model** — from [Genesis](https://github.com/Genesis-Embodied-AI/Genesis)'s bundled assets.
- **YCB object meshes** — from the [ManiSkill2](https://github.com/haosulab/ManiSkill) dataset, originally the [YCB Object and Model Set](https://www.ycbbenchmarks.com/).

Refer to the upstream projects for their licenses if redistributing these assets.

## Team

**Chanikya Nelapatla** — solo developer. AMD AI DevMaster Hackathon, Track 3: Physical AI. Every stage of this project — the co-design search, the statistical validation, the cross-simulator replication, the ROCm benchmarking, the grasp planner, and the live demos above — was designed, built, and validated by one person.

## License

[MIT](LICENSE). Genesis is Apache 2.0; YCB/ManiSkill2 assets remain under their own licenses (see Credits above).
