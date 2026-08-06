# rocm-autopilot

**An autonomous agent that optimizes its own LLM deployment on AMD Radeon GPUs: measured, not assumed.**

> Act II of [gemma-autopilot (Gemma²)](https://github.com/wilfred-dore/gemma-autopilot), the Apache-2.0 agent built in one day at the Build with Gemma Hackathon Paris. Same agent, new silicon: the loop now drives vLLM-ROCm, reads energy through amdsmi, and reports a carbon label per configuration.

Status: pre-hackathon port scaffold. Numbers, port notes and the demo video land during the AMD AI DevMaster sprint (Aug 6, 2026).

## The loop

Benchmark a live deployment → read tokens/s, TTFT, joules/token → diagnose the bottleneck in plain language → act through native function calling → re-benchmark until gains flatten. Guardrails: whitelisted tools, bounded ranges, readable rejections the agent adapts to. Every unavailable sensor or blocked lever is reported honestly.

## Port status (NVIDIA → ROCm)

| Module | State |
|---|---|
| `autopilot/agent.py` (function-calling loop) | inherited, engine-agnostic |
| `autopilot/bench_runner.py` (vllm bench serve) | inherited; knob parity to verify on vLLM-ROCm |
| `autopilot/power.py` (energy telemetry) | TO PORT: NVML → amdsmi/rocm-smi with documented fallbacks |
| `autopilot/tools.py` + guardrails | inherited; backend whitelist to remap |
| Carbon label (gCO2e / 1,000 tokens, A→G) | NEW in Act II |
| Serving-backend lever (vLLM-ROCm, llama.cpp-HIP, MAX) | NEW in Act II |

## License

Apache-2.0 (same as the parent project).
