# Autotuner Benchmark Protocol

## Purpose

This protocol defines how to produce fair and reproducible Radeon evidence for the final Autotuner submission.

## Frozen inputs

Record these values before testing:

1. Radeon product name.
2. GFX target.
3. Radeon memory capacity.
4. Host operating system and kernel.
5. AMD driver version.
6. ROCm version.
7. vLLM version.
8. Container image digest.
9. Model identifier and exact revision.
10. Draft model identifier and exact revision when used.
11. Experiment configuration commit.

Save the machine record:

```bash
autotuner inspect artifacts/final_radeon_run/hardware.json
```

## Workload

Use one prompt set that represents the final application scenario. Include a mixture of explanation, code generation, structured output, and operational reasoning prompts. Keep prompts identical for every candidate.

Use the same values for:

1. Request count.
2. Concurrency.
3. Maximum output tokens.
4. Warmup request count.
5. Context length.
6. Quality checks.
7. Error and latency limits.

Do not run unrelated GPU workloads during measurement.

## Measurement sequence

1. Reboot or otherwise return the machine to a known idle state.
2. Capture the hardware record.
3. Run the stock baseline once to populate model caches.
4. Start the recorded Autotuner run.
5. Preserve every accepted and rejected trial.
6. Select the strongest accepted preset.
7. Run the stock baseline three clean times without `rocprofv3`.
8. Run the winning preset three clean times without `rocprofv3`.
9. Report the median throughput and the associated p95 latency for both.
10. Run one representative baseline and one winning trial with `rocprofv3` for supporting evidence.

## Required metrics

1. Output tokens per second.
2. P50 request latency.
3. P95 request latency.
4. Error rate.
5. Response validity score.
6. Peak measured Radeon memory.
7. GPU use samples.
8. Power samples when available.

## Acceptance rule

A candidate may win only when it meets the quality floor, latency limit, and error limit declared before the run. A faster candidate that violates any limit must remain rejected.

## Reported improvement

Calculate:

```text
improvement percent = ((winning throughput / baseline throughput) minus 1) times 100
```

Report both raw values and the percent change. Do not generalize the result beyond the declared model, GPU, software versions, and request distribution.

## Artifact review

Confirm that the final directory contains:

1. `hardware.json`
2. `run.json`
3. `best_preset.json`
4. `engineering_report.md`
5. `dashboard.html`
6. Trial server logs
7. Trial telemetry
8. Selected profiler output

## Integrity rules

1. Never label simulation output as Radeon evidence.
2. Never discard a failed trial from the machine record.
3. Never change the workload between baseline and winning runs.
4. Never report a result without its constraints.
5. Preserve the exact configuration used in the video.
