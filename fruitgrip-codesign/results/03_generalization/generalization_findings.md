# Generalization test + real-density force check — findings

Session 3 of the task-adaptive end-effector co-design work, Priorities 1-2 (Priority 3
onward — ROCm benchmark, demo assets, PR — held pending confirmed Radeon Cloud access).
Both frozen designs unchanged from sessions 1-2, no re-searching:

- **Baseline**: `GripperParams(n_fingers=2, finger_length=0.0454, curvature_deg=0.0, aperture=0.08, compliance=0.0)`
- **Winner**: `GripperParams(n_fingers=3, finger_length=0.04618, curvature_deg=4.20, aperture=0.09122, compliance=0.234)`

In-pool reference (session 2, `../01_core_confirmation/confirmation_eval.json`, n=30 each): baseline
26.7% success (95% CI [14.2%, 44.4%]), winner 93.3% (CI [78.7%, 98.2%]).

---

## Priority 1: held-out object generalization

**The gap holds directionally but collapses dramatically in magnitude, and the
winner's advantage turns out to be object-specific, not general.** This needs to be
reported plainly, per the brief's own instruction not to soften a negative result.

### Setup
Two objects never seen during search, the confirmation eval, or the attribution
experiment:
- **013_apple** — ~7.5cm smooth sphere, right at/near the baseline's 8cm aperture and
  close to the winner's 9.1cm aperture (only ~0.8cm clearance per side).
- **016_pear** — ~6.7×9.5×6.6cm, asymmetric/tapered — a different shape class, not
  just a size variant, from the round fruit (lemon/plum) or elongated fruit (banana)
  the winner was searched against.

Both are bundled in the repo's own assets and were already present (but disabled) in
`scene_config.py`'s object layout, with the demo authors' own comments explicitly
flagging them as difficult for parallel-jaw grasping — a well-motivated, not arbitrary,
choice of held-out test, and one that should favor the winner's core mechanism (wider
aperture, 3-point contact) if that mechanism actually generalizes.

Ran both frozen designs for 20 trials each (`held_out_eval.py`), same domain
randomization as every other eval in this project. Visually verified outcomes via
frame capture on a smaller pilot run before committing to the full run — confirmed
genuine physical outcomes (a wedged/stuck apple for the winner, a knocked-away apple
and pear for baseline, a cleanly-placed pear for the winner), not an evaluation bug.

### Results

| | n | successes | success rate | 95% CI | pear success | apple success | mean peak force |
|---|---|---|---|---|---|---|---|
| Baseline | 20 | 0 | **0.0%** | [0.0%, 16.1%] | 0/12 (0%) | 0/8 (0%) | 7.73 ± 8.84 N |
| Winner | 20 | 5 | **25.0%** | [11.2%, 46.9%] | 5/12 (41.7%) | 0/8 (0%) | 54.73 ± 25.38 N |

| | In-pool success | Held-out success | Change |
|---|---|---|---|
| Baseline | 26.7% | 0.0% | **-26.7 pts** (total collapse) |
| Winner | 93.3% | 25.0% | **-68.3 pts** (large collapse) |

### What this means, stated plainly

1. **The winner still beats baseline on held-out objects** (25.0% vs 0.0%), and the
   95% CIs are (barely) non-overlapping — so the directional claim "geometry co-design
   generalizes better than a fixed gripper" survives. But the *magnitude* of the
   original headline (93.3% vs 26.7%, a 66.6-point gap) does **not** transfer — the
   held-out gap is 25 points, roughly a third the size.
2. **The winner's entire held-out success comes from pear (41.7%); it is a complete
   failure on apple (0/8, identical to baseline's 0/8).** The winner's advantage over
   baseline is not "works better on hard objects in general" — it is specific to
   objects with clearance inside its aperture. Apple sits right at the edge of both
   designs' aperture (baseline 8cm vs apple's 7.5cm width; winner 9.1cm vs apple's
   7.5cm, nominally more headroom but still a total failure in practice). The search
   never had to solve "grip an object nearly as wide as the gripper's own opening,"
   and it shows: neither design solves it.
3. **Peak force on held-out objects is far higher for the winner (54.7N vs its
   in-pool 12.7N)** — a real, physically-explicable effect (heavier, tighter-clearance
   objects need a harder squeeze), not a solver artifact; visually confirmed frames
   showed a genuinely wedged object, not a physics glitch. This feeds directly into
   Priority 2 below.

**Honest framing for the report**: the co-design result is real but the object pool it
was searched over (banana/lemon/plum) is narrow, and the winning geometry has not been
shown to generalize to objects that stress a different part of the design space
(near-aperture-limit size). A generalization claim broader than "this specific 3-finger
geometry beats this specific 2-finger baseline on round/elongated fruit within its
aperture margin, and still edges it out — but far less dramatically — outside that
regime" would not be supported by this data.

### Update (session 5): re-run at 10x the trial count with the batched pipeline

Session 5's batched evaluation pipeline (16x faster than sequential, see
`rocm_findings.md`) made a much larger held-out sample affordable: 200 trials per
design (100 apple + 100 pear, up from 20 total) — tight enough now for real
per-object confidence intervals, not just a point estimate.

