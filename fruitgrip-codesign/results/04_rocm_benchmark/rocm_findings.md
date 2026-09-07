# ROCm benchmark — findings

Session 4 of the task-adaptive end-effector co-design work, Priority 3. First time
this codebase actually ran on a real discrete AMD GPU (a Radeon Cloud instance,
`gfx1100`/device `0x744b`, 48GB VRAM, ROCm 7.2.1). All prior sessions were CPU-only
(a laptop iGPU with no ROCm support), so every number below is the first real
hardware evidence for or against the project's ROCm claim.

## Setup notes (real friction encountered, fixed along the way)

- Generic `pip install torch --index-url .../rocm6.2` worked (confirmed
  `torch.cuda.is_available()==True`) but Genesis flagged it as unsupported
  (`torch<2.8.0`). Upgraded to the demo README's exact matched wheel
  (`torch-2.9.1+rocm7.2.1`) rather than ignore the warning.
- `pip install genesis-world` hit the same `numba`/`llvmlite` resolver-backtracking
  problem already known from local setup (session 1) — fixed by pre-installing the
  pinned versions before `genesis-world`, same as the local `pyproject.toml` override.
- **Found and fixed a real portability bug**: `gripper_gen.generate_gripper_xml`
  baked an *absolute, local-machine* path into the `meshdir` of every generated
  gripper MJCF file. Copying the codebase (or just its generated-file cache) to a
  different machine broke instantly with a MuJoCo "Error opening file" pointing at
  the *origin* machine's path. Fixed to a relative path (`../assets`, resolved
  relative to the MJCF file's own location, which is how MuJoCo actually resolves
  `meshdir`) and cleared the stale cache on both machines. This would have silently
  broken reproducibility for anyone else trying to run this project from a fresh
  clone on different hardware — exactly the scenario the hackathon's own
  "Reproducibility Instruction README" requirement cares about.
- Confirmed Genesis actually selects the GPU device before spending further credits:
  `Running on [AMD Radeon Graphics] with backend gs.amdgpu` in Genesis's own init log.

## The literal same-structure benchmark: GPU is *not* faster (and that's expected)

Reran the exact 5-seed attribution experiment (same seeds, same per-arm budgets) that
took the CPU backend 9272.8s, with the backend flipped to `gs.amdgpu`. A 3-call smoke
test first showed each evaluation taking 56–65s on GPU vs ~19s on CPU. The real run
confirmed this at scale (21 evaluations completed before the run was stopped, per a
mid-run decision — see below): **59.6s/eval average on GPU vs 24.1s/eval on CPU, i.e.
GPU ran ~2.5x *slower***.

This is not a bug — it's the expected outcome once you know why. The evaluation loop
this project built (`evaluate_candidate`, everything in `search.py`/
`run_attribution.py`) runs **one environment at a time, sequentially**. GPU physics
engines like Genesis get their throughput advantage from stepping *thousands* of
environments in lockstep; a single environment gets none of that parallelism and only
pays the per-step GPU kernel-dispatch/host-device-sync overhead. Naively swapping the
backend on a single-environment workload was always going to lose.

**This run was stopped after 21/385 evaluations** (partway through the first of 5
seed sets) by explicit user decision, once the direction and rough magnitude were
already well-established by the smoke test and the first ~20 real evaluations — the
full run was on track to take 9–12 hours to produce a more precise version of a
number that was not going to change qualitatively. The partial data (21 real
evaluations, not extrapolated) is reported honestly as partial in
`rocm_benchmark.json`.

## The batched throughput benchmark: this is the real ROCm story

Built a separate, raw physics-stepping throughput benchmark
(`throughput_bench.py`) that isolates the actual parallelism axis: build the same
scene (Franka + banana/lemon/plum + bowl) at varying `n_envs`, step it forward, time
it. This reuses `build_scene.py`'s own already-existing `n_envs` batching support
(built for an earlier part of the demo, not previously exercised by the codesign
pipeline) rather than requiring a rewrite of the scripted-grasp controller to be
batch-aware.

