# Track 2 — Amaresh Hebbar — TrueNorth

**Source repository:** https://github.com/onenot8/TrueNorth
**Application demonstrated:** KisanSathi (bundled sample — AI farm advisor)

## What this submission shows

TrueNorth is an existing, actively developed open-source AI agent framework
(1,282 passing tests, PyPI/NPM/Go SDKs). This submission demonstrates local,
cost-free inference on an AMD Radeon GPU via ROCm, using TrueNorth's built-in
`LocalLLMClient` provider (no framework code changes required — only a
goal-level YAML routing config).

## Files in this folder

- `PROJECT_SPECIFICATION.md` — full write-up: architecture, ROCm deployment,
  benchmark (cloud vs local routing), reproduction steps
- `llm_routing_block.yaml` — the exact config added to route inference to a
  local vLLM/ROCm endpoint
- `conversation_transcript.txt` — real end-to-end session log against the
  local Radeon-served model, including the generated JSON advisory
- `vllm_server.log` — vLLM server log from the AMD Radeon Cloud instance
  (ROCm 7.2.1, gfx1100, Qwen2.5-7B-Instruct)

## Headline result

Same TrueNorth engine, same goal, same conversation — only the LLM routing
target changed:

| Routing | Latency (turn 1) | Cost |
|---|---|---|
| Cloud (default chain) | 85,406 ms | API-metered |
| Local ROCm (Qwen2.5-7B, vLLM, Radeon) | 2,073 ms | $0.0000 |

~41x latency reduction, $0 marginal inference cost.

## Reproduce

See `PROJECT_SPECIFICATION.md` §7 for full setup steps against
https://github.com/onenot8/TrueNorth.
