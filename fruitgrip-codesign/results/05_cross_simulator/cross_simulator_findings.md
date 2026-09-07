# Cross-simulator replication (MuJoCo) — findings

Session 7 of the task-adaptive end-effector co-design work. Purpose: every prior
result in this project (search, attribution, generalization) ran on one physics
engine (Genesis, CPU backend). This session independently re-evaluates the two
*already-frozen* designs — no re-searching — in MuJoCo, an architecturally different
engine, to check whether the headline finding (winner beats baseline; the mechanism
is contact geometry, not squeeze force) survives a change of physics backend, or was
partly an artifact of Genesis's specific contact/solver behavior.

Frozen designs (byte-identical `GripperParams` to every prior session, not re-derived):
- **Baseline**: 2-finger, straight, rigid — `n_fingers=2, finger_length=0.0454, curvature_deg=0.0, aperture=0.08, compliance=0.0`
- **Winner**: 3-finger, near-straight, wide aperture, moderate compliance — `n_fingers=3, finger_length=0.04618, curvature_deg=4.20, aperture=0.09122, compliance=0.234`

Both the geometry (MJCF) and the scripted controller's decision logic (grasp height
formula, per-object yaw/force co-adaptation) are ports of the exact Genesis-side code
— not reimplementations from a spec. No physics parameter (friction value, solver
iterations, contact stiffness) was tuned to make MuJoCo's result resemble Genesis's;
where MuJoCo needed its own defaults (contact solver, friction cone) they were left
at MuJoCo's stock values.

**Headline: the result does not replicate.** On the two round objects (lemon, plum)
where the ported controller works reliably, MuJoCo shows baseline *outperforming* the
winner — the opposite direction of Genesis's 26.7%-vs-93.3% result. Details, and the
project's best diagnosis of why, follow below.

---

## 1. Setup: what carried over vs. what didn't

**MJCF portability — fully confirmed.** `gripper_gen.py`'s generated XML is 100%
standard MJCF (essentially the MuJoCo Menagerie Franka Panda, with a generated finger
subtree appended); MuJoCo loads it directly with zero Genesis-specific extensions to
strip.

**What did NOT carry over automatically, and had to be added:**
- **Base mounting.** Genesis applies `FRANKA_POS`/`FRANKA_EULER` as an entity-level
  transform at `scene.add_entity()` time — outside the MJCF file. The raw MJCF's
  `link0` has no `pos` (defaults to world origin). Naively reusing the file left the
  whole robot floating at the origin instead of mounted on the table, with the arm's
  home pose already penetrating the tabletop by up to 7cm before any motion. Fixed by
  setting `link0`'s `pos` explicitly in `scene_builder.py`.