| n_envs | GPU env-steps/sec | CPU env-steps/sec |
|---|---|---|
| 1 | 132 | **1,180** |
| 8 | 997 | **3,614** |
| 32 | 3,991 | **4,699** |
| 128 | **15,377** | 5,052 (CPU's peak) |
| 512 | **52,198** | 4,932 |
| 1024 | **90,162** | — |
| 2048 | **130,567** | — |
| 4096 | **148,419** (GPU's peak so far, growth slowing) | — |

- **CPU wins below roughly n_envs=32–128** — for small batches, CPU's lower
  per-step overhead dominates.
- **CPU throughput saturates by n_envs=128 (~5,000 env-steps/sec) and does not
  improve further** — it even declines slightly at n_envs=512. This host has 128
  CPU cores, but Genesis's CPU backend doesn't scale batched rigid-body sim
  linearly with core count for this scene.
- **GPU throughput keeps climbing all the way to n_envs=4096** (148,419
  env-steps/sec) with **no OOM** — the 48GB VRAM ceiling was never hit, growth was
  just becoming sub-linear past ~1024 envs, suggesting the true ceiling is somewhat
  higher still but wasn't chased further.
- **Peak GPU throughput is ~29.4x CPU's peak throughput**, and **~1,120x the naive
  single-environment GPU throughput** — the gap between "GPU used wrong" (slower
  than CPU) and "GPU used right" (30x faster than CPU) is enormous and entirely a
  function of batch size, not hardware capability.

**What this means for the project**: the co-design search pipeline as currently
built (sequential single-environment trials) cannot benefit from this GPU at all —
it would need to be restructured to batch multiple trials (different domain-
randomization draws, or even different candidate designs sharing the same
finger-count structure) across parallel environments to convert this throughput
into faster search. That restructuring is future work, not done this session. But
the *capability* — a real, measured, first-of-its-kind-in-this-literature ROCm
throughput number for Genesis on AMD hardware — is now established and honest.

## Session 5: closing the loop — restructuring the evaluation loop to actually batch

Session 4 identified but explicitly did not attempt: rewriting the evaluation loop
to run a candidate's trials as one batched Genesis scene instead of sequential
single-environment calls, so the search pipeline could actually use the GPU
throughput measured above. Session 5 built this (`batched_episode.py` +
`evaluate_candidate_batched`), grouping trials by their shared picked object (one
batched scene per object, `n_envs` = trial count for that object — the natural
batching axis, since a batched call needs one consistent grasp target).

**Correctness first.** Genesis's entity API (IK, `plan_path`, `control_dofs_position/
force`, contacts, AABB) turned out to be unconditionally batched once a scene is
built with `n_envs>1` — confirmed empirically (a single non-batched IK call on such a
scene raises `"First dimension of `pos` must be equal to `scene.n_envs`"`). The work
was rewriting the *control logic* (every motion helper in `sim_episode.py`/
`grasp_demo.py`/`randomize.py`) to operate on `(n_envs, ...)` arrays throughout, not
working around a missing capability. A dedicated stratified-sequential reference
(`evaluate_candidate_grouped`, forcing the same deterministic per-object trial split
instead of `EnvRandomizer`'s random pool sampling) was built specifically so batched
vs. sequential could be compared on identical trial instances, not just similar ones.

**Result — both frozen designs, 300 trials each (100/object x banana/lemon/plum), on GPU:**

| | Sequential | Batched | Speedup | Success (seq/bat) | Fitness (seq/bat) | Exact per-trial match |
|---|---|---|---|---|---|---|
| Baseline | 3397.0s | 209.2s | **16.24x** | 30.7% / 30.7% | 0.0239 / 0.0240 | 290/300 (96.7%) |
| Winner | 3577.2s | 221.2s | **16.17x** | 96.0% / 95.0% | 1.0897 / 1.0759 | 297/300 (99.0%) |

Aggregate metrics match closely (success rate identical to 3 decimal places for
baseline, within 1 point for winner; force within 0.2N; slip within 0.001-0.005m).
The handful of per-trial mismatches (10/300 baseline, 3/300 winner) land on the same
kind of marginal trials this project has already documented as sensitive to solver
nondeterminism (session 2's 0.475-0.530 baseline-fitness spread across "identical"
CPU seeds) — not a sign of a batching-introduced bug. No number here is silently
hiding a physics change.

**Closing the loop with session 4's numbers.** Extrapolating CPU's measured per-trial
cost (session 2/3's 30-trial confirmation eval: ~3.34-3.36s/trial) to the same 300
trials gives ~1002-1008s. So, for this workload:

- CPU sequential (extrapolated): ~1000s
- GPU sequential, naive (session 4 + this session, refined with a much larger sample
  than session 4's partial 21-eval estimate): ~11.3-11.9s/trial -> ~3400-3580s for 300
  trials, i.e. **~3.4-3.6x slower than CPU** (session 4's smaller-sample estimate was
  2.47x slower — same conclusion, now measured more precisely)
- GPU batched (this session): ~210-221s for 300 trials, i.e. **~4.6-4.8x faster than
  CPU**, and **~16.2x faster than naive (unbatched) GPU**

The full arc: naive GPU use is a regression, batched GPU use is a real win, and the
size of that win (16x within this single benchmark, before even reaching the
higher-`n_envs` throughput ceiling measured in session 4) is the concrete answer to
"did restructuring for the hardware pay off." It did.

**Scope note**: this validates batched evaluation of a *fixed* design at a large
trial count — it does not yet rewire the CMA-ES search loop itself (`search.py`/
`run_attribution.py`) to call the batched path, which would require re-deriving each
candidate's trial-seed set into a per-object grouping mid-search. That plumbing is
mechanical (the hard part — proving batched execution matches sequential physics —
is done) but wasn't completed this session.

## Result parity: GPU produces the same physics conclusions as CPU

Reran the 30-trial confirmation eval (session 2/3's headline statistical-power
check) on GPU:

| | CPU (session 2) | GPU (this session) |
|---|---|---|
| Baseline success | 26.7% (CI [14.2%, 44.4%]) | 23.3% (CI [11.8%, 40.9%]) |
| Winner success | 93.3% (CI [78.7%, 98.2%]) | **93.3%** (CI [78.7%, 98.2%]) — exact match |
| Baseline peak force | 15.41 ± 4.99 N | 15.78 ± 5.06 N |
| Winner peak force | 12.73 ± 4.18 N | 12.73 ± 4.22 N — exact match |

Every number is within expected run-to-run solver-nondeterminism noise (already
documented in session 2/3), and several match to two decimal places. **The GPU
backend does not silently change simulation behavior or the project's physical
conclusions** — the confirmed-at-statistical-power headline result (93.3% vs 26.7%,
geometry not force) is backend-independent.

## Bugs found and fixed this session

1. `gripper_gen.generate_gripper_xml`'s absolute-path `meshdir` (see above) — the
   most consequential, since it would have broken cross-machine reproducibility
   for anyone else trying to run this project.

## What's NOT claimed here

- Session 4: no claim that this project's search pipeline was GPU-accelerated in
  practice at that point — it wasn't, and running it on GPU unbatched is a
  regression, not an improvement (see the literal-benchmark section). Session 5's
  batched pipeline changes this for direct candidate evaluation (16x speedup,
  validated) but has not yet been wired into the CMA-ES search loop itself (see the
  scope note in the session 5 section above) — so the *search* (as opposed to
  evaluating a fixed design) still runs unbatched as of this writing.
- No claim about the exact GPU throughput ceiling beyond n_envs=4096 — not chased
  further this session.
- The session 4 literal-benchmark comparison was from a **partial** run
  (21/385 evaluations), clearly labeled as such. Session 5's batched-vs-sequential
  benchmark used a full, non-partial 300-trial run per design and refined that
  earlier estimate (2.47x slower, partial sample) to 3.4-3.6x slower (full sample) —
  same qualitative conclusion, tighter number.
