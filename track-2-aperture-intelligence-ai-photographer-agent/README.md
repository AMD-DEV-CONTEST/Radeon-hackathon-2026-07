# AI Photographer Agent

Private multimodal photography agent for **AMD AI DevMaster Hackathon · Track 2**.
It runs Qwen2.5-VL-3B-Instruct locally with AMD Radeon + ROCm. Given a reference
image and a request, it understands the people–environment relationship, tells
both photographer and subject what to do, and returns a deterministic **AI
Photography Guidance Card**. The card combines the local reference thumbnail,
structured VLM guidance, and a real person-mask contour; it never generates an image.

No reference image or prompt is sent to an external AI API.

## What is implemented

```text
Image + request
  → Intent Router (shooting / photo_edit / hybrid)
  → Vision Analyzer (local Qwen2.5-VL-3B)
  → Composition Checker
  → Photography Planner
  → Plan Critic
  → one bounded refinement when required
  → Pose Analyzer (strict structured JSON)
  → local person segmentation + contour extraction
  → deterministic PIL Pose Card Renderer
  → tool-call + permission audit
  → JSON result + local web presentation
```

The output is a stable 1600×1100 editorial poster: a large reference frame and
observation column, a hero subject contour with image-specific direction labels,
and a compact photographer field strip with calibrated distance, shooting
angle, camera height, and background treatment. Relative left/right/front/back
camera position is intentionally omitted because it is not reliably observable
from a single reference image. Qwen-VL outputs the labels as structured JSON; ordinary
PIL/SVG-style drawing code controls every pixel in the card. The current visual
system uses a low-saturation Morandi palette, Marching-Squares mask tracing,
Chaikin-smoothed dual-contrast contours, multi-scale face/hand detail emphasis,
a 10% larger subject, and real-mask label anchors.

For the competition recording, use the fixed cases in
`submission/evidence/DEMO_CASES.md` and the timed English narration in
`docs/demo_script.md`. The single-phone portrait is the live case; longer group
evidence must be shown with its pre-generated disclosure.

If required fields are missing, the result records
`vlm+validated_fallback` instead of presenting the fallback as pure VLM output.

Every stage is a registered Agent tool. The registry checks permissions before
execution and records safe input summaries, device, status, output summary, and
latency. Core tools may read the current upload and use the local GPU; external
network access, persistent storage, and replacement-image generation are
denied.

## Verified Radeon Cloud environment

| Item | Verified value |
|---|---|
| Python | 3.12.3 |
| PyTorch | 2.13.0+rocm7.2 |
| HIP runtime | 7.2.53211 |
| GPU | AMD Radeon Graphics |
| VRAM | 47.98 GiB |
| `torch.cuda.is_available()` | `True` |
| Default model | Qwen2.5-VL-3B-Instruct, local |

PyTorch intentionally retains the `torch.cuda` public API on ROCm. A valid AMD
environment has both `torch.cuda.is_available() == True` and a non-null
`torch.version.hip`.

**Do not reinstall `torch` and do not install a CUDA wheel.** The cloud image
already contains its matched ROCm build. `requirements.txt` deliberately omits
Torch.

Check the environment without modifying it:

```bash
source /workspace/venv/bin/activate
cd /workspace/AI-Photographer-Agent
python scripts/check_environment.py
```

## Run the web demo

```bash
source /workspace/venv/bin/activate
cd /workspace/AI-Photographer-Agent
./scripts/run_web.sh
```

Open `http://127.0.0.1:7860`. For a remote instance, use the Radeon Cloud/Jupyter
port route or an SSH tunnel:

```bash
ssh -L 7860:127.0.0.1:7860 <radeon-cloud-host>
```

The first request loads Qwen-VL; later requests reuse it. The web UI returns the
text lesson and deterministic execution card, without a generated image.

The pose-card renderer uses the official torchvision
`maskrcnn_resnet50_fpn_v2` person segmentation weights. Download them once
before the first demo (this does not install or replace PyTorch):

```bash
python scripts/download_person_segmenter.py
```

The segmenter matches COCO person masks to the primary-person regions grounded
by Qwen-VL. This keeps background tourists out of the lesson. If segmentation
cannot run, the card keeps its action labels and stable layout but deliberately
does not invent a geometric person outline.

## Run the CLI

Stop the web process first, then:

```bash
source /workspace/venv/bin/activate
cd /workspace/AI-Photographer-Agent

python -m src.main \
  --image submission/evidence/samples/01_single_with_phone.jpg \
  --request "Show me how to recreate this portrait, including the phone action and gaze." \
  --card-output demo/ai_photography_execution_card.png \
  --output demo/demo_result.json
```

