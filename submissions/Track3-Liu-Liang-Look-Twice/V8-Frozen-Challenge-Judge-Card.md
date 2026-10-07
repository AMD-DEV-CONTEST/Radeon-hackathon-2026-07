# V8 Frozen Challenge — Judge Card

**Entrant / team:** Liu Liang (solo) · GitHub `@eason4kim-rocket` · Track 3
Physical AI

**Status:** independently verified `PASS` · 30 paired worlds · 60/60 valid
episodes · no retry, replacement seed, early stop, model change, calibration
change, or threshold change.

This is an additive, preregistered **same-generator non-locked supplement** to
the permanent 12-pair V8 locked result. Its primary endpoint is not an OOD,
rigid-body, or physical-robot claim. Separate additive evidence tests the
archived route decisions through bounded rigid-body actuation: recovery V2
uses 30 independent three-body scenes, while a solver-scale complement covers
the same fixed decisions in exactly two scene shards, with at most 60 robots
co-resident. Neither changes the primary endpoint.

> **Owner-review snapshot recorded on 2026-08-05:** at snapshot generation,
> both solver-scale reports, complete evidence directories, and the then-current
> PDF were packaged, and the manifest plus every checksum verified
> locally. At that timestamp, their protocol targets were not yet public and no
> competition PR had been opened. This is immutable packaging-time context;
> linked targets show current availability.

The current contract-progress-integrated report supersedes that historical
snapshot: **19 pages**, **1,104,864 bytes**, SHA256
`7dc0b453191a4ea215e432f22de6b374319c8df72580026f3adc8fa064291143`,
with 19/19 rendered-page QA and byte-identical output/site/official copies.

> **Additive 2026-08-06 compound result:** a separate public-before-run,
> same-generator, non-locked 20-world challenge preserved direct success at
> 20/20 in both arms while reducing mean scout path 40.2563%, mean team path
> 15.0306%, and physical captures 27.5362%. All 40/40 missions completed with
> zero unsafe/collision/fallback/false-clear outcomes. This complete-system
> result is kinematic, non-OOD, not physical-robot evidence, and retains
> `formal_result_eligible=false`. See the packaged
> [result summary](evidence/contract_progress_challenge_102530_102549/RESULT_SUMMARY.md)
> and [hash index](evidence/contract_progress_challenge_102530_102549/EVIDENCE_INDEX.json).

## Seven judge checks

