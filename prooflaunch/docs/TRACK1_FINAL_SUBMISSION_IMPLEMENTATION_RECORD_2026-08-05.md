# Track 1 final submission implementation record — 2026-08-05

## Outcome

ProofLaunch has been converted from a large engineering workspace into a
judge-first Track 1 submission package. The package is locally reproducible,
claim-bounded and hash-locked. A 190.9-second product-operation Demo Video, PR
#308 and an archived executed Gemma-4 Radeon/HIP Notebook are now present. It is
not yet competition-complete because a fresh end-to-end ProofLaunch Radeon
campaign run with image/video stages, latency, peak VRAM and output hashes is
not in the final evidence set.

## Implemented in this closure pass

- Added `JUDGE_START_HERE.md` as the single evaluator entry point.
- Added `demos/run_track1_demo.py` as the one-command governed replay.
- Isolated evaluator replays in `artifacts/judge-track1-replay-v1/` so judges
  cannot mutate the sealed canonical receipt by running the demo.
- Added the compact English Track 1 README and English PR body.
- Added a machine-readable submission manifest with seven verified file hashes
  and explicit negative claims.
- Added the mandatory live Radeon capture card with a continuous 3–5 minute
  shot sequence and exact retain-before-destroy evidence list.
- Added a Chinese public sharing draft that never upgrades mechanical evidence
  into Radeon, 4A, Top-1 or production-effect claims.
- Fixed the run-bound demo platform regression by replacing the retired generic
  `owned` public surface with the explicit LinkedIn surface contract.
- Improved run-bound failure diagnostics to expose worker, snapshot and job
  errors when the workflow does not reach the human release boundary.
- Made challenger-repair and dossier compilers safely regenerable in place
  while rejecting unexpected files.
- Rebound the 130-row named-product ledger, 13 challenger dossiers, baseline
  capture kit, hybrid quality control and readiness receipt to the final
  canonical deliverable bytes.
- Expanded the final source lock to include `demos/`, `submission/` and the
  root judge entry point.

## Final observed evidence

| Evidence | Result |
|---|---:|
| Product-critical Python regression | 827/827 passed |
| Local route-head Node regression | 10/10 passed |
| Final targeted lock/readiness/demo regression | 14/14 passed |
| Web build | 46 routes / 60 same-origin API contracts |
| Run-bound registered deliverables | 10 |
| Last-mile mechanically ready lanes | 14/14 |
| Mechanically admitted named-product challenger dossiers | 13/13 |
| Agentic readiness audit | 9 pass / 3 gaps |
| Named-product PK completed rows | 0/130 |
| Named-human quality observations | 0 |
| Production-effect observations | 0 |
| Automatic external actions | 0 |
| Historical Gemma-4 Radeon inference | observed in archived executed Notebook |
| Fresh end-to-end ProofLaunch Radeon run | not observed |

The sealed canonical run is `run-77d4b65d605ef305250e29ef`. Its receipt
content SHA-256 is
`00279a273342a9c401d09a904070ea75e34445090d2cfa4b3e379cdd42519192`.

## Submission state

Passed official material gates:

- project profile PDF;
- complete source and English environment/startup documentation;
- supplementary English deck (the official PPT/Poster choice is satisfied);
- deterministic local evaluator replay and evidence manifest.

Open official gates:

- fresh end-to-end ProofLaunch execution on AMD Radeon/ROCm;
- video evidence that binds the Radeon run to final output, latency and VRAM;
- final competition evidence seal with no blocked P0 gate.

The official fork and PR #308 are present. The workflow performed no external
publication, paid action or autonomous business submission.
