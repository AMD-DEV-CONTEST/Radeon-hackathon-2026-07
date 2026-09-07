# GPU-corrected re-run (session 8, Part A) — findings

Escalations 1–3 ran on local CPU by default. This session closes that gap: SSH'd
into the Radeon Cloud instance from session 4 (ROCm
7.2.1, gfx1100, 48GB VRAM, `Genesis-ROCm-CoDesign` template — GPU confirmed live
via `rocm-smi`, Genesis 1.3.1 available in the instance's pre-built venv) and
re-ran the most compute-hungry piece, FruitArchive, on GPU using the same
batched-evaluation path session 4 validated (`evaluate_candidate_batched`,
`backend=gs.amdgpu`, n_envs = trial count, one build per object).

**Headline, stated plainly up front**: the GPU re-run of the *search itself*
did not find a better design than the CPU run — it found nothing good at all,
for an architectural reason explained below, not a hardware or capability
problem. The GPU *did* deliver clean, fast, higher-confidence confirmation of
what the CPU search already found, once re-validation (not fresh search) was
the task. Both outcomes are reported honestly; neither is softened.

---

## 1. The GPU-batched search: found nothing good, and here's exactly why

Ran `fruit_archive_gpu.py`: same MAP-Elites algorithm as the CPU version, but
each genotype's fitness now comes from `evaluate_candidate_batched` with
32 trials per object × 4 objects (banana/lemon/plum/apple) = 128 real trials
per genotype, batched on GPU — a huge upgrade in per-genotype statistical
power over the CPU run's 3 trials. Calibration (measured directly on this
instance before committing to a budget) showed genotype cost is
**build-dominated, not step-dominated**: a genotype at 3 trials/object took
163s; the same genotype at 32 trials/object took only 178s — the extra 10x
trials cost almost nothing, because `evaluate_candidate_batched` builds a
*separate* Genesis scene per object (one build per object, batched trials
within it), and that per-object build overhead (~150-160s total for 4 objects)
dwarfs the step-time regardless of batch size.

