# Live Science · Common GPU Generation Policy

This policy applies to all image and video generation tasks in `Re_0`. The phase prompts determine content and quality requirements; this file only specifies common scheduling, acceleration, VRAM safety, and recording practices. In case of conflict, the stricter requirement of the phase prompt takes precedence.

## 1. Optimization order

Optimize in the following order:

1. Avoid OOMs, failures, and wasted reruns;
2. Use low-cost smoke runs to validate input, semantics, and workflow;
3. Reuse hot-loaded models and stable configurations;
4. Only last, optimize single-inference latency.

Do not trade speed by degrading key semantics, structural correctness, start/end constraints, or traceability.

## 2. Before submitting a task

- Confirm the input, model, workflow, output path, and key parameters;
- Confirm the GPU has no other high-VRAM tasks and the ComfyUI queue will not overlap;
- Prefer reusing a validated local environment and workflow; do not install parallel frameworks for a single task;
- Normalize inputs to the target aspect ratio and valid dimensions up front to avoid repeated rescaling inside the pipeline;
- Reserve a safe VRAM margin first, then choose resolution, batch size, frame count, and decoding method.

High-VRAM generation must be serial. You may queue tasks with the same configuration back-to-back, but they must not occupy VRAM concurrently.

The full pipeline uses `Re_0/.pipeline-gpu.lock` to prevent multiple runs from occupying the GPU at the same time; phase scripts must still check the actual ComfyUI queue and cannot rely on the file lock alone.

## 3. Fast validation and batch execution

- Run a smoke test first on one representative, difficult sample;
- Smoke runs use the lowest reasonable resolution, batch size, frame count, or duration sufficient to judge the result;
- When a smoke fails, first fix the input, prompt, anchors, or workflow; do not blindly raise specs to compensate;
- After a smoke passes, run continuously in groups sharing the same model and workflow, reusing checkpoints, text encoders, and node caches;
- Do not generate multiple seeds, purposeless variants, or duplicate references by default.

## 4. VRAM strategy

Start from a configuration that is already working reliably. Only when VRAM is insufficient or near the risk threshold should you, in order, reduce batch size or specs, enable tiled decode, increase model offload, or move the text encoders and VAE to CPU.

CPU offload, CPU VAE, tiled decode, and larger VRAM reservations are mainly stability measures; they may reduce speed and should not be described as acceleration. Do not switch VRAM strategies back and forth without reason within the same batch of tasks, and do not consume the safety margin just to chase full utilization.

## 5. Retries and recording

- Each generated asset gets at most one retry with a clear purpose, unless a phase prompt is stricter;
- Adjust for only one primary failure cause at a time; do not perturb many parameters at once;
- Keep the first result, prompt, workflow, parameters, and failure reason;
- Record at minimum the model and workflow, resolution, batch size or frame count, cold/hot start times, and the lowest remaining VRAM when available;
- Do not record smoke runs, retries, upscale phases, or checks that were not actually executed as complete.
