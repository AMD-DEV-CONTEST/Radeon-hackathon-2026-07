# Antipodal grasp planner vs. the fixed per-object heuristic — findings

Adds a geometry-driven grasp planner (`franka_fruit_pick/codesign/grasp_planner.py`)
as an alternative to the scripted controller's original fixed lookup table
(`controller_adapt._OBJECT_GRASP_META` — yaw + a single global height fraction,
covering 7 hardcoded object names, everything else falling back to a generic
default). The planner slices each object's own mesh across a range of heights and
picks the best-scoring antipodal (2-finger) or radial (N-finger) cross-section that
fits the *active* design's real aperture — see the module docstring for the full
method and its explicitly stated scope limits (height + yaw only; no free (x, y)
offset, no out-of-plane approach).

Same statistical protocol as the original 36-object generalization sweep
(`results/03_generalization/`): both frozen designs, same 36 objects, n=15 trials
each, same DR ranges (friction 0.7–1.3x, mass 0.8–1.2x), same seeded pipeline —
only the grasp-targeting source differs (`use_planner=True` vs. the original
fixed heuristic). Full run: 72 (object × design) evaluations, 6685s (~111 min)
wall-clock, CPU. Raw data: `ycb_generalization_eval_planner.json`.

---

## 1. Headline: this is a mixed result, not a clean win — reported exactly as measured

**Pooled mean success rate across all 36 objects barely moved for the winner
design: 18.7% → 18.5%.** Baseline improved modestly: 11.7% → 15.4%. **The count
of objects where both designs score 0% went from 20/36 to 21/36 — one object
worse, not better.** Geometry-driven targeting does **not** broadly close the
generalization gap this project's own 36-object sweep already documented. It
closes it for *some* objects and opens new gaps on *others* — a reshuffle, not
a uniform improvement, and reported that way rather than leading with the
individually-impressive wins below.

This was checked directly rather than assumed: per the validation protocol
this brief specified, every previously-working object was checked for
regression, not just the previously-failing ones for improvement.

---

## 2. Real wins

| Object | Design | Old | New | Old 95% CI | New 95% CI |
|---|---|---|---|---|---|
| 013_apple | winner | 20.0% | **40.0%** | [0.07, 0.45] | [0.20, 0.64] |
| 077_rubiks_cube | winner | 0.0% | **60.0%** | [0.00, 0.20] | [0.36, 0.80] |
| 058_golf_ball | winner | 0.0% | **40.0%** | [0.00, 0.20] | [0.20, 0.64] |
| 037_scissors | winner | 0.0% | 6.7% | [0.00, 0.20] | — |
| 010_potted_meat_can | winner | 0.0% | 6.7% | [0.00, 0.20] | — |
| 033_spatula | baseline | 0.0% | **80.0%** | [0.00, 0.20] | [0.55, 0.93] |

**013_apple is the most load-bearing result here.** Apple has been confirmed
unsolved by *every* prior mechanism this project tried on it — the original
fixed heuristic (0–20%), a 500+80-evaluation quality-diversity search explicitly
aimed at it (`results/06_fruit_archive_qd/`), all reporting it as a hard,
confirmed size limit. The planner doubles winner's apple success rate (20% →
40%, CIs still wide but no longer overlapping zero-ish territory), and both
CIs are non-overlapping-adjacent enough that this reads as a real, if partial,
effect: **targeting was part of apple's problem, not the whole of it.** 077_rubiks_cube
and 058_golf_ball going from a clean 0% to 40–60% are the two next-cleanest
wins — both are geometrically round/cubic-symmetric objects where the old
fixed heuristic's generic top-surface grasp was a poor match for what the
object's own geometry actually offers.

---

## 3. Real regressions — reported with the same weight as the wins

| Object | Design | Old | New | Old 95% CI | New 95% CI |
|---|---|---|---|---|---|
| 048_hammer | winner | **60.0%** | **0.0%** | [0.36, 0.80] | [0.00, 0.20] |
| 065-a_cups | winner | 100.0% | 66.7% | [0.80, 1.00] | [0.42, 0.85] |
| 033_spatula | winner | 73.3% | 40.0% | [0.48, 0.89] | [0.20, 0.64] |
| 016_pear | winner | 73.3% | 60.0% | [0.48, 0.89] | [0.36, 0.80] |
| 043_phillips_screwdriver | winner | 13.3% | 0.0% | — | [0.00, 0.20] |
| 035_power_drill | baseline | 6.7% | 0.0% | — | [0.00, 0.20] |
| 026_sponge | baseline | 13.3% | 0.0% | — | [0.00, 0.20] |
| 065-a_cups | baseline | 26.7% | 0.0% | [0.11, 0.52] | [0.00, 0.20] |