| Check | Result | Machine evidence |
|---|---|---|
| Public before execution | [Commit A](https://github.com/eason4kim-rocket/look-twice/commit/9e14cbb999824d35a21749f4ff420ab63f81847d) published `2026-08-03 10:01:53Z`; [Commit B](https://github.com/eason4kim-rocket/look-twice/commit/3a52ba548de26858a7fdcad1c1ce7237b709fe69) published `2026-08-03 10:02:22Z`. B changed only the A-hash field. Preregistration SHA-256: `90679e84f835c6e46983c1b219c1196506164e3c82dd1dfffec33469a73e28a2`. | [Protocol](https://github.com/eason4kim-rocket/look-twice/blob/v8-competition-release/docs/V8_FROZEN_CHALLENGE_PROTOCOL.md) · [preregistration JSON](https://github.com/eason4kim-rocket/look-twice/blob/v8-competition-release/release/v8-frozen/results/V8_FROZEN_CHALLENGE_PREREGISTRATION.json) · [packaged run manifest](evidence/challenge_102500_102529/RUN_MANIFEST.json) |
| Capability | The preregistered primary remains active full-chain direct **29/30 = 96.7%**, Wilson 95% CI **83.3–99.4%**, versus passive **0/30**, CI **0–11.4%**. Paired gain: **+96.7 percentage points**; exact two-sided McNemar **p = 3.73×10⁻⁹**. “Full-chain” requires mission success, direct/no-detour, and a Python+Go+effective joint admit for the corridor actually executed. A separate post-hoc descriptive offline oracle-feasibility audit found **29/29** worlds with an oracle-clear corridor went direct, while the sole dual-blocked world, seed `102515`, safely detoured: **30/30 active route outcomes matched offline feasibility**. Oracle labels were never available to the controller; this audit is not a preregistered endpoint. | [packaged challenge report](evidence/challenge_102500_102529/CHALLENGE_REPORT.json) · [packaged post-hoc feasibility audit](evidence/V8_FROZEN_CHALLENGE_FEASIBILITY_AUDIT.json) |
| Mission and safety | **60/60 mission success**, **0/60 unsafe**, **0/60 fallback**. Across the 30 active records, unsafe was false, collision count was zero, and fallback was false. Seed `102515` remained safe and completed by detour because both corridors were oracle-blocked. All 18/268 Python/Go receipt disagreements were Python-admit/Go-deny with `effective_admit=false`; no disagreement opened the gate. In every disagreement, Go independently found only one qualifying root and the inconclusive set `{clear, blocked}`. | [packaged verification report](evidence/challenge_102500_102529/VERIFICATION.json) · [raw archive](https://github.com/eason4kim-rocket/look-twice/releases/download/v8-competition-candidate/v8-frozen-challenge-102500-102529.raw.tar.gz) |
| AMD full-pipeline execution | **60/60** episodes used Genesis live RGB-D, the frozen checkpoint, and Purify Go receipts: 268 RGB-D observations, 134 vision proposals, and 268 Go invocations/receipts. Full subprocess-wall telemetry retained **844** two-second ROCm samples across **1,685.5 s**, including idle: GPU mean/median/p95/max **19.4/0/95/100%**; VRAM p95/max **2/2%**; package power mean/p95/max **35.7/81/109 W**. | [packaged ROCm telemetry](evidence/challenge_102500_102529/ROCM_TELEMETRY.json) |
| Warehouse operational trade | Active scouting reduced loaded-carrier logical path from **6.404 to 4.961** (`−1.443`, **−22.5%**) while adding **2.980** scout path; total logical-role team path rose from **6.404 to 7.941** (`+1.538`, **+24.0%**). This is kinematic path burden, not energy, throughput, latency, or physical duty cycle. | [packaged per-seed and burden tables](evidence/challenge_102500_102529/CHALLENGE_REPORT.json) |
| Additive decision-to-dynamics bridge | A separate fixed-denominator V2 replay consumed the archived decisions—**29 direct + 1 safe detour**—without rerunning perception or policy inference. It passed **30/30** across 30 serial, independent three-body scenes: **90/90** distinct non-fixed robot instantiations reached; all **29/29** direct carrier pairs saved at least 0.50 m; mean loaded-carrier path was **4.9435 m active vs 6.2433 m passive (−20.8183%)**; and counted blocker-contact and active carrier/scout contact rows were both **0**. The sole dual-blocked seed `102515` executed its declared safe outer detour. | [V2 result summary](README.md#separate-additive-decision-bound-dynamics-replay) · [packaged report](evidence/decision_dynamics_recovery_v2_102500_102529/REPORT.json) · [packaged scope audit](evidence/decision_dynamics_recovery_v2_102500_102529/PROVENANCE_REVIEW.json) |
| Solver-scale two-shard complement | The same archived decision set separately passed **20/20** in one 60-body scene and **10/10** in a second 30-body scene. Across exactly two scenes, all 30 scouts, 30 active carriers, and 30 passive carriers reached; all 29 direct pairs saved at least 0.50 m; the weighted loaded-carrier path was **4.943605 m active vs 6.245385 m passive (−20.8439%)**; counted blocker/active-pair contact rows and post-build pose writes were **0**; maximum tilt/drift was **10.583984° / 0.021342 m**. This means **90 cumulative distinct robot instantiations, maximum co-resident count 60, and never all 90 in one scene**. | [packaged 60-body prefix report](evidence/decision_dynamics_single_scene_60_102500_102519/REPORT.json) · [prefix package checksums](evidence/decision_dynamics_single_scene_60_102500_102519/PACKAGE_SHA256SUMS) · [packaged 30-body suffix report](evidence/decision_dynamics_single_scene_30_suffix_102520_102529/REPORT.json) · [suffix package checksums](evidence/decision_dynamics_single_scene_30_suffix_102520_102529/PACKAGE_SHA256SUMS) · owner-review [prefix protocol](https://github.com/eason4kim-rocket/look-twice/blob/v8-competition-release/docs/V8_ADDITIVE_DECISION_DYNAMICS_60_PROTOCOL.md) · [suffix protocol](https://github.com/eason4kim-rocket/look-twice/blob/v8-competition-release/docs/V8_ADDITIVE_DECISION_DYNAMICS_30_SUFFIX_PROTOCOL.md) |

## Scope that must travel with the result

- The preregistered primary uses Genesis 1.1.2 kinematic simulation on AMD
  ROCm; it is not rigid-body contact validation.
- Carrier and scout are separate logical-role poses, viewpoints, and capture
  roots on **one shared Genesis chassis**; they are not two physical devices or
  simultaneous dual-body dynamics.
- Seeds `102500–102529` are a previously untouched reserved subset from the
  same generator family. The result is not called OOD or population-level
  generalization.
- Receipt-level Python/Go agreement is **250/268 = 93.3%**. The Go side vetoed
  every disagreement, and the effective authorization remained fail-closed.
  A post-hoc descriptive audit (not a preregistered endpoint) found that all 18
  shared one signature: active policy, corridor B, a single Go-qualified root,
  and the inconclusive Go set `{clear, blocked}`. Four were on a non-selected
  corridor; 14 were transient evaluations before the final selected-corridor
  joint admit. This audit changed no runtime, calibration, or threshold.
- The rigid-dynamics V2 is **additive, non-locked**, and declares
  `formal_result_eligible=false`. It preserves the challenge primary at
  **29/30**; 30/30 describes archived decision-to-actuation replay outcomes,
  not a revised direct-route score.
- V2 used 30 serial, independent scenes with three non-fixed bodies per scene.
  Its 90 bodies are distinct instantiations across the run, not one
  simultaneous 90-body scene, and the replay is not simultaneous cooperative
  motion or a live perception-policy rerun.
- V2 “zero contact” means zero counted Genesis contact rows in the fixed run,
  not real-robot validation or safety certification. The 20.8183% result is a
  paired loaded-carrier path reduction, not lower total team travel, energy,
  task time, or throughput.
- The solver-scale complement consists of two independently verified,
  non-resumable reports: seeds `102500-102519` in one 60-body scene and seeds
  `102520-102529` in a second 30-body scene. The only combined topology
  statement is exactly two scenes, 90 cumulative distinct robot instantiations,
  and maximum co-resident count 60. The 90 were never co-resident in one scene;
  there was no checkpoint/state resume and there is no synthetic combined
  execution report.
- Both solver-scale shards are archived-decision, fixed-order serial,
  simulation-only evidence and declare `formal_result_eligible=false`. They
  are not a live perception-policy rerun, simultaneous cooperative fleet
  control, dynamic-obstacle evidence, physical-robot validation, sim-to-real
  evidence, or safety certification. The primary remains **29/30**, not 30/30.
- The V2 formal source binding omitted the directly imported
  `src/v4_motion.py`; a post-run audit matched it to clean commit `b0c4f0d`,
  but that is corroborating evidence rather than complete formal import-closure
  attestation. The original inner V2 `SHA256SUMS` did not cover
  `ATTEMPTS.jsonl`, `PROGRESS.json`, or worker logs. The retained records show
  30 first-attempt, zero-exit workers and no observed retry or replacement;
  they are not cryptographic proof that no additional unsealed attempt ever
  existed.

## Clean-clone verification

The raw archive contains 195 files. Its internal `SHA256SUMS` binds every other
regular file (194/194). Validator output must remain outside the extracted
results directory.

```bash
git clone --branch v8-competition-release \
  https://github.com/eason4kim-rocket/look-twice.git
cd look-twice
curl -LO https://github.com/eason4kim-rocket/look-twice/releases/download/v8-competition-candidate/v8-frozen-challenge-102500-102529.raw.tar.gz
tar -xzf v8-frozen-challenge-102500-102529.raw.tar.gz
python3 scripts/verify_v8_frozen_challenge.py \
  --results-dir v8-frozen-challenge-102500-102529 \
  --preregistration release/v8-frozen/results/V8_FROZEN_CHALLENGE_PREREGISTRATION.json \
  --repo-root . \
  --output v8-frozen-challenge-102500-102529.LOCAL-VERIFICATION.json
sha256sum v8-frozen-challenge-102500-102529.LOCAL-VERIFICATION.json
```

Expected verification SHA-256:
`942f1624e6903033335e5ffbcdbc12afed4a0e8eed4e0d33ffa657f5e147a940`.

Raw archive SHA-256:
`171c9bab73554e1a3654c24872ade011b8423d3aca0df8eca38625a90b0854d2`.

After owner-approved source publication, verify the two solver-scale shards
independently from the same clean clone:

```bash
PREFIX=release/v8-derived/decision_dynamics_single_scene_60_102500_102519
SUFFIX=release/v8-derived/decision_dynamics_single_scene_30_suffix_102520_102529
(cd "$PREFIX" && shasum -a 256 -c SHA256SUMS && \
  shasum -a 256 -c PACKAGE_SHA256SUMS)
(cd "$SUFFIX" && shasum -a 256 -c SHA256SUMS && \
  shasum -a 256 -c PACKAGE_SHA256SUMS)
python3 scripts/verify_v8_additive_decision_dynamics_60.py \
  "$PREFIX/REPORT.json"
python3 scripts/verify_v8_additive_decision_dynamics_30_suffix.py \
  "$SUFFIX/REPORT.json"
```

Expected report SHA-256 values are
`3cfcf19e60ba102772d052862f44bae29eb47d84717db3d0fbe7ed3b62b24450`
for the 60-body prefix and
`69dfd142175ea3d9f719dd5cd0dbb3126f3f7b77b74f4ad753b5f92193ce1a4e`
for the 30-body suffix. Both reports must verify independently; the weighted
summary is not a third execution report or a one-scene result.

The complete machine result is also available as a stable
[release verification asset](https://github.com/eason4kim-rocket/look-twice/releases/download/v8-competition-candidate/v8-frozen-challenge-102500-102529.VERIFICATION.json).
