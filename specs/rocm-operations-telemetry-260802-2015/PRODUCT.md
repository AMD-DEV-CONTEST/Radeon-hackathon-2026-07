# Product specification

- Level: S1
- Status: implemented

## Goal

Make the system-administrator operations panel show live, meaningful model and AMD GPU utilization while a project report is running.

## Behaviour

- The page refreshes operations telemetry every five seconds while it is visible, in addition to the manual refresh action.
- AMD Radeon deployments show VRAM used/total, GPU utilization, and edge temperature when ROCm SMI provides them.
- A reachable llama.cpp server shows its model identifier and context size instead of an unavailable placeholder.
- Cache values remain request-cache metrics: they only change after reusable requests occur, and are not GPU-memory counters.

## Acceptance criteria

- Current ROCm SMI byte-based JSON output is rendered as non-zero VRAM data.
- The model name and context size are populated from llama.cpp's OpenAI-compatible model endpoint.
- The operations page refreshes without a full page reload and does not show a loading blank during background updates.