- **Self-collision filtering.** Genesis auto-excludes geometry pairs that inherently
  overlap at the neutral pose (its own logs: *"Filtered out geometry pairs causing
  self-collision for the neutral configuration"*). MuJoCo has no equivalent. Handled
  via an explicit `contype`/`conaffinity` bitmask scheme that disables Franka-internal
  collision while preserving Franka-vs-scene and scene-vs-scene collision.
- **Mesh format.** This MuJoCo build has no PLY decoder; YCB `collision.ply` files
  were converted to `.obj` once via `trimesh` (cached).
- **Per-finger direct control.** Both engines bypass the stock tendon-coupled gripper
  actuator in favor of direct per-joint control (`gripper_gen.py`'s own comment notes
  Genesis does this too) — the MJCF's stock tendon actuator was removed and replaced
  with one explicit `<position>` actuator per finger joint (with an explicit
  `ctrlrange` — `<compiler autolimits="true">` otherwise silently clamps an
  unspecified-range actuator's `ctrl` to `[0,0]`).

**Documented controller-implementation deviations** (decisions about *how the ported
controller drives the arm*, not physics — none chosen to push the outcome toward or
away from Genesis's numbers):
1. **Pregrasp clearance**: 0.10m here vs Genesis's 0.18m. This IK solver (damped
   least-squares, no motion planner) converges to sub-mm accuracy at 0.10m but hits a
   genuine position/orientation conflict at 0.18m for a strict top-down grasp,
   confirmed by position-only IK converging to ~1e-16 error at the same point where
   the combined problem plateaus.
2. **Two-stage approach** (move to a safe height above the whole scene, then descend
   onto the pregrasp point) rather than one straight joint-space interpolation from
   home. A single interpolation swept the arm's mid-links through the tabletop —
   MuJoCo has no equivalent to Genesis's collision-aware `plan_path()`.
3. **Grasp-height formula, non-center-align (elongated) objects**: Genesis's own
   formula for this branch (`sim_episode._grasp_hand_z`) returns the object's-top
   height directly, without the `hand_to_fingertip` offset its own center-align
   branch uses. Ported verbatim, this commands the fingertip ~10cm *below* the
   object's actual top surface — for the banana (only ~3.8cm tall lying on its
   side), that lands ~6cm into the table, and MuJoCo's stiffer contact solver blocks
   the descent outright (Genesis's own confirmation-eval results show banana
   succeeding 8/9 and 9/9 for baseline/winner despite the identical formula, most
   likely because its contact resolution doesn't hard-block a partially-invalid
   target the way MuJoCo's does). Unified both branches to target the same
   "dip partway from the object's vertical center" fingertip position. This
   materially changed banana's *reachability* but, as below, did not fix its
   grasp *stability* — see §3.

None of these are physics tuning; all three are documented in `controller.py`'s and
`ik.py`'s own module docstrings, at the exact code locations they apply.

---

## 2. Confirmation eval: 30 paired trials, same DR ranges as Genesis

Same protocol as `confirmation_eval.py`: friction ratio 0.7–1.3x, mass ratio
0.8–1.2x, object pool `{banana, lemon, plum}`, pose jitter ±3cm / ±30°, seeds
1000–1029, paired (same seed set for both designs). MuJoCo's own RNG draws, not a
replay of Genesis's — same protocol/ranges, not a bit-identical trial stream (not
meaningful across engines).

| | n | successes | success rate | 95% Wilson CI | mean peak force | mean max slip |
|---|---|---|---|---|---|---|
| Baseline | 30 | 20 | **66.7%** | [48.8%, 80.8%] | 15.12 ± 9.96 N | 96 ± 130 mm |
| Winner | 30 | 16 | **53.3%** | [36.1%, 69.8%] | 16.88 ± 5.70 N | 96 ± 126 mm |

CIs **overlap** — at this N the two designs are not statistically distinguishable,
and the point estimate favors the *baseline*. This is already a clear divergence from
Genesis's non-overlapping 26.7%-vs-93.3% gap in the winner's favor.

Per-object breakdown makes the picture much clearer:

| Object | Baseline | Winner |
|---|---|---|
| 014_lemon | 12/12 (100%) | 9/12 (75%) |
| 018_plum | 8/8 (100%) | 7/8 (88%) |
| 011_banana | 0/10 (0%) | 0/10 (0%) |

---

## 3. Banana: a controller-port limitation, not a design-comparison confound

Banana fails **100% of the time for both designs** — not stochastic variance, and not
biased toward one design over the other. Traced in detail: after the height-formula
fix (§1.3), the arm reaches the banana and the fingers do make real contact (peak
forces 20–30N, well above the round-object grip forces) — but the object is
consistently left behind on the table during the lift phase, with the fingers closing
to near-zero as if gripping empty air. The most likely cause: the banana's tapered,
non-symmetric cross-section under a straight top-down 2-or-3-point squeeze pinches
unevenly (visible as a lateral shift and a ~2cm vertical settle *during the close
phase itself*, before lift even starts) — a failure mode Genesis's scripted controller
apparently avoids (its own results: 8/9 and 9/9), plausibly because of a softer
contact response that tolerates an imperfectly-centered squeeze without popping the
object free.

Because this affects both designs identically (0/10 each), it does not bias the
baseline-vs-winner comparison — but it does mean this replication cannot speak to
banana at all. The round-object result (lemon/plum, both designs working reliably,
100%+ contact uptime on every successful trial) is the part of this report that
actually carries evidence.

---

## 4. Does the force-margin mechanism hold?

Recomputed in MuJoCo's own units (uniform friction μ=1.0, per `scene_builder.py`;
sim masses from `body_mass` at nominal density, rho=300 kg/m³ — matching Genesis's
material exactly):

