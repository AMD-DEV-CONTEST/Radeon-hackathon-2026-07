# GuardianSim — Think Thousands. Execute One.

**Track:** Track 3 — Physical AI Challenge

**Team:** Aegis Motion

**Team structure:** Solo developer, GitHub
[`@nvm-star-max`](https://github.com/nvm-star-max)

## Judge quick start

1. Open the public evidence arena: <https://nvm-star-max.github.io/GuardianSim/>
2. Watch the packaged 90-second Radeon preview.
3. Read the packaged technical report and inspect the machine-readable evidence.

No account is required. The site replays preserved results; it does not create
new benchmark samples in the browser.

## What GuardianSim does

GuardianSim is a policy-agnostic decision layer for simulated robot
manipulation. A PPO, VLA, or scripted policy can propose a motion. GuardianSim
restores one fingerprinted Genesis state, evaluates bounded counterfactual
actions on an AMD Radeon GPU, applies frozen hard safety gates, then permits
one eligible action or explicitly stops.

The Radeon role is direct: run thousands of complete robot worlds in parallel,
then use the same parallel-physics path to screen candidate actions before one
simulated motion is executed.

## Memorable Radeon result

The frozen Scale V3 endurance suite ran one full headless manipulation scene
per world: Franka, table, and four active YCB entities.

| Parallel worlds | Measured steps | P50 env-steps/s | P95 env-steps/s | Mean GPU | Peak VRAM |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 4,096 | 41,943,040 | 152,697.384 | 153,087.797 | 97.768% | 6.246 GiB |
| 8,192 | 83,886,080 | 214,944.307 | 215,406.452 | 97.978% | 11.524 GiB |
| 16,384 | 167,772,160 | 278,051.244 | 278,660.488 | 98.817% | 22.051 GiB |

Five independent processes were run per batch. Across all 15 formal
measurements, Radeon advanced **293,601,280** Genesis environment steps,
recorded **98.330%** weighted mean GPU utilization, and reached **100%**
observed peak utilization. The largest batch's five-repeat range was
274,989.939–278,671.733 environment-steps/s.

These are physics environment steps from complete simulated worlds, not PPO
samples, inference tokens, independent robot trials, or physical-robot data.

## Robot-decision result

The separate Safety Swarm V2 run evaluated **18 candidate actions × 256
uncertainty worlds = 4,608 candidate-world pairs**. Five actions passed all
256 worlds. Frozen ranking selected one action with:

- **256/256** safe worlds;
- **0** sampled clutter contacts;
- **66.249 mm** worst-case sampled clearance;
- **0.907** minimum stability.

This produces the judge-facing funnel **4,608 → 5 → 1**. The candidate-world
pairs are an engineering stress-test population, not independent robot trials.

## Frozen 30-scenario result

The primary Gate 3.2 benchmark used three independent Genesis simulations per
strategy and scenario:

| Metric | Nominal | GuardianSim |
| --- | ---: | ---: |
| Repeatable safe scenarios | 18/30 | 30/30 |
| Independent safe simulations | 58/90 | 90/90 |
| Sampled clutter-contact executions | 30 | 0 |
| Mean sampled clutter clearance | 23.191 mm | 46.003 mm |

These are Genesis simulation results, not physical-robot deployment claims.

## AMD Radeon / ROCm path

- AMD Radeon Cloud, one `gfx1100` Radeon GPU;
- Genesis 1.2.3 with the `gs.amdgpu` backend;
- PyTorch `2.9.1+gitff65f5b`;
- HIP `7.2.53211-e1a6bc5663`;
- Python 3.12.3.

The repository includes the exact ROCm installer, dependency lock,
GPU-required preflight, bounded real-Genesis smoke, strict validators,
checksums, and complete-source ROCm Dockerfile.

## Deliverables

- Public evidence arena: <https://nvm-star-max.github.io/GuardianSim/>
- Immutable V5 source and evidence:
  <https://github.com/nvm-star-max/GuardianSim/tree/hackathon-2026-submission-v5>
- Reproducibility guide:
  <https://github.com/nvm-star-max/GuardianSim/blob/hackathon-2026-submission-v5/REPRODUCIBILITY.md>
- Technical report: [`GuardianSim-Technical-Report.pdf`](GuardianSim-Technical-Report.pdf)
- 90-second narrated Radeon preview:
  [`GuardianSim-Radeon-Parallel-Futures-preview.mp4`](GuardianSim-Radeon-Parallel-Futures-preview.mp4)
- 4:41 complete workflow demo:
  <https://raw.githubusercontent.com/nvm-star-max/GuardianSim/hackathon-2026-submission-v5/docs/submission/GuardianSim-Aegis-Motion-demo-review-v2.mp4>
- Scale V3 and decision evidence: [`evidence`](evidence)
- Full Scale V3 evidence:
  <https://github.com/nvm-star-max/GuardianSim/tree/hackathon-2026-submission-v5/docs/evidence/radeon-scale-v3-formal-2026-08-03>
- Full Safety Swarm V2 evidence:
  <https://github.com/nvm-star-max/GuardianSim/tree/hackathon-2026-submission-v5/docs/evidence/safety-swarm-v2-formal-2026-07-30>
- Immutable Gate 3.2 evidence:
  <https://github.com/nvm-star-max/GuardianSim/tree/hackathon-2026-submission-v5/docs/evidence/gate-3-2>

## Reproduction

On a supported Radeon Cloud Blank OpenCode workspace:

```bash
git clone https://github.com/nvm-star-max/GuardianSim.git
cd GuardianSim
git checkout hackathon-2026-submission-v5

scripts/install_system_deps.sh
uv python install 3.12
export UV_PROJECT_ENVIRONMENT=/opt/venv
uv sync --frozen --python 3.12
scripts/install_rocm_stack.sh

./scripts/evaluator_preflight.sh
./scripts/run_evaluator_smoke.sh
```

The smoke checks the documented Radeon/Genesis execution path. It is not the
Scale V3 performance benchmark.

## Responsible limitations

- All published evidence comes from Genesis simulation; no physical robot was
  tested.
- Sampled axis-aligned clearance is an engineering proxy, not a formal
  continuous-time collision proof.
- The action family is bounded and planning is not yet real-time.
- Unsupported geometry can produce a deliberate safe stop.
- Scale V3 environment steps, Safety Swarm candidate-world pairs, and Gate 3.2
  independent executions remain separate units.

## Team contribution

The solo developer `@nvm-star-max` completed project direction, system design,
implementation, Radeon Cloud experiments, evidence preservation,
reproducibility documentation, report production, and video production.
AI-assisted tools supported implementation and documentation; the submitting
team remains responsible for validation, claims, licenses, and compliance.
