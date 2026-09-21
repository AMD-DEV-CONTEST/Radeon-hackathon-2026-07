# Track 3 Submission: Q-Forge

## Submission identity

| Field | Value |
|---|---|
| Track | Track 3 — Physical AI |
| Participant / team name | Yuhao Cao |
| Application name | Q-Forge |
| Pull request title | `Track 3, Yuhao Cao, Q-Forge` |
| Primary platform | AMD Radeon `gfx1100`, 96 compute units, 48 GiB VRAM |
| License | Apache-2.0 for original Q-Forge code |
| Dedicated source repository | <https://github.com/ZorAttC/Q-Forge> |

## Project summary

Q-Forge improves a flow-matching SmolVLA robot policy without collecting
additional expert demonstrations. A Base policy fine-tuned on 20 demonstrations
generates locally perturbed simulator rollouts. LIBERO reward and terminal
success automatically label the experience. A five-member action-sensitive Q
ensemble learns from the resulting successful and failed trajectories, and
bounded Q-gradient ascent makes small value-increasing corrections to each
action chunk. An optional residual-distillation path amortizes those corrections
into the policy so deployment no longer requires the critic.

The complete workflow runs on one AMD Radeon `gfx1100` GPU: supervised
fine-tuning, EGL simulation, rollout collection, feature extraction, critic
training, Q-guided evaluation, residual distillation, and attention-backend
benchmarking.

## Headline results

All methods use paired reset states and a shared inference seed within each task.

| LIBERO-Spatial task | Method | Success | Paired change vs. Base |
|---|---|---:|---:|
| Task 7 | Base | 21/50 (42%) | — |
| Task 7 | Q selection, N=4 | 18/50 (36%) | −3 states |
| Task 7 | **Q-guidance** | **34/50 (68%)** | **+13 states; p=0.0146** |
| Task 7 | QVGM residual | 32/50 (64%) | +11 states; no regressions |
| Task 3 | Base | 38/50 (76%) | — |
| Task 3 | Q selection, N=4 | 35/50 (70%) | −3 states |
| Task 3 | **Conservative Q-guidance** | **44/50 (88%)** | **+6 states; p=0.03125** |
| Task 3 | QVGM residual | 43/50 (86%) | +5 states |

The primary Task 7 result uses a frozen 512-dimensional random projection of
the SmolVLA prefix, not the optional 2048-dimensional RL-token representation.

## Track 3 compliance matrix

| Requirement | Submission evidence | Status |
|---|---|---|
| Target application definition | Technical report Sections 1, 3, and 5 | Included |
| Overall architecture and solution design | Technical report Section 4 and two architecture figures | Included |
| Training and evaluation datasets | `docs/DATA.md`, report Section 5, Task 3 reproduction section | Included |
| AMD Radeon use in training and inference | Report Section 7, `docs/AMD_ROCM.md`, benchmark artifacts | Included |
| Innovations and technical contributions | Report introduction, method, discussion, and contribution list below | Included |
| Final deliverables and output forms | Report Section 10 and this submission index | Included |
| Additional strengths | Paired statistics, negative baselines, attention profiling, latency optimization | Included |
| Team members and contributions | Sole-participant statement in report and this index | Included |
| Dedicated source repository | <https://github.com/ZorAttC/Q-Forge> plus the complete embedded source package | Included |
| Docker image | Native ROCm reproduction is supplied; prebuilt image is optional and not included | Optional item not included |
| Environment and dependencies | Root README, `pyproject.toml`, ROCm constraints, reproduction guide | Included |
| Step-by-step reproduction | Task 7 and Task 3 procedures in `docs/REPRODUCTION.md` | Included |
| Demonstration video | 4:16 English 1080p video with actual paired simulator rollouts, workflow, and results | Included |
| Supplementary materials | JSON evidence, interactive HTML, SVG figures, optimization record | Included |

## Required Track 3 deliverables

### 1. Technical report

- [Technical report](docs/TECHNICAL_REPORT.md)
- [System architecture](assets/architecture.svg)
- [State representation and Q-ensemble architecture](assets/q_critic_rlt.svg)
- [Audited results](docs/RESULTS.md)
- [Dataset and split documentation](docs/DATA.md)

