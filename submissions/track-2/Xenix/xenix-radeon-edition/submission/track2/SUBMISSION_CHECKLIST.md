# Xenix Radeon Edition — Final Submission Checklist

This is a stop/go checklist for the official Track 2 pull request. An unchecked
required item is a blocker, not a suggestion.

## Stop: this worktree is not the submission

The current `Xenix_native-radeon-special` worktree is a development and staging
worktree. It is **not** the official hackathon fork, submission branch, or pull
request. Do not publish this worktree as-is. The final entry must be copied from
an approved source snapshot into a branch based on the official contest
repository, reviewed there, and submitted through the official fork/PR flow.

The organizers provide no mandatory directory or document template. Confirm the
current official repository convention immediately before copying the entry.

## Deadline

**Final deadline: 2026-08-06 23:59 UTC+8 (2026-08-06 15:59 UTC).**

- [ ] Confirm the official event and Rules pages still show this deadline.
- [ ] Leave enough time for upload processing, public-link checks, and PR review;
      a local file timestamp is not a submission.
- [ ] Confirm the pull request is open and publicly accessible before the
      deadline.

## Eligibility

- [ ] Every participant completed the official Luma registration.
- [ ] Every participant meets the Rules' identity, age, location,
      sanctions/export-control, and other eligibility requirements.
- [ ] Required AMD AI Developer Program membership is active for prize
      eligibility.
- [x] Public GitHub identity is **xiaoland**. The participant's applicable China
      regional organizer contact identity is retained privately and is not
      published in the repository or pull request.
- [ ] The entry was created during the permitted competition period and complies
      with the official Rules and Conditions.
- [ ] The team has reviewed the competition's submission license/property terms
      and has authority to grant the required rights.

## Team and naming

- [x] Team size is one participant.
- [x] Final team name: **Xenix**.
- [ ] If no team name was supplied during registration, replace the team field
      with the registered participant's own name as required by the official
      repository.
- [x] Participant **Lan_zhijiang** and the contribution summary are recorded in
      the PR body draft.
- [ ] Every placeholder in [PR_DESCRIPTION.md](PR_DESCRIPTION.md) is replaced
      and its links are rechecked in the official-fork path.
- [ ] Application name is consistently **Xenix Radeon Edition**.
- [ ] Final PR title is exactly:

```text
Track 2, Xenix, Xenix Radeon Edition
```

## Required materials

- [x] English project specification exists:
      [PROJECT_SPEC.md](PROJECT_SPEC.md).
- [x] Complete source tree and English root run guide exist:
      [repository README](../../README.md).
- [x] Environment, startup commands, dependency manifests, and verification
      commands are linked from the project specification and root README.
- [x] Claim boundaries are documented in [EVIDENCE.md](EVIDENCE.md).
- [ ] Final demo video is 3–5 minutes, in English, and shows actual operation
      from UI/command path to the final result on AMD Radeon/ROCm.
- [x] Choose exactly one supplementary format for the required slot:
      **poster**.
- [x] The selected poster highlights the scenario, practical value,
      architecture, and bounded Radeon evidence.
- [ ] Every material and the PR description is in English.

## Demo identity

Fill these fields only after the final encoded file is accepted. Hash the exact
uploaded bytes, not an earlier local render.

```text
Public video URL: DEMO_PUBLIC_URL_TBD
Video filename: Xenix-Radeon-Edition-Track-2-Demo-1080p.mp4
SHA-256: DEMO_SHA256_TBD
Duration: DEMO_DURATION_TBD
Resolution / frame rate: 1920x1080 / 30 fps
```

- [ ] Public video URL works in a signed-out/private browser window.
- [ ] Video audio, captions, UI, and all inserts are legible at 1080p.
- [ ] SHA-256 is exactly 64 lowercase hexadecimal characters and matches a fresh
      download from the public URL.
- [ ] The video shows the real Chat, Embedding, and OCR setup paths without
      implying a nonexistent deploy-all action.
- [ ] The video shows explicit provider selection after registration.
- [ ] The Hero result is exactly `U100 = 130` and `R200 = 75`; `B500` is excluded.
- [ ] The follow-up reuses and cites the same policy/inventory context.
- [ ] Radeon/ROCm telemetry is synchronized with actual requests and identifies
      only the exact accepted cell.
- [ ] Any accelerated setup footage displays truthful elapsed time.
- [ ] Hidden chain-of-thought is absent; only user input, Tool/Artifact events,
      sources, and final outputs are shown.

## Performance and claim gate

- [ ] Capture timestamped repeated measurements on the exact declared
      `gfx1100 / ROCm 7.2.1` cell with fixed inputs and configuration.
- [ ] If claiming an improvement, preserve a comparable baseline and optimized
      result with the same measurement method.
