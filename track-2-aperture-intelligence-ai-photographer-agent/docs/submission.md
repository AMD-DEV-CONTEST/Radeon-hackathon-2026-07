# Hackathon submission guide

## One-sentence pitch

Aperture is a fully local AI Photographer Agent on AMD Radeon + ROCm: it
understands a private reference photo, orchestrates photography tools, creates
an executable plan, and returns a deterministic AI Photography Guidance Card.

## Problem

Generic image assistants describe a picture but rarely translate the
subject–environment relationship into actions a photographer and subject can
execute. Cloud endpoints also create privacy and connectivity concerns for
personal photos.

## AMD contribution

- Qwen2.5-VL-3B and Mask R-CNN execute locally through ROCm-enabled PyTorch.
- The Radeon environment keeps the VLM resident for repeated requests.
- The demo exposes HIP, GPU, VRAM, cold/warm latency, and tool timings.
- Core inference is offline-only and fails closed if the local checkpoint is
  missing.

## Track 2 capabilities

This submission demonstrates three of the five minimum-function categories:

1. **Tool invocation** — every operation is registered, permission-checked,
   timed, and returned in `tool_calls`.
2. **Multi-step task planning** — intent routing, grounded vision analysis,
   composition checking, planning, criticism, one bounded refinement, person
   pose-schema validation, segmentation, and deterministic card rendering.
3. **Permission control and privacy protection** — local image-read and GPU
   permissions are explicitly allowed; external network, persistent storage,
   and replacement-image generation are explicitly denied.

The orchestration layer is framework-neutral Python. Transformers and PyTorch
ROCm provide the open-source model runtime without depending on a closed Agent
platform.

## Agent toolchain

```text
intent_router
  → vision_analyzer               [local Radeon GPU]
  → composition_checker
  → photography_planner
  → plan_critic
  → plan_refiner (at most once)
  → pose_analyzer
  → pose_card_renderer            [local Radeon GPU]
```

Each result includes:

- `tool_manifest`
- `tool_calls`
- `permission_audit`
- `privacy`
- `agent_trace`
- GPU and latency `metrics`

## Verified evidence

- Environment: PyTorch 2.13.0+rocm7.2, HIP 7.2.53211, AMD Radeon Graphics,
  47.98 GiB VRAM, `torch.cuda.is_available() == True`.
- Final public non-generative suite: 71/71 passed on Radeon Cloud.
- Full development workspace shown in the demo: 76/76 passed; five historical
  generation-experiment tests are deliberately absent from the public package.
- Fresh single portrait with JSON repair: 82.376 s end to end.
- Fresh no-prop portrait: 57.867 s end to end.
- Fresh three-person group: 59.569 s end to end.
- Maximum allocated VRAM across the fresh English cases: 10.403 GiB.
- The result records `pose_source = vlm` and both image-generation flags false.

The 82.376-second portrait includes one bounded JSON repair. The evidence is
retained as measured rather than presented as a synthetic average. The earlier
nine-run stability matrix remains available as historical regression evidence.

## Demo video (4 minutes 50 seconds)

1. Open the web UI and show the live Radeon + ROCm badge.
2. Point out that external AI APIs, external network access, and persistent
   memory are disabled.
3. Upload a portrait; the fixed local workflow generates photographer, pose,
   hand, and gaze guidance without a separate text prompt.
4. Show the scene and subject–environment analysis.
5. Show the executable photographer and subject instructions.
6. Reveal the three-region guidance card and its image-specific pose labels.
7. Open the Tool Invocation section and walk through each completed tool.
8. Open Permission Audit and show the local allow/remote deny policy.
9. Show the full benchmark report with success rate, P50/P95, and peak VRAM.

## Claims that can be demonstrated

- local Radeon/HIP inference with measured GPU evidence;
- offline Qwen2.5-VL and Mask R-CNN checkpoints;
- registered, audited tool invocation;
- multi-step planning and bounded critic refinement;
- explicit deny-by-default permission control;
- the private reference thumbnail remains local and is intentionally shown in the card;
- temporary web uploads deleted after every request;
- working CLI, HTTP API, responsive local UI, automated tests, and repeated
  real-GPU benchmark artifacts.

## Product boundary

The product does not generate a replacement photograph. The input image remains
local and supplies the reference thumbnail plus real segmentation contour. The
downloadable teaching result is a deterministic three-region guidance card;
no VLM or image-generation model controls its pixels.
