# Architecture

## Runtime flow

1. `PhotographerAgent` validates the image and user request and starts a
   request-scoped audit trail.
2. `ToolRegistry` checks every tool against `PermissionPolicy` before
   invocation and records device, safe input/output summaries, status, and
   elapsed time.
3. `IntentRouter` selects a private editing, shooting, or hybrid path. This
   preserves the strongest product behavior from the original Aperture demo.
4. `VisionAnalyzer` loads Qwen2.5-VL-3B-Instruct on the ROCm device and returns
   structured photographic observations.
5. `CompositionChecker` verifies that composition evidence is actionable.
6. `PhotographyPlanner` converts grounded observations into camera starting
   points, framing, subject direction, lighting, shot list, capture sequence,
   fallbacks, and success checks.
7. `PlanCritic` verifies evidence, mode-specific actions, shot/camera
   specificity, preservation constraints, and delivery checks.
8. One bounded deterministic refinement is allowed when the critic finds a
   problem. It cannot invent new visual evidence.
9. The VLM returns strict structured pose JSON for body rotation, shoulders,
   head, hands, gaze, expression, plus distance/angle/height/background guidance.
   Relative camera position is deliberately excluded because a single image
   does not provide reliable left/right/front/back evidence.
10. `PoseAnalyzer` validates that contract and records whether a bounded,
    evidence-based fallback was required.
11. `PersonSegmenter` runs local torchvision Mask R-CNN and extracts the real
    primary-person mask contour.
12. `PoseCardRenderer` deterministically draws a fixed 1600×1100 editorial
    poster: reference hero, observation column, subject-contour hero and labels,
    plus a compact photographer field strip. CLI or HTTP returns PNG and JSON.

## Agent toolchain and orchestration

The implementation is framework-neutral: Agent capabilities are expressed as
registered tools with stable names instead of depending on a closed Agent
platform. The current manifest contains `intent_router`, `vision_analyzer`,
`composition_checker`, `photography_planner`, `plan_critic`, `plan_refiner`,
`pose_analyzer`, and `pose_card_renderer`.

The orchestrator performs a real multi-step workflow rather than a single model
call. Each result contains:

- `tool_manifest`: available tools, device, and requested permissions;
- `tool_calls`: ordered invocation records with timing and status;
- `agent_trace`: higher-level workflow nodes;
- `permission_audit`: decisions made before invoked tools run.

The critic may trigger exactly one bounded `plan_refiner` pass. It cannot loop
indefinitely or add unsupported visual claims.

## Permission and privacy boundary

`PermissionPolicy` allows only user-authorized image reads, local GPU inference,
and temporary result writes. External network access, persistent prompt/image
storage, and generated replacement images are denied by default. Unknown
permissions fail closed.

The VLM resolver accepts only an existing local model directory or an already
downloaded Hugging Face snapshot. It raises a clear error instead of
downloading a model during core inference. The web handler deletes uploaded
images and rendered temporary files in a `finally` block and returns no session
memory.

## ROCm boundary

PyTorch exposes the same `torch.cuda` frontend for CUDA and HIP backends.
This project requires:

```python
torch.cuda.is_available() is True
torch.version.hip is not None
```

The application never installs or replaces PyTorch. Model placement uses the
existing ROCm-enabled build and `device_map="auto"`. A Linux file lock prevents
multiple Agent processes from loading competing model copies onto the same GPU.

## Model boundary

The vision layer owns model loading, image verification, offline snapshot
resolution, prompt construction, JSON recovery, and GPU metrics. A
process-scoped singleton keeps the model resident between web requests.

The planner is deterministic and does not invent a second visual description.
There is no generated-image or second-image critic branch in the product flow.

Person segmentation uses `MaskRCNN_ResNet50_FPN_V2_Weights.DEFAULT` from the
installed ROCm-compatible torchvision package. It runs through PyTorch's HIP
backend, keeps one process-scoped model instance, and reports detection,
matching, model-load, and inference metrics. Only person masks matched to
Qwen-VL's primary-person regions are outlined. Runtime loading reads the
checkpoint directly from the local Torch cache and never invokes a download.
A missing checkpoint fails closed with a preparation command. A segmentation
failure degrades to labels-only guidance rather than a synthetic box, skeleton,
or rough silhouette.

Action labels reference `people_boxes` by index and use semantic anchors:
`head`, `body`, `hands`, `feet`, or `between`. Validation removes vague labels,
remaps indices after tiny-bystander filtering, infers obvious anchor corrections
from the label text, and prevents distraction boxes from covering primary
people. A short VLM retry fills missing labels. Prop contradictions receive one
bounded VLM correction; malformed correction JSON is contained and recorded.
Any remaining prop-specific fallback is explicitly reported as
`vlm+validated_fallback`.

## Product migration

The original Aperture demo used an external GPT-compatible API. The AMD version
keeps its intent routing and photographic planning concepts while moving image
understanding to a local Qwen2.5-VL checkpoint on Radeon + ROCm:

```text
Old: user + image -> external API -> shooting/editing advice
AMD: user + image -> local VLM -> pose JSON -> planner -> critic -> deterministic execution card
```

## Presentation boundary

`src.web` uses only the Python standard library. It accepts JPEG/PNG/WebP up to
20 MB, stores the upload in a temporary file, serializes inference on one GPU,
returns the deterministic execution-card PNG as a data URL and removes temporary files in
a `finally` block. Requests for concept generation are rejected.

## Post-hackathon extensions

- camera EXIF and lens-aware recommendations
- horizon/key-line detection
- optional fine-grained hand and face gesture analysis
- optional EXIF-aware recommendations
- local, user-controlled session history
- camera tethering and voice capture
