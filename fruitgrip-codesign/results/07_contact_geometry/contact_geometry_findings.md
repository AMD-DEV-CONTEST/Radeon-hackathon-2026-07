# Contact-geometry mechanism test (session 8, Part B) — findings

`ycb_generalization_findings.md` §3 noticed a pattern but explicitly flagged it
as unconfirmed: winner-favored objects (round/curved) vs baseline-favored
objects (flat-faced), hypothesized as a contact-area/alignment effect (curved
fingers meet round surfaces flush, meet flat surfaces at a point/edge). This
session tests that directly with new instrumentation rather than leaving it
as a read-off-the-data guess.

**What Genesis's contact API actually exposes** (checked first, per the
brief's own instruction): `get_contacts()` returns `position`, `normal`,
`force` per contact — no literal contact-area field. Like MuJoCo (see
`cross_simulator_findings.md`), Genesis uses point contacts, not finite
patches. Two proxies built from what's actually available, reported as
proxies throughout, not literal area/alignment:
- **contact point count**: how many simultaneous discrete contacts exist
  between a finger and the object at a sampled instant (a stand-in for patch
  extent — more simultaneous points approximates a wider contact).
- **normal spread** (`1 − mean resultant length` of the unit contact
  normals across those points): low spread means the normals agree (locally
  flat, single-plane contact); high spread means they disagree.

Ran on 10 objects spanning `ycb_generalization_findings.md`'s three observed
categories (round/winner-favored, flat/baseline-favored, tie/both-fail), both
frozen designs, 10 trials each, sampled every step during the close phase (the
grip-forming phase, where a flush-vs-point-contact difference should be most
visible).

---

## 1. Result: confirms the flat-object half, does not confirm the round-object half

**Flat-faced objects — clean, consistent confirmation.** For all three
flat-baseline-favored objects, the pattern holds in the same direction every
single time: the design that *succeeds* has *lower* normal spread than the
design that *fails*, on the exact same object.

| Object | Baseline success / spread | Winner success / spread |
|---|---|---|
| rubik's cube | 90% / **0.00012** | 0% / 0.00091 (7.6x higher) |
| large clamp | 80% / **0.053** | 0% / 0.072 (1.3x higher) |
| scissors | 30% / **0.010** | 0% / 0.038 (3.6x higher) |

This is exactly what the hypothesis predicts: baseline's straight
(`curvature_deg=0`) fingers sit flush against a flat face (normals agree,
low spread); winner's curved (`curvature_deg=4.2`) fingers meet the same flat
face at more of a point/edge (normals disagree more, higher spread) — and the
higher-spread design is the one that fails, every time, in this sample.

**Round objects — the same proxy does *not* discriminate cleanly.** For the
three round-winner-favored objects, winner succeeds and baseline fails (as
already known), but normal spread does **not** consistently track this:

| Object | Baseline success / spread | Winner success / spread |
|---|---|---|
| pear | 0% / 0.00041 | 80% / 0.0034 (**higher**, yet succeeds) |
| tomato soup can | 0% / 0.00037 | 100% / 0.0016 (**higher**, yet succeeds) |
| tennis ball | 0% / 0.0026 | 100% / 0.0031 (**higher**, yet succeeds) |

Here the *succeeding* design (winner) has *higher* spread than the *failing*
design (baseline) — the opposite direction from the flat-object result, and
opposite to what a naive "low spread = good" reading would predict. Contact
point count doesn't rescue this either (baseline actually has *more* points
than winner on 2 of the 3 objects, despite failing outright).

---

## 2. Why the round-object side doesn't confirm — a flaw in the proxy, not necessarily the hypothesis

The likely explanation is that "low normal spread = good contact" is only a
valid prediction for a **flat** surface, where genuine flush contact really
does mean every contact point's normal points the same way. On a **curved**
surface, real wrap-around contact necessarily samples normals that point in
*different* directions as the contact patch follows the curve — so a
higher spread on a round object is not obviously evidence of worse contact,
it may just be evidence of a wider, curvature-following contact (which could
be the *good* outcome there). Baseline's very low spread on round objects is
more likely explained by baseline making only 1-2 near-tangent point contacts
(too few points for spread to have room to vary) rather than genuinely
"flush" contact — this project's own prior finding (`../01_core_confirmation/findings.md`) is
that a 2-point pinch on a round object is rotationally unstable, i.e. the
opposite of good contact, despite trivially low measured spread here. The
metric built for this session conflates "few points, low spread by
default" with "many points, low spread because genuinely flat" — these need
to be distinguished (e.g. only trusting spread when point count exceeds some
threshold) in any follow-up, not done here.

**Two more data points, for completeness, not central to the hypothesis:**
- **Tie case (foam brick, both 100%)**: both designs show tiny, near-identical
  spread (4–6×10⁻⁵) — consistent with (not proof of) the mechanism: when both
  achieve genuinely flush contact, both succeed.
- **Dice (both 0%)**: near-zero contact points for both designs (0.20 and
  0.00) — this failure has nothing to do with contact alignment; dice is
  almost certainly too small for either aperture to engage at all, a size
  limit like apple/orange's opposite (too big), not a geometry-alignment
  story.

---

## 3. Honest verdict: partial confirmation

Per the brief's own standard — report confirmed, partially confirmed, or
refuted, plainly: **this is a partial confirmation.** The flat-object half of
the hypothesis (curvature mismatch hurts on flat faces) is now directly,
consistently, measurement-backed across all three tested objects — genuinely
stronger evidence than the original "pattern read off the data" from
Escalation 2. The round-object half (curvature match helps on round objects)
is **not** confirmed by this measurement — the proxy built for it doesn't
discriminate the way a naive reading would predict, most likely because the
proxy itself needs to be curvature-of-surface-aware (comparing measured
spread against the *object's own* local surface curvature, not a fixed
low-spread target) to properly test the round-object side. That's a concrete,
scoped next step, not pursued here.

---

## 4. What this does and doesn't tell us

**New material for the technical report, with a caveat attached**: "flat
surfaces punish curved fingers, measured directly via contact-normal
alignment" is now a defensible, instrumented claim, stronger than the
original pattern-matched observation, and can be cited as such. "Round
surfaces favor curved fingers" should **not** be upgraded to a
contact-alignment claim on this data — it remains the weaker, unconfirmed
observation it was before this session, and should be reported as such if
mentioned at all.

**Reinforces**: `../01_core_confirmation/findings.md`'s existing "3 distributed contact
points resist rotation" framing for round objects is a *different* and
*already better-supported* explanation than the alignment mechanism tested
here — this session's data doesn't compete with that explanation, it just
confirms the alignment story doesn't extend to explain the round-object side
too.

**Raw data**: `contact_geometry_eval.json` (10 objects × 2 designs ×
10 trials, per-object success rate + mean contact points + mean normal
spread).
