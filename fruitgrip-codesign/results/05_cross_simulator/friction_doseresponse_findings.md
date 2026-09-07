# Friction dose-response sweep (Escalation 1) — findings

Session 8 (full-scale escalation pass). Converts the correlational friction
finding from `cross_simulator_findings.md` §5 (winner's MuJoCo failures cluster
at friction ratio ≥1.06; Genesis's cluster at ≥1.24, both confirmed via direct
per-trial logging) into a controlled dose-response curve: friction ratio fixed
(not drawn from a range) at each of several values swept from 0.5 to 2.0 —
deliberately extending well past the original 0.7–1.3 DR ceiling — with mass
ratio fixed at 1.0 and pose jitter (±3cm/±30°) kept on as the one remaining
source of trial-to-trial variance (documented design choice, see both sweep
scripts' docstrings). Frozen winner and baseline designs, unchanged. Lemon/plum
only (banana's MuJoCo grasp is independently broken — see
`cross_simulator_findings.md` §3).

**Resolution note**: the full brief asked for 0.05 friction steps × 30 trials in
both engines. MuJoCo ran at that resolution (fast, ~3min). Genesis's identical
scope drove this machine — a personal desktop with limited free RAM, not a
dedicated compute node — into active swap-thrashing (confirmed via `vmstat`:
78–89% iowait, sustained page-in/out traffic) rather than just running slowly.
Per a mid-run check-in, the Genesis sweep was killed and restarted at a coarser
resolution (0.1 steps, 15 trials/point) that completed cleanly without
thrashing. MuJoCo's finer-resolution data is used where the extra precision
matters (exact per-object thresholds, §2); Genesis's coarser data is sufficient
to answer the core shape question this escalation asks (§1).

---

## 1. The core question: same curve shape across engines, or not?

**Split answer — real agreement for the winner, real divergence for the
baseline.** This is not a case where averaging the two would be honest; the two
designs behave completely differently across this comparison.

**Winner: yes, a recognizably similar cliff in both engines**, at a similar
absolute friction range:

| Friction ratio | MuJoCo (winner) | Genesis (winner) |
|---|---|---|
| 0.5 – 1.10 | 100% | 100% |
| 1.15 – 1.20 | 50% | 100% |
| 1.25 | 50% | 100% |
| 1.30 – 1.40 | 0% | ~53% |
| 1.50 | 0% | 40% |
| 1.60 – 2.00 | 0% | 0% |

Both engines show the winner succeeding reliably at low-to-moderate friction,
entering a failure transition somewhere in the ~1.1–1.6 range, and reaching
complete failure by 1.6. That is real, cross-engine-consistent evidence that the
winner design's grip has a genuine friction ceiling — not an artifact specific
to either simulator's contact solver. The *shape* of the transition differs
(MuJoCo's is a sharp, near-binary step over a ~0.15–0.20-wide band; Genesis's is
a shallower decline over a ~0.4-wide band — see §3 for the likely reason), but
the presence and rough location of a cliff is shared.

**Baseline: no, categorically different curves.**

| Friction ratio | MuJoCo (baseline) | Genesis (baseline) |
|---|---|---|
| 0.5 – 1.30 | 100% | ~0% (1/15 at 0.50, 0% everywhere else) |
| 1.35 – 1.45 | 50% | 0% |
| 1.50 – 2.00 | 0% | 0% |

MuJoCo's baseline has its *own* real cliff — later than the winner's (1.30–1.50
vs. 1.10–1.30) but a cliff nonetheless, meaning baseline is *also*
friction-sensitive in MuJoCo, just more tolerant of it. Genesis's baseline has
**no cliff at all** — it is uniformly near-zero across the *entire* swept range,
including friction values well below the original DR floor (0.5, 0.6, 0.7...).
This is not a friction effect in Genesis; baseline simply cannot grip lemon or
plum there, at any friction level tested. This matches (and is now precisely
explained by) the original Genesis confirmation-eval numbers: baseline was
already 0/12 on lemon and 0/9 on plum at nominal friction (~1.0), and this sweep
shows that failure is unconditional, not a friction-dependent near-miss that a
luckier DR draw could have avoided.

---

## 2. Why this explains the entire cross-simulator reversal

This is the headline result of this escalation: it identifies the actual
mechanism behind `cross_simulator_findings.md` §2's direction reversal, not just
another correlational observation.

- **In Genesis**, baseline's failure on round objects is a friction-independent
  geometric problem (a 2-finger pinch on a round fruit is unstable regardless of
  grip strength — the project's own long-standing "geometry, not force" framing,
  `../01_core_confirmation/findings.md`). Any DR sampling of friction, including the original
  0.7–1.3 range, will show baseline failing badly and winner succeeding — which
  is exactly the 26.7%-vs-93.3% result.
- **In MuJoCo**, both designs are fine at nominal friction, but *both* have a
  friction ceiling — the winner's is just lower (~1.1–1.3) than the baseline's
  (~1.3–1.5). The winner's ceiling falls partly *inside* the original 0.7–1.3
  DR range (specifically the 1.15–1.30 band); the baseline's does not. That
  single fact — not a broken controller, not an engine bug — is why sampling
  friction uniformly in [0.7, 1.3] makes the winner look *worse* than baseline
  in MuJoCo: the winner is the only one of the two designs whose failure region
  the original DR range actually reaches into.

In short: the reversal is real, and it is explained. It is not "MuJoCo is wrong
about the winner" or "Genesis is wrong about the baseline" — both engines are
being internally consistent about two *different* underlying failure
mechanisms (a friction-independent geometric instability in Genesis's baseline;
a friction-dependent grip ceiling that happens to catch the winner more than the
baseline in MuJoCo's 0.7–1.3 sampling window). The confirmed shared
friction-sensitivity of the winner (§1) is real and cross-engine, but it is only
*half* of what produced the original reversal — the other half is the
baseline's totally engine-specific behavior, which this sweep is what finally
separated the two effects.

---

## 3. Precise per-object thresholds (MuJoCo) — the "smooth" curve is two step functions

The 50%-ish plateau points in MuJoCo's tables above are not a probabilistic
transition — they are the pooled average of two objects, each of which fails
*deterministically* at its own sharp threshold. Verified directly (6 trials per
object at the boundary friction, both fully consistent — 6/6 or 0/6, no mixed
outcomes):

| Design | Object | Exact failure threshold |
|---|---|---|
| Baseline | lemon | 1.50 (last success 1.45) |
| Baseline | plum | 1.35 (last success 1.30) |
| Winner | lemon | 1.30 (last success 1.25) |
| Winner | plum | 1.15 (last success 1.10) |

Two clean patterns: (1) plum's threshold is lower than lemon's for **both**
designs — plum is the more friction-sensitive object regardless of gripper; (2)
the winner's threshold is **exactly 0.20 lower than baseline's for both objects**
(1.50→1.30, 1.35→1.15) — a strikingly uniform shift, suggesting whatever
mechanism the winner's geometry introduces at high friction affects both
objects by the same fixed margin, not object-specifically. This precision was
only feasible on the fast MuJoCo side; Genesis's per-object breakdown at this
resolution was not run (see §4).

This also explains why the MuJoCo dose-response transition band looks *narrow
and sharp* (§1) — it's the sum of two hard steps 0.15–0.20 apart, not a
genuinely gradual physical transition. Genesis's own transition band is wider
and shows real intermediate probabilities (53%, 53%, 40% — not clean fractions
implied by a 2-object step-function sum with 15 trials, e.g. 8/15 isn't a
clean half-and-half split of two 15-trial deterministic sub-populations), which
suggests Genesis's contact resolution introduces genuine trial-to-trial (not
just object-to-object) variability near the boundary that MuJoCo's does not —
a real, if secondary, engine difference worth flagging.

---

## 4. Mechanistic read on *why* high friction hurts — not attempted beyond what the sweep itself shows

The brief allowed skipping deeper instrumentation here if it wasn't already
close to hand, and that's the case: understanding *why* higher friction
produces a worse-seated grip (final resting contact angle, whether the fingers
fail to slide into a symmetric seated position before the close force
locks in) would need new instrumentation beyond this sweep's success/fail
readout, which was not built this pass. Flagged as a natural next diagnostic,
not pursued here.

---

## 5. What this does and doesn't tell us

**New headline material for the technical report**: the cross-simulator
reversal is now mechanistically explained, not just observed. This is a
stronger, more defensible finding than the original correlational note and
should replace it as the primary framing in any report section covering
cross-simulator replication.

**Reinforces, doesn't overturn**: the winner's real, shared friction ceiling
(§1) reinforces the original friction-correlation finding rather than
contradicting it — it's now precisely located and shown to be genuinely
cross-engine, not just correlated within one engine's own trials.

**Does not** change the conclusion that this project's headline 93.3%-vs-26.7%
Genesis result does not straightforwardly replicate in MuJoCo (it still
doesn't, and now we know precisely why) — nor does it substitute for physical
hardware validation, per `cross_simulator_findings.md`'s standing caveat.

**Raw data**: `friction_doseresponse_mujoco.json` (0.05-step, 30
trials/point), `friction_doseresponse_genesis.json` (0.1-step, 15
trials/point, after the mid-run resolution reduction described above).
