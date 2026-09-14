# Track 2 Submission Checklist - RDK Agent

Official deadline: **2026-08-06 23:59 Beijing/Singapore time (UTC+8)**.

## User-supplied fields

- [x] Use the registered team name `d-robotics agent` consistently across the submission.
- [x] Provide and verify both the Bilibili primary video URL and Baidu Cloud backup URL.

## Eligibility and pull request

- [ ] Every team member is approved on Luma and enrolled in the AMD AI Developer Program.
- [ ] Team size is one to three and all members used the same team name.
- [ ] Fork the official competition repository and create one project directory, for example `submissions/track2-your-team-rdk-agent/`.
- [x] Use the title `Track 2, d-robotics agent, RDK Agent`.
- [ ] Keep the PR description and competition-facing artifacts in English.
- [ ] Confirm the source and all links are publicly readable.

## Project Specification

- [x] Application scenarios.
- [x] Current agent and system architecture diagrams.
- [x] Core capabilities.
- [x] Model and private local deployment plan.
- [x] AMD Radeon/ROCm optimization description.
- [x] Honest implemented/partial/not-implemented capability matrix.
- [x] Markdown source and polished PDF.

## Source and README

- [x] Complete `rdk-agent` and `rdk-sophon` sources.
- [x] Dependency lockfiles.
- [x] English root README with environment, dependencies, startup, deployment, and verification.
- [x] Detailed evaluator reproduction guide.
- [ ] Decide whether to add a repository-level LICENSE after owner review; Cargo metadata currently declares MIT but no root license file exists.
- [ ] Review and commit the current dirty worktree only after all changes are accepted.

## Verification before final upload

- [x] `npm run check` passed.
- [x] `npm test`: 134 passed, 0 failed.
- [x] `cargo test --workspace`: 62 passed, 0 failed.
- [x] `cargo clippy --workspace -- -D warnings` passed.
- [x] `cargo build --release --workspace` passed.
- [ ] Fix existing Rust formatting differences and re-run `cargo fmt --all -- --check` if time permits.
- [ ] Align the HTTP/WS default daemon socket with `/run/probe-daemon/probe.sock`, or explicitly pass that path in every demo command.
- [ ] Verify the unprivileged `probe` service user has the GPIO permissions required by `Hobot.GPIO`.
- [ ] Do not include ignored local `target/` or `node_modules/` directories in the competition copy.

## AMD evidence

- [x] Archive a redacted Radeon run record and model-side evidence.
- [x] Capture AMD Radeon GPU model for both measured paths.
- [x] Capture ROCm/HIP version for the 32B SFT path; disclose that the exact version was not archived for the independent 80B `llama.cpp` run.
- [ ] Capture vLLM version and exact launch command.
- [x] Record model revision and precision/quantization for both measured paths.
- [x] Capture local `/v1/models` response for the 32B SFT path; retain the three archived API canaries for the 80B path.
- [x] Run baseline and tuned benchmarks for both measured paths.
- [x] Report the metrics actually archived for each path without inventing missing percentiles.
- [x] Keep raw/redacted evidence with the submitted project.
- [ ] Never publish the endpoint credential or API key.

## Demo video

- [ ] Duration is approximately 3-5 minutes.
- [ ] Shows real CLI/TUI operation and the observable result.
- [ ] Shows Robot Development Mode and Robot Application Mode.
- [ ] Shows read-only RDK X5 connectivity/state/plugin evidence.
- [ ] Shows actual Radeon/ROCm inference plus redacted runtime evidence.
- [ ] Shows the final physical action and distinguishes command success from human observation.
- [ ] Contains no credentials or private infrastructure details.

## Supplementary material

- [x] PowerPoint deck provided.
- [x] Current five-node workflow used instead of the obsolete three-loop diagram.
- [x] Concept cover clearly identified as an illustration.
- [x] Architecture, workflow, board, and test evidence graphics provided.
- [x] Original “Why Sophon?” science-fiction visual and naming background included without adaptation artwork.
- [ ] Optionally replace the conceptual cover or video placeholder with a strong real frame from the recorded demo.

## Final integrity review

- [x] Search the current submission tree for secrets, private URLs, tokens, keys, and personal data.
- [x] Check every relative link in the current working copy.
- [ ] Repeat both integrity checks after copying the package into the official competition repository.
- [ ] Open the PDF and PPTX on a second machine.
- [ ] Verify the video and source links while signed out.
- [ ] Ensure no `Evidence pending` item has been replaced with an unmeasured estimate.