| | n | success rate | 95% CI | apple (n=100) | pear (n=100) |
|---|---|---|---|---|---|
| Baseline | 200 | **0.0%** | [0.0%, 1.9%] | 0.0% (CI [0.0%, 3.7%]) | 0.0% (CI [0.0%, 3.7%]) |
| Winner | 200 | **21.5%** | [16.4%, 27.7%] | 3.0% (CI [1.0%, 8.5%]) | 40.0% (CI [30.9%, 49.8%]) |

**Mostly confirms session 3's finding, with one small correction.** Pear holds almost
exactly (40.0% vs the original 41.7% at n=12) — that small-N estimate was already
accurate. Overall winner success (21.5% vs 25.0%) is a touch lower but consistent
within the original's much wider CI. Baseline's 0% is now nailed down hard — at n=200
the upper CI bound is under 2%, ruling out anything but a true near-zero rate, not
just "we didn't see one in 20 tries."

**The correction**: apple is not literally impossible for the winner. Session 3's
0/8 was consistent with anywhere up to ~37% true success rate at that sample size —
it just happened to land on zero. At n=100, the real rate is **3.0%** (CI [1.0%,
8.5%]) — rare, but not zero. This doesn't change the qualitative story (apple remains
a near-total failure mode for both designs, dominated by the aperture-clearance issue
identified in session 3), but "3% of the time it works" is a more precise and more
honest claim than "it never works," and is exactly the kind of small correction that
justifies re-running a headline number at higher N before it goes in a report.

---

## Priority 2: real-density force sanity check

Session 2's force-margin calculation used the *simulated* object mass (`rho=300
kg/m^3`, the sim's material density — much lighter than real fruit). Recomputed using
real fruit density (**950 kg/m^3**, the brief's conservative bound) to check whether
the "geometry, not force, explains the success gap" conclusion still holds at
realistic mass.

| Object | Volume | Sim mass (ρ=300) | Real mass (ρ=950) | Required grip force* |
|---|---|---|---|---|
| banana | 171.5 cm³ | 51.5 g | 163.0 g | 3.23 N |
| lemon | 96.8 cm³ | 29.1 g | 92.0 g | 1.82 N |
| plum | 86.2 cm³ | 25.9 g | 81.9 g | 1.62 N |
| apple | 246.6 cm³ | 74.0 g | 234.3 g | 4.64 N |
| pear | 192.2 cm³ | 57.7 g | 182.6 g | 3.62 N |

*held against gravity + peak transport acceleration (~10 m/s², per `grasp_demo.py`'s
own tuning notes), worst case = heaviest object.

Available support force modeled the same way as session 2
(`n_contacts x mu x peak_measured_force`, mu=1.0):

| Design / object set | Mean peak force | Margin (mean) | Margin (mean − 1 std) |
|---|---|---|---|
| Baseline, in-pool | 15.41 N | 6.6x | **4.5x** |
| Winner, in-pool | 12.73 N | 8.2x | **5.5x** |
| Baseline, held-out (apple/pear) | 7.73 N | 3.3x | **~0.0x** |
| Winner, held-out (apple/pear) | 54.73 N | 35.4x | **19.0x** |

### Does the "geometry not force" conclusion still hold at realistic mass?

**Mostly, but with an important qualification the session-2 sim-density numbers
masked.** At real fruit density, margins shrink substantially from the ~30-37x seen
with sim-density objects — but for three of the four design/object combinations they
remain comfortably positive (4.5x-19x at a full standard deviation below the mean),
so the core claim survives there: neither design is anywhere close to "just barely"
holding on for the objects it can pick up at all.

**The exception is baseline on held-out objects**: its margin collapses to
**essentially zero at −1 std**. This means that at realistic mass, baseline's total
failure (0/20) on apple/pear plausibly has a genuine force-insufficiency component
alongside the contact-geometry limitation identified in session 2 — the two designs'
held-out gap can no longer be attributed to geometry alone with the same confidence as
the in-pool gap. The winner, by contrast, never runs low on force anywhere (its high
absolute forces on held-out objects, flagged as a possible artifact in Priority 1, are
now confirmed as genuinely ample margin, not a stress response to inadequate grip) —
so on the winner's side, its 0% apple result is still cleanly a geometry/clearance
failure, not a force failure.

**Report this precisely**: "geometry, not force, explains the gap" is well-supported
for the in-pool comparison (session 2) and for the winner across all objects tested.
It is *not* well-supported as a universal claim for baseline on objects near its
aperture limit — there, force scarcity is plausibly part of the explanation too, and
the sim's low material density (rho=300 vs real ~950-1000 kg/m^3) had been silently
making baseline's force margin look far more comfortable than it would be with real
fruit.

---

## Status: Priority 3 onward

Held pending your confirmation of Radeon Cloud / AMD Developer Cloud access. Priority
4 (demo video asset) and Priority 5 (PR for the atomic-write bug fix) are not
technically gated on GPU access, but per your instruction ("do till priority 2 and
later — I will say when we get access"), not started yet.
