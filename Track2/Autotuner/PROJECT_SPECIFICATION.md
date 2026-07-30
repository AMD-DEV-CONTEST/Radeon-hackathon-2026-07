# Autotuner Project Specification

## Project identity

Application name: Autotuner

Track: Track 2, Agentic AI

Team: Velocity

Primary platform: AMD Radeon GPU with ROCm

Deployment model: Private local inference

## Executive summary

Autotuner is a local performance engineering agent for language model serving on AMD Radeon GPUs. The agent profiles a declared serving workload, forms a testable hypothesis, selects one candidate from a bounded configuration space, runs the candidate on the same Radeon GPU, measures the outcome, applies quality and reliability gates, and repeats. It exports a reproducible preset, machine readable evidence, a visual dashboard, and a human readable engineering report.

The product makes the optimization process visible. During the demonstration, the audience sees baseline output speed, every hypothesis, accepted and rejected candidates, and the final improvement. The model that advises the search is the model served by the Radeon deployment under test.

## Problem definition

ROCm exposes strong performance capabilities, but practical local inference speed depends on choices distributed across the serving stack. A developer must reason about the model representation, quantization, attention implementation, cache dtype, sequence capacity, context length, memory reservation, request concurrency, and speculative decoding. Compatibility and performance can change across GPU architecture, model shape, serving version, and workload.

This creates three user problems:

1. A working deployment may leave significant performance unused.
2. Manual tuning requires scarce systems expertise and repeated experimentation.
3. Results are often shared as isolated command snippets without the workload, constraints, hardware record, or raw evidence required for reproduction.

Autotuner treats tuning as a local agent task with controlled execution and durable evidence.

## Target users

### Independent Radeon AI developer

The developer has a supported Radeon GPU and wants faster local code assistance, document analysis, or creative inference without sending prompts to a hosted service.

### Enterprise platform engineer

The engineer must deploy a private model on Radeon workstations and needs a repeatable process that protects latency, reliability, and response validity.

### ROCm application maintainer

The maintainer wants to compare serving presets across models, ROCm releases, and Radeon architectures, then submit evidence backed defaults to an application repository.

### AMD developer advocate

The advocate needs a clear artifact that teaches developers how Radeon performance changes in response to real serving controls.

## Application scenarios

1. Tune a local coding assistant before it is distributed to a development team.
2. Compare full precision and quantized variants of the same model family under a fixed quality gate.
3. Find a safe concurrency and memory reservation for an interactive private assistant.
4. Test ROCm attention backends for a specific model and Radeon architecture.
5. Evaluate cache dtype choices for a long context retrieval agent.
6. Produce a reviewable preset and report for an upstream application.

## System architecture

![System architecture](assets/architecture.svg)

### Control plane

The Python controller loads an experiment contract, enumerates valid candidates, manages trial state, and writes durable artifacts. It has no external Python dependencies.

### Local reasoning plane

After a measured trial, the active local model receives compact benchmark history, declared constraints, and a shortlist of allowed candidates. It returns one candidate identifier and one hypothesis. The response is rejected if the identifier is not in the allowlist.

### Serving plane

The managed adapter launches vLLM with the selected model and candidate settings. Environment variables select a compatible Radeon attention backend. Server arguments control cache dtype, maximum sequences, context length, memory utilization, quantization, and optional speculative decoding.

### Measurement plane

The benchmark client sends a fixed request distribution with declared concurrency and generation length. `rocm-smi` samples Radeon use, power, and memory. Selected trials can run under `rocprofv3` with HIP tracing and summary statistics.

### Evidence plane

Every run produces a complete JSON record, per trial logs and telemetry, the best preset, a visual HTML dashboard, and an engineering report.

## Agent loop

1. Inspect

The controller records the system, GPU identity, GFX target, Python version, vLLM version, ROCm tools, and available profiling tools.

2. Baseline

The first value in every search dimension defines the stock candidate. This makes the comparison explicit and reproducible.

3. Hypothesize

The active local model receives only the evidence and candidate shortlist needed for the next decision. If local inference fails, a constraint aware heuristic continues the run.

4. Experiment

The controller constructs an allowlisted command without a shell, starts the serving process, waits for readiness, performs warmup, and runs the fixed workload.

5. Measure

The controller calculates output tokens per second, p50 latency, p95 latency, error rate, response validity, and peak measured Radeon memory.

