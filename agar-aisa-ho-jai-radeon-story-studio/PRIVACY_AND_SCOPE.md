# Privacy, Safety, and Scope Review

This public snapshot was built from committed source at `eba2f1544f03fbc6e7ad6dd137138147e5be3f26`. The original working repository was **not** copied wholesale.

## Entirely excluded

- `codex_inputs/aahj-real-people-context-*` and every private-context archive
- `codex_campaigns/` and historical agent/campaign harnesses
- both nested `gpu_factory` Git repositories and their independent histories
- local `.env`, SSH, Radeon session, cache, virtual-environment, and credential material
- raw/generated rejected media and private model/evidence archives
- model weights, including the 17.7 GB Qwen GGUF
- legacy renderer copies, backup files, patch files, and duplicated self-test outputs
- Google Gemini, Fireworks, ComfyUI experimentation, and other non-core provider adapters
- all working-tree changes and untracked files

## Included image

`assets/accepted-safe-lesson-card.png` is an accepted contest output assembled from fictional Radeon-generated source assets. The builder verifies the committed SHA-256 recorded by the acceptance report and rejects PNG textual/EXIF metadata chunks.

## Claim boundary

- SDXL image inference and Qwen/vLLM inference were executed locally on AMD Radeon through ROCm.
- Deterministic Pillow rendering and FFmpeg encoding are CPU stages.
- Textual safety review is not described as a complete multimodal safety evaluation.
- Rejected candidates are represented by hashes and reasons, not published as artwork.

## Manual checks still required before publication

1. Review the final image, PDF, presentation/poster, and demo video visually.
2. Confirm the final YouTube/video link is accessible to judges.
3. Confirm model, font, framework, and generated-asset attribution.
4. Confirm the chosen source-code license terms.
5. Review the exact Git diff in the official fork before pushing.