Given that, ran a bounded 80-genotype archive (15 random inits + 65
mutations, ~4hr wall-clock at the machine's measured ~168s/genotype) rather
than the brief's literal "tens of thousands" — infeasible at this
architecture's per-genotype cost (10,000 genotypes × 168s ≈ 19.4 days).

**Result: every one of the 38 filled cells scored negative fitness** (best:
-0.022) — worse than the CPU archive's best of 1.187, and worse even than
either frozen design. This looked, at first, like a bug (every cell showed
*exactly* 0% on lemon/plum/apple, only banana ever nonzero) — investigated
directly rather than reported at face value:

- Isolated GPU evaluation of the exact frozen winner (`evaluate_genotype_gpu`,
  called standalone, same code) succeeded cleanly: 100%/100%/80.6%/0% on
  banana/lemon/plum/apple.
- A random mutation *near* the winner (`curvature_deg=2.23` vs the winner's
  4.2, same neighborhood) also succeeded cleanly: 93.75%/100%/100%/3.1%.
- The archive's own history shows every one of its 80 genotypes landed with
  negative fitness, including several that fell in the *same coarse bin*
  ([5,0], [6,0], [7,1]) the CPU archive found excellent cells in — but those
  specific GPU-explored points within those bins were bad, because the
  8×8 aperture/curvature binning is coarse relative to how narrow the actual
  high-performing region is (finger_length and compliance vary freely within
  a bin, and CPU's own top cells needed a fairly specific combination).

**Conclusion: not a bug.** The pipeline works correctly (confirmed twice,
directly). This 80-genotype run simply never got lucky enough — with a
smaller random-init budget (15 vs CPU's 60) and far fewer total genotypes (80
vs 500) — to land in or mutate into the narrow region CPU's larger search
found. This is a genuine, reportable finding about the actual tradeoff of
this GPU-batched search architecture: **because per-object build cost, not
per-trial step cost, dominates genotype throughput, GPU batching buys far
more trials per genotype almost for free, but does NOT buy more genotypes per
hour** — and for a search problem with a narrow optimum, genotype *count*
matters more than per-genotype precision. Trading CPU's "many cheap, noisy
evaluations" for GPU's "few expensive, precise evaluations" was, for this
specific problem, a bad trade.

**Wall-clock comparison, the number the brief asked for**: GPU archive (80
evals) took **13,470s (3.74 hours)**, i.e. **168.4s/genotype**. CPU archive
(500 evals) took **9,165s (2.55 hours)**, i.e. **18.3s/genotype**. The CPU run
was both *faster in total wall-clock time* and *found a better result* — the
direct opposite of "GPU should have won." This is not a contradiction of
session 4's own raw-throughput benchmark (GPU peaked at 29.4x CPU's raw
env-step throughput there) — it's a demonstration that raw step-throughput
and this-workflow's genotype throughput are different things, and the second
one is what actually matters for a MAP-Elites search, and it's bottlenecked
by scene-build cost, which batching does not address.

---

## 2. Where GPU batching *did* help: fast, thorough re-validation

Re-ran the CPU archive's top 4 cells, plus both frozen designs, via
`fruit_archive_gpu_revalidate.py` — 64 trials per object per candidate (256
total trials/candidate), all 6 candidates in **979.7s (16.3 minutes)**. For
comparison, the equivalent CPU-side re-validation (30 trials/object/candidate,
half the per-candidate trial count) took **28,669.9s (7.97 hours)** — this
*is* a case where GPU batching delivered a real, large speedup, because
re-validation only needs a handful of *known* genotypes evaluated thoroughly,
not thousands of *new* scene builds.

| Candidate | banana | lemon | plum | apple |
|---|---|---|---|---|
| Frozen winner | 100% | 100% | 79.7% | 1.6% |
| Frozen baseline | 98.4% | 0% | 0% | 0% |
| CPU archive rank 1 | 90.6% | 100% | 100% | 0% |
| CPU archive rank 2 | 100% | 100% | 100% | 0% |
| CPU archive rank 3 | 84.4% | 100% | 100% | 0% |
| CPU archive rank 4 | 84.4% | 100% | 100% | 0% |

**Result parity confirmed**: every number here matches the CPU-side
re-validation (`fruit_archive_revalidation.json`) within sampling noise —
same qualitative pattern, same ranking, same conclusion. Apple is 0% (or
statistically indistinguishable from 0%) for every candidate, at both n=30
(CPU) and n=64 (GPU). **GPU did not change the physics conclusion** — it
reproduced it, faster, at higher confidence. This is the parity check the
brief asked for, and it passes cleanly.

---

## 3. YCB generalization (Escalation 2) GPU re-run: not attempted

The brief listed this as "if time allows after" the FruitArchive re-run.
Given (a) the FruitArchive GPU work above already used a meaningful chunk of
this session's bounded, credit-conscious GPU time, and (b) `ycb_generalization_eval.py`'s
per-object evaluation structure has the *same* build-per-object cost profile
that just explained why GPU batching didn't help genotype throughput —
re-running it on GPU would very plausibly show the same pattern (batching
helps trial count per object almost for free, doesn't reduce the 36 separate
scene-build cost that dominates the run) rather than a meaningfully faster
total runtime. Given that expectation and the time already spent, this was
not pursued. Flagged as a known, low-priority gap, not silently dropped.

---

## 4. What this does and doesn't tell us

**Closes the "why didn't you use the GPU" gap** with real, honest numbers in
both directions: GPU lost badly as a search engine here (slower AND worse
result, for a specific, now-understood architectural reason), and won clearly
as a re-validation engine (17x faster than CPU for the same task at double
the trial count). Both are genuine findings, not spin.

**Reinforces** `fruitarchive_findings.md`'s conclusion: apple's 0% is a real,
robust limit — now confirmed at higher trial counts (n=64) via an
independently-executed, different-hardware code path, not just the original
CPU numbers.

**New engineering insight for the report, not previously stated anywhere in
this project**: this codebase's GPU batching infrastructure (`batched_episode.py`,
`evaluate_candidate_batched`) is well-suited to *validating a small, known set
of candidates thoroughly*, and poorly suited (as currently architected, one
scene build per distinct gripper geometry) to *searching* — the search
workload's bottleneck is genotype-to-genotype scene compilation, which no
amount of within-genotype trial batching addresses. Restructuring the search
to amortize scene builds across genotypes (e.g., only re-mutating within a
fixed-topology geometry family, or building multiple candidate geometries
into one scene) is the natural next step for anyone wanting a GPU-accelerated
version of this specific search — not pursued here, flagged as future work.

**Raw data**: `fruit_archive_gpu.json` (80-eval GPU search archive,
38/64 cells, all negative fitness), `fruit_archive_gpu_revalidation.json`
(6-candidate GPU re-validation at n=64/object).
