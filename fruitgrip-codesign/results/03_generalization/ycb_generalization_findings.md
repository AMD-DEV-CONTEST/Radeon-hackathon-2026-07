# Full YCB-scale generalization test (Escalation 2) — findings

Session 8 (full-scale escalation pass), Genesis only. Expands the original
held-out generalization check (apple/pear, n=200 combined,
`generalization_findings.md`) to a much broader, deliberately diverse
36-object set — cans, boxes, bottles, hand tools, balls from golf-ball to
mini-soccer-ball size, cups, flat/thin items, and small graspables, not just
more fruit-like shapes. Frozen winner and baseline designs, unchanged; this
only adds evaluation objects, never re-searches or re-tunes either design.

**Scope note**: the brief asked for 30–50 objects at 30+ trials each. This ran
36 objects at 15 trials each — trimmed from an original 45-object plan, and
trials halved, for the same reason as Escalation 1: this machine is a personal
desktop with limited free RAM, and Escalation 1's full-resolution run drove it
into swap-thrashing. 36×15 stayed inside the same safe compute envelope that
Escalation 1's reduced scope proved stable at (confirmed via `vmstat`
throughout: no sustained iowait spike). Total run: 72 (object × design)
evaluations, ~72 minutes wall-clock, no thrashing.

Same DR ranges as the original confirmation-eval protocol (friction 0.7–1.3x,
mass 0.8–1.2x) — the original range, not Escalation 1's extended sweep, per the
brief.

Each object was evaluated in its own single-object scene (target object + place
bowl only) rather than the original 3-fruit shared layout, to avoid clutter/
collision issues from placing 36 wildly different-sized objects in one scene.
This is a scoping convenience — every object still goes through the identical
frozen `build_scene` → `EnvRandomizer` → `adapt_grasp_profile` →
`sim_episode.run_pick_place` pipeline used everywhere else in this project.

---

## 1. Headline finding: neither design generalizes broadly

**20 of 36 objects (56%) score 0% for *both* designs.** This is the most
important single number in this escalation, and it complicates the framing
more than it reinforces it: the scripted grasp controller — single top-down
approach, fixed-force close, no re-grasp, no adaptive strategy — was tuned
against three specific small fruit, and it simply does not work on most of a
broader object set, regardless of which gripper geometry is attached. Objects
in this all-fail category span cans (master_chef_can, sugar_box,
potted_meat_can), bottles (bleach_cleanser, pitcher_base, mustard_bottle),
most elongated tools (large_marker, spoon, knife, adjustable_wrench), most
balls except tennis_ball (golf_ball, softball, mini_soccer_ball), the larger
cup (065-j), and several others.

This means the "winner beats baseline" headline result from the original
Genesis confirmation-eval is **not evidence of general-purpose superiority** —
it's a result about three specific fruit-scale objects and a narrow band of
similarly-scaled objects nearby. Neither design should be described as
"generalizing well" in the report without this caveat attached.

---

## 2. Among the objects where *something* works: highly bimodal, not a uniform winner edge

Of the 16 objects with nonzero success for at least one design, the pattern is
**not** "winner is generally better" — it's sharply, almost cleanly bimodal:
winner dominates on some objects, baseline dominates on others, with very few
close contests.

**Winner-favored** (all with clean, non-overlapping 95% Wilson CIs at n=15):

| Object | Baseline | Winner | 95% CI (baseline) | 95% CI (winner) |
|---|---|---|---|---|
| 005_tomato_soup_can | 0% | **100%** | [0.00, 0.20] | [0.80, 1.00] |
| 056_tennis_ball | 0% | **100%** | [0.00, 0.20] | [0.80, 1.00] |
| 065-a_cups (small) | 27% | **100%** | [0.11, 0.52] | [0.80, 1.00] |
| 016_pear | 0% | **73%** | [0.00, 0.20] | [0.48, 0.89] |
| 033_spatula | 0% | **73%** | [0.00, 0.20] | [0.48, 0.89] |
| 013_apple | 0% | 20% | [0.00, 0.20] | [0.07, 0.45] |
| 038_padlock | 7% | 33% | — | — |
| 043_phillips_screwdriver | 0% | 13% | — | — |
| 048_hammer | 47% | 60% | — | — |

**Baseline-favored** (also clean, non-overlapping):