The report covers the target application, architecture, algorithms, datasets,
AMD Radeon utilization, contributions, deliverables, results, limitations, and
the sole participant's contribution.

### 2. Project source code

- `src/` — Q-Forge Python package
- `scripts/` — training, collection, caching, evaluation, and benchmark tools
- `configs/` — experiment and LIBERO/RLinf configuration
- `tests/` — unit and protocol tests
- `patches/` — narrowly scoped upstream compatibility patch
- `pyproject.toml` — package metadata and direct dependencies

Large checkpoints, raw datasets, caches, and training logs are intentionally
excluded. Their expected locations and generation steps are documented.

### 3. Reproducibility instructions

- [Reproduction guide](docs/REPRODUCTION.md)
- [AMD Radeon and ROCm notes](docs/AMD_ROCM.md)
- [Root project guide](README.md)
- ROCm package constraints: `constraints/torch-rocm64.txt`

The guide separates a short evaluator check from the complete pipeline and
documents dependencies, environment setup, artifact layout, training stages,
paired evaluation, and attention benchmarking.

### 4. Demonstration video

- [Q-Forge demonstration video](video/Q-Forge-demo.mp4)
- Duration: approximately 4 minutes 16 seconds
- English narration and burned-in English subtitles
- Editable [storyboard](video/storyboard.md), [narration](video/narration.txt),
  and [subtitle file](video/subtitles.srt)

The video shows the paired Base and Q-guided rollout, result evidence, the
self-labeled training loop, and AMD Radeon engineering decisions.

### 5. Supplementary materials

- [Interactive attention benchmark](reports/attention_bench_gfx1100.html)
- [Machine-readable attention benchmark](reports/attention_bench_gfx1100.json)
- [Inference optimization record](reports/inference_optimization_change_record.md)
- [Machine-readable primary results](results/main_results.json)
- [Machine-readable Task 3 replication](results/task3_results.json)
- [Machine-readable critic and guidance diagnostics](results/critic_and_guidance.json)

## Key technical contributions

1. **Self-labeled local action coverage.** Six perturbed rollouts per reset state
   create successful and failed outcomes under nearly fixed state context. The
   primary dataset contains 300 episodes, 60,505 transitions, and 36/50 states
   with mixed outcomes.
2. **Action-sensitive Q ensemble.** Five Q heads repeatedly inject the flattened
   action chunk at every layer, preserving useful action gradients despite a
   much larger state representation.
3. **Constrained Q-guidance.** Gradient clipping, valid-action projection, a
   Base-centered trust region, and per-sample keep-best selection restrict
   critic optimization to a local neighborhood.
4. **Critic-free residual deployment.** Detached critic-guided corrections are
   distilled into the flow velocity field, preserving the standard SmolVLA
   deployment architecture.
5. **AMD-specific systems work.** The project documents stable mixed CPU/GPU
   residual-target construction and chooses CK, SDPA, or Triton attention by
   execution phase rather than forward throughput alone.

## Participant contribution

**Yuhao Cao** is the sole participant and is responsible for project conception,
system design, implementation, AMD ROCm adaptation, experimentation, evaluation,
visualization, video production, and documentation.

## Evidence boundary

The controlled study covers two LIBERO-Spatial tasks with 50 paired reset states
and one inference seed per task. Task 7 guidance-selection states are included in
the final 50-state summary. Task 3 uses a conservative preset because its held-out
TD loss is slightly above the predefined gate. No real-robot result is claimed.

## Third-party components

Q-Forge builds on LIBERO, LIBERO-sim, LeRobot, SmolVLA, RLinf, PyTorch,
FlashAttention, Transformers, MuJoCo, and their dependencies. Their source,
weights, datasets, and licenses remain governed by their respective upstream
terms. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Container packaging status

A prebuilt Docker image is not included. The full stack depends on separately
licensed LIBERO assets and demonstrations, SmolVLA weights, compatible LeRobot
and RLinf checkouts, and a ROCm runtime matched to the evaluator's Radeon
hardware. The native setup is documented in `docs/REPRODUCTION.md`; generated
models and datasets are intentionally kept outside the source submission.
