# Confirmation runs + robustness pass — findings

Session 2 of the task-adaptive end-effector co-design work. Purpose: the prior
session's headline numbers (67% vs 100% success, 86%/14% geometry/controller
attribution split) came from small-N search trials (n=3 per candidate) and a single
trial-instance seed set. This session re-evaluates the *frozen* winning design at
statistical power, and reruns the attribution experiment across multiple seeds, before
any of these numbers go into a report.

CPU-only throughout (no ROCm GPU on this machine — Barcelo iGPU). No throughput claims
made anywhere in this document.

Frozen designs (unchanged from the prior session, not re-searched):
- **Baseline**: 2-finger, straight, rigid — `GripperParams(n_fingers=2, finger_length=0.0454, curvature_deg=0.0, aperture=0.08, compliance=0.0)`
- **Winner**: 3-finger, near-straight, wide aperture, moderate compliance — `GripperParams(n_fingers=3, finger_length=0.04618, curvature_deg=4.20, aperture=0.09122, compliance=0.234)`

---

## 1. Does the 100%-vs-67% gap hold up?

**Yes — and the corrected numbers are more dramatic, but the original point estimates
were wrong.** Re-evaluated both frozen designs over 30 fixed, paired trial instances
(seeds 1000–1029 winner, 1000–1029 baseline — same instance draws for both, so this is
a paired comparison) under the same domain randomization used throughout
(friction ratio 0.7–1.3, mass ratio 0.8–1.2).

| | n | successes | success rate | 95% Wilson CI | mean peak force | mean max slip |
|---|---|---|---|---|---|---|
| Baseline | 30 | 8 | **26.7%** | [14.2%, 44.4%] | 15.41 ± 4.99 N | 232 ± 200 mm |
| Winner | 30 | 28 | **93.3%** | [78.7%, 98.2%] | 12.73 ± 4.18 N | 20 ± 29 mm |

The 95% CIs **do not overlap** — the gap is statistically distinguishable at this N.

**Correction to flag explicitly**: the original small-N estimate (n=3) reported
baseline success at 67%. The true rate, at n=30, is **26.7%** — less than half the
originally-reported number. The winner's small-N estimate (100%) also came down
slightly, to 93.3%. Net effect: the *qualitative* story (winner dramatically
outperforms baseline) is confirmed and now statistically solid, but **the specific
67%/100% figures must not be used in any report** — replace with 26.7%/93.3%.

Slip is the most dramatic differentiator: baseline's 232mm mean slip with a 200mm
standard deviation reflects a design that is inconsistent, not just "sometimes fails
cleanly" — many baseline trials involve the object being flung or dropped at very
different distances, not a tight failure mode.

---

## 2. Force/slip sanity check — is the force difference physically meaningful?

Computed the actual simulated masses (not assumed real-world fruit mass) from the
bundled meshes at the sim's material density (`rho=300 kg/m^3` per `build_scene.py`):

| Object | Sim mass |
|---|---|
| banana | 51.5 g |
| lemon | 29.1 g |
| plum | 25.9 g |

(These are much lighter than real fruit — real lemons run ~100–150g — because the sim
uses a low, uniform density rather than fruit-realistic density. Worth noting if this
pipeline is ever compared against real hardware.)

**Worst-case required grip force** (heaviest object, banana, held against gravity +
peak transport acceleration ~10 m/s², per `grasp_demo.py`'s own tuning notes on
velocity-limited transport): **1.02 N**.