The loader automatically resolves the existing Hugging Face snapshot in
`/root/.cache/huggingface`. Set `QWEN_MODEL_PATH` only when using another fully
local checkpoint.

## Test

Fast test suite:

```bash
cd /workspace/AI-Photographer-Agent
/workspace/venv/bin/python -m unittest discover -s tests -v
```

Repeated real-GPU smoke test:

```bash
/workspace/venv/bin/python tests/gpu_smoke.py \
  --image submission/evidence/samples/01_single_with_phone.jpg \
  --runs 3 \
  --output demo/gpu_smoke_results.json
```

Full Agent stability benchmark:

```bash
/workspace/venv/bin/python scripts/benchmark_agent.py \
  --image submission/evidence/samples/01_single_with_phone.jpg \
  --image submission/evidence/samples/03_group_three_people.jpg \
  --runs 10 \
  --output demo/full_agent_benchmark.json
```

The final public product path passes **71/71 tests** on Radeon Cloud. The full
development workspace shown in the demo passed 76/76; five historical tests
belonged to retired generation experiments and are intentionally excluded from
this public, non-generative release.

Three fresh English UI cases were then run on the same Radeon instance:

| Final case | End-to-end Agent time | Peak allocated VRAM |
|---|---:|---:|
| Single portrait with JSON repair | **82.376 s** | 7.558 GiB |
| Single portrait without a prop | **57.867 s** | **10.403 GiB** |
| Three-person graduation group | **59.569 s** | 10.385 GiB |

These are measured full Agent paths, not synthetic estimates. The live demo
also exposes the narrower warm visual-inference timing separately so it is not
confused with end-to-end latency. An earlier nine-run regression campaign is
summarized in `submission/evidence/RELEASE_CANDIDATE_REPORT.md` as historical
stability evidence.
The result reports `pose_source = vlm`, `image_generation_model_used = false`,
and `vlm_generated_image = false`.

The default real-GPU web path returns the reference-based execution card,
localized primary people, structured
tool and permission audits, and `preview.status = disabled`. See
[`docs/test_report.md`](docs/test_report.md).

## Layout

```text
AI-Photographer-Agent/
├── README.md
├── requirements.txt
├── docs/
│   ├── architecture.md
│   ├── demo_script.md
│   ├── environment_report.md
│   ├── photography_plan.schema.json
│   ├── submission.md
│   ├── track2_compliance.md
│   └── test_report.md
├── scripts/
│   ├── benchmark_agent.py
│   ├── check_environment.py
│   ├── download_person_segmenter.py
│   ├── package_submission.sh
│   └── run_web.sh
├── src/
│   ├── agent/
│   │   ├── intent.py
│   │   ├── orchestrator.py
│   │   ├── permissions.py
│   │   ├── planner.py
│   │   ├── tool_registry.py
│   │   └── critic.py
│   ├── vision/
│   │   ├── pose_analyzer.py
│   │   └── vlm_inference.py
│   ├── tools/
│   │   ├── scene_analyzer.py
│   │   ├── composition_checker.py
│   │   ├── segmentation.py
│   │   ├── pose_card_renderer.py
│   │   ├── person_segmenter.py
│   │   └── image_health.py
│   ├── main.py
│   └── web.py
├── web/demo.html
├── tests/
├── submission/evidence/    # licensed samples, outputs, timings, and audit JSON
├── models/
└── demo/
```

## Privacy and safety boundaries

- Local model weights and local inference only.
- No external GPT-compatible endpoint or bundled API key.
- The reference thumbnail stays local and is intentionally included in the card.
- Person contours come from local model segmentation, not manual retouching.
- No generated or fabricated target-pose person is drawn.
- Generated replacement and concept images are disabled in the product flow.
- Camera settings are starting points and must be metered on location.
- Uploaded web images are deleted immediately after each request.

Build a clean submission archive that excludes unsupported generation
experiments and historical output files:

```bash
./scripts/package_submission.sh
```

## Model weights and reproducibility

The public, reproducible competition path uses the official
`Qwen/Qwen2.5-VL-3B-Instruct` checkpoint and torchvision's official
`maskrcnn_resnet50_fpn_v2` weights. Model weights are **not** bundled in this
repository or in the submission archive.

The participating team at Aperture Intelligence also maintains an optional proprietary
photography-domain checkpoint. It is not included, is not required to reproduce
the submitted demo or evidence, and does not change the tool, privacy, Planner,
Critic, segmentation, or deterministic rendering architecture. The official
open checkpoint remains the documented default.

Licensed release-candidate inputs, source attribution, and the nine-run summary
are under `submission/evidence/`. Final English demo
materials, the project PDF, presentation, video, and fresh result JSON are under
`submission/final/`.
