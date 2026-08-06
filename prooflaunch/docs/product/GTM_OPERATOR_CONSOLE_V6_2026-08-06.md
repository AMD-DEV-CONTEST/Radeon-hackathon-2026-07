# ProofLaunch GTM Operator Console V6 — AI Judge Ready

## Objective

Turn the submission from a feature-heavy control panel into a light, production-oriented GTM operator console that a human or model-based judge can understand and verify in approximately two minutes.

## Deterministic review path

1. Open `/control/frontier-gtm`.
2. Choose one of the five production recipes.
3. The preset immediately compiles the governed campaign package.
4. Review strategy, native copy, three rendered PNGs, one playable MP4, audit data, and run state.
5. Continue to Assets, Approve & release, and Learn from results.

The primary navigation exposes only this five-step path. The complete 46-route product remains available under **All tools** and the Command-K palette.

## Real generation contract

- Every recipe submits its closed brief to authenticated, idempotent `POST /v1/realtime-preset-campaigns`.
- One response contains an adapted GTM strategy, three creative territories, channel-native social copy, image/video systems, three real PNG binaries, one real H.264 MP4 binary, content hashes, and a release audit.
- The browser fetches the four tenant-authorized content-addressed assets, then displays the PNGs and playable MP4 in the production result instead of substituting placeholders.
- The realtime preset renderer is an OSS Pillow + ImageIO + FFmpeg editorial compositor. Its manifest records `image_model_inference_claimed=false` and `video_model_inference_claimed=false`; this path does not pretend that a diffusion or video foundation model ran.
- The advanced **Run frontier production** action remains a separate cloud-model path through `POST /v1/frontier-gtm/runs`. It fails closed if the tenant session or server credential is unavailable and never substitutes an unlabelled local model.
- Publication, external messaging, and budget spend remain separately governed actions; successful binary generation does not imply release.
- The loopback evaluator may obtain an ephemeral tenant session only when the server is started with `--enable-local-evaluation-session`. That bootstrap is disabled by default in production.

## AI judge discoverability

- `/judge-manifest.json` is the canonical machine-readable capability and evidence map.
- `/llms.txt` gives a compact evaluator guide and points to the manifest.
- The HTML advertises both resources with alternate links, an explicit manifest meta tag, and inline SoftwareApplication structured data.
- The manifest states the deterministic review sequence, 46 UI routes, 60 same-origin API contracts, authentication requirements, safety boundaries, and unsupported claims.
- Stable DOM anchors identify the generation entry, one-click action, real API form, server-only result, live status, and five review steps.
- A claim-evidence matrix tells an automated judge exactly how to verify each important capability and what correct failure looks like.
- Truth boundaries explicitly prohibit unsupported Apple award, campaign performance, human preference, and autonomous action claims.

## Experience changes

- Full light-mode SaaS operator surface with a compact translucent command bar.
- Five-step mission navigation designed for a two-minute evaluation.
- Command palette, route breadcrumb, collapsible sidebar, and context/run/policy inspector.
- Five one-click B2B/B2C production recipes covering adapted strategy, social text, three rendered image formats, and a six-second vertical film.
- High-contrast focus states, responsive work surfaces, mobile stage navigation, and no observed horizontal overflow.

## Verification record

- Workspace build: 46 routes, 12 declared interactions, 60 same-origin API contracts.
- Realtime media and UI suites: 20/20 passed.
- Frontier and production API suites: 60/60 passed.
- API evidence: all four returned assets were downloaded through tenant authorization and matched their SHA-256, three PNG signatures, one MP4 `ftyp` signature, and the exact idempotent replay body.
- Browser interaction path: loopback evaluation bootstrap, one-click preset production, in-page PNG/MP4 display, asset download, advanced fail-closed cloud path, Command-K routes, and responsive no-overflow layout.
- Latest desktop evidence: `evidence/v10/operator-console-v6-judge-ready-final-2026-08-06.png`.

## Evidence and source files

- `web/index.html`
- `web/styles.css`
- `web/app.js`
- `web/judge-manifest.json`
- `web/llms.txt`
- `src/prooflaunch_remix/realtime_preset_campaign.py`
- `tests/test_realtime_preset_campaign.py`
- `tests/test_v10_submission_production_api.py`
- `evidence/v10/operator-console-v6-judge-ready-final-2026-08-06.png`

## Super Site 10X execution note

Super Site 10X run `super10x-20260806-eb18601004-8416d773` stopped at its internal `stage_contract_invalid` gate. Its generated output was not merged. The implementation described above was completed directly in the project source and verified with the project build, unit/API tests, and browser interaction checks.
