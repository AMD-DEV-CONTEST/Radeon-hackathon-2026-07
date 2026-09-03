# Publication Checklist

> Local content and integrity gates pass for this candidate. Every item is
> classified as `PASS`, `LIMITATION`, or `PENDING_EXTERNAL`. Clean-room
> reproduction, a public PR or submission, competition acceptance, G3 success,
> convergence, robustness, real-robot safety, raw-asset redistribution rights,
> and any AMD performance advantage remain unproven. It is ready for an
> authorized public PR only after independent `RELEASE_GO`. No commit, push,
> fork, PR, or external contact is performed by this work package.

Product identity: **Mantis-ROCm Bridge**, a configurable robot adaptation and
task-porting framework by **Zhiwen Su / Blueworm**, licensed **Apache-2.0** for
eligible original material. Mantis is the `stack_bowls_three` reference case.

## 1. Secret gate

- [x] **PASS** — the allowlisted candidate tree contains no SSH passwords,
      tokens, cloud credentials, private keys, authenticated control-socket
      material, `.bash_history`, `.env`, credential-bearing deployment YAML, or
      private deployment payload. The release audit reported zero content
      findings; this candidate adds no executable or secret-bearing input.

## 2. Size gate

- [x] **PASS** — no file exceeds **100 MB** in the allowlisted public tree
      (`competition-resources-v1.json` → `project_packaging_requirements`).
- [x] **PASS** — checkpoint payloads, dataset parquet, large receipt archives,
      and robot meshes are excluded. The release audit reports zero content and
      promotion findings with all checked local Markdown links resolved.

## 3. License gate

- [x] **PASS** — owner selected a project **LICENSE** and the exact canonical
      Apache License 2.0 text is present as the root `LICENSE` (SHA-256
      `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`,
      11358 bytes; no custom header). License: Apache-2.0; copyright holder
      Blueworm; copyright year 2026; decision date 2026-07-29; recorded in
      `docs/PROJECT_LICENSE_DECISION.md`. The license covers only original
      project code and documentation that Blueworm has the right to license.
- [x] **PASS (candidate policy)** — Mantis remains **externalized**: no URDF,
      mesh, source asset, derived raw asset file, materialization, or asset
      payload is committed
      (`third_party/ASSET_LICENSES.md`). The
      fallback is a hash-pinned local materialization script with explicit
      acknowledgement.
- [ ] **LIMITATION** — Mantis owner authorization to redistribute raw URDF,
      meshes, source assets, derived raw assets, materializations, or asset
      payloads has not been received. This does not block the local package
      because all such payloads remain excluded and externalized.
- [x] **PASS (candidate policy)** — the user permits rendered Mantis visual
      media in the demonstration video. This limited permission is not a
      general redistribution right or third-party license and does not weaken
      the raw-asset exclusions above.
- [x] **PASS (candidate policy)** — the MIT-licensed bowl asset (`002_bowl`
      model 3, Tianxing Chen / RoboTwin2.0) is not vendored in the candidate;
      if later packaged, pinned attribution and the verified license file are
      mandatory.
- [x] **PASS (candidate policy)** — `third_party/ASSET_LICENSES.md` is current and dated in the
      public tree; the `BlueWorm-EAI-Tech/lerobot_mantis_server` 404 / no-
      license notes are preserved.
- Acceptance: every third-party payload is either licensed+attributed or
      externalized; nothing unlicensed is committed.

## 4. Clean-room reproduction gate

- [ ] **LIMITATION** — archive clean-room source review remains
      `CLEANROOM_RUNNER_NO_GO`; neither runner executed. Clean-room reproduction
      from a fresh checkout is unproven and is not a local package blocker.
- [x] **PASS (documentation)** — dataset generation/materialization
      instructions are documented in `docs/REPRODUCIBILITY.md`; no dataset
      payload is published.
- Acceptance boundary: no clean-room pass or full reproduction is claimed.

## 5. Framework-story and English-primary gate

