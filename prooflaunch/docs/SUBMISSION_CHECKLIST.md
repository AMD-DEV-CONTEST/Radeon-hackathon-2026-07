# AMD Radeon Hackathon Track 1 submission checklist

Official submission route: complete the Luma registration, fork the competition
repository, and open a pull request. All submission materials, descriptions,
and the pull request must be in English.

- Registration deadline: `2026-08-05 23:59 UTC+8`
- Submission deadline: `2026-08-06 23:59 UTC+8`
  (`2026-08-06 11:59 America/New_York`)
- Team: individual or up to three people
- Eligibility: AMD Developer Program membership
- Registration: <https://luma.com/amd-4dhi?utm_source=modelscope>
- Official repository:
  <https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07>

ModelScope native result submission is disabled for this event. Radeon Cloud
**Add Template** is a private development launcher, not the official entry.

Proposed pull request title:

`Track 1, Banyan, ProofLaunch: Multimodal GTM Studio`

## Required materials

- [x] Project Profile PDF
  - [x] Project background
  - [x] Target users and application scenarios
  - [x] System architecture
  - [x] Model and algorithm introduction
  - [x] AMD Radeon / ROCm adaptation
- [x] Source code repository structure
- [x] English README with environment, startup, and dependencies
- [x] Model card, Radeon setup, evaluation, security and governance documents
- [x] Strict allowlisted public-export builder and secret/path/hash validation
- [ ] Demo Video (official guidance recommends 3–5 minutes)
  - [ ] Actual operation process
  - [ ] Actual execution on AMD Radeon
  - [ ] Command line or GUI through final result
  - [ ] Output clarity, stability, and diversity
- [x] Supplementary English deck (PPTX)
- [x] Optional one-slide poster
- [ ] Confirm every team member is registered and an AMD Developer Program member
- [ ] Fork competition repository
- [ ] Create branch `submission/track1-banyan-prooflaunch`
- [ ] Add the reviewed public export at `prooflaunch/`
- [ ] Configure Radeon Add Template only after its GitHub notebook path exists
- [ ] Open English pull request with the exact title format

## Scoring alignment

- [ ] Complete input → processing → output workflow: 40/40 target
- [ ] Innovation and fun: 20/20 target
- [ ] Practical or social value: 20/20 target
- [ ] Radeon output clarity, stability, and diversity: 20/20 target
- [ ] At least one key inference process runs locally on AMD Radeon GPU
- [ ] Core functionality does not rely only on a closed online API

## Proof gates before PR

- [ ] All 27 unit/integration tests pass on Radeon.
- [ ] Post-fine-tuning Gemma emotion evaluation is recorded.
- [ ] Gemma pre/post multimodal-retention gate passes.
- [ ] One frozen SDXL visual-generation fixture passes.
- [ ] SigLIP2 fifth semantic gate passes and records its limitations.
- [ ] The local model router proves sequential Gemma → SDXL → SigLIP2 unloads.
- [ ] Latency and peak VRAM are recorded.
- [ ] Audit → repair → export completes on Radeon.
- [ ] Demo video URL resolves without authentication.
- [ ] Every visible claim is supported by source evidence.
- [ ] Third-party licenses and model terms have been reviewed.
- [ ] No credentials, cookies, tokens, personal email, or private paths remain.
- [ ] `SUBMISSION_GATE.json` reports `overallStatus: ready`.

Do not open the pull request while a P0 proof gate remains blocked.
