# ADR-0002: Use Ollama through a Replaceable ROCm Provider for Hackathon v0.1

> **AlphaNoah A1 Edge Agent** — *An AMD ROCm-powered industrial asset maintenance edge agent.*

## Status

Accepted for hackathon v0.1

Decision date: 2026-07-22<br>
Implementation status: Provider boundary implemented and fake-tested; Task 03B
records one direct AMD Linux Ollama `qwen3.5:9b` analysis. This is integration
evidence, not a benchmark or proof that every broader target below is complete.

## Context

The competition must demonstrate local inference on an AMD Ryzen AI Max+ 395 / Radeon 8060S (`gfx1151`) using ROCm. The supplied single-machine audit reports a working Ollama path over a llama.cpp HIP backend, AMD GPU use and warm-response behavior for the prototype scenario. Reported as working, but not independently evidenced in the supplied audit material.

The two-week schedule does not justify migrating the judged path to vLLM or maintaining several inference backends. At the same time, making Agent Core depend directly on Ollama request/response types would turn a short-term backend choice into a domain constraint.

## Decision

Use this dependency direction:

```text
A1 Maintenance Runtime
→ LocalModelProvider
→ OllamaROCmProvider
→ Ollama
→ llama.cpp HIP backend
→ ROCm
→ AMD Radeon GPU
```

`LocalModelProvider` is a backend-neutral port. `OllamaROCmProvider` is the hackathon adapter. Agent Core, Skills, state and memory do not depend on Ollama-specific types.

The judged path will:

- keep one selected model resident;
- use `keep_alive` and startup warmup;
- disable unnecessary Thinking for the measured structured-extraction path;
- bound prompt and output sizes;
- validate JSON and planned Pydantic schemas;
- retry a format-only error once at most;
- enforce inference timeout and health checks;
- record model/runtime/GPU evidence, mean latency and P95;
- verify ten sequential runs and an offline run;
- never silently fall back to a cloud model.

## Audited Basis

The task-provided environment audit reports:

- Ubuntu 24.04.4, kernel `7.0.0-28-generic`, ROCm 7.2.0, Radeon 8060S and `gfx1151`;
- `rocminfo` reportedly identifies `gfx1151`;
- observed GPU utilization changes from roughly 1% to roughly 91% during inference;
- Ollama inference is reported on the AMD GPU;
- observed warm response is approximately 1.7–2.7 seconds for the audited prototype workload;
- disabling Thinking is reported to improve throughput;
- one direct Transformers load did not complete within the reported 300-second observation window.

These are single-machine report summaries, not independently reproduced
observations or universal performance commitments. Raw commands, samples, model
revision and prompt settings remain pending human attachment.

## Reasons

- it is the lowest-risk path reported on the target prototype;
- local HTTP isolates model-process lifecycle from the maintenance runtime;
- model residency and warmup are easy to explain and observe;
- the Provider abstraction allows future replacement;
- the decision keeps the competition focused on the closed-loop Agent rather than backend migration.

## Consequences

Positive:

- fewer competition variables;
- clear local/offline architecture;
- a defined path for collecting direct AMD ROCm evidence;
- independent evolution of domain and inference layers.

Negative:

- Ollama behavior and supported models must be pinned and tested;
- vLLM-specific scheduling or throughput capabilities are not available;
- the project must build neutral error and metrics translation;
- structured output reliability still requires measured validation.

## Why vLLM Is Deferred

The current project does not claim vLLM migration or support. Evaluate it after the hackathon only when a pinned `gfx1151` stack, chosen model, benchmark need, offline behavior, memory stability, health/timeout semantics and Provider compatibility are demonstrated.

## Migration Conditions

A replacement backend must:

1. implement the same `LocalModelProvider` contract;
2. run locally on the target AMD/ROCm stack;
3. pass structured-output and offline tests;
4. expose equivalent or better health and metrics evidence;
5. improve a measured constraint rather than only adding novelty;
6. preserve deterministic state and human approval boundaries;
7. have a documented rollback path to the known competition backend.

## Alternatives Considered

### Direct Transformers model loading

Deferred for the main demo because one supplied report did not complete loading
within 300 seconds, while a planning document contains a conflicting 30–60 second
estimate. It may be useful after a reproducible cold-start test resolves the gap.

### vLLM during the hackathon

Deferred because migration risk is higher than its demonstrated benefit for a bounded sequential demo.

### Remote API

Rejected for the judged path because it weakens privacy, offline operation and AMD local-inference evidence.

## References

- Use the [AMD Ryzen AI Max+ 395 Environment Audit Template](../experiments/AMD395_ENVIRONMENT_AUDIT_TEMPLATE.md) for the pending raw environment record and version manifest.
- Use the [ROCm Inference Benchmark Template](../experiments/ROCM_INFERENCE_BENCHMARK_TEMPLATE.md) for reproducible measured results.
- See [External Technical References](../references/REFERENCES.md) for official ROCm, AMD GPU, and Ollama documentation.
- See [AMD ROCm Runtime](../architecture/AMD_ROCM_RUNTIME.md).
