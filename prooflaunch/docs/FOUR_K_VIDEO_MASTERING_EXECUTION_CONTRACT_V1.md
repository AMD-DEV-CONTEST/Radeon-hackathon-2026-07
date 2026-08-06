# 4K Video Mastering Execution Contract V1

This contract controls the last mile around existing video models. It does not
claim that a local renderer replaces Wan, LTX, SeedVR2, rCM, Causal Forcing, or
a mature Comfy workflow.

## Observed local mechanics

- The master timeline is fixed to eight seconds, 24 FPS, and 192 frames.
- Director, Identity Guardian, and A/V Quality Editor are distinct roles.
- Three shots form a validated DAG and cover every frame without a gap.
- Every shot start and end is content-addressed as a keyframe.
- Product, logo, motion, and camera constraints are located on observed frames.
- Five temporal reward dimensions have independent values and locators.
- Single-card training or distillation of a teacher at or above 10B parameters
  is rejected; a frozen, pinned distilled checkpoint may be reused.
- Frame fallback is admitted only inside an observed small failure box and may
  not overlap a protected product or logo.
- Chunk windows overlap and VAE tiles cover an exact approved 4K canvas.
- Pronunciation, safe-zone, exact product pixels, flicker, motion continuity,
  A/V event alignment, and cross-media claim lineage fail closed.

Six project-owned 3840×2160 boundary frames exercise those mechanics. They are
mechanical Pillow composites, not generative-model outputs and not an encoded
video. Their purpose is to prove enforcement before scarce GPU work begins.

## Still required

The pack remains planned until real pinned-revision runs exist for Wan2.2 5B,
Wan I2V, LTX fallback, SeedVR2, rCM, and Causal Forcing. It also needs an
encoded landscape, portrait, and square 4K master; observed -16 LUFS and
-1 dBTP audio; mature workflow baselines; Video Evidence; Distillation
Evidence; and a frozen Video Pack. All these fields remain null in
`evidence/v10/video-pack-card.planned.json`.

The competition core remains Radeon-local. Third-party APIs may only support
development, teacher-data work, or evaluation under the inference gateway's
license, privacy, budget, and provenance controls; they cannot satisfy the
Radeon-local inference requirement.