| Object | Sim mass (MuJoCo) | Sim mass (Genesis, for reference) |
|---|---|---|
| banana | 70.1 g | 51.5 g |
| lemon | 31.4 g | 29.1 g |
| plum | 29.5 g | 25.9 g |

(Masses are close but not identical — expected, since MuJoCo auto-hulls each YCB
mesh to a single convex geom for volume/mass purposes, a different mesh-processing
path than Genesis's, not a parameter either engine's mass computation was tuned to
match.)

**Worst-case required grip force** (heaviest object, banana, held against gravity +
peak transport acceleration ~10 m/s², same conservative assumption `findings.md`
used): 0.0701 × (9.81 + 10) = **1.39 N**.

**Available support force** (`n_contacts × μ × mean peak force`, restricted to the
round-object trials — banana's own force readings reflect an unstable grip, not a
valid steady-state number):

| Design | n_contacts | mean peak force (lemon+plum) | available support | margin |
|---|---|---|---|---|
| Baseline | 2 | 10.18 N | 20.4 N | **~15x** |
| Winner | 3 | 13.48 N | 40.4 N | **~29x** |

Both margins are enormous — force is not the bottleneck for either design in MuJoCo
either, exactly as in Genesis. This matters: it means the reversed success-rate
result in §2 is **not** explained by "the winner squeezes harder" (findings.md
already ruled this direction out) nor by "the baseline is under-powered" (this
section rules that out too). Whatever is driving baseline's advantage here is a
grip-*stability* effect, not a grip-*strength* effect — consistent with the original
project's "geometry, not force" framing as the right lens, just landing on the
opposite empirical answer about which geometry wins.

---

## 5. Diagnosis: why would the direction reverse?

**Update (same session, follow-up diagnostic): the per-finger-onset-timing
hypothesis below was tested directly and is refuted.** The original version of
this section speculated that the winner's failures were caused by its 3 fingers
not engaging the object simultaneously — a plausible-sounding mechanism, but
inferred from *aggregate* uptime/slip numbers, never actually measured. New
instrumentation (`mujoco_repl/finger_diag.py` and `finger_contact_diag.py`, same
methodology in both engines: log each finger's first-contact step and total
contact-steps) was added and run on 60 fresh trials per engine (winner design,
lemon+plum only, same DR ranges, seeds 2000–2059):

| | success rate | all fingers ever engaged | onset spread, success trials | onset spread, failure trials |
|---|---|---|---|---|
| MuJoCo | 50/60 (83%) | 60/60 | 5.0 steps (n=50) | 4.9 steps (n=10) |
| Genesis | 56/60 (93%) | 60/60 | 2.4 steps (n=56) | 0.5 steps (n=4) |

**The hypothesis does not hold in either engine.** All three fingers engage the
object in *every single trial*, in both engines — there is no case of a finger
never making contact. Onset spread (the gap between the first and last finger's
first-contact step) is small in both engines and, critically, is **not
elevated in failure trials** — if anything it's *smaller* in Genesis's failures
(0.5 vs 2.4 steps) and statistically indistinguishable in MuJoCo's (4.9 vs 5.0
steps). Per-finger contact-hold duration (`contact_steps`) is also essentially
equal across all 3 fingers within every trial, in both engines — no finger
systematically drops out early while the others continue. Whatever is causing
the winner's MuJoCo failures, it is not asymmetric or delayed multi-finger
engagement. That earlier paragraph's specific causal claim is withdrawn.

**What the new data points to instead — and this part IS now confirmed on both
sides.** Splitting the 60 MuJoCo trials by outcome shows a clean split on the
*domain-randomization friction draw*: all 10 failures occurred at friction ratio
≥ 1.06 (mean 1.21), while the 50 successes span the entire 0.7–1.3 range (mean
0.92). A follow-up patch exposed the same value on the Genesis side — a minimal,
non-invasive addition (`EnvRandomizer.last_friction_ratio`, `randomize.py`) that
records the ratio `_randomize_dynamics` already samples every reset, changing
nothing about what is sampled or how — and re-running the identical 60-trial
Genesis diagnostic with this logged shows the same pattern: **all 4 Genesis
failures occurred at friction ratio ≥ 1.24 (values: 1.24, 1.25, 1.26, 1.30, mean
1.26), while the 56 successes span the full 0.70–1.26 range (mean 0.95).**