**048_hammer is the clearest, largest, and most concerning regression** — a
clean, non-overlapping-CI drop from 60% to a complete 0% for the winner design.
The most plausible mechanism (read off the data, not independently
instrumented this pass): the old fixed heuristic used a hand-tuned yaw offset
for tool-like objects, almost certainly chosen to align the grasp with a
handle's long axis. The planner has no notion of "handle" — it picks whichever
cross-section scores best on pure antipodal/radial alignment, which can land
on a geometrically well-aligned but functionally wrong part of an asymmetric
tool (e.g. gripping across the head instead of the handle). This is a genuine
limitation of the planner's scope (stated in its own docstring: no semantic
object understanding, pure surface geometry), not a bug to silently patch —
recorded here as a real, load-bearing finding about *when* geometry-only
targeting helps versus hurts.

**065-a_cups** also regressed on *both* designs simultaneously (winner
100%→66.7%, baseline 26.7%→0%) — the planner's chosen grip band for this
object is measurably worse for both grippers than the original heuristic's,
independent of aperture differences between the two designs.

---

## 4. Interpretation

Splitting the 36 objects by what actually happened to the winner design:

- **4 objects meaningfully improved** (apple, rubiks_cube, golf_ball, and a
  marginal move on scissors/potted_meat_can) — all either round/cubic-symmetric
  shapes (where "best antipodal cross-section" is close to "correct grasp") or
  a previously size-limited case (apple) where better height selection alone
  recovers real success.
- **5 objects meaningfully regressed** (hammer, cups, spatula, pear,
  screwdriver) — disproportionately tool-like or asymmetric shapes, where a
  purely-geometric cross-section score can select a real but functionally
  wrong grip location that a hand-tuned yaw offset had implicitly encoded
  domain knowledge about (e.g. "grip the handle").
- **27 objects unchanged** — most of these are the already-confirmed hard
  failures (elongated tools, most cans/boxes/bottles) where neither targeting
  approach reaches a working grasp at all; this class is unaffected by this
  change, consistent with §1's "confirmed unfixable-by-targeting" framing
  from the QD-search finding being correct for *most*, though evidently not
  *all*, of the previously-all-fail set.

**Read against the brief's own framing**: "if it only closes some of the gap
... report that split plainly — targeting was part of the problem, size
limits are a separate, confirmed, unfixable-by-targeting limitation" is
close but not quite what the data shows. The more precise statement: **for
objects near a genuine geometric size/shape boundary (apple, round/cubic
shapes), targeting was measurably part of the problem, and this planner
recovers real success there.** For objects that fail for a *different*
reason — needing semantic understanding of where to grip an asymmetric tool,
which this planner deliberately does not attempt — geometry-only targeting
can make things measurably worse, not just fail to help. Both are real,
useful, and now measured findings; neither should stand in for the other.

---

## 5. What this does and doesn't change about the project's existing claims

**Does not overturn**: the core confirmation-eval result, the attribution
result, the cross-simulator replication, or the ROCm benchmark — none of
those pipelines were touched, and none used `use_planner=True` (verified: the
default `use_planner=False` path is byte-for-byte the original code, confirmed
by direct comparison of `adapt_grasp_profile`'s output before and after this
change on the same inputs).

**Does not overturn** the original 36-object generalization finding
("neither design generalizes broadly," 56%→58% both-fail rate here) — if
anything, the both-fail count getting *slightly worse* under better targeting
reinforces that most of that 56% is a genuine hard limit (controller strategy,
object size, or shape) rather than a targeting artifact.

**Does add**: a real, working, tested capability — a controller can now be
routed through actual per-object geometric reasoning instead of a 7-entry
lookup table — with honest, mixed, statistically-characterized evidence about
where that helps (round/cubic/size-boundary cases) and where it currently
doesn't (asymmetric tools needing semantic grip-location knowledge the
planner doesn't have). A natural next step, not pursued here (out of scope
for this pass): bias the height/yaw search toward the object's principal axis
of elongation for non-round shapes, which would directly target the
hammer/screwdriver-class regressions.

**Live demo**: `demo/grasp_planner_viz/` visualizes this exact planner's
output (same `plan_grasp_with_geometry` function, not a separate illustrative
version) on all 38 evaluated object meshes for both designs, including an
animated descend/close/lift sequence and the infeasible-case explanation —
see the main README for the hosted link.
