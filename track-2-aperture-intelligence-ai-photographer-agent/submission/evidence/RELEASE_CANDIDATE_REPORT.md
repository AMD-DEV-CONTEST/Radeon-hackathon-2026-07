# AI Photographer Agent — Release Candidate

Status: **ready for submission packaging**

## Acceptance results

- AMD Radeon + ROCm environment verified.
- Clean public archive tests: **65/65 passed**.
- Real cloud runs: **9/9 completed**.
- Plan Critic: **9/9 passed**.
- Person contours: 1/1, 1/1, and 3/3 matched for the three scenarios.
- Peak allocated VRAM: **10.684 GiB**.
- External AI APIs: **not used**.
- Image-generation models: **not used**.

## Canonical demo scenarios

1. Single portrait with a smartphone
   - Hand label: `Phone`
   - Action: hold it naturally without deliberately displaying it
2. Single portrait without a handheld prop
   - Prop explanation: no extra prop is required
   - Hand label: `Both hands`
   - Action: let the hands rest naturally
3. Three-person group portrait
   - Three foreground people detected and segmented
   - Group framing, shared gaze, arm spacing, and calibrated photographer distance

## Performance

| Path | Result |
|---|---:|
| Warm single-pass portrait | approximately 52 s end to end |
| No-prop bounded-repair average | 116.459 s |
| Three-person two-pass average | 226.018 s |
| Peak allocated VRAM | 10.684 GiB |

## Public repository boundary

The clean archive includes active source code, tests, documentation, the local
web UI, licensed evidence inputs, and canonical outputs. It excludes:

- all model weights and model caches;
- the private `IMG_8091` input and derived files;
- historical generated-image experiments;
- Stable Diffusion and Qwen Image Edit experiments;
- backup files, bytecode, local caches, and internal design-skill files.

The official Qwen2.5-VL-3B-Instruct and torchvision checkpoints are documented
as reproducible defaults. An optional Aperture Intelligence internal photography-domain
checkpoint is not included and is not required for the submitted results.
