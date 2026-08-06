# Track 2 Submission Checklist

Deadline: **2026-08-06 23:59 Beijing/Singapore time**.

## Eligibility and accounts

- [ ] Luma registration is approved with the final participant/team name.
- [ ] AMD Developer Program account is active.
- [ ] GitHub ID and Discord ID are valid.
- [ ] Every team member is registered under the same team name.

## Internal product acceptance

- [ ] Core inference runs on Radeon Cloud with AMD Radeon GPU and ROCm.
- [ ] `/api/health` reports `local-radeon` only with verified runtime evidence.
- [ ] Investigation performs three distinct read-only tools and one synthesis step.
- [ ] Session state persists and supports a cited follow-up.
- [ ] Approval decisions are immutable and simulation-only.
- [ ] Model failure produces a visible, cited deterministic fallback.
- [ ] Full automated test suite passes.
- [ ] Secret and hardware-identifier scan passes.

## Official English deliverables

- [ ] Complete source code and dependency manifest.
- [ ] README with environment setup, launch guide, architecture, and evidence links.
- [ ] A Project Specification covers scenario, architecture, capabilities, local deployment, and optimization.
- [ ] A 3-5 minute Demo video shows real Radeon execution from UI/CLI to result.
- [ ] A Poster or PPT is included.
- [ ] All submitted material, project descriptions, and PR text are English.

## Internal artifact gates

- [ ] English subtitles and a public, signed-out video link are verified.
- [ ] Machine-readable ROCm and performance evidence is sanitized.

## Official PR

- [ ] Fork `AMD-DEV-CONTEST/Radeon-hackathon-2026-07`.
- [ ] Add the complete project to the fork on a submission branch.
- [ ] Open a PR to the official repository's default `main` branch.
- [ ] Use title `Track 2, <Team or participant>, Local Incident Commander`.
- [ ] Link source, specification, video, poster, and benchmark evidence in the PR body.
- [ ] Verify every link in a signed-out browser and mark the PR ready for review.
- [ ] Save the PR URL, commit SHA, and screenshots as the submission receipt.

The final PR submission is an external side effect. Stop for an immediate human
confirmation after all links and artifacts pass their acceptance checks.
