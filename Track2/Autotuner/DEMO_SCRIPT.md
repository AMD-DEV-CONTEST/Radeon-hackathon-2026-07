# Autotuner Demonstration Script

Target length: four minutes and thirty seconds

## Preparation

1. Use the final Radeon run configuration.
2. Confirm that the terminal shows the Radeon identity and ROCm tools.
3. Clear unrelated windows and notifications.
4. Set the dashboard browser window beside the terminal.
5. Record at a resolution that keeps terminal metrics readable.
6. Prepare the stock preset and the final winning preset.

## Scene 1

Time: 0:00 to 0:25

Visual: Title card, Radeon workstation or Radeon Cloud dashboard, then the Autotuner poster.

Narration:

Every team deploying private local AI needs performance engineering. Autotuner is a local agent that performs that work on an AMD Radeon GPU. The model studies its own serving performance, chooses controlled experiments, and makes its own deployment faster.

## Scene 2

Time: 0:25 to 0:55

Visual: Run hardware inspection.

```bash
autotuner inspect artifacts/final_radeon_run/hardware.json
```

Narration:

The entire workflow runs locally. Autotuner first records the Radeon GPU, GFX target, ROCm tools, vLLM version, and host environment so every result has a reproducible hardware identity.

## Scene 3

Time: 0:55 to 1:25

Visual: Open `configs/radeon.json`. Highlight the model variants, attention backends, cache dtype, sequence values, memory values, workload, and acceptance limits.

Narration:

This JSON file is the experiment contract. It defines exactly what the agent may change and what must remain fixed. The model cannot write commands. It may select only a candidate that the controller has already validated.

## Scene 4

Time: 1:25 to 2:35

Visual: Start or replay the recorded terminal run.

```bash
autotuner tune configs/radeon.json artifacts/final_radeon_run
```

Narration:

Autotuner establishes the stock baseline, warms the endpoint, sends the fixed request workload, and measures throughput, p95 latency, errors, response validity, power, GPU use, and memory. Selected trials also run with `rocprofv3`.

After each measurement, the model currently running on the Radeon reads the history and chooses the next bounded experiment. Here it predicts that changing the attention backend can improve throughput. Here it tries a more aggressive memory and sequence configuration. This candidate is rejected because it violates the reliability limit, but the agent recovers and continues.

On screen callouts:

1. Current hypothesis
2. Output tokens per second
3. P95 latency
4. Acceptance decision
5. Local Radeon inference source

## Scene 5

Time: 2:35 to 3:20

Visual: Open `dashboard.html`. Scroll through the experiment timeline and winning candidate.

Narration:

The result is not a mystery command. Every candidate remains visible, including failures. The dashboard compares the baseline with the strongest accepted result and explains every change in the winning configuration.

Replace these placeholders after the verified run:

Baseline throughput: `BASELINE_TOKENS_PER_SECOND`

Winning throughput: `WINNING_TOKENS_PER_SECOND`

Measured improvement: `IMPROVEMENT_PERCENT`

Winning p95 latency: `WINNING_P95_MS`

## Scene 6

Time: 3:20 to 3:55

Visual: Open `best_preset.json`, `engineering_report.md`, telemetry, and one profiler output file.

Narration:

Autotuner exports a preset that can be committed beside the application, a report for human review, and raw evidence for verification. This makes every tuning run reusable rather than anecdotal.

## Scene 7

Time: 3:55 to 4:30

Visual: Return to the title card with GEAK and Autotuner scope comparison.

Narration:

AMD GEAK shows what agent driven optimization can do for Instinct kernels and serving workloads. Autotuner brings a complementary product experience to private local inference on Radeon. It focuses on bounded deployment tuning, consumer memory limits, reproducible presets, and a clear user experience. The agent runs on the Radeon, tunes the Radeon, and leaves behind evidence that another developer can reproduce.

Closing text:

Autotuner

Private Radeon performance engineering in a box

## Recording checklist

1. Show real Radeon hardware identity.
2. Show local vLLM inference.
3. Show one local model hypothesis.
4. Show at least one accepted candidate.
5. Show one rejected candidate and recovery.
6. Show baseline and winning throughput.
7. Show p95 latency and quality limits.
8. Show the final preset.
9. Show the report and profiler evidence.
10. Keep the final video between three and five minutes.
