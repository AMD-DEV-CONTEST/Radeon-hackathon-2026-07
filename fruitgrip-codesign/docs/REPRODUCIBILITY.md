# Reproducibility

One exact command per result table in [`TECHNICAL_REPORT.md`](TECHNICAL_REPORT.md), in report order. Every command is run from the repo root after setup (below). Expected runtime is measured on a 16-core AMD Ryzen 7 5825U CPU-only machine unless a GPU/ROCm backend is explicitly called out.

## Setup

```bash
uv sync --extra codesign              # genesis-world, numpy, trimesh, cma, etc.
uv pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU build; see below for ROCm
uv run python franka_fruit_pick/setup_assets.py   # verify/populate bundled assets
```

Requires Python 3.12. `torch` is deliberately not a plain dependency in `pyproject.toml` — `genesis-world` imports it unconditionally (so it's required for every result below, not just the GPU ones), but the correct wheel depends on your backend, so it's installed explicitly here. For the ROCm-backend results (§6, and the GPU rows below), install the matched ROCm 7.2.1 torch wheel instead of the CPU one above — see the original demo README section this project builds on, or provision a ROCm cloud instance with the `Genesis-ROCm-CoDesign` template. MuJoCo results (§7) additionally need `pip install mujoco` (already a `genesis-world` dependency, no extra install needed in this project's `pyproject.toml`).

---

## §3 — Core confirmation-eval

```bash
uv run python franka_fruit_pick/codesign/confirmation_eval.py --n-trials 30
```
**Backend**: Genesis, CPU. **Runtime**: ~2–4 minutes. **Output**: `results/01_core_confirmation/confirmation_eval.json`.

## §4 — 5-seed attribution

```bash
uv run python franka_fruit_pick/codesign/run_attribution_multiseed.py
```
**Backend**: Genesis, CPU. **Runtime**: ~2.5 hours (5 seeds × 4 arms × population×generations CMA-ES evaluations — this is the most expensive single-machine reproduction in this table; the ROCm-GPU naive attempt at the same workload was slower, not faster, see §6). **Output**: `results/02_attribution_multiseed/attribution_multiseed.json`.

## §5 — Generalization

Original apple/pear held-out check:
```bash
uv run python franka_fruit_pick/codesign/held_out_eval.py
uv run python franka_fruit_pick/codesign/held_out_eval_batched.py   # the expanded n=200 version
```
**Backend**: Genesis, CPU. **Runtime**: ~10–20 minutes combined. **Output**: `results/01_core_confirmation/held_out_eval.json`, `results/03_generalization/held_out_eval_expanded.json`.

36-object YCB-scale generalization:
```bash
uv run python franka_fruit_pick/codesign/ycb_generalization_eval.py --seed-base 7000 --n-trials 15
```
**Backend**: Genesis, CPU. **Runtime**: ~72 minutes (36 objects × 2 designs × 15 trials, one scene build per object). **Output**: `results/03_generalization/ycb_generalization_eval.json`. Note: trial count is 15/object here (reduced from 30 for machine-headroom reasons on the development box — see the script's own header comment); CIs in `ycb_generalization_findings.md` reflect n=15.

Contact-geometry mechanism test (the direct instrumentation behind §5's "confirmed via" claim):
```bash
uv run python franka_fruit_pick/codesign/contact_geometry_eval.py --seed-base 11000
```
**Backend**: Genesis, CPU. **Runtime**: ~14 minutes (10 objects × 2 designs × 10 trials). **Output**: `results/07_contact_geometry/contact_geometry_eval.json`.

## §6 — ROCm / AMD hardware

The raw-throughput and naive-vs-batched benchmarks require an actual ROCm-capable AMD GPU; they are not reproducible on CPU-only hardware by construction (that's the point being measured). On a provisioned ROCm instance:

```bash
uv run python franka_fruit_pick/codesign/throughput_bench.py            # raw batched-stepping throughput curve
uv run python franka_fruit_pick/codesign/fruit_archive_gpu.py --n-evals 80 --n-init 15 --seed 42          # GPU-batched search
uv run python franka_fruit_pick/codesign/fruit_archive_gpu_revalidate.py                                   # GPU-batched re-validation
```
**Backend**: Genesis, `gs.amdgpu` (ROCm 7.2.1). **Runtime**: throughput benchmark ~15–20 minutes (sweeps `n_envs` from 1 to 4096); GPU archive search ~3.74 hours; GPU re-validation ~16 minutes. **Output**: `results/04_rocm_benchmark/throughput_bench_gpu*.json`, `results/06_fruit_archive_qd/fruit_archive_gpu.json`, `results/06_fruit_archive_qd/fruit_archive_gpu_revalidation.json`.

CPU-side comparison points (already covered above/below): `throughput_bench_cpu.json` (§6's CPU throughput row), `fruit_archive.json` (§8's CPU search), `fruit_archive_revalidation.json` (§8's CPU re-validation).

## §7 — Cross-simulator replication (MuJoCo)

```bash
uv run python franka_fruit_pick/codesign/mujoco_repl/confirmation_eval_mj.py --n-trials 30
```
**Backend**: MuJoCo, CPU. **Runtime**: ~3–5 minutes. **Output**: `results/05_cross_simulator/cross_simulator_confirmation_eval.json`.

Friction dose-response sweep, both engines (the mechanism explanation behind §7's reversal):
```bash
# MuJoCo side (fast, full resolution)
uv run python franka_fruit_pick/codesign/mujoco_repl/friction_sweep_mj.py --seed-base 5000
# Genesis side (reduced resolution — see script header; full resolution triggered swap-thrashing on the dev machine)
uv run python franka_fruit_pick/codesign/friction_sweep_genesis.py --seed-base 5000 --friction-step 0.1 --n-trials 15
```
**Backend**: MuJoCo CPU (~3 minutes) / Genesis CPU (~26 minutes at reduced resolution). **Output**: `results/05_cross_simulator/friction_doseresponse_mujoco.json`, `results/05_cross_simulator/friction_doseresponse_genesis.json`.

Per-finger contact-onset timing diagnostic (ruled out as the reversal's mechanism, reported in `cross_simulator_findings.md` §5):
```bash
uv run python franka_fruit_pick/codesign/finger_contact_batch_genesis.py --n-trials 60 --seed-base 2000
uv run python franka_fruit_pick/codesign/mujoco_repl/finger_contact_batch_mj.py --n-trials 60 --seed-base 2000
```
**Runtime**: Genesis ~2.5 minutes, MuJoCo ~5 seconds.

## §8 — Quality-diversity search (FruitArchive)

```bash
uv run python franka_fruit_pick/codesign/fruit_archive.py --n-evals 500 --n-init 60 --seed 42
```
**Backend**: Genesis, CPU. **Runtime**: ~2.55 hours. **Output**: `results/06_fruit_archive_qd/fruit_archive.json`.

Re-validation of the top archive cells + both frozen designs, at full statistical power (30 trials/object, includes apple explicitly):
```bash
uv run python franka_fruit_pick/codesign/fruit_archive_revalidate.py
```
**Backend**: Genesis, CPU. **Runtime**: ~8 hours (6 candidates × 4 objects × 30 trials, one scene build per candidate-object pair — this is the slowest single command in this table; the GPU-batched equivalent in §6 does the same job in ~16 minutes). **Output**: `results/06_fruit_archive_qd/fruit_archive_revalidation.json`.

GPU-side versions of both are listed under §6 above (same commands, ROCm backend).

---

## Convenience script

```bash
scripts/run_all_confirmation_evals.sh
```

Reproduces every **fast** (CPU, under ~5 minutes) result table above end to end — the core confirmation-eval, both cross-simulator confirmation-evals, and the contact-geometry test. Does not include the multi-hour attribution, generalization-sweep, FruitArchive search/re-validation, or any GPU-backend command — those are listed individually above with their own runtime so you can choose which to run.

---

## A note on exact numeric reproduction

Every script above uses fixed, documented seeds, so re-running it reproduces the *same* trial instances — but not necessarily bit-identical numbers, since Genesis's own physics stepping is not guaranteed bit-reproducible across hardware/driver versions. Expect the same qualitative result (success-rate ballpark, CI overlap/non-overlap direction, force-margin order of magnitude) rather than digit-for-digit identical output. Where two runs of the *same* script on the *same* machine produced slightly different numbers during this project's own development (noted in the relevant `results/*/*.md` file when it happened), that variance is reported, not hidden.