- [x] **PASS (local story audit)** — English is the primary official
      submission language; the English `README.md`, `TECHNICAL_REPORT.md`,
      `EVIDENCE_MATRIX.md`,
      `VIDEO_STORYBOARD.md`, and this checklist are authoritative
      (`competition-resources-v1.json` → `language_rules`).
- [x] **PASS (local story audit)** — `README.zh-CN.md` exists as a faithful
      **navigation mirror**;
      divergence resolves to English.
- [x] **PASS (local story audit)** — the framework is the product, Mantis is
      one reference case, and the synthetic fixture is not presented as a
      second real robot port.
- Acceptance: every public-facing document has an English-primary version and
  the Chinese mirror carries the same framework and result posture.

## 6. Honesty / claim-boundary gate

- [x] **PASS (local story audit)** — G3 is reported as **0/10**, eight
      `timeout`, two
      `collision_safety`, aggregate **FAIL** (no positive relabeling).
- [x] **PASS (local story audit)** — CUDA corrective representative terminal
      is `COMPLETE_NOT_PROMOTABLE`; official AMD corrective execution is not
      claimed.
- [x] **PASS (local story audit)** — training loss is labeled descriptive, not
      convergence/task
      success; no AMD performance advantage is claimed.
- [x] **PASS (local story audit)** — every quantitative claim maps to a receipt
      or `TODO-evidence`
      (see `EVIDENCE_MATRIX.md`).

## 7. Pull-request gate

- [ ] **PENDING_EXTERNAL** — fork the official repository
      `https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07`.
      `TODO-evidence` (not performed).
- [ ] **PENDING_EXTERNAL** — open a PR titled `Track 3, <team name>, <application name>`
      per the official format. `TODO-evidence`.
- [ ] **PENDING_EXTERNAL** — capture the **PR confirmation screenshot** required by
      `project_packaging_requirements`. `TODO-evidence`.
- [ ] **PENDING_EXTERNAL** — re-check the official ModelScope event page and the official
      GitHub repository **immediately before submission**
      (`competition-resources-v1.json` → `claim_boundary`).
- Acceptance boundary: these external actions require separate authorization;
  none has occurred.

## 8. Required-deliverables gate

- [x] **PASS** — evidence-backed framework-first technical-report draft —
      `TECHNICAL_REPORT.md`; participant Zhiwen Su / Blueworm and the
      `COMPLETE_NOT_PROMOTABLE` corrective terminal are synchronized.
- [x] **PASS** — evidence matrix — `EVIDENCE_MATRIX.md`.
- [x] **PASS** — independently accepted 168-second 720p demo with English
      narration and subtitles —
      `submission/Mantis_ROCm_Bridge_demo_20260806_v4.mp4`, H.264
      1280x720, SHA-256
      `220c54c7ca68760db53a5a9d8c80d1d8f39755a7365ee682758d6b5b50952017`;
      `VIDEO_GO` after 5,040/5,040-frame decode, 33 pinned frames, 89 dense
      samples, and no caption-overlap or black-frame finding. Storyboard:
      `VIDEO_STORYBOARD.md`.
- [x] **PASS** — complete allowlisted source code is present. Local content and
      integrity gates pass; an authorized public PR remains gated on
      independent `RELEASE_GO`. The Apache-2.0 project LICENSE is resolved,
      rendered demo visuals are permitted, and raw Mantis assets and payloads
      remain externalized.
- [x] **PASS** — reproducibility README + dependency specification —
      `docs/REPRODUCIBILITY.md`, `requirements/`, and `docker/` are present;
      independent clean-room execution remains `TODO-evidence`.
- [x] **PASS** — packaged ROCm execution evidence is present and remains
      separated from unsupported task-success or AMD-advantage claims.

## Terminal condition

The local package gates read `PASS`; the raw-asset authorization and clean-room
states remain explicit `LIMITATION`s, while fork, PR, screenshot, and rule
recheck are `PENDING_EXTERNAL`. Independent `RELEASE_GO` and separate public
authorization are required before a PR. This checklist does not establish
clean-room reproduction, a public repository, submitted PR, submission, G3
pass, or competition acceptance.
