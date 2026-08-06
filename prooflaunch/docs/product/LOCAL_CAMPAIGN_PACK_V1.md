# Local Campaign Pack V1–V6

The identity-hidden five-person V5/V6 comparison protocol, frozen rubric, and
current evidence boundary are documented in
[`CAMPAIGN_PACK_VISUAL_BLIND_REVIEW_V1.md`](CAMPAIGN_PACK_VISUAL_BLIND_REVIEW_V1.md).

ProofLaunch now exposes a source-bound local campaign pack at
`GET /v1/local-campaign-pack`. Its six hash-verified delivery artifacts are
served from `GET /v1/local-campaign-pack/assets/{asset-id}` with the evidence
class `local-campaign-pack-mechanical-not-product`.

## Observed execution history

- Image source: cached `AbstractFramework/qwen-image-2512-8bit`, seed
  `20260802`, 32 steps, 8-bit quantization, Apple Metal.
- Generation time: 624.91 seconds.
- Network downloads and cloud API calls: zero.
- Voice source: the existing local Qwen3-TTS qualification master.
- Music source: the existing local Ming Omni instrumental generation.
- Film: deterministic FFmpeg composition, 3840×2160, H.264 High, 24 fps,
  14.75 seconds, AAC 48 kHz stereo.
- Audio master: PCM 24-bit, 48 kHz stereo, 14.72 seconds.
- Still delivery: 3840×2160 hero, 1920×1080 landing image and 1080×1350
  social image.

## Candidate rejection and bounded repair

The direct Qwen Image candidate was rejected because it contained generated
pseudo-copy and a malformed robotic hand. No generative repair is claimed.
The delivery compositor deterministically occludes those regions, replaces the
pseudo dashboard with an unlabeled evidence graph and draws source-bound copy.
Versions `delivery` through `delivery-v4` remain as rejected iteration evidence;
`delivery-v5` is the admitted local-only Qwen baseline.

## V6 concept challenger

`delivery-v6` replaces the generic business-person-plus-chart metaphor with an
original “evidence becomes momentum” engine: evidence fragments converge
through a physical decision structure and leave as one coherent trajectory.
The source contains no people, anatomy, generated text, charts, screens, logos
or pseudo UI, so the delivery no longer hides source defects behind an
artificial dashboard. Deterministic typography is still applied downstream.

The source came from exactly one Codex built-in image-generation call. The
provider did not expose the underlying model, accelerator or controllable seed;
the manifest records those facts instead of presenting it as local Qwen/Metal
execution. The voice, music, 4K mastering and delivery compositor remain the
same governed pipeline. V6 is the current mechanically admitted presentation
challenger, but it is not automatically preferred over V5 without blinded
named-human review.

## Admission boundary

Mechanical delivery readiness is true. Named human blind review, 4A preference,
production effect, causal revenue, Radeon execution and external publication
remain false or unobserved. The artifacts must not be described as market-best,
4A-proven or production-effective until those independent gates pass.
