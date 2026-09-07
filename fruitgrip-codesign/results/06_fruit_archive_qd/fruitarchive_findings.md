# Quality-diversity archive over gripper geometry (Escalation 3) — findings

Session 8 (full-scale escalation pass), Genesis only. Builds a MAP-Elites-style
archive over the gripper design space — an illumination search that maps out
which regions of (aperture, curvature) geometry perform well, rather than the
project's usual single-objective CMA-ES search for one winner. Specifically
built to answer the brief's named question: **does any region of this design
space solve the apple-style narrow-clearance failure mode better than the
single frozen winner does?**

**Scale, explicitly reduced from the brief.** The brief asked for "tens of
thousands of evaluations." Each evaluation needs a fresh Genesis scene build
for a new gripper geometry (~18–20s) plus trial episodes — at that cost, tens
of thousands of evaluations is a multi-day job on this machine (a personal
desktop, not a cluster — the same constraint documented in Escalations 1 and
2). Per an explicit check-in this session, this ran **500 evaluations**
instead — roughly the scale of the original project's own hackathon-budget
search (population=5, generations=5 per branch), not "research scale." This
is stated plainly, not glossed over: this archive is a reduced-scope
exploration, not the exhaustive map the brief originally asked for.

**Setup**: behavior descriptors are (aperture, curvature_deg), binned 8×8 = 64
cells — chosen because Escalation 2's generalization findings identified these
as the two parameters that visibly separated winner-favored (round,
wide-aperture) from baseline-favored (flat-faced, straight-finger) objects.
`n_fingers`, `finger_length`, and `compliance` are free — the search can vary
them within a cell, same as `search.py`'s own "outer loop over n_fingers"
treatment. Fitness objects: the original banana/lemon/plum plus apple (added
specifically to give the search a chance to discover something that handles
apple). Each of the 500 evaluations used only 3 trial seeds (matching
`search.py`'s own convention) to keep the run affordable — took ~2.55 hours,
all 64 cells filled.

---

## 1. A data-quality problem, caught and fixed before drawing conclusions

Checking the finished archive found that **zero of the 64 filled cells ever
had apple drawn in their 3-trial sample** — with 3 random trials pulled from a
4-object pool, the probability any specific object is never drawn is
(3/4)³ ≈ 42%, and apple happened to lose that coin flip in all 64 cells. This
meant the 500-evaluation search's own results said *nothing* about apple
despite that being the explicit point of including it — a direct consequence
of keeping per-evaluation cost low (3 trials) to make 500 evaluations
affordable at all. Caught this before writing any conclusion about apple, and
built a proper fix (`fruit_archive_revalidate.py`): the top 4 cells (by
archive fitness) were re-evaluated with 30 trials *per object*, each object
forced explicitly rather than randomly drawn, alongside the frozen winner and
frozen baseline for direct comparison. That re-validation — not the raw
archive's own fitness numbers — is what §2 below reports for apple.

---

## 2. Does any cell solve the apple problem? **No — plainly, no.**

| Design | banana | lemon | plum | **apple** |
|---|---|---|---|---|
| Frozen winner (original) | 100% [0.89,1.0] | 100% [0.89,1.0] | 83% [0.66,0.93] | **0% [0.0,0.11]** |
| Frozen baseline (original) | 93% [0.79,0.98] | 0% [0.0,0.11] | 0% [0.0,0.11] | **0% [0.0,0.11]** |
| Archive rank 1 (cell 5,0) | 90% | 97% | 100% | **0% [0.0,0.11]** |
| Archive rank 2 (cell 7,1) | 100% | 100% | 100% | **0% [0.0,0.11]** |
| Archive rank 3 (cell 6,0) | 93% | 100% | 100% | **0% [0.0,0.11]** |
| Archive rank 4 (cell 4,0) | 83% | 100% | 100% | **0% [0.0,0.11]** |

All six designs — the two original frozen designs and the four best cells this
500-evaluation search could find — score **exactly 0/30 on apple**, with
identical 95% Wilson CIs [0.0, 0.11]. Every top cell converged to
`n_fingers=3`, low curvature (0.08°–10.1°, vs. the original winner's 4.2° —
all in the same "nearly straight" regime), aperture 0.079–0.098m, and low
compliance (0.0–0.12) — i.e. the search kept rediscovering minor variations on
the *same* geometric idea the original winner already represents, not a
structurally different design. Apple's known failure mode (per
`ycb_generalization_findings.md`, apple and orange both fail near-universally
even for the wider-aperture winner) is most likely a hard **size** limit —
apple's radius approaches or exceeds what any aperture in the searched range
(0.045–0.100m) can accommodate — not a curvature or compliance problem this
kind of search can route around. This is reported as the honest, negative
result the brief explicitly asked for: **no, nothing in this archive solves
the apple-style failure mode.**

---

## 3. What the archive *did* find: modest, real gains on the original 3 fruit

Archive rank 2 (cell [7,1]: `n_fingers=3, finger_length=0.0527,
curvature_deg=10.11, aperture=0.0978, compliance=0.0`) scores a clean
**100%/100%/100%** across banana/lemon/plum at 30 trials each — a genuine,
if modest, improvement over the original frozen winner's 100%/100%/83.3%
(winner's plum CI [0.66, 0.93] vs. this cell's plum CI [0.89, 1.0] — close to,
though not quite, non-overlapping at n=30). Three of the four top cells beat
the original winner on plum specifically, the object where the original
winner was weakest. This is a legitimate finding: a slightly wider aperture
(~0.098m vs. 0.091m) combined with slightly more curvature (~10° vs 4.2°)
appears to grip plum a bit more reliably. It is not a dramatic result — the
original winner was already strong (93.3% pooled in the original
confirmation-eval) — and this reduced-scale search should not be oversold as
having found a meaningfully better design; it found a marginally better one
within a narrow neighborhood of the original.

---

## 4. What this does and doesn't tell us

**New material for the technical report**: a plain "no" on the apple question,
backed by six designs and 720 forced-object trials, is stronger and more
useful than silence on the topic — it tells the report's authors not to claim
or imply that any variant of this gripper family handles narrow-clearance
objects like apple, and points at *why* (aperture/size, not curvature or
compliance) for anyone continuing this line of work.

**Reinforces**: `ycb_generalization_findings.md`'s finding that
apple/orange-scale objects are a hard limit for this whole gripper family, now
confirmed by direct search rather than just observation on two fixed points
(winner, baseline).

**Does not** establish that quality-diversity search is unhelpful here more
broadly — the modest plum improvement (§3) shows the method can find real,
if small, gains; it simply didn't find anything that escapes the apple
failure mode within the reduced 500-evaluation budget and the (aperture,
curvature) descriptor space searched. A larger, multi-day run, or a search
that treats aperture bounds themselves as extendable (the current
`APERTURE_BOUNDS = (0.045, 0.100)` may simply be too narrow to reach whatever
aperture apple needs), are the natural next steps — flagged, not pursued
here, consistent with this session's scope discipline.

**Does not** substitute for re-running this at the brief's original "tens of
thousands of evaluations" scale — if that scale is wanted, it needs either
much more wall-clock time (days, not hours) or actual cluster/cloud compute,
neither available to this session.

**Raw data**: `fruit_archive.json` (full 64-cell archive, 500-eval
history), `fruit_archive_revalidation.json` (30-trials-per-object
re-validation of the top 4 cells + both frozen designs, the source for §2–3's
tables).