6. Gate

A candidate is rejected when quality is below the floor, error rate is above the limit, or p95 latency is above the limit.

7. Learn

Observed factor performance and controlled change distance guide the next shortlist. The local model uses the same history for technical judgment.

8. Export

The strongest accepted candidate becomes a portable preset with a configuration diff and complete evidence.

## Core capabilities

1. Private local agent reasoning.
2. Bounded tool use and candidate validation.
3. Managed vLLM lifecycle.
4. Adaptive configuration search.
5. Real workload benchmarking.
6. Radeon telemetry.
7. Optional ROCm profiling.
8. Quality and reliability constraints.
9. Failure recovery.
10. Reproducible artifact generation.
11. A deterministic development simulation.

## Model introduction

The reference configuration uses the Qwen 3 model family because it provides instruction tuned models at sizes suitable for local experimentation and includes quantized variants. The exact final model must be selected after confirming the Radeon memory available to the participant.

Autotuner is model agnostic at the controller layer. Any model served through the local vLLM OpenAI compatible interface can provide benchmark responses and agent decisions. A smaller draft model can be declared for speculative decoding when the model pair and vLLM release are compatible.

The model performs two roles:

1. It serves the target user workload.
2. It studies measurements from its active deployment and chooses the next bounded experiment.

No hosted frontier model is required.

## Local deployment plan

### Recommended runtime

The reference environment is the official AMD ROCm vLLM RDNA container on Ubuntu 24.04. It includes PyTorch and vLLM builds aligned with ROCm for supported Radeon architectures.

### Network posture

The endpoint binds to `127.0.0.1` by default. Benchmark prompts, model responses, and engineering reports remain local.

### Model storage

Model files use a persistent local Hugging Face cache or a mounted storage volume. Exact model revisions should be recorded for the final benchmark.

### Controller installation

The controller is a standard Python package with no third party runtime dependency. It can be installed directly into the ROCm vLLM container.

### Hardware path

The hackathon Radeon Cloud guide provides a Notebook workflow. A local Linux Radeon workstation may use the same official container with `/dev/kfd` and `/dev/dri` access.

## Radeon and ROCm optimization strategy

### Attention backend

vLLM can select an attention backend automatically or accept a Radeon compatible backend through `VLLM_ATTENTION_BACKEND`. The reference search includes automatic selection, `ROCM_ATTN`, and `TRITON_ATTN`. AITER choices are intentionally opt in because support depends on the ROCm image and GPU architecture.

Autotuner does not present rocWMMA as a universal on or off switch because serving engines expose higher level backend choices. A rocWMMA based implementation can be registered as a named engine or backend profile when the target runtime provides it.

### KV cache dtype

The search can compare automatic cache dtype with FP8 cache storage when the platform and model support it. Reduced cache memory can increase available concurrency, but the candidate must pass response validity and workload quality checks.

### Quantization

Model variants can pair a model identifier with its quantization method. This supports controlled comparison of full precision and AWQ variants while preserving the declared workload and limits.

### Scheduler capacity

`max_num_seqs` changes the amount of concurrent work available to the scheduler. The best value depends on request shape, memory, and interactive latency.

### Radeon memory reservation

`gpu_memory_utilization` controls how much device memory vLLM may reserve. More capacity can improve cache availability, while an aggressive value can cause instability. Failed candidates are rejected and the run continues.

### Context length

`max_model_len` controls memory demand and the shape of attention work. The final search should use the context length required by the target application.

### Speculative decoding

An optional draft model and token count can be searched when a compatible pair is available. Autotuner treats the pair as one controlled candidate and verifies its end result.

### Workload controls

Prompt distribution, request count, generation length, concurrency, warmup, and limits are committed in one JSON experiment contract.

### Profiling

Selected trials run under `rocprofv3` with HIP tracing and summary statistics. This connects application throughput changes to ROCm execution evidence.

## Optimization objective

The primary objective is accepted output tokens per second.

A result is eligible only when:

1. Response validity meets the configured quality floor.
2. Request error rate stays below the configured limit.
3. P95 latency stays below the configured limit.

The engineering report includes baseline performance, winning performance, percent improvement, the configuration diff, every trial decision, and the raw artifact locations.

## Security design

The model never supplies a command. It selects one opaque identifier from a controller generated allowlist. The controller resolves that identifier to a typed candidate and builds process arguments without shell evaluation.

