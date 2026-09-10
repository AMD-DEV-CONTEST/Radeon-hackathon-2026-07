Document ID: RP-KB-003
Revision: 1.0
Classification: competition-public

# Inference Speed Optimisation Policy

Every optimisation RadeonPilot proposes must be grounded in measured evidence and
must never fabricate a number. The policy below drives the Optimization Analyst.

## Baseline first

Capture a baseline profile before touching any flag. The baseline uses the default
launch command and records time-to-first-token (TTFT), decode tokens-per-second,
end-to-end latency, and peak VRAM across a fixed prompt set.

## Ordered levers

1. Prefix caching: enable `--enable-prefix-caching` so the shared system prompt and
   policy preamble are reused across specialist sessions.
2. Chunked prefill: enable `--enable-chunked-prefill` to overlap prefill and decode
   under concurrent agent load.
3. Bounded context: cap `--max-model-len` and truncate evidence packs to the tokens
   the task actually needs.
4. Compact output: force specialist JSON schemas with small max_tokens so decode
   time stays low.
5. Parallel specialists: run the four specialist agents concurrently against one
   batched endpoint instead of sequentially.
6. Quantization: only after the quality gate passes, compare a Q4_K_M GGUF profile.

## Reporting rules

- Report before/after numbers from the same prompt set and same hardware.
- Mark any number not produced by the benchmark runner as absent, never estimated.
- A change that lowers quality below the frozen gate must be rolled back.

## Multi-turn value

Persistent Pi sessions reuse the incident context, so follow-up questions such as
"what if the endpoint OOMs under double concurrency?" replan from memory instead of
re-deriving the whole environment, which is both faster and more consistent.