- [ ] If the comparison is not reproducible, remove all speedup/uplift language
      and report only the fixed architecture, runtime, capacity, and self-tests.
- [ ] Do not claim tokens/s, TTFT, Embedding latency, OCR latency, throughput,
      energy, cost, CPU advantage, NVIDIA advantage, or utilization without the
      final evidence bundle.
- [ ] Do not claim the optional 20-point Radeon Cloud model-API optimization
      category; it is outside this entry's evidenced scope.

## Privacy, security, rights, and integrity

- [ ] Search every submitted text, image, video frame, subtitle, metadata field,
      and archive for endpoints, hostnames, usernames, email addresses, personal
      names, credentials, key material, fingerprints, bearer secrets, live URLs,
      ports, PIDs, private paths, and raw runtime logs.
- [ ] Submit only fictional or explicitly cleared business data.
- [ ] Confirm no internal task workspace, runtime home, database, logs, caches,
      screenshots of unrelated applications, or development-only notes are
      included.
- [ ] Confirm no `.env`, SSH key, `known_hosts`, credential store, token, or
      diagnostic bundle is included.
- [ ] Confirm source files used in the demo are unchanged and the derived Dataset
      is separately registered.
- [ ] Review [`COPYRIGHT.md`](../../COPYRIGHT.md),
      [`TRADEMARKS.md`](../../TRADEMARKS.md), and
      [`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md) against the exact
      public source and media set.
- [ ] Inventory the licenses and publication rights for source code, Qwen3.5,
      BGE-M3, RapidOCR/PP-OCRv6, vLLM, PyTorch, Triton, fonts, music, narration,
      screenshots, data, and all poster/video assets.
- [ ] Resolve the repository's public-viewable/non-open-source notice against the
      contest submission terms before opening the PR.
- [ ] Confirm architecture/key art are illustrative and never presented as
      runtime or performance proof.

## Source and verification freeze

- [ ] Select one exact source commit for the entry and record its commit ID in
      the PR body.
- [ ] Confirm the final source includes every code change required by the demo;
      do not submit a video produced by uncommitted behavior.
- [ ] Run `pdm install` from the frozen source and dependency lock.
- [ ] Run `pdm run check`.
- [ ] Run `pdm run test`.
- [ ] Run `pdm run smoke`.
- [ ] Run `pdm run package` and `pdm run smoke-package` if a packaged build is
      part of the entry.
- [ ] Record command, timestamp, source commit, exact result, and any justified
      omission in the PR body or a public verification note.
- [ ] Run `git diff --check` and the repository's Markdown relative-link check on
      the exact submission branch.
- [ ] Re-run a public-safe secret/PII scan on the staged file set.

## Official fork and pull-request procedure

1. [ ] Open the
   [official contest repository](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07)
   and review its latest README, Rules link, open-PR convention, and deadline.
2. [ ] Fork the official repository to the submitting GitHub account or team.
3. [ ] Clone that fork separately; verify `origin` is the fork and `upstream` is
   the official repository. Do not reuse the current staging worktree's remote or
   history.
4. [ ] Create a submission branch from the current official `main`.
5. [ ] Choose a self-contained Track 2 project path consistent with the latest
   accepted repository convention. Because no official template is prescribed,
   record the chosen path in the PR body.
6. [ ] Copy the frozen complete source, root README, project specification,
   Evidence Register, final poster/PPT, and public video link into that path.
   Exclude internal tasks, runtime state, caches, credentials, and unrelated
   worktree files.
7. [ ] Review the complete staged diff, file sizes, binary assets, license notices,
   relative links, and line endings. Confirm the diff contains only the intended
   entry.
8. [ ] Commit and push the reviewed submission branch to the official fork.
9. [ ] Open a pull request from the fork branch to the official repository's
   `main` using the exact title format above and an English description that
   links every required material.
10. [ ] In a signed-out/private browser window, open the PR, every repository
    link, the poster/PPT, and the video. Confirm that no link relies on local
    paths or access permissions.
11. [ ] Check the PR for organizer feedback, merge conflicts, automated checks,
    and requested changes until the submission window closes.

## Final go/no-go review

- [ ] A skeptical judge can locate the scenario, architecture, five Agent
      capabilities, exact cell, run instructions, result, and limitations in
      under five minutes.
- [ ] The 60-point functional story is supported by an accepted complete Hero
      and multi-turn follow-up.
- [ ] The 40-point Radeon story is supported by real request-path evidence and
      a truthful same-cell measurement method/result.
- [ ] Every claim in the video, poster/PPT, PR, README, and project specification
      agrees with [EVIDENCE.md](EVIDENCE.md).
- [ ] No required checkbox above remains open.