The controller owns only the process group that it starts. It does not inspect unrelated user files or terminate unrelated workloads.

The local endpoint is private by default. Publishing artifacts remains an explicit participant action.

## User experience

The terminal prints each candidate, hypothesis, throughput, p95 latency, and acceptance result as the experiment runs. The HTML dashboard turns the same evidence into a visual timeline with an immediate baseline versus best comparison.

The final user receives three levels of detail:

1. A winning preset for direct reuse.
2. A human readable report for review.
3. Raw JSON, telemetry, logs, and profiler output for verification.

## Innovation and differentiation

GEAK V4 demonstrates agent driven kernel and serving optimization on AMD Instinct systems. Autotuner focuses on the local Radeon deployment experience. Its contribution is the combination of self hosted agent reasoning, consumer memory constraints, bounded configuration search, application level acceptance gates, and reviewable preset export.

The self reference is functional rather than cosmetic. The active deployment provides the reasoning used to select its next configuration. Every measured trial is simultaneously a product action, optimization experiment, and judging artifact.

## Business value

Local AI adoption is limited when every deployment needs manual performance engineering. Autotuner packages a repeatable part of that work into a private tool. It can reduce deployment effort, create shared organizational knowledge, and make Radeon serving results easier to reproduce.

The reusable artifact has value beyond one benchmark. Teams can commit presets beside their application, compare results across machines, and review performance changes with the same evidence discipline used for source code.

## Evaluation plan

### Functional evaluation

1. Run hardware inspection.
2. Validate the experiment contract.
3. Execute at least eight candidates.
4. Show one rejected candidate without ending the run.
5. Show a local model generated hypothesis.
6. Open the exported dashboard and report.
7. Apply the winning preset and repeat the benchmark.

### Radeon performance evaluation

1. Record the exact GPU, GFX target, ROCm release, vLLM release, model revision, and container image.
2. Run the stock baseline at least three times.
3. Run the winning candidate at least three times.
4. Report median output tokens per second and p95 latency.
5. Preserve raw run records and profiler output.
6. Do not present simulation results as hardware evidence.

### Success criteria

1. The full run completes without hosted inference.
2. The agent selects valid candidates from the allowlist.
3. Unsupported candidates are rejected safely.
4. The winning candidate meets all declared limits.
5. The final preset reproduces its result within a reasonable variance band.
6. The demonstration shows a measurable improvement over the stock baseline.

## Limitations

1. The current quality gate measures successful nonempty responses and optional required terms. Final evaluation should use a curated prompt suite with task specific checks.
2. Hardware support for FP8 cache, quantization kernels, attention backends, and speculative decoding varies.
3. `rocprofv3` adds overhead, so profiled trials should be interpreted separately from final clean benchmarks.
4. Performance results are workload specific.
5. The checked in sample is simulated and is not Radeon evidence.

## Deliverables

1. Complete Python source.
2. Dockerfile based on the official AMD RDNA vLLM image.
3. Live Radeon experiment configuration.
4. Deterministic simulation configuration.
5. Automated tests.
6. Reproducibility README.
7. Project specification.
8. Benchmark protocol.
9. Demonstration script.
10. Supplementary poster.
11. Sample dashboard and engineering report.
12. Final Radeon run and video after hardware execution.

## Team

### Govind

Role: Project lead and developer

Contributions include concept design, agent workflow, implementation, Radeon experiment design, validation, documentation, visual presentation, and demonstration production.

### Shreeya Dasa

Role: Applied machine learning and LLM systems

Profile: [github.com/dasashreeya](https://github.com/dasashreeya)

Contribution focus includes LLM systems review, evaluation design, benchmark interpretation, production AI perspective, demonstration validation, and submission review.

## References

1. [AMD vLLM inference and serving on ROCm](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/inference/vllm.html)
2. [AMD rocprofv3 documentation](https://rocm.docs.amd.com/projects/rocprofiler-sdk/en/develop/how-to/using-rocprofv3.html)
3. [vLLM ROCm attention guidance](https://docs.vllm.ai/en/v0.11.1/getting_started/quickstart/)
4. [vLLM serving interface](https://docs.vllm.ai/en/latest/cli/serve/)
5. [AMD GEAK V4 technical article](https://www.amd.com/en/developer/resources/technical-articles/2026/geak-v4.html)
