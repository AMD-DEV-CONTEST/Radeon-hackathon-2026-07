# ClaimCourt Final Submission Checklist

## Identity

- [x] Track: Track 2 - Development & Local Deployment of Private AI Agents
- [x] Team: Zi Fei Yu
- [x] Application: ClaimCourt
- [x] PR title: `Track 2, Zi Fei Yu, ClaimCourt`

## Required Materials

- [x] English README
- [x] Complete source code in the local working tree
- [x] English project-description source
- [x] Final project-description PDF generated and visually checked
- [x] Final PPT generated and visually checked
- [x] English 3-5 minute demo script
- [x] Demo video recorded and uploaded: https://youtu.be/Do_LJsUSFnQ
- [x] Public video URL added to `submission/PR_BODY.md`

## Technical Verification

- [x] 78 Python tests pass
- [x] Frontend TypeScript lint passes
- [x] Frontend production build passes
- [x] Local deterministic championship check passes
- [x] Frozen 320-query local holdout passes
- [x] Frozen 320-query Radeon live holdout passes
- [x] Qwen3-14B live court gate passes
- [x] Clean public snapshot install, tests, frontend lint, and frontend build re-run after cleanup

## Privacy and Repository Hygiene

- [x] Exclude personal documents and private evaluation corpora from the public snapshot
- [x] Exclude SSH keys, access tokens, credentials, and shell history
- [ ] Remove internal-only handoff and temporary build artifacts from the submission commit
- [ ] Verify `git diff --check`
- [x] Scan public release files for secret-shaped content and personal paths

## GitHub Submission

- [ ] Review the final diff with the owner
- [ ] Receive explicit owner approval to commit
- [ ] Create one clean English submission commit
- [ ] Push the `claimcourt` branch to the Fork
- [ ] Open the official Pull Request
- [ ] Confirm PR title and English PR body
- [ ] Open every material link from the PR