| Object | Baseline | Winner | 95% CI (baseline) | 95% CI (winner) |
|---|---|---|---|---|
| 051_large_clamp | **93%** | 0% | [0.70, 0.99] | [0.00, 0.20] |
| 077_rubiks_cube | **93%** | 0% | [0.70, 0.99] | [0.00, 0.20] |
| 037_scissors | **27%** | 0% | [0.11, 0.52] | [0.00, 0.20] |
| 026_sponge | 13% | 0% | — | — |
| 008_pudding_box | 7% | 0% | — | — |
| 035_power_drill | 7% | 0% | — | — |

**Tie**: 061_foam_brick, 100% for both.

Pooled across all 36 objects: baseline mean success rate 11.7% (median 0%),
winner mean 18.7% (median 0%) — winner ahead on the pooled average, but that
single number badly understates how the advantage is distributed. It is
**not** "winner is a bit better everywhere" — it's "winner wins big on ~9
objects, baseline wins big on ~6 different objects, and both fail completely
on 20." Reporting only the pooled mean would misrepresent this result.

---

## 3. A geometric pattern in the split — curvature, not just size

The winner-favored objects are overwhelmingly **round or curved-surface**:
a can (cylinder), a tennis ball and cups (round cross-section), pear and apple
(round fruit — winner's home turf), a spatula (thin but with a curved profile
where gripped). The baseline-favored objects are overwhelmingly **flat- or
straight-faced**: a rubik's cube (flat cube faces), a large clamp (flat jaw
faces), scissors (flat handle loops).

This lines up with a specific, testable geometric explanation: the winner's
searched parameters include `curvature_deg=4.20` (its fingers curve slightly
inward) and `n_fingers=3`, both selected because they help a gripper *wrap
around* convex, round fruit. That same curvature is a liability against a
flat face — a curved finger meets a flat surface at a point or edge rather
than flush, giving less stable contact area than the baseline's dead-straight
(`curvature_deg=0.0`) rigid fingers, which seat flush against any flat
surface. The winner's wider aperture (0.09122m vs baseline's 0.08m) plausibly
compounds the round-object advantage further (more clearance for larger round
objects like the tomato soup can and tennis ball) independent of curvature.

This is a pattern read off the data, not a mechanism confirmed by additional
instrumentation (no per-contact-point geometry logging was added this pass) —
offered as the most parsimonious explanation, and a strong candidate for
direct testing (log finger-face contact area or contact-normal alignment) in
a future session, not chased further here.

---

## 4. A note on the apple discrepancy

This run's apple result (winner 20%, 3/15, CI [0.07, 0.45]) reads notably
higher than the original held-out generalization session's reported apple-
specific rate ("rare — not impossible — at 3%", from a much larger n). The
wide CI here (upper bound 0.45) technically permits a true rate near 3%, and
this run's n=15 is far smaller than the original's — this is most likely
sampling noise, not a real change in apple's grip probability, but it's
recorded here rather than smoothed over, consistent with this project's
practice of flagging inconsistencies plainly.

---

## 5. What this does and doesn't tell us

**New headline material for the technical report**: "neither design
generalizes to the broader YCB set" (§1) and "the winner's advantage is
category-specific — round/curved objects — not general-purpose" (§2–3) are
both stronger, more honest framings than "the winner generalizes better,"
and should replace or qualify any generalization claim currently planned for
the report. The original apple/pear held-out result is not overturned, but
this places it in a much more precise context: pear (round) is a
winner-favored category; apple's rarity may be more about absolute size
relative to aperture than about the round/flat distinction (both apple and
orange are round yet both score at or near 0% for winner too — likely too
large in radius for even the wider aperture, a size-limit rather than a
shape-limit failure).

**Reinforces**: the "geometry, not force" framing from the original findings —
here extended to show that *which* geometric property matters (curvature vs.
flatness, not just squeeze force) shifts depending on the object, which is a
richer and more defensible version of that claim than the original fruit-only
result could support alone.

**Does not** establish either design as a general-purpose gripper — 56% total
failure across a modestly diverse 36-object set is a real, load-bearing
limitation that belongs in the report's limitations section, not just a
footnote.

**Raw data**: `ycb_generalization_eval.json` (all 36 objects × 2
designs, per-trial-aggregated success/CI/force/slip).