**Available support force**, modeled as `n_contacts x mu x peak_measured_force`
(mu=1.0, the sim's explicit friction coefficient for lemon/plum):

| Design | n_contacts | mean peak force | available support | margin over requirement |
|---|---|---|---|---|
| Baseline | 2 | 15.41 N | 30.8 N | **~30x** |
| Winner | 3 | 12.73 N | 38.2 N | **~37x** |

Even at one standard deviation below the mean peak force, both designs retain a
20–25x margin.

**Conclusion**: the ~2.7N (18% relative) difference in mean peak force between designs
is **not a threshold effect**. Both designs grip far harder than physically necessary
to support these lightweight objects — neither is "barely holding on." The success-rate
gap (93.3% vs 26.7%) is therefore not explained by the winner using "just enough more
force" — it's explained by contact geometry: 3 distributed contact points resist
rotation/slip within the grip in a way that 2 opposing points don't, independent of how
hard either design squeezes. This is consistent with what the attribution experiment
found (below): geometry, not force, is doing the work.

---

## 3. Does the 86%/14% attribution split hold up across seeds?

**Directionally yes — geometry is the majority contributor in every single seed — but
the exact 86/14 point estimate does not hold up; the true split is wider and noisier
than one seed suggested.** Reran the full 4-arm experiment
(`run_attribution_multiseed.py`) across 5 independent trial-instance seed sets, each
with its own CMA-ES optimizer seed too (so both "which tasks got evaluated" and "what
the search happened to find" vary), at the same per-arm budget used for the original
86/14 result (geometry: population=5, generations=5, both finger counts; controller:
population=5, generations=5).

| Seed set | Baseline success | Geometry-only success | Controller-only success | Joint success | Geometry share |
|---|---|---|---|---|---|
| 1 (100–102) | 66.7% | 100% | 66.7% | 100% | 92.4% |
| 2 (200–202) | 33.3% | 100% | 33.3% | 100% | 93.5% |
| 3 (300–302) | 66.7% | 100% | 100% | 100% | 51.5% |
| 4 (400–402) | 0.0% | 66.7% | 0.0% | 100% | 89.1% |
| 5 (500–502) | 33.3% | 100% | 66.7% | 100% | 74.8% |
| **mean ± std** | **40.0% ± 27.9%** | **93.3% ± 14.9%** | **53.3% ± 38.0%** | **100.0% ± 0.0%** | **80.3% ± 17.7%** |

Geometry share ranges from **51.5% to 93.5%** across seeds — never the minority
contributor, but the margin over controller varies by nearly 2x depending on the
seed draw. **Controller share: 19.7% ± 17.7%** (mean, not 14%). The interaction term
is noisy and should not be over-read seed-by-seed (mean −0.041, but individual values
range from −0.416 to +0.789 — it's a difference-of-differences computed from small
per-candidate trial counts during search, so it inherits a lot of variance; the
population mean near zero, i.e. roughly additive with no dramatic synergy either way,
is the only defensible reading).

**The most striking number in this table isn't the split — it's the joint row.** The
frozen winning design hit **100% success in all 5 seed sets**, with essentially zero
fitness variance across them (std 0.036 vs. baseline's 0.437). Baseline's success rate,
by contrast, swings wildly with the seed draw (0% to 66.7%) — it is not just worse on
average, it is *unreliable* in a way the winning design is not. That reliability gap is
arguably a stronger practical claim than the point-estimate attribution split.

**Correction to flag**: the original single-seed 86%/14% split is within the observed
range (seed 1's 92.4%/7.6% is close to it) but should not be reported as *the* number.
Report the 5-seed mean ± std (80.3% ± 17.7% geometry, 19.7% ± 17.7% controller), or the
full per-seed table, not a single point estimate.

---

## 4. Did controller-only tuning ever beat baseline's success ceiling?

**Yes, in 2 of 5 seeds — this is a real, seed-dependent effect, not noise in one
direction.** Reported per seed, not averaged, per the explicit instruction not to
soften this into a percentage:

| Seed set | Baseline success | Controller-only success | Outcome |
|---|---|---|---|
| 1 (100–102) | 66.7% | 66.7% | **tied** |
| 2 (200–202) | 33.3% | 33.3% | **tied** |
| 3 (300–302) | 66.7% | 100% | **exceeded** |
| 4 (400–402) | 0.0% | 0.0% | **tied** (both total failures) |
| 5 (500–502) | 33.3% | 66.7% | **exceeded** |

Controller-only tuning **never performed worse than baseline** in any seed, but it only
*exceeded* baseline's success ceiling in 2/5 seeds (300–302 and 500–502) — in the other
3 it matched baseline exactly, including the seed 4 case where both totally failed
(0%). When it did exceed the ceiling, it still never matched geometry-only or joint's
consistent 100%. **The precise claim**: controller tuning alone can occasionally break
past the fixed-geometry's failure ceiling depending on which task instances it's
evaluated against, but it does so unreliably and never reaches the ceiling-breaking
consistency that changing the geometry does (geometry-only hit 100% in 4/5 seeds and
66.7% in the fifth — never tied or lost to baseline in any seed). Geometry is not just
usually better than controller tuning here — it is *reliably* better, where controller
tuning is only *sometimes* better.

---

## Infra note (not a result, but affects how to read the above)

This session's host (a physical laptop, not a cloud sandbox) rebooted twice mid-run
during the first attempts at the 5-seed job, apparently from a suspend/resume failure
under sustained ~175-200% CPU load. One of those interrupted runs also exposed a real
bug: `gripper_gen.generate_gripper_xml` cached generated MJCF files by existence alone,
so a write killed mid-flight left a 0-byte file that later runs kept trying to parse
and crashing on. Fixed with an atomic write (temp file + `os.replace`); the 3 corrupted
cache files were removed. The final 5-seed run (this document's numbers) completed
cleanly end-to-end after that fix, took ~2h35m wall-clock, and its
`../02_attribution_multiseed/attribution_multiseed.json` checkpoints after each seed set.

---

## Known limitations of this confirmation pass

- Single physics backend (Genesis CPU), no cross-validation against a second simulator.
- Domain randomization ranges (friction 0.7–1.3x, mass 0.8–1.2x) are the same ones used
  throughout this project, not independently chosen for this robustness pass — a design
  that overfits to *this* DR range would not be caught here.
- Solver nondeterminism is real (see prior session's 0.475–0.530 baseline-fitness
  spread at identical seeds) — the paired-seed, 30-trial, non-overlapping-CI result
  above is the correct way to average that out, but individual trial outcomes near the
  success/failure boundary should still be read as noisy.
- Object pool is 3 fruits (banana, lemon, plum) from the stock demo's reliable-pick
  pool — no claim is made about generalization to other object shapes/materials.
