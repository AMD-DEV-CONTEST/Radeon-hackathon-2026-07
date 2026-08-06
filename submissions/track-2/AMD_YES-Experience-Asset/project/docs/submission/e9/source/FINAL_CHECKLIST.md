# Final Submission Reference

This is a deadline checklist for the organizer-facing package. It separates
completed engineering evidence from the human publication steps that still
cannot be inferred or automated.

## Completed and evidence-bound

- [x] Exact tested implementation is frozen at
  `c9ec07489d17a2abb74bac66a23ade2c775c1b06` and merged through PR #52.
- [x] A complete M1-M5-private-delivery journey passed on Radeon PRO W7900.
- [x] The run used local `Qwen/Qwen3.5-9B` revision
  `460979c3d11864dd16408d860ac930a360a2fac2`, BF16, vLLM 0.26.0,
  ROCm/HIP 7.2 and a 20K context limit.
- [x] Correction, invalidation, regeneration, canonical evidence, privacy,
  permission and three-format delivery were observed in the same journey.
- [x] Stage 2 compared S0 and P1 on the same exact-commit public case; both
  passed and P1 was selected with S0 as rollback.
- [x] Stage 2 is described as one bounded observation, not a generalized
  performance claim; 0.0% cache hit and unmeasured peak VRAM remain visible.
- [x] Sanitized evidence packets are committed under
  `evidence/milestones/e8-a0-w7900/20260806T122806Z/` and
  `evidence/performance/stage2-minimal/20260806T124938Z/` on `main`.

## Repository integration before recording

- [x] PR #58 is merged; the final P1 launcher and S0 rollback are available on
  `main`.
- [ ] Confirm PR #59 (stage-rail demo navigation) is merged if the team wants
  that UI in the recording. It is presentation polish, not a product-evidence
  prerequisite.
- [ ] Rebase or otherwise update E9 PR #54 onto the current `main` before its
  final merge; its material branch predates PR #52 and PR #57.
- [ ] Re-run the repository-required checks after that integration and record
  the final `main` commit shown in the demo.

## Official package and publication

- [ ] Every team member has completed the required event/program registration.
- [ ] English Project Specification PDF is final and publicly accessible.
- [ ] Source repository README contains dependencies, setup, startup, tests and
  the exact W7900 reproduction route.
- [ ] English seven-slide PPT is final and publicly accessible.
- [ ] Record a 3-5 minute demo showing the actual application and Radeon
  execution; the prepared target is approximately four minutes.
- [ ] Add English narration or complete English subtitles.
- [ ] Upload the video and verify it is viewable while signed out.
- [ ] Add the final team-repository, specification, PPT and demo URLs to
  `OFFICIAL_PR_DRAFT.md`.
- [ ] Use an English organizer-PR title in the required form:
  `Track 2, Team Name/Registered Name, Application Name`.
- [ ] Open the actual PR against the organizer repository. A team-repository PR
  is not the competition submission.
- [ ] Submit before 2026-08-06 23:59 UTC+8.

## Claim and privacy integrity

- [x] Historical commit `60503eb` is not presented as complete-product proof.
- [x] Stage 1 PR #39/#44 metrics are labelled service-layer evidence only.
- [x] No claim says hallucination or privacy risk is eliminated.
- [x] Future roadmap items are not presented as implemented features.
- [ ] No secret, cookie, hostname, private prompt/response, model weight, cache,
  database or private evidence appears in the final public package.
- [ ] All public links work in a signed-out browser.
- [ ] The demo uses the public synthetic fixture and does not expose a private
  service or private data.
- [ ] Final contribution wording is checked against merged Git/PR history.

## Artifact consistency

- [x] Final-content PDF and PPT have been visually checked page by page / slide
  by slide and contain no clipping, broken fonts, stale commits or unintended
  draft/candidate labels.
- [x] SHA-256 values in `docs/submission/e9/README.md` match the published
  binaries.
- [ ] Demo narration, README, specification, PPT and official PR use the same
  model, commit and evidence boundaries.
- [ ] The owner has explicitly authorized the official PR/publication.
