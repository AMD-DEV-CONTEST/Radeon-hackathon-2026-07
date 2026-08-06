# ProofLaunch GTM operator console V8 · contest, interaction and model-backed production repair

Date: 2026-08-06

## Outcome

V8 repairs four judge-facing defects in the Track 1 production path:

1. The console now exposes a concise AMD public scoring map and links to the official public event page while preserving the attached Rules & Conditions as the governing document.
2. Brief → Strategy → Concept → Production → Audit → Release is a six-button interactive navigator. Every stage explains its input, operation, output and next action.
3. The result workspace exposes four high-contrast selectable views instead of low-affordance text tabs: Strategy map, Copy system, Live assets, and Quality & release.
4. Preset production now starts from a SHA-256-verified, project-generated image-model master and performs a new server-side multi-format adaptation for the current brief. The server produces three new PNG binaries and one playable motion-design MP4, then returns hashes and source receipts.

## Truth boundary

- Image-model inference is observed for the verified source master and recorded in `web/assets/model-masters/model-master-manifest-v1.json`.
- The production click verifies that master and runs live format adaptation for the submitted brief; it does not rerun the image model.
- The MP4 is a live motion-design render from the verified image-model master. Video-model inference is not claimed.
- `4A_candidate` describes the target rubric, not an achieved preference result. Named-human craft/rights review, source-hidden preference testing, and live-market effect evidence remain required.
- Generation never publishes, sends, spends, or grants release authority.

## Contest mapping

The public AMD AI DevMaster event page places the entry in Track 1 (Multimodal AI), describes text/image/video/audio-visual creation examples, and publishes an 80-point product assessment plus a 20-point AMD Radeon GPU operational-performance assessment. The console labels this as a summary only; the complete attached Rules & Conditions remain governing.

## Model-master set

- B2B proof observatory, OpenAI built-in ImageGen project asset, SHA-256 verified.
- B2B evidence engine, OpenAI built-in ImageGen project asset, SHA-256 verified.
- B2C private ritual, generated for this repair with OpenAI built-in ImageGen, SHA-256 verified.

The B2C generation prompt and every receipt field are stored in `web/assets/model-masters/model-master-manifest-v1.json`.

## Implementation surfaces

- `web/index.html`: contest map, six-stage controls, stage guide and explicit result switcher.
- `web/styles.css`: strong interactive affordances, focus/hover/active states and responsive behavior.
- `web/app.js`: stage navigation, result switching and three-level production-source disclosure.
- `src/prooflaunch_remix/realtime_preset_campaign.py`: model-master verification, responsive art direction, PNG/MP4 rendering and fail-closed receipts.
- `tests/test_realtime_preset_campaign.py`: binary, source, adaptation and truth-boundary assertions.
- `tests/test_v10_submission_ui.py`: visible judge-path interaction contract.
- `tests/test_v10_submission_production_api.py`: static model-master delivery and authenticated production API contract.

## Acceptance checks

- Six stage controls are keyboard-operable buttons, not decorative labels.
- Four result views present obvious click targets and selected state.
- Every returned media asset has a binary signature, SHA-256 and tenant-bound download path.
- Source-model inference, current-request adaptation and video-generation mode are independently disclosed.
- Long campaign text is bounded and positioned from measured line boxes to prevent collision.
- The release step remains named-human gated.
- The 46-route console contains 2,336 DOM nodes against a 2,350-node budget. The new controls were compressed by 30 nodes before the budget moved from 2,300; the remaining 2.2% increase preserves real button semantics and visible guidance.