This is a genuine, confirmed, cross-simulator-consistent finding: in both
engines, the winner design's failures cluster at the *high* end of the sampled
friction range, not the low end — the opposite of the naive expectation that
more friction should mean a more secure grip. Whatever mechanism produces this
(plausibly: higher friction impeding the fingers' ability to settle into a
symmetric, well-seated contact during the close phase, leaving a geometrically
worse grip that's more failure-prone under the SAME squeeze force, independent
of onset timing) is present in both physics engines, using the identical
scripted controller. It is evidence *against* "this is purely a MuJoCo contact-
solver artifact" and evidence *for* "this is a real sensitivity of the winner
design's specific grasp geometry to friction, that Genesis's own protocol (DR
range 0.7–1.3x) already samples into often enough to show up as ~7% of its
trials, and that MuJoCo's own DR sampling this session (or a different overall
episode count/seed set) simply exposed more severely."

One further observation, offered without over-interpreting samples of 4 and 10:
the two engines' failures still don't look identical in *character* — Genesis's
4 show near-perfectly synchronized onset and near-full contact-hold duration
throughout (206–220 of ~220 steps, i.e. a grip that was held steadily, not lost),
more consistent with a placement-precision near-miss than a dropped grip; MuJoCo's
10 show partial contact-hold (75–91% uptime) consistent with an actual grip loss
mid-episode. So the *shared* friction-sensitivity is confirmed, but it may not be
manifesting as exactly the same downstream failure mode in each engine.

**Honest bottom line for this section**: the reversal in §2 remains real and is
not explained by grip force (§4) or by asymmetric contact onset (tested and ruled
out, both engines). It IS accompanied by a confirmed, shared friction-sensitivity
in the winner design present in both engines — the clearest, most reproducible
signal this investigation found, even though it does not by itself explain why
MuJoCo's overall success rate for the winner sits so much lower than Genesis's.
Per this session's scope, this is the final diagnostic pass on this question;
further mechanism-isolation (e.g. why high friction produces a worse seated grip)
is out of scope here and left for a future session.

---

## 6. What this does and doesn't tell us

**Does not confirm** the original finding. The core empirical claim of this
project — that the searched 3-finger design reliably outperforms the 2-finger
baseline — does not hold up under a straightforward, non-tuned replication in a
second physics engine. On the subset of objects this replication can actually speak
to (lemon, plum), the direction is reversed and the gap is not statistically
significant either way.

**Rules out** a narrow class of Genesis-specific artifacts: the underlying gripper
geometry and MJCF are not malformed or Genesis-only constructs (they load and run
natively in MuJoCo), and the force-margin mechanism check confirms grip force itself
was never the limiting factor in either engine.

**Does not rule out, and actively suggests**: the original 93.3%-vs-26.7% gap may be
partly attributable to Genesis's specific contact-solver behavior (compliance,
friction-cone approximation, or self-collision handling) interacting with this
particular scripted controller, rather than being a property of the gripper geometry
alone. That is a materially different, more cautious claim than "the winning design
generalizes across physics engines" — and it's the honest one this session's evidence
supports.

**Does not substitute for physical hardware validation.** Two simulators disagreeing
on direction is itself evidence that neither should be treated as ground truth for
this specific comparison without a real-world check.

**Recommendation for the writeup**: report the original Genesis result as validated
*within Genesis, at statistical power, across seeds and held-out objects* (sessions
2–3's findings stand on their own), but explicitly flag — as this project has done at
every prior stage when a result didn't hold up — that the cross-simulator check in
this session did not replicate the geometry-search advantage, and describe why. This
is a limitation worth stating plainly in the submission, not a result to omit.

**Follow-up closed**: the friction-ratio question above (originally left open) was
checked in a bounded follow-up pass via a minimal, non-invasive addition
(`EnvRandomizer.last_friction_ratio` in `randomize.py`, exposing a value the
randomizer already computed) — Genesis's failures cluster at high friction too
(§5). This was the last diagnostic pass scoped for this cross-simulator
investigation; further mechanism work is future-session territory, not continued
here.

**Raw data**: `cross_simulator_confirmation_eval.json` (§2's 30-trial run),
`finger_contact_timing_mujoco.json` and `finger_contact_timing_genesis.json`
(§5's 60-trial per-finger diagnostic, both engines, same seeds/protocol).
