# Compound Contract-Progress Result

Independent verification: **`promotion_pass=true`**

Public-before-run binding:

- Commit A: `6c7b46dc3ac5044c7ed0c422fc30dee1d5b1ba1e`
- Commit B: `427f2f729ce653df91a20db56c9fdbd16911a014`
- Fixed population: seeds `102530–102549`, 20 worlds, 40 paired cells

| Preregistered check | Result |
| --- | ---: |
| Full-chain direct | baseline 20/20; candidate 20/20 |
| Scout path reduction | 40.2563% (95% bootstrap: 36.0505–45.0271%) |
| Team path reduction | 15.0306% (95% bootstrap: 12.2563–17.6227%) |
| Physical-capture reduction | 27.5362% (95% bootstrap: 15.6250–37.8378%) |
| Physical captures | baseline 69; candidate 50 |
| Negative scout/team paired deltas | 20/20; 20/20 |
| Mission success | 40/40 |
| Unsafe / collision / fallback / false clear | 0 / 0 / 0 / 0 |
| Candidate native / delegated decisions | 30 / 0 |

All mandatory and capability gates passed. The exact output path set,
checksums, pre/post immutable bindings, public-remote binding, frozen-Go
authentication, attempt reconstruction, and telemetry validated.

Digest note: `EVIDENCE_INDEX.json` binds the pretty-printed `REPORT.json` file
bytes at SHA256
`8dc2d5026f697312bd39ddf6be7a65aa3ee08ac0e2799d0ca24cf4348c439a44`.
The independent verifier records its canonical-JSON serialization of the same
parsed report object as
`ac498eaef1e6013acfb761f009478ce387e6b76ab08318f9a6a18ca22d4dd5cd`;
the two representations are intentionally not byte-identical.

This is an additive compound V8 system result: one initial physical RGB-D
capture feeds one shared frozen seg-v3 backbone forward and two corridor ROI
proposals; geometry and vision share the physical root; contract-debt → online
Go `p_blocked` → travel NBV then selects the next observation. No weight,
calibration, gate, or threshold changed, and no effect is attributed to one
component alone.

Scope: `formal_result_eligible=false`; same-generator; non-locked; not OOD;
Genesis/AMD ROCm kinematic simulation; not physical-robot, sim-to-real, or
safety-certification evidence. This supplement does not overwrite the frozen
primary result.

The complete evidence is public on the additive review branch at
[`release/v8-derived/contract_progress_challenge_102530_102549/formal_run/`](https://github.com/eason4kim-rocket/look-twice/tree/v8-contract-progress-nbv/release/v8-derived/contract_progress_challenge_102530_102549/formal_run).
This official package intentionally avoids duplicating the roughly 15 MB raw
tree; [`EVIDENCE_INDEX.json`](EVIDENCE_INDEX.json) binds the compact formal
artifacts by path and SHA256.
