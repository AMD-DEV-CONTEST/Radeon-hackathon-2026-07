# Product specification

- Level: S1
- Status: implemented

## Goal

Provide a safe performance profile for Qwen3.6 35B project-report generation on a single AMD Radeon GPU without changing the evidence-first workflow or rule-owned task status.

## Behaviour

- A model request has a 384-token completion cap for concise task explanations.
- The application waits up to 90 seconds for local 35B structured output instead of falling back after 15 seconds.
- Each retrieved evidence excerpt sent to the explanation model is limited to 180 characters, while the original evidence and report citations remain unchanged.
- Deployment guidance recommends a 16K chat context for ordinary project reports and keeps a documented 32K fallback for long-document work.
- The benchmark tool calls separate chat and embedding endpoints and records current ROCm metrics.

## Acceptance criteria

- A normal structured task explanation includes an explicit `max_tokens` cap.
- Long local-model responses are not prematurely treated as unavailable after 15 seconds.
- The benchmark command can target the cloud's ports 8000 and 8080 independently.
- Status calculation, evidence links, and downloaded reports retain their prior behavior.
