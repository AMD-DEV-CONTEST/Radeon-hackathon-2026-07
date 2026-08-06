# Demo video script (target: 4 minutes 15 seconds)

This script is designed for a single continuous recording on AMD Radeon Cloud.
The single-person case is run live. The longer group result is opened from the
auditable evidence generated on the same cloud instance; the video must label
the shortened waiting period instead of implying instant inference.

## Before recording

- Start the local web service and verify `/api/health` reports `ready`.
- Keep the browser at the empty workbench before recording.
- Keep a terminal ready with `rocm-smi` and the environment-check command.
- Use `submission/evidence/samples/01_single_with_phone.jpg` for the live run.
- Keep the final group card and JSON ready in
  `submission/evidence/results/03_group_three_people/`.
- Close unrelated tabs and hide any credentials, SSH addresses, or private data.
- Do not show or claim use of the optional internal checkpoint. The submitted
  evidence uses the official `Qwen/Qwen2.5-VL-3B-Instruct` checkpoint.

## Recording script

### 0:00-0:25 — Problem and product

**On screen:** Empty AI Photographer workbench.

**Narration:**

> A reference photo can be easy to like but difficult to reproduce. Most image
> assistants describe what they see; they do not tell ordinary users what to do
> on location. Aperture is a fully local AI Photographer Agent that converts a
> private reference photo into an executable photography guidance card.

### 0:25-0:50 — AMD Radeon and local runtime

**On screen:** Terminal environment report followed by the web health badge.

**Narration:**

> The complete workflow runs on AMD Radeon Cloud with ROCm. This instance has
> 47.98 GiB of VRAM, PyTorch 2.13 with ROCm 7.2, and HIP reports the Radeon GPU
> as available. Core vision inference is local. No external AI API is used.

**Show these facts:**

- `torch.cuda.is_available() == True` — PyTorch uses the CUDA-compatible API
  name for both CUDA and ROCm; `torch.version.hip` proves this is the HIP build.
- GPU: `AMD Radeon Graphics`
- HIP: `7.2.53211`
- PyTorch: `2.13.0+rocm7.2`

### 0:50-1:55 — Live single-person workflow

**On screen:** Click the reference-photo area and upload
`01_single_with_phone.jpg`. Keep the loading stages visible, then show the card.

**Narration while the workflow runs:**

> I only provide a photo. The Agent first understands the scene, subject,
> environment, composition, visible props, and visual risks with Qwen2.5-VL-3B.
> It then invokes the Photography Planner, checks the plan with a Critic, extracts
> the real person mask locally, and renders the final card deterministically.
> The model does not generate or replace the photograph.

**Narration after the card appears:**

> The result explains why the reference works, gives concrete body, gaze, and
> hand actions, and tells the photographer the distance, shooting angle, camera
> height, and background treatment. Relative left or right camera position is
> deliberately omitted because it cannot be estimated reliably from one image.

**Recording note:** A warm run is approximately 52 seconds. Do not cut directly
from upload to result. If the wait must be shortened, retain several loading
stages and add the caption `Waiting time shortened; inference ran locally on the
same Radeon instance`.

### 1:55-2:35 — Tool invocation and permission control

**On screen:** Expand Tool Invocation and Permission Audit.

**Narration:**

> This is an Agent workflow rather than a single prompt. Each tool call is named,
> timed, and recorded: intent routing, vision analysis, composition checking,
> planning, criticism, pose normalization, segmentation, and card rendering.
> The permission policy allows local image reading and GPU inference while
> denying external AI APIs, replacement-image generation, and persistent memory.
> Temporary uploads are deleted after each request.

### 2:35-3:15 — Image-specific behavior

**On screen:** Show the no-prop card, then the three-person group card. Put the
case name on screen. Do not rerun the long group case during the final video.

**Narration:**

> The guidance changes with the image. When no handheld prop is present, the
> system uses a concrete two-hand instruction instead of inventing an object.
> In this three-person case, it detects and segments all three foreground people,
> changes the plan to group framing, coordinates gaze and arm spacing, and keeps
> the same stable card structure.

**On-screen disclosure:**

`Pre-generated on this Radeon instance; source image, JSON, timings, and tool
trace are included in the repository.`

### 3:15-3:45 — Performance and stability

**On screen:** Release Candidate report or benchmark summary.

**Narration:**

> Across nine real Radeon runs, nine completed successfully and all nine plans
> passed the Critic. The warm single-person path is approximately 52 seconds.
> Peak allocated GPU memory across the release cases is 10.684 GiB. The longer
> group path is retained honestly at approximately 226 seconds because it uses a
> second grounding pass rather than hiding the latency tail.

### 3:45-4:15 — Closing

**On screen:** Final guidance card and a compact architecture diagram.

**Narration:**

> Aperture turns the implicit decisions of a photographer into actions ordinary
> people can execute. It combines local multimodal understanding, multi-step
> planning, tool invocation, permission control, real-person segmentation, and
> deterministic rendering on AMD Radeon and ROCm. The result is private,
> inspectable, and useful on an actual shoot.

## Claims to avoid

- Do not say the Agent trained Qwen2.5-VL or that public results require a
  private checkpoint.
- Do not call pre-generated group evidence a live real-time run.
- Do not claim the system can infer photographer left/right/front/back position.
- Do not say that the card is generated by an image-generation model.
- Do not expose private photographs, credentials, host addresses, or model
  weight files in the recording.

## One-take recovery lines

- If a request takes longer than expected: `This is local inference; I will keep
  the loading stages visible and show the recorded timing when it completes.`
- If the Critic performs a repair: `The Critic found an incomplete instruction
  and allowed one bounded repair without inventing new image evidence.`
- If the service is not ready: stop recording, verify `/api/health`, restart the
  local service, and begin a fresh take. Do not edit an error into a success.
