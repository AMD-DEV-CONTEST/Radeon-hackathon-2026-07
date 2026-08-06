# AMD AI DevMaster — Radeon Evidence

## Result

AAHJ successfully ran a locally hosted Qwen3-Coder 30B-A3B GGUF model through
vLLM on an AMD Radeon `gfx1100` GPU and produced a validated seven-scene
children's animal storyboard.

This is a technical storyboard and motion prototype, not the final production
episode.

## Measured Radeon/Qwen execution

- Served model: `qwen3-coder-30b-a3b`
- GPU architecture: `gfx1100`
- Model file size: `17,665,334,432` bytes
- Storyboard scenes: 7
- Cast members: 6
- Storyboard-plan completion tokens: 1259
- Storyboard-plan elapsed time: 14.941 seconds
- Storyboard-plan throughput: 84.264 tokens/second
- Safety-review completion tokens: 315
- Safety-review elapsed time: 5.395 seconds
- Safety-review throughput: 58.389 tokens/second
- Motion scenes validated: 7 of 7
- Semantic action checks passed: 7 of 7

## Pipeline

1. A transcript is supplied to the Radeon-hosted Qwen model.
2. Qwen returns a constrained storyboard plan with cast, scenes, actions,
   backgrounds, narration and child-safety reasons.
3. A second Qwen call independently reviews the textual storyboard for safety
   and continuity.
4. The deterministic preview renderer produces scene images and an action-aware
   animatic.
5. Acceptance checks validate JSON structure, seven-scene transcript coverage,
   distinct frame motion, semantic action landmarks and checksums.
6. A compact evidence archive records the source, metrics and outputs.

## Workload boundary

The AMD Radeon GPU performed Qwen/vLLM inference. The deterministic Pillow
preview rendering and FFmpeg encoding were CPU workloads. The renderer is a
preview and evidence layer; polished production media will use a dedicated
image/video provider while retaining the Radeon planning and validation layer.

## Safety scope

The reported safety pass applies to the structured textual storyboard. It is
not a multimodal safety judgment over the rendered images or video.

## Storyboard result

- Title: Good Morning, Little Friends!
- Visual style requested by the plan: Soft pastel colors, large expressive eyes, simple shapes, and gentle movements
- Final scene: all six animal friends wave good night together.

## Evidence location

- Repository evidence: `reports/amd-ai-devmaster/radeon/20260805T144024Z/`
- Durable private archive: location intentionally omitted from the public submission; the selected evidence needed for review is included under `evidence/qwen/`.
- Handoff archive: `aahj-radeon-hackathon-handoff-20260805T144024Z.tar.gz`
- Archive SHA-256: `d5a35a953ad145dc4eec9d43d074f845aaca3a2b3e5c21b9b24a401ea068c71e`

The 17.7 GB model is intentionally excluded from Git and from the compact
handoff archive.
