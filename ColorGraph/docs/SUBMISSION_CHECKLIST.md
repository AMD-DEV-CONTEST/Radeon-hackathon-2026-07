# AMD Radeon Hackathon Submission Checklist

Track target: **Track 1 — AI Application on AMD Radeon**

Project: **ColorGraph**

Official requirements: <https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07>

This file separates completed engineering work from paused or externally blocked
submission work. ColorGraph is **not ready to submit** until every required row is
complete.

## Prepared in the current workstream

- [x] English root README with environment, dependency, startup, architecture, and
  verification instructions.
- [x] Public demo-media strategy with source pages, attribution, licenses, frozen
  SHA-256 values, and a reproducible downloader.
- [x] Private DJI source excluded from Git and separated from public redistribution.
- [x] Tbilisi night selected as the public creative-direction hero.
- [x] Snowdonia selected as the public multi-cut workflow/mask demo.
- [x] DJI 111.0–123.8 s selected as the local professional D-Log hero segment,
  conditional on finished-work publication rights.
- [x] `faithful` / `amplified` / `counterpoint` effect ranges made visibly distinct.
- [x] Real-frame Tbilisi offline run: 3/3 candidates hard-pass; current graph
  unchanged pending confirmation.
- [x] Non-AMD lint/test/build CI workflow.
- [x] English Project Profile PDF generated and visually checked.
- [x] Reduced submission gate executed on the supported Radeon Cloud host:
  Ubuntu 24.04, AMD `gfx1100`, ROCm 7.2.1, local AI stages, two representative
  1080p benchmark rows, HEVC Main10 output, and hard QA all passed. Frozen unified
  report SHA-256:
  `c7a7e15c265ac8a33a9286125059b67d6ee4b7df90827caa02be53337235c195`.

## Owner decisions / external actions

- [ ] Select and add a project source-code license. This is a rights decision and
  must not be guessed by a contributor.
- [ ] Supply final team name/member/contact details if the official form requires
  them.
- [ ] Archive the actual DJI authorization/certificate and verify public display,
  commercial showcase, modification, attribution, and redistribution clauses.
- [ ] Make the GitHub repository publicly accessible for judging.

## Remaining submission production

- [ ] Record the required 3-5 minute demo through the verified AMD host, showing
  live device identity, UI operations, ROCm jobs, playback, export, and evidence.
- [ ] Produce the PPT or Poster.
- [ ] Fork the official contest repository and open the final English submission PR
  with the required Track/team/application title.

## Resume order

1. Freeze the code commit and source license.
2. Verify that the archived AMD report, inputs, runtime identity, and hashes still
   match the frozen commit. Rerun the AMD gate only if code, inputs, or the target
   environment changed.
3. Run the complete non-AMD regression suite and resolve any freeze-time failures.
4. Record the final video through the verified AMD host using public media or a
   DJI-derived finished output only after rights review.
5. Produce the PPT/Poster from the frozen Project Profile and measured AMD evidence.
6. Publish the repository, create the official fork/PR, and verify every link from
   an unauthenticated browser.
